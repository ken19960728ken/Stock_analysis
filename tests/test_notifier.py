"""core/notifier.py 單元測試"""

import smtplib
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from core.notifier import _convert_tables, _markdown_to_html, send_report_email


# ---------------------------------------------------------------------------
# send_report_email
# ---------------------------------------------------------------------------


class TestSendReportEmail:
    """send_report_email 測試"""

    def test_missing_env_vars_returns_false(self, tmp_path):
        """環境變數缺失時回傳 False，不噴錯"""
        report = tmp_path / "test.md"
        report.write_text("# Test", encoding="utf-8")

        with patch.dict(
            "os.environ",
            {"EMAIL_SENDER": "", "EMAIL_APP_PASSWORD": "", "EMAIL_RECIPIENTS": ""},
            clear=False,
        ):
            # 確保 dotenv 不會覆蓋
            with patch("core.notifier.load_dotenv"):
                result = send_report_email(str(report))
        assert result is False

    def test_partial_env_vars_returns_false(self, tmp_path):
        """只設定部分環境變數時也回傳 False"""
        report = tmp_path / "test.md"
        report.write_text("# Test", encoding="utf-8")

        with patch.dict(
            "os.environ",
            {
                "EMAIL_SENDER": "a@b.com",
                "EMAIL_APP_PASSWORD": "",
                "EMAIL_RECIPIENTS": "c@d.com",
            },
            clear=False,
        ):
            with patch("core.notifier.load_dotenv"):
                result = send_report_email(str(report))
        assert result is False

    def test_empty_recipients_returns_false(self, tmp_path):
        """EMAIL_RECIPIENTS 為空字串（只有逗號）時回傳 False"""
        report = tmp_path / "test.md"
        report.write_text("# Test", encoding="utf-8")

        with patch.dict(
            "os.environ",
            {
                "EMAIL_SENDER": "a@b.com",
                "EMAIL_APP_PASSWORD": "pass",
                "EMAIL_RECIPIENTS": ", , ",
            },
            clear=False,
        ):
            with patch("core.notifier.load_dotenv"):
                result = send_report_email(str(report))
        assert result is False

    def test_report_not_found_returns_false(self):
        """報告檔案不存在時回傳 False"""
        with patch.dict(
            "os.environ",
            {
                "EMAIL_SENDER": "a@b.com",
                "EMAIL_APP_PASSWORD": "pass",
                "EMAIL_RECIPIENTS": "c@d.com",
            },
            clear=False,
        ):
            with patch("core.notifier.load_dotenv"):
                result = send_report_email("/nonexistent/path.md")
        assert result is False

    def test_successful_send(self, tmp_path):
        """正常寄送流程（mock SMTP，無 proxy）"""
        report = tmp_path / "daily_pick_2026-03-04.md"
        report.write_text("# 每日選股\n\n測試內容", encoding="utf-8")

        with patch.dict(
            "os.environ",
            {
                "EMAIL_SENDER": "sender@gmail.com",
                "EMAIL_APP_PASSWORD": "apppass",
                "EMAIL_RECIPIENTS": "r1@gmail.com, r2@gmail.com",
                "EMAIL_PROXY": "",
            },
            clear=False,
        ):
            with patch("core.notifier.load_dotenv"):
                with patch("core.notifier.smtplib.SMTP") as mock_cls:
                    server = mock_cls.return_value
                    server.__enter__ = MagicMock(return_value=server)
                    server.__exit__ = MagicMock(return_value=False)
                    result = send_report_email(str(report))

        assert result is True
        mock_cls.assert_called_once_with("smtp.gmail.com", 587, timeout=30)
        server.starttls.assert_called_once()
        server.login.assert_called_once_with("sender@gmail.com", "apppass")
        server.sendmail.assert_called_once()
        # 確認收件人
        call_args = server.sendmail.call_args
        assert call_args[0][0] == "sender@gmail.com"
        assert call_args[0][1] == ["r1@gmail.com", "r2@gmail.com"]

    def test_auto_subject_from_filename(self, tmp_path):
        """自動從檔名產生主旨"""
        report = tmp_path / "daily_pick_2026-03-04.md"
        report.write_text("test", encoding="utf-8")

        with patch.dict(
            "os.environ",
            {
                "EMAIL_SENDER": "a@b.com",
                "EMAIL_APP_PASSWORD": "pass",
                "EMAIL_RECIPIENTS": "c@d.com",
                "EMAIL_PROXY": "",
            },
            clear=False,
        ):
            with patch("core.notifier.load_dotenv"):
                with patch("core.notifier.smtplib.SMTP") as mock_cls:
                    server = mock_cls.return_value
                    server.__enter__ = MagicMock(return_value=server)
                    server.__exit__ = MagicMock(return_value=False)
                    result = send_report_email(str(report))

        assert result is True
        # Subject 含中文會被 MIME base64 編碼，解碼後驗證
        from email import message_from_string
        from email.header import decode_header

        msg_str = server.sendmail.call_args[0][2]
        msg = message_from_string(msg_str)
        decoded_parts = decode_header(msg["Subject"])
        subject = "".join(
            part.decode(enc) if enc else (part if isinstance(part, str) else part.decode())
            for part, enc in decoded_parts
        )
        assert "2026-03-04" in subject

    def test_custom_subject(self, tmp_path):
        """自訂主旨"""
        report = tmp_path / "test.md"
        report.write_text("test", encoding="utf-8")

        with patch.dict(
            "os.environ",
            {
                "EMAIL_SENDER": "a@b.com",
                "EMAIL_APP_PASSWORD": "pass",
                "EMAIL_RECIPIENTS": "c@d.com",
                "EMAIL_PROXY": "",
            },
            clear=False,
        ):
            with patch("core.notifier.load_dotenv"):
                with patch("core.notifier.smtplib.SMTP") as mock_cls:
                    server = mock_cls.return_value
                    server.__enter__ = MagicMock(return_value=server)
                    server.__exit__ = MagicMock(return_value=False)
                    result = send_report_email(
                        str(report), subject="Custom Subject"
                    )

        assert result is True
        msg_str = server.sendmail.call_args[0][2]
        assert "Custom Subject" in msg_str

    def test_smtp_error_returns_false(self, tmp_path):
        """SMTP 連線失敗時回傳 False，不噴錯"""
        report = tmp_path / "test.md"
        report.write_text("test", encoding="utf-8")

        with patch.dict(
            "os.environ",
            {
                "EMAIL_SENDER": "a@b.com",
                "EMAIL_APP_PASSWORD": "pass",
                "EMAIL_RECIPIENTS": "c@d.com",
                "EMAIL_PROXY": "",
            },
            clear=False,
        ):
            with patch("core.notifier.load_dotenv"):
                with patch(
                    "core.notifier.smtplib.SMTP",
                    side_effect=smtplib.SMTPAuthenticationError(535, b"Auth failed"),
                ):
                    result = send_report_email(str(report))

        assert result is False


