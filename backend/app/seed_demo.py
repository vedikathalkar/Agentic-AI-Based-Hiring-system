"""DEMO / TEST data for Hirelune.

    cd backend
    python -m app.seed_demo            # add demo data (skipped if it already exists)
    python -m app.seed_demo --reset    # remove ONLY demo rows, then re-create them
    python -m app.seed_demo --remove   # remove ONLY demo rows

Everything created here is clearly marked and never touches real users:
* every account email ends with @demo.hirelune.test
* names, companies and job titles carry "(Demo)"
* every demo password is  Demo@1234  (stored hashed like any other account)

Scores are NOT hardcoded: resumes are real PDFs run through the resume parser and
screening graph, and assessments are graded by the normal grading code (MCQ answer
keys + coding submissions executed in the sandbox).
"""

from __future__ import annotations

import argparse
import json
import logging
from datetime import datetime, timedelta

from .database import SessionLocal
from . import main as _app_main  # noqa: F401  (runs migrations + platform seed so tables exist)
from . import models
from .security import hash_password
from .services import credits_service, files, settings_service
from .services.pdf_service import text_pdf

log = logging.getLogger("seed_demo")
DOMAIN = "@demo.hirelune.test"
PASSWORD = "Demo@1234"

# 1x1 PNG used as the demo company logo.
_PNG = bytes.fromhex("89504e470d0a1a0a0000000d4948445200000001000000010806000000"
                     "1f15c4890000000d49444154789c6360f8cfc0f01f0005000201a5f3c1"
                     "b00000000049454e44ae426082")

HRS = [
    {"email": "priya.hr" + DOMAIN, "name": "Priya Sharma (Demo)", "company": "Nimbus Analytics (Demo)",
     "designation": "Talent Acquisition Lead", "department": "People", "location": "Bengaluru", "phone": "+91 90000 00001",
     "industry": "Data & AI", "size": "51-200", "website": "https://nimbus-demo.example.com", "hq": "Bengaluru, India",
     "reg": "DEMO-U72900KA2020PTC000001", "gst": "29DEMO0000A1Z5"},
    {"email": "arjun.hr" + DOMAIN, "name": "Arjun Mehta (Demo)", "company": "Orbitware Labs (Demo)",
     "designation": "Engineering Recruiter", "department": "Human Resources", "location": "Pune", "phone": "+91 90000 00002",
     "industry": "Software", "size": "201-500", "website": "https://orbitware-demo.example.com", "hq": "Pune, India",
     "reg": "DEMO-U72200MH2019PTC000002", "gst": "27DEMO0000B1Z3"},
    {"email": "kavya.hr" + DOMAIN, "name": "Kavya Reddy (Demo)", "company": "Finvera Payments (Demo)",
     "designation": "HR Business Partner", "department": "People Operations", "location": "Hyderabad", "phone": "+91 90000 00003",
     "industry": "Fintech", "size": "501-1000", "website": "https://finvera-demo.example.com", "hq": "Hyderabad, India",
     "reg": "DEMO-U67190TG2018PTC000003", "gst": "36DEMO0000C1Z1"},
    {"email": "rohit.hr" + DOMAIN, "name": "Rohit Malhotra (Demo)", "company": "Medisphere Health (Demo)",
     "designation": "Senior Recruiter", "department": "Talent Acquisition", "location": "Chennai", "phone": "+91 90000 00004",
     "industry": "Healthcare technology", "size": "201-500", "website": "https://medisphere-demo.example.com", "hq": "Chennai, India",
     "reg": "DEMO-U85100TN2017PTC000004", "gst": "33DEMO0000D1Z8"},
    {"email": "isha.hr" + DOMAIN, "name": "Isha Kapoor (Demo)", "company": "Kalpa Retail Tech (Demo)",
     "designation": "Head of Talent", "department": "Human Resources", "location": "Mumbai", "phone": "+91 90000 00005",
     "industry": "E-commerce", "size": "1000+", "website": "https://kalpa-demo.example.com", "hq": "Mumbai, India",
     "reg": "DEMO-U52100MH2016PTC000005", "gst": "27DEMO0000E1Z6"},
]
COMPANY_COLORS = [(255, 197, 61), (94, 129, 244), (52, 199, 140), (236, 99, 120), (155, 108, 245)]

