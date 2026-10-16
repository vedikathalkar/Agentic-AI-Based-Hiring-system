import json
import logging
from typing import Optional

from fastapi.concurrency import run_in_threadpool
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from .. import models
from ..database import get_db
from ..security import Principal, require_candidate
from ..services import ats_service, credits_service, files, profile_service

router = APIRouter(prefix="/ats", tags=["ats"])
logger = logging.getLogger(__name__)


@router.post("/check")
async def ats_check(file: Optional[UploadFile] = File(None), use_profile_resume: bool = Form(False),
                    job_id: Optional[int] = Form(None), job_description: str = Form(""),
                    user: Principal = Depends(require_candidate), db: Session = Depends(get_db)):
    """Analyse a resume against a chosen job or a pasted description.
    The uploaded file is only read for this analysis; it never replaces the candidate's resume."""
    job = db.get(models.JobRole, job_id) if job_id else None
    if job_id and job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    if not job and len(job_description.strip()) < 30:
        raise HTTPException(status_code=422, detail="Choose a job or paste a job description (at least 30 characters)")
    temp_path = None
    try:
        if file is not None and file.filename:
            temp_path, name = await files.save_upload(file, "ats_tmp", (".pdf", ".docx"))
            path = temp_path
        elif use_profile_resume:
            p = profile_service.get_candidate_profile(db, user.id)
            if not p.resume_path or not p.resume_path.lower().endswith((".pdf", ".docx")):
                raise HTTPException(status_code=404, detail="Upload a PDF or DOCX resume to your profile first")
            path, name = p.resume_path, p.resume_file_name
        else:
            raise HTTPException(status_code=422, detail="Upload a resume (PDF or DOCX) or use your profile resume")
        try:
            text = await run_in_threadpool(ats_service.extract_text, path)
        except Exception:
            logger.warning("ATS text extraction failed", exc_info=True)
            raise HTTPException(status_code=422, detail="Could not read this resume. Make sure it is a valid, "
                                                        "non-password-protected PDF or DOCX file.")
        if len(text.split()) < 5:
            raise HTTPException(status_code=422, detail="Almost no text could be read from this resume. It may be a scanned "
                                                        "image — upload a text-based PDF or DOCX.")
        report = await run_in_threadpool(lambda: ats_service.analyze(text, job_description=(job.description or "") + "\n" + job_description if job else job_description,
                                     requirements=job.requirements if job else "",
                                     min_experience=job.min_experience if job else None,
                                     preferred_skills=(job.preferred_skills or "") if job else "",
                                     education_requirement=(job.education_requirement or "") if job else "",
                                     sections_detail=ats_service.section_details(text)))
        credits_service.spend(db, "candidate", user.id, "ats_check", "Resume ATS check", commit=False)
        row = models.ATSCheck(account_id=user.id, file_name=name, job_id=job.job_id if job else None,
                              job_description=job_description[:20000] or None, score=report["score"],
                              result=json.dumps(report))
        db.add(row)
        db.commit()
        db.refresh(row)
        return {"check_id": row.check_id, "created_at": row.created_at, "file_name": name,
                "job_title": job.title if job else None, **report,
                "credits_balance": credits_service.balance(db, "candidate", user.id)}
    finally:
        files.remove_file(temp_path)


@router.get("/checks")
def history(user: Principal = Depends(require_candidate), db: Session = Depends(get_db)):
    rows = (db.query(models.ATSCheck).filter(models.ATSCheck.account_id == user.id)
            .order_by(models.ATSCheck.check_id.desc()).limit(20).all())
    out = []
    for r in rows:
        job = db.get(models.JobRole, r.job_id) if r.job_id else None
        out.append({"check_id": r.check_id, "file_name": r.file_name, "score": r.score, "created_at": r.created_at,
                    "job_title": job.title if job else "Pasted description"})
    return {"checks": out, "cost": credits_service.config.CREDIT_COSTS["ats_check"],
            "balance": credits_service.balance(db, "candidate", user.id)}


@router.get("/checks/{check_id}")
def get_check(check_id: int, user: Principal = Depends(require_candidate), db: Session = Depends(get_db)):
    r = db.get(models.ATSCheck, check_id)
    if r is None or r.account_id != user.id:
        raise HTTPException(status_code=404, detail="Report not found")
    job = db.get(models.JobRole, r.job_id) if r.job_id else None
    return {"check_id": r.check_id, "created_at": r.created_at, "file_name": r.file_name,
            "job_title": job.title if job else None, **json.loads(r.result or "{}")}
