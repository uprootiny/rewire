(ns rewire.server
  "Rewire HTTP server and background checker."
  (:require [clojure.data.json :as json]
            [clojure.string :as str]
            [clojure.tools.cli :refer [parse-opts]]
            [reitit.ring :as ring]
            [ring.adapter.jetty :as jetty]
            [ring.util.response :as resp]
            [rewire.db :as db]
            [rewire.rules :as rules]
            [rewire.notify :as notify])
  (:import [java.security SecureRandom]
           [java.util Base64])
  (:gen-class))

;; ============================================================
;; Utilities
;; ============================================================

(defn token-urlsafe
  "Generate URL-safe random token."
  [n-bytes]
  (let [bytes (byte-array n-bytes)
        _ (.nextBytes (SecureRandom.) bytes)]
    (-> (Base64/getUrlEncoder)
        (.withoutPadding)
        (.encodeToString bytes))))

(defn constant-time-eq?
  "Constant-time string comparison."
  [a b]
  (when (and a b (= (count a) (count b)))
    (zero? (reduce bit-or 0 (map bit-xor (.getBytes a) (.getBytes b))))))

;; ============================================================
;; Handlers
;; ============================================================

(defn text-response [status body]
  (-> (resp/response body)
      (resp/status status)
      (resp/content-type "text/plain; charset=utf-8")))

(defn json-response [status body]
  (-> (resp/response (json/write-str body))
      (resp/status status)
      (resp/content-type "application/json; charset=utf-8")))

