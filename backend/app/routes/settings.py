from typing import Literal, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from .. import models
from ..database import get_db
from ..security import Principal, current_user, require_hr_or_admin
from ..services import email_service, settings_service
from ..services.email_service import dispatch_email

router = APIRouter(tags=["settings"])


class SettingsIn(BaseModel):
    theme: Optional[Literal["light", "dark"]] = None
    email_notifications: Optional[bool] = None
    assessment_notifications: Optional[bool] = None
    interview_notifications: Optional[bool] = None
    reminder_notifications: Optional[bool] = None
    offer_notifications: Optional[bool] = None
    marketing_notifications: Optional[bool] = None
    profile_visibility: Optional[Literal["employers", "private"]] = None
    resume_visibility: Optional[Literal["applied", "private"]] = None
    allow_data_for_matching: Optional[bool] = None


class AccountIn(BaseModel):
    name: Optional[str] = None
    phone: Optional[str] = None


@router.get("/settings")
def get_settings(user: Principal = Depends(current_user), db: Session = Depends(get_db)):
    row = settings_service.get_settings(db, user.role, user.id)
    account = {"name": user.name, "email": user.email, "role": user.role,
               "phone": getattr(user.account, "phone", None)}
    return {"account": account, "preferences": settings_service.settings_dict(row),
            "delete_account": {"supported": False,
                               "message": "To delete your account and data, open a support ticket — deletion is "
                                          "reviewed manually so hiring records you are part of stay consistent."}}


@router.put("/settings")
def update_settings(payload: SettingsIn, user: Principal = Depends(current_user), db: Session = Depends(get_db)):
    row = settings_service.update_settings(db, user.role, user.id, payload.model_dump(exclude_unset=True))
    return settings_service.settings_dict(row)


@router.put("/settings/account")
def update_account(payload: AccountIn, user: Principal = Depends(current_user), db: Session = Depends(get_db)):
    if user.role == "admin":
        raise HTTPException(status_code=403, detail="Admin account details are managed by environment configuration")
    if payload.name is not None:
        if not payload.name.strip():
            raise HTTPException(status_code=422, detail="Name can't be empty")
        user.account.name = payload.name.strip()
    if payload.phone is not None:
        user.account.phone = payload.phone.strip() or None
        model = models.CandidateProfile if user.role == "candidate" else models.HRProfile
        prof = db.query(model).filter(model.account_id == user.id).first()
        if prof:
            prof.phone = user.account.phone
    db.commit()
    return {"name": user.account.name, "email": user.account.email, "phone": user.account.phone}


# ---- Email (HR/admin) ------------------------------------------------------------

class TestEmailIn(BaseModel):
    to: Optional[str] = None


@router.get("/email/status")
def smtp_status(user: Principal = Depends(require_hr_or_admin)):
    return email_service.smtp_status()   # never includes the password


@router.post("/email/test")
def smtp_test(payload: TestEmailIn, user: Principal = Depends(require_hr_or_admin)):
    to = (payload.to or user.email or "").strip()
    if not to or "@" not in to:
        raise HTTPException(status_code=422, detail="Enter the address to send the test email to")
    result = email_service.send_test_email(to)
    if not result["ok"]:
        raise HTTPException(status_code=502, detail=f"Test email failed: {result['error']}")
    return {"sent_to": to, "ok": True}


@router.get("/email/logs")
def email_logs(status: Optional[str] = None, limit: int = 50, user: Principal = Depends(require_hr_or_admin),
               db: Session = Depends(get_db)):
    q = db.query(models.EmailLog)
    if user.role == "hr":
        q = q.filter(models.EmailLog.owner_role == "hr", models.EmailLog.owner_id == user.id)
    if status:
        q = q.filter(models.EmailLog.status == status)
    rows = q.order_by(models.EmailLog.email_id.desc()).limit(min(200, max(1, limit))).all()
    return [{"email_id": r.email_id, "to": r.to_email, "subject": r.subject, "template": r.template, "status": r.status,
             "error": r.error_message, "attempts": r.attempts, "related_type": r.related_type,
             "related_id": r.related_id, "created_at": r.created_at, "sent_at": r.sent_at} for r in rows]


@router.post("/email/logs/{email_id}/retry")
def retry_email(email_id: int, background: BackgroundTasks, user: Principal = Depends(require_hr_or_admin),
                db: Session = Depends(get_db)):
    log = db.get(models.EmailLog, email_id)
    if log is None or (user.role == "hr" and not (log.owner_role == "hr" and log.owner_id == user.id)):
        raise HTTPException(status_code=404, detail="Email not found")
    if log.status == "sent":
        raise HTTPException(status_code=409, detail="This email was already sent")
    log.status = "failed" if log.status != "queued" else "queued"
    db.commit()
    status = dispatch_email(email_id)
    db.refresh(log)
    return {"email_id": email_id, "status": status, "error": log.error_message}
