"""Smart search: natural-language query understanding + structured filters.

A query such as "remote python ml jobs in pune 2+ years" is parsed into
structured filters (skills, locations, work mode, experience, seniority) plus
free-text keywords. Explicit filters from the UI override what was parsed.
Results are ranked by how well they match, and every result explains why.

NLP pieces (dependency-free, deterministic):
* tokenisation, stop-word removal and light stemming;
* skill entity recognition using the platform's skill vocabulary and aliases
  (the same normaliser the screening agents use), multi-word phrases first;
* typo tolerance (fuzzy matching with difflib) for skills and locations;
* pattern extraction for experience ranges ("3+ years", "2-5 yrs", "fresher"),
  scores ("score above 70"), work mode and seniority;
* TF-IDF style weighting for the remaining keywords.
"""

from __future__ import annotations

import math
import re
from difflib import SequenceMatcher, get_close_matches
from typing import Iterable, Optional

from ..agents.skill_agent import ALIASES, normalize_skill, parse_requirements

STOPWORDS = {
    "a", "an", "the", "and", "or", "for", "of", "to", "in", "at", "on", "with", "without", "who", "that", "which",
    "job", "jobs", "role", "roles", "position", "positions", "opening", "openings", "vacancy", "vacancies",
    "candidate", "candidates", "people", "profile", "profiles", "developer", "developers", "engineer", "engineers",
    "looking", "find", "show", "me", "want", "need", "hiring", "work", "working", "based", "near", "around",
    "experience", "experienced", "exp", "year", "years", "yr", "yrs", "having", "has", "have", "know", "knows",
    "knowing", "skill", "skills", "good", "strong", "plus", "any", "all", "from", "is", "are", "i", "my", "please",
}
# Words that describe the role but are useful as keywords (kept out of STOPWORDS on purpose).
ROLE_WORDS = {"frontend", "backend", "fullstack", "full", "stack", "data", "analyst", "scientist", "ml", "ai", "devops",
              "mobile", "android", "ios", "qa", "test", "security", "cloud", "product", "designer", "manager"}

# Role words expand to the skills they usually imply ("frontend" finds React jobs).
ROLE_EXPANSIONS = {
    "frontend": ["react", "javascript", "typescript", "html", "css", "angular", "vue", "frontend", "front end", "ui"],
    "backend": ["node", "python", "java", "django", "fastapi", "spring", "sql", "rest apis", "backend", "back end", "api"],
    "fullstack": ["full stack", "react", "node", "javascript"],
    "devops": ["docker", "kubernetes", "aws", "terraform", "ci/cd", "jenkins", "devops"],
    "analyst": ["analyst", "sql", "excel", "tableau", "power bi", "data analysis"],
    "scientist": ["scientist", "machine learning", "statistics", "python"],
    "ai": ["machine learning", "deep learning", "nlp", "llm", "ai"],
    "mobile": ["android", "ios", "flutter", "react native", "kotlin", "swift"],
    "cloud": ["aws", "azure", "gcp", "cloud"],
    "qa": ["selenium", "testing", "qa", "automation"],
}

CITIES = [
    "bengaluru", "bangalore", "mumbai", "pune", "delhi", "new delhi", "gurugram", "gurgaon", "noida", "hyderabad",
    "chennai", "kolkata", "ahmedabad", "jaipur", "kochi", "indore", "chandigarh", "coimbatore", "nagpur", "lucknow",
    "thiruvananthapuram", "mysuru", "vadodara", "surat", "bhubaneswar", "visakhapatnam", "goa", "london", "singapore",
    "dubai", "new york", "san francisco", "berlin", "toronto",
]
CITY_ALIASES = {"bangalore": "bengaluru", "gurgaon": "gurugram", "new delhi": "delhi", "bombay": "mumbai",
                "madras": "chennai", "calcutta": "kolkata", "blr": "bengaluru", "ncr": "delhi"}
WORK_MODES = {"remote": "remote", "wfh": "remote", "work from home": "remote", "hybrid": "hybrid",
              "onsite": "on-site", "on-site": "on-site", "on site": "on-site", "office": "on-site", "in-office": "on-site"}
SENIORITY = {"intern": (0, 0.5), "internship": (0, 0.5), "fresher": (0, 1), "freshers": (0, 1), "entry": (0, 1),
             "graduate": (0, 1), "junior": (0, 2), "jr": (0, 2), "associate": (0, 3), "mid": (2, 5),
             "senior": (4, None), "sr": (4, None), "lead": (6, None), "principal": (8, None), "staff": (7, None)}
