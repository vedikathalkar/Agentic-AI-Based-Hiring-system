"""
Bias/Fairness Agent.

Checks candidate/job/evaluation data for explicitly present sensitive or
non-job-relevant information and, separately, checks whether an evaluation
appears to use such information as a hiring decision factor.

IMPORTANT:
- Presence of a sensitive attribute is NOT proof of biased scoring.
- This agent never changes, reduces, or increases a candidate score.
- It never infers protected attributes from names, locations, photos, or
  other indirect clues.
- It uses deterministic pattern checks so no LLM/API call is required.
- The returned structure is suitable for later use as a LangGraph node.
"""

from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List


# Explicit textual indicators only. We deliberately do not include names,
# locations, surnames, or other proxies that could cause sensitive attributes
# to be inferred.
_SENSITIVE_PATTERNS: Dict[str, tuple[str, ...]] = {
    "age": (
        r"\b(?:age|aged)\s*[:\-]?\s*\d{1,3}\b",
        r"\b\d{1,3}\s*(?:years?\s*old|yrs?\s*old)\b",
        r"\b(?:date\s+of\s+birth|dob)\s*[:\-]?",
    ),
    "gender": (
        r"\b(?:gender|sex)\s*[:\-]?\s*(?:male|female|man|woman|non[- ]?binary|transgender|trans|other)\b",
        r"\b(?:male|female|non[- ]?binary|transgender)\b",
    ),
    "religion": (
        r"\b(?:religion|faith)\s*[:\-]?\s*[A-Za-z][A-Za-z -]{1,30}\b",
        r"\b(?:hindu|muslim|christian|sikh|buddhist|jain|jewish)\b",
    ),
    "caste": (
        r"\b(?:caste|community)\s*[:\-]?\s*[A-Za-z][A-Za-z -]{1,40}\b",
        r"\b(?:sc|st|obc|scheduled caste|scheduled tribe)\b",
    ),
    "race_ethnicity": (
        r"\b(?:race|ethnicity|ethnic\s+group)\s*[:\-]?\s*[A-Za-z][A-Za-z -]{1,40}\b",
    ),
    "marital_family_status": (
        r"\b(?:marital|marriage|married|single|divorced|widowed)\b",
        r"\b(?:spouse|husband|wife|children|child|mother|father|family|pregnan(?:t|cy))\b",
    ),
    "disability_medical": (
        r"\b(?:disability|disabled|medical\s+condition|medical\s+history|diagnosis|illness|pregnan(?:t|cy))\b",
    ),
    "political_affiliation": (
        r"\b(?:political\s+party|political\s+affiliation|party\s+membership|member\s+of\s+the\s+party)\b",
    ),
    "nationality": (
        r"\b(?:nationality|citizenship)\s*[:\-]?\s*[A-Za-z][A-Za-z -]{1,40}\b",
    ),
    "photo": (
        r"\b(?:photograph|photo|headshot|profile\s+picture|passport\s+photo)\b",
    ),
}

# Phrases that indicate a sensitive factor is being used in a hiring
# judgement. We inspect evaluation/explanation text only for these patterns.
_BIAS_INFLUENCE_PATTERNS: Dict[str, tuple[str, ...]] = {
    "age": (
        r"\b(?:because|due\s+to|based\s+on|considering|given)\b[^.]{0,100}\b(?:age|young|old)\b",
        r"\b(?:age|young|old)\b[^.]{0,100}\b(?:score|suitable|fit|reject|hire|select|experience)\b",
    ),
    "gender": (
        r"\b(?:because|due\s+to|based\s+on|considering|given)\b[^.]{0,100}\b(?:gender|male|female|woman|man)\b",
        r"\b(?:gender|male|female|woman|man)\b[^.]{0,100}\b(?:score|suitable|fit|reject|hire|select)\b",
    ),
    "religion": (
        r"\b(?:because|due\s+to|based\s+on|considering|given)\b[^.]{0,100}\b(?:religion|faith|hindu|muslim|christian|sikh|jain|buddhist|jewish)\b",
        r"\b(?:religion|faith)\b[^.]{0,100}\b(?:score|suitable|fit|reject|hire|select)\b",
    ),
    "caste": (
        r"\b(?:because|due\s+to|based\s+on|considering|given)\b[^.]{0,100}\b(?:caste|community|sc|st|obc)\b",
        r"\b(?:caste|community)\b[^.]{0,100}\b(?:score|suitable|fit|reject|hire|select)\b",
    ),
    "race_ethnicity": (
        r"\b(?:race|ethnicity|ethnic\s+group)\b[^.]{0,100}\b(?:score|suitable|fit|reject|hire|select|because|due)\b",
    ),
    "marital_family_status": (
        r"\b(?:because|due\s+to|based\s+on|considering|given)\b[^.]{0,100}\b(?:married|marital|spouse|husband|wife|children|family|pregnan)\b",
        r"\b(?:married|marital|spouse|husband|wife|children|family|pregnan)\b[^.]{0,100}\b(?:score|suitable|fit|reject|hire|select)\b",
    ),
    "disability_medical": (
        r"\b(?:because|due\s+to|based\s+on|considering|given)\b[^.]{0,100}\b(?:disability|disabled|medical|diagnosis|illness|pregnan)\b",
        r"\b(?:disability|disabled|medical|diagnosis|illness|pregnan)\b[^.]{0,100}\b(?:score|suitable|fit|reject|hire|select)\b",
    ),
    "political_affiliation": (
        r"\b(?:political\s+party|political\s+affiliation|party\s+membership)\b[^.]{0,100}\b(?:score|suitable|fit|reject|hire|select|because|due)\b",
    ),
    "nationality": (
        r"\b(?:nationality|citizenship)\b[^.]{0,100}\b(?:score|suitable|fit|reject|hire|select|because|due)\b",
    ),
}


