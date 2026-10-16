"""Admin console API (all endpoints require an admin session)."""

import os
from datetime import datetime
from typing import Literal, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

from .. import models
from ..database import get_db
from ..security import Principal, hash_password, require_admin
from ..services import code_runner, config, credits_service, email_service, profile_service
from ..services.email_service import EmailService, dispatch_email
from ..services.hiring_context import link
from ..services.notification_service import notify

router = APIRouter(prefix="/admin", tags=["admin"])


def ensure_admin_account(db: Session) -> None:
    """Create the initial admin from ADMIN_USERNAME / ADMIN_PASSWORD if none exists.
    An existing admin's password is never overwritten by the environment."""
    username = (os.getenv("ADMIN_USERNAME") or "nehadhumal").strip().lower()
    password = os.getenv("ADMIN_PASSWORD") or "admin"
    if db.query(models.AdminAccount).filter(models.AdminAccount.username == username).first():
        return
    db.add(models.AdminAccount(username=username, name=os.getenv("ADMIN_NAME") or "Neha Dhumal",
                               password_hash=hash_password(password)))
    db.commit()


@router.get("/overview")
def overview(user: Principal = Depends(require_admin), db: Session = Depends(get_db)):
    from ..scheduler.jobs import scheduler_status
    ledger = db.query(models.CreditTransaction)
    paid = db.query(func.coalesce(func.sum(models.CreditOrder.amount_paise), 0)).filter(models.CreditOrder.status == "paid").scalar()
    return {
        "counts": {
            "hr_accounts": db.query(models.HRAccount).count(),
            "candidate_accounts": db.query(models.CandidateAccount).count(),
            "jobs": db.query(models.JobRole).count(),
            "applications": db.query(models.Application).count(),
            "pending_verifications": db.query(models.Company).filter(models.Company.verification_status == "pending").count(),
            "verified_companies": db.query(models.Company).filter(models.Company.verification_status == "verified").count(),
            "open_tickets": db.query(models.SupportTicket).filter(models.SupportTicket.status.in_(("open", "in_progress"))).count(),
            "failed_emails": db.query(models.EmailLog).filter(models.EmailLog.status == "failed").count(),
            "queued_emails": db.query(models.EmailLog).filter(models.EmailLog.status == "queued").count(),
            "upcoming_interviews": db.query(models.InterviewSchedule).filter(
                models.InterviewSchedule.status.in_(("scheduled", "confirmed", "rescheduled")),
                models.InterviewSchedule.scheduled_at_utc >= datetime.utcnow()).count(),
            "offers_sent": db.query(models.OfferLetter).filter(models.OfferLetter.status != "draft").count(),
        },
        "credits": {
            "issued": int(ledger.filter(models.CreditTransaction.amount > 0).with_entities(
                func.coalesce(func.sum(models.CreditTransaction.amount), 0)).scalar() or 0),
            "spent": -int(ledger.filter(models.CreditTransaction.amount < 0).with_entities(
                func.coalesce(func.sum(models.CreditTransaction.amount), 0)).scalar() or 0),
            "revenue_paise": int(paid or 0),
        },
        "system": {"smtp": email_service.smtp_status(), "scheduler": scheduler_status(),
                   "sandbox": code_runner.sandbox_info(),
                   "languages": [lang["key"] for lang in code_runner.available_languages()],
                   "payments_configured": config.payments_configured(),
                   "groq_api_key_configured": bool(os.getenv("GROQ_API_KEY"))},
    }


# ---- Verification ------------------------------------------------------------------

@router.get("/verifications")
def verifications(status: Optional[str] = "pending", user: Principal = Depends(require_admin), db: Session = Depends(get_db)):
    q = db.query(models.Company)
    if status and status != "all":
        q = q.filter(models.Company.verification_status == status)
    out = []
    for c in q.order_by(models.Company.submitted_at.desc().nullslast(), models.Company.company_id.desc()).all():
        hr = db.get(models.HRAccount, c.hr_account_id)
        hp = profile_service.get_hr_profile(db, c.hr_account_id)
        out.append({**profile_service.company_dict(c),
                    "hr": {"account_id": hr.account_id, "name": hr.name, "email": hr.email, "phone": hp.phone,
                           "designation": hp.designation, "linkedin": hp.linkedin} if hr else None,
                    "completion": profile_service.hr_completion(hr, hp, c)["percent"] if hr else None})
    return out


class RejectIn(BaseModel):
    reason: str = Field(min_length=5, max_length=1000)


def _review(db: Session, company_id: int, status: str, reason: Optional[str], admin: Principal,
            background: BackgroundTasks) -> dict:
    c = db.get(models.Company, company_id)
    if c is None:
        raise HTTPException(status_code=404, detail="Company not found")
    if c.verification_status != "pending":
        raise HTTPException(status_code=409, detail=f"Company is {c.verification_status}, not pending review")
    c.verification_status, c.reviewed_by = status, admin.account.username
    c.verified_at = datetime.utcnow() if status == "verified" else None
    c.rejection_reason = reason if status == "rejected" else None
    db.commit()
    hr = db.get(models.HRAccount, c.hr_account_id)
    title = "Company verified" if status == "verified" else "Verification needs changes"
    notify(db, "hr", hr.account_id, "verification_update", title,
           "You can now post jobs." if status == "verified" else (reason or ""), "/hr/verification")
    log = EmailService.queue(db, to=hr.email, subject=f"{title} — {c.name}", template="verification_status",
                             context={"hr_name": hr.name, "company_name": c.name, "status": status, "reason": reason,
                                      "link": link("/hr/verification")},
                             related_type="company", related_id=c.company_id, recipient_role="hr",
                             recipient_id=hr.account_id, owner_role="hr", owner_id=hr.account_id)
    if log:
        background.add_task(dispatch_email, log.email_id)
    return profile_service.company_dict(c)