JOBS = [
    {"hr": 0, "key": "ml", "title": "Machine Learning Engineer (Demo)", "team": "AI Platform", "location": "Bengaluru · Hybrid",
     "requirements": "Python, Machine Learning, Deep Learning, PyTorch, scikit-learn, SQL, NLP",
     "preferred_skills": "Docker, AWS, MLOps, TensorFlow",
     "education_requirement": "B.Tech / B.E. in Computer Science or related field",
     "min_experience": 2, "coding_questions": 1, "assessment_minutes": 30,
     "description": "Build and deploy machine learning models for our analytics products. You will design training "
                    "pipelines, evaluate models, and ship NLP features to production with the platform team."},
    {"hr": 1, "key": "fs", "title": "Full Stack Developer (Demo)", "team": "Product Engineering", "location": "Pune · On-site",
     "requirements": "JavaScript, React, Node.js, TypeScript, REST APIs, PostgreSQL, Git",
     "preferred_skills": "Docker, AWS, GraphQL, Redux",
     "education_requirement": "Bachelor's degree in Computer Science, IT or equivalent",
     "min_experience": 2, "coding_questions": 1, "assessment_minutes": 30,
     "description": "Own features end to end across our React front end and Node.js services, design REST APIs, "
                    "model data in PostgreSQL and ship with CI/CD."},
    {"hr": 1, "key": "android", "title": "Android Developer (Demo)", "team": "Mobile", "location": "Pune · Hybrid",
     "requirements": "Kotlin, Android, REST APIs, Git", "preferred_skills": "Jetpack Compose, Firebase",
     "education_requirement": "B.E. / B.Tech or equivalent", "min_experience": 1, "coding_questions": 1, "assessment_minutes": 30,
     "description": "Build and ship our Android app used by 2 million shoppers. Work with designers and backend engineers."},
    {"hr": 2, "key": "backend", "title": "Backend Engineer, Python (Demo)", "team": "Payments Platform", "location": "Hyderabad · Hybrid",
     "requirements": "Python, FastAPI, PostgreSQL, Docker, REST APIs, SQL", "preferred_skills": "Kafka, AWS, Redis",
     "education_requirement": "Bachelor's degree in Computer Science or related field", "min_experience": 3,
     "coding_questions": 1, "assessment_minutes": 40,
     "description": "Design reliable payment APIs in Python and FastAPI, model data in PostgreSQL and run services in Docker."},
    {"hr": 2, "key": "devops", "title": "DevOps Engineer (Demo)", "team": "Infrastructure", "location": "Remote",
     "requirements": "AWS, Docker, Kubernetes, Terraform, CI/CD, Linux", "preferred_skills": "Python, Prometheus",
     "education_requirement": "Any engineering degree", "min_experience": 3, "coding_questions": 0, "assessment_minutes": 30,
     "description": "Own our cloud infrastructure on AWS: Kubernetes clusters, Terraform, CI/CD pipelines and observability."},
    {"hr": 3, "key": "ds", "title": "Data Scientist (Demo)", "team": "Clinical AI", "location": "Chennai · On-site",
     "requirements": "Python, Machine Learning, Statistics, SQL, pandas, scikit-learn", "preferred_skills": "Deep Learning, NLP",
     "education_requirement": "Master's degree in Statistics, Computer Science or a related field", "min_experience": 2,
     "coding_questions": 1, "assessment_minutes": 40,
     "description": "Build predictive models on anonymised clinical data and work with doctors to validate them."},
    {"hr": 3, "key": "qa", "title": "QA Automation Engineer (Demo)", "team": "Quality", "location": "Chennai · Hybrid",
     "requirements": "Selenium, Java, Test Automation, SQL, Git", "preferred_skills": "Cypress, CI/CD",
     "education_requirement": "B.E. / B.Tech or B.Sc in Computer Science", "min_experience": 1, "coding_questions": 0,
     "assessment_minutes": 25,
     "description": "Automate regression testing for our patient and doctor apps and keep releases green."},
    {"hr": 4, "key": "frontend", "title": "Frontend Developer, React (Demo)", "team": "Storefront", "location": "Mumbai · Hybrid",
     "requirements": "React, JavaScript, TypeScript, HTML, CSS, Redux", "preferred_skills": "Next.js, Tailwind",
     "education_requirement": "Bachelor's degree or equivalent experience", "min_experience": 1, "coding_questions": 1,
     "assessment_minutes": 30,
     "description": "Build fast, accessible storefront pages in React and TypeScript for millions of shoppers."},
    {"hr": 4, "key": "pa", "title": "Product Analyst (Demo)", "team": "Growth", "location": "Remote",
     "requirements": "SQL, Excel, Statistics, Data Analysis, Tableau", "preferred_skills": "Python, A/B Testing",
     "education_requirement": "Bachelor's degree in any quantitative field", "min_experience": 0, "coding_questions": 0,
     "assessment_minutes": 20,
     "description": "Analyse funnels and experiments for the growth team and turn data into product decisions. Freshers welcome."},
    {"hr": 0, "key": "da", "title": "Data Analyst (Demo)", "team": "Insights", "location": "Remote",
     "requirements": "SQL, Excel, Python, Tableau, Statistics, Data Analysis",
     "preferred_skills": "Power BI, pandas, Data Visualization",
     "education_requirement": "Bachelor's degree in Statistics, Mathematics, Economics or Engineering",
     "min_experience": 1, "coding_questions": 0, "assessment_minutes": 20,
     "description": "Turn product and business data into dashboards and insights. Write SQL, analyse experiments "
                    "and present findings to stakeholders."},
]


