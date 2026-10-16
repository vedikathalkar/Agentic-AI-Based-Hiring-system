def pct(value) -> str:
    """Email/PDF display only — the API always returns raw floats (None = not calculated)."""
    if value is None:
        return "—"
    try:
        return f"{round(float(value))}%"
    except (TypeError, ValueError):
        return "—"
