import logging
import os
from contextlib import asynccontextmanager, contextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import inspect, text
from sqlalchemy.exc import SQLAlchemyError

from .database import Base, engine, SQLALCHEMY_DATABASE_URL, safe_url
from . import models  # noqa: F401  (registers tables on Base.metadata)
from .routes import (jobs, candidates, resumes, assessments, interviews, auth, profile, settings as settings_routes,
                     notifications, offers, coding, ats, referrals, support, billing, dashboard, admin,
                     assessment_templates, practice)
from .database import SessionLocal
from .agents import resume_parser
from .agents.semantic_utils import model_available

if not logging.getLogger().handlers:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("hirelune")

SCORE_COLUMNS = ("skill_score", "experience_score", "test_score", "final_score")
POST_ASSESSMENT_STATUSES = ("assessed", "shortlisted", "scheduled", "selected", "rejected")
MIGRATION_VERSION = 2


# ---------------------------------------------------------------------------
# Startup schema migration (PostgreSQL and SQLite)
# ---------------------------------------------------------------------------
# create_all() creates missing tables but never alters existing ones, so new
# columns are added here with ALTER TABLE. Data is always preserved.

def _literal_default(column, dialect) -> str | None:
    d = column.default
    if d is None or not getattr(d, "is_scalar", False):
        return None
    v = d.arg
    if isinstance(v, bool):
        return ("TRUE" if v else "FALSE") if dialect.name == "postgresql" else ("1" if v else "0")
    if isinstance(v, (int, float)):
        return str(v)
    if isinstance(v, str):
        return "'" + v.replace("'", "''") + "'"
    return None


def _add_missing_columns(conn) -> None:
    insp = inspect(conn)
    quote = conn.dialect.identifier_preparer.quote
    tables = set(insp.get_table_names())
    for table in Base.metadata.sorted_tables:
        if table.name not in tables:
            continue
        have = {c["name"] for c in insp.get_columns(table.name)}
        for column in table.columns:
            if column.name in have:
                continue
            ddl = f"{quote(column.name)} {column.type.compile(dialect=conn.dialect)}"
            default = _literal_default(column, conn.dialect)
            if default is not None:
                ddl += f" DEFAULT {default}"     # old rows get the default instead of NULL
            conn.execute(text(f"ALTER TABLE {quote(table.name)} ADD COLUMN {ddl}"))
            logger.info("Migrated table %s: added column %s", table.name, column.name)


def _sqlite_table_info(conn, table: str) -> dict:
    return {row[1]: row for row in conn.exec_driver_sql(f'PRAGMA table_info("{table}")').fetchall()}


def _sqlite_rebuild_table(conn, table) -> None:
    """SQLite cannot drop NOT NULL in place: recreate the table and copy every row."""
    name, legacy = table.name, f"{table.name}__legacy"
    old_cols = set(_sqlite_table_info(conn, name))
    conn.exec_driver_sql(f'ALTER TABLE "{name}" RENAME TO "{legacy}"')
    for (index_name,) in conn.exec_driver_sql(
        "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name=? AND sql IS NOT NULL", (legacy,)
    ).fetchall():
        conn.exec_driver_sql(f'DROP INDEX IF EXISTS "{index_name}"')
    table.create(bind=conn)
    cols = ", ".join(f'"{c.name}"' for c in table.columns if c.name in old_cols)
    conn.exec_driver_sql(f'INSERT INTO "{name}" ({cols}) SELECT {cols} FROM "{legacy}"')
    conn.exec_driver_sql(f'DROP TABLE "{legacy}"')
    logger.info("Migrated table %s (rebuilt)", name)


def _make_score_columns_nullable(conn) -> None:
    """Scores must be NULL (not 0) until calculated."""
    insp = inspect(conn)
    if "final_scores" not in insp.get_table_names():
        return
    info = {c["name"]: c for c in insp.get_columns("final_scores")}
    bad = [c for c in SCORE_COLUMNS if c in info and (not info[c]["nullable"] or info[c].get("default") is not None)]
    if not bad:
        return
    if conn.dialect.name == "sqlite":
        _sqlite_rebuild_table(conn, Base.metadata.tables["final_scores"])
    else:
        for c in bad:
            conn.execute(text(f'ALTER TABLE final_scores ALTER COLUMN "{c}" DROP NOT NULL'))
            conn.execute(text(f'ALTER TABLE final_scores ALTER COLUMN "{c}" DROP DEFAULT'))


