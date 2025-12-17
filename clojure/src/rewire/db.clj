(ns rewire.db
  "SQLite-backed storage for Rewire.

   Design principles:
   - Append-only observations (epistemic trail)
   - Violations are facts with evidence pointers
   - WAL mode for concurrent read/write"
  (:require [clojure.data.json :as json])
  (:import [java.sql Connection DriverManager PreparedStatement ResultSet]))

;; ============================================================
;; Time utilities
;; ============================================================

(defn now-i
  "Current Unix timestamp as integer."
  []
  (quot (System/currentTimeMillis) 1000))

;; ============================================================
;; Database connection
;; ============================================================

(defn connect
  "Create a SQLite connection."
  [db-path]
  (Class/forName "org.sqlite.JDBC")
  (doto (DriverManager/getConnection (str "jdbc:sqlite:" db-path))
    (.setAutoCommit true)))

(defn execute!
  "Execute SQL statement with parameters."
  [^Connection conn sql & params]
  (with-open [stmt (.prepareStatement conn sql)]
    (doseq [[i param] (map-indexed vector params)]
      (.setObject stmt (inc i) param))
    (.executeUpdate stmt)))

(defn query
  "Execute query and return results as vector of maps."
  [^Connection conn sql & params]
  (with-open [stmt (.prepareStatement conn sql)]
    (doseq [[i param] (map-indexed vector params)]
      (.setObject stmt (inc i) param))
    (with-open [rs (.executeQuery stmt)]
      (let [meta (.getMetaData rs)
            cols (for [i (range 1 (inc (.getColumnCount meta)))]
                   (keyword (.getColumnName meta i)))]
        (loop [results []]
          (if (.next rs)
            (recur (conj results
                         (zipmap cols
                                 (for [i (range 1 (inc (count cols)))]
                                   (.getObject rs (int i))))))
            results))))))

(defn query-one
  "Execute query and return first result."
  [conn sql & params]
  (first (apply query conn sql params)))

;; ============================================================
;; Schema
;; ============================================================

(def schema
  "CREATE TABLE IF NOT EXISTS expectations (
     id TEXT PRIMARY KEY,
     type TEXT NOT NULL CHECK(type IN ('schedule', 'alert_path')),
     name TEXT NOT NULL,
     expected_interval_s INTEGER NOT NULL CHECK(expected_interval_s >= 60),
     tolerance_s INTEGER NOT NULL DEFAULT 0 CHECK(tolerance_s >= 0),
     params_json TEXT NOT NULL,
     owner_email TEXT NOT NULL,
     is_enabled INTEGER NOT NULL DEFAULT 1 CHECK(is_enabled IN (0, 1)),
     created_at INTEGER NOT NULL,
     updated_at INTEGER NOT NULL
   );

   CREATE TABLE IF NOT EXISTS observations (
     id INTEGER PRIMARY KEY AUTOINCREMENT,
     expectation_id TEXT NOT NULL,
     kind TEXT NOT NULL CHECK(kind IN ('start', 'end', 'ping', 'ack')),
     observed_at INTEGER NOT NULL,
     meta_json TEXT,
     FOREIGN KEY(expectation_id) REFERENCES expectations(id)
   );

   CREATE INDEX IF NOT EXISTS idx_obs_exp_time ON observations(expectation_id, observed_at);

   CREATE TABLE IF NOT EXISTS alert_trials (
     id TEXT PRIMARY KEY,
     expectation_id TEXT NOT NULL,
     sent_at INTEGER NOT NULL,
     acked_at INTEGER,
     status TEXT NOT NULL CHECK(status IN ('pending', 'acked', 'expired')),
     meta_json TEXT,
     FOREIGN KEY(expectation_id) REFERENCES expectations(id)
   );

   CREATE INDEX IF NOT EXISTS idx_trials_exp ON alert_trials(expectation_id);
   CREATE INDEX IF NOT EXISTS idx_trials_status ON alert_trials(status);

   CREATE TABLE IF NOT EXISTS violations (
     id INTEGER PRIMARY KEY AUTOINCREMENT,
     expectation_id TEXT NOT NULL,
     detected_at INTEGER NOT NULL,
     code TEXT NOT NULL,
     message TEXT NOT NULL,
     evidence_json TEXT NOT NULL,
     is_open INTEGER NOT NULL DEFAULT 1 CHECK(is_open IN (0, 1)),
     last_notified_at INTEGER,
     FOREIGN KEY(expectation_id) REFERENCES expectations(id)
   );

   CREATE INDEX IF NOT EXISTS idx_viol_open ON violations(expectation_id, is_open);
   CREATE INDEX IF NOT EXISTS idx_viol_code ON violations(expectation_id, code);")

