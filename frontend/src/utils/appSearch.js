// Natural-language search over a candidate's own applications. It is rule-based (like the job search on the
// server): it pulls structured meaning out of the sentence — outcome, stage, assessment state, score floor,
// recency — and treats whatever words are left as a title/company match.
// "rejected data roles", "pending assessments", "interview stage this month", "score above 70".

const RULES = [
  { key: 'stopped', label: 'Process stopped', re: /\b(rejected|rejections?|not selected|declined|stopped|turned down|unsuccessful)\b/i },
  { key: 'hired', label: 'Hired', re: /\b(hired|joined|accepted)\b/i },
  { key: 'offer', label: 'Offer stage', re: /\b(offers?|offered)\b/i },
  { key: 'interview', label: 'Interview stage', re: /\b(interviews?|interviewing|scheduled|shortlisted)\b/i },
  { key: 'assess_pending', label: 'Assessment pending', re: /\b(pending assessments?|assessments? pending|assessments? to do|not taken|todo|to do|yet to take)\b/i },
  { key: 'assess_done', label: 'Assessment completed', re: /\b(completed assessments?|assessments? (?:completed|done)|assessed|taken)\b/i },
  { key: 'screening', label: 'Being screened', re: /\b(screening|screened|under review|evaluation|evaluating)\b/i },
  { key: 'active', label: 'Still in progress', re: /\b(in progress|ongoing|active|still open|open)\b/i },
];
const SCORE = /\b(?:(?:score|scored|test|match)\s*)?(?:above|over|>=?|at least|more than|min(?:imum)?)\s*(\d{1,3})\s*%?/i;
const WHEN = [
  { key: 7, label: 'Last 7 days', re: /\b(this week|last 7 days|past week)\b/i },
  { key: 30, label: 'Last 30 days', re: /\b(this month|last 30 days|past month|last month)\b/i },
  { key: 1, label: 'Today', re: /\b(today)\b/i },
];
const FILLER = new Set(['my', 'me', 'show', 'find', 'all', 'the', 'that', 'are', 'is', 'for', 'in', 'at', 'of', 'a', 'an', 'and', 'with', 'applications', 'application', 'applied', 'jobs', 'job', 'roles', 'role', 'stage', 'status', 'which', 'what', 'where', 'have', 'i', 'being', 'still', 'currently', 'now', 'under']);

export function parseApplicationQuery(text) {
  let rest = ` ${text || ''} `;
  const chips = [];
  const f = { outcomes: new Set(), minScore: null, withinDays: null, words: [] };
  const take = (re, build) => {
    const m = rest.match(re);
    if (!m) return false;
    chips.push(build(m)); rest = rest.replace(m[0], ' ');
    return true;
  };
  for (const r of RULES) take(r.re, (m) => { f.outcomes.add(r.key); return { kind: 'status', label: r.label, source: m[0].trim() }; });
  take(SCORE, (m) => { f.minScore = Math.min(100, Number(m[1])); return { kind: 'min_score', label: `≥ ${f.minScore}%`, source: m[0].trim() }; });
  for (const w of WHEN) if (take(w.re, (m) => { f.withinDays = w.key; return { kind: 'keyword', label: w.label, source: m[0].trim() }; })) break;
  f.words = (rest.toLowerCase().match(/[a-z0-9+#.]+/g) || []).filter((w) => w.length > 1 && !FILLER.has(w));
  return { filters: f, understood: chips };
}

const outcomeOf = (a) => {
  const o = a.pipeline?.outcome;
  const cur = o?.current;
  return {
    stopped: o?.state === 'stopped',
    hired: o?.state === 'completed' || a.status === 'hired',
    offer: cur === 'offer' && o?.state === 'in_progress',
    interview: (cur === 'interview' && o?.state === 'in_progress') || ['shortlisted', 'scheduled', 'interviewed', 'selected'].includes(a.status),
    assess_pending: o?.state !== 'stopped' && a.assessment_status !== 'completed',
    assess_done: a.assessment_status === 'completed',
    screening: o?.state === 'in_progress' && (cur === 'skill' || cur === 'experience'),
    active: o?.state === 'in_progress',
  };
};

export function matchApplications(apps, filters, extra = {}) {
  const now = Date.now();
  return apps.filter((a) => {
    const o = outcomeOf(a);
    for (const k of filters.outcomes) if (!o[k]) return false;
    if (extra.stage === 'stopped' && !o.stopped) return false;
    if (extra.stage === 'active' && !o.active) return false;
    if (extra.stage === 'interview' && !o.interview) return false;
    if (extra.stage === 'offer' && !(o.offer || o.hired)) return false;
    if (extra.assessment === 'pending' && !o.assess_pending) return false;
    if (extra.assessment === 'completed' && !o.assess_done) return false;
    if (filters.minScore != null) {
      const best = Math.max(a.final_score ?? -1, a.test_score ?? -1, a.skill_score ?? -1);
      if (best < filters.minScore) return false;
    }
    if (filters.withinDays != null && a.applied_at) {
      const t = new Date(/Z|[+-]\d\d:?\d\d$/.test(a.applied_at) ? a.applied_at : `${a.applied_at}Z`).getTime();
      if (now - t > filters.withinDays * 86400000) return false;
    }
    if (filters.words.length) {
      const hay = `${a.job_title || ''} ${a.company_name || ''}`.toLowerCase();
      if (!filters.words.every((w) => hay.includes(w))) return false;
    }
    return true;
  });
}
