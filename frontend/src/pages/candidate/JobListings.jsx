import { useEffect, useMemo, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { SlidersHorizontal } from 'lucide-react';
import SmartSearch, { useDebounced } from '../../components/SmartSearch';
import { api } from '../../api';
import { Async, EmptyState, PageHeader, useAsync } from '../../components/ui';

const LOGO_COLORS = ['#4C3FD6', '#A9752E', '#12805C', '#C2344D', '#5A6E8C'];
const logoColor = (name) => LOGO_COLORS[(name?.charCodeAt(0) || 0) % LOGO_COLORS.length];

const timeAgo = (dateStr) => {
  if (!dateStr) return '';
  const days = Math.floor((Date.now() - new Date(`${dateStr}Z`).getTime()) / 86400000);
  if (days <= 0) return 'Today';
  if (days === 1) return '1 day ago';
  if (days < 14) return `${days} days ago`;
  return `${Math.floor(days / 7)} weeks ago`;
};

const EXAMPLES = ['remote python jobs', 'react developer in pune', 'fresher data analyst', 'ml engineer bangalore 2+ years'];

export default function JobListings() {
  const [params, setParams] = useSearchParams();
  const applied = useAsync(() => api.getMyApplications(), []);
  const [query, setQuery] = useState(params.get('q') || '');
  const [location, setLocation] = useState('');
  const [mode, setMode] = useState('');
  const [maxExp, setMaxExp] = useState('');
  const [sort, setSort] = useState('relevance');
  const q = useDebounced(query, 300);
  const results = useAsync(() => api.searchJobs({ q, location, work_mode: mode, max_experience: maxExp, sort }), [q, location, mode, maxExp, sort]);

  useEffect(() => { setParams(q ? { q } : {}, { replace: true }); }, [q]); // keep the search in the URL (shareable, survives refresh)

  const appliedJobs = useMemo(() => new Set((applied.data || []).map((a) => a.job_id)), [applied.data]);
  const data = results.data;
  const anyFilter = location || mode || maxExp;

  return (
    <>
      <PageHeader title="Find your next role" subtitle="Search the way you talk — skills, city, experience and work mode are understood automatically." />
      <div className="card" style={{ padding: 16, marginBottom: 16, display: 'grid', gap: 12 }}>
        <SmartSearch id="job-q" value={query} onChange={setQuery} understood={data?.understood || []} corrections={data?.corrections || []}
                     examples={EXAMPLES} count={data?.total} loading={results.loading}
                     placeholder="e.g. remote python ML jobs in Pune, 2+ years" label="Search jobs" />
        <div className="filter-bar">
          <SlidersHorizontal size={15} aria-hidden="true" className="muted" />
          <label className="sr-only" htmlFor="job-loc">Location</label>
          <select id="job-loc" className="input" value={location} onChange={(e) => setLocation(e.target.value)}>
            <option value="">Any location</option>
            {(data?.facets.locations || []).map((l) => <option key={l} value={l.split(/[·,]/)[0].trim()}>{l}</option>)}
          </select>
          <label className="sr-only" htmlFor="job-mode">Work mode</label>
          <select id="job-mode" className="input" value={mode} onChange={(e) => setMode(e.target.value)}>
            <option value="">Any work mode</option><option value="remote">Remote</option><option value="hybrid">Hybrid</option><option value="on-site">On-site</option>
          </select>
          <label className="sr-only" htmlFor="job-exp">Experience</label>
          <select id="job-exp" className="input" value={maxExp} onChange={(e) => setMaxExp(e.target.value)}>
            <option value="">Any experience</option><option value="0">Freshers</option><option value="1">Up to 1 year</option><option value="3">Up to 3 years</option><option value="5">Up to 5 years</option>
          </select>
          <label className="sr-only" htmlFor="job-sort">Sort</label>
          <select id="job-sort" className="input" value={sort} onChange={(e) => setSort(e.target.value)}>
            <option value="relevance">Best match</option><option value="newest">Newest first</option><option value="experience">Least experience first</option>
          </select>
          {anyFilter && <button className="btn btn-secondary btn-sm" onClick={() => { setLocation(''); setMode(''); setMaxExp(''); }}>Clear filters</button>}
        </div>
        {!query && data?.facets.skills?.length > 0 && (
          <div className="chips" aria-label="Popular skills">
            <span className="small muted">Popular:</span>
            {data.facets.skills.slice(0, 10).map((s) => <button key={s} type="button" className="chip" onClick={() => setQuery(s)}>{s}</button>)}
          </div>
        )}
      </div>
      <Async state={results} loadingLabel="Searching roles…" errorLabel="Search failed">
        {(r) => r.results.length === 0 ? (
          <EmptyState title="No roles match">{query ? 'Remove a filter chip above or try different words.' : 'No open roles right now — check back soon.'}</EmptyState>
        ) : (
          <div style={{ display: 'grid', gap: 12 }}>
            {r.results.map((job) => {
              const skills = (job.requirements || '').split(/[,;\n]/).map((s) => s.trim()).filter(Boolean);
              const matched = new Set((job.matched_skills || []).map((s) => s.toLowerCase()));
              const already = appliedJobs.has(job.job_id);
              return (
                <article key={job.job_id} className="card job-card" style={{ padding: '18px 20px', display: 'flex', gap: 16, alignItems: 'flex-start', flexWrap: 'wrap' }}>
                  <div aria-hidden="true" style={{ width: 42, height: 42, borderRadius: 10, background: logoColor(job.company_name || job.title), color: '#fff', display: 'flex', alignItems: 'center', justifyContent: 'center', fontFamily: 'var(--font-display)', fontSize: 17, flexShrink: 0 }}>
                    {(job.company_name || job.team || job.title || '?')[0]}
                  </div>
                  <div style={{ flex: 1, minWidth: 220 }}>
                    <p className="small muted">{job.company_name || job.team || 'Company'}</p>
                    <h3 style={{ marginTop: 2 }}>{job.title}</h3>
                    <p className="small muted" style={{ marginTop: 4 }}>{[job.team, job.location, job.min_experience ? `${job.min_experience}+ yrs` : 'Freshers welcome'].filter(Boolean).join(' · ')}</p>
                    <div className="chips" style={{ marginTop: 10 }}>
                      {skills.slice(0, 6).map((s) => <span key={s} className={`pill ${[...matched].some((m) => s.toLowerCase().includes(m) || m.includes(s.toLowerCase())) ? 'pill-ok' : 'pill-neutral'}`}>{s}</span>)}
                      {skills.length > 6 && <span className="pill pill-neutral">+{skills.length - 6} more</span>}
                    </div>
                    {query && job.reasons?.length > 0 && <p className="small muted" style={{ marginTop: 8 }}>Why: {job.reasons.join(' · ')}</p>}
                  </div>
                  <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: 10 }}>
                    <span className="small muted">{timeAgo(job.created_at)}</span>
                    {query && <span className="relevance" title="How well this role matches your search">Match <span className="relevance-bar"><span style={{ width: `${job.relevance}%` }} /></span> {Math.round(job.relevance)}%</span>}
                    {already ? <Link className="btn btn-secondary" to="/applications">Applied ✓</Link>
                      : <Link className="btn btn-primary" to={`/apply/${job.job_id}`}>Apply</Link>}
                  </div>
                </article>
              );
            })}
          </div>
        )}
      </Async>
    </>
  );
}
