from sqlalchemy import Column, Integer, String, Float, Text, DateTime, ForeignKey, Boolean, UniqueConstraint
from sqlalchemy.orm import relationship
from datetime import datetime
from .database import Base


class JobRole(Base):
    __tablename__ = "job_roles"

    job_id = Column(Integer, primary_key=True, index=True)
    title = Column(String(200), nullable=False)
    team = Column(String(100))
    location = Column(String(150))
    description = Column(Text)
    requirements = Column(Text)  # comma separated skills, e.g. "Python, FastAPI, SQL"
    preferred_skills = Column(Text)          # comma separated nice-to-have skills
    education_requirement = Column(String(300))  # shown to candidates / ATS only; never used in ranking
    min_experience = Column(Float, default=0)
    open_positions = Column(Integer, default=1)
    weight_skill = Column(Integer, default=40)
    weight_experience = Column(Integer, default=20)
    weight_test = Column(Integer, default=40)
    # Owner HR account. NULL for legacy jobs created before ownership existed
    # (those stay visible to every HR account).
    hr_account_id = Column(Integer, ForeignKey("hr_accounts.account_id"), nullable=True, index=True)
    status = Column(String(20), default="open")  # open | closed
    coding_questions = Column(Integer, default=0)   # coding problems appended to the assessment
    assessment_minutes = Column(Integer, default=30)
    created_at = Column(DateTime, default=datetime.utcnow)

    applications = relationship("Application", back_populates="job")


