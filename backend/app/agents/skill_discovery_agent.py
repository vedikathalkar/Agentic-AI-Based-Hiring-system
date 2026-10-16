"""
Skill Discovery Agent

Uses Groq only for ambiguous skill candidates that the local
Resume Parsing Agent could not confidently classify.

Defensive features:
- cleans obvious extraction artifacts before LLM calls
- uses Groq Chat API
- robust JSON parsing
- validates LLM classifications
- never crashes the Resume Parsing Agent
- preserves existing output keys
"""

import json
import os
import re

from groq import Groq


MODEL_NAME = "openai/gpt-oss-120b"
MIN_CONFIDENCE = 0.70
MAX_CANDIDATES = 40


def _get_client():
    api_key = os.getenv("GROQ_API_KEY")

    if not api_key:
        return None

    try:
        return Groq(api_key=api_key)
    except Exception:
        return None


def _unique(items):
    result = []
    seen = set()

    for item in items or []:
        item = str(item).strip()

        if not item:
            continue

        key = item.lower()

        if key not in seen:
            seen.add(key)
            result.append(item)

    return result


def _clean_candidate(candidate):
    candidate = str(candidate or "").strip()

    candidate = re.sub(
        r"^[\s\-•*◦▪●○➜➤→|]+",
        "",
        candidate
    )

    candidate = re.sub(r"\s+", " ", candidate)

    return candidate.strip(" \t.,;:|")


def _clean_candidates(candidates):
    header_words = {
        "tech",
        "technical",
        "technical skills",
        "tech skills",
        "soft",
        "soft skills",
        "hard skills",
        "skills",
        "skill",
        "core skills",
    }

    contact_words = {
        "phone",
        "mobile",
        "mobile number",
        "email",
        "email id",
        "e-mail",
        "address",
        "location",
        "linkedin",
        "linkedin profile",
        "github profile",
        "portfolio",
        "website",
        "contact",
        "contact number",
    }

    cleaned = []

    for candidate in candidates or []:

        candidate = _clean_candidate(candidate)
        lower = candidate.lower()

        if not candidate:
            continue

        if lower in header_words:
            continue

        if lower in contact_words:
            continue

        if len(candidate) > 80:
            continue

        if re.fullmatch(r"[\d\s./_\-–—]+", candidate):
            continue

        cleaned.append(candidate)

    return _unique(cleaned)[:MAX_CANDIDATES]


def _strip_code_fences(text):
    text = str(text or "").strip()

    if not text:
        return ""

    text = re.sub(
        r"^\s*```(?:json)?\s*",
        "",
        text,
        flags=re.IGNORECASE
    )

    text = re.sub(
        r"\s*```\s*$",
        "",
        text
    )

    return text.strip()


def _extract_json_object(text):
    cleaned = _strip_code_fences(text)

    if not cleaned:
        raise ValueError("Groq returned an empty response.")

    try:
        return json.loads(cleaned)

    except json.JSONDecodeError:
        pass

    start = cleaned.find("{")
    end = cleaned.rfind("}")

    if start == -1 or end <= start:
        raise ValueError(
            "Groq response did not contain a JSON object."
        )

    try:
        return json.loads(
            cleaned[start:end + 1]
        )

    except json.JSONDecodeError as exc:
        raise ValueError(
            f"Groq returned invalid JSON: {exc}"
        ) from exc


def _empty_result(error=None):

    result = {
        "technical_skills": [],
        "soft_skills": [],
        "rejected_skills": [],
        "details": [],
    }

    if error:
        result["error"] = str(error)

    return result


def _normalise_type(value):

    value = str(value or "").strip().lower()

    aliases = {
        "tech": "technical",
        "technical skill": "technical",
        "technical_skills": "technical",
        "soft skill": "soft",
        "soft_skills": "soft",
        "invalid skill": "invalid",
        "reject": "invalid",
        "rejected": "invalid",
    }

    return aliases.get(value, value)


