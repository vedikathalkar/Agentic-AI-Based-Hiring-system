"""
Experience Agent (Phase 5 — role/relevance-aware version).

Compares a candidate's experience against a job's requirements. This
version adds the ability to reason about experience at the level of
individual roles/entries (title, duration, description), so that total
years and *relevant* years are no longer assumed to be the same thing.

BACKWARD COMPATIBILITY (unchanged from the previous version):
score_experience(candidate_years, min_experience) — the original two
positional arguments — still works exactly as before and returns the
original fields (score, note). All newer parameters, including the new
`experience_entries` list, are optional keyword arguments; when omitted,
this function degrades gracefully through the same fallback chain as
before:
    entries given  -->  blob text + job context given  -->  years only
Each fallback level reduces to exactly the previous version's behavior,
so any existing caller (Skill/Bias Agents, API routes, tests) that only
supplies the old arguments gets identical output to before.

NEW: STRUCTURED, PER-ROLE EXPERIENCE
`experience_entries` is an optional list of dicts, one per role the
Resume Parser extracted, e.g.:
    [{"title": "Software Engineer", "years": 3, "description": "..."},
     {"title": "Product Manager",   "years": 2, "description": "..."}]
Field names are read flexibly (title/role/job_title/position,
years/duration/years_worked, description/text/responsibilities/summary)
since the exact key names emitted by the Resume Parser package weren't
available when this was written — swap the key lists in `_ENTRY_*_KEYS`
below if the parser uses different names. If this parameter isn't
supplied, the agent falls back to its previous blob-text behavior
unchanged.

Each entry is judged independently for relevance to the target job
(by role-title semantic similarity and by responsibility-text semantic
similarity), and only years from entries judged relevant are counted as
"relevant experience." Entries with no title/description at all cannot
be judged, and are reported as such rather than assumed relevant.

WHAT THIS AGENT DOES NOT DO:
- It does not invent experience, dates, organizations, or roles that
  weren't extracted.
- It does not convert projects/education/certifications into work
  experience — that classification is assumed to already be correct by
  the time entries reach this agent (the Resume Parser's job).
- It does not assume a required skill was used just because it appears
  elsewhere in the resume — only skills explicitly present in the
  entry's own description/experience text count as evidence.
- It does not let an LLM invent the final score — every number below is
  a deterministic function of the inputs.
"""

from .semantic_utils import semantic_similarity, model_available

# ---------------------------------------------------------------------
# Tunable constants — grouped here so behavior can be retuned without
# touching logic.
# ---------------------------------------------------------------------

# Legacy blend (no structured entries; blob text + job context only).
# Unchanged from the previous version, so old-style calls score
# identically to before.
YEARS_WEIGHT = 0.70
RELEVANCE_WEIGHT = 0.30

# Blend used when structured `experience_entries` are supplied — more
# granular because we can actually tell relevant years apart from total
# years.
ENTRIES_YEARS_WEIGHT = 0.30
ENTRIES_RELEVANT_YEARS_WEIGHT = 0.30
ENTRIES_ROLE_WEIGHT = 0.20
ENTRIES_RESPONSIBILITY_WEIGHT = 0.20

# A role/entry counts as relevant if its title similarity to the job
# title, OR its description similarity to the job context, clears these
# bars. Kept lower than skill-matching thresholds (semantic_utils'
# skill_agent uses 0.60/0.90) because job titles are short, noisy
# strings ("SWE" vs "Software Engineer") where cosine similarity runs
# lower than for full-sentence comparisons.
ROLE_RELEVANCE_THRESHOLD = 0.50
RESPONSIBILITY_RELEVANCE_THRESHOLD = 0.45

STRONG_THRESHOLD = 75
PARTIAL_THRESHOLD = 40

# Flexible field-name lookup for entries, since the exact Resume Parser
# output schema for structured experience entries wasn't available.
_ENTRY_TITLE_KEYS = ("title", "role", "job_title", "position", "role_title")
_ENTRY_YEARS_KEYS = ("years", "duration_years", "duration", "years_worked", "num_years")
_ENTRY_TEXT_KEYS = ("description", "text", "responsibilities", "summary", "experience_text")


def _years_component(candidate_years: float, min_experience: float) -> tuple[float, str]:
    """Original years-vs-minimum scoring logic, unchanged."""
    if min_experience <= 0:
        score = 100.0 if candidate_years > 0 else 60.0
        note = (
            f"Role has no minimum experience requirement; candidate has {candidate_years} years."
            if candidate_years > 0
            else "Role has no minimum experience requirement; no experience detected on resume."
        )
    elif candidate_years >= min_experience:
        score = 100.0
        note = f"Meets the {min_experience}-year requirement with {candidate_years} years."
    else:
        score = round((candidate_years / min_experience) * 100, 1)
        note = f"Below the {min_experience}-year requirement — candidate has {candidate_years} years."
    return score, note