class Candidate(Base):
    __tablename__ = "candidates"

    candidate_id = Column(Integer, primary_key=True, index=True)
    name = Column(String(150), nullable=False)
    email = Column(String(150), nullable=False)
    phone = Column(String(30))
    # Logged-in candidate account that created this application (NULL for legacy rows).
    account_id = Column(Integer, ForeignKey("candidate_accounts.account_id"), nullable=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    resume = relationship("Resume", back_populates="candidate", uselist=False)
    applications = relationship("Application", back_populates="candidate")


class Resume(Base):
    __tablename__ = "resumes"

    resume_id = Column(Integer, primary_key=True, index=True)
    candidate_id = Column(Integer, ForeignKey("candidates.candidate_id"), nullable=False)
    file_name = Column(String(255))
    file_path = Column(String(500))
    skills = Column(Text)       # extracted, comma separated
    experience = Column(Text)   # extracted summary
    education = Column(Text)    # extracted summary
    experience_years = Column(Float, nullable=True)
    experience_entries = Column(Text, nullable=True)  # JSON
    uploaded_at = Column(DateTime, default=datetime.utcnow)

    candidate = relationship("Candidate", back_populates="resume")


class Application(Base):
    """Links a candidate to a job role. Not in the original ER diagram by name,
    but needed to represent the many-to-many 'applies for' relationship and
    track per-job status shown on the dashboard."""
    __tablename__ = "applications"

    application_id = Column(Integer, primary_key=True, index=True)
    candidate_id = Column(Integer, ForeignKey("candidates.candidate_id"), nullable=False)
    job_id = Column(Integer, ForeignKey("job_roles.job_id"), nullable=False)
    status = Column(String(50), default="submitted")
    # submitted -> assessed -> shortlisted -> scheduled -> selected / rejected
    applied_at = Column(DateTime, default=datetime.utcnow)
    # The decision HR took and the explanation the candidate sees (services/feedback_service.py).
    decision_stage = Column(String(20), nullable=True)   # pipeline stage where a rejection stopped the process
    decision_note = Column(Text, nullable=True)          # optional note HR typed with the decision
    decision_at = Column(DateTime, nullable=True)
    decision_feedback = Column(Text, nullable=True)      # JSON snapshot of the explanation at decision time

    candidate = relationship("Candidate", back_populates="applications")
    job = relationship("JobRole", back_populates="applications")
    assessment = relationship("Assessment", back_populates="application", uselist=False)
    final_score = relationship("FinalScore", back_populates="application", uselist=False)
    interview = relationship("InterviewSchedule", back_populates="application", uselist=False)


class Assessment(Base):
    __tablename__ = "assessments"

    assessment_id = Column(Integer, primary_key=True, index=True)
    application_id = Column(Integer, ForeignKey("applications.application_id"), nullable=False)
    questions = Column(Text)   # JSON string of generated questions
    answers = Column(Text)     # JSON string of graded candidate answers (set on submit)
    draft_answers = Column(Text, nullable=True)  # JSON {index: answer} saved while in progress
    score = Column(Float, nullable=True)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    time_limit_minutes = Column(Integer, nullable=True)
    expires_at = Column(DateTime, nullable=True)       # started_at + time limit (UTC)
    auto_submitted = Column(Boolean, default=False)
    template_id = Column(Integer, nullable=True)   # published AssessmentTemplate this attempt was copied from
    # Proctoring (services/proctor_service.py)
    proctored = Column(Boolean, default=False)
    integrity = Column(String(20), default="clean")      # clean | flagged | terminated | unmonitored
    strikes = Column(Integer, default=0)
    proctor_consent_at = Column(DateTime, nullable=True)
    precheck = Column(Text, nullable=True)               # JSON: what the pre-exam check reported
    last_seen = Column(DateTime, nullable=True)          # last proctoring heartbeat
    # State is derived from the row: no row/questions -> not_started,
    # questions without completed_at -> in_progress, completed_at -> completed.

    application = relationship("Application", back_populates="assessment")


class ProctorEvent(Base):
    """One thing the proctoring agent noticed during an assessment."""
    __tablename__ = "proctor_events"

    event_id = Column(Integer, primary_key=True, index=True)
    assessment_id = Column(Integer, ForeignKey("assessments.assessment_id"), nullable=False, index=True)
    kind = Column(String(40), nullable=False)       # tab_hidden | window_blur | fullscreen_exit | no_face | multiple_faces | looking_away | loud_audio | ...
    severity = Column(String(10), default="info")   # info | warning | strike
    message = Column(String(300), nullable=True)
    strike_no = Column(Integer, nullable=True)      # which strike this was, when severity == strike
    meta = Column(Text, nullable=True)              # JSON
    snapshot = Column(Text, nullable=True)          # tiny JPEG data-URL taken at a strike (evidence for HR)
    at = Column(DateTime, default=datetime.utcnow)


class FinalScore(Base):
    __tablename__ = "final_scores"

    score_id = Column(Integer, primary_key=True, index=True)
    application_id = Column(Integer, ForeignKey("applications.application_id"), nullable=False)
    skill_score = Column(Float, nullable=True)
    experience_score = Column(Float, nullable=True)
    test_score = Column(Float, nullable=True)
    final_score = Column(Float, nullable=True)
    skill_matched = Column(Text, nullable=True)
    skill_missing = Column(Text, nullable=True)
    recommendation = Column(Text, nullable=True)
    explanation = Column(Text, nullable=True)
    # "completed" | "failed" | None (never ran). Lets the submit route know
    # whether a null skill/experience score still needs a screening retry.
    screening_status = Column(String(20), nullable=True)
    screening_error = Column(Text, nullable=True)

    application = relationship("Application", back_populates="final_score")


class InterviewSchedule(Base):
    __tablename__ = "interview_schedules"

    schedule_id = Column(Integer, primary_key=True, index=True)
    application_id = Column(Integer, ForeignKey("applications.application_id"), nullable=False)
    date = Column(String(20))   # local date YYYY-MM-DD in `timezone`
    time = Column(String(20))   # local time HH:MM in `timezone`
    mode = Column(String(50), default="Google Meet")
    status = Column(String(50), default="scheduled")  # scheduled|confirmed|completed|cancelled|rescheduled
    timezone = Column(String(64), nullable=True, default="Asia/Kolkata")
    scheduled_at_utc = Column(DateTime, nullable=True, index=True)
    duration_minutes = Column(Integer, default=45)
    meeting_link = Column(String(500), nullable=True)
    location = Column(String(300), nullable=True)
    interviewer = Column(String(200), nullable=True)
    notes = Column(Text, nullable=True)
    hr_account_id = Column(Integer, ForeignKey("hr_accounts.account_id"), nullable=True)
    reminder_status = Column(String(20), nullable=True, default="pending")  # pending|sending|sent|failed|skipped
    reminder_sent_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow)
    cancelled_at = Column(DateTime, nullable=True)

    application = relationship("Application", back_populates="interview")