def _clean_legacy_zero_scores(conn) -> None:
    """Old schemas stored default=0 for scores that were never calculated. A 0 is
    treated as "not calculated" only where there is no evidence it was real."""
    not_assessed = f"""application_id NOT IN (
            SELECT application_id FROM assessments WHERE completed_at IS NOT NULL)
        AND application_id NOT IN (
            SELECT application_id FROM applications
            WHERE status IN ({", ".join(f"'{s}'" for s in POST_ASSESSMENT_STATUSES)}))"""
    conn.execute(text(f"UPDATE final_scores SET test_score = NULL WHERE test_score = 0 AND {not_assessed}"))
    conn.execute(text(f"UPDATE final_scores SET final_score = NULL WHERE final_score = 0 AND (test_score IS NULL OR {not_assessed})"))
    conn.execute(text(f"""UPDATE final_scores SET skill_score = NULL, experience_score = NULL
        WHERE (skill_score = 0 OR experience_score = 0)
          AND skill_matched IS NULL AND skill_missing IS NULL AND screening_status IS NULL
          AND (test_score IS NULL OR {not_assessed})"""))


def _schema_version(conn) -> int:
    conn.execute(text("CREATE TABLE IF NOT EXISTS schema_meta (key VARCHAR(50) PRIMARY KEY, value INTEGER NOT NULL)"))
    v = conn.execute(text("SELECT value FROM schema_meta WHERE key = 'version'")).scalar()
    if v is None and conn.dialect.name == "sqlite":
        v = conn.exec_driver_sql("PRAGMA user_version").scalar()   # databases migrated by older releases
    return int(v or 0)


def _set_schema_version(conn, version: int) -> None:
    conn.execute(text("DELETE FROM schema_meta WHERE key = 'version'"))
    conn.execute(text("INSERT INTO schema_meta (key, value) VALUES ('version', :v)"), {"v": version})


def migrate_schema() -> None:
    with engine.begin() as conn:
        if conn.dialect.name == "sqlite":
            conn.exec_driver_sql("PRAGMA foreign_keys=OFF")
        Base.metadata.create_all(bind=conn)
        _add_missing_columns(conn)
        _make_score_columns_nullable(conn)
        if _schema_version(conn) < MIGRATION_VERSION:
            _clean_legacy_zero_scores(conn)
            _set_schema_version(conn, MIGRATION_VERSION)


@contextmanager
def _startup_lock():
    """Several uvicorn workers may start together; on PostgreSQL only one of them
    migrates and seeds at a time (session-level advisory lock)."""
    if engine.dialect.name != "postgresql":
        yield
        return
    with engine.connect() as conn:
        conn.execute(text("SELECT pg_advisory_lock(724001)"))
        conn.commit()
        try:
            yield
        finally:
            conn.execute(text("SELECT pg_advisory_unlock(724001)"))
            conn.commit()


# ---------------------------------------------------------------------------
# Model availability
# ---------------------------------------------------------------------------

def _spacy_ner_loaded() -> bool:
    try:
        return resume_parser._get_nlp() is not None
    except Exception:
        return False


def _semantic_available() -> bool:
    try:
        return bool(model_available())
    except Exception:
        return False


def _backfill_existing_rows(db) -> None:
    """Bring rows created before the platform features up to date (idempotent)."""
    from .services import credits_service
    from .services.interview_service import to_utc
    for hr in db.query(models.HRAccount).all():
        credits_service.grant_signup_bonus(db, "hr", hr.account_id)   # reference-keyed: never twice
        if not db.query(models.Company).filter(models.Company.hr_account_id == hr.account_id).first():
            db.add(models.Company(hr_account_id=hr.account_id, name=hr.company, verification_status="unverified"))
    for cand in db.query(models.CandidateAccount).all():
        # Candidates created before the credits ledger existed had 0 credits (ATS checks failed with 402).
        credits_service.grant_signup_bonus(db, "candidate", cand.account_id)
    for iv in db.query(models.InterviewSchedule).filter(models.InterviewSchedule.scheduled_at_utc.is_(None)).all():
        try:
            iv.scheduled_at_utc = to_utc(iv.date, iv.time, iv.timezone or "Asia/Kolkata")
            iv.timezone = iv.timezone or "Asia/Kolkata"
            iv.reminder_status = iv.reminder_status or "pending"
        except Exception:
            pass
    db.commit()


