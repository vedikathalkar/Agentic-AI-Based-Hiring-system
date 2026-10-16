from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy.orm import Session

from .. import models
from ..database import get_db
from ..security import Principal, current_user, require_candidate, require_hr
from ..services import files, profile_service as ps
from ..services.email_service import EmailService, dispatch_email
from ..services.hiring_context import link
from ..services.notification_service import notify, notify_admins

router = APIRouter(tags=["profile"])

IDENTITY_FIELDS = ("name", "registration_number", "gst_number", "website")
DOC_TYPES = {"id_proof": "Official ID proof", "visiting_card": "Visiting card",
             "registration_proof": "Company registration proof"}


# ---- generic -------------------------------------------------------------------

@router.get("/profile")
def my_profile(user: Principal = Depends(current_user), db: Session = Depends(get_db)):
    if user.role == "candidate":
        return candidate_profile(user, db)
    if user.role == "hr":
        return hr_profile(user, db)
    return {"role": "admin", "name": user.name}


# ---- candidate -----------------------------------------------------------------

class CandidateProfileIn(BaseModel):
    name: Optional[str] = None
    headline: Optional[str] = None
    phone: Optional[str] = None
    location: Optional[str] = None
    date_of_birth: Optional[str] = None
    linkedin: Optional[str] = None
    github: Optional[str] = None
    portfolio: Optional[str] = None
    education: Optional[List[dict]] = None
    experience: Optional[List[dict]] = None
    projects: Optional[List[dict]] = None
    certifications: Optional[List[dict]] = None
    technical_skills: Optional[List[str]] = None
    soft_skills: Optional[List[str]] = None
    tools: Optional[List[str]] = None
    languages: Optional[List[str]] = None
    frameworks: Optional[List[str]] = None


@router.get("/candidate/profile")
def candidate_profile(user: Principal = Depends(require_candidate), db: Session = Depends(get_db)):
    p = ps.get_candidate_profile(db, user.id)
    return ps.candidate_profile_dict(user.account, p)


@router.put("/candidate/profile")
def update_candidate_profile(payload: CandidateProfileIn, user: Principal = Depends(require_candidate),
                             db: Session = Depends(get_db)):
    p = ps.update_candidate_profile(db, user.account, payload.model_dump(exclude_unset=True))
    return ps.candidate_profile_dict(user.account, p)


@router.post("/candidate/profile/photo")
async def upload_candidate_photo(file: UploadFile = File(...), user: Principal = Depends(require_candidate),
                                 db: Session = Depends(get_db)):
    p = ps.get_candidate_profile(db, user.id)
    path, _ = await files.save_upload(file, "photos", files.IMAGE_EXT, 2 * 1024 * 1024)
    old, p.photo_path, p.updated_at = p.photo_path, path, datetime.utcnow()
    db.commit()
    files.remove_file(old)
    return ps.candidate_profile_dict(user.account, p)


@router.get("/candidate/profile/photo")
def candidate_photo(user: Principal = Depends(require_candidate), db: Session = Depends(get_db)):
    p = ps.get_candidate_profile(db, user.id)
    return files.file_response(p.photo_path, "photo" + (p.photo_path or ".png")[-4:])


@router.post("/candidate/profile/resume")
async def upload_profile_resume(file: UploadFile = File(...), user: Principal = Depends(require_candidate),
                                db: Session = Depends(get_db)):
    p = ps.get_candidate_profile(db, user.id)
    path, name = await files.save_upload(file, "profile_resumes", files.RESUME_EXT)
    old = p.resume_path
    p.resume_path, p.resume_file_name, p.resume_uploaded_at = path, name, datetime.utcnow()
    db.commit()
    files.remove_file(old)
    return ps.candidate_profile_dict(user.account, p)


@router.get("/candidate/profile/resume")
def profile_resume(download: bool = False, user: Principal = Depends(require_candidate), db: Session = Depends(get_db)):
    p = ps.get_candidate_profile(db, user.id)
    return files.file_response(p.resume_path, p.resume_file_name, download)