class CandidateAccount(Base):
    __tablename__ = "candidate_accounts"

    account_id = Column(Integer, primary_key=True, index=True)
    name = Column(String(150), nullable=False)
    email = Column(String(150), unique=True, nullable=False, index=True)
    password_hash = Column(String(500), nullable=False)
    session_token = Column(String(200), unique=True, index=True)
    phone = Column(String(30), nullable=True)
    referred_by_code = Column(String(40), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class HRAccount(Base):
    __tablename__ = "hr_accounts"

    account_id = Column(Integer, primary_key=True, index=True)
    name = Column(String(150), nullable=False)
    company = Column(String(200), nullable=False)
    email = Column(String(150), unique=True, nullable=False, index=True)
    password_hash = Column(String(500), nullable=False)
    session_token = Column(String(200), unique=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    phone = Column(String(30), nullable=True)


# ===========================================================================
# Platform models (profiles, verification, notifications, email, credits,
# offers, coding, ATS, referrals, support, admin, settings)
# ===========================================================================

class AdminAccount(Base):
    __tablename__ = "admin_accounts"

    admin_id = Column(Integer, primary_key=True)
    username = Column(String(80), unique=True, nullable=False)
    name = Column(String(150), default="Administrator")
    password_hash = Column(String(500), nullable=False)
    session_token = Column(String(200), unique=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class AuthSession(Base):
    """One row per login. Only a SHA-256 hash of the bearer token is stored, so
    several devices/tabs can stay logged in and a DB leak exposes no live token."""
    __tablename__ = "auth_sessions"

    session_id = Column(Integer, primary_key=True)
    token_hash = Column(String(64), unique=True, index=True, nullable=False)
    role = Column(String(20), nullable=False)          # candidate | hr | admin
    account_id = Column(Integer, nullable=False, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    last_used_at = Column(DateTime, default=datetime.utcnow)
    expires_at = Column(DateTime, nullable=False)


class UserSettings(Base):
    __tablename__ = "user_settings"
    __table_args__ = (UniqueConstraint("role", "account_id", name="uq_settings_owner"),)

    settings_id = Column(Integer, primary_key=True)
    role = Column(String(20), nullable=False)          # candidate | hr | admin
    account_id = Column(Integer, nullable=False)
    theme = Column(String(10), default="dark")         # light | dark (dark matches the home page)
    email_notifications = Column(Boolean, default=True)
    assessment_notifications = Column(Boolean, default=True)
    interview_notifications = Column(Boolean, default=True)
    reminder_notifications = Column(Boolean, default=True)
    offer_notifications = Column(Boolean, default=True)
    marketing_notifications = Column(Boolean, default=False)
    profile_visibility = Column(String(20), default="employers")  # employers | private
    resume_visibility = Column(String(20), default="applied")     # applied | private
    allow_data_for_matching = Column(Boolean, default=True)
    updated_at = Column(DateTime, default=datetime.utcnow)


class CandidateProfile(Base):
    __tablename__ = "candidate_profiles"

    profile_id = Column(Integer, primary_key=True)
    account_id = Column(Integer, ForeignKey("candidate_accounts.account_id"), unique=True, nullable=False)
    headline = Column(String(200), nullable=True)
    phone = Column(String(30), nullable=True)
    location = Column(String(150), nullable=True)
    date_of_birth = Column(String(20), nullable=True)
    linkedin = Column(String(300), nullable=True)
    github = Column(String(300), nullable=True)
    portfolio = Column(String(300), nullable=True)
    photo_path = Column(String(500), nullable=True)
    # Repeating sections stored as JSON arrays of objects.
    education = Column(Text, nullable=True)
    experience = Column(Text, nullable=True)
    projects = Column(Text, nullable=True)
    certifications = Column(Text, nullable=True)
    # Skill groups stored as JSON arrays of strings.
    technical_skills = Column(Text, nullable=True)
    soft_skills = Column(Text, nullable=True)
    tools = Column(Text, nullable=True)
    languages = Column(Text, nullable=True)
    frameworks = Column(Text, nullable=True)
    resume_file_name = Column(String(255), nullable=True)
    resume_path = Column(String(500), nullable=True)
    resume_uploaded_at = Column(DateTime, nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow)


class HRProfile(Base):
    __tablename__ = "hr_profiles"

    profile_id = Column(Integer, primary_key=True)
    account_id = Column(Integer, ForeignKey("hr_accounts.account_id"), unique=True, nullable=False)
    phone = Column(String(30), nullable=True)
    designation = Column(String(150), nullable=True)
    department = Column(String(150), nullable=True)
    linkedin = Column(String(300), nullable=True)
    location = Column(String(150), nullable=True)
    photo_path = Column(String(500), nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow)


class Company(Base):
    __tablename__ = "companies"

    company_id = Column(Integer, primary_key=True)
    hr_account_id = Column(Integer, ForeignKey("hr_accounts.account_id"), unique=True, nullable=False)
    name = Column(String(200), nullable=True)
    official_email = Column(String(150), nullable=True)
    website = Column(String(300), nullable=True)
    logo_path = Column(String(500), nullable=True)
    description = Column(Text, nullable=True)
    industry = Column(String(150), nullable=True)
    company_size = Column(String(50), nullable=True)
    headquarters = Column(String(200), nullable=True)
    registration_number = Column(String(100), nullable=True)   # CIN / company registration
    gst_number = Column(String(30), nullable=True)
    contact_number = Column(String(30), nullable=True)
    # unverified -> pending -> verified | rejected  (profile_incomplete is derived)
    verification_status = Column(String(20), default="unverified")
    submitted_at = Column(DateTime, nullable=True)
    verified_at = Column(DateTime, nullable=True)
    rejection_reason = Column(Text, nullable=True)
    reviewed_by = Column(String(80), nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow)

    documents = relationship("CompanyDocument", back_populates="company", cascade="all, delete-orphan")


class CompanyDocument(Base):
    __tablename__ = "company_documents"

    document_id = Column(Integer, primary_key=True)
    company_id = Column(Integer, ForeignKey("companies.company_id"), nullable=False, index=True)
    doc_type = Column(String(40), nullable=False)  # id_proof | visiting_card | registration_proof
    file_name = Column(String(255))
    file_path = Column(String(500))
    content_type = Column(String(100))
    uploaded_at = Column(DateTime, default=datetime.utcnow)

    company = relationship("Company", back_populates="documents")


class Notification(Base):
    __tablename__ = "notifications"

    notification_id = Column(Integer, primary_key=True)
    recipient_role = Column(String(20), nullable=False, index=True)
    recipient_id = Column(Integer, nullable=False, index=True)
    type = Column(String(50), nullable=False)
    title = Column(String(200), nullable=False)
    message = Column(Text)
    link = Column(String(300), nullable=True)
    read = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)


class EmailLog(Base):
    __tablename__ = "email_logs"

    email_id = Column(Integer, primary_key=True)
    to_email = Column(String(200), nullable=False)
    subject = Column(String(300), nullable=False)
    template = Column(String(80), nullable=True)
    body_html = Column(Text)
    body_text = Column(Text)
    attachment_path = Column(String(500), nullable=True)
    attachment_name = Column(String(255), nullable=True)
    status = Column(String(20), default="queued")  # queued | sending | sent | failed
    error_message = Column(Text, nullable=True)
    attempts = Column(Integer, default=0)
    related_type = Column(String(40), nullable=True)
    related_id = Column(Integer, nullable=True)
    owner_role = Column(String(20), nullable=True)   # who may retry it (hr/admin)
    owner_id = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    sent_at = Column(DateTime, nullable=True)


class CreditTransaction(Base):
    """Append-only credits ledger. Balance = SUM(amount) for an account."""
    __tablename__ = "credit_transactions"
    __table_args__ = (UniqueConstraint("account_role", "account_id", "reference", name="uq_credit_reference"),)

    transaction_id = Column(Integer, primary_key=True)
    account_role = Column(String(20), nullable=False, index=True)
    account_id = Column(Integer, nullable=False, index=True)
    amount = Column(Integer, nullable=False)          # + credit, - debit
    type = Column(String(30), nullable=False)          # signup_bonus|purchase|spend|refund|admin_adjustment|referral_reward
    description = Column(String(300))
    reference = Column(String(120), nullable=True, index=True)  # idempotency key, e.g. unlock:app:12
    balance_after = Column(Integer, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)


class CreditOrder(Base):
    __tablename__ = "credit_orders"

    order_id = Column(Integer, primary_key=True)
    account_role = Column(String(20), nullable=False)
    account_id = Column(Integer, nullable=False, index=True)
    credits = Column(Integer, nullable=False)
    price_paise = Column(Integer, nullable=False)
    discount_paise = Column(Integer, default=0)
    amount_paise = Column(Integer, nullable=False)
    currency = Column(String(5), default="INR")
    status = Column(String(20), default="created")  # created | paid | failed
    provider = Column(String(20), default="razorpay")
    provider_order_id = Column(String(100), nullable=True, index=True)
    provider_payment_id = Column(String(100), nullable=True)
    invoice_number = Column(String(40), nullable=True, unique=True)
    billing_snapshot = Column(Text, nullable=True)   # JSON of billing details at purchase time
    failure_reason = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    paid_at = Column(DateTime, nullable=True)


class BillingProfile(Base):
    __tablename__ = "billing_profiles"
    __table_args__ = (UniqueConstraint("account_role", "account_id", name="uq_billing_owner"),)

    billing_id = Column(Integer, primary_key=True)
    account_role = Column(String(20), nullable=False)
    account_id = Column(Integer, nullable=False)
    billed_to = Column(String(200))
    company = Column(String(200))
    email = Column(String(200))
    mobile = Column(String(30))
    address = Column(Text)
    gst_number = Column(String(30))
    updated_at = Column(DateTime, default=datetime.utcnow)


class CandidateUnlock(Base):
    __tablename__ = "candidate_unlocks"
    __table_args__ = (UniqueConstraint("hr_account_id", "application_id", name="uq_unlock"),)

    unlock_id = Column(Integer, primary_key=True)
    hr_account_id = Column(Integer, ForeignKey("hr_accounts.account_id"), nullable=False)
    application_id = Column(Integer, ForeignKey("applications.application_id"), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)


class OfferTemplate(Base):
    __tablename__ = "offer_templates"

    template_id = Column(Integer, primary_key=True)
    hr_account_id = Column(Integer, ForeignKey("hr_accounts.account_id"), nullable=True)  # NULL = built-in default
    name = Column(String(150), nullable=False)
    content = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow)


class OfferLetter(Base):
    __tablename__ = "offer_letters"

    offer_id = Column(Integer, primary_key=True)
    application_id = Column(Integer, ForeignKey("applications.application_id"), nullable=False, index=True)
    hr_account_id = Column(Integer, ForeignKey("hr_accounts.account_id"), nullable=True)
    template_id = Column(Integer, ForeignKey("offer_templates.template_id"), nullable=True)
    revision_of_id = Column(Integer, ForeignKey("offer_letters.offer_id"), nullable=True)
    template_content = Column(Text)      # template text with {{placeholders}}
    fields = Column(Text)                # JSON placeholder values
    content = Column(Text)               # rendered letter (frozen once sent)
    status = Column(String(20), default="draft")  # draft|sent|viewed|accepted|rejected|expired|withdrawn
    valid_days = Column(Integer, nullable=True)      # days the candidate has to respond (default OFFER_VALID_DAYS)
    view_token = Column(String(64), unique=True, index=True)
    expires_at = Column(DateTime, nullable=True)
    pdf_path = Column(String(500), nullable=True)
    email_status = Column(String(20), nullable=True)
    response_note = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow)
    sent_at = Column(DateTime, nullable=True)
    viewed_at = Column(DateTime, nullable=True)
    accepted_at = Column(DateTime, nullable=True)
    rejected_at = Column(DateTime, nullable=True)

    application = relationship("Application")


class CodingProblem(Base):
    __tablename__ = "coding_problems"

    problem_id = Column(Integer, primary_key=True)
    slug = Column(String(80), unique=True, nullable=True)
    title = Column(String(200), nullable=False)
    difficulty = Column(String(20), default="easy")
    tags = Column(String(300), default="")           # comma separated skills
    statement = Column(Text, nullable=False)
    input_format = Column(Text)
    output_format = Column(Text)
    constraints = Column(Text)
    examples = Column(Text)        # JSON [{input, output, explanation}]
    visible_tests = Column(Text)   # JSON [{input, output}]
    hidden_tests = Column(Text)    # JSON [{input, output}] — never sent to candidates
    time_limit_ms = Column(Integer, default=2000)
    memory_limit_mb = Column(Integer, default=256)
    hr_account_id = Column(Integer, ForeignKey("hr_accounts.account_id"), nullable=True)  # NULL = library
    active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class AssessmentTemplate(Base):
    """An HR-reviewed assessment for a job, generated by the LangGraph assessment
    agent (agents/assessment_graph.py). ``questions`` uses the same JSON schema as
    Assessment.questions (GeneratedQuestionSet), so candidates get a copy of the
    published template when they start and grading is unchanged."""
    __tablename__ = "assessment_templates"

    template_id = Column(Integer, primary_key=True)
    job_id = Column(Integer, ForeignKey("job_roles.job_id"), nullable=False, index=True)
    hr_account_id = Column(Integer, ForeignKey("hr_accounts.account_id"), nullable=True, index=True)
    title = Column(String(200), nullable=False)
    assessment_type = Column(String(10), default="mixed")     # mcq | coding | mixed
    difficulty = Column(String(10), default="medium")         # easy | medium | hard
    num_questions = Column(Integer, default=10)
    time_limit_minutes = Column(Integer, default=30)
    skills = Column(Text)                                     # JSON list
    questions = Column(Text)                                  # JSON GeneratedQuestionSet
    status = Column(String(12), default="draft")              # draft | published | archived
    generation_notes = Column(Text)                           # JSON list of agent warnings (fallbacks etc.)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    published_at = Column(DateTime, nullable=True)


class CodingSubmission(Base):
    __tablename__ = "coding_submissions"

    submission_id = Column(Integer, primary_key=True)
    assessment_id = Column(Integer, ForeignKey("assessments.assessment_id"), nullable=False, index=True)
    question_index = Column(Integer, nullable=False)
    problem_id = Column(Integer, ForeignKey("coding_problems.problem_id"), nullable=False)
    language = Column(String(20), nullable=False)
    source_code = Column(Text, nullable=False)
    kind = Column(String(10), default="submit")      # run | submit
    status = Column(String(30))                       # accepted|wrong_answer|compile_error|runtime_error|time_limit|error
    passed = Column(Integer, default=0)
    total = Column(Integer, default=0)
    score = Column(Float, nullable=True)              # 0-100
    exec_time_ms = Column(Integer, nullable=True)
    memory_kb = Column(Integer, nullable=True)
    error = Column(Text, nullable=True)
    submitted_at = Column(DateTime, default=datetime.utcnow)


class ATSCheck(Base):
    __tablename__ = "ats_checks"

    check_id = Column(Integer, primary_key=True)
    account_id = Column(Integer, ForeignKey("candidate_accounts.account_id"), nullable=False, index=True)
    file_name = Column(String(255))
    job_id = Column(Integer, ForeignKey("job_roles.job_id"), nullable=True)
    job_description = Column(Text, nullable=True)
    score = Column(Float)
    result = Column(Text)   # JSON report
    created_at = Column(DateTime, default=datetime.utcnow)


class ReferralCode(Base):
    __tablename__ = "referral_codes"

    code_id = Column(Integer, primary_key=True)
    code = Column(String(40), unique=True, nullable=False, index=True)
    account_id = Column(Integer, ForeignKey("candidate_accounts.account_id"), unique=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)


class Referral(Base):
    __tablename__ = "referrals"

    referral_id = Column(Integer, primary_key=True)
    code_id = Column(Integer, ForeignKey("referral_codes.code_id"), nullable=False)
    referrer_account_id = Column(Integer, ForeignKey("candidate_accounts.account_id"), nullable=False, index=True)
    referred_account_id = Column(Integer, ForeignKey("candidate_accounts.account_id"), unique=True, nullable=False)
    status = Column(String(20), default="signed_up")  # signed_up | qualified | rewarded
    reward_credits = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)
    qualified_at = Column(DateTime, nullable=True)
    rewarded_at = Column(DateTime, nullable=True)


