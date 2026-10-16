from app.agents.skill_agent import normalize_skill, parse_requirements, score_skills


# ---- Required behaviours ---------------------------------------------------

def test_exact_match():
    result = score_skills("Python, SQL", "Python, SQL")
    assert result["score"] == 100.0
    assert result["matched"] == ["Python", "SQL"]
    assert result["missing"] == []


def test_alias_match():
    result = score_skills("PostgreSQL, JavaScript, scikit-learn, NLP", "Postgres, JS, sklearn, Natural Language Processing")
    assert result["score"] == 100.0
    assert result["match_details"]["Postgres"] == "PostgreSQL"


def test_ml_alias_is_exact_not_substring():
    assert score_skills("Machine Learning", "ML")["score"] == 100.0
    # "ml" must not match inside "HTML" by substring.
    assert score_skills("HTML", "ML")["score"] == 0.0


def test_js_variants():
    result = score_skills("React.js, Node.js", "ReactJS, Node js")
    assert result["score"] == 100.0
    assert normalize_skill("React.js") == normalize_skill("reactjs") == "react"
    assert normalize_skill("Node JS") == "node"


def test_semicolon_requirements():
    result = score_skills("Python, SQL", "Python; SQL; Tableau")
    assert result["score"] == 66.7
    assert result["missing"] == ["Tableau"]


def test_newline_and_short_and_slash_split():
    assert parse_requirements("Python\nSQL and Tableau\nHTML/CSS") == ["Python", "SQL", "Tableau", "HTML", "CSS"]
    # Long phrases are not split on "and".
    long_phrase = "Experience designing and operating large distributed data pipelines"
    assert parse_requirements(long_phrase) == [long_phrase]


def test_list_candidate_input():
    result = score_skills(["Python", "MySQL"], "Python, MySQL")
    assert result["score"] == 100.0


def test_empty_requirements():
    result = score_skills("Python", "")
    assert result["score"] == 0.0
    assert result["matched"] == []
    assert result["missing"] == []


def test_none_detected():
    result = score_skills("None detected", "Python")
    assert result["score"] == 0.0
    assert result["matched"] == []
    assert result["missing"] == ["Python"]


def test_single_letter_false_positive():
    result = score_skills("C++, C#, Ruby, Django", "C, R, Go")
    assert result["score"] == 0.0
    assert result["missing"] == ["C", "R", "Go"]


def test_single_letter_exact_match_still_works():
    assert score_skills("C, R", "C; R")["score"] == 100.0


def test_phrase_containment_requires_whole_words():
    assert score_skills("Applied Machine Learning", "Machine Learning")["score"] == 100.0
    # "Java" is not satisfied by "JavaScript".
    assert score_skills("JavaScript", "Java")["score"] == 0.0


def test_mysql_does_not_satisfy_sql():
    result = score_skills("Python, MySQL", "SQL, Python, Tableau")
    assert result["score"] == 33.3
    assert result["matched"] == ["Python"]
    assert result["missing"] == ["SQL", "Tableau"]


def test_return_keys_unchanged():
    result = score_skills("Python", "Python")
    assert {"score", "matched", "missing", "extra"} <= set(result)


# ---- Explicit bug cases ----------------------------------------------------

def test_full_match_is_100():
    result = score_skills("SQL, Python, Tableau", "SQL, Python, Tableau")
    assert result["score"] == 100.0
    assert result["matched"] == ["SQL", "Python", "Tableau"]
    assert result["missing"] == []


def test_full_match_any_order_is_100():
    assert score_skills("Python, SQL, Tableau", "SQL, Python, Tableau")["score"] == 100.0


def test_partial_match_is_66_7():
    result = score_skills("SQL, Python", "SQL, Python, Tableau")
    assert result["score"] == 66.7
    assert result["matched"] == ["SQL", "Python"]
    assert result["missing"] == ["Tableau"]


def test_no_overlap_is_valid_zero():
    candidate = "Python, SQL, Tableau, Machine Learning, Pandas, NumPy, scikit-learn, REST APIs, Git"
    result = score_skills(candidate, "PyTorch, NLP")
    assert result["score"] == 0.0
    assert result["matched"] == []
    assert result["missing"] == ["PyTorch", "NLP"]
