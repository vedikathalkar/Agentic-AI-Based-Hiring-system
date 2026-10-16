"""Platform features end-to-end: profiles, verification, settings/theme, notifications,
SMTP emails, interviews + reminders, offers, coding assessments, ATS, referrals,
support, billing/credits and authorization. Only Groq + resume parsing are patched;
SMTP is replaced by an in-memory outbox (or left unconfigured to test failures)."""

import io
from datetime import datetime, timedelta

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("sqlalchemy")
pytest.importorskip("langgraph")

from conftest import PDF, admin_token, auth, signup_candidate, signup_hr, verified_hr  # noqa: E402
from test_e2e_scores import ALL_RIGHT, JOB, World, _questions  # noqa: E402,F401
from test_e2e_scores import pipeline  # noqa: E402,F401  (fixture)


def _future(days=3, hour="10:30"):
    return (datetime.utcnow() + timedelta(days=days)).strftime("%Y-%m-%d"), hour


# ---- profiles & verification -------------------------------------------------------

def test_candidate_profile_completion_is_computed_from_saved_fields(client):
    token = signup_candidate(client)
    p = client.get("/candidate/profile", headers=auth(token)).json()
    assert p["completion"]["percent"] < 100
    missing = {s["key"] for s in p["completion"]["sections"] if not s["complete"]}
    assert {"education", "experience", "skills", "resume"} <= missing

    r = client.put("/candidate/profile", headers=auth(token), json={
        "phone": "+91 98200 00000", "location": "Pune", "linkedin": "https://linkedin.com/in/x",
        "education": [{"degree": "B.Tech", "institution": "COEP", "graduation_year": "2024"}],
        "experience": [{"company": "Acme", "role": "Intern", "current": False}],
        "technical_skills": ["Python", "SQL", "python", "Tableau"],
        "projects": [{"name": "Forecasting", "technologies": "Python"}],
        "certifications": [{"name": "AWS CCP", "issuer": "AWS"}]})
    assert r.status_code == 200
    body = r.json()
    assert body["technical_skills"] == ["Python", "SQL", "Tableau"]   # de-duplicated
    assert body["completion"]["percent"] == 80                        # everything except resume (20)
    r = client.post("/candidate/profile/resume", headers=auth(token), files={"file": ("cv.pdf", PDF, "application/pdf")})
    assert r.json()["completion"]["percent"] == 100
    # Persisted across logins.
    token2 = client.post("/auth/candidate/login", json={"email": "cand@example.com", "password": "secret1"}).json()["token"]
    assert client.get("/candidate/profile", headers=auth(token2)).json()["completion"]["percent"] == 100


def test_hr_verification_workflow(client, outbox):
    from conftest import complete_hr_profile
    hr = signup_hr(client)
    v = client.get("/hr/verification", headers=auth(hr)).json()
    assert v["state"] == "profile_incomplete" and v["status"] == "unverified"
    assert client.post("/hr/verification", headers=auth(hr)).status_code == 422   # not ready
    complete_hr_profile(client, hr)
    assert client.get("/hr/verification", headers=auth(hr)).json()["state"] == "verification_required"
    r = client.post("/hr/verification", headers=auth(hr))
    assert r.status_code == 200 and r.json()["status"] == "pending" and r.json()["submitted_at"]
    assert client.post("/hr/verification", headers=auth(hr)).status_code == 409   # no double submit
    assert client.post("/jobs", json=JOB, headers=auth(hr)).status_code == 403     # pending != verified

    admin = admin_token(client)
    queue = client.get("/admin/verifications", headers=auth(admin)).json()
    company_id = queue[0]["company_id"]
    assert client.post(f"/admin/verifications/{company_id}/reject", headers=auth(admin),
                       json={"reason": "ID proof is unreadable"}).status_code == 200
    v = client.get("/hr/verification", headers=auth(hr)).json()
    assert v["status"] == "rejected" and v["rejection_reason"] == "ID proof is unreadable"
    client.post("/hr/verification", headers=auth(hr))
    assert client.post(f"/admin/verifications/{company_id}/approve", headers=auth(admin)).status_code == 200
    v = client.get("/hr/verification", headers=auth(hr)).json()
    assert v["status"] == "verified" and v["verified_at"]
    assert client.post("/jobs", json=JOB, headers=auth(hr)).status_code == 200
    assert any("verified" in m["subject"].lower() for m in outbox)
    assert client.get("/notifications", headers=auth(hr)).json()["unread"] >= 1
    # Only admins review verifications.
    assert client.post(f"/admin/verifications/{company_id}/approve", headers=auth(hr)).status_code == 403


