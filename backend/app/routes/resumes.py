import json
import logging
import os
import shutil
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy.orm import Session

from .. import models
from ..database import get_db
from ..agents.resume_parser import parse_resume
from ..security import Principal, candidate_owns, require_candidate
from ..scoring_service import (
    newest_application,
    run_and_store_screening,
    run_and_store_final_ranking,
    get_or_create_final_score,
)

logger = logging.getLogger(__name__)
from ..services import files  # noqa: E402

router = APIRouter(prefix="/resumes", tags=["resumes"])
UPLOAD_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)

ALLOWED_EXTENSIONS = (".pdf", ".docx")   # the parser cannot read legacy .doc files


def _owned_candidate(db: Session, candidate_id: int, user: Principal) -> models.Candidate:
    candidate = db.query(models.Candidate).filter(models.Candidate.candidate_id == candidate_id).first()
    if not candidate or not candidate_owns(user, candidate):
        raise HTTPException(status_code=404, detail="Candidate not found")
    return candidate


@router.post("/{candidate_id}")
def upload_resume(candidate_id: int, file: UploadFile = File(...), user: Principal = Depends(require_candidate),
                        db: Session = Depends(get_db)):
    """Store the original file, parse it, and run screening.

    This endpoint never generates or starts an assessment. Screening failure
    does not fail the upload: the response carries
    ``screening_result = {"status": "failed", "error": ...}``.
    """
    candidate = _owned_candidate(db, candidate_id, user)
    # Plain `def`: FastAPI runs it in a worker thread, so parsing + LangGraph screening
    # don't block every other request on the event loop.
    original_name = files.safe_name(file.filename or "resume")
    ext = os.path.splitext(original_name)[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=400, detail="Only PDF and DOCX resumes are supported")
    data = file.file.read()
    if len(data) > 5 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Resume must be 5 MB or smaller")
    if not data:
        raise HTTPException(status_code=400, detail="Uploaded file is empty")
    if not files._content_matches(ext, data):
        raise HTTPException(status_code=400, detail=f"The file content is not a valid {ext.lstrip('.').upper()} file")
    file_path = os.path.join(UPLOAD_DIR, f"{candidate_id}_{uuid.uuid4().hex[:8]}{ext}")
    with open(file_path, "wb") as f:
        f.write(data)
    return _process(db, candidate, file_path, original_name)


@router.post("/{candidate_id}/from-profile")
def use_profile_resume(candidate_id: int, user: Principal = Depends(require_candidate), db: Session = Depends(get_db)):
    """Apply with the resume already saved on the candidate's profile (copied, then parsed + screened)."""
    candidate = _owned_candidate(db, candidate_id, user)
    profile = db.query(models.CandidateProfile).filter(models.CandidateProfile.account_id == user.id).first()
    if not profile or not profile.resume_path or not os.path.isfile(profile.resume_path):
        raise HTTPException(status_code=404, detail="No resume saved on your profile")
    ext = os.path.splitext(profile.resume_path)[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=422, detail="Your profile resume is a .doc file, which can't be read. "
                                                    "Upload a PDF or DOCX version instead.")
    file_path = os.path.join(UPLOAD_DIR, f"{candidate_id}_{uuid.uuid4().hex[:8]}{ext}")
    shutil.copyfile(profile.resume_path, file_path)
    return _process(db, candidate, file_path, profile.resume_file_name or f"resume{ext}")


def _process(db: Session, candidate: models.Candidate, file_path: str, original_name: str) -> dict:
    candidate_id = candidate.candidate_id

    try:
        parsed = parse_resume(file_path, candidate_name=candidate.name)
    except Exception:
        logger.exception("Resume parsing failed for candidate %s", candidate_id)
        raise HTTPException(status_code=422, detail="Could not read this resume. Upload a text-based PDF or DOCX file "
                                                    "that is not password protected.")

    # One current resume per candidate: re-uploading updates the existing row.
    resume = candidate.resume
    if resume is None:
        resume = models.Resume(candidate_id=candidate_id)
        db.add(resume)
    resume.file_name = original_name
    resume.file_path = file_path
    resume.skills = parsed.get("skills", "")
    resume.experience = parsed.get("experience", "")
    resume.education = parsed.get("education", "")
    resume.experience_years = parsed.get("experience_years")
    resume.experience_entries = json.dumps(parsed.get("experience_entries", []))
    resume.uploaded_at = datetime.utcnow()

    application = newest_application(db, candidate_id)
    if application and application.status in (None, "submitted"):
        application.status = "parsed"
    db.commit()
    db.refresh(resume)

    screening_result = None
    if application is not None:
        # Screening reads the stored Resume row and application.job, so the
        # score is computed from exactly what HR will see.
        screening_result = run_and_store_screening(db, application, resume)
        if parsed.get("skill_discovery_error"):
            screening_result["warning"] = f"Skill discovery: {parsed['skill_discovery_error']}"

        # Re-upload after the assessment: keep the final score consistent
        # with the new screening values instead of leaving it stale.
        fs = get_or_create_final_score(db, application)
        if fs.test_score is not None:
            screening_result["final_ranking"] = run_and_store_final_ranking(db, application, fs)

    return {
        "resume_id": resume.resume_id,
        "candidate_id": candidate_id,
        "application_id": application.application_id if application else None,
        "file_name": resume.file_name,
        "skills": resume.skills,
        "education": resume.education,
        "experience": resume.experience,
        "experience_years": resume.experience_years,
        "screening_result": screening_result,
    }