class SupportTicket(Base):
    __tablename__ = "support_tickets"

    ticket_id = Column(Integer, primary_key=True)
    requester_role = Column(String(20), nullable=False, index=True)
    requester_id = Column(Integer, nullable=False, index=True)
    name = Column(String(150))
    email = Column(String(150))
    category = Column(String(40))
    subject = Column(String(200), nullable=False)
    status = Column(String(20), default="open")  # open | in_progress | resolved | closed
    attachment_name = Column(String(255), nullable=True)
    attachment_path = Column(String(500), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow)

    messages = relationship("SupportMessage", back_populates="ticket", cascade="all, delete-orphan",
                            order_by="SupportMessage.message_id")


class SupportMessage(Base):
    __tablename__ = "support_messages"

    message_id = Column(Integer, primary_key=True)
    ticket_id = Column(Integer, ForeignKey("support_tickets.ticket_id"), nullable=False, index=True)
    author_role = Column(String(20), nullable=False)  # candidate | hr | admin
    author_name = Column(String(150))
    body = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    ticket = relationship("SupportTicket", back_populates="messages")



class MockInterview(Base):
    """A candidate's PRACTICE interview with the AI interviewer (never visible to employers)."""
    __tablename__ = "mock_interviews"

    interview_id = Column(Integer, primary_key=True)
    account_id = Column(Integer, ForeignKey("candidate_accounts.account_id"), nullable=False, index=True)
    job_id = Column(Integer, ForeignKey("job_roles.job_id"), nullable=True)
    role_title = Column(String(200), nullable=False)
    config = Column(Text)            # JSON: type, difficulty, num_questions, mode, total_limit_minutes, skills
    plan = Column(Text)              # JSON list of planned slots
    turns = Column(Text)             # JSON list of asked questions, answers and evaluations
    status = Column(String(20), default="in_progress")   # in_progress | completed
    overall_score = Column(Float, nullable=True)
    report = Column(Text, nullable=True)                 # JSON
    engine = Column(String(20), default="offline")       # ai | offline
    created_at = Column(DateTime, default=datetime.utcnow)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)