def test_documents_are_private(client):
    hr = verified_hr(client)
    other = signup_hr(client, email="other@hr.com")
    doc_id = client.get("/hr/profile", headers=auth(hr)).json()["company"]["documents"][0]["document_id"]
    assert client.get(f"/hr/company/documents/{doc_id}", headers=auth(hr)).status_code == 200
    assert client.get(f"/hr/company/documents/{doc_id}", headers=auth(other)).status_code == 404
    assert client.get(f"/hr/company/documents/{doc_id}", headers=auth(admin_token(client))).status_code == 200


# ---- settings / theme / notifications ------------------------------------------------

def test_theme_and_settings_persist_across_login(client):
    token = signup_candidate(client)
    assert client.put("/settings", headers=auth(token), json={"theme": "dark", "marketing_notifications": True}).status_code == 200
    client.post("/auth/logout", headers=auth(token))
    assert client.get("/settings", headers=auth(token)).status_code == 401
    login = client.post("/auth/candidate/login", json={"email": "cand@example.com", "password": "secret1"}).json()
    assert login["theme"] == "dark"
    prefs = client.get("/settings", headers=auth(login["token"])).json()["preferences"]
    assert prefs["theme"] == "dark" and prefs["marketing_notifications"] is True
    assert client.put("/settings", headers=auth(login["token"]), json={"theme": "blue"}).status_code == 422


def test_password_change(client):
    token = signup_candidate(client)
    assert client.post("/auth/password", headers=auth(token), json={"current_password": "nope", "new_password": "newpass1"}).status_code == 400
    assert client.post("/auth/password", headers=auth(token), json={"current_password": "secret1", "new_password": "newpass1"}).status_code == 200
    assert client.post("/auth/candidate/login", json={"email": "cand@example.com", "password": "newpass1"}).status_code == 200


# ---- assessment emails + coding -------------------------------------------------------

def test_assessment_start_sends_emails_only_on_explicit_start(client, pipeline, outbox):
    w = World(client)
    w.upload()
    assert not [m for m in outbox if "Assessment" in m["subject"]]
    w.c_post(f"/assessments/start/{w.aid}")
    subjects = [m["subject"] for m in outbox]
    assert any(s.startswith("Assessment started") for s in subjects)            # candidate
    assert any("started the" in s for s in subjects)                             # HR
    kinds = [n["type"] for n in client.get("/notifications", headers=auth(w.cand)).json()["items"]]
    assert "assessment_started" in kinds
    # AI assessment was billed to the employer once.
    tx = client.get("/billing/transactions", headers=auth(w.hr)).json()["items"]
    assert sum(1 for t in tx if "AI assessment" in (t["description"] or "")) == 1


def test_coding_question_run_submit_and_grading(client, pipeline):
    from app.services import code_runner
    if not code_runner.is_available("python"):
        pytest.skip("python sandbox unavailable")
    w = World(client, job=dict(JOB, coding_questions=1))
    w.upload()
    body = w.c_post(f"/assessments/start/{w.aid}").json()
    coding = [q for q in body["questions"] if q["type"] == "coding"]
    assert len(coding) == 1
    q = coding[0]
    assert q["coding"]["sample_tests"] and q["coding"]["hidden_test_count"] >= 3
    assert "hidden_tests" not in q["coding"]
    slug_solutions = {
        "Category Totals": "import sys\nfrom collections import defaultdict\nd=sys.stdin.read().split();n=int(d[0]);t=defaultdict(int)\nfor i in range(n): t[d[1+2*i]]+=int(d[2+2*i])\nfor k,v in sorted(t.items(),key=lambda x:(-x[1],x[0])): print(k,v)",
        "Sum of Numbers": "n=int(input());print(sum(map(int,input().split())))",
    }
    source = slug_solutions.get(q["question"], "print('x')")
    run = w.c_post("/coding/run", json={"application_id": w.aid, "question_index": q["index"], "language": "python", "source": source}).json()
    assert run["kind"] == "run" and all(not t["hidden"] for t in run["tests"])
    sub = w.c_post("/coding/submit", json={"application_id": w.aid, "question_index": q["index"], "language": "python", "source": source}).json()
    assert sub["hidden_total"] >= 3
    assert all("input" not in t for t in sub["tests"] if t["hidden"])           # hidden cases never exposed
    result = w.c_post(f"/assessments/submit/{w.aid}", json=ALL_RIGHT).json()
    coding_result = [r for r in result["results"] if r["type"] == "coding"][0]
    assert coding_result["feedback"].startswith(f"{sub['passed']} / {sub['total']}")
    hr_view = w.hr_get(f"/candidates/{w.cid}/assessment").json()
    assert [x for x in hr_view["questions"] if x["type"] == "coding"][0]["coding"]["source_code"] == source


