"""Candidate/HR profiles and profile-completion calculation (from stored fields only)."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Optional

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .. import models

CANDIDATE_JSON_LISTS = ("education", "experience", "projects", "certifications",
                        "technical_skills", "soft_skills", "tools", "languages", "frameworks")
CANDIDATE_SCALARS = ("headline", "phone", "location", "date_of_birth", "linkedin", "github", "portfolio")


def _loads(value: Optional[str]) -> list:
    try:
        data = json.loads(value) if value else []
        return data if isinstance(data, list) else []
    except (TypeError, ValueError):
        return []


def _filled(v: Any) -> bool:
    return v is not None and str(v).strip() != ""


# ---- Candidate --------------------------------------------------------------

def get_candidate_profile(db: Session, account_id: int) -> models.CandidateProfile:
    row = db.query(models.CandidateProfile).filter(models.CandidateProfile.account_id == account_id).first()
    if row is None:
        row = models.CandidateProfile(account_id=account_id)
        db.add(row)
        try:
            db.commit()
        except IntegrityError:          # a parallel request created it first
            db.rollback()
            return db.query(models.CandidateProfile).filter(models.CandidateProfile.account_id == account_id).one()
        db.refresh(row)
    return row


def _clean_entries(entries: Any, keys: tuple[str, ...]) -> list[dict]:
    out = []
    for e in entries or []:
        if not isinstance(e, dict):
            continue
        item = {k: (e.get(k).strip() if isinstance(e.get(k), str) else e.get(k)) for k in keys}
        if any(_filled(v) for k, v in item.items() if k != "current"):
            out.append(item)
    return out


ENTRY_KEYS = {
    "education": ("degree", "specialization", "institution", "start_year", "graduation_year", "grade"),
    "experience": ("company", "role", "start_date", "end_date", "current", "responsibilities", "achievements"),
    "projects": ("name", "description", "technologies", "url"),
    "certifications": ("name", "issuer", "date", "credential_url"),
}


def update_candidate_profile(db: Session, account: models.CandidateAccount, data: dict) -> models.CandidateProfile:
    profile = get_candidate_profile(db, account.account_id)
    if _filled(data.get("name")):
        account.name = data["name"].strip()
    for key in CANDIDATE_SCALARS:
        if key in data:
            value = data[key]
            setattr(profile, key, value.strip() if isinstance(value, str) and value.strip() else None)
    if "phone" in data:
        account.phone = profile.phone
    for key, keys in ENTRY_KEYS.items():
        if key in data:
            setattr(profile, key, json.dumps(_clean_entries(data[key], keys)))
    for key in ("technical_skills", "soft_skills", "tools", "languages", "frameworks"):
        if key in data:
            values, seen = [], set()
            for v in data[key] or []:
                v = str(v).strip()
                if v and v.lower() not in seen:
                    seen.add(v.lower())
                    values.append(v[:60])
            setattr(profile, key, json.dumps(values))
    profile.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(profile)
    return profile


def candidate_completion(account: models.CandidateAccount, p: models.CandidateProfile) -> dict:
    education = _loads(p.education)
    experience = _loads(p.experience)
    tech = _loads(p.technical_skills)
    sections = []

    def section(key, label, weight, missing):
        sections.append({"key": key, "label": label, "weight": weight, "complete": not missing, "missing": missing})

    section("personal", "Personal details", 20,
            [lbl for lbl, v in (("Full name", account.name), ("Email", account.email), ("Phone", p.phone),
                                ("Location", p.location)) if not _filled(v)])
    section("education", "Education", 15,
            [] if any(_filled(e.get("degree")) and _filled(e.get("institution")) for e in education)
            else ["At least one degree with college/university"])
    section("experience", "Experience", 15,
            [] if any(_filled(e.get("company")) and _filled(e.get("role")) for e in experience)
            else ["At least one role (internships count)"])
    section("skills", "Skills", 15, [] if len(tech) >= 3 else [f"At least 3 technical skills ({len(tech)} added)"])
    section("resume", "Resume", 20, [] if p.resume_path else ["Upload your resume"])
    section("projects", "Projects", 5, [] if _loads(p.projects) else ["Add a project"])
    section("certifications", "Certifications", 5, [] if _loads(p.certifications) else ["Add a certification"])
    section("links", "Professional links", 5,
            [] if any(_filled(v) for v in (p.linkedin, p.github, p.portfolio)) else ["LinkedIn, GitHub or portfolio"])
    percent = sum(s["weight"] for s in sections if s["complete"])
    return {"percent": percent, "sections": sections, "complete": percent == 100}


def candidate_profile_dict(account: models.CandidateAccount, p: models.CandidateProfile) -> dict:
    out = {"account_id": account.account_id, "name": account.name, "email": account.email,
           "has_photo": bool(p.photo_path), "resume_file_name": p.resume_file_name,
           "resume_uploaded_at": p.resume_uploaded_at, "updated_at": p.updated_at}
    for key in CANDIDATE_SCALARS:
        out[key] = getattr(p, key)
    for key in CANDIDATE_JSON_LISTS:
        out[key] = _loads(getattr(p, key))
    out["completion"] = candidate_completion(account, p)
    return out


# ---- HR / company ---------------------------------------------------------------

HR_SCALARS = ("phone", "designation", "department", "linkedin", "location")
COMPANY_FIELDS = ("name", "official_email", "website", "description", "industry", "company_size",
                  "headquarters", "registration_number", "gst_number", "contact_number")
COMPANY_REQUIRED = (("name", "Company name"), ("official_email", "Official company email"),
                    ("website", "Company website"), ("industry", "Industry"), ("company_size", "Company size"),
                    ("headquarters", "Headquarters"), ("description", "Company description"),
                    ("contact_number", "Company contact number"))


def get_hr_profile(db: Session, account_id: int) -> models.HRProfile:
    row = db.query(models.HRProfile).filter(models.HRProfile.account_id == account_id).first()
    if row is None:
        row = models.HRProfile(account_id=account_id)
        db.add(row)
        try:
            db.commit()
        except IntegrityError:          # a parallel request created it first
            db.rollback()
            return db.query(models.HRProfile).filter(models.HRProfile.account_id == account_id).one()
        db.refresh(row)
    return row


def get_company(db: Session, account: models.HRAccount) -> models.Company:
    row = db.query(models.Company).filter(models.Company.hr_account_id == account.account_id).first()
    if row is None:
        row = models.Company(hr_account_id=account.account_id, name=account.company, verification_status="unverified")
        db.add(row)
        try:
            db.commit()
        except IntegrityError:          # a parallel request created it first
            db.rollback()
            return db.query(models.Company).filter(models.Company.hr_account_id == account.account_id).one()
        db.refresh(row)
    return row


def docs_by_type(company: models.Company) -> dict[str, models.CompanyDocument]:
    latest: dict[str, models.CompanyDocument] = {}
    for d in sorted(company.documents, key=lambda d: d.document_id):
        latest[d.doc_type] = d
    return latest


def hr_completion(account: models.HRAccount, hp: models.HRProfile, company: models.Company) -> dict:
    docs = docs_by_type(company)
    sections = []

    def section(key, label, weight, missing):
        sections.append({"key": key, "label": label, "weight": weight, "complete": not missing, "missing": missing})

    section("personal", "Personal details", 20,
            [lbl for lbl, v in (("Full name", account.name), ("Email", account.email), ("Phone", hp.phone),
                                ("Designation", hp.designation)) if not _filled(v)])
    section("photo", "Profile photo", 5, [] if hp.photo_path else ["Profile photo"])
    section("company", "Company details", 40, [lbl for key, lbl in COMPANY_REQUIRED if not _filled(getattr(company, key))])
    section("logo", "Company logo", 10, [] if company.logo_path else ["Company logo"])
    section("identity", "ID proof or visiting card", 15,
            [] if ("id_proof" in docs or "visiting_card" in docs) else ["Official ID proof or visiting card"])
    section("registration", "Company registration proof", 10,
            [] if "registration_proof" in docs else ["Company registration proof"])
    percent = sum(s["weight"] for s in sections if s["complete"])
    return {"percent": percent, "sections": sections, "complete": percent == 100}


def verification_ready(account, hp, company) -> list[str]:
    """What must exist before verification can be submitted."""
    comp = hr_completion(account, hp, company)
    needed = []
    for s in comp["sections"]:
        if s["key"] in ("company", "logo", "identity") and not s["complete"]:
            needed.extend(s["missing"])
    return needed


def verification_state(account, hp, company) -> str:
    """Display state: profile_incomplete | verification_required | pending | verified | rejected."""
    status = company.verification_status or "unverified"
    if status in ("pending", "verified", "rejected"):
        return status
    return "profile_incomplete" if verification_ready(account, hp, company) else "verification_required"


def company_dict(company: models.Company) -> dict:
    docs = docs_by_type(company)
    out = {f: getattr(company, f) for f in COMPANY_FIELDS}
    out.update({
        "company_id": company.company_id, "has_logo": bool(company.logo_path),
        "verification_status": company.verification_status or "unverified",
        "submitted_at": company.submitted_at, "verified_at": company.verified_at,
        "rejection_reason": company.rejection_reason,
        "documents": [{"document_id": d.document_id, "doc_type": d.doc_type, "file_name": d.file_name,
                       "uploaded_at": d.uploaded_at} for d in docs.values()],
    })
    return out


def hr_profile_dict(account, hp, company) -> dict:
    out = {"account_id": account.account_id, "name": account.name, "email": account.email,
           "has_photo": bool(hp.photo_path)}
    for key in HR_SCALARS:
        out[key] = getattr(hp, key)
    out["company"] = company_dict(company)
    out["completion"] = hr_completion(account, hp, company)
    out["verification_state"] = verification_state(account, hp, company)
    out["verification_missing"] = verification_ready(account, hp, company)
    return out
