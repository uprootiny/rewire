(ns rewire.rules
  "Rewire rule evaluation: schedule and alert-path constraint checking.

   All evaluations return evidence-based results."
  (:require [clojure.data.json :as json]
            [rewire.db :as db]))

;; ============================================================
;; Parameter parsing
;; ============================================================

(defn parse-schedule-params
  "Parse schedule-type parameters."
  [params-json]
  (let [obj (json/read-str params-json :key-fn keyword)]
    {:max-runtime-s (or (:max_runtime_s obj) 0)
     :min-spacing-s (or (:min_spacing_s obj) 0)
     :allow-overlap (boolean (:allow_overlap obj))}))

(defn parse-alertpath-params
  "Parse alert-path parameters."
  [params-json]
  (let [obj (json/read-str params-json :key-fn keyword)]
    {:ack-window-s (:ack_window_s obj)
     :test-interval-s (:test_interval_s obj)}))

(defn parse-params
  "Parse type-specific parameters from JSON."
  [exp-type params-json]
  (case exp-type
    "schedule" (parse-schedule-params params-json)
    "alert_path" (parse-alertpath-params params-json)
    (throw (ex-info "Unknown expectation type" {:type exp-type}))))

;; ============================================================
;; Schedule evaluation
;; ============================================================

(defn- find-obs
  "Find first observation matching predicate."
  [obs-rows pred]
  (first (filter pred obs-rows)))

(defn schedule-evaluate
  "Evaluate schedule constraints against observations.

   Args:
     exp-row: Expectation row from database
     obs-rows-desc: Observations sorted by observed_at DESC (newest first)

   Returns:
     Map with :violations (list of [code message evidence]) and :close-codes"
  [exp-row obs-rows-desc]
  (let [params (parse-params "schedule" (:params_json exp-row))
        expected (:expected_interval_s exp-row)
        tol (:tolerance_s exp-row)
        t (db/now-i)
        violations (atom [])
        close-codes (atom [])]

    ;; Find most recent start
    (when-let [last-start (find-obs obs-rows-desc #(= (:kind %) "start"))]
      (let [start-t (:observed_at last-start)
            age (- t start-t)]

        ;; Check: missed execution
        (if (> age (+ expected tol))
          (swap! violations conj
                 ["missed"
                  (format "Expected a start within %ds (+%ds); last start was %ds ago."
                          expected tol age)
                  {:last_start_at start-t :age_s age
                   :expected_s expected :tolerance_s tol}])
          (swap! close-codes conj "missed"))

        ;; Find end after this start
        (let [newer-end (find-obs obs-rows-desc
                                  #(and (= (:kind %) "end")
                                        (>= (:observed_at %) start-t)))]
          (if (nil? newer-end)
            ;; Job may still be running
            (let [run-for (- t start-t)]
              (if (and (pos? (:max-runtime-s params))
                       (> run-for (:max-runtime-s params)))
                (swap! violations conj
                       ["longrun"
                        (format "Run exceeded max_runtime_s=%d; running for %ds."
                                (:max-runtime-s params) run-for)
                        {:start_at start-t :running_for_s run-for
                         :max_runtime_s (:max-runtime-s params)}])
                (swap! close-codes conj "longrun"))

              ;; Check overlap
              (when-not (:allow-overlap params)
                (let [starts (filter #(= (:kind %) "start") obs-rows-desc)]
                  (if (and (> (count starts) 1)
                           (< (:observed_at (second starts)) start-t))
                    (swap! violations conj
                           ["overlap"
                            "Detected overlapping runs."
                            {:newest_start_at start-t
                             :other_start_at (:observed_at (second starts))}])
                    (swap! close-codes conj "overlap")))))

            ;; Job completed
            (do
              (swap! close-codes conj "longrun" "overlap")

              ;; Check spacing
              (when (pos? (:min-spacing-s params))
                (when-let [prev-end (find-obs obs-rows-desc
                                              #(and (= (:kind %) "end")
                                                    (< (:observed_at %) start-t)))]
                  (let [gap (- start-t (:observed_at prev-end))]
                    (if (< gap (:min-spacing-s params))
                      (swap! violations conj
                             ["spacing"
                              (format "Start occurred %ds after previous end; min_spacing_s=%d."
                                      gap (:min-spacing-s params))
                              {:gap_s gap :min_spacing_s (:min-spacing-s params)
                               :prev_end_at (:observed_at prev-end) :start_at start-t}])
                      (swap! close-codes conj "spacing"))))))))))

    {:violations @violations
     :close-codes (vec (distinct @close-codes))}))

;; ============================================================
;; Alert path evaluation
;; ============================================================

(defn alertpath-should-send-test?
  "Determine if it's time to send a synthetic alert test."
  [exp-row last-any-obs-time]
  (let [params (parse-params "alert_path" (:params_json exp-row))]
    (or (nil? last-any-obs-time)
        (>= (- (db/now-i) last-any-obs-time) (:test-interval-s params)))))
