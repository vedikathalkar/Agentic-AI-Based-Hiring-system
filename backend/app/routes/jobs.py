from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from .. import models, schemas
from ..database import get_db
from ..security import Principal, hr_can_access_job, optional_user, require_hr_or_admin, require_verified_hr
from ..agents.skill_agent import parse_requirements
from ..services import search_service as search
from ..services.hiring_context import company_name

router = APIRouter(prefix="/jobs", tags=["jobs"])


def _out(db: Session, job: models.JobRole) -> dict:
    data = schemas.JobRoleOut.model_validate(job).model_dump()
    owner = db.get(models.HRAccount, job.hr_account_id) if job.hr_account_id else None
    data["company_name"] = company_name(db, owner) if owner else None
    data["status"] = job.status or "open"
    return data


@router.post("", response_model=schemas.JobRoleOut)
def create_job(job: schemas.JobRoleCreate, user: Principal = Depends(require_verified_hr), db: Session = Depends(get_db)):
    db_job = models.JobRole(**job.model_dump(), hr_account_id=user.id, status="open")
    db.add(db_job)
    db.commit()
    db.refresh(db_job)
    return _out(db, db_job)


@router.get("", response_model=List[schemas.JobRoleOut])
def list_jobs(db: Session = Depends(get_db)):
    """Public job board: open roles only."""
    jobs = (db.query(models.JobRole)
            .filter((models.JobRole.status.is_(None)) | (models.JobRole.status == "open"))
            .order_by(models.JobRole.created_at.desc().nullslast()).all())
    return [_out(db, j) for j in jobs]


@router.get("/search")
def search_jobs(q: str = "", location: Optional[str] = None, work_mode: Optional[str] = None,
                min_experience: Optional[float] = None, max_experience: Optional[float] = None,
                skills: Optional[str] = None, sort: str = "relevance", db: Session = Depends(get_db)):
    """Natural-language job search with structured filters (see services/search_service.py)."""
    jobs = [_out(db, j) for j in (db.query(models.JobRole)
                                  .filter((models.JobRole.status.is_(None)) | (models.JobRole.status == "open"))
                                  .order_by(models.JobRole.created_at.desc().nullslast()).all())]
    vocab = {s for j in jobs for s in parse_requirements(f"{j.get('requirements') or ''},{j.get('preferred_skills') or ''}")}
    parsed = search.parse_query(q[:300], extra_skills=vocab, extra_locations=[j.get("location") or "" for j in jobs])
    f = search.merge_filters(parsed, skills=[x.strip() for x in (skills or "").split(",") if x.strip()], location=location,
                             work_mode=work_mode, min_experience=min_experience, max_experience=max_experience)
    ranked = search.rank_jobs(jobs, f)
    if sort == "newest":
        ranked.sort(key=lambda r: str(r["job"].get("created_at") or ""), reverse=True)
    elif sort == "experience":
        ranked.sort(key=lambda r: r["job"].get("min_experience") or 0)
    skill_counts: dict[str, int] = {}
    for j in jobs:
        for sk in parse_requirements(j.get("requirements") or ""):
            skill_counts[sk] = skill_counts.get(sk, 0) + 1
    return {
        "understood": search.describe(f), "corrections": parsed["corrections"], "total": len(ranked),
        "results": [{**r["job"], "relevance": r["score"], "matched_skills": r["matched_skills"], "reasons": r["reasons"]}
                    for r in ranked],
        "facets": {"locations": sorted({j["location"] for j in jobs if j.get("location")}),
                   "skills": [k for k, _ in sorted(skill_counts.items(), key=lambda kv: -kv[1])[:15]]},
    }


@router.get("/mine", response_model=List[schemas.JobRoleOut])
def my_jobs(user: Principal = Depends(require_hr_or_admin), db: Session = Depends(get_db)):
    q = db.query(models.JobRole)
    if user.role == "hr":
        q = q.filter((models.JobRole.hr_account_id == user.id) | (models.JobRole.hr_account_id.is_(None)))
    return [_out(db, j) for j in q.order_by(models.JobRole.created_at.desc().nullslast()).all()]


@router.get("/{job_id}", response_model=schemas.JobRoleOut)
def get_job(job_id: int, user=Depends(optional_user), db: Session = Depends(get_db)):
    job = db.query(models.JobRole).filter(models.JobRole.job_id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.status == "closed" and not (user and hr_can_access_job(user, job)):
        raise HTTPException(status_code=404, detail="Job not found")
    return _out(db, job)


class JobStatusIn(BaseModel):
    status: str


@router.patch("/{job_id}/status", response_model=schemas.JobRoleOut)
def set_job_status(job_id: int, payload: JobStatusIn, user: Principal = Depends(require_hr_or_admin),
                   db: Session = Depends(get_db)):
    job = db.get(models.JobRole, job_id)
    if job is None or not hr_can_access_job(user, job) or (user.role == "hr" and job.hr_account_id != user.id):
        raise HTTPException(status_code=404, detail="Job not found")
    if payload.status not in ("open", "closed"):
        raise HTTPException(status_code=422, detail="status must be open or closed")
    job.status = payload.status
    db.commit()
    db.refresh(job)
    return _out(db, job)
