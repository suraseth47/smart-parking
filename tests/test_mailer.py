"""อีเมลคำเชิญ: เนื้อหาถูกต้อง, escape ข้อมูลจากผู้ใช้, แจ้ง error เป็นภาษาไทย"""
import pytest

from core.config import SmtpSettings
from core.mailer import MailError, build_invite_email, send_email

URL = "https://125.26.22.145:8010/invite/abc123"


def _invite(**kw):
    args = dict(url=URL, recipient_name="สมชาย", role_label="เจ้าหน้าที่",
                permission_labels=["สถานะช่องจอดสด", "รายงานและสถิติ"], expires_text="26 ต.ค. 2569 16:34 น.",
                message=None, is_reset=False)
    args.update(kw)
    return build_invite_email(**args)


def test_invite_email_has_link_role_and_menus():
    mail = _invite()
    assert "คำเชิญ" in mail.subject
    for part in (URL, "เจ้าหน้าที่", "สถานะช่องจอดสด", "26 ต.ค. 2569"):
        assert part in mail.text and part in mail.html


def test_user_supplied_text_is_escaped_in_html():
    mail = _invite(recipient_name="<script>x</script>", message='<img src=x onerror="alert(1)">')
    assert "<script>" not in mail.html and "<img" not in mail.html
    assert "&lt;script&gt;" in mail.html


def test_reset_email_mentions_username():
    mail = _invite(is_reset=True, username="somchai")
    assert "รหัสผ่านใหม่" in mail.subject and "somchai" in mail.text


def test_send_without_config_raises_thai_error():
    cfg = SmtpSettings(host="", port=587, user="", password="", from_address="", security="starttls")
    with pytest.raises(MailError, match="ยังไม่ได้ตั้งค่า"):
        send_email(cfg, "a@example.com", _invite())


def test_unreachable_server_gives_thai_error():
    cfg = SmtpSettings(host="127.0.0.1", port=1, user="", password="", from_address="a@example.com", security="none")
    with pytest.raises(MailError, match="เชื่อมต่อ"):
        send_email(cfg, "b@example.com", _invite())
