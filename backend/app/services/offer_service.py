"""Offer letters: templates, drafts, sending (PDF + email) and candidate responses.

A sent offer is immutable: editing it creates a new draft revision
(``revision_of_id``) so the historical letter the candidate received is kept.
"""

from __future__ import annotations

import json
import re
import secrets
from datetime import datetime, timedelta
from typing import Optional

from fastapi import HTTPException
from sqlalchemy.orm import Session

from .. import models
from . import config, credits_service, files, hiring_context as ctx
from .email_service import EmailService
from .notification_service import notify
from .pdf_service import letter_pdf

PLACEHOLDERS = ("candidate_name", "candidate_email", "company_name", "job_title", "department", "joining_date",
                "ctc_amount", "location", "offer_date", "reporting_manager", "employment_type",
                "probation_period", "notice_period", "working_hours", "benefits", "hr_name", "hr_designation",
                "acceptance_deadline")
# Values the server always fills itself (never typed by HR).
AUTO_FIELDS = ("acceptance_deadline",)
MAX_CUSTOM_FIELDS = 40
REQUIRED_TO_SEND = ("joining_date", "ctc_amount")
OFFERABLE_STATUSES = ("assessed", "shortlisted", "scheduled", "interviewed", "selected", "offered")
_TOKEN = re.compile(r"\{\{\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*\}\}")


def placeholders_in(template: str) -> list[str]:
    seen: list[str] = []
    for key in _TOKEN.findall(template or ""):
        if key not in seen:
            seen.append(key)
    return seen


def _clean_fields(fields: Optional[dict], template: str) -> dict:
    """Accept built-in placeholders plus any custom {{key}} used in this letter."""
    allowed = set(PLACEHOLDERS) | set(placeholders_in(template)[:MAX_CUSTOM_FIELDS])
    out = {}
    for k, v in (fields or {}).items():
        if k in allowed and k not in AUTO_FIELDS and isinstance(k, str):
            out[k] = "" if v is None else str(v)[:2000]
    return out

DEFAULT_TEMPLATE = """Date: {{offer_date}}

To,
{{candidate_name}}

# Offer of Employment: {{job_title}}

Dear {{candidate_name}},

We are delighted to offer you the position of **{{job_title}}** in the {{department}} team at {{company_name}}. We were impressed by your profile and believe you will make a strong contribution to the team.

# Position details
- Designation: {{job_title}}
- Department: {{department}}
- Employment type: {{employment_type}}
- Work location: {{location}}
- Reporting manager: {{reporting_manager}}
- Date of joining: {{joining_date}}

# Compensation
- Annual cost to company (CTC): {{ctc_amount}}
- Benefits: {{benefits}}

# Terms
- Probation period: {{probation_period}}
- Notice period: {{notice_period}}
- Working hours: {{working_hours}}

This offer is contingent upon satisfactory verification of your documents and references. Please accept this offer through your Hirelune dashboard by {{acceptance_deadline}}.

We look forward to welcoming you to {{company_name}}.

---
**Warm regards,**
{{hr_name}}
{{hr_designation}}
{{company_name}}
"""


_OLD_DEFAULT_MARKER = "Your annual compensation (CTC) will be {{ctc_amount}}, subject to applicable statutory deductions."


def ensure_default_template(db: Session) -> models.OfferTemplate:
    row = db.query(models.OfferTemplate).filter(models.OfferTemplate.hr_account_id.is_(None)).first()
    if row is None:
        row = models.OfferTemplate(hr_account_id=None, name="Standard offer letter", content=DEFAULT_TEMPLATE)
        db.add(row)
        db.commit()
        db.refresh(row)
    elif _OLD_DEFAULT_MARKER in (row.content or ""):
        row.content = DEFAULT_TEMPLATE          # upgrade the untouched built-in letter to the new layout
        db.commit()
    return row


def render(template: str, values: dict) -> tuple[str, list[str]]:
    missing: list[str] = []

    def sub(m):
        key = m.group(1)
        val = values.get(key)
        if val is None or str(val).strip() == "":
            if key not in missing:
                missing.append(key)
            return m.group(0)
        return str(val)
    return _TOKEN.sub(sub, template or ""), missing