def test_timer_expiry_auto_submits_saved_answers(client, pipeline):
    from app import models
    from app.database import SessionLocal
    from app.scheduler.jobs import run_due_jobs
    w = World(client)
    w.upload()
    w.c_post(f"/assessments/start/{w.aid}")
    client.put(f"/assessments/progress/{w.aid}", headers=auth(w.cand), json={"answers": {"0": "A"}})
    with SessionLocal() as db:
        a = db.query(models.Assessment).filter(models.Assessment.application_id == w.aid).one()
        a.expires_at = datetime.utcnow() - timedelta(minutes=5)
        db.commit()
    assert client.put(f"/assessments/progress/{w.aid}", headers=auth(w.cand), json={"answers": {"1": "B"}}).status_code == 409
    run_due_jobs()
    status = client.get(f"/assessments/status/{w.aid}", headers=auth(w.cand)).json()
    assert status["status"] == "completed" and status["auto_submitted"] is True
    assert status["test_score"] == 50.0                     # only the answer saved in time counts
    assert w.c_post(f"/assessments/submit/{w.aid}", json=ALL_RIGHT).status_code == 409


# ---- interviews + reminders -------------------------------------------------------------

def _shortlist(w):
    r = w.client.patch(f"/candidates/applications/{w.aid}/status", headers=auth(w.hr), json={"status": "shortlisted"})
    assert r.status_code == 200, r.text


def test_interview_schedule_emails_both_parties(client, pipeline, outbox):
    w = World(client)
    w.upload()
    _shortlist(w)
    date, time = _future()
    r = client.post("/interviews", headers=auth(w.hr), json={
        "application_id": w.aid, "date": date, "time": time, "timezone": "Asia/Kolkata", "mode": "Google Meet",
        "meeting_link": "https://meet.example/abc", "interviewer": "Priya"})
    assert r.status_code == 200, r.text
    iv = r.json()
    assert iv["status"] == "scheduled" and iv["timezone"] == "Asia/Kolkata"
    to = {m["to"] for m in outbox if m["subject"].startswith("Interview scheduled")}
    assert to == {"test@example.com", "hr@acme.com"}
    cand_list = client.get("/interviews?scope=upcoming", headers=auth(w.cand)).json()
    assert [x["schedule_id"] for x in cand_list] == [iv["schedule_id"]]
    assert "notes" not in cand_list[0]                                  # HR-only field
    assert client.get("/dashboard/hr", headers=auth(w.hr)).json()["stats"]["scheduled_interviews"] == 1
    assert client.get("/dashboard/candidate", headers=auth(w.cand)).json()["stats"]["upcoming_interviews"] == 1
    # Double booking the same slot for the same candidate is refused.
    assert client.post("/interviews", headers=auth(w.hr), json={"application_id": w.aid, "date": date, "time": time}).status_code == 409


def test_interview_saved_even_when_email_fails(client, pipeline):
    """SMTP is not configured here: the interview must persist and the email is logged as failed."""
    w = World(client)
    w.upload()
    _shortlist(w)
    date, time = _future()
    r = client.post("/interviews", headers=auth(w.hr), json={"application_id": w.aid, "date": date, "time": time})
    assert r.status_code == 200
    assert client.get(f"/interviews/{r.json()['schedule_id']}", headers=auth(w.hr)).json()["status"] == "scheduled"
    logs = client.get("/email/logs", headers=auth(w.hr)).json()
    interview_logs = [e for e in logs if e["related_type"] == "interview"]
    assert interview_logs and all(e["status"] == "failed" for e in interview_logs)
    assert "SMTP is not configured" in interview_logs[0]["error"]


