from datetime import datetime
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .. import models
from ..database import get_db
from ..security import (Principal, assert_hr_application_access, candidate_owns, candidate_row_filter, current_user,
                        ensure_verified_hr, hr_can_access_job, require_candidate, require_hr_or_admin)
from ..services import files, offer_service as svc
from ..services.email_service import dispatch_email
from .candidates import _is_unlocked, _mask_email

router = APIRouter(prefix="/offers", tags=["offers"])


# ---- Templates -----------------------------------------------------------------

class TemplateIn(BaseModel):
    name: str = Field(min_length=2, max_length=150)
    content: str = Field(min_length=20)


@router.get("/templates")
def list_templates(user: Principal = Depends(require_hr_or_admin), db: Session = Depends(get_db)):
    svc.ensure_default_template(db)
    q = db.query(models.OfferTemplate)
    if user.role == "hr":
        q = q.filter((models.OfferTemplate.hr_account_id.is_(None)) | (models.OfferTemplate.hr_account_id == user.id))
    return {"placeholders": list(svc.PLACEHOLDERS), "auto_fields": list(svc.AUTO_FIELDS),
            "templates": [{"template_id": t.template_id, "name": t.name, "content": t.content,
                           "built_in": t.hr_account_id is None, "updated_at": t.updated_at}
                          for t in q.order_by(models.OfferTemplate.template_id).all()]}


@router.post("/templates")
def create_template(payload: TemplateIn, user: Principal = Depends(require_hr_or_admin), db: Session = Depends(get_db)):
    t = models.OfferTemplate(hr_account_id=user.id if user.role == "hr" else None, name=payload.name.strip(),
                             content=payload.content)
    db.add(t)
    db.commit()
    db.refresh(t)
    return {"template_id": t.template_id, "name": t.name, "content": t.content, "built_in": t.hr_account_id is None}


def _own_template(db: Session, template_id: int, user: Principal) -> models.OfferTemplate:
    t = db.get(models.OfferTemplate, template_id)
    if t is None or not (user.role == "admin" or t.hr_account_id == user.id):
        raise HTTPException(status_code=404, detail="Template not found (built-in templates can be copied, not edited)")
    return t


@router.put("/templates/{template_id}")
def update_template(template_id: int, payload: TemplateIn, user: Principal = Depends(require_hr_or_admin),
                    db: Session = Depends(get_db)):
    t = _own_template(db, template_id, user)
    t.name, t.content, t.updated_at = payload.name.strip(), payload.content, datetime.utcnow()
    db.commit()
    return {"template_id": t.template_id, "name": t.name, "content": t.content}


@router.delete("/templates/{template_id}")
def delete_template(template_id: int, user: Principal = Depends(require_hr_or_admin), db: Session = Depends(get_db)):
    t = _own_template(db, template_id, user)
    db.query(models.OfferLetter).filter(models.OfferLetter.template_id == t.template_id).update({"template_id": None})
    db.delete(t)
    db.commit()
    return {"deleted": template_id}


# ---- Offers --------------------------------------------------------------------

class OfferCreate(BaseModel):
    application_id: int
    template_id: Optional[int] = None
    template_content: Optional[str] = None
    fields: dict = {}


class OfferUpdate(BaseModel):
    template_content: Optional[str] = None
    fields: Optional[dict] = None
    valid_days: Optional[int] = Field(None, ge=1, le=60)


class OfferResponse(BaseModel):
    decision: str
    note: Optional[str] = Field(None, max_length=2000)


def _offer_for(db: Session, offer_id: int, user: Principal) -> models.OfferLetter:
    offer = db.get(models.OfferLetter, offer_id)
    app = db.get(models.Application, offer.application_id) if offer else None
    if offer is None or app is None:
        raise HTTPException(status_code=404, detail="Offer not found")
    if user.role == "candidate":
        # Candidates never see drafts.
        if offer.status == "draft" or not candidate_owns(user, app.candidate):
            raise HTTPException(status_code=404, detail="Offer not found")
    elif not hr_can_access_job(user, app.job):
        raise HTTPException(status_code=404, detail="Offer not found")
    return offer


@router.get("")
def list_offers(user: Principal = Depends(current_user), db: Session = Depends(get_db)):
    q = db.query(models.OfferLetter).join(models.Application)
    if user.role == "candidate":
        q = q.join(models.Candidate).filter(candidate_row_filter(user), models.OfferLetter.status != "draft")
    elif user.role == "hr":
        q = q.join(models.JobRole).filter((models.JobRole.hr_account_id == user.id) | (models.JobRole.hr_account_id.is_(None)))
    rows = q.order_by(models.OfferLetter.offer_id.desc()).all()
    for o in rows:
        svc.expire_if_needed(db, o)
    return [svc.offer_dict(db, o, user.role) for o in rows]


