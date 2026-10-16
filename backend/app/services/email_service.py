"""SMTP email service.

Flow used everywhere:

    1. The business change (interview, offer, ...) is committed first.
    2. ``EmailService.queue(...)`` renders the template and stores an EmailLog
       row with status ``queued``.
    3. ``dispatch_email(email_id)`` (run as a FastAPI background task, by the
       scheduler, or by a manual retry) sends it and records ``sent`` or
       ``failed`` + the error. A failed email never rolls back the business
       change and can be retried.

Credentials only come from environment variables and are never returned.
"""

from __future__ import annotations

import logging
import mimetypes
import re
import smtplib
import ssl
from datetime import datetime
from email.message import EmailMessage
from email.utils import formataddr
from pathlib import Path
from typing import Any, Optional

from jinja2 import Environment, FileSystemLoader, select_autoescape
from sqlalchemy.orm import Session

from .. import models
from ..database import SessionLocal
from . import config

logger = logging.getLogger(__name__)

TEMPLATE_DIR = Path(__file__).resolve().parents[1] / "templates" / "emails"
_env = Environment(loader=FileSystemLoader(str(TEMPLATE_DIR)), autoescape=select_autoescape(["html"]))

MAX_ATTEMPTS = 3

# Which user preference controls each template (None = always allowed).
TEMPLATE_CATEGORY = {
    "assessment_started": "assessment_notifications",
    "assessment_completed": "assessment_notifications",
    "interview_scheduled": "interview_notifications",
    "interview_updated": "interview_notifications",
    "interview_reminder": "reminder_notifications",
    "offer_letter": "offer_notifications",
    "offer_response": "offer_notifications",
    "application_status": None,
    "verification_status": None,
    "support_ticket": None,
    "test_email": None,
}


def render(template: str, context: dict[str, Any]) -> tuple[str, str]:
    ctx = {"app_name": config.app_name(), "app_url": config.frontend_url(), **context}
    html = _env.get_template(f"{template}.html").render(**ctx)
    return html, html_to_text(html)


def html_to_text(html: str) -> str:
    text = re.sub(r"(?is)<(script|style|head).*?</\1>", "", html)
    text = re.sub(r"(?i)</td>", ": ", text)
    text = re.sub(r"(?i)<br\s*/?>|</p>|</tr>|</h\d>|</li>", "\n", text)
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"&nbsp;", " ", text)
    text = re.sub(r"&amp;", "&", text)
    text = re.sub(r"&lt;", "<", text)
    text = re.sub(r"&gt;", ">", text)
    text = re.sub(r"&#39;|&#x27;", "'", text)
    text = re.sub(r"&quot;|&#34;", '"', text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r":\s*(\n|$)", r"\1", text)
    return re.sub(r"\n\s*\n+", "\n\n", text).strip()


def email_allowed(db: Session, role: Optional[str], account_id: Optional[int], template: str) -> bool:
    """Respect the recipient's notification settings when we know who they are."""
    if not role or not account_id:
        return True
    prefs = (db.query(models.UserSettings)
             .filter(models.UserSettings.role == role, models.UserSettings.account_id == account_id).first())
    if prefs is None:
        return True
    if prefs.email_notifications is False:
        return False
    category = TEMPLATE_CATEGORY.get(template)
    return True if category is None else getattr(prefs, category, True) is not False


class EmailService:
    """Reusable email API used by routes and services."""

    @staticmethod
    def queue(
        db: Session,
        *,
        to: str,
        subject: str,
        template: str,
        context: dict[str, Any],
        related_type: Optional[str] = None,
        related_id: Optional[int] = None,
        recipient_role: Optional[str] = None,
        recipient_id: Optional[int] = None,
        owner_role: Optional[str] = None,
        owner_id: Optional[int] = None,
        attachment_path: Optional[str] = None,
        attachment_name: Optional[str] = None,
    ) -> Optional[models.EmailLog]:
        if not to or "@" not in to:
            logger.warning("Email %s not queued: invalid recipient %r", template, to)
            return None
        if not email_allowed(db, recipient_role, recipient_id, template):
            logger.info("Email %s to %s skipped by recipient preferences", template, to)
            return None
        html, text = render(template, {"subject": subject, **context})
        log = models.EmailLog(
            to_email=to.strip(), subject=subject, template=template, body_html=html, body_text=text,
            attachment_path=attachment_path, attachment_name=attachment_name, status="queued",
            related_type=related_type, related_id=related_id, owner_role=owner_role, owner_id=owner_id,
        )
        db.add(log)
        db.commit()
        db.refresh(log)
        return log

    # Convenience wrappers named in the spec -------------------------------------------------

    @staticmethod
    def send_email(to: str, subject: str, html: str, text: str | None = None,
                   attachment_path: str | None = None, attachment_name: str | None = None) -> None:
        """Send immediately (raises on failure). Prefer queue()+dispatch_email()."""
        _smtp_send(to, subject, html, text or html_to_text(html), attachment_path, attachment_name)

    @staticmethod
    def send_template_email(to: str, subject: str, template: str, context: dict[str, Any]) -> None:
        html, text = render(template, {"subject": subject, **context})
        _smtp_send(to, subject, html, text, None, None)


