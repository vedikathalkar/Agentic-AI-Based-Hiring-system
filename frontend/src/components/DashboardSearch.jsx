import { useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { Briefcase, FileText, SlidersHorizontal } from 'lucide-react';
import SmartSearch, { useDebounced } from './SmartSearch';
import HiringPipeline from './HiringPipeline';
import { api } from '../api';
import { useAsync } from './ui';
import { matchApplications, parseApplicationQuery } from '../utils/appSearch';
import '../styles/pipeline.css';

const JOB_EXAMPLES = ['remote python jobs', 'react developer in pune', 'fresher data analyst', 'ml engineer bangalore 2+ years'];
const APP_EXAMPLES = ['rejected roles', 'pending assessments', 'interview stage this month', 'score above 70'];

function useJobSearch({ query, filters, appliedJobs }) {
  const q = useDebounced(query, 300);
  const res = useAsync(() => api.searchJobs({ q, location: filters.location, work_mode: filters.mode, max_experience: filters.exp, sort: filters.sort }),
    [q, filters.location, filters.mode, filters.exp, filters.sort]);
  const data = res.data;
  let rows = data?.results || [];
  if (filters.hideApplied) rows = rows.filter((j) => !appliedJobs.has(j.job_id));
  return { data, loading: res.loading, error: res.error, rows, q };
}

export default function DashboardSearch() {
  const [scope, setScope] = useState('jobs');
  const [query, setQuery] = useState('');
  const [f, setF] = useState({ location: '', mode: '', exp: '', sort: 'relevance', hideApplied: true, stage: '', assessment: '' });
  const set = (k, v) => setF((s) => ({ ...s, [k]: v }));
  const apps = useAsync(() => api.getMyApplications(), []);
  const appliedJobs = useMemo(() => new Set((apps.data || []).map((a) => a.job_id)), [apps.data]);

  const jobs = useJobSearch({ query: scope === 'jobs' ? query : '', filters: f, appliedJobs });
  const parsed = useMemo(() => parseApplicationQuery(query), [query]);
  const appRows = useMemo(() => matchApplications(apps.data || [], parsed.filters, { stage: f.stage, assessment: f.assessment }), [apps.data, parsed, f.stage, f.assessment]);

  const isJobs = scope === 'jobs';
  const anyFilter = isJobs ? (f.location || f.mode || f.exp) : (f.stage || f.assessment);
  const total = isJobs ? jobs.rows.length : appRows.length;

  return (
    <section className="card section ds" aria-label="Search">
      <div className="row" style={{ marginBottom: 12 }}>
        <div className="ds-tabs" role="tablist" aria-label="What to search">
          <button role="tab" aria-selected={isJobs} className={isJobs ? 'on' : ''} onClick={() => { setScope('jobs'); setQuery(''); }}><Briefcase size={15} aria-hidden="true" /> Find roles</button>
          <button role="tab" aria-selected={!isJobs} className={!isJobs ? 'on' : ''} onClick={() => { setScope('apps'); setQuery(''); }}><FileText size={15} aria-hidden="true" /> My applications</button>
        </div>
        <span className="spacer" />
        {isJobs && <Link className="small" to={`/jobs${jobs.q ? `?q=${encodeURIComponent(jobs.q)}` : ''}`}>Open full job search</Link>}
      </div>

      <SmartSearch id="dash-q" value={query} onChange={setQuery}
                   understood={isJobs ? (jobs.data?.understood || []) : parsed.understood}
                   corrections={isJobs ? (jobs.data?.corrections || []) : []}
                   examples={isJobs ? JOB_EXAMPLES : APP_EXAMPLES} count={query ? total : undefined} loading={isJobs && jobs.loading}
                   label={isJobs ? 'Search roles' : 'Search your applications'}
                   placeholder={isJobs ? 'Try “remote python ML jobs in Pune, 2+ years”' : 'Try “rejected data roles” or “pending assessments”'} />

      <div className="filter-bar" style={{ marginTop: 12 }}>
        <SlidersHorizontal size={15} aria-hidden="true" className="muted" />
        {isJobs ? (
          <>
            <label className="sr-only" htmlFor="ds-loc">Location</label>
            <select id="ds-loc" className="input" value={f.location} onChange={(e) => set('location', e.target.value)}>
              <option value="">Any location</option>
              {(jobs.data?.facets?.locations || []).map((l) => <option key={l} value={l.split(/[·,]/)[0].trim()}>{l}</option>)}
            </select>
            <label className="sr-only" htmlFor="ds-mode">Work mode</label>
            <select id="ds-mode" className="input" value={f.mode} onChange={(e) => set('mode', e.target.value)}>
              <option value="">Any work mode</option><option value="remote">Remote</option><option value="hybrid">Hybrid</option><option value="on-site">On-site</option>
            </select>
            <label className="sr-only" htmlFor="ds-exp">Experience</label>
            <select id="ds-exp" className="input" value={f.exp} onChange={(e) => set('exp', e.target.value)}>
              <option value="">Any experience</option><option value="0">Freshers</option><option value="1">Up to 1 year</option><option value="3">Up to 3 years</option><option value="5">Up to 5 years</option>
            </select>
            <label className="sr-only" htmlFor="ds-sort">Sort</label>
            <select id="ds-sort" className="input" value={f.sort} onChange={(e) => set('sort', e.target.value)}>
              <option value="relevance">Best match</option><option value="newest">Newest first</option><option value="experience">Least experience first</option>
            </select>
            <label className="ds-check"><input type="checkbox" checked={f.hideApplied} onChange={(e) => set('hideApplied', e.target.checked)} /> Hide roles I applied to</label>
          </>
        ) : (
          <>
            <label className="sr-only" htmlFor="ds-stage">Outcome</label>
            <select id="ds-stage" className="input" value={f.stage} onChange={(e) => set('stage', e.target.value)}>
              <option value="">Any outcome</option><option value="active">In progress</option><option value="interview">Interview stage</option><option value="offer">Offer / hired</option><option value="stopped">Process stopped</option>
            </select>
            <label className="sr-only" htmlFor="ds-asmt">Assessment</label>
            <select id="ds-asmt" className="input" value={f.assessment} onChange={(e) => set('assessment', e.target.value)}>
              <option value="">Any assessment state</option><option value="pending">Assessment pending</option><option value="completed">Assessment completed</option>
            </select>
          </>
        )}
        {anyFilter && <button className="btn btn-secondary btn-sm" onClick={() => setF((s) => ({ ...s, location: '', mode: '', exp: '', stage: '', assessment: '' }))}>Clear filters</button>}
      </div>

      <div className="ds-results" aria-live="polite">
        {isJobs ? (
          jobs.error ? <p className="alert alert-danger small">Search failed: {jobs.error.message}</p>
            : jobs.rows.length === 0 ? <p className="small muted" style={{ marginTop: 14 }}>{jobs.loading ? 'Searching…' : 'No roles match — remove a filter chip or try different words.'}</p>
              : (
                <div className="ds-grid">
                  {jobs.rows.slice(0, 6).map((j) => {
                    const already = appliedJobs.has(j.job_id);
                    return (
                      <article key={j.job_id} className="list-card">
                        <b>{j.title}</b>
                        <p className="small muted">{[j.company_name || j.team, j.location, j.min_experience ? `${j.min_experience}+ yrs` : 'Freshers welcome'].filter(Boolean).join(' · ')}</p>
                        {query && j.reasons?.length > 0 && <p className="small muted" style={{ margin: '4px 0' }}>Why: {j.reasons.slice(0, 2).join(' · ')}</p>}
                        <div className="row" style={{ marginTop: 8 }}>
                          {query && <span className="relevance">Match <span className="relevance-bar"><span style={{ width: `${j.relevance}%` }} /></span> {Math.round(j.relevance)}%</span>}
                          <span className="spacer" />
                          {already ? <Link className="btn btn-secondary btn-sm" to="/applications">Applied ✓</Link> : <Link className="btn btn-primary btn-sm" to={`/apply/${j.job_id}`}>Apply</Link>}
                        </div>
                      </article>
                    );
                  })}
                </div>
              )
        ) : (
          apps.error ? <p className="alert alert-danger small">Couldn't load your applications: {apps.error.message}</p>
            : appRows.length === 0 ? <p className="small muted" style={{ marginTop: 14 }}>{apps.loading ? 'Loading…' : 'None of your applications match.'}</p>
              : (
                <div className="ds-apps">
                  {appRows.slice(0, 6).map((a) => (
                    <article key={a.application_id} className="list-card">
                      <div className="row"><b>{a.job_title}</b><span className="spacer" /><Link className="small" to="/applications">Details</Link></div>
                      <div style={{ marginTop: 10 }}><HiringPipeline pipeline={a.pipeline} compact /></div>
                    </article>
                  ))}
                </div>
              )
        )}
      </div>
    </section>
  );
}
