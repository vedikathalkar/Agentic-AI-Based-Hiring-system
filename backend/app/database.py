import os
from pathlib import Path
from dotenv import load_dotenv

# backend/ directory, derived from this file so it never depends on the CWD.
BASE_DIR = Path(__file__).resolve().parent.parent

load_dotenv(BASE_DIR / ".env")
load_dotenv(BASE_DIR.parent / ".env", override=False)

from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import sessionmaker, declarative_base

import logging

logger = logging.getLogger("hirelune.db")

# PostgreSQL is the default database. Override with DATABASE_URL, e.g.
#   postgresql+psycopg2://hirelune:secret@localhost:5432/hirelune
#   sqlite:///hiring.db            (relative paths resolve against backend/; used by the tests)
DEFAULT_DATABASE_URL = "postgresql+psycopg2://postgres:postgres@localhost:5432/hirelune"


def _resolve_database_url(raw: str | None) -> str:
    url = (raw or "").strip() or DEFAULT_DATABASE_URL
    # Heroku/Render style URLs; SQLAlchemy 2 only accepts "postgresql".
    if url.startswith("postgres://"):
        url = "postgresql+psycopg2://" + url[len("postgres://"):]
    elif url.startswith("postgresql://"):
        url = "postgresql+psycopg2://" + url[len("postgresql://"):]
    prefix = "sqlite:///"
    if url.startswith(prefix):
        path = url[len(prefix):]
        if path and path != ":memory:" and not Path(path).is_absolute():
            return f"{prefix}{(BASE_DIR / path).resolve()}"
    return url


SQLALCHEMY_DATABASE_URL = _resolve_database_url(os.getenv("DATABASE_URL"))
IS_SQLITE = SQLALCHEMY_DATABASE_URL.startswith("sqlite")
IS_POSTGRES = SQLALCHEMY_DATABASE_URL.startswith("postgresql")


def safe_url(url: str = SQLALCHEMY_DATABASE_URL) -> str:
    """The URL with the password hidden, for logs."""
    from sqlalchemy.engine import make_url
    try:
        return make_url(url).render_as_string(hide_password=True)
    except Exception:
        return url.split("@")[-1]


def ensure_postgres_database(url: str = SQLALCHEMY_DATABASE_URL) -> None:
    """Create the PostgreSQL database named in the URL if it does not exist yet
    (needs a role with CREATEDB; otherwise create it in pgAdmin first)."""
    if not url.startswith("postgresql"):
        return
    from sqlalchemy.engine import make_url
    from sqlalchemy.exc import OperationalError, ProgrammingError
    target = make_url(url)
    admin_engine = create_engine(target.set(database="postgres"), isolation_level="AUTOCOMMIT")
    try:
        with admin_engine.connect() as conn:
            exists = conn.execute(text("SELECT 1 FROM pg_database WHERE datname = :n"), {"n": target.database}).scalar()
            if not exists:
                conn.execute(text(f'CREATE DATABASE "{target.database}"'))
                logger.info("Created PostgreSQL database %s", target.database)
    except (OperationalError, ProgrammingError) as exc:
        logger.warning("Could not check/create database %s automatically: %s", target.database, exc.__class__.__name__)
    finally:
        admin_engine.dispose()


if IS_SQLITE:
    if ":memory:" not in SQLALCHEMY_DATABASE_URL:
        Path(SQLALCHEMY_DATABASE_URL[len("sqlite:///"):]).parent.mkdir(parents=True, exist_ok=True)
    # timeout: wait for the scheduler thread's writes instead of failing with "database is locked".
    engine = create_engine(SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False, "timeout": 30})

    @event.listens_for(engine, "connect")
    def _sqlite_pragmas(dbapi_conn, _record):
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")      # readers don't block the writer
        cur.execute("PRAGMA synchronous=NORMAL")
        cur.close()
else:
    if IS_POSTGRES and os.getenv("DB_AUTO_CREATE", "true").lower() != "false":
        ensure_postgres_database()
    engine = create_engine(SQLALCHEMY_DATABASE_URL, pool_pre_ping=True, pool_size=int(os.getenv("DB_POOL_SIZE", "10")),
                           max_overflow=int(os.getenv("DB_MAX_OVERFLOW", "20")), pool_recycle=1800)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