def _seed_platform_data() -> None:
    """Idempotent: initial admin, built-in coding problems, default offer template."""
    from .services.coding_library import seed_library
    from .services.offer_service import ensure_default_template
    db = SessionLocal()
    try:
        admin.ensure_admin_account(db)
        seed_library(db)
        ensure_default_template(db)
        _backfill_existing_rows(db)
    finally:
        db.close()


def _maybe_seed_demo() -> None:
    """SEED_DEMO_DATA=true loads the demo companies, jobs and candidates once (if absent)."""
    if os.getenv("SEED_DEMO_DATA", "false").lower() != "true":
        return
    from . import seed_demo
    db = SessionLocal()
    try:
        if not seed_demo._demo_ids(db)[0]:
            logger.info("SEED_DEMO_DATA=true: loading demo data (one time)…")
            seed_demo.seed(db)
    except Exception:  # noqa: BLE001 - demo data must never stop the server
        db.rollback()
        logger.exception("Demo data could not be loaded")
    finally:
        db.close()


with _startup_lock():
    migrate_schema()
    _seed_platform_data()
    _maybe_seed_demo()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    from .scheduler.jobs import start_background_scheduler, stop_background_scheduler
    from .services import code_runner
    from .services.config import smtp_configured
    with SessionLocal() as _db:
        logger.info("Database: %s (%d candidate / %d HR accounts) — data persists across restarts",
                    safe_url(), _db.query(models.CandidateAccount).count(), _db.query(models.HRAccount).count())
    logger.info("SMTP configured: %s", smtp_configured())
    logger.info("Code sandbox: %s", code_runner.sandbox_info())
    logger.info("GROQ_API_KEY configured: %s", bool(os.getenv("GROQ_API_KEY")))
    logger.info("spaCy NER model loaded: %s", str(_spacy_ner_loaded()).lower())
    logger.info("semantic model available: %s", str(_semantic_available()).lower())
    start_background_scheduler()
    yield
    stop_background_scheduler()


app = FastAPI(title="Agentic Hiring System API", lifespan=lifespan)


@app.exception_handler(SQLAlchemyError)
async def _db_error(request: Request, exc: SQLAlchemyError):
    logger.exception("Database error on %s %s", request.method, request.url.path)
    return JSONResponse(status_code=503, content={"detail": "The database is temporarily unavailable. Please try again."})


@app.middleware("http")
async def _unhandled_errors(request: Request, call_next):
    # Registered before CORS so the error response still carries CORS headers.
    # The traceback goes to the server log only; the client never sees internals.
    try:
        return await call_next(request)
    except Exception:
        logger.exception("Unhandled error on %s %s", request.method, request.url.path)
        return JSONResponse(status_code=500, content={"detail": "Something went wrong on our side. Please try again."})


_origins = [o.strip() for o in os.getenv("FRONTEND_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173").split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(jobs.router)
app.include_router(candidates.router)
app.include_router(resumes.router)
app.include_router(assessments.router)
app.include_router(interviews.router)
app.include_router(auth.router)
for _router in (profile.router, settings_routes.router, notifications.router, offers.router, coding.router, ats.router,
                referrals.router, support.router, billing.router, dashboard.router, admin.router,
                assessment_templates.router, practice.router):
    app.include_router(_router)


@app.get("/")
def root():
    return {"status": "ok", "service": "Agentic Hiring System API"}


@app.get("/health")
def health():
    """Configuration/model health. Never returns secret values."""
    db_ok = True
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception:
        logger.exception("Database health check failed")
        db_ok = False
    from .scheduler.jobs import scheduler_status
    from .services import code_runner, config as cfg
    return {
        "status": "ok" if db_ok else "degraded",
        "database_ok": db_ok,
        "groq_api_key_configured": bool(os.getenv("GROQ_API_KEY")),
        "spacy_ner_loaded": _spacy_ner_loaded(),
        "semantic_model_available": _semantic_available(),
        "smtp_configured": cfg.smtp_configured(),
        "payments_configured": cfg.payments_configured(),
        "scheduler": {k: v for k, v in scheduler_status().items() if k != "last_result"},
        "code_sandbox": code_runner.sandbox_info(),
        "code_languages": [lang["key"] for lang in code_runner.available_languages()],
    }