# ---- HR ------------------------------------------------------------------------

class CompanyIn(BaseModel):
    name: Optional[str] = None
    official_email: Optional[str] = None
    website: Optional[str] = None
    description: Optional[str] = None
    industry: Optional[str] = None
    company_size: Optional[str] = None
    headquarters: Optional[str] = None
    registration_number: Optional[str] = None
    gst_number: Optional[str] = None
    contact_number: Optional[str] = None


class HRProfileIn(BaseModel):
    name: Optional[str] = None
    phone: Optional[str] = None
    designation: Optional[str] = None
    department: Optional[str] = None
    linkedin: Optional[str] = None
    location: Optional[str] = None
    company: Optional[CompanyIn] = None


def _hr_bundle(user: Principal, db: Session):
    return user.account, ps.get_hr_profile(db, user.id), ps.get_company(db, user.account)


@router.get("/hr/profile")
def hr_profile(user: Principal = Depends(require_hr), db: Session = Depends(get_db)):
    return ps.hr_profile_dict(*_hr_bundle(user, db))


@router.put("/hr/profile")
def update_hr_profile(payload: HRProfileIn, user: Principal = Depends(require_hr), db: Session = Depends(get_db)):
    account, hp, company = _hr_bundle(user, db)
    data = payload.model_dump(exclude_unset=True)
    if data.get("name") and data["name"].strip():
        account.name = data["name"].strip()
    for key in ps.HR_SCALARS:
        if key in data:
            v = data[key]
            setattr(hp, key, v.strip() if isinstance(v, str) and v.strip() else None)
    note = None
    if payload.company is not None:
        cdata = payload.company.model_dump(exclude_unset=True)
        changed_identity = any(k in cdata and (cdata[k] or None) != getattr(company, k) for k in IDENTITY_FIELDS)
        for key, value in cdata.items():
            setattr(company, key, value.strip() if isinstance(value, str) and value.strip() else None)
        if company.name:
            account.company = company.name
        if changed_identity and company.verification_status in ("verified", "pending"):
            company.verification_status, company.verified_at = "unverified", None
            note = "Company identity details changed, so verification must be submitted again."
        company.updated_at = datetime.utcnow()
    hp.updated_at = datetime.utcnow()
    db.commit()
    out = ps.hr_profile_dict(account, hp, company)
    out["note"] = note
    return out


async def _save_image(file: UploadFile, sub: str) -> str:
    path, _ = await files.save_upload(file, sub, files.IMAGE_EXT, 2 * 1024 * 1024)
    return path


@router.post("/hr/profile/photo")
async def upload_hr_photo(file: UploadFile = File(...), user: Principal = Depends(require_hr), db: Session = Depends(get_db)):
    account, hp, company = _hr_bundle(user, db)
    old, hp.photo_path = hp.photo_path, await _save_image(file, "photos")
    db.commit()
    files.remove_file(old)
    return ps.hr_profile_dict(account, hp, company)


@router.get("/hr/profile/photo")
def hr_photo(user: Principal = Depends(require_hr), db: Session = Depends(get_db)):
    hp = ps.get_hr_profile(db, user.id)
    return files.file_response(hp.photo_path, "photo" + (hp.photo_path or ".png")[-4:])


@router.post("/hr/company/logo")
async def upload_logo(file: UploadFile = File(...), user: Principal = Depends(require_hr), db: Session = Depends(get_db)):
    account, hp, company = _hr_bundle(user, db)
    old, company.logo_path = company.logo_path, await _save_image(file, "logos")
    db.commit()
    files.remove_file(old)
    return ps.hr_profile_dict(account, hp, company)


@router.get("/hr/company/logo")
def company_logo(user: Principal = Depends(require_hr), db: Session = Depends(get_db)):
    company = ps.get_company(db, user.account)
    return files.file_response(company.logo_path, "logo" + (company.logo_path or ".png")[-4:])