def _relevant_skill_overlap(candidate_experience_text: str, job_requirements: str) -> list[str]:
    """
    Grounds 'relevant experience' in something actually extracted, rather
    than an LLM guess: which required skills are literally mentioned in
    the candidate's experience narrative. Simple substring check — this
    is a factual presence check, not an inference.
    """
    if not candidate_experience_text or not job_requirements:
        return []
    text_lower = candidate_experience_text.lower()
    required = [s.strip() for s in job_requirements.split(",") if s.strip()]
    return [r for r in required if r.lower() in text_lower]


def _get_field(entry: dict, keys: tuple) -> object:
    """Case-insensitive lookup of the first present key from `keys`."""
    if not isinstance(entry, dict):
        return None
    lower_map = {str(k).lower(): v for k, v in entry.items()}
    for key in keys:
        if key in lower_map and lower_map[key] not in (None, ""):
            return lower_map[key]
    return None


def _entry_years(entry: dict) -> float:
    raw = _get_field(entry, _ENTRY_YEARS_KEYS)
    try:
        return float(raw) if raw is not None else 0.0
    except (TypeError, ValueError):
        return 0.0


def _entry_title(entry: dict) -> str:
    raw = _get_field(entry, _ENTRY_TITLE_KEYS)
    return str(raw).strip() if raw else ""


def _entry_text(entry: dict) -> str:
    raw = _get_field(entry, _ENTRY_TEXT_KEYS)
    return str(raw).strip() if raw else ""


def _evaluate_entry(entry: dict, job_title: str, job_requirements: str, job_description: str) -> dict:
    """
    Judges a single experience entry against the job. Never guesses:
    if there's nothing to compare (no title and no description), the
    entry is marked undetermined rather than counted as relevant.
    """
    title = _entry_title(entry)
    text = _entry_text(entry)
    years = _entry_years(entry)

    role_score = None
    if title and job_title:
        role_score = semantic_similarity(title, job_title)

    job_context = ". ".join(part for part in [job_title, job_requirements, job_description] if part)
    resp_score = None
    if text and job_context:
        resp_score = semantic_similarity(text, job_context)

    skill_evidence = _relevant_skill_overlap(text, job_requirements)

    relevant = False
    reasons = []
    if role_score is not None and role_score >= ROLE_RELEVANCE_THRESHOLD:
        relevant = True
        reasons.append(f"title '{title}' is semantically similar to '{job_title}' ({round(role_score * 100, 1)}%)")
    if resp_score is not None and resp_score >= RESPONSIBILITY_RELEVANCE_THRESHOLD:
        relevant = True
        reasons.append(f"responsibilities align with the job context ({round(resp_score * 100, 1)}%)")
    if skill_evidence:
        relevant = True
        reasons.append(f"explicitly mentions required skill(s): {', '.join(skill_evidence)}")

    undetermined = not title and not text

    return {
        "title": title or "Unspecified role",
        "years": years,
        "relevant": relevant,
        "undetermined": undetermined,
        "role_relevance": role_score,
        "responsibility_relevance": resp_score,
        "skills_evidence": skill_evidence,
        "reasons": reasons,
    }


