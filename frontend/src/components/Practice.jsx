import { useEffect, useMemo, useRef, useState } from 'react';
import { X } from 'lucide-react';

/** Segmented control (radio group styled as pills). */
export function Segmented({ label, value, onChange, options, id }) {
  return (
    <div className="field">
      <span className="field-label" id={`${id}-l`}>{label}</span>
      <div className="seg" role="radiogroup" aria-labelledby={`${id}-l`}>
        {options.map(([v, text, hint]) => (
          <button key={v} type="button" role="radio" aria-checked={value === v} className={value === v ? 'on' : ''} onClick={() => onChange(v)} title={hint}>
            {text}
          </button>
        ))}
      </div>
    </div>
  );
}

/** Pick an open job (applied ones first) or type a custom role + skills. */
export function RolePicker({ roles, value, onChange }) {
  const [draft, setDraft] = useState('');
  const jobs = roles?.jobs || [];
  const set = (patch) => onChange({ ...value, ...patch });
  const pickJob = (e) => {
    const id = e.target.value;
    if (!id) { set({ job_id: null }); return; }
    const j = jobs.find((x) => String(x.job_id) === id);
    set({ job_id: j.job_id, role_title: j.title, skills: j.skills.slice(0, 8) });
  };
  const addSkill = () => {
    const parts = draft.split(/[,;]/).map((s) => s.trim()).filter(Boolean);
    if (parts.length) set({ skills: [...new Set([...(value.skills || []), ...parts])].slice(0, 12) });
    setDraft('');
  };
  const mine = (roles?.my_skills || []).filter((s) => !(value.skills || []).some((x) => x.toLowerCase() === s.toLowerCase())).slice(0, 8);
  return (
    <div className="role-picker">
      <div className="form-grid">
        <div className="field">
          <label className="field-label" htmlFor="rp-job">Role from a job</label>
          <select id="rp-job" className="input" value={value.job_id || ''} onChange={pickJob}>
            <option value="">— Custom role —</option>
            {jobs.some((j) => j.applied) && <optgroup label="Jobs you applied to">{jobs.filter((j) => j.applied).map((j) => <option key={j.job_id} value={j.job_id}>{j.title}</option>)}</optgroup>}
            <optgroup label="Open jobs">{jobs.filter((j) => !j.applied).map((j) => <option key={j.job_id} value={j.job_id}>{j.title}</option>)}</optgroup>
          </select>
        </div>
        <div className="field">
          <label className="field-label" htmlFor="rp-title">Role you're preparing for</label>
          <input id="rp-title" className="input" placeholder="e.g. Data Analyst" value={value.role_title || ''} disabled={!!value.job_id}
                 onChange={(e) => set({ role_title: e.target.value })} />
        </div>
      </div>
      <div className="field">
        <label className="field-label" htmlFor="rp-skill">Skills to practise <span className="muted small">({(value.skills || []).length}/12)</span></label>
        <div className="tag-input">
          {(value.skills || []).map((s) => (
            <span key={s} className="chip chip-req">{s}<button type="button" className="chip-x" aria-label={`Remove ${s}`} onClick={() => set({ skills: value.skills.filter((x) => x !== s) })}><X size={12} /></button></span>
          ))}
          <input id="rp-skill" value={draft} placeholder={(value.skills || []).length ? 'Add another…' : 'Type a skill and press Enter'}
                 onChange={(e) => setDraft(e.target.value)} onBlur={addSkill}
                 onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ',') { e.preventDefault(); addSkill(); } }} />
        </div>
        {mine.length > 0 && (
          <div className="chips" style={{ marginTop: 8 }}>
            <span className="small muted">From your profile:</span>
            {mine.map((s) => <button key={s} type="button" className="chip" onClick={() => set({ skills: [...(value.skills || []), s].slice(0, 12) })}>+ {s}</button>)}
          </div>
        )}
      </div>
    </div>
  );
}

/** Single headline number as a ring (0-100). */
export function ScoreRing({ value, size = 120, label = 'Score' }) {
  const r = (size - 14) / 2;
  const c = 2 * Math.PI * r;
  const v = Math.max(0, Math.min(100, value ?? 0));
  const tone = v >= 75 ? 'var(--a3)' : v >= 50 ? 'var(--gold)' : 'var(--a1)';
  return (
    <div className="score-ring" style={{ width: size, height: size }} role="img" aria-label={`${label}: ${Math.round(v)} out of 100`}>
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} aria-hidden="true">
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="var(--raised)" strokeWidth="10" />
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke={tone} strokeWidth="10" strokeLinecap="round"
                strokeDasharray={c} strokeDashoffset={c * (1 - v / 100)} transform={`rotate(-90 ${size / 2} ${size / 2})`}
                style={{ transition: 'stroke-dashoffset .8s var(--ease, ease-out)' }} />
      </svg>
      <div className="score-ring-text"><b>{Math.round(v)}</b><span>{label}</span></div>
    </div>
  );
}