(defn parse-form [body]
  (when body
    (->> (str/split (slurp body) #"&")
         (map #(str/split % #"=" 2))
         (filter #(= 2 (count %)))
         (map (fn [[k v]] [(keyword k) (java.net.URLDecoder/decode v "UTF-8")]))
         (into {}))))

(defn auth-admin? [req admin-token]
  (let [auth (get-in req [:headers "authorization"] "")]
    (when (str/starts-with? auth "Bearer ")
      (constant-time-eq? (subs auth 7) admin-token))))

;; Status
(defn handle-status [_req _ctx]
  (text-response 200 "rewire ok\n"))

;; Observe GET
(defn handle-observe-get [req {:keys [conn]}]
  (let [exp-id (get-in req [:path-params :id])
        row (db/get-expectation conn exp-id)]
    (if row
      (let [obs (db/recent-observations conn exp-id 10)]
        (json-response 200
                       {:id (:id row)
                        :type (:type row)
                        :name (:name row)
                        :expected_interval_s (:expected_interval_s row)
                        :tolerance_s (:tolerance_s row)
                        :params (json/read-str (:params_json row))
                        :owner_email (:owner_email row)
                        :is_enabled (= 1 (:is_enabled row))
                        :recent_observations (mapv #(select-keys % [:kind :observed_at :meta_json]) obs)}))
      (text-response 404 "unknown expectation\n"))))

;; Observe POST
(defn handle-observe-post [req {:keys [conn]}]
  (let [exp-id (get-in req [:path-params :id])
        row (db/get-expectation conn exp-id)]
    (if row
      (let [form (parse-form (:body req))
            kind (str/trim (or (:kind form) ""))
            meta-json (:meta form)]
        (if (#{"start" "end" "ping" "ack"} kind)
          (do
            (db/add-observation! conn exp-id kind meta-json)
            (text-response 200 "ok\n"))
          (json-response 400 {:error "kind must be start|end|ping|ack"})))
      (text-response 404 "unknown expectation\n"))))

;; ACK
(defn handle-ack [req {:keys [conn]}]
  (let [trial-id (-> (get-in req [:path-params :id])
                     (str/split #"\?")
                     first)]
    (if (db/ack-trial! conn trial-id)
      (text-response 200 "acked\n")
      (text-response 404 "unknown or not pending\n"))))

;; Admin new
(defn handle-admin-new [req {:keys [conn admin-token base-url]}]
  (if-not (auth-admin? req admin-token)
    (text-response 401 "unauthorized\n")
    (let [form (parse-form (:body req))
          exp-type (str/trim (or (:type form) ""))
          name (str/trim (or (:name form) ""))
          owner-email (str/trim (or (:email form) ""))
          expected (Integer/parseInt (or (:expected_interval_s form) "0"))
          tol (Integer/parseInt (or (:tolerance_s form) "0"))
          params-json (or (:params_json form) "{}")]
      (cond
        (not (#{"schedule" "alert_path"} exp-type))
        (json-response 400 {:error "type must be schedule|alert_path"})

        (or (str/blank? name) (str/blank? owner-email) (< expected 60))
        (json-response 400 {:error "need name,email,expected_interval_s>=60"})

        :else
        (try
          (rules/parse-params exp-type params-json)
          (let [exp-id (token-urlsafe 16)]
            (db/create-expectation! conn
                                    {:exp-id exp-id
                                     :exp-type exp-type
                                     :name name
                                     :expected-interval-s expected
                                     :tolerance-s tol
                                     :params-json params-json
                                     :owner-email owner-email})
            (json-response 200
                           {:id exp-id
                            :observe_url (str (str/replace base-url #"/$" "") "/observe/" exp-id)}))
          (catch Exception e
            (json-response 400 {:error (str "invalid params_json: " (.getMessage e))})))))))

;; Admin enable/disable
(defn handle-admin-enable [enable?]
  (fn [req {:keys [conn admin-token]}]
    (if-not (auth-admin? req admin-token)
      (text-response 401 "unauthorized\n")
      (let [form (parse-form (:body req))
            exp-id (str/trim (or (:id form) ""))]
        (if (str/blank? exp-id)
          (json-response 400 {:error "need id"})
          (do
            (db/set-enabled! conn exp-id enable?)
            (json-response 200 {:ok true :enabled enable?})))))))

;; ============================================================
;; Router
;; ============================================================

(defn make-router [ctx]
  (ring/ring-handler
   (ring/router
    [["/status" {:get #(handle-status % ctx)}]
     ["/observe/:id" {:get #(handle-observe-get % ctx)
                      :post #(handle-observe-post % ctx)}]
     ["/ack/:id" {:get #(handle-ack % ctx)}]
     ["/admin/new" {:post #(handle-admin-new % ctx)}]
     ["/admin/enable" {:post #((handle-admin-enable true) % ctx)}]
     ["/admin/disable" {:post #((handle-admin-enable false) % ctx)}]])))

;; ============================================================
;; Checker
;; ============================================================

(defn notify-violation! [notifier owner name exp-type code msg ev viol-id conn]
  (let [subj (format "[rewire] VIOLATION %s: %s" code name)
        body (str "Rewire detected an expectation violation.\n\n"
                  "Name: " name "\n"
                  "Type: " exp-type "\n"
                  "Code: " code "\n"
                  "Message: " msg "\n\n"
                  "Evidence:\n" (json/write-str ev :indent true) "\n\n"
                  "Rewire reports only mismatches it can justify with evidence.\n")]
    (notify/send-email! notifier owner subj body)
    (db/mark-notified! conn viol-id)))

(defn check-schedule! [exp conn cfg notifier now]
  (let [exp-id (:id exp)
        owner (:owner_email exp)
        name (:name exp)
        obs (db/recent-observations conn exp-id 80)
        {:keys [violations close-codes]} (rules/schedule-evaluate exp obs)]

    (when (seq close-codes)
      (db/close-violations! conn exp-id close-codes))

    (doseq [[code msg ev] violations]
      (let [openv (db/open-violation conn exp-id code)]
        (if (nil? openv)
          (let [vid (db/create-violation! conn exp-id code msg (json/write-str ev))]
            (notify-violation! notifier owner name "schedule" code msg ev vid conn))
          (when (and (pos? (:renotify-after-s cfg))
                     (:last_notified_at openv)
                     (>= (- now (:last_notified_at openv)) (:renotify-after-s cfg)))
            (notify-violation! notifier owner name "schedule" code
                               (:message openv) (json/read-str (:evidence_json openv))
                               (:id openv) conn)))))))

(defn check-alertpath! [exp conn cfg notifier base-url now]
  (let [exp-id (:id exp)
        owner (:owner_email exp)
        name (:name exp)
        last-obs (db/last-observation-time conn exp-id)]

    (when (rules/alertpath-should-send-test? exp last-obs)
      (let [trial-id (token-urlsafe 16)
            ack-url (str (str/replace base-url #"/$" "") "/ack/" trial-id)
            meta-json (json/write-str {:ack_url ack-url :note "synthetic test"})]
        (db/create-trial! conn trial-id exp-id meta-json)
        (db/add-observation! conn exp-id "ping" (json/write-str {:sent_trial trial-id}))
        (notify/send-email! notifier owner
                            (format "[rewire] Alert-path test: %s" name)
                            (str "This is a synthetic Rewire alert-path test.\n\n"
                                 "Path: " name "\n"
                                 "Expectation ID: " exp-id "\n"
                                 "To acknowledge delivery, open this link:\n"
                                 ack-url "\n\n"
                                 "If no ack is received in time, Rewire will open a violation.\n"))))

    ;; Check pending trials for expiry
    (let [params (rules/parse-params "alert_path" (:params_json exp))
          pending (db/pending-trials conn exp-id)]
      (doseq [tr pending]
        (let [age (- now (:sent_at tr))]
          (when (> age (+ (:ack-window-s params) (:tolerance_s exp)))
            (db/expire-trial! conn (:id tr))
            (let [code "no_ack"
                  msg (format "No ACK received within %ds (+%ds)."
                              (:ack-window-s params) (:tolerance_s exp))
                  ev {:trial_id (:id tr) :sent_at (:sent_at tr) :age_s age}
                  openv (db/open-violation conn exp-id code)]
              (when (nil? openv)
                (let [vid (db/create-violation! conn exp-id code msg (json/write-str ev))]
                  (notify-violation! notifier owner name "alert_path" code msg ev vid conn))))))))

    (db/close-violations! conn exp-id ["no_ack"])))

(defn checker-tick! [{:keys [conn notifier cfg]}]
  (let [exps (db/list-enabled-expectations conn)
        now (db/now-i)]
    (doseq [exp exps]
      (try
        (case (:type exp)
          "schedule" (check-schedule! exp conn cfg notifier now)
          "alert_path" (check-alertpath! exp conn cfg notifier (:base-url cfg) now)
          nil)
        (catch Exception e
          (println "[checker] error:" (.getMessage e)))))))

(defn start-checker! [ctx interval-ms]
  (let [running (atom true)]
    (future
      (while @running
        (try
          (checker-tick! ctx)
          (catch Exception e
            (println "[checker] tick error:" (.getMessage e))))
        (Thread/sleep interval-ms)))
    (fn [] (reset! running false))))

;; ============================================================
;; Main
;; ============================================================

(def cli-options
  [[nil "--db DB" "SQLite database path" :required true]
   [nil "--init-db" "Initialize database schema"]
   [nil "--listen ADDR" "Listen address" :default "127.0.0.1"]
   [nil "--port PORT" "Listen port" :default 8080 :parse-fn #(Integer/parseInt %)]
   [nil "--base-url URL" "Public base URL" :required true]
   [nil "--admin-token TOKEN" "Admin API token" :default "dev-admin-token"]
   [nil "--check-every SEC" "Check interval (seconds)" :default 60 :parse-fn #(Integer/parseInt %)]
   [nil "--renotify-after SEC" "Renotify interval (0=disable)" :default 0 :parse-fn #(Integer/parseInt %)]
   [nil "--smtp-host HOST" "SMTP server (nil=dev mode)"]
   [nil "--smtp-port PORT" "SMTP port" :default 587 :parse-fn #(Integer/parseInt %)]
   [nil "--smtp-user USER" "SMTP username"]
   [nil "--smtp-pass PASS" "SMTP password"]
   [nil "--from-email EMAIL" "From address" :default "rewire@localhost"]
   ["-h" "--help"]])

(defn -main [& args]
  (let [{:keys [options errors summary]} (parse-opts args cli-options)]
    (when errors
      (doseq [e errors] (println e))
      (System/exit 1))
    (when (:help options)
      (println "Rewire - Epistemic expectation verifier")
      (println summary)
      (System/exit 0))

    (let [conn (db/connect (:db options))]
      (when (:init-db options)
        (db/init-db! conn)
        (println "db initialized"))

      (let [notifier (notify/make-notifier {:host (:smtp-host options)
                                            :port (:smtp-port options)
                                            :user (:smtp-user options)
                                            :password (:smtp-pass options)
                                            :from-email (:from-email options)})
            cfg {:base-url (:base-url options)
                 :admin-token (:admin-token options)
                 :check-every-s (:check-every options)
                 :renotify-after-s (:renotify-after options)}
            ctx {:conn conn :notifier notifier :cfg cfg
                 :admin-token (:admin-token options)
                 :base-url (:base-url options)}
            handler (make-router ctx)
            stop-checker (start-checker! ctx (* 1000 (:check-every options)))]

        (println (format "rewire listening on %s:%d" (:listen options) (:port options)))
        (jetty/run-jetty handler
                         {:host (:listen options)
                          :port (:port options)
                          :join? true})
        (stop-checker)))))
