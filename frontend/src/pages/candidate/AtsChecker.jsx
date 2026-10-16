import { useState } from 'react';
import { api } from '../../api';
import { useApp } from '../../context/AppContext';
import { Async, FileUploader, PageHeader, ProgressBar, useAsync } from '../../components/ui';
import { formatDate } from '../../utils/status';
import { scoreTone } from '../../utils/score';

function Report({ r }) {
  const download = () => {
    const lines = [`${r.label} — ${formatDate(r.created_at, true)}`, r.disclaimer, '', `Resume: ${r.file_name}`,
      `Target: ${r.job_title || 'Pasted job description'}`, `Score: ${Math.round(r.score)}%`, '',
      ...Object.entries(r.breakdown).map(([k, v]) => `${k}: ${v.score}/${v.max}`), '',
      `Matched keywords: ${r.keywords.matched.join(', ') || 'none'}`, `Missing keywords: ${r.keywords.missing.join(', ') || 'none'}`, '',
      'Strengths:', ...r.strengths.map((s) => `- ${s}`), '', 'Formatting issues:', ...r.formatting_issues.map((s) => `- ${s}`), '',
      'Suggestions:', ...r.suggestions.map((s) => `- ${s}`)];
    const url = URL.createObjectURL(new Blob([lines.join('\n')], { type: 'text/plain' }));
    const a = document.createElement('a'); a.href = url; a.download = `ats-report-${r.check_id}.txt`; a.click();
    setTimeout(() => URL.revokeObjectURL(url), 10_000);
  };
  const tone = scoreTone(r.score);
  return (
    <section className="card section" aria-label="ATS report">
      <div className="row"><h2 style={{ fontSize: 19 }}>{r.label}</h2><span className="spacer" /><button className="btn btn-secondary btn-sm" onClick={download}>Download report</button></div>
      <p className="small muted" style={{ marginTop: 4 }}>{r.disclaimer}</p>
      <div style={{ margin: '16px 0' }}><ProgressBar value={r.score} label={`ATS score for ${r.job_title || 'the pasted description'}`} tone={tone === 'neutral' ? 'brand' : tone} /></div>
      <div className="grid" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(140px, 1fr))' }}>
        {Object.entries(r.breakdown).map(([k, v]) => <div key={k} className="list-card"><span className="small muted" style={{ textTransform: 'capitalize' }}>{k}</span><br /><b>{v.score} / {v.max}</b></div>)}
      </div>
      <div className="grid grid-2" style={{ marginTop: 12 }}>
        <div><p className="section-title">Matched keywords ({r.keywords.matched.length})</p><div className="chips">{r.keywords.matched.map((k) => <span key={k} className="chip chip-ok">✓ {k}</span>)}{!r.keywords.matched.length && <span className="small muted">None</span>}</div></div>
        <div><p className="section-title">Missing keywords ({r.keywords.missing.length})</p><div className="chips">{r.keywords.missing.map((k) => <span key={k} className="chip chip-missing">✕ {k}</span>)}{!r.keywords.missing.length && <span className="small tone-ok">None — great coverage</span>}</div></div>
      </div>
      {r.preferred_skills?.total > 0 && (
        <div style={{ marginTop: 12 }}><p className="section-title">Preferred skills ({r.preferred_skills.matched.length}/{r.preferred_skills.total})</p>
          <div className="chips">{r.preferred_skills.matched.map((k) => <span key={k} className="chip chip-ok">✓ {k}</span>)}{r.preferred_skills.missing.map((k) => <span key={k} className="chip">○ {k}</span>)}</div></div>
      )}
      {(r.experience_match || r.education_match) && (
        <div className="grid grid-2" style={{ marginTop: 12 }}>
          {r.experience_match && <div className="list-card"><span className="small muted">Experience</span><br />
            <b className={r.experience_match.meets ? 'tone-ok' : 'tone-danger'}>{r.experience_match.meets ? '✓ Meets' : '✕ Below'} requirement</b>
            <p className="small">Required {r.experience_match.required}+ yrs · found {r.experience_match.found ?? 'not stated'}{r.experience_match.found != null ? ' yrs' : ''}</p></div>}
          {r.education_match && <div className="list-card"><span className="small muted">Qualification</span><br />
            <b className={r.education_match.meets ? 'tone-ok' : 'tone-danger'}>{r.education_match.meets ? '✓ Degree level matches' : '✕ Required degree not evident'}</b>
            <p className="small">Required: {r.education_match.required}</p></div>}
        </div>
      )}
      {r.section_details && Object.keys(r.section_details).length > 0 && (
        <div style={{ marginTop: 16 }}><p className="section-title">What we read from each section</p>
          <div className="grid grid-2">
            {[['skills', 'Skills'], ['experience', 'Experience'], ['education', 'Education'], ['projects', 'Projects'], ['certifications', 'Certifications']].map(([k, label]) => (
              <div key={k} className="list-card"><b className="small">{label}</b>
                {r.section_details[k]?.length ? <ul className="small">{r.section_details[k].slice(0, 8).map((x, i) => <li key={i}>{x}</li>)}</ul> : <p className="small muted">Section not found</p>}
              </div>
            ))}
          </div>
        </div>
      )}
      <div className="grid grid-2" style={{ marginTop: 16 }}>
        <div><p className="section-title">Strengths</p><ul className="small">{r.strengths.map((s) => <li key={s}>{s}</li>)}{!r.strengths.length && <li className="muted">—</li>}</ul></div>
        <div><p className="section-title">Suggestions</p><ul className="small">{r.suggestions.map((s) => <li key={s}>{s}</li>)}</ul></div>
        <div><p className="section-title">Formatting issues</p><ul className="small">{r.formatting_issues.map((s) => <li key={s}>{s}</li>)}{!r.formatting_issues.length && <li className="tone-ok">No formatting issues found</li>}</ul></div>
        <div><p className="section-title">Sections & relevance</p>
          <p className="small">Found: {r.sections.found.join(', ') || 'none'}</p>
          {r.sections.missing.length > 0 && <p className="small muted">Missing: {r.sections.missing.join(', ')}</p>}
          {r.experience_relevance && <p className="small">{r.experience_relevance}</p>}
          <p className="small">Education {r.education_found ? 'found' : 'not found'} · {r.quantified_achievements} quantified achievements · {r.word_count} words</p>
        </div>
      </div>
    </section>
  );
}