/** Horizontal bars for a single series (0-100). Values are text in ink, the bar carries magnitude. */
export function ScoreBars({ items, valueKey = 'score', labelKey = 'name' }) {
  return (
    <ul className="score-bars">
      {items.map((it) => {
        const v = Math.round(it[valueKey] ?? 0);
        return (
          <li key={it[labelKey]} title={`${it[labelKey]}: ${v}%`}>
            <span className="score-bars-label">{it[labelKey]}</span>
            <span className="score-bars-track"><span style={{ width: `${Math.max(2, v)}%`, background: v >= 75 ? 'var(--a3)' : v >= 50 ? 'var(--gold)' : 'var(--a1)' }} /></span>
            <b className="score-bars-value">{v}%</b>
          </li>
        );
      })}
    </ul>
  );
}

/** Countdown to a deadline (ms epoch). Calls onExpire once. Shows overrun when allowOverrun. */
export function useCountdown(deadline, onExpire) {
  const [now, setNow] = useState(Date.now());
  const fired = useRef(false);
  useEffect(() => { fired.current = false; }, [deadline]);
  useEffect(() => {
    if (!deadline) return undefined;
    const id = setInterval(() => setNow(Date.now()), 250);
    return () => clearInterval(id);
  }, [deadline]);
  const left = deadline ? Math.ceil((deadline - now) / 1000) : null;
  useEffect(() => {
    if (deadline && left <= 0 && !fired.current) { fired.current = true; onExpire?.(); }
  }, [left, deadline]); // eslint-disable-line react-hooks/exhaustive-deps
  return left;
}

export const fmtClock = (s) => {
  const neg = s < 0; const a = Math.abs(s);
  return `${neg ? '+' : ''}${Math.floor(a / 60)}:${String(a % 60).padStart(2, '0')}`;
};

/** Small ring timer: amber at 25 % left, red at 10 %. */
export function TimerRing({ left, total, size = 64 }) {
  const frac = total ? Math.max(0, Math.min(1, left / total)) : 0;
  const r = (size - 8) / 2; const c = 2 * Math.PI * r;
  const tone = left <= 0 ? 'var(--danger)' : frac <= 0.1 ? 'var(--danger)' : frac <= 0.25 ? 'var(--gold)' : 'var(--a3)';
  return (
    <div className={`timer-ring${left <= 0 ? ' over' : ''}`} style={{ width: size, height: size }} role="timer" aria-live="off" aria-label={`${fmtClock(left)} left`}>
      <svg width={size} height={size} aria-hidden="true">
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="var(--raised)" strokeWidth="5" />
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke={tone} strokeWidth="5" strokeLinecap="round"
                strokeDasharray={c} strokeDashoffset={c * (1 - frac)} transform={`rotate(-90 ${size / 2} ${size / 2})`} />
      </svg>
      <span style={{ color: tone }}>{fmtClock(left)}</span>
    </div>
  );
}

/** Sessions history with small score pills. */
export function HistoryList({ rows, scoreKey, onOpen, empty }) {
  const stats = useMemo(() => {
    const done = rows.filter((r) => r[scoreKey] != null);
    if (!done.length) return null;
    const avg = done.reduce((a, r) => a + r[scoreKey], 0) / done.length;
    return { count: done.length, avg: Math.round(avg), best: Math.round(Math.max(...done.map((r) => r[scoreKey]))) };
  }, [rows, scoreKey]);
  return (
    <>
      {stats && (
        <div className="mini-stats">
          <div><b>{stats.count}</b><span>completed</span></div>
          <div><b>{stats.avg}</b><span>average</span></div>
          <div><b>{stats.best}</b><span>best</span></div>
        </div>
      )}
      {rows.length === 0 ? <p className="small muted">{empty}</p> : (
        <ul className="history-list">
          {rows.map((r) => (
            <li key={r.id}>
              <button type="button" onClick={() => onOpen(r)}>
                <span><b>{r.title}</b><span className="small muted">{r.sub}</span></span>
                {r[scoreKey] != null ? <span className={`pill ${r[scoreKey] >= 75 ? 'pill-ok' : r[scoreKey] >= 50 ? 'pill-warn' : 'pill-danger'}`}>{Math.round(r[scoreKey])}</span>
                  : <span className="pill pill-neutral">Resume</span>}
              </button>
            </li>
          ))}
        </ul>
      )}
    </>
  );
}