from .agents.practice_bank import DA_MCQ, EXTRA_MCQ, FS_MCQ, ML_MCQ, _mcq  # noqa: E402,F401


# Solutions submitted by demo candidates. "strong" are correct; "weak" is a realistic bug.
SOLUTIONS = {
    "max-subarray": {
        "strong": "input();a=list(map(int,input().split()));best=cur=a[0]\nfor x in a[1:]:\n    cur=max(x,cur+x);best=max(best,cur)\nprint(best)",
        "weak": "input();a=list(map(int,input().split()))\nprint(sum(x for x in a if x>0))",   # fails all-negative input
    },
    "balanced-brackets": {
        "strong": "s=input().strip();st=[];m={')':'(',']':'[','}':'{'};ok=True\nfor c in s:\n    if c in '([{': st.append(c)\n"
                  "    elif not st or st.pop()!=m[c]: ok=False;break\nprint('YES' if ok and not st else 'NO')",
        "weak": "s=input().strip()\nprint('YES' if s.count('(')==s.count(')') and s.count('[')==s.count(']') and s.count('{')==s.count('}') else 'NO')",
    },
}

CANDIDATES = [
    {"key": "aarav", "name": "Aarav Kulkarni (Demo)", "job": "ml", "level": 1.0, "code": "strong", "location": "Bengaluru",
     "headline": "ML Engineer · NLP & deep learning", "phone": "+91 91000 00001",
     "skills": ["Python", "PyTorch", "TensorFlow", "scikit-learn", "NLP", "SQL", "Docker", "AWS"],
     "resume": """SUMMARY
Machine learning engineer with 4 years of experience building NLP and deep learning systems in production.

SKILLS
Python, PyTorch, TensorFlow, scikit-learn, Machine Learning, Deep Learning, NLP, SQL, Docker, AWS, MLOps, Git

EXPERIENCE
Senior ML Engineer, DataForge Analytics (Demo) | Jan 2022 - Present
- Built a transformer-based document classifier that improved accuracy by 18% across 2M documents.
- Deployed PyTorch models on AWS with Docker, cutting inference latency by 40%.
ML Engineer, Insight Labs (Demo) | Jul 2020 - Dec 2021
- Developed scikit-learn churn models and SQL feature pipelines used by 3 product teams.

EDUCATION
B.Tech in Computer Science, Demo Institute of Technology, 2020, CGPA 8.7

PROJECTS
Resume Entity Extractor - spaCy NER model for resumes with 91% F1.

CERTIFICATIONS
AWS Certified Machine Learning - Specialty (Demo)"""},
    {"key": "kabir", "name": "Kabir Singh (Demo)", "job": "ml", "level": None, "code": None, "location": "Delhi",
     "headline": "Aspiring ML engineer", "phone": "+91 91000 00002",
     "skills": ["Python", "NumPy", "pandas", "scikit-learn"],
     "resume": """SUMMARY
Recent graduate interested in machine learning with one internship.

SKILLS
Python, NumPy, pandas, scikit-learn, Matplotlib, Git

EXPERIENCE
Data Science Intern, Brightpath (Demo) | Jan 2024 - Jun 2024
- Cleaned datasets with pandas and trained baseline scikit-learn regression models.

EDUCATION
B.Sc in Mathematics, Demo University, 2024

PROJECTS
House Price Prediction - linear regression model on a public dataset."""},
    {"key": "sneha", "name": "Sneha Iyer (Demo)", "job": "fs", "level": 0.72, "code": "strong", "location": "Pune",
     "headline": "Full stack developer · React & Node.js", "phone": "+91 91000 00003",
     "skills": ["JavaScript", "TypeScript", "React", "Node.js", "PostgreSQL", "Git"],
     "resume": """SUMMARY
Full stack developer with 3 years of experience shipping React and Node.js products.

SKILLS
JavaScript, TypeScript, React, Redux, Node.js, Express, REST APIs, PostgreSQL, Git, Docker

EXPERIENCE
Software Engineer, CloudNest (Demo) | Mar 2021 - Present
- Built a React + TypeScript dashboard used by 12,000 customers.
- Designed REST APIs in Node.js/Express backed by PostgreSQL, reducing page load time by 35%.

EDUCATION
B.E. in Information Technology, Demo College of Engineering, 2020

PROJECTS
Team Planner - React/Node task board with real-time updates.

CERTIFICATIONS
Meta Front-End Developer Certificate (Demo)"""},
    {"key": "meera", "name": "Meera Nair (Demo)", "job": "fs", "level": 1.0, "code": "weak", "location": "Kochi",
     "headline": "Senior full stack engineer", "phone": "+91 91000 00004",
     "skills": ["React", "Node.js", "GraphQL", "MongoDB", "AWS", "Kubernetes"],
     "resume": """SUMMARY
Senior full stack engineer with 6 years of experience across React, Node.js and cloud infrastructure.

SKILLS
JavaScript, React, Node.js, GraphQL, MongoDB, AWS, Kubernetes, Docker, Git, CI/CD

EXPERIENCE
Lead Engineer, Streamline (Demo) | Jun 2019 - Present
- Led a team of 5 engineers delivering a GraphQL platform serving 1M requests per day.
- Migrated services to Kubernetes on AWS, cutting infrastructure cost by 22%.
Software Developer, Pixelworks (Demo) | Jul 2017 - May 2019
- Built React single page apps and Node.js microservices.

EDUCATION
M.Tech in Computer Science, Demo National Institute, 2017

PROJECTS
Open-source GraphQL rate limiter with 400 GitHub stars."""},
    {"key": "rohan", "name": "Rohan Das (Demo)", "job": "da", "level": 0.4, "code": None, "location": "Kolkata",
     "headline": "Junior data analyst", "phone": "+91 91000 00005",
     "skills": ["SQL", "Excel", "Tableau"],
     "resume": """SUMMARY
Data analyst with 1 year of experience in reporting and dashboards.

SKILLS
SQL, Excel, Tableau, Data Analysis

EXPERIENCE
Junior Analyst, RetailCo (Demo) | Aug 2023 - Present
- Maintained weekly Excel and Tableau sales reports for 4 regions.

EDUCATION
B.Com, Demo Commerce College, 2023"""},
    {"key": "ananya", "name": "Ananya Rao (Demo)", "job": "da", "level": None, "code": None, "location": "Hyderabad",
     "headline": "Data analyst · SQL, Python & Power BI", "phone": "+91 91000 00006",
     "skills": ["SQL", "Python", "pandas", "Power BI", "Statistics"],
     "resume": """SUMMARY
Data analyst with 3 years of experience in SQL, Python and business intelligence.

SKILLS
SQL, Python, pandas, Statistics, Power BI, Excel, Data Visualization, Data Analysis

EXPERIENCE
Data Analyst, FinScope (Demo) | Feb 2021 - Present
- Automated 15 recurring SQL reports with Python, saving 10 hours per week.
- Analysed A/B tests for pricing experiments that lifted conversion by 6%.

EDUCATION
B.Sc in Statistics, Demo University, 2020

CERTIFICATIONS
Microsoft Power BI Data Analyst (Demo)"""},
]


