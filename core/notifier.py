"""Email 通知模組 — 使用 Gmail SMTP 發送報告"""

import os
import re
import socket
import smtplib
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email import encoders
from pathlib import Path
from urllib.parse import urlparse

from dotenv import load_dotenv

from core.logger import setup_logger

logger = setup_logger("notifier")

# Gmail SMTP 設定
SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 587


def send_report_email(report_path: str, subject: str | None = None) -> bool:
    """
    寄送報告 Email。

    Parameters
    ----------
    report_path : str
        報告檔案路徑（.md 檔）
    subject : str | None
        郵件主旨，None 則自動從檔名產生

    Returns
    -------
    bool
        寄送成功回 True，失敗回 False
    """
    load_dotenv()
    sender = os.getenv("EMAIL_SENDER")
    password = os.getenv("EMAIL_APP_PASSWORD")
    recipients_str = os.getenv("EMAIL_RECIPIENTS")

    # 任一環境變數缺失 → 靜默跳過（不中斷排程）
    if not all([sender, password, recipients_str]):
        logger.warning("Email 環境變數未設定，跳過寄送")
        return False

    recipients = [r.strip() for r in recipients_str.split(",") if r.strip()]
    if not recipients:
        logger.warning("EMAIL_RECIPIENTS 為空，跳過寄送")
        return False

    # 讀取報告
    report = Path(report_path)
    if not report.exists():
        logger.error(f"報告檔案不存在: {report_path}")
        return False

    content = report.read_text(encoding="utf-8")

    # 自動主旨
    if subject is None:
        stem = report.stem  # e.g. "daily_pick_2026-03-04"
        date_str = stem.replace("daily_pick_", "")
        subject = f"每日選股報告 — {date_str}"

    # Markdown → HTML（簡易轉換）
    html_body = _markdown_to_html(content)

    # 組裝 Email（mixed 容器 → alternative 內文 + 附件）
    msg = MIMEMultipart("mixed")
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = ", ".join(recipients)

    # 內文（alternative: 純文字 + HTML）
    body_part = MIMEMultipart("alternative")
    body_part.attach(MIMEText(content, "plain", "utf-8"))
    body_part.attach(MIMEText(html_body, "html", "utf-8"))
    msg.attach(body_part)

    # 附件（原始 .md 檔）
    attachment = MIMEBase("application", "octet-stream")
    attachment.set_payload(content.encode("utf-8"))
    encoders.encode_base64(attachment)
    attachment.add_header(
        "Content-Disposition", "attachment", filename=report.name
    )
    msg.attach(attachment)

    # 寄送
    success = _send_smtp(msg, sender, password, recipients)
    if success:
        logger.info(f"報告 Email 已寄送至 {recipients}")
    return success


def _send_smtp(msg, sender: str, password: str, recipients: list[str]) -> bool:
    """共用 SMTP 寄送邏輯"""
    proxy_url = os.getenv("EMAIL_PROXY")
    try:
        if proxy_url:
            server = _smtp_via_proxy(proxy_url)
        else:
            server = smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=30)

        with server:
            server.starttls()
            server.login(sender, password)
            server.sendmail(sender, recipients, msg.as_string())
        return True
    except Exception as e:
        logger.error(f"SMTP 寄送失敗: {e}")
        return False


def send_alert_email(subject: str, body: str, severity: str = "warning") -> bool:
    """
    寄送告警 Email（純文字，無附件）。

    Parameters
    ----------
    subject : str
        告警主旨（自動加上嚴重等級前綴）
    body : str
        告警內容（純文字）
    severity : str
        "info" / "warning" / "critical"
    """
    load_dotenv()
    sender = os.getenv("EMAIL_SENDER")
    password = os.getenv("EMAIL_APP_PASSWORD")
    recipients_str = os.getenv("EMAIL_RECIPIENTS")

    if not all([sender, password, recipients_str]):
        logger.warning("Email 環境變數未設定，跳過告警")
        return False

    recipients = [r.strip() for r in recipients_str.split(",") if r.strip()]
    if not recipients:
        return False

    prefix = {"info": "[INFO]", "warning": "[WARNING]", "critical": "[CRITICAL]"}
    full_subject = f"{prefix.get(severity, '[ALERT]')} {subject}"

    msg = MIMEMultipart("alternative")
    msg["Subject"] = full_subject
    msg["From"] = sender
    msg["To"] = ", ".join(recipients)
    msg.attach(MIMEText(body, "plain", "utf-8"))

    success = _send_smtp(msg, sender, password, recipients)
    if success:
        logger.info(f"告警 Email 已寄送: {full_subject}")
    return success