class MockAssessment(Base):
    """A candidate's PRACTICE test for a role (MCQ + coding), graded instantly."""
    __tablename__ = "mock_assessments"

    mock_id = Column(Integer, primary_key=True)
    account_id = Column(Integer, ForeignKey("candidate_accounts.account_id"), nullable=False, index=True)
    job_id = Column(Integer, ForeignKey("job_roles.job_id"), nullable=True)
    role_title = Column(String(200), nullable=False)
    config = Column(Text)            # JSON: skills, difficulty, counts
    questions = Column(Text)         # JSON list (includes answer keys; stripped before sending)
    answers = Column(Text)           # JSON {index: answer}
    code = Column(Text)              # JSON {index: {language, source, result}}
    results = Column(Text)           # JSON per-question grading + per-skill breakdown
    score = Column(Float, nullable=True)
    engine = Column(String(20), default="offline")
    time_limit_minutes = Column(Integer, default=20)
    started_at = Column(DateTime, default=datetime.utcnow)
    expires_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    auto_submitted = Column(Boolean, default=False)

# ---------------------------------------------------------------------------
# PostgreSQL enforces VARCHAR(n) lengths (SQLite never did). Generated values
# such as email subjects or notification text can exceed a column, so they are
# trimmed to fit right before every flush instead of failing the request.
# ---------------------------------------------------------------------------
from sqlalchemy import String as _String, event as _event, inspect as _inspect  # noqa: E402
from sqlalchemy.orm import Session as _Session  # noqa: E402


@_event.listens_for(_Session, "before_flush")
def _fit_strings_to_columns(session, _ctx, _instances):
    for obj in list(session.new) + list(session.dirty):
        try:
            mapper = _inspect(obj).mapper
        except Exception:  # noqa: BLE001
            continue
        for attr in mapper.column_attrs:
            col = attr.columns[0]
            limit = getattr(col.type, "length", None)
            if not limit or not isinstance(col.type, _String):
                continue
            value = getattr(obj, attr.key, None)
            if isinstance(value, str) and len(value) > limit:
                setattr(obj, attr.key, value[:limit])