def default_fields(db: Session, app: models.Application, valid_days: Optional[int] = None) -> dict:
    job = app.job
    hr = ctx.hr_for_job(db, job)
    hp = db.query(models.HRProfile).filter(models.HRProfile.account_id == hr.account_id).first() if hr else None
    days = valid_days or config.OFFER_VALID_DAYS
    return {
        "candidate_name": app.candidate.name if app.candidate else "",
        "candidate_email": app.candidate.email if app.candidate else "",
        "company_name": ctx.company_name(db, hr),
        "job_title": job.title if job else "",
        "department": (job.team if job else None) or "",
        "location": (job.location if job else None) or "",
        "offer_date": datetime.utcnow().strftime("%d %B %Y"),
        "employment_type": "Full-time",
        "joining_date": "", "ctc_amount": "", "reporting_manager": "",
        "probation_period": "6 months", "notice_period": "30 days", "working_hours": "Monday to Friday, 9:30 AM to 6:30 PM",
        "benefits": "Health insurance, paid leave and statutory benefits as per company policy",
        "hr_name": hr.name if hr else "HR Team", "hr_designation": (hp.designation if hp and hp.designation else "Human Resources"),
        "acceptance_deadline": (datetime.utcnow() + timedelta(days=days)).strftime("%d %B %Y"),
    }


def _fields(offer: models.OfferLetter) -> dict:
    try:
        return json.loads(offer.fields or "{}")
    except ValueError:
        return {}


def _ensure_not_accepted(db: Session, app: models.Application) -> None:
    accepted = (db.query(models.OfferLetter)
                .filter(models.OfferLetter.application_id == app.application_id,
                        models.OfferLetter.status == "accepted").first())
    if accepted or app.status == "hired":
        raise HTTPException(status_code=409, detail="The candidate has already accepted an offer for this application")


def create_draft(db: Session, hr_id: Optional[int], app: models.Application, template_id: Optional[int],
                 template_content: Optional[str], fields: dict) -> models.OfferLetter:
    if app.status not in OFFERABLE_STATUSES:
        raise HTTPException(status_code=409, detail="Offers can be created for assessed, shortlisted or interviewed candidates")
    _ensure_not_accepted(db, app)
    template = None
    if template_id:
        template = db.get(models.OfferTemplate, template_id)
        if template is None or (template.hr_account_id not in (None, hr_id)):
            raise HTTPException(status_code=404, detail="Template not found")
    content_src = template_content or (template.content if template else ensure_default_template(db).content)
    values = {**default_fields(db, app), **_clean_fields(fields, content_src)}
    content, _ = render(content_src, values)
    offer = models.OfferLetter(application_id=app.application_id, hr_account_id=hr_id,
                               template_id=template.template_id if template else None,
                               template_content=content_src, fields=json.dumps(values), content=content,
                               status="draft", created_at=datetime.utcnow(), updated_at=datetime.utcnow())
    db.add(offer)
    db.commit()
    db.refresh(offer)
    return offer


def update_draft(db: Session, offer: models.OfferLetter, template_content: Optional[str], fields: Optional[dict],
                 valid_days: Optional[int] = None) -> models.OfferLetter:
    if offer.status != "draft":
        raise HTTPException(status_code=409, detail="Only drafts can be edited. Create a revision to change a sent offer.")
    if template_content is not None:
        if len(template_content) > 50_000:
            raise HTTPException(status_code=422, detail="The letter is too long (50,000 characters max)")
        offer.template_content = template_content
    if valid_days is not None:
        offer.valid_days = valid_days
    values = {**_fields(offer), **_clean_fields(fields, offer.template_content)}
    values["acceptance_deadline"] = (datetime.utcnow() + timedelta(days=offer.valid_days or config.OFFER_VALID_DAYS)).strftime("%d %B %Y")
    offer.fields = json.dumps(values)
    offer.content, _ = render(offer.template_content, values)
    offer.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(offer)
    return offer


def revise(db: Session, offer: models.OfferLetter, hr_id: Optional[int]) -> models.OfferLetter:
    if offer.status in ("accepted",):
        raise HTTPException(status_code=409, detail="An accepted offer can't be revised")
    _ensure_not_accepted(db, db.get(models.Application, offer.application_id))
    draft = models.OfferLetter(valid_days=offer.valid_days, application_id=offer.application_id, hr_account_id=hr_id or offer.hr_account_id,
                               template_id=offer.template_id, revision_of_id=offer.offer_id,
                               template_content=offer.template_content, fields=offer.fields, content=offer.content,
                               status="draft", created_at=datetime.utcnow(), updated_at=datetime.utcnow())
    db.add(draft)
    db.commit()
    db.refresh(draft)
    return draft


