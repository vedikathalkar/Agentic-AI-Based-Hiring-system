import { useCallback, useEffect, useMemo, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import StatusBadge from '../../components/StatusBadge';
import SmartSearch, { useDebounced } from '../../components/SmartSearch';
import DecisionDialog from '../../components/DecisionDialog';
import { api } from '../../api';
import { formatScore, scoreTone, compareScoresDesc } from '../../utils/score';
import { applicationStageLabel, formatDate } from '../../utils/status';

const TABS = [
  ['all', 'All'],
  ['pending', 'Assessment pending'],
  ['assessed', 'Assessed'],
  ['shortlisted', 'Shortlisted'],
  ['rejected', 'Rejected'],
];

function inTab(a, tab) {
  if (tab === 'all') return true;
  if (tab === 'pending') return a.assessment_status !== 'completed' && !['shortlisted', 'scheduled', 'interviewed', 'selected', 'offered', 'hired', 'offer_declined', 'rejected'].includes(a.status);
  if (tab === 'assessed') return a.assessment_status === 'completed' || a.status === 'assessed';
  if (tab === 'shortlisted') return ['shortlisted', 'scheduled', 'interviewed', 'selected', 'offered', 'hired'].includes(a.status);
  return a.status === tab;
}

function ScoreCell({ value }) {
  return <td className={`num tone-${scoreTone(value)}`}>{formatScore(value)}</td>;
}

export default function Applications() {
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const [apps, setApps] = useState([]);
  const [jobs, setJobs] = useState([]);
  const [jobId, setJobId] = useState(params.get('job') || 'all');
  const [tab, setTab] = useState('all');
  const [query, setQuery] = useState('');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(null);
  const [notice, setNotice] = useState(null);
  const [search, setSearch] = useState(null);   // server NLP results for the current query
  const debounced = useDebounced(query, 300);

  useEffect(() => {
    if (!debounced.trim()) { setSearch(null); return undefined; }
    let live = true;
    api.searchCandidates({ q: debounced, job_id: jobId === 'all' ? undefined : jobId })
      .then((r) => { if (live) setSearch(r); })
      .catch((err) => { if (live) setError(err.message); });
    return () => { live = false; };
  }, [debounced, jobId, apps]);

  const load = useCallback(() => {
    setError(null);
    return Promise.all([api.getCandidates(), api.getMyJobs()])
      .then(([a, j]) => { setApps(a); setJobs(j); })
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => { load(); }, [load]);

  // HR decisions are persisted through the backend, then the list is reloaded.
  const [pending, setPending] = useState(null);      // { app, status } waiting for the decision dialog
  const decide = (app, status) => setPending({ app, status });
  const confirmDecision = async (note) => {
    const { app, status } = pending;
    setBusy(app.application_id); setNotice(null);
    try {
      await api.updateApplicationStatus(app.application_id, status, note);
      setPending(null);
      await load();
      setNotice(`${app.candidate_name} marked ${status}. They've been notified with an explanation.`);
    } catch (err) { setError(err.message); setPending(null); }
    finally { setBusy(null); }
  };

  const rows = useMemo(() => {
    const base = apps.filter((a) => jobId === 'all' || String(a.job_id) === String(jobId)).filter((a) => inTab(a, tab));
    if (search && debounced.trim()) {
      // Ranked by the NLP search; each row keeps the server's explanation.
      const byId = new Map(search.results.map((r, i) => [r.application_id, { ...r, rank: i }]));
      return base.filter((a) => byId.has(a.application_id))
        .map((a) => ({ ...a, ...byId.get(a.application_id) }))
        .sort((a, b) => a.rank - b.rank);
    }
    return base.sort((a, b) => compareScoresDesc(a.final_score, b.final_score) || compareScoresDesc(a.skill_score, b.skill_score));
  }, [apps, jobId, tab, search, debounced]);

  return (
    <>
      {pending && <DecisionDialog name={pending.app.candidate_name} status={pending.status} busy={busy === pending.app.application_id} onCancel={() => setPending(null)} onConfirm={confirmDecision} />}
        <div className="page-head">
          <div>
            <h1>Applications</h1>
            <p>Scores come straight from the screening and ranking agents. “—” means not calculated yet.</p>
          </div>
        </div>

        <div className="tabs" role="tablist" aria-label="Filter by stage">
          {TABS.map(([key, label]) => (
            <button key={key} role="tab" aria-selected={tab === key} onClick={() => setTab(key)}>
              {label} ({apps.filter((a) => (jobId === 'all' || String(a.job_id) === String(jobId)) && inTab(a, key)).length})
            </button>
          ))}
        </div>

        <div className="card" style={{ padding: 14, marginBottom: 14 }}>
          <SmartSearch id="app-search" value={query} onChange={setQuery} understood={search?.understood || []} corrections={search?.corrections || []}
                       count={debounced.trim() ? rows.length : null} label="Search applicants"
                       examples={['python 3+ years score above 70', 'shortlisted react developers', 'freshers with sql']}
                       placeholder="e.g. shortlisted python developers, 3+ years, score above 70" />
        </div>
        <div className="tools">
          <label className="sr-only" htmlFor="app-job">Filter by role</label>
          <select id="app-job" className="input" value={jobId} onChange={(e) => setJobId(e.target.value)}>
            <option value="all">All roles</option>
            {jobs.map((j) => <option key={j.job_id} value={j.job_id}>{j.title}</option>)}
          </select>
        </div>

        {error && <p className="alert alert-danger" role="alert" style={{ marginBottom: 12 }}>Failed to load applications: {error} <button className="btn btn-secondary btn-sm" onClick={load}>Retry</button></p>}
        {notice && <p className="alert alert-ok" role="status" style={{ marginBottom: 12 }}>{notice}</p>}

        <div className="card table-wrap">
          <table className="table">
            <thead>
              <tr>
                <th scope="col">Candidate</th>
                <th scope="col">Applied for</th>
                <th scope="col">Experience</th>
                <th scope="col">Skill</th>
                <th scope="col">Test</th>
                <th scope="col">Final</th>
                <th scope="col">Status</th>
                <th scope="col">Actions</th>
              </tr>
            </thead>
            <tbody>
              {loading ? (
                <tr><td colSpan={8} className="muted" style={{ textAlign: 'center', padding: 32 }}>Loading applications…</td></tr>
              ) : rows.length === 0 ? (
                <tr><td colSpan={8} className="muted" style={{ textAlign: 'center', padding: 32 }}>No applications match. Clear the search or change the filters.</td></tr>
              ) : rows.map((a) => (
                <tr key={a.application_id}>
                  <td><b>{a.candidate_name}</b><br /><span className="small muted">{a.candidate_email} · {formatDate(a.applied_at)}</span>
                    {a.reasons?.length > 0 && <div className="small" style={{ color: 'var(--gold)', marginTop: 3 }}>{a.reasons.join(' · ')}</div>}</td>
                  <td>{a.job_title || `Job #${a.job_id}`}</td>
                  <ScoreCell value={a.experience_score} />
                  <ScoreCell value={a.skill_score} />
                  <ScoreCell value={a.test_score} />
                  <td className={`num tone-${scoreTone(a.final_score)}`}><b>{formatScore(a.final_score)}</b></td>
                  <td>
                    <StatusBadge label={applicationStageLabel(a)} />
                    {a.screening_status === 'failed' && <div className="small tone-danger" style={{ marginTop: 4 }}>Screening failed</div>}
                  </td>
                  <td>
                    <div className="row" style={{ flexWrap: 'nowrap', gap: 6 }}>
                      <button className="btn btn-primary btn-sm" onClick={() => navigate(`/hr/candidate/${a.candidate_id}`)}>View Candidate</button>
                      <button className="btn btn-ok btn-sm" disabled={busy === a.application_id || ['shortlisted', 'scheduled', 'interviewed', 'selected', 'offered', 'hired'].includes(a.status)} onClick={() => decide(a, 'shortlisted')} aria-label={`Shortlist ${a.candidate_name}`}>Shortlist</button>
                      <button className="btn btn-danger btn-sm" disabled={busy === a.application_id || ['rejected', 'hired'].includes(a.status)} onClick={() => decide(a, 'rejected')} aria-label={`Reject ${a.candidate_name}`}>Reject</button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
    </>
  );
}
