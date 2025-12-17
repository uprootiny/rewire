(ns rewire.db-test
  (:require [clojure.test :refer :all]
            [rewire.db :as db])
  (:import [java.io File]))

(defn temp-db []
  (let [f (File/createTempFile "rewire-test" ".db")]
    (.deleteOnExit f)
    (.getAbsolutePath f)))

(deftest test-expectation-lifecycle
  (let [db-path (temp-db)
        conn (db/connect db-path)]
    (db/init-db! conn)

    (testing "create and get expectation"
      (db/create-expectation! conn
                              {:exp-id "e1"
                               :exp-type "schedule"
                               :name "test-job"
                               :expected-interval-s 3600
                               :tolerance-s 300
                               :params-json "{}"
                               :owner-email "test@example.com"})
      (let [row (db/get-expectation conn "e1")]
        (is (some? row))
        (is (= "test-job" (:name row)))
        (is (= "schedule" (:type row)))
        (is (= 1 (:is_enabled row)))))

    (testing "get nonexistent returns nil"
      (is (nil? (db/get-expectation conn "does-not-exist"))))

    (testing "enable and disable"
      (db/set-enabled! conn "e1" false)
      (is (= 0 (:is_enabled (db/get-expectation conn "e1"))))
      (db/set-enabled! conn "e1" true)
      (is (= 1 (:is_enabled (db/get-expectation conn "e1")))))

    (.close conn)))

(deftest test-observations
  (let [db-path (temp-db)
        conn (db/connect db-path)]
    (db/init-db! conn)
    (db/create-expectation! conn
                            {:exp-id "obs1"
                             :exp-type "schedule"
                             :name "obs-job"
                             :expected-interval-s 60
                             :tolerance-s 0
                             :params-json "{}"
                             :owner-email "test@example.com"})

    (testing "add and retrieve observations"
      (db/add-observation! conn "obs1" "start" nil)
      (db/add-observation! conn "obs1" "end" nil)
      (let [obs (db/recent-observations conn "obs1" 10)]
        (is (= 2 (count obs)))
        ;; Newest first
        (is (= "end" (:kind (first obs))))
        (is (= "start" (:kind (second obs))))))

    (testing "last observation time"
      (is (some? (db/last-observation-time conn "obs1")))
      (is (some? (db/last-observation-time conn "obs1" "start"))))

    (.close conn)))

(deftest test-trials
  (let [db-path (temp-db)
        conn (db/connect db-path)]
    (db/init-db! conn)
    (db/create-expectation! conn
                            {:exp-id "trial1"
                             :exp-type "alert_path"
                             :name "trial-path"
                             :expected-interval-s 3600
                             :tolerance-s 0
                             :params-json "{\"ack_window_s\":300,\"test_interval_s\":3600}"
                             :owner-email "test@example.com"})

    (testing "create and ack trial"
      (db/create-trial! conn "t1" "trial1" "{}")
      (is (= 1 (count (db/pending-trials conn "trial1"))))
      (is (true? (db/ack-trial! conn "t1")))
      (is (= 0 (count (db/pending-trials conn "trial1"))))
      (is (false? (db/ack-trial! conn "t1"))))

    (testing "expire trial"
      (db/create-trial! conn "t2" "trial1" "{}")
      (db/expire-trial! conn "t2")
      (is (= 0 (count (db/pending-trials conn "trial1")))))

    (.close conn)))

(deftest test-violations
  (let [db-path (temp-db)
        conn (db/connect db-path)]
    (db/init-db! conn)
    (db/create-expectation! conn
                            {:exp-id "viol1"
                             :exp-type "schedule"
                             :name "viol-job"
                             :expected-interval-s 60
                             :tolerance-s 0
                             :params-json "{}"
                             :owner-email "test@example.com"})

    (testing "create and query violation"
      (db/create-violation! conn "viol1" "missed" "Job missed" "{}")
      (let [v (db/open-violation conn "viol1" "missed")]
        (is (some? v))
        (is (= "missed" (:code v)))))

    (testing "close violation"
      (db/close-violations! conn "viol1" ["missed"])
      (is (nil? (db/open-violation conn "viol1" "missed"))))

    (.close conn)))