STATUS_WORDS = {"shortlisted": "shortlisted", "rejected": "rejected", "hired": "hired", "offered": "offered",
                "interviewed": "interviewed", "scheduled": "scheduled", "assessed": "assessed", "new": "submitted",
                "applied": "submitted", "screened": "in_review"}

# Base skill vocabulary (extended at runtime with the skills present in the data).
_BASE_SKILLS = [
    "python", "java", "javascript", "typescript", "c++", "c#", "go", "golang", "rust", "kotlin", "swift", "php", "ruby",
    "scala", "r", "sql", "mysql", "postgresql", "mongodb", "redis", "nosql", "react", "angular", "vue", "next.js",
    "node", "express", "django", "flask", "fastapi", "spring", "spring boot", ".net", "html", "css", "tailwind",
    "redux", "graphql", "rest apis", "microservices", "aws", "azure", "gcp", "docker", "kubernetes", "terraform",
    "jenkins", "ci/cd", "git", "linux", "machine learning", "deep learning", "nlp", "computer vision", "pytorch",
    "tensorflow", "keras", "scikit-learn", "pandas", "numpy", "tableau", "power bi", "excel", "statistics",
    "data analysis", "data visualization", "etl", "spark", "hadoop", "airflow", "kafka", "snowflake", "llm",
    "langchain", "generative ai", "selenium", "figma", "mlops", "android", "flutter", "react native",
]

_WORD = re.compile(r"[a-z0-9][a-z0-9+#./-]*")


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").lower()).strip()


def _stem(word: str) -> str:
    for suffix in ("ing", "ers", "er", "es", "s"):
        if len(word) > 4 and word.endswith(suffix):
            return word[: -len(suffix)]
    return word


def tokens(text: str) -> list[str]:
    return [t.strip("./-") for t in _WORD.findall(_norm(text)) if t.strip("./-")]


def skill_vocabulary(extra: Iterable[str] = ()) -> dict[str, str]:
    """phrase -> display name, including aliases (js -> JavaScript)."""
    vocab: dict[str, str] = {}
    for s in [x for x in extra if x] + list(_BASE_SKILLS):
        key = normalize_skill(s)
        if key:
            vocab.setdefault(_norm(s), s if s != s.lower() else key)
            vocab.setdefault(key, s if s != s.lower() else key)
    for alias, canon in ALIASES.items():
        vocab.setdefault(_norm(alias), vocab.get(canon, canon))
    return vocab


def _phrase_in(text: str, phrase: str) -> bool:
    return re.search(rf"(?<![\w+#]){re.escape(phrase)}(?![\w+#])", text) is not None