@router.post("/verifications/{company_id}/approve")
def approve(company_id: int, background: BackgroundTasks, user: Principal = Depends(require_admin),
            db: Session = Depends(get_db)):
    return _review(db, company_id, "verified", None, user, background)


@router.post("/verifications/{company_id}/reject")
def reject(company_id: int, payload: RejectIn, background: BackgroundTasks, user: Principal = Depends(require_admin),
           db: Session = Depends(get_db)):
    return _review(db, company_id, "rejected", payload.reason.strip(), user, background)


# ---- Users & credits ---------------------------------------------------------------

@router.get("/users")
def users(role: Literal["hr", "candidate"] = "hr", q: Optional[str] = None, user: Principal = Depends(require_admin),
          db: Session = Depends(get_db)):
    model = models.HRAccount if role == "hr" else models.CandidateAccount
    query = db.query(model)
    if q:
        like = f"%{q.lower()}%"
        query = query.filter(func.lower(model.name).like(like) | func.lower(model.email).like(like))
    out = []
    for a in query.order_by(model.account_id.desc()).limit(200).all():
        row = {"account_id": a.account_id, "name": a.name, "email": a.email, "created_at": a.created_at,
               "credits": credits_service.balance(db, role, a.account_id)}
        if role == "hr":
            c = db.query(models.Company).filter(models.Company.hr_account_id == a.account_id).first()
            row.update({"company": c.name if c else a.company, "verification_status": c.verification_status if c else "unverified",
                        "jobs": db.query(models.JobRole).filter(models.JobRole.hr_account_id == a.account_id).count()})
        else:
            row["applications"] = db.query(models.Candidate).filter(models.Candidate.account_id == a.account_id).count()
        out.append(row)
    return out


class CreditAdjust(BaseModel):
    role: Literal["hr", "candidate"]
    account_id: int
    amount: int
    reason: str = Field(min_length=3, max_length=200)


@router.post("/credits")
def adjust_credits(payload: CreditAdjust, user: Principal = Depends(require_admin), db: Session = Depends(get_db)):
    model = models.HRAccount if payload.role == "hr" else models.CandidateAccount
    if db.get(model, payload.account_id) is None:
        raise HTTPException(status_code=404, detail="Account not found")
    if payload.amount == 0:
        raise HTTPException(status_code=422, detail="Amount can't be zero")
    if payload.amount < 0 and credits_service.balance(db, payload.role, payload.account_id) + payload.amount < 0:
        raise HTTPException(status_code=422, detail="Adjustment would make the balance negative")
    tx = credits_service.add(db, payload.role, payload.account_id, payload.amount, "admin_adjustment",
                             f"Admin: {payload.reason.strip()}")
    notify(db, payload.role, payload.account_id, "credits_adjusted",
           f"{'Added' if payload.amount > 0 else 'Removed'} {abs(payload.amount)} credits", payload.reason,
           "/hr/credits" if payload.role == "hr" else "/refer")
    return {"transaction_id": tx.transaction_id, "balance": tx.balance_after}


# ---- Jobs --------------------------------------------------------------------------

@router.get("/jobs")
def jobs(user: Principal = Depends(require_admin), db: Session = Depends(get_db)):
    out = []
    for j in db.query(models.JobRole).order_by(models.JobRole.job_id.desc()).all():
        owner = db.get(models.HRAccount, j.hr_account_id) if j.hr_account_id else None
        out.append({"job_id": j.job_id, "title": j.title, "status": j.status or "open", "created_at": j.created_at,
                    "owner": {"account_id": owner.account_id, "name": owner.name, "company": owner.company} if owner else None,
                    "applications": db.query(models.Application).filter(models.Application.job_id == j.job_id).count()})
    return out


class OwnerIn(BaseModel):
    hr_account_id: int


@router.patch("/jobs/{job_id}/owner")
def assign_owner(job_id: int, payload: OwnerIn, user: Principal = Depends(require_admin), db: Session = Depends(get_db)):
    """Assign a legacy (unowned) job to an HR account so access is scoped."""
    job = db.get(models.JobRole, job_id)
    if job is None or db.get(models.HRAccount, payload.hr_account_id) is None:
        raise HTTPException(status_code=404, detail="Job or HR account not found")
    job.hr_account_id = payload.hr_account_id
    db.commit()
    return {"job_id": job_id, "hr_account_id": job.hr_account_id}


# ---- Operations --------------------------------------------------------------------

@router.post("/scheduler/run")
def run_scheduler(user: Principal = Depends(require_admin)):
    """Run the due jobs (reminders, expired assessments/offers, email retries) now."""
    from ..scheduler.jobs import run_due_jobs
    return run_due_jobs()
