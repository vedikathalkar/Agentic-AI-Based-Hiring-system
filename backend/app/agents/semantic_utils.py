"""
Lightweight semantic-similarity helper.

`experience_agent.py` (the already-tested Phase 5 version supplied for this
integration) imports `semantic_similarity` and `model_available` from this
module. It did not exist anywhere in this project yet, so this file is the
minimal addition needed to make that agent importable and runnable -- per
integration Rule #3 ("only adapt imports/function calls if required"), NOT
a rewrite of the agent's own scoring logic, which lives entirely in
experience_agent.py and is untouched here.

Contract expected by the caller (see experience_agent.py): `model_available()`
is the authoritative "is real semantic scoring available" flag, and
`semantic_similarity()` returns None whenever it isn't -- the caller already
has its own graceful fallback ("Semantic model unavailable -- scoring relies
on years only.") for exactly that case, so this module must not paper over
a missing model with a look-alike numeric score.
"""

from __future__ import annotations

_model = None
_load_attempted = False


def _get_model():
    """Lazily load a sentence-transformers model exactly once. Any failure
    (package not installed, no internet to fetch weights, etc.) leaves
    `_model` as None permanently for this process."""
    global _model, _load_attempted
    if _load_attempted:
        return _model
    _load_attempted = True
    try:
        from sentence_transformers import SentenceTransformer  # type: ignore

        _model = SentenceTransformer("all-MiniLM-L6-v2")
    except Exception:
        _model = None
    return _model


def model_available() -> bool:
    """True only when a real sentence-embedding model loaded successfully."""
    return _get_model() is not None


def semantic_similarity(text_a: str, text_b: str) -> float | None:
    """Cosine similarity in [0, 1] between two texts, computed with a real
    sentence-embedding model. Returns None when either text is empty OR
    when no model is available -- callers must treat None as "not scored",
    never as zero similarity."""
    if not text_a or not text_b:
        return None

    model = _get_model()
    if model is None:
        return None

    try:
        import numpy as np

        embeddings = model.encode([text_a, text_b])
        vec_a, vec_b = embeddings[0], embeddings[1]
        denom = (np.linalg.norm(vec_a) * np.linalg.norm(vec_b)) or 1e-8
        score = float(np.dot(vec_a, vec_b) / denom)
        return max(0.0, min(1.0, score))
    except Exception:
        return None