# ---------------------------------------------------------------------------

def _demo_ids(db):
    hr_ids = [a.account_id for a in db.query(models.HRAccount).filter(models.HRAccount.email.ilike(f"%{DOMAIN}")).all()]
    cand_ids = [a.account_id for a in db.query(models.CandidateAccount).filter(models.CandidateAccount.email.ilike(f"%{DOMAIN}")).all()]
    return hr_ids, cand_ids


def remove_demo(db) -> None:
    """Delete demo rows only (identified by the demo email domain)."""
    hr_ids, cand_ids = _demo_ids(db)
    M = models
    job_ids = [j.job_id for j in db.query(M.JobRole).filter(M.JobRole.hr_account_id.in_(hr_ids)).all()] if hr_ids else []
    cands = db.query(M.Candidate).filter((M.Candidate.email.ilike(f"%{DOMAIN}")) |
                                         (M.Candidate.account_id.in_(cand_ids or [-1]))).all()
    cand_row_ids = [c.candidate_id for c in cands]
    app_ids = [a.application_id for a in db.query(M.Application).filter(
        (M.Application.candidate_id.in_(cand_row_ids or [-1])) | (M.Application.job_id.in_(job_ids or [-1]))).all()]
    ass_ids = [a.assessment_id for a in db.query(M.Assessment).filter(M.Assessment.application_id.in_(app_ids or [-1])).all()]

    def wipe(model, *conds):
        db.query(model).filter(*conds).delete(synchronize_session=False)

    wipe(M.CodingSubmission, M.CodingSubmission.assessment_id.in_(ass_ids or [-1]))
    if hr_ids:   # rows a demo HR created on any application (PostgreSQL enforces foreign keys)
        for model in (M.InterviewSchedule, M.OfferLetter, M.CandidateUnlock):
            wipe(model, model.hr_account_id.in_(hr_ids))
    if cand_ids:
        wipe(M.Referral, (M.Referral.referrer_account_id.in_(cand_ids)) | (M.Referral.referred_account_id.in_(cand_ids)))
    for model in (M.Assessment, M.FinalScore, M.InterviewSchedule, M.OfferLetter, M.CandidateUnlock):
        wipe(model, model.application_id.in_(app_ids or [-1]))
    wipe(M.Application, M.Application.application_id.in_(app_ids or [-1]))
    wipe(M.Resume, M.Resume.candidate_id.in_(cand_row_ids or [-1]))
    wipe(M.Candidate, M.Candidate.candidate_id.in_(cand_row_ids or [-1]))
    wipe(M.AssessmentTemplate, M.AssessmentTemplate.job_id.in_(job_ids or [-1]))
    wipe(M.ATSCheck, M.ATSCheck.job_id.in_(job_ids or [-1]))
    for model in (M.MockInterview, M.MockAssessment):      # practice sessions that targeted a demo job
        db.query(model).filter(model.job_id.in_(job_ids or [-1])).update({"job_id": None}, synchronize_session=False)
    wipe(M.JobRole, M.JobRole.job_id.in_(job_ids or [-1]))
    for role, ids in (("hr", hr_ids), ("candidate", cand_ids)):
        if not ids:
            continue
        wipe(M.AuthSession, M.AuthSession.role == role, M.AuthSession.account_id.in_(ids))
        wipe(M.UserSettings, M.UserSettings.role == role, M.UserSettings.account_id.in_(ids))
        wipe(M.Notification, M.Notification.recipient_role == role, M.Notification.recipient_id.in_(ids))
        wipe(M.CreditTransaction, M.CreditTransaction.account_role == role, M.CreditTransaction.account_id.in_(ids))
        wipe(M.BillingProfile, M.BillingProfile.account_role == role, M.BillingProfile.account_id.in_(ids))
    if hr_ids:
        companies = [c.company_id for c in db.query(M.Company).filter(M.Company.hr_account_id.in_(hr_ids)).all()]
        wipe(M.CompanyDocument, M.CompanyDocument.company_id.in_(companies or [-1]))
        wipe(M.Company, M.Company.hr_account_id.in_(hr_ids))
        wipe(M.HRProfile, M.HRProfile.account_id.in_(hr_ids))
        wipe(M.CodingProblem, M.CodingProblem.hr_account_id.in_(hr_ids))
        wipe(M.OfferTemplate, M.OfferTemplate.hr_account_id.in_(hr_ids))
        wipe(M.HRAccount, M.HRAccount.account_id.in_(hr_ids))
    if cand_ids:
        wipe(M.ATSCheck, M.ATSCheck.account_id.in_(cand_ids))
        wipe(M.ReferralCode, M.ReferralCode.account_id.in_(cand_ids))
        wipe(M.CandidateProfile, M.CandidateProfile.account_id.in_(cand_ids))
        wipe(M.MockInterview, M.MockInterview.account_id.in_(cand_ids))
        wipe(M.MockAssessment, M.MockAssessment.account_id.in_(cand_ids))
        wipe(M.CandidateAccount, M.CandidateAccount.account_id.in_(cand_ids))
    wipe(M.EmailLog, M.EmailLog.to_email.ilike(f"%{DOMAIN}")) if hasattr(M.EmailLog, "to_email") else None
    db.commit()
    log.info("Removed demo data: %d HR, %d candidate accounts, %d jobs", len(hr_ids), len(cand_ids), len(job_ids))


