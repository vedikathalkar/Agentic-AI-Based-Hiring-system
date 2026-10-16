"""Environment-driven configuration. Nothing secret is ever returned to clients."""

import os
from datetime import datetime
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[2]


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


def _bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None or raw == "":
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def storage_dir() -> Path:
    """Private file storage (never served statically)."""
    path = Path(os.getenv("STORAGE_DIR") or (BACKEND_DIR / "storage"))
    if not path.is_absolute():
        path = BACKEND_DIR / path
    path.mkdir(parents=True, exist_ok=True)
    return path


def frontend_url() -> str:
    return (os.getenv("FRONTEND_URL") or "http://localhost:5173").rstrip("/")


def app_name() -> str:
    return os.getenv("APP_NAME") or "Hirelune"


# ---- SMTP ------------------------------------------------------------------

def smtp_settings() -> dict:
    return {
        "host": os.getenv("SMTP_HOST", "").strip(),
        "port": _int("SMTP_PORT", 587),
        "username": os.getenv("SMTP_USERNAME", "").strip(),
        "password": os.getenv("SMTP_PASSWORD", ""),
        "from_email": (os.getenv("SMTP_FROM_EMAIL") or os.getenv("SMTP_USERNAME") or "").strip(),
        "from_name": os.getenv("SMTP_FROM_NAME") or app_name(),
        "use_tls": _bool("SMTP_USE_TLS", True),
        "use_ssl": _bool("SMTP_USE_SSL", False),
        "timeout": _int("SMTP_TIMEOUT", 20),
    }


def smtp_configured() -> bool:
    s = smtp_settings()
    return bool(s["host"] and s["from_email"])


# ---- Credits / billing -----------------------------------------------------

CREDIT_COSTS = {
    "candidate_unlock": _int("CREDIT_COST_CANDIDATE_UNLOCK", 10),
    "ai_assessment": _int("CREDIT_COST_AI_ASSESSMENT", 5),
    "offer_letter": _int("CREDIT_COST_OFFER_LETTER", 0),
    "ats_check": _int("CREDIT_COST_ATS_CHECK", 0),
}
HR_SIGNUP_CREDITS = _int("HR_SIGNUP_CREDITS", 1000)
CANDIDATE_SIGNUP_CREDITS = _int("CANDIDATE_SIGNUP_CREDITS", 100)
REFERRAL_REWARD_CREDITS = _int("REFERRAL_REWARD_CREDITS", 50)
CREDIT_PACKS = [200, 500, 750, 1000, 1500, 2500]
PRICE_PER_CREDIT_PAISE = _int("PRICE_PER_CREDIT_PAISE", 100)  # 1 credit = ₹1
EARLY_BIRD_PERCENT = _int("EARLY_BIRD_DISCOUNT_PERCENT", 10)
EARLY_BIRD_UNTIL = os.getenv("EARLY_BIRD_UNTIL", "2026-11-30")


def early_bird_active(now: datetime | None = None) -> bool:
    now = now or datetime.utcnow()
    try:
        until = datetime.strptime(EARLY_BIRD_UNTIL, "%Y-%m-%d")
    except ValueError:
        return False
    return EARLY_BIRD_PERCENT > 0 and now.date() <= until.date()


def razorpay_keys() -> tuple[str, str]:
    return os.getenv("RAZORPAY_KEY_ID", "").strip(), os.getenv("RAZORPAY_KEY_SECRET", "").strip()


def payments_configured() -> bool:
    key_id, secret = razorpay_keys()
    return bool(key_id and secret)


# ---- Scheduler / assessments ----------------------------------------------

def scheduler_enabled() -> bool:
    return _bool("SCHEDULER_ENABLED", True)


def scheduler_interval_seconds() -> int:
    return max(15, _int("SCHEDULER_INTERVAL_SECONDS", 60))


ASSESSMENT_GRACE_SECONDS = _int("ASSESSMENT_GRACE_SECONDS", 30)
# Proctoring: the assessment ends automatically on this many strikes (tab switches, fullscreen exits, face/voice issues).
PROCTORING_ENABLED = _bool("PROCTORING_ENABLED", True)
PROCTOR_MAX_STRIKES = max(1, _int("PROCTOR_MAX_STRIKES", 3))
OFFER_VALID_DAYS = _int("OFFER_VALID_DAYS", 14)
DEFAULT_TIMEZONE = os.getenv("DEFAULT_TIMEZONE", "Asia/Kolkata")
