import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# Isolated database + storage; never touch backend/hiring.db.
TEST_DB = Path(__file__).parent / "test_hirelune.db"
# Tests use a throw-away SQLite file by default. To run them against PostgreSQL, point
# TEST_DATABASE_URL at an EMPTY scratch database (all tables are dropped and recreated).
os.environ["DATABASE_URL"] = os.getenv("TEST_DATABASE_URL") or f"sqlite:///{TEST_DB}"
os.environ["STORAGE_DIR"] = str(Path(__file__).parent / "_storage")
os.environ.setdefault("GROQ_API_KEY", "test-key")
os.environ["SCHEDULER_ENABLED"] = "false"          # tests drive jobs explicitly
os.environ["PROCTORING_ENABLED"] = "false"         # existing flows start assessments without the browser pre-check; test_proctoring.py turns it on
os.environ["ADMIN_USERNAME"] = "nehadhumal"
os.environ["ADMIN_PASSWORD"] = "admin"
for key in ("SMTP_HOST", "SMTP_FROM_EMAIL", "SMTP_USERNAME", "SMTP_PASSWORD", "RAZORPAY_KEY_ID", "RAZORPAY_KEY_SECRET"):
    os.environ.pop(key, None)

PDF = b"%PDF-1.4 fake resume"


@pytest.fixture
def client():
    # Imported lazily so the pure unit tests do not need the web stack.
    from fastapi.testclient import TestClient
    from app.database import Base, engine
    from app import main

    engine.dispose()
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    main._seed_platform_data()
    with TestClient(main.app) as c:
        yield c
    engine.dispose()
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def outbox(monkeypatch):
    """Capture emails instead of talking to an SMTP server (SMTP counts as configured)."""
    from app.services import config, email_service
    sent = []
    monkeypatch.setattr(config, "smtp_configured", lambda: True)

    def fake_send(to, subject, html, text, attachment_path, attachment_name):
        sent.append({"to": to, "subject": subject, "html": html, "text": text,
                     "attachment": attachment_name if attachment_path else None})
    monkeypatch.setattr(email_service, "_smtp_send", fake_send)
    return sent


# ---- account helpers --------------------------------------------------------------

def auth(token):
    return {"Authorization": f"Bearer {token}"}


def signup_candidate(client, email="cand@example.com", name="Test Candidate", ref=None):
    r = client.post("/auth/candidate/signup", json={"name": name, "email": email, "password": "secret1",
                                                   "referral_code": ref})
    assert r.status_code == 200, r.text
    r = client.post("/auth/candidate/login", json={"email": email, "password": "secret1"})
    assert r.status_code == 200, r.text
    return r.json()["token"]


def signup_hr(client, email="hr@acme.com", name="Neha HR", company="Acme Analytics"):
    r = client.post("/auth/hr/signup", json={"name": name, "company": company, "email": email, "password": "secret1"})
    assert r.status_code == 200, r.text
    r = client.post("/auth/hr/login", json={"email": email, "password": "secret1"})
    assert r.status_code == 200, r.text
    return r.json()["token"]


def admin_token(client):
    r = client.post("/auth/admin/login", json={"username": "nehadhumal", "password": "admin"})
    assert r.status_code == 200, r.text
    return r.json()["token"]


PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 64


def complete_hr_profile(client, token):
    r = client.put("/hr/profile", headers=auth(token), json={
        "phone": "+91 90000 00000", "designation": "Talent Lead",
        "company": {"name": "Acme Analytics", "official_email": "careers@acme.com", "website": "https://acme.example",
                    "industry": "Software", "company_size": "51-200", "headquarters": "Pune",
                    "description": "Analytics products", "contact_number": "+91 20 0000 0000"}})
    assert r.status_code == 200, r.text
    assert client.post("/hr/company/logo", headers=auth(token), files={"file": ("logo.png", PNG, "image/png")}).status_code == 200
    r = client.post("/hr/company/documents", headers=auth(token), data={"doc_type": "id_proof"},
                    files={"file": ("id.pdf", PDF, "application/pdf")})
    assert r.status_code == 200, r.text


def verified_hr(client, email="hr@acme.com"):
    token = signup_hr(client, email=email)
    complete_hr_profile(client, token)
    r = client.post("/hr/verification", headers=auth(token))
    assert r.status_code == 200, r.text
    admin = admin_token(client)
    company_id = client.get("/hr/profile", headers=auth(token)).json()["company"]["company_id"]
    r = client.post(f"/admin/verifications/{company_id}/approve", headers=auth(admin))
    assert r.status_code == 200, r.text
    return token
