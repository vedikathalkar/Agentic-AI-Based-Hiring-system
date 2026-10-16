import { useState } from 'react';
import { Link } from 'react-router-dom';
import { api } from '../../api';
import { useApp } from '../../context/AppContext';
import { Async, EmptyState, PageHeader, Tabs, useAsync } from '../../components/ui';
import { formatDate } from '../../utils/status';

export default function HrJobs() {
  const { toast } = useApp();
  const jobs = useAsync(() => api.getMyJobs(), []);
  const apps = useAsync(() => api.getCandidates(), []);
  const [tab, setTab] = useState('open');
  const [q, setQ] = useState('');
  const [busy, setBusy] = useState(null);

  const count = (jobId) => (apps.data || []).filter((a) => a.job_id === jobId).length;
  const toggle = async (job) => {
    setBusy(job.job_id);
    try { await api.setJobStatus(job.job_id, job.status === 'closed' ? 'open' : 'closed'); jobs.reload(); toast(job.status === 'closed' ? 'Job re-opened' : 'Job closed', 'ok'); }
    catch (e) { toast(e.message, 'danger'); }
    finally { setBusy(null); }
  };

  return (
    <>
      <PageHeader title="Jobs" subtitle="Roles you own. Closed roles stop accepting applications but keep their candidates."
                  actions={<Link className="btn btn-primary" to="/hr/post-job">+ Post new role</Link>} />
      <Async state={jobs} loadingLabel="Loading jobs…" errorLabel="Failed to load jobs">
        {(rows) => {
          const n = (s) => rows.filter((j) => (j.status || 'open') === s).length;
          const list = rows.filter((j) => (j.status || 'open') === tab && j.title.toLowerCase().includes(q.toLowerCase()));
          return (
            <>
              <Tabs tabs={[['open', `Live (${n('open')})`], ['closed', `Closed (${n('closed')})`]]} value={tab} onChange={setTab} />
              <div className="tools"><label className="sr-only" htmlFor="jq">Filter jobs</label><input id="jq" className="input" placeholder="Filter listings…" value={q} onChange={(e) => setQ(e.target.value)} /></div>
              <section className="card" style={{ padding: '4px 18px' }}>
                {list.length === 0 ? <EmptyState title="No listings here yet" action={<Link className="btn btn-primary btn-sm" to="/hr/post-job">Post a role</Link>}>Post your first role to start receiving applications.</EmptyState> : list.map((j) => (
                  <div key={j.job_id} className="job-row">
                    <div style={{ flex: 1, minWidth: 220 }}>
                      <h3 style={{ fontSize: 16 }}>{j.title}{!j.hr_account_id && <span className="pill pill-neutral" style={{ marginLeft: 8 }}>Legacy · shared</span>}</h3>
                      <p className="small muted">{[j.team, j.location, `${j.min_experience || 0}+ yrs`, j.requirements].filter(Boolean).join(' · ')}</p>
                      <p className="small muted">Weights {j.weight_skill}/{j.weight_experience}/{j.weight_test} · {j.coding_questions || 0} coding · {j.assessment_minutes || 30} min · posted {formatDate(j.created_at)}</p>
                    </div>
                    <Link className="small" to={`/hr/applications?job=${j.job_id}`}>{count(j.job_id)} applicants</Link>
                    {j.hr_account_id && <button className="btn btn-secondary btn-sm" disabled={busy === j.job_id} onClick={() => toggle(j)}>{j.status === 'closed' ? 'Re-open' : 'Close'}</button>}
                  </div>
                ))}
              </section>
            </>
          );
        }}
      </Async>
    </>
  );
}
