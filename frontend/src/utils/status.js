// Single mapping for the backend's application status vocabulary.
const STATUS = {
  submitted: { text: 'Submitted', cls: 'pill-neutral' },
  parsed: { text: 'Resume parsed', cls: 'pill-neutral' },
  in_review: { text: 'Screened', cls: 'pill-brand' },
  assessed: { text: 'Assessed', cls: 'pill-ok' },
  shortlisted: { text: 'Shortlisted', cls: 'pill-ok' },
  scheduled: { text: 'Interview scheduled', cls: 'pill-ok' },
  interviewed: { text: 'Interviewed', cls: 'pill-ok' },
  selected: { text: 'Selected', cls: 'pill-ok' },
  offered: { text: 'Offer sent', cls: 'pill-brand' },
  hired: { text: 'Hired', cls: 'pill-ok' },
  offer_declined: { text: 'Offer declined', cls: 'pill-danger' },
  rejected: { text: 'Rejected', cls: 'pill-danger' },
};

export const HR_DECIDED = ['shortlisted', 'scheduled', 'interviewed', 'selected', 'offered', 'hired', 'offer_declined', 'rejected'];

export const OFFER_STATUS = {
  draft: { text: 'Draft', cls: 'pill-neutral' }, sent: { text: 'Sent', cls: 'pill-brand' },
  viewed: { text: 'Viewed', cls: 'pill-warn' }, accepted: { text: 'Accepted', cls: 'pill-ok' },
  rejected: { text: 'Declined', cls: 'pill-danger' }, expired: { text: 'Expired', cls: 'pill-neutral' },
  withdrawn: { text: 'Withdrawn', cls: 'pill-neutral' },
};

export const INTERVIEW_STATUS = {
  scheduled: { text: 'Scheduled', cls: 'pill-brand' }, confirmed: { text: 'Confirmed', cls: 'pill-ok' },
  rescheduled: { text: 'Rescheduled', cls: 'pill-warn' }, completed: { text: 'Completed', cls: 'pill-ok' },
  cancelled: { text: 'Cancelled', cls: 'pill-danger' },
};

export const VERIFICATION_STATE = {
  profile_incomplete: { text: 'Profile incomplete', cls: 'pill-neutral' },
  verification_required: { text: 'Verification required', cls: 'pill-warn' },
  unverified: { text: 'Verification required', cls: 'pill-warn' },
  pending: { text: 'Verification pending', cls: 'pill-brand' },
  verified: { text: '✓ Verified', cls: 'pill-ok' },
  rejected: { text: 'Verification rejected', cls: 'pill-danger' },
};

export function pill(map, key) {
  return map[key] || { text: key || '—', cls: 'pill-neutral' };
}

export function statusPill(status) {
  return STATUS[status] || { text: status || 'Unknown', cls: 'pill-neutral' };
}

// Combined label used in HR tables, e.g. "Assessment pending".
export function applicationStageLabel(app) {
  if (!app) return statusPill(null);
  const out = app.pipeline?.outcome;
  if (out?.state === 'stopped') return { text: out.by_candidate ? 'Offer declined' : `Stopped at ${String(out.stopped_label || '').toLowerCase()}`, cls: 'pill-danger' };
  if (HR_DECIDED.includes(app.status)) return statusPill(app.status);
  if (app.assessment_status === 'completed' || app.status === 'assessed') return statusPill('assessed');
  if (app.assessment_status === 'in_progress') return { text: 'Assessment in progress', cls: 'pill-warn' };
  if (app.status === 'in_review' || app.status === 'parsed') return { text: 'Assessment pending', cls: 'pill-brand' };
  return statusPill(app.status);
}

export const ASSESSMENT_LABEL = {
  not_started: 'Not started',
  in_progress: 'In progress',
  completed: 'Completed',
};

export function formatDate(value, withTime = false) {
  if (!value) return '—';
  // Backend timestamps are naive UTC.
  const iso = /Z|[+-]\d\d:?\d\d$/.test(value) ? value : `${value}Z`;
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '—';
  const opts = { day: 'numeric', month: 'short', year: 'numeric' };
  if (withTime) Object.assign(opts, { hour: 'numeric', minute: '2-digit' });
  return d.toLocaleString(undefined, opts);
}

export function splitList(value) {
  if (Array.isArray(value)) return value.filter(Boolean);
  return String(value || '').split(',').map((s) => s.trim()).filter((s) => s && s.toLowerCase() !== 'none detected');
}