def parse_query(q: str, extra_skills: Iterable[str] = (), extra_locations: Iterable[str] = ()) -> dict:
    """Turn free text into structured filters. Never raises."""
    text = _norm(q)
    for a, b in (("full stack", "fullstack"), ("full-stack", "fullstack"), ("front end", "frontend"),
                 ("front-end", "frontend"), ("back end", "backend"), ("back-end", "backend")):
        text = text.replace(a, b)
    text = re.sub(r"\b(node|react|vue|next|express)\s*\.?\s*js\b", r"\1js", text)
    out = {"text": q or "", "skills": [], "locations": [], "work_mode": None, "min_experience": None,
           "max_experience": None, "min_score": None, "status": None, "seniority": None, "keywords": [], "corrections": [],
           "sources": {}}
    if not text:
        return out
    rest = f" {text} "

    # 1. Experience ranges.
    m = re.search(r"(\d+(?:\.\d+)?)\s*(?:-|to|–)\s*(\d+(?:\.\d+)?)\s*(?:\+)?\s*(?:years?|yrs?|y)\b", rest)
    if m:
        out["min_experience"], out["max_experience"] = float(m.group(1)), float(m.group(2))
        out["sources"]["experience"] = m.group(0).strip()
        rest = rest.replace(m.group(0), " ")
    else:
        m = re.search(r"(?:(?:at\s*least|min(?:imum)?|over|more\s*than|above)\s*)?(\d+(?:\.\d+)?)\s*\+?\s*(?:\+\s*)?(?:years?|yrs?|y)\b(?:\s*(?:of\s*)?(?:experience|exp))?", rest)
        if m:
            out["min_experience"] = float(m.group(1))
            out["sources"]["experience"] = m.group(0).strip()
            rest = rest.replace(m.group(0), " ")
        m2 = re.search(r"(?:under|less\s*than|below|upto|up\s*to|max(?:imum)?)\s*(\d+(?:\.\d+)?)\s*(?:years?|yrs?)", rest)
        if m2:
            out["max_experience"] = float(m2.group(1))
            out["sources"]["experience"] = (out["sources"].get("experience", "") + " " + m2.group(0).strip()).strip()
            rest = rest.replace(m2.group(0), " ")

    # 2. Score threshold (HR search): "score above 70", "70%+", "score > 80".
    m = re.search(r"(?:score|match|final|rank)\w*\s*(?:above|over|>=?|at\s*least|more\s*than|of)?\s*(\d{1,3})\s*%?\+?", rest)
    if not m:
        m = re.search(r"\b(\d{1,3})\s*%\s*\+?\s*(?:score|match)?", rest)
    if m and 0 < int(m.group(1)) <= 100:
        out["min_score"] = float(m.group(1))
        out["sources"]["min_score"] = m.group(0).strip()
        rest = rest.replace(m.group(0), " ")

    # 3. Work mode.
    for phrase, mode in sorted(WORK_MODES.items(), key=lambda kv: -len(kv[0])):
        if _phrase_in(rest, phrase):
            out["work_mode"] = mode
            out["sources"]["work_mode"] = phrase
            rest = re.sub(rf"(?<![\w-]){re.escape(phrase)}(?![\w-])", " ", rest)
            break

    # 4. Seniority -> experience band (only if no explicit years were given).
    for word, (lo, hi) in SENIORITY.items():
        if _phrase_in(rest, word):
            out["seniority"] = word
            out["sources"]["experience"] = word
            if out["min_experience"] is None and out["max_experience"] is None:
                out["min_experience"], out["max_experience"] = (lo or None), hi
            rest = re.sub(rf"(?<![\w-]){re.escape(word)}(?![\w-])", " ", rest)
            break

    # 5. Application status words (HR search).
    for word, status in STATUS_WORDS.items():
        if _phrase_in(rest, word):
            out["status"] = status
            out["sources"]["status"] = word
            rest = re.sub(rf"(?<![\w-]){re.escape(word)}(?![\w-])", " ", rest)
            break

    # 6. Locations: known cities, locations present in the data, and "in <place>".
    places = {c: CITY_ALIASES.get(c, c) for c in CITIES}
    for loc in extra_locations:
        for part in re.split(r"[·,|/]", _norm(loc)):
            part = part.strip()
            if part and part not in WORK_MODES and len(part) > 2:
                places.setdefault(part, CITY_ALIASES.get(part, part))
    for alias, canon in CITY_ALIASES.items():
        places.setdefault(alias, canon)
    for phrase in sorted(places, key=len, reverse=True):
        if _phrase_in(rest, phrase):
            canon = places[phrase]
            if canon not in out["locations"]:
                out["locations"].append(canon)
                out["sources"][f"location:{canon}"] = phrase
            rest = re.sub(rf"(?<![\w-]){re.escape(phrase)}(?![\w-])", " ", rest)

    # 7. Skills: longest phrases first so "machine learning" wins over "learning".
    vocab = skill_vocabulary(extra_skills)
    for phrase in sorted(vocab, key=len, reverse=True):
        if len(phrase) < 1:
            continue
        if _phrase_in(rest, phrase):
            name = vocab[phrase]
            if normalize_skill(name) not in {normalize_skill(s) for s in out["skills"]}:
                out["skills"].append(name)
                out["sources"][f"skill:{name}"] = phrase
            rest = re.sub(rf"(?<![\w+#]){re.escape(phrase)}(?![\w+#])", " ", rest)

    # 8. Remaining words: typo-tolerant skill / city match, otherwise keywords.
    single_skills = [p for p in vocab if " " not in p and len(p) >= 4]
    for tok in tokens(rest):
        if tok in STOPWORDS or (tok.isdigit() and len(tok) < 3) or tok in {"in", "at"}:
            continue
        if len(tok) >= 5 and get_close_matches(tok, list(STOPWORDS), n=1, cutoff=0.85):
            continue            # misspelt filler word ("developr")
        if len(tok) >= 4:
            close = get_close_matches(tok, single_skills, n=1, cutoff=0.8 if len(tok) >= 5 else 0.84)
            if close:
                name = vocab[close[0]]
                if normalize_skill(name) not in {normalize_skill(s) for s in out["skills"]}:
                    out["skills"].append(name)
                    out["sources"][f"skill:{name}"] = tok
                    out["corrections"].append(f"{tok} → {name}")
                continue
            close = get_close_matches(tok, [p for p in places if " " not in p], n=1, cutoff=0.84)
            if close and places[close[0]] not in out["locations"]:
                out["locations"].append(places[close[0]])
                out["sources"][f"location:{places[close[0]]}"] = tok
                out["corrections"].append(f"{tok} → {places[close[0]].title()}")
                continue
        if tok not in out["keywords"]:
            out["keywords"].append(tok)
    return out