def _score_from_entries(
    experience_entries: list,
    candidate_years: float,
    job_title: str,
    job_requirements: str,
    job_description: str,
) -> dict:
    """
    Builds relevant-years, relevant-roles, and per-entry evidence out of
    structured experience entries. Returns a dict of intermediate values
    consumed by score_experience(); does not compute the final score.
    """
    breakdown = []
    relevant_years = 0.0
    total_entry_years = 0.0
    relevant_roles = []
    undetermined_entries = 0
    best_role_score = None
    weighted_resp_total = 0.0
    weighted_resp_denom = 0.0
    all_skill_evidence = []

    for raw_entry in experience_entries:
        if not isinstance(raw_entry, dict):
            breakdown.append({"title": "Unrecognized entry (skipped)", "years": 0, "relevant": False,
                               "undetermined": True, "reasons": ["Entry was not a structured object — skipped, not guessed."]})
            continue
        result = _evaluate_entry(raw_entry, job_title, job_requirements, job_description)
        breakdown.append(result)
        total_entry_years += result["years"]

        if result["undetermined"]:
            undetermined_entries += 1
            continue

        if result["role_relevance"] is not None:
            if best_role_score is None or result["role_relevance"] > best_role_score:
                best_role_score = result["role_relevance"]
        if result["responsibility_relevance"] is not None and result["years"] > 0:
            weighted_resp_total += result["responsibility_relevance"] * result["years"]
            weighted_resp_denom += result["years"]

        if result["skills_evidence"]:
            all_skill_evidence.extend(s for s in result["skills_evidence"] if s not in all_skill_evidence)

        if result["relevant"]:
            relevant_years += result["years"]
            if result["title"] not in relevant_roles:
                relevant_roles.append(result["title"])

    relevant_years = round(relevant_years, 2)
    total_entry_years = round(total_entry_years, 2)
    avg_resp_score = round(weighted_resp_total / weighted_resp_denom, 4) if weighted_resp_denom > 0 else None

    # Total candidate years: prefer the explicitly supplied figure (it
    # may come from a different, more authoritative extraction path);
    # otherwise derive it by summing entry years.
    derived_total_used = False
    if not candidate_years:
        candidate_years = total_entry_years
        derived_total_used = True

    return {
        "breakdown": breakdown,
        "relevant_years": relevant_years,
        "total_entry_years": total_entry_years,
        "relevant_roles": relevant_roles,
        "undetermined_entries": undetermined_entries,
        "best_role_score": best_role_score,
        "avg_responsibility_score": avg_resp_score,
        "all_skill_evidence": all_skill_evidence,
        "candidate_years": candidate_years,
        "derived_total_used": derived_total_used,
    }