def send(db: Session, offer: models.OfferLetter, hr_id: Optional[int], acting_role: str) -> list[int]:
    if offer.status != "draft":
        raise HTTPException(status_code=409, detail="This offer has already been sent")
    app = db.get(models.Application, offer.application_id)
    if app is None or app.candidate is None or not app.candidate.email:
        raise HTTPException(status_code=422, detail="The candidate has no email address")
    _ensure_not_accepted(db, app)
    values = _fields(offer)
    days = offer.valid_days or config.OFFER_VALID_DAYS
    values["acceptance_deadline"] = (datetime.utcnow() + timedelta(days=days)).strftime("%d %B %Y")
    values["candidate_email"] = app.candidate.email
    missing = [k for k in REQUIRED_TO_SEND if not str(values.get(k) or "").strip()]
    content, unresolved = render(offer.template_content, values)
    if missing:
        raise HTTPException(status_code=422, detail=f"Fill in before sending: {', '.join(missing)}")
    if unresolved:
        raise HTTPException(status_code=422, detail=f"Unfilled placeholders: {', '.join(unresolved)}")
    if acting_role == "hr" and hr_id:
        credits_service.spend(db, "hr", hr_id, "offer_letter", f"Offer letter — {values.get('candidate_name')}",
                              reference=f"offer:{offer.offer_id}", commit=False)
    # Freeze the final content and render the PDF before committing.
    offer.content = content
    offer.fields = json.dumps(values)
    offer.pdf_path = files.save_bytes(offer_pdf_bytes(db, offer, content, values), "offers", ".pdf")
    offer.view_token = secrets.token_urlsafe(24)
    offer.status, offer.sent_at = "sent", datetime.utcnow()
    offer.expires_at = offer.sent_at + timedelta(days=days)
    offer.email_status = "queued"
    # Older unanswered offers for the same application are superseded, not deleted.
    for older in (db.query(models.OfferLetter)
                  .filter(models.OfferLetter.application_id == offer.application_id,
                          models.OfferLetter.offer_id != offer.offer_id,
                          models.OfferLetter.status.in_(("sent", "viewed"))).all()):
        older.status = "withdrawn"
    app.status = "offered"
    db.commit()
    db.refresh(offer)

    account = ctx.candidate_account_for(db, app.candidate)
    if account:
        notify(db, "candidate", account.account_id, "offer_received", f"Offer received — {values.get('company_name')}",
               f"{values.get('job_title')} · joining {values.get('joining_date')}", f"/offers/{offer.offer_id}")
    log = EmailService.queue(
        db, to=app.candidate.email, subject=f"Offer Letter — {values.get('company_name')}", template="offer_letter",
        context={**values, "expires_on": offer.expires_at.strftime("%d %B %Y"),
                 "link": ctx.link(f"/offers/{offer.offer_id}")},
        related_type="offer", related_id=offer.offer_id,
        recipient_role="candidate", recipient_id=account.account_id if account else None,
        owner_role="hr", owner_id=hr_id, attachment_path=offer.pdf_path,
        attachment_name=f"Offer-{re.sub(r'[^A-Za-z0-9]+', '-', values.get('candidate_name', 'candidate'))}.pdf")
    if log is None:
        offer.email_status = "skipped"
        db.commit()
    return [log.email_id] if log else []


def offer_pdf_bytes(db: Session, offer: models.OfferLetter, content: str, values: dict) -> bytes:
    """Letterhead PDF: company name, website/HQ/email line, formatted body."""
    app = db.get(models.Application, offer.application_id)
    hr = ctx.hr_for_job(db, app.job) if app else None
    company = db.query(models.Company).filter(models.Company.hr_account_id == hr.account_id).first() if hr else None
    name = values.get("company_name") or (company.name if company else "") or "Offer letter"
    head = "  |  ".join(x for x in ((company.website if company else None), (company.headquarters if company else None),
                                    (company.official_email if company else None)) if x)
    return letter_pdf(name, head, content, footer=f"{name}  |  Offer #{offer.offer_id}  |  Confidential")


def preview_pdf(db: Session, offer: models.OfferLetter) -> bytes:
    values = _fields(offer)
    content, _ = render(offer.template_content, values)
    return offer_pdf_bytes(db, offer, content, values)


