import smtplib
import ssl
import uuid
from email.message import EmailMessage
from email.utils import formatdate
from ..db import utcnow
from ..schemas import Preferences


class DeliveryService:
    def __init__(self, db, settings, smtp_factory=None):
        self.db, self.settings = db, settings
        self.smtp_factory = smtp_factory or smtplib.SMTP

    def enqueue(self, user_id, digest_id, preferences):
        digest = self.db.one("SELECT * FROM digests WHERE id=? AND user_id=?", (digest_id, user_id))
        if not digest:
            raise ValueError("Digest not found")
        with self.db.connect() as conn:
            for channel, enabled in (("in_app", preferences.in_app_enabled), ("email", preferences.email_enabled)):
                if enabled:
                    conn.execute("INSERT OR IGNORE INTO deliveries(id,user_id,digest_id,channel,status,created_at) "
                                 "VALUES(?,?,?,?,?,?)", (uuid.uuid4().hex, user_id, digest_id, channel, "pending", utcnow()))
        return self.db.all("SELECT id,channel,status,error FROM deliveries WHERE digest_id=?", (digest_id,))

    def deliver_pending(self):
        rows = self.db.all("SELECT * FROM deliveries WHERE status='pending' ORDER BY created_at LIMIT 20")
        for row in rows:
            current = self.db.one("SELECT data FROM preferences WHERE user_id=?", (row["user_id"],))
            preferences = Preferences.model_validate_json(current["data"])
            enabled = preferences.in_app_enabled if row["channel"] == "in_app" else preferences.email_enabled
            if not enabled:
                self.db.execute("UPDATE deliveries SET status='cancelled',error='Channel disabled before delivery' WHERE id=? AND status='pending'", (row["id"],))
                continue
            if row["channel"] == "in_app":
                self._in_app(row)
            else:
                self._email(row)

    def _in_app(self, row):
        with self.db.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            fresh = conn.execute("SELECT status FROM deliveries WHERE id=?", (row["id"],)).fetchone()
            if fresh[0] != "pending":
                return
            title = conn.execute("SELECT title FROM digests WHERE id=?", (row["digest_id"],)).fetchone()[0]
            conn.execute("INSERT OR IGNORE INTO notifications VALUES(?,?,?,?,?,NULL)",
                         (uuid.uuid4().hex, row["user_id"], row["digest_id"], title, utcnow()))
            conn.execute("UPDATE deliveries SET status='sent',sent_at=? WHERE id=?", (utcnow(), row["id"]))

    def _email(self, row):
        if not self.settings.smtp_host or not self.settings.smtp_from:
            self.db.execute("UPDATE deliveries SET status='failed',error='SMTP is not configured' WHERE id=? AND status='pending'", (row["id"],))
            return
        if not self.db.execute("UPDATE deliveries SET status='sending' WHERE id=? AND status='pending'", (row["id"],)):
            return
        digest = self.db.one("SELECT * FROM digests WHERE id=? AND user_id=?", (row["digest_id"], row["user_id"]))
        user = self.db.one("SELECT email FROM users WHERE id=?", (row["user_id"],))
        smtp, submitted = None, False
        try:
            message = EmailMessage()
            message["Subject"] = digest["title"].replace("\n", " ").replace("\r", " ")
            message["From"], message["To"] = self.settings.smtp_from, user["email"]
            message["Date"] = formatdate(localtime=False)
            message["Message-ID"] = f"<{row['id']}@daily-ai-news-agent.local>"
            message.set_content(digest["markdown"])
            smtp = self.smtp_factory(self.settings.smtp_host, self.settings.smtp_port, timeout=15)
            smtp.ehlo()
            if self.settings.smtp_starttls:
                smtp.starttls(context=ssl.create_default_context())
                smtp.ehlo()
            if self.settings.smtp_user:
                smtp.login(self.settings.smtp_user, self.settings.smtp_password)
            submitted = True
            smtp.send_message(message)
            self.db.execute("UPDATE deliveries SET status='sent',sent_at=?,error=NULL WHERE id=?", (utcnow(), row["id"]))
        except Exception as exc:
            # Once send_message starts, a dropped acknowledgement is ambiguous. Never auto-resend.
            self.db.execute("UPDATE deliveries SET status=?,error=? WHERE id=?",
                            ("uncertain" if submitted else "failed", type(exc).__name__, row["id"]))
        finally:
            if smtp:
                try:
                    smtp.quit()
                except Exception:
                    pass