def _solid_png(rgb, size=96) -> bytes:
    """A small square PNG in one colour (no imaging library needed)."""
    import struct
    import zlib
    raw = b"".join(b"\x00" + bytes(rgb) * size for _ in range(size))
    def chunk(tag, data):
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


def _create_hr(db, spec) -> models.HRAccount:
    hr = models.HRAccount(name=spec["name"], company=spec["company"], email=spec["email"],
                          password_hash=hash_password(PASSWORD), phone=spec["phone"])
    db.add(hr); db.flush()
    color = COMPANY_COLORS[HRS.index(spec) % len(COMPANY_COLORS)]
    db.add(models.HRProfile(account_id=hr.account_id, phone=spec["phone"], designation=spec["designation"],
                            department=spec["department"], location=spec["location"],
                            photo_path=files.save_bytes(_solid_png(tuple(max(0, c - 60) for c in color)), "photos", ".png"),
                            linkedin="https://www.linkedin.com/in/demo-profile"))
    now = datetime.utcnow()
    company = models.Company(
        hr_account_id=hr.account_id, name=spec["company"], official_email=spec["email"], website=spec["website"],
        logo_path=files.save_bytes(_solid_png(color), "logos", ".png"),
        description=f"{spec['company']} is a DEMO {spec['industry'].lower()} company created by the Hirelune demo seed "
                    f"for testing. Headquartered in {spec['hq']}, team size {spec['size']}.",
        industry=spec["industry"], company_size=spec["size"], headquarters=spec["hq"], registration_number=spec["reg"],
        gst_number=spec["gst"], contact_number=spec["phone"], verification_status="verified",
        submitted_at=now - timedelta(days=3), verified_at=now - timedelta(days=2), reviewed_by="demo-seed")
    db.add(company); db.flush()
    for doc_type, title in (("id_proof", "Employee ID card"), ("visiting_card", "Visiting card"),
                            ("registration_proof", "Certificate of incorporation")):
        body = f"DEMO / TEST DOCUMENT - NOT A REAL {title.upper()}\n\n{spec['company']}\n{spec['name']}\nGenerated by app.seed_demo"
        path = files.save_bytes(text_pdf(f"DEMO {title}", body), "company_docs", ".pdf")
        db.add(models.CompanyDocument(company_id=company.company_id, doc_type=doc_type,
                                      file_name=f"demo-{doc_type.replace('_', '-')}.pdf", file_path=path,
                                      content_type="application/pdf", uploaded_at=now - timedelta(days=3)))
    db.commit()
    credits_service.grant_signup_bonus(db, "hr", hr.account_id)
    settings_service.get_settings(db, "hr", hr.account_id)
    return hr