def _smtp_send(to: str, subject: str, html: str, text: str,
               attachment_path: Optional[str], attachment_name: Optional[str]) -> None:
    s = config.smtp_settings()
    if not config.smtp_configured():
        raise RuntimeError("SMTP is not configured (set SMTP_HOST and SMTP_FROM_EMAIL)")
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = formataddr((s["from_name"], s["from_email"]))
    msg["To"] = to
    msg.set_content(text or " ")
    msg.add_alternative(html, subtype="html")
    if attachment_path and Path(attachment_path).is_file():
        ctype = mimetypes.guess_type(attachment_name or attachment_path)[0] or "application/octet-stream"
        maintype, subtype = ctype.split("/", 1)
        msg.add_attachment(Path(attachment_path).read_bytes(), maintype=maintype, subtype=subtype,
                           filename=attachment_name or Path(attachment_path).name)
    context = ssl.create_default_context()
    if s["use_ssl"]:
        with smtplib.SMTP_SSL(s["host"], s["port"], timeout=s["timeout"], context=context) as server:
            if s["username"]:
                server.login(s["username"], s["password"])
            server.send_message(msg)
    else:
        with smtplib.SMTP(s["host"], s["port"], timeout=s["timeout"]) as server:
            server.ehlo()
            if s["use_tls"]:
                server.starttls(context=context)
                server.ehlo()
            if s["username"]:
                server.login(s["username"], s["password"])
            server.send_message(msg)


def dispatch_email(email_id: int) -> str:
    """Send one queued/failed email in its own DB session. Returns the final status.

    Status is claimed atomically (queued/failed -> sending) so two workers can
    never send the same email twice.
    """
    db = SessionLocal()
    try:
        claimed = (db.query(models.EmailLog)
                   .filter(models.EmailLog.email_id == email_id,
                           models.EmailLog.status.in_(("queued", "failed")))
                   .update({"status": "sending", "attempts": models.EmailLog.attempts + 1},
                           synchronize_session=False))
        db.commit()
        log = db.get(models.EmailLog, email_id)
        if not claimed or log is None:
            return log.status if log else "missing"
        try:
            _smtp_send(log.to_email, log.subject, log.body_html or "", log.body_text or "",
                       log.attachment_path, log.attachment_name)
            log.status, log.sent_at, log.error_message = "sent", datetime.utcnow(), None
        except Exception as exc:  # noqa: BLE001 - recorded for retry
            logger.exception("Email %s to %s failed", email_id, log.to_email)
            log.status, log.error_message = "failed", f"{type(exc).__name__}: {exc}"[:1000]
        db.commit()
        _after_dispatch(db, log)
        return log.status
    finally:
        db.close()


def _after_dispatch(db: Session, log: models.EmailLog) -> None:
    """Mirror delivery state onto the business record where one tracks it."""
    if log.related_type == "offer" and log.related_id:
        offer = db.get(models.OfferLetter, log.related_id)
        if offer:
            offer.email_status = log.status
            db.commit()


def retry_failed_emails(db: Session, limit: int = 20) -> int:
    rows = (db.query(models.EmailLog.email_id)
            .filter(models.EmailLog.status.in_(("queued", "failed")),
                    models.EmailLog.attempts < MAX_ATTEMPTS)
            .order_by(models.EmailLog.email_id).limit(limit).all())
    if not rows or not config.smtp_configured():
        return 0
    return sum(1 for (eid,) in rows if dispatch_email(eid) == "sent")


def send_test_email(to: str) -> dict:
    """Synchronously send a real test email; returns {ok, error}."""
    try:
        EmailService.send_template_email(to, f"{config.app_name()} SMTP test", "test_email",
                                         {"sent_at": datetime.utcnow().strftime("%d %b %Y %H:%M UTC")})
        return {"ok": True, "error": None}
    except Exception as exc:  # noqa: BLE001
        logger.exception("SMTP test email failed")
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


def smtp_status() -> dict:
    s = config.smtp_settings()
    return {"configured": config.smtp_configured(), "host": s["host"] or None, "port": s["port"],
            "from_email": s["from_email"] or None, "use_tls": s["use_tls"], "use_ssl": s["use_ssl"],
            "username_set": bool(s["username"]), "password_set": bool(s["password"])}
