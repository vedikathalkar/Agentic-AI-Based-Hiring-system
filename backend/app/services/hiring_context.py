"""Lookups shared by interview/offer/assessment services (who, which company, links)."""

from __future__ import annotations

from typing import Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from .. import models
from . import config


def candidate_account_for(db: Session, candidate: Optional[models.Candidate]) -> Optional[models.CandidateAccount]:
    if candidate is None:
        return None
    if candidate.account_id:
        return db.get(models.CandidateAccount, candidate.account_id)
    if candidate.email:
        return (db.query(models.CandidateAccount)
                .filter(func.lower(models.CandidateAccount.email) == candidate.email.strip().lower()).first())
    return None


def hr_for_job(db: Session, job: Optional[models.JobRole], fallback_id: Optional[int] = None) -> Optional[models.HRAccount]:
    hr_id = job.hr_account_id if job and job.hr_account_id else fallback_id
    return db.get(models.HRAccount, hr_id) if hr_id else None


def company_name(db: Session, hr: Optional[models.HRAccount]) -> str:
    if hr is None:
        return config.app_name()
    company = db.query(models.Company).filter(models.Company.hr_account_id == hr.account_id).first()
    return (company.name if company and company.name else None) or hr.company or config.app_name()


def company_contact(db: Session, hr: Optional[models.HRAccount]) -> Optional[str]:
    if hr is None:
        return None
    company = db.query(models.Company).filter(models.Company.hr_account_id == hr.account_id).first()
    email = (company.official_email if company and company.official_email else None) or hr.email
    return f"{hr.name} ({email})"


def link(path: str) -> str:
    return f"{config.frontend_url()}{path}"
