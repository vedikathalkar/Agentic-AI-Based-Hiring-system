"""Authentication and authorization helpers.

Every request carries ``Authorization: Bearer <session token>``. The token is
resolved against the admin, HR and candidate account tables (tokens are random
and unique). Ownership checks live here so routes never rely on the frontend
for access control.
"""

from __future__ import annotations

import base64
import hmac
from dataclasses import dataclass
import os
from datetime import datetime, timedelta
from hashlib import pbkdf2_hmac, sha256
from os import urandom
from secrets import token_urlsafe
from typing import Any, Optional

from fastapi import Depends, Header, HTTPException
from sqlalchemy.orm import Session

from . import models
from .database import get_db


def hash_password(password: str) -> str:
    salt = urandom(16)
    digest = pbkdf2_hmac("sha256", password.encode(), salt, 120_000)
    return base64.b64encode(salt + digest).decode()


def verify_password(password: str, stored: str) -> bool:
    try:
        raw = base64.b64decode(stored.encode())
        salt, expected = raw[:16], raw[16:]
        actual = pbkdf2_hmac("sha256", password.encode(), salt, 120_000)
        return hmac.compare_digest(actual, expected)
    except Exception:
        return False


@dataclass
class Principal:
    role: str          # candidate | hr | admin
    id: int
    name: str
    email: Optional[str]
    account: Any

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"


def _token_from_header(authorization: Optional[str]) -> Optional[str]:
    if not authorization:
        return None
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        return None
    return token.strip()


SESSION_DAYS = int(os.getenv("SESSION_DAYS", "30"))
_ACCOUNT_MODELS = {"admin": models.AdminAccount, "hr": models.HRAccount, "candidate": models.CandidateAccount}


def _token_hash(token: str) -> str:
    return sha256(token.encode()).hexdigest()


def create_session(db: Session, role: str, account_id: int) -> str:
    """Issue a new bearer token for a login. Other sessions stay valid."""
    token = token_urlsafe(32)
    now = datetime.utcnow()
    db.add(models.AuthSession(token_hash=_token_hash(token), role=role, account_id=account_id,
                              created_at=now, last_used_at=now, expires_at=now + timedelta(days=SESSION_DAYS)))
    # Opportunistic cleanup of expired rows for this account.
    db.query(models.AuthSession).filter(models.AuthSession.role == role, models.AuthSession.account_id == account_id,
                                        models.AuthSession.expires_at < now).delete(synchronize_session=False)
    db.commit()
    return token


def end_session(db: Session, token: Optional[str]) -> None:
    if token:
        db.query(models.AuthSession).filter(models.AuthSession.token_hash == _token_hash(token)).delete(synchronize_session=False)
        db.commit()


def _principal(role: str, account) -> Principal:
    if role == "admin":
        return Principal("admin", account.admin_id, account.name or account.username, None, account)
    return Principal(role, account.account_id, account.name, account.email, account)


def resolve_token(db: Session, token: Optional[str]) -> Optional[Principal]:
    if not token:
        return None
    row = db.query(models.AuthSession).filter(models.AuthSession.token_hash == _token_hash(token)).first()
    if row is not None:
        now = datetime.utcnow()
        account = db.get(_ACCOUNT_MODELS[row.role], row.account_id) if row.role in _ACCOUNT_MODELS else None
        if account is None or row.expires_at < now:
            db.delete(row); db.commit()
            return None
        if (now - (row.last_used_at or now)).total_seconds() > 3600:   # sliding expiry, written at most hourly
            row.last_used_at, row.expires_at = now, now + timedelta(days=SESSION_DAYS)
            db.commit()
        return _principal(row.role, account)
    # Legacy single-column tokens issued before auth_sessions existed.
    admin = db.query(models.AdminAccount).filter(models.AdminAccount.session_token == token).first()
    if admin:
        return Principal("admin", admin.admin_id, admin.name or admin.username, None, admin)
    hr = db.query(models.HRAccount).filter(models.HRAccount.session_token == token).first()
    if hr:
        return Principal("hr", hr.account_id, hr.name, hr.email, hr)
    cand = db.query(models.CandidateAccount).filter(models.CandidateAccount.session_token == token).first()
    if cand:
        return Principal("candidate", cand.account_id, cand.name, cand.email, cand)
    return None


