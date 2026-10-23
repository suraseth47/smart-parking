"""ส่งอีเมลคำเชิญ/ลิงก์ตั้งรหัสผ่านใหม่ผ่าน SMTP (ใช้ smtplib ที่มากับ Python ไม่ต้องติดตั้งเพิ่ม)

แยกเป็น 2 ส่วน:
- build_*_email(): สร้างหัวข้อ + เนื้อหา (ข้อความล้วน และ HTML) — pure function ทดสอบได้
- send_email(): ส่งจริงผ่าน SMTP แล้วแปลง error เป็นภาษาไทยที่ผู้ดูแลเข้าใจ
"""
from __future__ import annotations

import html
import smtplib
import socket
import ssl
from dataclasses import dataclass
from email.message import EmailMessage
from email.utils import formatdate, make_msgid

from core.config import SmtpSettings

SMTP_TIMEOUT_SECONDS = 15
BRAND = "NASLINK Smart Parking"


class MailError(Exception):
    """ส่งอีเมลไม่สำเร็จ — ข้อความเป็นภาษาไทยพร้อมแสดงให้ผู้ดูแล"""


@dataclass
class MailContent:
    subject: str
    text: str
    html: str


def build_invite_email(
    *, url: str, recipient_name: str | None, role_label: str, permission_labels: list[str],
    expires_text: str, message: str | None, is_reset: bool, username: str | None = None,
) -> MailContent:
    """อีเมลคำเชิญ (หรือลิงก์ตั้งรหัสผ่านใหม่) — ข้อมูลทุกอย่างจากผู้ใช้ถูก escape ก่อนใส่ HTML"""
    greet = f"เรียน คุณ{recipient_name}" if recipient_name else "สวัสดีครับ/ค่ะ"
    if is_reset:
        subject = f"ลิงก์ตั้งรหัสผ่านใหม่ - {BRAND}"
        intro = f"มีการขอตั้งรหัสผ่านใหม่ของบัญชี {username or ''} ในระบบ Smart Parking (หลังบ้าน)"
        button = "ตั้งรหัสผ่านใหม่"
        details: list[str] = ["ถ้าคุณไม่ได้ขอ ให้เพิกเฉยอีเมลนี้ รหัสผ่านเดิมยังใช้ได้"]
    else:
        subject = f"คำเชิญเข้าใช้งานระบบ {BRAND}"
        intro = f"คุณได้รับเชิญให้เข้าใช้งานระบบ Smart Parking (หลังบ้าน) ในบทบาท {role_label}"
        button = "ตั้งค่าบัญชีของฉัน"
        details = [f"เมนูที่ใช้ได้: {', '.join(permission_labels)}"] if permission_labels else []
    note = f"ข้อความจากผู้ดูแลระบบ: {message}" if message else ""
    footer = [
        f"ลิงก์ใช้ได้ครั้งเดียว ถึง {expires_text}",
        'ครั้งแรกเบราว์เซอร์อาจเตือนเรื่องใบรับรอง ให้กด "ขั้นสูง" แล้ว "ดำเนินการต่อ"',
    ]

    text_lines = [greet, "", intro, *details]
    if note:
        text_lines += ["", note]
    text_lines += ["", f"{button}: {url}", "", *footer, "", BRAND]
    text = "\n".join(text_lines)

    esc = html.escape
    detail_html = "".join(f'<p style="margin:0 0 8px;color:#475467;">{esc(d)}</p>' for d in details)
    note_html = (
        f'<p style="margin:16px 0;padding:10px 12px;background:#ecfdf3;border:1px solid #bbf7d0;'
        f'border-radius:8px;color:#166534;white-space:pre-line;">{esc(note)}</p>' if note else ""
    )
    footer_html = "".join(f'<p style="margin:0 0 4px;font-size:13px;color:#667085;">{esc(f)}</p>' for f in footer)
    body = f"""<!DOCTYPE html>
<html lang="th"><body style="margin:0;padding:24px;background:#f5f7fb;font-family:Tahoma,'Leelawadee UI',sans-serif;color:#1e2532;">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0"><tr><td align="center">
<table role="presentation" width="560" cellpadding="0" cellspacing="0" style="max-width:560px;background:#ffffff;border:1px solid #e4e8f0;border-radius:14px;">
<tr><td style="padding:20px 24px;border-bottom:1px solid #e4e8f0;font-weight:700;font-size:16px;color:#2f6bec;">NASLINK <span style="color:#667085;font-weight:400;">Smart Parking</span></td></tr>
<tr><td style="padding:24px;">
<p style="margin:0 0 12px;font-size:15px;">{esc(greet)}</p>
<p style="margin:0 0 12px;font-size:15px;">{esc(intro)}</p>
{detail_html}{note_html}
<p style="margin:20px 0;"><a href="{esc(url, quote=True)}" style="display:inline-block;background:#2f6bec;color:#ffffff;text-decoration:none;padding:12px 22px;border-radius:10px;font-weight:700;">{esc(button)}</a></p>
<p style="margin:0 0 16px;font-size:12px;color:#667085;word-break:break-all;">หรือคัดลอกลิงก์: {esc(url)}</p>
{footer_html}
</td></tr></table>
<p style="font-size:12px;color:#98a2b3;margin-top:12px;">อีเมลนี้ส่งอัตโนมัติจาก {BRAND} กรุณาอย่าตอบกลับ</p>
</td></tr></table></body></html>"""
    return MailContent(subject=subject, text=text, html=body)