export default function AtsChecker() {
  const { refreshMe } = useApp();
  const jobs = useAsync(() => api.getJobs(), []);
  const history = useAsync(() => api.atsChecks(), []);
  const profile = useAsync(() => api.getCandidateProfile(), []);
  const [file, setFile] = useState(null);
  const [useProfile, setUseProfile] = useState(false);
  const [jobId, setJobId] = useState('');
  const [jd, setJd] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [report, setReport] = useState(null);

  const pickFile = (f) => {
    setError(null);
    if (!/\.(pdf|docx)$/i.test(f.name)) { setFile(null); setError('Only PDF or DOCX resumes can be analysed.'); return; }
    if (f.size > 5 * 1024 * 1024) { setFile(null); setError('The resume must be 5 MB or smaller.'); return; }
    setFile(f);
  };
  const run = async () => {
    setBusy(true); setError(null);
    try {
      const r = await api.atsCheck({ file: useProfile ? undefined : file, use_profile_resume: useProfile ? 'true' : undefined, job_id: jobId || undefined, job_description: jd });
      setReport(r); history.reload(); refreshMe();
    } catch (e) { setError(e.message); }
    finally { setBusy(false); }
  };
  const openOld = async (id) => { try { setReport(await api.atsReport(id)); } catch (e) { setError(e.message); } };
  const cost = history.data?.cost;

  return (
    <>
      <PageHeader title="Resume ATS Checker" subtitle="See how well an applicant tracking system could read your resume and match it to a job. Your saved resume is never modified." />
      <section className="card section" style={{ marginTop: 0 }}>
        <div className="grid grid-2">
          <div>
            <p className="section-title">1. Resume</p>
            {profile.data?.resume_file_name && profile.data.resume_file_name.match(/\.(pdf|docx)$/i) && (
              <label className="row small" style={{ marginBottom: 8 }}><input type="checkbox" checked={useProfile} onChange={(e) => setUseProfile(e.target.checked)} /> Use my profile resume ({profile.data.resume_file_name})</label>
            )}
            {!useProfile && <FileUploader label="Upload resume" hint="PDF or DOCX" accept=".pdf,.docx" onFile={pickFile} fileName={file?.name} id="ats-file" />}
          </div>
          <div>
            <p className="section-title">2. Target job</p>
            <label className="field-label" htmlFor="ats-job">Choose an open job</label>
            <select id="ats-job" className="input" value={jobId} onChange={(e) => setJobId(e.target.value)}>
              <option value="">— or paste a description below —</option>
              {(jobs.data || []).map((j) => <option key={j.job_id} value={j.job_id}>{j.title}{j.company_name ? ` · ${j.company_name}` : ''}</option>)}
            </select>
            <label className="field-label" htmlFor="ats-jd" style={{ marginTop: 10 }}>Job description {jobId ? '(optional extra text)' : ''}</label>
            <textarea id="ats-jd" className="input" rows={5} value={jd} onChange={(e) => setJd(e.target.value)} placeholder="Paste the job description…" />
          </div>
        </div>
        {error && <p className="alert alert-danger" role="alert" style={{ marginTop: 12 }}>{error}</p>}
        <div className="row" style={{ marginTop: 14 }}>
          <button className="btn btn-primary" disabled={busy || (!useProfile && !file) || (!jobId && jd.trim().length < 30)} onClick={run}>{busy ? 'Analysing…' : 'Analyse resume'}</button>
          {cost > 0 && <span className="small muted">Each check uses {cost} credits · balance {history.data?.balance}</span>}
        </div>
      </section>
      {report && <Report r={report} />}
      <section className="card section">
        <h3>Previous checks</h3>
        <Async state={history} loadingLabel="Loading history…">
          {(h) => h.checks.length === 0 ? <p className="small muted" style={{ marginTop: 8 }}>No checks yet.</p> : (
            <ul className="plain-list">{h.checks.map((c) => (
              <li key={c.check_id} className="row"><span><b>{Math.round(c.score)}%</b> · {c.job_title} · {c.file_name}</span><span className="spacer" /><span className="small muted">{formatDate(c.created_at, true)}</span>
                <button className="btn btn-secondary btn-sm" onClick={() => openOld(c.check_id)}>Open</button></li>
            ))}</ul>
          )}
        </Async>
      </section>
    </>
  );
}