def _flatten_text(value: Any) -> str:
    """Convert nested candidate/job/evaluation data into searchable text."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return " ".join(_flatten_text(v) for v in value.values())
    if isinstance(value, (list, tuple, set)):
        return " ".join(_flatten_text(v) for v in value)
    return str(value)


def _search_patterns(text: str, patterns: Iterable[str]) -> bool:
    return any(re.search(pattern, text, flags=re.IGNORECASE) for pattern in patterns)


def _detect_sensitive(text: str) -> List[str]:
    return sorted(
        factor
        for factor, patterns in _SENSITIVE_PATTERNS.items()
        if _search_patterns(text, patterns)
    )


def _detect_influencing_factors(text: str) -> List[str]:
    return sorted(
        factor
        for factor, patterns in _BIAS_INFLUENCE_PATTERNS.items()
        if _search_patterns(text, patterns)
    )


def _job_relevant_fields() -> List[str]:
    return [
        "skills",
        "experience",
        "education",
        "assessment",
        "certifications",
        "job-related qualifications",
    ]


def check_bias(
    candidate_data: Dict[str, Any] | None,
    job_data: Dict[str, Any] | None = None,
    evaluation_data: Dict[str, Any] | None = None,
) -> dict:
    """
    Check candidate/evaluation data for fairness concerns.

    Sensitive attributes are detected only when explicitly present in the
    supplied data. No sensitive attribute is inferred from a name, location,
    photograph, or other proxy.

    Returns a structured result and NEVER modifies evaluation scores.
    """
    candidate_data = candidate_data or {}
    job_data = job_data or {}
    evaluation_data = evaluation_data or {}

    candidate_text = _flatten_text(candidate_data)
    evaluation_text = _flatten_text(evaluation_data)

    flagged_factors = _detect_sensitive(candidate_text)
    influencing_factors = _detect_influencing_factors(evaluation_text)

    # Information present in the candidate data is potentially non-job-relevant
    # unless the project explicitly establishes a lawful job-related reason.
    non_job_relevant = list(flagged_factors)
    score_influenced = bool(influencing_factors)

    evidence: List[str] = []
    if flagged_factors:
        labels = ", ".join(flagged_factors)
        evidence.append(f"Potentially sensitive information detected: {labels}.")
    else:
        evidence.append("No explicitly stated sensitive attributes were detected in the supplied candidate data.")

    if influencing_factors:
        labels = ", ".join(influencing_factors)
        evidence.append(
            f"The evaluation text appears to use potentially sensitive factor(s) as decision criteria: {labels}."
        )
    else:
        evidence.append(
            "No evidence was found in the supplied evaluation text that sensitive attributes influenced the score or decision."
        )

    if score_influenced:
        fairness_status = "flag"
        recommendation = "Review the evaluation and remove sensitive/non-job-relevant factors from decision making."
    elif flagged_factors:
        fairness_status = "review"
        recommendation = "Use job-relevant qualifications only; sensitive information should not affect scoring."
    else:
        fairness_status = "pass"
        recommendation = "Proceed using job-relevant qualifications."

    # Keep a clear audit trail without returning raw sensitive values.
    if score_influenced:
        evidence.append("No score penalty was applied by the Bias Agent; it only flags the evaluation for review.")

    return {
        "bias_detected": bool(flagged_factors or score_influenced),
        "fairness_status": fairness_status,
        "flagged_factors": flagged_factors,
        "non_job_relevant_information": non_job_relevant,
        "score_influenced_by_bias": score_influenced,
        "influencing_factors": influencing_factors,
        "job_relevant_factors": _job_relevant_fields(),
        "recommendation": recommendation,
        "evidence": evidence,
    }
