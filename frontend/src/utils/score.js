// Scores arrive from the API as floats 0-100. null/undefined means
// "not calculated"; 0 is a real score and must be shown as 0%.
const isMissing = (v) => v === null || v === undefined || v === '' || Number.isNaN(Number(v));

export function formatScore(v) {
  return isMissing(v) ? '—' : `${Math.round(Number(v))}%`;
}

export function scoreTone(v) {
  if (isMissing(v)) return 'neutral';
  const n = Number(v);
  if (n >= 80) return 'ok';
  if (n >= 50) return 'warn';
  return 'danger';
}

export function hasScore(v) {
  return !isMissing(v);
}

// Sort helper: real scores (including 0) descending, unscored last.
export function compareScoresDesc(a, b) {
  const am = isMissing(a);
  const bm = isMissing(b);
  if (am !== bm) return am ? 1 : -1;
  if (am) return 0;
  return Number(b) - Number(a);
}