def test_reminder_sent_once_one_day_before(client, pipeline, outbox):
    from app import models
    from app.database import SessionLocal
    from app.services.interview_service import process_due_reminders
    w = World(client)
    w.upload()
    _shortlist(w)
    date, time = _future(days=3)
    sid = client.post("/interviews", headers=auth(w.hr), json={"application_id": w.aid, "date": date, "time": time}).json()["schedule_id"]
    with SessionLocal() as db:
        assert process_due_reminders(db) == 0                       # 3 days away: not yet
        iv = db.get(models.InterviewSchedule, sid)
        iv.scheduled_at_utc = datetime.utcnow() + timedelta(hours=23)  # now inside the 24h window
        db.commit()
        assert process_due_reminders(db) == 1
        assert process_due_reminders(db) == 0                       # second run: nothing
        assert db.get(models.InterviewSchedule, sid).reminder_status == "sent"
    reminders = [m for m in outbox if m["subject"].startswith("Reminder: Interview Tomorrow")]
    assert {m["to"] for m in reminders} == {"test@example.com", "hr@acme.com"}
    assert len(reminders) == 2


def test_cancelled_interview_gets_no_reminder(client, pipeline):
    from app import models
    from app.database import SessionLocal
    from app.services.interview_service import process_due_reminders
    w = World(client)
    w.upload()
    _shortlist(w)
    date, time = _future(days=3)
    sid = client.post("/interviews", headers=auth(w.hr), json={"application_id": w.aid, "date": date, "time": time}).json()["schedule_id"]
    assert client.delete(f"/interviews/{sid}", headers=auth(w.hr)).json()["status"] == "cancelled"
    with SessionLocal() as db:
        iv = db.get(models.InterviewSchedule, sid)
        iv.scheduled_at_utc = datetime.utcnow() + timedelta(hours=10)
        db.commit()
        assert process_due_reminders(db) == 0


# ---- offers -----------------------------------------------------------------------------

def test_offer_lifecycle(client, pipeline, outbox):
    w = World(client)
    w.upload()
    _shortlist(w)
    assert client.post("/offers", headers=auth(w.hr), json={"application_id": w.aid}).status_code == 409   # unlock first
    assert client.post(f"/candidates/{w.cid}/unlock", headers=auth(w.hr)).status_code == 200
    r = client.post("/offers", headers=auth(w.hr), json={"application_id": w.aid, "fields": {"ctc_amount": "₹6,00,000"}})
    assert r.status_code == 200, r.text
    offer = r.json()
    assert offer["status"] == "draft" and "joining_date" in offer["unresolved"]
    assert client.get(f"/offers/{offer['offer_id']}", headers=auth(w.cand)).status_code == 404   # drafts are private
    assert client.post(f"/offers/{offer['offer_id']}/send", headers=auth(w.hr)).status_code == 422
    r = client.put(f"/offers/{offer['offer_id']}", headers=auth(w.hr), json={
        "fields": {"joining_date": "01 Dec 2026", "reporting_manager": "Priya"},
        "template_content": "Dear {{candidate_name}}, join {{company_name}} as {{job_title}} on {{joining_date}} for {{ctc_amount}}."})
    assert "01 Dec 2026" in r.json()["content"]
    sent = client.post(f"/offers/{offer['offer_id']}/send", headers=auth(w.hr)).json()
    assert sent["status"] == "sent" and sent["has_pdf"]
    mail = [m for m in outbox if m["subject"].startswith("Offer Letter")][0]
    assert mail["to"] == "test@example.com" and mail["attachment"].endswith(".pdf")
    assert client.put(f"/offers/{offer['offer_id']}", headers=auth(w.hr), json={"fields": {"ctc_amount": "1"}}).status_code == 409

    mine = client.get("/offers", headers=auth(w.cand)).json()
    assert [o["offer_id"] for o in mine] == [offer["offer_id"]]
    viewed = client.get(f"/offers/{offer['offer_id']}", headers=auth(w.cand)).json()
    assert viewed["status"] == "viewed" and "template_content" not in viewed
    pdf = client.get(f"/offers/{offer['offer_id']}/pdf", headers=auth(w.cand))
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")
    accepted = client.post(f"/offers/{offer['offer_id']}/respond", headers=auth(w.cand), json={"decision": "accept"}).json()
    assert accepted["status"] == "accepted" and accepted["accepted_at"]
    assert client.post(f"/offers/{offer['offer_id']}/respond", headers=auth(w.cand), json={"decision": "reject"}).status_code == 409
    assert w.hr_get(f"/candidates/{w.cid}").json()["applications"][0]["status"] == "hired"
    assert any(m["subject"].startswith("Offer accepted") for m in outbox)