def merge_filters(parsed: dict, *, skills: Optional[list[str]] = None, location: Optional[str] = None,
                  work_mode: Optional[str] = None, min_experience: Optional[float] = None,
                  max_experience: Optional[float] = None, min_score: Optional[float] = None,
                  status: Optional[str] = None) -> dict:
    """Explicit UI filters win over values parsed from the text."""
    f = dict(parsed)
    if skills:
        f["skills"] = list(dict.fromkeys([*f.get("skills", []), *skills]))
    if location:
        f["locations"] = [_norm(location)]
    for key, value in (("work_mode", work_mode), ("min_experience", min_experience), ("max_experience", max_experience),
                       ("min_score", min_score), ("status", status)):
        if value not in (None, ""):
            f[key] = value
    return f


def _idf(docs: list[str], term: str) -> float:
    n = sum(1 for d in docs if term in d)
    return math.log((1 + len(docs)) / (1 + n)) + 1


def _location_match(job_location: str, wanted: list[str]) -> bool:
    loc = _norm(job_location)
    loc = " ".join(CITY_ALIASES.get(p, p) for p in re.split(r"\s+", loc))
    return any(w in loc or SequenceMatcher(None, w, loc).ratio() > 0.85 for w in wanted)


def _mode_of(location: str) -> Optional[str]:
    loc = _norm(location)
    for phrase, mode in WORK_MODES.items():
        if phrase in loc:
            return mode
    return None


def rank_jobs(jobs: list[dict], f: dict) -> list[dict]:
    """jobs: dicts with title, team, description, requirements, preferred_skills, location, min_experience,
    company_name. Returns [{job, score, matched_skills, reasons}] filtered and sorted."""
    docs = [_norm(" ".join(str(j.get(k) or "") for k in ("title", "team", "description", "requirements",
                                                       "preferred_skills", "company_name"))) for j in jobs]
    wanted = [normalize_skill(s) for s in f.get("skills", [])]
    out = []
    for job, doc in zip(jobs, docs):
        reasons = []
        # Hard filters.
        if f.get("locations") and not _location_match(job.get("location") or "", f["locations"]):
            if not (f.get("work_mode") == "remote" and _mode_of(job.get("location") or "") == "remote"):
                continue
        if f.get("work_mode") and _mode_of(job.get("location") or "") not in (f["work_mode"], None):
            continue
        need = float(job.get("min_experience") or 0)
        if f.get("max_experience") is not None and need > float(f["max_experience"]):
            continue
        if f.get("min_experience") is not None and need + 3 < float(f["min_experience"]):
            continue   # far too junior for what the user asked
        # Soft scoring.
        reqs = {normalize_skill(r) for r in parse_requirements(job.get("requirements") or "")}
        prefs = {normalize_skill(r) for r in parse_requirements(job.get("preferred_skills") or "")}
        matched = [s for s, w in zip(f.get("skills", []), wanted) if w in reqs or w in prefs or _phrase_in(doc, w)]
        score = 0.0
        if wanted:
            if not matched:
                continue
            score += 60 * len(matched) / len(wanted)
            reasons.append(f"{len(matched)}/{len(wanted)} skills")
        title = _norm(job.get("title"))
        kw = f.get("keywords", [])
        if kw:
            hits = [k for k in kw if k in doc or _stem(k) in doc
                    or any(_phrase_in(doc, e) for e in ROLE_EXPANSIONS.get(k, []))]
            if not hits and not wanted:
                continue
            score += 30 * sum(_idf(docs, k) for k in hits) / max(1e-9, sum(_idf(docs, k) for k in kw))
            score += 10 * sum(1 for k in hits if k in title or _stem(k) in title) / len(kw)
            if hits:
                reasons.append("matches “" + ", ".join(hits[:3]) + "”")
        if not wanted and not kw:
            score = 50.0
        if f.get("locations"):
            reasons.append(job.get("location") or "")
        if f.get("min_experience") is not None or f.get("max_experience") is not None:
            reasons.append(f"{need:g}+ yrs required")
        out.append({"job": job, "score": round(min(100.0, score), 1), "matched_skills": matched,
                    "reasons": [r for r in reasons if r]})
    out.sort(key=lambda r: -r["score"])
    return out