def optional_user(authorization: Optional[str] = Header(None), db: Session = Depends(get_db)) -> Optional[Principal]:
    return resolve_token(db, _token_from_header(authorization))


def current_user(principal: Optional[Principal] = Depends(optional_user)) -> Principal:
    if principal is None:
        raise HTTPException(status_code=401, detail="Please log in to continue")
    return principal


def require_candidate(user: Principal = Depends(current_user)) -> Principal:
    if user.role != "candidate":
        raise HTTPException(status_code=403, detail="Candidate account required")
    return user


def require_hr(user: Principal = Depends(current_user)) -> Principal:
    if user.role != "hr":
        raise HTTPException(status_code=403, detail="HR account required")
    return user


def require_hr_or_admin(user: Principal = Depends(current_user)) -> Principal:
    if user.role not in ("hr", "admin"):
        raise HTTPException(status_code=403, detail="HR or admin account required")
    return user


def require_admin(user: Principal = Depends(current_user)) -> Principal:
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin account required")
    return user


def company_for(db: Session, hr_account_id: int) -> Optional[models.Company]:
    return db.query(models.Company).filter(models.Company.hr_account_id == hr_account_id).first()


def ensure_verified_hr(db: Session, user: Principal) -> None:
    """Posting jobs, unlocking candidates and sending offers need a verified company."""
    if user.role == "admin":
        return
    company = company_for(db, user.id)
    if not company or company.verification_status != "verified":
        raise HTTPException(
            status_code=403,
            detail="Company verification required. Complete your company profile and submit verification documents.",
        )


def require_verified_hr(user: Principal = Depends(require_hr), db: Session = Depends(get_db)) -> Principal:
    ensure_verified_hr(db, user)
    return user


# ---- Ownership -------------------------------------------------------------

def hr_can_access_job(user: Principal, job: Optional[models.JobRole]) -> bool:
    if user.role == "admin":
        return True
    if user.role != "hr" or job is None:
        return False
    # Legacy jobs (created before job ownership existed) have no owner.
    return job.hr_account_id is None or job.hr_account_id == user.id


def candidate_owns(user: Principal, candidate: Optional[models.Candidate]) -> bool:
    if user.role != "candidate" or candidate is None:
        return False
    if candidate.account_id is not None:
        return candidate.account_id == user.id
    # Legacy rows created before accounts were linked: match on email.
    return bool(candidate.email and user.email and candidate.email.strip().lower() == user.email.strip().lower())


def can_view_application(user: Principal, application: models.Application) -> bool:
    if user.role == "candidate":
        return candidate_owns(user, application.candidate)
    return hr_can_access_job(user, application.job)


def assert_application_access(user: Principal, application: Optional[models.Application]) -> models.Application:
    if application is None:
        raise HTTPException(status_code=404, detail="Application not found")
    if not can_view_application(user, application):
        # 404 rather than 403 so ids of other users' data are not confirmed.
        raise HTTPException(status_code=404, detail="Application not found")
    return application


def assert_hr_application_access(user: Principal, application: Optional[models.Application]) -> models.Application:
    if application is None or user.role not in ("hr", "admin") or not hr_can_access_job(user, application.job):
        raise HTTPException(status_code=404, detail="Application not found")
    return application


def assert_candidate_application(user: Principal, application: Optional[models.Application]) -> models.Application:
    if application is None or not candidate_owns(user, application.candidate):
        raise HTTPException(status_code=404, detail="Application not found")
    return application


def hr_job_filter(query, user: Principal):
    """Restrict a JobRole/Application query to jobs the HR user may see."""
    if user.role == "admin":
        return query
    return query.filter((models.JobRole.hr_account_id == user.id) | (models.JobRole.hr_account_id.is_(None)))


def candidate_row_filter(user: Principal):
    """SQL filter for Candidate rows belonging to a candidate account (incl. legacy email-linked rows)."""
    from sqlalchemy import and_, func
    return (models.Candidate.account_id == user.id) | and_(
        models.Candidate.account_id.is_(None), func.lower(models.Candidate.email) == (user.email or "").lower())