def test_revising_a_sent_offer_keeps_history(client, pipeline, outbox):
    w = World(client)
    w.upload()
    _shortlist(w)
    client.post(f"/candidates/{w.cid}/unlock", headers=auth(w.hr))
    oid = client.post("/offers", headers=auth(w.hr), json={"application_id": w.aid, "fields": {
        "ctc_amount": "₹6,00,000", "joining_date": "01 Dec 2026", "reporting_manager": "Priya",
        "department": "Analytics", "location": "Pune"}}).json()["offer_id"]
    client.post(f"/offers/{oid}/send", headers=auth(w.hr))
    draft = client.post(f"/offers/{oid}/revise", headers=auth(w.hr)).json()
    assert draft["status"] == "draft" and draft["revision_of_id"] == oid
    client.put(f"/offers/{draft['offer_id']}", headers=auth(w.hr), json={"fields": {"ctc_amount": "₹7,00,000"}})
    client.post(f"/offers/{draft['offer_id']}/send", headers=auth(w.hr))
    old = client.get(f"/offers/{oid}", headers=auth(w.hr)).json()
    assert old["status"] == "withdrawn" and "₹6,00,000" in old["content"]


# ---- ATS / referrals / support / billing --------------------------------------------------

def _docx_bytes(text):
    from docx import Document
    doc = Document()
    for line in text.splitlines():
        doc.add_paragraph(line)
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def test_ats_check_endpoint(client):
    hr = verified_hr(client)
    job_id = client.post("/jobs", json=JOB, headers=auth(hr)).json()["job_id"]
    token = signup_candidate(client)
    resume = _docx_bytes("Neha\nneha@x.com\nExperience\nBuilt Python and SQL dashboards, reduced time by 30%\nEducation\nB.Tech\nSkills\nPython, SQL")
    r = client.post("/ats/check", headers=auth(token), data={"job_id": str(job_id)},
                    files={"file": ("cv.docx", resume, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")})
    assert r.status_code == 200, r.text
    rep = r.json()
    assert rep["label"] == "Hirelune ATS analysis"
    assert set(rep["keywords"]["matched"]) == {"SQL", "Python"} and rep["keywords"]["missing"] == ["Tableau"]
    assert client.get("/ats/checks", headers=auth(token)).json()["checks"][0]["check_id"] == rep["check_id"]
    assert client.get("/candidate/profile", headers=auth(token)).json()["resume_file_name"] is None   # not modified


def test_referral_reward_only_after_qualifying_event(client, pipeline):
    referrer = signup_candidate(client, email="ref@example.com", name="Neha Dhumal")
    info = client.post("/referrals", headers=auth(referrer)).json()
    assert info["code"].startswith("HIRL-NEHA-")
    start_balance = info["credit_balance"]
    hr = verified_hr(client)
    friend = signup_candidate(client, email="friend@example.com", ref=info["code"])
    summary = client.get("/referrals", headers=auth(referrer)).json()
    assert summary["pending"] == 1 and summary["successful"] == 0 and summary["credit_balance"] == start_balance
    job_id = client.post("/jobs", json=JOB, headers=auth(hr)).json()["job_id"]
    app = client.post("/candidates", headers=auth(friend), json={"name": "Friend", "email": "friend@example.com", "job_id": job_id}).json()
    client.post(f"/resumes/{app['candidate_id']}", headers=auth(friend), files={"file": ("r.pdf", PDF, "application/pdf")})
    client.post(f"/assessments/start/{app['application_id']}", headers=auth(friend))
    client.post(f"/assessments/submit/{app['application_id']}", headers=auth(friend), json=ALL_RIGHT)
    summary = client.get("/referrals", headers=auth(referrer)).json()
    assert summary["successful"] == 1 and summary["credit_balance"] == start_balance + summary["reward_per_referral"]


def test_support_ticket_conversation(client, outbox):
    token = signup_candidate(client)
    r = client.post("/support/tickets", headers=auth(token), data={"subject": "Assessment froze", "message": "The timer stopped",
                                                                   "category": "Assessment issue"})
    assert r.status_code == 200, r.text
    tid = r.json()["ticket_id"]
    admin = admin_token(client)
    client.post(f"/support/tickets/{tid}/messages", headers=auth(admin), json={"body": "We are looking into it"})
    t = client.get(f"/support/tickets/{tid}", headers=auth(token)).json()
    assert t["status"] == "in_progress" and len(t["messages"]) == 2
    other = signup_candidate(client, email="other@example.com")
    assert client.get(f"/support/tickets/{tid}", headers=auth(other)).status_code == 404
    client.patch(f"/support/tickets/{tid}/status", headers=auth(admin), json={"status": "resolved"})
    assert client.get("/support/tickets", headers=auth(token)).json()[0]["status"] == "resolved"


def test_credits_ledger_and_unconfigured_payments(client):
    hr = signup_hr(client)
    s = client.get("/billing/summary", headers=auth(hr)).json()
    assert s["balance"] == 1000
    tx = client.get("/billing/transactions", headers=auth(hr)).json()["items"]
    assert tx[0]["type"] == "signup_bonus" and tx[0]["amount"] == 1000
    r = client.post("/billing/orders", headers=auth(hr), json={"credits": 1000, "accept_terms": True})
    assert r.status_code == 503                                  # no fake payment
    assert client.get("/billing/summary", headers=auth(hr)).json()["balance"] == 1000
    admin = admin_token(client)
    hr_id = client.get("/auth/me", headers=auth(hr)).json()["account_id"]
    r = client.post("/admin/credits", headers=auth(admin), json={"role": "hr", "account_id": hr_id, "amount": 250, "reason": "Pilot"})
    assert r.json()["balance"] == 1250
    pricing = client.get("/billing/pricing").json()
    assert [p["credits"] for p in pricing["packs"]] == [200, 500, 750, 1000, 1500, 2500]


def test_razorpay_signature_verification(client, monkeypatch):
    import hashlib
    import hmac
    from app.routes import billing
    monkeypatch.setenv("RAZORPAY_KEY_ID", "rzp_test_x")
    monkeypatch.setenv("RAZORPAY_KEY_SECRET", "secret")
    monkeypatch.setattr(billing, "_razorpay_create", lambda amount, receipt, notes: {"id": "order_ABC"})
    hr = signup_hr(client)
    order = client.post("/billing/orders", headers=auth(hr), json={"credits": 500, "accept_terms": True}).json()
    assert order["provider_order_id"] == "order_ABC"
    bad = client.post(f"/billing/orders/{order['order_id']}/verify", headers=auth(hr), json={
        "razorpay_order_id": "order_ABC", "razorpay_payment_id": "pay_1", "razorpay_signature": "nope"})
    assert bad.status_code == 400
    order = client.post("/billing/orders", headers=auth(hr), json={"credits": 500, "accept_terms": True}).json()
    sig = hmac.new(b"secret", b"order_ABC|pay_2", hashlib.sha256).hexdigest()
    ok = client.post(f"/billing/orders/{order['order_id']}/verify", headers=auth(hr), json={
        "razorpay_order_id": "order_ABC", "razorpay_payment_id": "pay_2", "razorpay_signature": sig}).json()
    assert ok["status"] == "paid" and ok["balance"] == 1500 and ok["invoice_number"]
    again = client.post(f"/billing/orders/{order['order_id']}/verify", headers=auth(hr), json={
        "razorpay_order_id": "order_ABC", "razorpay_payment_id": "pay_2", "razorpay_signature": sig}).json()
    assert again["balance"] == 1500                                         # idempotent
    inv = client.get(f"/billing/invoices/{order['order_id']}", headers=auth(hr))
    assert inv.status_code == 200 and inv.content.startswith(b"%PDF")


# ---- authorization ---------------------------------------------------------------------

def test_authorization_boundaries(client, pipeline):
    w = World(client)
    w.upload()
    other_cand = signup_candidate(client, email="intruder@example.com")
    other_hr = verified_hr(client, email="rival@hr.com")
    client.post("/jobs", json=JOB, headers=auth(other_hr))

    # Anonymous
    assert client.get("/candidates").status_code == 401
    assert client.post("/candidates", json={"name": "x", "email": "x@x.com", "job_id": w.job_id}).status_code == 401
    # Another candidate can't touch this application
    assert client.post(f"/resumes/{w.cid}", headers=auth(other_cand), files={"file": ("r.pdf", PDF, "application/pdf")}).status_code == 404
    assert client.post(f"/assessments/start/{w.aid}", headers=auth(other_cand)).status_code == 404
    assert client.get(f"/candidates/{w.cid}", headers=auth(other_cand)).status_code == 404
    assert client.get(f"/candidates/{w.cid}/resume", headers=auth(other_cand)).status_code == 404
    # Candidates can't use HR endpoints
    assert client.get("/candidates", headers=auth(w.cand)).status_code == 403
    assert client.get(f"/candidates/{w.cid}/scores", headers=auth(w.cand)).status_code == 403
    # Another company's HR can't see this candidate
    assert client.get(f"/candidates/{w.cid}", headers=auth(other_hr)).status_code == 404
    assert client.get(f"/candidates/{w.cid}/scores", headers=auth(other_hr)).status_code == 404
    assert all(a["application_id"] != w.aid for a in client.get("/candidates", headers=auth(other_hr)).json())
    # HR can't take the assessment for the candidate
    assert client.post(f"/assessments/start/{w.aid}", headers=auth(w.hr)).status_code == 403
    # Admin endpoints
    assert client.get("/admin/overview", headers=auth(w.hr)).status_code == 403
    assert client.get("/admin/overview", headers=auth(admin_token(client))).status_code == 200


def test_health_reports_without_secrets(client):
    body = client.get("/health").json()
    for key in ("groq_api_key_configured", "spacy_ner_loaded", "semantic_model_available", "smtp_configured",
                "scheduler", "code_sandbox"):
        assert key in body
    assert "test-key" not in str(body)


def test_unsubmitted_code_draft_is_graded_on_final_submit(client, pipeline):
    """Candidates who write code but never press "Submit Code" (or edit after submitting) still get graded:
    the page autosaves {"language", "source"} as the coding draft and the final submit runs it."""
    import json as _json
    from app.services import code_runner
    if not code_runner.is_available("python"):
        pytest.skip("python sandbox unavailable")
    w = World(client, job=dict(JOB, coding_questions=1))
    w.upload()
    body = w.c_post(f"/assessments/start/{w.aid}").json()
    q = [q for q in body["questions"] if q["type"] == "coding"][0]
    solutions = {
        "Category Totals": "import sys\nfrom collections import defaultdict\nd=sys.stdin.read().split();n=int(d[0]);t=defaultdict(int)\nfor i in range(n): t[d[1+2*i]]+=int(d[2+2*i])\nfor k,v in sorted(t.items(),key=lambda x:(-x[1],x[0])): print(k,v)",
        "Sum of Numbers": "n=int(input());print(sum(map(int,input().split())))",
    }
    if q["question"] not in solutions:
        pytest.skip("unexpected problem picked")
    draft = _json.dumps({"language": "python", "source": solutions[q["question"]]})
    # autosave keeps the draft, and the reload payload returns it
    assert client.put(f"/assessments/progress/{w.aid}", headers=auth(w.cand), json={"answers": {str(q["index"]): draft}}).status_code == 200
    again = client.get(f"/assessments/{w.aid}", headers=auth(w.cand)).json()
    assert again["draft_answers"][str(q["index"])] == draft
    answers = [a for a in ALL_RIGHT["answers"] if a["index"] != q["index"]] + [{"index": q["index"], "user_answer": draft}]
    result = w.c_post(f"/assessments/submit/{w.aid}", json={"answers": answers}).json()
    coding_result = [r for r in result["results"] if r["type"] == "coding"][0]
    assert coding_result["correct"] is True and coding_result["score"] == 1.0
    # an untouched starter template is not run
    from app.services.assessment_service import parse_code_draft
    assert parse_code_draft(_json.dumps({"language": "python", "source": code_runner.STARTER_CODE["python"]})) is None
    assert parse_code_draft("B") is None