def rank_candidates(rows: list[dict], f: dict) -> list[dict]:
    """rows: dicts with candidate_name, job_title, status, skills (str), experience_years, final_score,
    skill_score, test_score. Same contract as rank_jobs."""
    wanted = [normalize_skill(s) for s in f.get("skills", [])]
    docs = [_norm(" ".join(str(r.get(k) or "") for k in ("candidate_name", "job_title", "skills", "skill_matched"))) for r in rows]
    out = []
    for row, doc in zip(rows, docs):
        if f.get("status") and row.get("status") != f["status"]:
            continue
        years = row.get("experience_years")
        if f.get("min_experience") is not None and (years is None or years < float(f["min_experience"])):
            continue
        if f.get("max_experience") is not None and years is not None and years > float(f["max_experience"]):
            continue
        best = row.get("final_score") if row.get("final_score") is not None else row.get("skill_score")
        if f.get("min_score") is not None and (best is None or best < float(f["min_score"])):
            continue
        have = {normalize_skill(s) for s in re.split(r"[,;\n]", row.get("skills") or "") if s.strip()}
        matched = [s for s, w in zip(f.get("skills", []), wanted) if w in have or _phrase_in(doc, w)]
        if wanted and not matched:
            continue
        score = 60 * len(matched) / len(wanted) if wanted else 0.0
        kw = f.get("keywords", [])
        hits = [k for k in kw if k in doc or any(_phrase_in(doc, e) for e in ROLE_EXPANSIONS.get(k, []))]
        if kw and not hits and not wanted:
            continue
        if kw:
            score += 25 * len(hits) / len(kw)
        score += 15 * ((best or 0) / 100)
        reasons = []
        if wanted:
            reasons.append(f"{len(matched)}/{len(wanted)} skills")
        if years is not None:
            reasons.append(f"{years:g} yrs")
        if best is not None:
            reasons.append(f"score {best:.0f}")
        out.append({"row": row, "score": round(min(100.0, score if (wanted or kw) else (best or 0)), 1),
                    "matched_skills": matched, "reasons": reasons})
    out.sort(key=lambda r: -r["score"])
    return out


_UPPER = {"sql", "nlp", "aws", "gcp", "css", "html", "etl", "llm", "ci/cd", "php", "mlops", "ui", "qa", "r"}
_PRETTY = {"javascript": "JavaScript", "typescript": "TypeScript", "postgresql": "PostgreSQL", "mongodb": "MongoDB",
           "node": "Node.js", "next.js": "Next.js", "scikit-learn": "scikit-learn", "pytorch": "PyTorch",
           "tensorflow": "TensorFlow", "fastapi": "FastAPI", "graphql": "GraphQL", "numpy": "NumPy", "power bi": "Power BI",
           "c++": "C++", "c#": "C#", ".net": ".NET", "mysql": "MySQL", "github": "GitHub", "rest apis": "REST APIs"}


def pretty_skill(name: str) -> str:
    low = (name or "").lower()
    if name != low:
        return name
    if low in _PRETTY:
        return _PRETTY[low]
    if low in _UPPER:
        return low.upper()
    return " ".join(w.capitalize() for w in low.split())


def describe(f: dict) -> list[dict]:
    """Chips for the UI: what the search understood."""
    chips = []
    src = f.get("sources", {})
    for s in f.get("skills", []):
        chips.append({"kind": "skill", "value": s, "label": pretty_skill(s), "source": src.get(f"skill:{s}")})
    for loc in f.get("locations", []):
        chips.append({"kind": "location", "value": loc, "label": loc.title(), "source": src.get(f"location:{loc}")})
    if f.get("work_mode"):
        chips.append({"kind": "work_mode", "value": f["work_mode"], "label": f["work_mode"].title(), "source": src.get("work_mode")})
    lo, hi = f.get("min_experience"), f.get("max_experience")
    if lo is not None or hi is not None:
        label = f"{lo:g}–{hi:g} yrs" if lo is not None and hi is not None else (f"{lo:g}+ yrs" if lo is not None else f"≤ {hi:g} yrs")
        chips.append({"kind": "experience", "value": [lo, hi], "label": label, "source": src.get("experience")})
    if f.get("min_score") is not None:
        chips.append({"kind": "min_score", "value": f["min_score"], "label": f"≥ {f['min_score']:g}", "source": src.get("min_score")})
    if f.get("status"):
        chips.append({"kind": "status", "value": f["status"], "label": f["status"].replace("_", " "), "source": src.get("status")})
    for k in f.get("keywords", []):
        chips.append({"kind": "keyword", "value": k, "label": f"“{k}”", "source": k})
    return chips