def score_experience(
    candidate_years: float,
    min_experience: float,
    candidate_experience_text: str = "",
    job_title: str = "",
    job_requirements: str = "",
    job_description: str = "",
    experience_entries: list = None,
) -> dict:
    """
    candidate_years: from Resume Parser's extracted total experience_years.
        Optional when `experience_entries` is supplied and each entry
        carries its own years — the total is then derived by summation.
    min_experience: from JobRole.min_experience.
    candidate_experience_text: Resume.experience (free-text summary) —
        used only when `experience_entries` is not supplied.
    job_title / job_requirements / job_description: optional job context.
    experience_entries: optional list of dicts describing individual
        roles (see module docstring for accepted field names). When
        provided, this enables per-role relevant-experience, role-title
        relevance, and responsibility relevance. When omitted, behavior
        is identical to the previous (blob-text) version.

    Returns the original fields (score, note) plus structured fields:
    experience_score, required_experience, candidate_experience,
    relevant_experience, relevant_roles, experience_status, evidence,
    semantic_model_available, and (when entries were supplied)
    experience_breakdown.
    """
    candidate_years = candidate_years or 0.0
    min_experience = min_experience or 0.0
    semantic_ready = model_available()

    entries_info = None
    if experience_entries:
        entries_info = _score_from_entries(
            experience_entries, candidate_years, job_title, job_requirements, job_description
        )
        candidate_years = entries_info["candidate_years"]

    years_score, years_note = _years_component(candidate_years, min_experience)
    evidence = [years_note]

    # ------------------------------------------------------------------
    # PATH A: structured entries supplied — granular scoring.
    # ------------------------------------------------------------------
    if entries_info is not None:
        relevant_years = entries_info["relevant_years"]
        relevant_score, relevant_note = _years_component(relevant_years, min_experience)
        if min_experience > 0:
            # Re-word the note so it clearly refers to *relevant* years, not total.
            if relevant_years >= min_experience:
                relevant_note = f"Relevant experience ({relevant_years} years) meets the {min_experience}-year requirement."
            else:
                relevant_note = f"Relevant experience is only {relevant_years} of the required {min_experience} years."
            evidence.append(relevant_note)
        elif relevant_years != candidate_years:
            # No minimum to compare against — only worth a note if relevant
            # years actually differs from total (otherwise it's a repeat
            # of the years_note already added above).
            evidence.append(f"Of the total, {relevant_years} years were judged relevant to the role.")

        if entries_info["derived_total_used"]:
            evidence.append(
                f"Total candidate years derived by summing {len(experience_entries)} experience entr"
                f"{'y' if len(experience_entries) == 1 else 'ies'} ({entries_info['total_entry_years']} years)."
            )

        role_component = None
        if entries_info["best_role_score"] is not None:
            role_component = entries_info["best_role_score"] * 100
            evidence.append(
                f"Best-matching role relevance to '{job_title}': {round(role_component, 1)}%."
            )
        elif job_title and not semantic_ready:
            evidence.append("Semantic model unavailable — role-title relevance was not scored.")

        resp_component = None
        if entries_info["avg_responsibility_score"] is not None:
            resp_component = entries_info["avg_responsibility_score"] * 100
            evidence.append(
                f"Years-weighted responsibility-text relevance to job context: {round(resp_component, 1)}%."
            )

        if entries_info["all_skill_evidence"]:
            evidence.append(
                f"Required skill(s) explicitly found in relevant experience entries: "
                f"{', '.join(entries_info['all_skill_evidence'])}."
            )

        if entries_info["undetermined_entries"]:
            evidence.append(
                f"{entries_info['undetermined_entries']} experience entr"
                f"{'y' if entries_info['undetermined_entries'] == 1 else 'ies'} had no title or description "
                f"and could not be judged for relevance — not counted as relevant, not discarded from total."
            )

        # Deterministic weighted blend. Components that couldn't be
        # computed are dropped and the remaining weights renormalized,
        # so a missing signal never silently drags the score toward 0.
        components = [(ENTRIES_YEARS_WEIGHT, years_score)]
        components.append((ENTRIES_RELEVANT_YEARS_WEIGHT, relevant_score))
        if role_component is not None:
            components.append((ENTRIES_ROLE_WEIGHT, role_component))
        if resp_component is not None:
            components.append((ENTRIES_RESPONSIBILITY_WEIGHT, resp_component))

        weight_sum = sum(w for w, _ in components)
        final_score = round(sum(w * s for w, s in components) / weight_sum, 1) if weight_sum else years_score

        if entries_info["total_entry_years"] > 0:
            relevant_experience = (
                f"~{relevant_years} of {entries_info['total_entry_years']} total years are relevant"
                + (f" ({', '.join(entries_info['relevant_roles'])})." if entries_info["relevant_roles"] else
                   " — no individual role cleared the relevance bar.")
            )
        else:
            relevant_experience = "No years-bearing experience entries were supplied to assess relevance."

        result_extra = {"experience_breakdown": entries_info["breakdown"]}
        relevant_roles_out = entries_info["relevant_roles"]

    # ------------------------------------------------------------------
    # PATH B: no structured entries — previous (blob-text) behavior,
    # unchanged so existing callers get identical output.
    # ------------------------------------------------------------------
    else:
        relevance_score = None  # None = not computed, distinct from 0.0
        job_context = ". ".join(part for part in [job_title, job_requirements, job_description] if part)

        if candidate_experience_text and job_context:
            relevance_score = semantic_similarity(candidate_experience_text, job_context)
            if relevance_score is not None:
                evidence.append(
                    f"Semantic similarity between candidate experience narrative and "
                    f"job context: {round(relevance_score * 100, 1)}%."
                )
            elif not semantic_ready:
                evidence.append(
                    "Semantic model unavailable — experience narrative was not compared "
                    "against job context; scoring relies on years only."
                )

        if relevance_score is not None:
            final_score = round(YEARS_WEIGHT * years_score + RELEVANCE_WEIGHT * (relevance_score * 100), 1)
        else:
            final_score = years_score  # exact original behavior when no text/context given

        overlap = _relevant_skill_overlap(candidate_experience_text, job_requirements)
        if overlap:
            relevant_years = round(candidate_years * (relevance_score or 1.0), 1) if candidate_years else 0.0
            relevant_experience = (
                f"~{relevant_years} years, with experience text explicitly mentioning: {', '.join(overlap)}."
            )
            evidence.append(f"Experience narrative explicitly mentions required skill(s): {', '.join(overlap)}.")
        elif candidate_experience_text:
            relevant_experience = (
                "No required skills were explicitly found in the candidate's experience "
                "narrative — relevance is based on overall semantic similarity only."
                if relevance_score is not None else
                "No required skills were explicitly found in the candidate's experience narrative."
            )
        else:
            relevant_experience = "No experience narrative available to assess relevance."

        result_extra = {}
        relevant_roles_out = []

    if final_score >= STRONG_THRESHOLD:
        status = "strong"
    elif final_score >= PARTIAL_THRESHOLD:
        status = "partial"
    else:
        status = "weak"

    required_experience = (
        f"{min_experience}+ years" if min_experience > 0 else "No minimum specified"
    )
    if job_requirements:
        required_experience += f" ({job_requirements})"

    result = {
        # original fields — preserved
        "score": years_score,
        "note": years_note,
        # structured fields
        "experience_score": final_score,
        "required_experience": required_experience,
        "candidate_experience": f"{candidate_years} years",
        "relevant_experience": relevant_experience,
        "relevant_roles": relevant_roles_out,
        "experience_status": status,
        "evidence": evidence,
        "semantic_model_available": semantic_ready,
    }
    result.update(result_extra)
    return result
