from app.services.ats_service import analyze, job_keywords

RESUME = """Neha Dhumal
neha@example.com | +91 98200 12345 | linkedin.com/in/neha
Summary
Data analyst with 2 years of experience.
Experience
Data Analyst, Acme — Jan 2023 – Present
- Built Tableau dashboards used by 40 managers, reducing reporting time by 30%.
- Automated SQL pipelines in Python (Pandas), improved data quality by 25%.
- Led a migration of 12 reports to Power BI.
Education
B.Tech Computer Engineering, 2022
Skills
Python, SQL, Tableau, Pandas, Excel, Git
Projects
Sales forecasting with scikit-learn
"""


def test_keywords_from_requirements_and_description():
    kws = job_keywords("We need someone strong in Docker and machine learning.", "SQL, Python; Tableau")
    assert kws[:3] == ["SQL", "Python", "Tableau"]
    assert "docker" in kws and "machine learning" in kws


def test_analysis_matches_and_misses():
    r = analyze(RESUME, "Experience with Docker is a plus", "SQL, Python, Tableau, PyTorch", min_experience=1)
    assert r["label"] == "Hirelune ATS analysis"
    assert set(r["keywords"]["matched"]) == {"SQL", "Python", "Tableau"}
    assert set(r["keywords"]["missing"]) == {"PyTorch", "docker"}
    assert {"experience", "education", "skills", "summary", "projects"} <= set(r["sections"]["found"])
    assert r["contact"] == {"email": True, "phone": True, "linkedin": True, "github": False}
    assert 0 <= r["score"] <= 100
    assert r["quantified_achievements"] >= 3
    assert "meeting" in r["experience_relevance"]


def test_short_mysql_does_not_match_sql_and_aliases_work():
    r = analyze("Skills\nMySQL, JS, sklearn\nExperience\nEducation", "", "SQL, JavaScript, scikit-learn")
    assert r["keywords"]["missing"] == ["SQL"]
    assert set(r["keywords"]["matched"]) == {"JavaScript", "scikit-learn"}


def test_empty_resume_warns():
    r = analyze("", "", "Python")
    assert r["keywords"]["missing"] == ["Python"]
    assert any("little text" in w for w in r["formatting_issues"])
