"""Deterministic, explainable skill matching.

score_skills(candidate_skills, job_requirements) -> {score, matched, missing, extra, match_details}

* ``score`` is a float 0-100 rounded to one decimal: matched / total * 100.
* ``matched`` / ``missing`` keep the job requirement's original spelling.
* ``match_details`` maps each matched requirement to the candidate skill that satisfied it.
"""

from __future__ import annotations

import re
from typing import Iterable

# Every alias maps to one canonical form. Keep all equivalents here so new
# ones are easy to add. Keys and values are already in normalized form
# (lowercase, punctuation such as "." and "-" replaced by spaces).
ALIASES = {
    "postgres": "postgresql",
    "postgresql": "postgresql",
    "ml": "machine learning",
    "machine learning": "machine learning",
    "js": "javascript",
    "javascript": "javascript",
    "reactjs": "react",
    "react": "react",
    "nodejs": "node",
    "node": "node",
    "rest api": "rest api",
    "rest apis": "rest api",
    "restful api": "rest api",
    "restful apis": "rest api",
    "sklearn": "scikit learn",
    "scikit learn": "scikit learn",
    "tf": "tensorflow",
    "tensorflow": "tensorflow",
    "ai": "artificial intelligence",
    "artificial intelligence": "artificial intelligence",
    "nlp": "natural language processing",
    "natural language processing": "natural language processing",
}

# Containment ("Machine Learning" inside "Applied Machine Learning") is only
# allowed when the shorter side has at least this many characters, so short
# skills such as C, R, Go or ML never produce substring false positives.
MIN_CONTAINMENT_LEN = 4

_NONE_MARKERS = {"", "none", "none detected", "n/a", "na"}


def normalize_skill(value) -> str:
    """The single normalization function used for both sides of a match."""
    value = str(value or "").strip().lower()
    # "React.js" / "Node js" -> "react" / "node"; a bare "js" is left alone.
    value = re.sub(r"(?<=\w)(?:\.js|\s+js)$", "", value)
    # Punctuation such as "." and "-" becomes a space; keep "+" and "#"
    # so C++ and C# stay distinct from C.
    value = re.sub(r"[^\w\s+#]|_", " ", value)
    value = re.sub(r"\s+", " ", value).strip()
    return ALIASES.get(value, value)


def _split_requirement_piece(piece: str) -> list[str]:
    """Split "A and B" / "A/B" only when every side is a short (<=3 word) phrase."""
    piece = piece.strip()
    if not piece:
        return []
    parts = re.split(r"\s+and\s+|\s*/\s*", piece, flags=re.I)
    parts = [p.strip() for p in parts]
    if len(parts) > 1 and all(p and len(p.split()) <= 3 for p in parts):
        return parts
    return [piece]


def parse_requirements(value) -> list[str]:
    """Split job requirements on , ; and newlines (then short and / pairs).

    Duplicates (after normalization) are dropped, keeping the first spelling.
    """
    if isinstance(value, (list, tuple, set)):
        raw = [str(v) for v in value]
    else:
        raw = re.split(r"[,;\n]", str(value or ""))
    out, seen = [], set()
    for piece in raw:
        for part in _split_requirement_piece(piece):
            key = normalize_skill(part)
            if key and key not in seen:
                seen.add(key)
                out.append(part)
    return out


def _candidate_list(candidate_skills) -> list[str]:
    """Accept either a comma/semicolon/newline separated string or a list."""
    if isinstance(candidate_skills, (list, tuple, set)):
        items: Iterable = candidate_skills
    else:
        items = re.split(r"[,;\n]", str(candidate_skills or ""))
    out = []
    for item in items:
        text = str(item or "").strip()
        if text.lower() not in _NONE_MARKERS:
            out.append(text)
    return out


def _contains_phrase(longer: str, shorter: str) -> bool:
    """Whole-word containment, so "java" is not found inside "javascript"."""
    return re.search(rf"(?<![\w+#]){re.escape(shorter)}(?![\w+#])", longer) is not None


def _exact(req_norm: str, cand_norm: str) -> bool:
    # normalize_skill already applies aliases, so equality covers both the
    # exact-normalized and the alias case.
    return bool(req_norm) and req_norm == cand_norm


def _contained(req_norm: str, cand_norm: str) -> bool:
    if not req_norm or not cand_norm:
        return False
    if min(len(req_norm), len(cand_norm)) < MIN_CONTAINMENT_LEN:
        return False
    return _contains_phrase(cand_norm, req_norm) or _contains_phrase(req_norm, cand_norm)


def score_skills(candidate_skills, job_requirements) -> dict:
    """Return {score, matched, missing, extra, match_details}."""
    candidates = _candidate_list(candidate_skills)
    required = parse_requirements(job_requirements)
    cand_norm = [(c, normalize_skill(c)) for c in candidates]

    if not required:
        return {"score": 0.0, "matched": [], "missing": [],
                "extra": sorted(set(candidates)), "match_details": {}}

    matched, missing, details = [], [], {}
    for req in required:
        req_n = normalize_skill(req)
        hit = next((c for c, n in cand_norm if _exact(req_n, n)), None)
        if hit is None:
            hit = next((c for c, n in cand_norm if _contained(req_n, n)), None)
        if hit is None:
            missing.append(req)
        else:
            matched.append(req)
            details[req] = hit

    used = set(details.values())
    extra = sorted({c for c in candidates if c not in used})
    score = round(len(matched) / len(required) * 100, 1)
    return {"score": score, "matched": matched, "missing": missing,
            "extra": extra, "match_details": details}
