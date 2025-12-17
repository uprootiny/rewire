(ns rewire.notify
  "Email notification via SMTP."
  (:import [java.util Properties]
           [javax.mail Message Message$RecipientType Session Transport]
           [javax.mail.internet InternetAddress MimeMessage]))

(defn make-notifier
  "Create a notifier configuration.
   Set :host to nil for dev mode (print-only)."
  [{:keys [host port user password from-email]}]
  {:host host
   :port (or port 587)
   :user user
   :password password
   :from-email from-email})

(defn send-email!
  "Send an email. In dev mode (no host), prints instead."
  [{:keys [host port user password from-email]} to-email subject body]
  (if (nil? host)
    ;; Dev mode: print
    (println (format "--- EMAIL to=%s\nSUBJ: %s\n\n%s\n---" to-email subject body))
    ;; Real mode: SMTP
    (let [props (doto (Properties.)
                  (.put "mail.smtp.host" host)
                  (.put "mail.smtp.port" (str port))
                  (.put "mail.smtp.auth" (str (boolean (and user password))))
                  (.put "mail.smtp.starttls.enable" "true"))
          session (if (and user password)
                    (Session/getInstance props
                                         (proxy [javax.mail.Authenticator] []
                                           (getPasswordAuthentication []
                                             (javax.mail.PasswordAuthentication. user password))))
                    (Session/getInstance props))
          msg (doto (MimeMessage. session)
                (.setFrom (InternetAddress. from-email))
                (.addRecipient Message$RecipientType/TO (InternetAddress. to-email))
                (.setSubject subject)
                (.setText body))]
      (Transport/send msg))))
