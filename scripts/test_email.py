"""Cloud Run Email 寄送測試腳本"""
import sys
import smtplib
import os
from email.mime.text import MIMEText

try:
    sender = os.getenv("EMAIL_SENDER")
    pwd = os.getenv("EMAIL_APP_PASSWORD")
    rcpt = os.getenv("EMAIL_RECIPIENTS")
    print(f"sender={sender}", file=sys.stderr)
    print(f"pwd_len={len(pwd) if pwd else 0}", file=sys.stderr)
    print(f"rcpt={rcpt}", file=sys.stderr)

    msg = MIMEText("Cloud Run Email 寄送測試成功！", "plain", "utf-8")
    msg["Subject"] = "[測試] Cloud Run Email 功能驗證"
    msg["From"] = sender
    msg["To"] = rcpt

    print("Connecting SMTP...", file=sys.stderr)
    srv = smtplib.SMTP("smtp.gmail.com", 587, timeout=30)
    srv.starttls()
    print("Logging in...", file=sys.stderr)
    srv.login(sender, pwd)
    print("Sending...", file=sys.stderr)
    srv.sendmail(sender, rcpt.split(","), msg.as_string())
    srv.quit()
    print("EMAIL SENT OK", file=sys.stderr)
except Exception as e:
    print(f"FAILED: {type(e).__name__}: {e}", file=sys.stderr)
    sys.exit(1)