def _create_candidate(db, spec) -> tuple[models.CandidateAccount, str]:
    email = spec["key"] + DOMAIN
    acc = models.CandidateAccount(name=spec["name"], email=email, password_hash=hash_password(PASSWORD), phone=spec["phone"])
    db.add(acc); db.flush()
    pdf = text_pdf(spec["name"].replace(" (Demo)", ""), f"{email} | {spec['phone']} | linkedin.com/in/{spec['key']}-demo\n\n{spec['resume']}")
    resume_path = files.save_bytes(pdf, "resumes", ".pdf")
    edu_line = next((ln for ln in spec["resume"].split("EDUCATION\n")[1].splitlines() if ln.strip()), "")
    db.add(models.CandidateProfile(
        account_id=acc.account_id, headline=spec["headline"], phone=spec["phone"], location=spec["location"],
        linkedin=f"https://www.linkedin.com/in/{spec['key']}-demo", github=f"https://github.com/{spec['key']}-demo",
        education=json.dumps([{"degree": edu_line.split(",")[0], "institution": (edu_line.split(",")[1:2] or [""])[0].strip(),
                               "graduation_year": next((w for w in edu_line.replace(",", " ").split() if w.isdigit() and len(w) == 4), "")}]),
        experience=json.dumps([]), projects=json.dumps([]), certifications=json.dumps([]),
        technical_skills=json.dumps(spec["skills"]), soft_skills=json.dumps(["Communication", "Teamwork"]),
        tools=json.dumps([]), languages=json.dumps(["English"]), frameworks=json.dumps([]),
        resume_file_name=f"{spec['key']}-demo-resume.pdf", resume_path=resume_path, resume_uploaded_at=datetime.utcnow()))
    db.commit()
    credits_service.grant_signup_bonus(db, "candidate", acc.account_id)
    settings_service.get_settings(db, "candidate", acc.account_id)
    return acc, resume_path