@router.post("/hr/company/documents")
async def upload_document(doc_type: str = Form(...), file: UploadFile = File(...), user: Principal = Depends(require_hr),
                          db: Session = Depends(get_db)):
    if doc_type not in DOC_TYPES:
        raise HTTPException(status_code=422, detail=f"doc_type must be one of {', '.join(DOC_TYPES)}")
    account, hp, company = _hr_bundle(user, db)
    if company.verification_status == "pending":
        raise HTTPException(status_code=409, detail="Verification is under review; documents can't be changed right now")
    if company.verification_status == "verified":
        raise HTTPException(status_code=409, detail="Your company is verified. Contact support to change verification documents.")
    path, name = await files.save_upload(file, "company_docs", files.IMAGE_EXT + (".pdf",), 2 * 1024 * 1024)
    db.add(models.CompanyDocument(company_id=company.company_id, doc_type=doc_type, file_name=name, file_path=path,
                                  content_type=file.content_type))
    db.commit()
    db.refresh(company)
    return ps.hr_profile_dict(account, hp, company)


@router.get("/hr/company/documents/{document_id}")
def get_document(document_id: int, user: Principal = Depends(current_user), db: Session = Depends(get_db)):
    doc = db.get(models.CompanyDocument, document_id)
    company = db.get(models.Company, doc.company_id) if doc else None
    if doc is None or company is None or not (user.role == "admin" or (user.role == "hr" and company.hr_account_id == user.id)):
        raise HTTPException(status_code=404, detail="Document not found")
    return files.file_response(doc.file_path, doc.file_name)


@router.get("/hr/verification")
def verification(user: Principal = Depends(require_hr), db: Session = Depends(get_db)):
    account, hp, company = _hr_bundle(user, db)
    docs = ps.docs_by_type(company)
    return {
        "state": ps.verification_state(account, hp, company), "status": company.verification_status or "unverified",
        "submitted_at": company.submitted_at, "verified_at": company.verified_at,
        "rejection_reason": company.rejection_reason, "missing": ps.verification_ready(account, hp, company),
        "checklist": [
            {"key": "identity", "label": "Identity document submitted", "done": "id_proof" in docs or "visiting_card" in docs},
            {"key": "company", "label": "Company information submitted",
             "done": not any(s["key"] == "company" and not s["complete"] for s in ps.hr_completion(account, hp, company)["sections"])},
            {"key": "logo", "label": "Company logo uploaded", "done": bool(company.logo_path)},
            {"key": "registration", "label": "Registration proof (optional)", "done": "registration_proof" in docs},
        ],
        "company": ps.company_dict(company),
    }


@router.post("/hr/verification")
def submit_verification(background: BackgroundTasks, user: Principal = Depends(require_hr), db: Session = Depends(get_db)):
    account, hp, company = _hr_bundle(user, db)
    if company.verification_status == "verified":
        raise HTTPException(status_code=409, detail="Your company is already verified")
    if company.verification_status == "pending":
        raise HTTPException(status_code=409, detail="Verification is already under review")
    missing = ps.verification_ready(account, hp, company)
    if missing:
        raise HTTPException(status_code=422, detail=f"Complete these before submitting: {', '.join(missing)}")
    company.verification_status, company.submitted_at = "pending", datetime.utcnow()
    company.rejection_reason, company.verified_at = None, None
    db.commit()
    notify(db, "hr", user.id, "verification_update", "Verification submitted",
           "Our team will review your company documents.", "/hr/verification")
    notify_admins(db, "verification_request", "New company verification",
                  f"{company.name} ({account.email}) submitted verification.", "/admin/verifications")
    log = EmailService.queue(db, to=account.email, subject=f"Verification received — {company.name}",
                             template="verification_status",
                             context={"hr_name": account.name, "company_name": company.name, "status": "pending",
                                      "link": link("/hr/verification")},
                             related_type="company", related_id=company.company_id,
                             recipient_role="hr", recipient_id=account.account_id, owner_role="hr", owner_id=account.account_id)
    if log:
        background.add_task(dispatch_email, log.email_id)
    return verification(user, db)
