from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from .. import models, schemas
from ..database import get_db
from ..security import Principal, _token_from_header, _token_hash, create_session, current_user, end_session, hash_password, verify_password
from ..services import credits_service, referral_service, settings_service
from ..services.notification_service import unread_count

router = APIRouter(prefix="/auth", tags=["auth"])

# Re-exported for older imports.
__all__ = ["hash_password", "verify_password", "router"]


def _validate_password(password: str):
    if len(password or "") < 6:
        raise HTTPException(status_code=400, detail="Password must be at least 6 characters")


def _session_payload(db: Session, role: str, account, name: str, email: Optional[str], extra: dict | None = None) -> dict:
    account_id = account.admin_id if role == "admin" else account.account_id
    prefs = settings_service.get_settings(db, role, account_id)
    return {"token": create_session(db, role, account_id), "role": role, "account_id": account_id, "name": name, "email": email,
            "theme": prefs.theme, **(extra or {})}


class CandidateSignupIn(schemas.CandidateSignup):
    referral_code: Optional[str] = None


@router.post("/candidate/signup")
def candidate_signup(payload: CandidateSignupIn, db: Session = Depends(get_db)):
    email = payload.email.strip().lower()
    if not email or "@" not in email:
        raise HTTPException(status_code=400, detail="Enter a valid email address")
    if not payload.name.strip():
        raise HTTPException(status_code=400, detail="Enter your name")
    _validate_password(payload.password)
    if db.query(models.CandidateAccount).filter(models.CandidateAccount.email == email).first():
        raise HTTPException(status_code=409, detail="An account with this email already exists")
    account = models.CandidateAccount(name=payload.name.strip(), email=email, password_hash=hash_password(payload.password))
    db.add(account); db.commit(); db.refresh(account)
    credits_service.grant_signup_bonus(db, "candidate", account.account_id)
    settings_service.get_settings(db, "candidate", account.account_id)
    referral_service.register_signup(db, account, payload.referral_code)
    return {"message": "Candidate account created", "email": account.email}


@router.post("/candidate/login")
def candidate_login(payload: schemas.LoginRequest, db: Session = Depends(get_db)):
    account = db.query(models.CandidateAccount).filter(models.CandidateAccount.email == payload.email.strip().lower()).first()
    if not account or not verify_password(payload.password, account.password_hash):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    return _session_payload(db, "candidate", account, account.name, account.email)


@router.post("/hr/signup")
def hr_signup(payload: schemas.HRSignup, db: Session = Depends(get_db)):
    email = payload.email.strip().lower()
    if not email or "@" not in email:
        raise HTTPException(status_code=400, detail="Enter a valid email address")
    if not payload.name.strip() or not payload.company.strip():
        raise HTTPException(status_code=400, detail="Name and company are required")
    _validate_password(payload.password)
    if db.query(models.HRAccount).filter(models.HRAccount.email == email).first():
        raise HTTPException(status_code=409, detail="An HR account with this email already exists")
    account = models.HRAccount(name=payload.name.strip(), company=payload.company.strip(), email=email,
                               password_hash=hash_password(payload.password))
    db.add(account); db.commit(); db.refresh(account)
    db.add(models.Company(hr_account_id=account.account_id, name=account.company, verification_status="unverified"))
    db.commit()
    credits_service.grant_signup_bonus(db, "hr", account.account_id)
    settings_service.get_settings(db, "hr", account.account_id)
    return {"message": "HR account created", "email": account.email}


@router.post("/hr/login")
def hr_login(payload: schemas.LoginRequest, db: Session = Depends(get_db)):
    account = db.query(models.HRAccount).filter(models.HRAccount.email == payload.email.strip().lower()).first()
    if not account or not verify_password(payload.password, account.password_hash):
        raise HTTPException(status_code=401, detail="Invalid HR email or password")
    return _session_payload(db, "hr", account, account.name, account.email, {"company": account.company})


class AdminLogin(BaseModel):
    username: str
    password: str


@router.post("/admin/login")
def admin_login(payload: AdminLogin, db: Session = Depends(get_db)):
    admin = db.query(models.AdminAccount).filter(models.AdminAccount.username == payload.username.strip().lower()).first()
    if not admin or not verify_password(payload.password, admin.password_hash):
        raise HTTPException(status_code=401, detail="Invalid admin username or password")
    return _session_payload(db, "admin", admin, admin.name or admin.username, None, {"username": admin.username})


@router.get("/me")
def me(user: Principal = Depends(current_user), db: Session = Depends(get_db)):
    prefs = settings_service.get_settings(db, user.role, user.id)
    out = {"role": user.role, "account_id": user.id, "name": user.name, "email": user.email, "theme": prefs.theme,
           "unread_notifications": unread_count(db, user.role, user.id)}
    if user.role == "hr":
        company = db.query(models.Company).filter(models.Company.hr_account_id == user.id).first()
        out.update({"company": (company.name if company and company.name else user.account.company),
                    "verification_status": company.verification_status if company else "unverified",
                    "credits": credits_service.balance(db, "hr", user.id)})
    elif user.role == "candidate":
        out["credits"] = credits_service.balance(db, "candidate", user.id)
    return out


@router.post("/logout")
def logout(authorization: Optional[str] = Header(None), user: Principal = Depends(current_user), db: Session = Depends(get_db)):
    token = _token_from_header(authorization)
    end_session(db, token)
    if user.account.session_token == token:      # legacy token
        user.account.session_token = None
        db.commit()
    return {"message": "Logged out"}


class PasswordChange(BaseModel):
    current_password: str
    new_password: str


@router.post("/password")
def change_password(payload: PasswordChange, authorization: Optional[str] = Header(None),
                    user: Principal = Depends(current_user), db: Session = Depends(get_db)):
    if not verify_password(payload.current_password, user.account.password_hash):
        raise HTTPException(status_code=400, detail="Current password is incorrect")
    _validate_password(payload.new_password)
    user.account.password_hash = hash_password(payload.new_password)
    # Sign out every other device; this session stays active.
    keep = _token_hash(_token_from_header(authorization) or "")
    db.query(models.AuthSession).filter(models.AuthSession.role == user.role, models.AuthSession.account_id == user.id,
                                        models.AuthSession.token_hash != keep).delete(synchronize_session=False)
    db.commit()
    return {"message": "Password updated", "updated_at": datetime.utcnow()}