def _smtp_via_proxy(proxy_url: str) -> smtplib.SMTP:
    """透過 HTTP CONNECT proxy 建立 SMTP 連線"""
    parsed = urlparse(proxy_url)
    proxy_host = parsed.hostname or "127.0.0.1"
    proxy_port = parsed.port or 7890

    logger.info(f"透過 proxy {proxy_host}:{proxy_port} 連線 SMTP")

    # HTTP CONNECT tunnel
    sock = socket.create_connection((proxy_host, proxy_port), timeout=30)
    connect_req = (
        f"CONNECT {SMTP_HOST}:{SMTP_PORT} HTTP/1.1\r\n"
        f"Host: {SMTP_HOST}:{SMTP_PORT}\r\n\r\n"
    )
    sock.sendall(connect_req.encode())
    response = sock.recv(4096).decode()
    status_line = response.split("\r\n")[0]
    if "200" not in status_line:
        sock.close()
        raise ConnectionError(f"Proxy CONNECT 失敗: {status_line}")

    # 用 tunnel socket 建立 SMTP
    smtp = smtplib.SMTP(timeout=30)
    smtp._host = SMTP_HOST
    smtp.sock = sock
    smtp.file = sock.makefile("rb")
    # 讀取 SMTP banner
    code, msg = smtp.getreply()
    if code != 220:
        raise smtplib.SMTPConnectError(code, msg)
    smtp.ehlo()
    return smtp


def _markdown_to_html(md_text: str) -> str:
    """將 Markdown 轉為簡易 HTML（用 Python 內建能力，不額外裝套件）"""
    html = md_text

    # 標題
    html = re.sub(r"^### (.+)$", r"<h3>\1</h3>", html, flags=re.MULTILINE)
    html = re.sub(r"^## (.+)$", r"<h2>\1</h2>", html, flags=re.MULTILINE)
    html = re.sub(r"^# (.+)$", r"<h1>\1</h1>", html, flags=re.MULTILINE)
    # 粗體
    html = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", html)
    # 列表
    html = re.sub(r"^- (.+)$", r"<li>\1</li>", html, flags=re.MULTILINE)
    # Markdown 表格 → HTML table
    html = _convert_tables(html)
    # 分隔線
    html = re.sub(r"^---+$", "<hr>", html, flags=re.MULTILINE)
    # 段落（連續空行）
    html = html.replace("\n\n", "</p><p>")

    return (
        '<html><body style="font-family: -apple-system, Arial, sans-serif;'
        ' max-width: 800px; margin: 0 auto; padding: 20px;">'
        f"<p>{html}</p>"
        "</body></html>"
    )


def _convert_tables(text: str) -> str:
    """將 Markdown 表格轉為 HTML table"""
    lines = text.split("\n")
    result = []
    in_table = False
    header_done = False

    for line in lines:
        stripped = line.strip()
        # 偵測表格行（至少有一個 | 且開頭是 |）
        if stripped.startswith("|") and stripped.endswith("|"):
            cells = [c.strip() for c in stripped.split("|")[1:-1]]

            # 跳過分隔行（如 |---|---|---| ）
            if all(re.match(r"^[-:]+$", c) for c in cells):
                continue

            if not in_table:
                result.append(
                    '<table style="border-collapse: collapse; width: 100%;">'
                )
                in_table = True
                header_done = False

            if not header_done:
                # 第一行當作表頭
                result.append("<tr>")
                for c in cells:
                    result.append(
                        f'<th style="border: 1px solid #ddd; padding: 8px;'
                        f' background: #f5f5f5;">{c}</th>'
                    )
                result.append("</tr>")
                header_done = True
            else:
                result.append("<tr>")
                for c in cells:
                    result.append(
                        f'<td style="border: 1px solid #ddd;'
                        f' padding: 8px;">{c}</td>'
                    )
                result.append("</tr>")
        else:
            if in_table:
                result.append("</table>")
                in_table = False
                header_done = False
            result.append(line)

    if in_table:
        result.append("</table>")

    return "\n".join(result)