@router.get("/defaults/{application_id}")
def offer_defaults(application_id: int, user: Principal = Depends(require_hr_or_admin), db: Session = Depends(get_db)):
    app = assert_hr_application_access(user, db.get(models.Application, application_id))
    fields = svc.default_fields(db, app)
    if user.role == "hr" and not _is_unlocked(db, user, app):
        fields["candidate_email"] = _mask_email(fields["candidate_email"])
    return {"fields": fields, "template": svc.ensure_default_template(db).content,
            "placeholders": list(svc.PLACEHOLDERS), "required": list(svc.REQUIRED_TO_SEND)}


@router.post("")
def create_offer(payload: OfferCreate, user: Principal = Depends(require_hr_or_admin), db: Session = Depends(get_db)):
    app = assert_hr_application_access(user, db.get(models.Application, payload.application_id))
    if user.role == "hr" and not _is_unlocked(db, user, app):
        raise HTTPException(status_code=409, detail="Unlock this candidate (contact details) before creating an offer.")
    offer = svc.create_draft(db, user.id if user.role == "hr" else None, app, payload.template_id,
                             payload.template_content, payload.fields)
    return svc.offer_dict(db, offer, user.role)


@router.get("/{offer_id}")
def get_offer(offer_id: int, user: Principal = Depends(current_user), db: Session = Depends(get_db)):
    offer = _offer_for(db, offer_id, user)
    svc.expire_if_needed(db, offer)
    if user.role == "candidate":
        svc.mark_viewed(db, offer)
    return svc.offer_dict(db, offer, user.role)


@router.put("/{offer_id}")
def update_offer(offer_id: int, payload: OfferUpdate, user: Principal = Depends(require_hr_or_admin),
                 db: Session = Depends(get_db)):
    offer = _offer_for(db, offer_id, user)
    return svc.offer_dict(db, svc.update_draft(db, offer, payload.template_content, payload.fields, payload.valid_days),
                          user.role)


@router.get("/{offer_id}/preview.pdf")
def preview_offer_pdf(offer_id: int, user: Principal = Depends(require_hr_or_admin), db: Session = Depends(get_db)):
    """Letterhead PDF of the current draft, exactly as it would be sent (not saved)."""
    from fastapi.responses import Response
    offer = _offer_for(db, offer_id, user)
    return Response(svc.preview_pdf(db, offer), media_type="application/pdf",
                    headers={"Content-Disposition": f'inline; filename="Offer-{offer_id}-preview.pdf"'})


@router.post("/{offer_id}/revise")
def revise_offer(offer_id: int, user: Principal = Depends(require_hr_or_admin), db: Session = Depends(get_db)):
    offer = _offer_for(db, offer_id, user)
    return svc.offer_dict(db, svc.revise(db, offer, user.id if user.role == "hr" else None), user.role)


@router.post("/{offer_id}/send")
def send_offer(offer_id: int, background: BackgroundTasks, user: Principal = Depends(require_hr_or_admin),
               db: Session = Depends(get_db)):
    offer = _offer_for(db, offer_id, user)
    ensure_verified_hr(db, user)
    ids = svc.send(db, offer, user.id if user.role == "hr" else None, user.role)
    for eid in ids:
        background.add_task(dispatch_email, eid)   # after the offer is committed
    db.refresh(offer)
    return svc.offer_dict(db, offer, user.role)


@router.delete("/{offer_id}")
def delete_draft(offer_id: int, user: Principal = Depends(require_hr_or_admin), db: Session = Depends(get_db)):
    offer = _offer_for(db, offer_id, user)
    if offer.status != "draft":
        raise HTTPException(status_code=409, detail="Only drafts can be deleted; sent offers are kept for history")
    db.delete(offer)
    db.commit()
    return {"deleted": offer_id}


@router.post("/{offer_id}/respond")
def respond(offer_id: int, payload: OfferResponse, background: BackgroundTasks,
            user: Principal = Depends(require_candidate), db: Session = Depends(get_db)):
    offer = _offer_for(db, offer_id, user)
    for eid in svc.respond(db, offer, payload.decision, payload.note):
        background.add_task(dispatch_email, eid)
    return svc.offer_dict(db, offer, user.role)


@router.get("/{offer_id}/pdf")
def offer_pdf(offer_id: int, download: bool = False, user: Principal = Depends(current_user), db: Session = Depends(get_db)):
    offer = _offer_for(db, offer_id, user)
    if not offer.pdf_path:
        raise HTTPException(status_code=404, detail="A PDF is generated when the offer is sent")
    return files.file_response(offer.pdf_path, f"Offer-{offer.offer_id}.pdf", download)