def mark_viewed(db: Session, offer: models.OfferLetter) -> None:
    if offer.status == "sent":
        offer.status, offer.viewed_at = "viewed", datetime.utcnow()
        db.commit()


def respond(db: Session, offer: models.OfferLetter, decision: str, note: Optional[str]) -> list[int]:
    expire_if_needed(db, offer)
    if offer.status not in ("sent", "viewed"):
        raise HTTPException(status_code=409, detail=f"This offer is {offer.status} and can no longer be answered")
    if decision not in ("accept", "reject"):
        raise HTTPException(status_code=422, detail="decision must be accept or reject")
    now = datetime.utcnow()
    app = db.get(models.Application, offer.application_id)
    if decision == "accept":
        offer.status, offer.accepted_at = "accepted", now
        app.status = "hired"
    else:
        offer.status, offer.rejected_at = "rejected", now
        app.status = "offer_declined"
    offer.response_note = (note or "").strip() or None
    offer.viewed_at = offer.viewed_at or now
    db.commit()
    values = _fields(offer)
    hr = db.get(models.HRAccount, offer.hr_account_id) if offer.hr_account_id else ctx.hr_for_job(db, app.job)
    if not hr:
        return []
    word = "accepted" if decision == "accept" else "declined"
    notify(db, "hr", hr.account_id, f"offer_{word}", f"Offer {word}",
           f"{values.get('candidate_name')} {word} the {values.get('job_title')} offer", f"/hr/offers?offer={offer.offer_id}")
    log = EmailService.queue(db, to=hr.email, subject=f"Offer {word}: {values.get('candidate_name')}",
                             template="offer_response",
                             context={"hr_name": hr.name, "candidate_name": values.get("candidate_name"),
                                      "job_title": values.get("job_title"), "decision": word, "note": offer.response_note,
                                      "responded_at": now.strftime("%d %b %Y %H:%M UTC"),
                                      "link": ctx.link(f"/hr/offers?offer={offer.offer_id}")},
                             related_type="offer", related_id=offer.offer_id,
                             recipient_role="hr", recipient_id=hr.account_id, owner_role="hr", owner_id=hr.account_id)
    return [log.email_id] if log else []


def expire_if_needed(db: Session, offer: models.OfferLetter) -> None:
    if offer.status in ("sent", "viewed") and offer.expires_at and offer.expires_at < datetime.utcnow():
        offer.status = "expired"
        db.commit()


def expire_offers(db: Session) -> int:
    n = (db.query(models.OfferLetter)
         .filter(models.OfferLetter.status.in_(("sent", "viewed")),
                 models.OfferLetter.expires_at.isnot(None),
                 models.OfferLetter.expires_at < datetime.utcnow())
         .update({"status": "expired"}, synchronize_session=False))
    db.commit()
    return n


def offer_dict(db: Session, offer: models.OfferLetter, viewer_role: str) -> dict:
    app = db.get(models.Application, offer.application_id)
    values = _fields(offer)
    out = {
        "offer_id": offer.offer_id, "application_id": offer.application_id, "status": offer.status,
        "candidate_name": values.get("candidate_name") or (app.candidate.name if app and app.candidate else None),
        "candidate_id": app.candidate_id if app else None,
        "job_title": values.get("job_title"), "company_name": values.get("company_name"),
        "joining_date": values.get("joining_date"), "ctc_amount": values.get("ctc_amount"),
        "location": values.get("location"), "content": offer.content, "has_pdf": bool(offer.pdf_path),
        "created_at": offer.created_at, "sent_at": offer.sent_at, "viewed_at": offer.viewed_at,
        "accepted_at": offer.accepted_at, "rejected_at": offer.rejected_at, "expires_at": offer.expires_at,
        "response_note": offer.response_note,
    }
    if viewer_role in ("hr", "admin"):
        _, unresolved = render(offer.template_content, values)
        out.update({"fields": values, "template_content": offer.template_content, "template_id": offer.template_id,
                    "revision_of_id": offer.revision_of_id, "email_status": offer.email_status,
                    "valid_days": offer.valid_days or config.OFFER_VALID_DAYS, "updated_at": offer.updated_at,
                    "unresolved": unresolved, "custom_fields": [k for k in placeholders_in(offer.template_content) if k not in PLACEHOLDERS],
                    "candidate_email": app.candidate.email if app and app.candidate else None})
    return out
