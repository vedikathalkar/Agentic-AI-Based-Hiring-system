"""NLP search: query understanding and ranking (pure functions, no web stack)."""

from app.services.search_service import describe, merge_filters, parse_query, rank_candidates, rank_jobs

JOBS = [
    dict(job_id=1, title="Machine Learning Engineer", requirements="Python, Machine Learning, PyTorch, SQL",
         location="Bengaluru · Hybrid", min_experience=2, description="Build ML models"),
    dict(job_id=2, title="Full Stack Developer", requirements="JavaScript, React, Node.js, TypeScript",
         location="Pune · On-site", min_experience=2, description="React and Node"),
    dict(job_id=3, title="Data Analyst", requirements="SQL, Excel, Tableau, Python", location="Remote", min_experience=1,
         description="Dashboards"),
]
LOCS = [j["location"] for j in JOBS]


def labels(q):
    return [c["label"] for c in describe(parse_query(q, extra_locations=LOCS))]


def test_parses_skills_places_mode_and_experience():
    assert labels("remote python ml jobs in pune 2+ years") == ["Python", "Machine Learning", "Pune", "Remote", "2+ yrs"]
    assert labels("node js typescript hybrid 3-5 yrs") == ["TypeScript", "Node.js", "Hybrid", "3–5 yrs"]
    p = parse_query("senior react developer bangalore")
    assert p["min_experience"] == 4 and p["locations"] == ["bengaluru"]


def test_typos_are_corrected():
    p = parse_query("pyhton developr in banglore")
    assert p["skills"] == ["python"] and p["locations"] == ["bengaluru"] and p["keywords"] == []
    assert "pyhton → Python" in [c.replace("python", "Python") for c in p["corrections"]]


def test_hr_query_parses_status_and_score():
    p = parse_query("shortlisted candidates with python 3+ years score above 70")
    assert (p["status"], p["min_experience"], p["min_score"], p["skills"]) == ("shortlisted", 3.0, 70.0, ["python"])


def test_rank_jobs_filters_and_explains():
    titles = lambda q: [r["job"]["title"] for r in rank_jobs(JOBS, parse_query(q, extra_locations=LOCS))]
    assert titles("python") == ["Machine Learning Engineer", "Data Analyst"]
    assert titles("react pune") == ["Full Stack Developer"]
    assert titles("remote python") == ["Data Analyst"]
    assert titles("frontend") == ["Full Stack Developer"]          # role word expands to React/JavaScript
    assert titles("senior java") == []
    assert titles("") == [j["title"] for j in JOBS]                 # empty query lists everything
    explicit = merge_filters(parse_query(""), work_mode="hybrid")
    assert [r["job"]["title"] for r in rank_jobs(JOBS, explicit)] == ["Machine Learning Engineer"]


def test_rank_candidates():
    rows = [dict(candidate_name="A", skills="Python, SQL", experience_years=5, final_score=85, status="shortlisted"),
            dict(candidate_name="B", skills="Python", experience_years=1, final_score=60, status="assessed"),
            dict(candidate_name="C", skills="React", experience_years=4, final_score=None, skill_score=70, status="assessed")]
    names = lambda q: [r["row"]["candidate_name"] for r in rank_candidates(rows, parse_query(q))]
    assert names("python 3+ years") == ["A"]
    assert names("python") == ["A", "B"]
    assert names("score above 65") == ["A", "C"]
    assert names("shortlisted") == ["A"]