def _template(db, job, hr, title, kind, questions, status):
    qset = {"skills_covered": sorted({q["skill"] for q in questions}), "questions": questions}
    t = models.AssessmentTemplate(job_id=job.job_id, hr_account_id=hr.account_id, title=title, assessment_type=kind,
                                  difficulty="medium", num_questions=len(questions), time_limit_minutes=job.assessment_minutes,
                                  skills=json.dumps([s.strip() for s in job.requirements.split(",")]),
                                  questions=json.dumps(qset), status=status,
                                  generation_notes=json.dumps(["DEMO assessment written by the demo seed (not AI-generated)."]),
                                  published_at=datetime.utcnow() if status == "published" else None)
    db.add(t); db.commit()
    return t


def _problem(db, slug):
    return db.query(models.CodingProblem).filter(models.CodingProblem.slug == slug).first()


def _coding_q(p, skill):
    return {"type": "coding", "skill": skill, "difficulty": p.difficulty, "question": p.title, "options": None,
            "correct_option_label": None, "reference_answer": None, "problem_id": p.problem_id}


def seed(db) -> None:
    from .agents.resume_parser import parse_resume
    from .scoring_service import run_and_store_screening
    from .services import assessment_service, code_runner

    hrs = [_create_hr(db, s) for s in HRS]
    jobs = {}
    for spec in JOBS:
        data = {k: v for k, v in spec.items() if k not in ("hr", "key")}
        job = models.JobRole(**data, hr_account_id=hrs[int(spec["hr"])].account_id, status="open")
        db.add(job); db.commit(); db.refresh(job)
        jobs[spec["key"]] = job

    maxsub, brackets = _problem(db, "max-subarray"), _problem(db, "balanced-brackets")
    arr, pal, words = _problem(db, "array-sum"), _problem(db, "palindrome-check"), _problem(db, "word-frequency")
    ml, fs, da = jobs["ml"], jobs["fs"], jobs["da"]
    _template(db, ml, hrs[0], "ML Engineer screening (Demo) — mixed", "mixed", ML_MCQ[:5] + [_coding_q(maxsub, "Python")], "published")
    _template(db, ml, hrs[0], "ML coding round (Demo)", "coding", [_coding_q(maxsub, "Python"), _coding_q(words, "NLP")], "draft")
    _template(db, fs, hrs[1], "Full Stack screening (Demo) — mixed", "mixed", FS_MCQ[:5] + [_coding_q(brackets, "JavaScript")], "published")
    _template(db, fs, hrs[1], "Full Stack fundamentals (Demo) — MCQ", "mcq", FS_MCQ, "draft")
    _template(db, fs, hrs[1], "Full Stack coding round (Demo)", "coding", [_coding_q(arr, "JavaScript"), _coding_q(pal, "JavaScript")], "draft")
    _template(db, da, hrs[0], "Data Analyst screening (Demo) — MCQ", "mcq", DA_MCQ, "published")
    coding_for = {"android": arr, "backend": brackets, "ds": maxsub, "frontend": pal}
    for spec in JOBS:
        key = spec["key"]
        if key in EXTRA_MCQ:
            job = jobs[key]
            qs = list(EXTRA_MCQ[key]) + ([_coding_q(coding_for[key], EXTRA_MCQ[key][0]["skill"])] if key in coding_for else [])
            _template(db, job, hrs[int(spec["hr"])], f"{job.title.replace(' (Demo)', '')} screening (Demo)",
                      "mixed" if key in coding_for else "mcq", qs, "published")

    python_ok = code_runner.is_available("python")
    for i, spec in enumerate(CANDIDATES):
        acc, resume_path = _create_candidate(db, spec)
        job = jobs[spec["job"]]
        cand = models.Candidate(name=spec["name"], email=acc.email, phone=spec["phone"], account_id=acc.account_id)
        db.add(cand); db.flush()
        app = models.Application(candidate_id=cand.candidate_id, job_id=job.job_id, status="submitted",
                                 applied_at=datetime.utcnow() - timedelta(days=6 - i))
        db.add(app); db.commit(); db.refresh(app)

        parsed = parse_resume(resume_path, candidate_name=spec["name"])
        resume = models.Resume(candidate_id=cand.candidate_id, file_name=f"{spec['key']}-demo-resume.pdf",
                               file_path=resume_path, skills=parsed.get("skills", ""),
                               experience=parsed.get("experience", ""), education=parsed.get("education", ""),
                               experience_years=parsed.get("experience_years"),
                               experience_entries=json.dumps(parsed.get("experience_entries", [])))
        db.add(resume); app.status = "parsed"; db.commit(); db.refresh(resume)
        screening = run_and_store_screening(db, app, resume)
        log.info("%s screened: %s", spec["name"], screening.get("status"))

        if spec["level"] is None:
            continue   # left for a live assessment during testing
        db.refresh(app)
        a, _ = assessment_service.start(db, app)
        qs = json.loads(a.questions)["questions"]
        mcq_idx = [k for k, q in enumerate(qs) if q["type"] == "mcq"]
        n_right = round(len(mcq_idx) * spec["level"])
        answers = {}
        for rank, k in enumerate(mcq_idx):
            right = qs[k]["correct_option_label"]
            answers[k] = right if rank < n_right else next(o["label"] for o in qs[k]["options"] if o["label"] != right)
        for k, q in enumerate(qs):
            if q["type"] == "coding" and spec["code"] and python_ok:
                p = db.get(models.CodingProblem, q["problem_id"])
                src = SOLUTIONS.get(p.slug, {}).get(spec["code"])
                if src:
                    assessment_service.run_code(db, app, k, "python", src, "submit")
        result = assessment_service.submit(db, app, answers)
        log.info("%s assessment: %s", spec["name"], result.get("test_score", result.get("score")))
    if not python_ok:
        log.warning("Python code runner unavailable: demo coding questions were left unanswered.")


def main():
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    ap = argparse.ArgumentParser(description="Hirelune DEMO/TEST data")
    ap.add_argument("--reset", action="store_true", help="remove demo rows, then re-create them")
    ap.add_argument("--remove", action="store_true", help="remove demo rows only")
    args = ap.parse_args()
    db = SessionLocal()
    try:
        if args.reset or args.remove:
            remove_demo(db)
        if args.remove:
            return
        if _demo_ids(db)[0]:
            log.info("Demo data already exists — use --reset to recreate it.")
            return
        seed(db)
        log.info("\nDEMO accounts (password %s):", PASSWORD)
        for s in HRS:
            log.info("  HR         %s", s["email"])
        for s in CANDIDATES:
            log.info("  Candidate  %s%s", s["key"], DOMAIN)
    finally:
        db.close()


if __name__ == "__main__":
    main()