def build_test_email() -> MailContent:
    text = f"อีเมลทดสอบจาก {BRAND}\n\nถ้าได้รับอีเมลนี้ แปลว่าการตั้งค่าส่งอีเมล (SMTP) ใช้งานได้แล้ว"
    body = (
        '<div style="font-family:Tahoma,sans-serif;padding:16px;">'
        f"<p><b>อีเมลทดสอบจาก {BRAND}</b></p>"
        "<p>ถ้าได้รับอีเมลนี้ แปลว่าการตั้งค่าส่งอีเมล (SMTP) ใช้งานได้แล้ว</p></div>"
    )
    return MailContent(subject=f"ทดสอบการส่งอีเมล - {BRAND}", text=text, html=body)


def send_email(cfg: SmtpSettings, to_address: str, content: MailContent) -> None:
    """ส่งอีเมล 1 ฉบับ — โยน MailError (ข้อความภาษาไทย) ถ้าไม่สำเร็จ"""
    if not cfg.configured:
        raise MailError("ยังไม่ได้ตั้งค่าการส่งอีเมล (SMTP_HOST / SMTP_FROM ในไฟล์ .env)")

    msg = EmailMessage()
    msg["Subject"] = content.subject
    msg["From"] = cfg.from_address
    msg["To"] = to_address
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid(domain=(cfg.from_address.rsplit("@", 1)[-1].strip(" >") or None))
    msg.set_content(content.text)
    msg.add_alternative(content.html, subtype="html")

    context = ssl.create_default_context()
    try:
        if cfg.security == "ssl":
            server = smtplib.SMTP_SSL(cfg.host, cfg.port, timeout=SMTP_TIMEOUT_SECONDS, context=context)
        else:
            server = smtplib.SMTP(cfg.host, cfg.port, timeout=SMTP_TIMEOUT_SECONDS)
        with server:
            server.ehlo()
            if cfg.security == "starttls":
                server.starttls(context=context)
                server.ehlo()
            if cfg.user:
                server.login(cfg.user, cfg.password)
            server.send_message(msg)
    except smtplib.SMTPAuthenticationError as exc:
        raise MailError(
            "ล็อกอินบัญชีอีเมลผู้ส่งไม่สำเร็จ ตรวจ SMTP_USER / SMTP_PASSWORD "
            "(Gmail ต้องใช้ App Password ไม่ใช่รหัสผ่านปกติ)"
        ) from exc
    except smtplib.SMTPRecipientsRefused as exc:
        raise MailError(f"เซิร์ฟเวอร์อีเมลไม่รับอีเมลผู้รับ {to_address} ตรวจว่าอีเมลถูกต้อง") from exc
    except smtplib.SMTPSenderRefused as exc:
        raise MailError("เซิร์ฟเวอร์อีเมลไม่ยอมให้ส่งในนามผู้ส่งนี้ ตรวจ SMTP_FROM ให้ตรงกับบัญชีที่ใช้") from exc
    except smtplib.SMTPNotSupportedError as exc:
        raise MailError("เซิร์ฟเวอร์อีเมลไม่รองรับวิธีเชื่อมต่อนี้ ลองตั้ง SMTP_SECURITY เป็น ssl หรือ starttls") from exc
    except ssl.SSLError as exc:
        raise MailError("เชื่อมต่อแบบเข้ารหัสไม่สำเร็จ ตรวจ SMTP_PORT กับ SMTP_SECURITY (587=starttls, 465=ssl)") from exc
    except (socket.timeout, TimeoutError) as exc:
        raise MailError(f"เชื่อมต่อ {cfg.host}:{cfg.port} ไม่ทันเวลา ตรวจชื่อเซิร์ฟเวอร์ พอร์ต หรือ firewall") from exc
    except smtplib.SMTPException as exc:
        raise MailError(f"ส่งอีเมลไม่สำเร็จ: {exc}") from exc
    except OSError as exc:
        raise MailError(f"เชื่อมต่อเซิร์ฟเวอร์อีเมล {cfg.host}:{cfg.port} ไม่ได้ ({exc.strerror or exc})") from exc