def discover_skills(review_required_skills):
    """
    Classify ambiguous candidates into technical, soft, or invalid.

    Existing Resume Parser compatibility is preserved:

      technical_skills
      soft_skills
      rejected_skills
      details
      error
    """

    candidates = _clean_candidates(
        review_required_skills
    )

    if not candidates:
        return _empty_result()

    client = _get_client()

    if client is None:
        return _empty_result(
            "GROQ_API_KEY is not configured. "
            "Ambiguous skills were not sent to the LLM."
        )

    prompt = f"""
You are the Skill Discovery Agent in an automated recruitment system.

Your task is to classify EACH candidate below.

For every candidate:

- type must be exactly "technical", "soft", or "invalid"
- normalize the skill name only when normalization is obvious
- confidence must be between 0.0 and 1.0
- give a short reason
- do not invent information

TECHNICAL SKILLS include:

- programming languages
- frameworks
- libraries
- databases
- cloud platforms
- AI/ML technologies
- developer tools
- software technologies
- technical methodologies

Examples:

Python
Java
C++
SQL
FastAPI
React
TensorFlow
AWS
Docker
Git
REST APIs

SOFT SKILLS include:

- communication
- leadership
- teamwork
- collaboration
- problem solving
- adaptability
- analytical thinking
- time management
- attention to detail
- decision making
- similar workplace abilities

INVALID includes:

- company names
- college names
- university names
- organizations
- locations
- people's names
- project names
- section headings
- dates
- contact information
- generic resume words
- anything that is not a genuine skill

IMPORTANT RULES:

1. Classify EVERY supplied candidate exactly once.

2. Do NOT invent a skill.

3. Do NOT turn a company name into a skill.

4. Do NOT turn a project name into a skill.

5. Do NOT turn a location into a skill.

6. Do NOT turn a degree or university into a skill.

7. Preserve genuine short technical names such as:
   C
   R
   AI
   ML
   SQL
   AWS
   Git

8. "Loan Default Prediction" is a project name, not a skill.

9. "Mumbai", "Pune", "Bengaluru", etc. are locations, not skills.

10. Normalize only when the meaning is obvious.

11. If uncertain, classify as "invalid" rather than inventing a classification.

12. Return JSON only.

Candidates:
{json.dumps(candidates, ensure_ascii=False)}

Return exactly this JSON structure:

{{
  "results": [
    {{
      "original": "candidate exactly as supplied",
      "normalized": "normalized skill name",
      "type": "technical",
      "confidence": 0.95,
      "reason": "short explanation"
    }}
  ]
}}
"""

    try:

        response = client.chat.completions.create(
            model=MODEL_NAME,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a precise Skill Discovery Agent. "
                        "Classify supplied resume skill candidates. "
                        "Return valid JSON only. "
                        "Never invent information."
                    ),
                },
                {
                    "role": "user",
                    "content": prompt,
                },
            ],
            temperature=0,
            response_format={
                "type": "json_object"
            },
        )

        raw = (
            response
            .choices[0]
            .message
            .content
            or ""
        ).strip()

        data = _extract_json_object(raw)

        if not isinstance(data, dict):
            raise ValueError(
                "Groq JSON response is not an object."
            )

        results = data.get("results")

        if not isinstance(results, list):
            raise ValueError(
                "Groq JSON response is missing "
                "a valid 'results' list."
            )

        technical = []
        soft = []
        rejected = []
        details = []

        supplied_by_key = {
            c.lower(): c
            for c in candidates
        }

        classified_keys = set()

        for item in results:

            if not isinstance(item, dict):
                continue

            original = str(
                item.get("original", "")
            ).strip()

            if not original:
                continue

            original_clean = _clean_candidate(
                original
            )

            original_key = (
                original_clean.lower()
            )

            # Ignore hallucinated candidates that
            # were not supplied to the LLM.
            if original_key not in supplied_by_key:
                continue

            original = supplied_by_key[
                original_key
            ]

            normalized = str(
                item.get("normalized", "")
            ).strip()

            if not normalized:
                normalized = original

            skill_type = _normalise_type(
                item.get("type", "")
            )

            try:
                confidence = float(
                    item.get(
                        "confidence",
                        0.0
                    )
                )

            except (TypeError, ValueError):
                confidence = 0.0

            confidence = max(
                0.0,
                min(1.0, confidence)
            )

            reason = str(
                item.get("reason", "")
            ).strip()

            if skill_type not in {
                "technical",
                "soft",
                "invalid",
            }:

                skill_type = "invalid"

                reason = (
                    reason
                    or
                    "Unknown classification returned by LLM."
                )

            details.append(
                {
                    "original": original,
                    "normalized": normalized,
                    "type": skill_type,
                    "confidence": confidence,
                    "reason": reason,
                }
            )

            classified_keys.add(
                original_key
            )

            if (
                skill_type == "technical"
                and confidence >= MIN_CONFIDENCE
            ):
                technical.append(
                    normalized
                )

            elif (
                skill_type == "soft"
                and confidence >= MIN_CONFIDENCE
            ):
                soft.append(
                    normalized
                )

            elif (
                skill_type == "invalid"
                and confidence >= MIN_CONFIDENCE
            ):
                rejected.append(
                    original
                )

        unresolved = [
            supplied_by_key[key]
            for key in supplied_by_key
            if key not in classified_keys
        ]

        low_confidence = [
            d["original"]
            for d in details
            if d["confidence"] < MIN_CONFIDENCE
        ]

        # Do not silently lose candidates.
        if unresolved or low_confidence:

            messages = []

            if unresolved:
                messages.append(
                    "Unclassified candidates: "
                    + ", ".join(unresolved)
                    + "."
                )

            if low_confidence:
                messages.append(
                    "Low-confidence candidates: "
                    + ", ".join(
                        _unique(low_confidence)
                    )
                    + "."
                )

            return {
                "technical_skills": _unique(
                    technical
                ),
                "soft_skills": _unique(
                    soft
                ),
                "rejected_skills": _unique(
                    rejected
                ),
                "details": details,
                "error": (
                    "Groq returned an "
                    "incomplete/low-confidence "
                    "classification. "
                    + " ".join(messages)
                ),
            }

        return {
            "technical_skills": _unique(
                technical
            ),
            "soft_skills": _unique(
                soft
            ),
            "rejected_skills": _unique(
                rejected
            ),
            "details": details,
        }

    except Exception as exc:

        return _empty_result(
            f"Skill Discovery Agent failed: "
            f"{type(exc).__name__}: {exc}"
        )