(defn init-db!
  "Initialize database schema."
  [conn]
  (execute! conn "PRAGMA journal_mode=WAL")
  (doseq [stmt (clojure.string/split schema #";")]
    (when (not (clojure.string/blank? stmt))
      (execute! conn stmt))))

;; ============================================================
;; Expectations
;; ============================================================

(defn create-expectation!
  "Create a new expectation."
  [conn {:keys [exp-id exp-type name expected-interval-s tolerance-s
                params-json owner-email]}]
  (let [t (now-i)]
    (execute! conn
              "INSERT INTO expectations (id, type, name, expected_interval_s, tolerance_s,
                params_json, owner_email, is_enabled, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, ?)"
              exp-id exp-type name expected-interval-s tolerance-s
              params-json owner-email t t)))

(defn get-expectation
  "Get expectation by ID."
  [conn exp-id]
  (query-one conn "SELECT * FROM expectations WHERE id = ?" exp-id))

(defn list-enabled-expectations
  "List all enabled expectations."
  [conn]
  (query conn "SELECT * FROM expectations WHERE is_enabled = 1"))

(defn set-enabled!
  "Enable or disable an expectation."
  [conn exp-id enabled?]
  (execute! conn
            "UPDATE expectations SET is_enabled = ?, updated_at = ? WHERE id = ?"
            (if enabled? 1 0) (now-i) exp-id))

;; ============================================================
;; Observations
;; ============================================================

(defn add-observation!
  "Record an observation. Returns observation ID."
  [conn exp-id kind meta-json]
  (execute! conn
            "INSERT INTO observations (expectation_id, kind, observed_at, meta_json)
             VALUES (?, ?, ?, ?)"
            exp-id kind (now-i) meta-json)
  ;; Get last insert ID
  (:id (query-one conn "SELECT last_insert_rowid() as id")))

(defn recent-observations
  "Get recent observations for an expectation, newest first."
  [conn exp-id limit]
  (query conn
         "SELECT * FROM observations WHERE expectation_id = ?
          ORDER BY observed_at DESC LIMIT ?"
         exp-id limit))

(defn last-observation-time
  "Get timestamp of most recent observation."
  ([conn exp-id]
   (:observed_at (query-one conn
                            "SELECT observed_at FROM observations
                             WHERE expectation_id = ?
                             ORDER BY observed_at DESC LIMIT 1"
                            exp-id)))
  ([conn exp-id kind]
   (:observed_at (query-one conn
                            "SELECT observed_at FROM observations
                             WHERE expectation_id = ? AND kind = ?
                             ORDER BY observed_at DESC LIMIT 1"
                            exp-id kind))))

;; ============================================================
;; Alert Trials
;; ============================================================

(defn create-trial!
  "Create a new alert trial."
  [conn trial-id exp-id meta-json]
  (execute! conn
            "INSERT INTO alert_trials (id, expectation_id, sent_at, acked_at, status, meta_json)
             VALUES (?, ?, ?, NULL, 'pending', ?)"
            trial-id exp-id (now-i) meta-json))

(defn ack-trial!
  "Acknowledge a pending trial. Returns true if acked."
  [conn trial-id]
  (let [row (query-one conn "SELECT status FROM alert_trials WHERE id = ?" trial-id)]
    (if (and row (= (:status row) "pending"))
      (do
        (execute! conn
                  "UPDATE alert_trials SET acked_at = ?, status = 'acked' WHERE id = ?"
                  (now-i) trial-id)
        true)
      false)))

(defn pending-trials
  "Get all pending trials for an expectation."
  [conn exp-id]
  (query conn
         "SELECT * FROM alert_trials WHERE expectation_id = ? AND status = 'pending'"
         exp-id))

(defn expire-trial!
  "Mark a pending trial as expired."
  [conn trial-id]
  (execute! conn
            "UPDATE alert_trials SET status = 'expired' WHERE id = ? AND status = 'pending'"
            trial-id))

;; ============================================================
;; Violations
;; ============================================================

(defn open-violation
  "Get the most recent open violation of a given code."
  [conn exp-id code]
  (query-one conn
             "SELECT * FROM violations
              WHERE expectation_id = ? AND code = ? AND is_open = 1
              ORDER BY detected_at DESC LIMIT 1"
             exp-id code))

(defn create-violation!
  "Create a new violation. Returns violation ID."
  [conn exp-id code message evidence-json]
  (execute! conn
            "INSERT INTO violations
             (expectation_id, detected_at, code, message, evidence_json, is_open, last_notified_at)
             VALUES (?, ?, ?, ?, ?, 1, NULL)"
            exp-id (now-i) code message evidence-json)
  (:id (query-one conn "SELECT last_insert_rowid() as id")))

(defn close-violations!
  "Close open violations matching the given codes."
  [conn exp-id codes]
  (when (seq codes)
    (let [placeholders (clojure.string/join "," (repeat (count codes) "?"))]
      (apply execute! conn
             (str "UPDATE violations SET is_open = 0
                   WHERE expectation_id = ? AND is_open = 1 AND code IN (" placeholders ")")
             exp-id codes))))

(defn mark-notified!
  "Mark a violation as notified."
  [conn viol-id]
  (execute! conn
            "UPDATE violations SET last_notified_at = ? WHERE id = ?"
            (now-i) viol-id))