# ---------------------------------------------------------------------------
# _markdown_to_html
# ---------------------------------------------------------------------------


class TestMarkdownToHtml:
    """_markdown_to_html 簡易轉換測試"""

    def test_headings(self):
        md = "# H1\n## H2\n### H3"
        html = _markdown_to_html(md)
        assert "<h1>H1</h1>" in html
        assert "<h2>H2</h2>" in html
        assert "<h3>H3</h3>" in html

    def test_bold(self):
        html = _markdown_to_html("**粗體**")
        assert "<strong>粗體</strong>" in html

    def test_list(self):
        html = _markdown_to_html("- item1\n- item2")
        assert "<li>item1</li>" in html
        assert "<li>item2</li>" in html

    def test_hr(self):
        html = _markdown_to_html("---")
        assert "<hr>" in html

    def test_wraps_in_html(self):
        html = _markdown_to_html("hello")
        assert "<html>" in html
        assert "</html>" in html


# ---------------------------------------------------------------------------
# _convert_tables
# ---------------------------------------------------------------------------


class TestConvertTables:
    """Markdown 表格 → HTML table 轉換"""

    def test_basic_table(self):
        md = "| A | B |\n|---|---|\n| 1 | 2 |\n| 3 | 4 |"
        html = _convert_tables(md)
        assert "<table" in html
        assert "<th" in html
        assert "<td" in html
        # 表頭
        assert ">A<" in html
        assert ">B<" in html
        # 資料
        assert ">1<" in html
        assert ">4<" in html

    def test_no_table(self):
        """無表格的文字不受影響"""
        text = "hello world\nfoo bar"
        result = _convert_tables(text)
        assert result == text

    def test_table_closes_properly(self):
        """表格後接普通文字時正確關閉 </table>"""
        md = "| A |\n|---|\n| 1 |\nsome text"
        html = _convert_tables(md)
        assert "</table>" in html
        assert "some text" in html
