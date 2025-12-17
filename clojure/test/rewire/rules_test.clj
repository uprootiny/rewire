(ns rewire.rules-test
  (:require [clojure.test :refer :all]
            [rewire.rules :as rules]
            [rewire.db :as db])
  (:import [java.io File]))

(defn temp-db []
  (let [f (File/createTempFile "rewire-test" ".db")]
    (.deleteOnExit f)
    (.getAbsolutePath f)))

(deftest test-parse-params
  (testing "schedule params"
    (let [p (rules/parse-params "schedule" "{\"max_runtime_s\":300,\"min_spacing_s\":60,\"allow_overlap\":true}")]
      (is (= 300 (:max-runtime-s p)))
      (is (= 60 (:min-spacing-s p)))
      (is (true? (:allow-overlap p)))))

  (testing "schedule defaults"
    (let [p (rules/parse-params "schedule" "{}")]
      (is (= 0 (:max-runtime-s p)))
      (is (= 0 (:min-spacing-s p)))
      (is (false? (:allow-overlap p)))))

  (testing "alertpath params"
    (let [p (rules/parse-params "alert_path" "{\"ack_window_s\":900,\"test_interval_s\":86400}")]
      (is (= 900 (:ack-window-s p)))
      (is (= 86400 (:test-interval-s p)))))

  (testing "unknown type throws"
    (is (thrown? Exception (rules/parse-params "unknown" "{}")))))

(deftest test-schedule-evaluate
  (let [db-path (temp-db)
        conn (db/connect db-path)]
    (db/init-db! conn)

    (testing "no observations => no violations"
      (db/create-expectation! conn
                              {:exp-id "sched1"
                               :exp-type "schedule"
                               :name "job1"
                               :expected-interval-s 60
                               :tolerance-s 0
                               :params-json "{}"
                               :owner-email "test@example.com"})
      (let [exp (db/get-expectation conn "sched1")
            {:keys [violations]} (rules/schedule-evaluate exp [])]
        (is (empty? violations))))

    (testing "old start triggers missed"
      ;; Insert an old observation directly
      (db/execute! conn
                   "INSERT INTO observations (expectation_id, kind, observed_at, meta_json)
                    VALUES (?, ?, ?, ?)"
                   "sched1" "start" 1 nil)
      (let [exp (db/get-expectation conn "sched1")
            obs (db/recent-observations conn "sched1" 10)
            {:keys [violations]} (rules/schedule-evaluate exp obs)
            codes (map first violations)]
        (is (some #(= "missed" %) codes))))

    (.close conn)))

(deftest test-alertpath-should-send
  (let [db-path (temp-db)
        conn (db/connect db-path)]
    (db/init-db! conn)
    (db/create-expectation! conn
                            {:exp-id "ap1"
                             :exp-type "alert_path"
                             :name "path1"
                             :expected-interval-s 3600
                             :tolerance-s 0
                             :params-json "{\"ack_window_s\":300,\"test_interval_s\":60}"
                             :owner-email "test@example.com"})

    (testing "should send if no previous observations"
      (let [exp (db/get-expectation conn "ap1")]
        (is (true? (rules/alertpath-should-send-test? exp nil)))))

    (.close conn)))
