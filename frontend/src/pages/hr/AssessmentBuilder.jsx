import { useState } from 'react';
import { Plus, Sparkles, Trash2 } from 'lucide-react';
import { api } from '../../api';
import { useApp } from '../../context/AppContext';
import { Async, EmptyState, Modal, TagInput, useAsync } from '../../components/ui';
import { formatDate } from '../../utils/status';

const STATUS = { draft: ['Draft', 'pill-warn'], published: ['Published', 'pill-ok'], archived: ['Archived', 'pill-neutral'] };
const TYPE_LABEL = { mcq: 'MCQ', coding: 'Coding', mixed: 'Mixed', short_answer: 'Short answer' };
const LETTERS = ['A', 'B', 'C', 'D', 'E', 'F'];

function GenerateForm({ jobs, onCreated, onCancel }) {
  const [f, setF] = useState({ job_id: jobs[0]?.job_id || '', title: '', skills: [], difficulty: 'medium', num_questions: 10, assessment_type: 'mixed', time_limit_minutes: 30 });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const job = jobs.find((j) => String(j.job_id) === String(f.job_id));
  const set = (k) => (e) => setF((x) => ({ ...x, [k]: e?.target ? e.target.value : e }));
  const pickJob = (e) => {
    const j = jobs.find((x) => String(x.job_id) === e.target.value);
    setF((x) => ({ ...x, job_id: e.target.value, skills: (j?.requirements || '').split(/[,;\n]/).map((s) => s.trim()).filter(Boolean) }));
  };
  const submit = async () => {
    setBusy(true); setError(null);
    try {
      onCreated(await api.generateAssessment({ ...f, job_id: Number(f.job_id), num_questions: Number(f.num_questions), time_limit_minutes: Number(f.time_limit_minutes) }));
    } catch (e) { setError(e.message); }
    finally { setBusy(false); }
  };
  const skills = f.skills.length ? f.skills : (job?.requirements || '').split(/[,;\n]/).map((s) => s.trim()).filter(Boolean);
  return (
    <section className="card section" style={{ marginTop: 0 }}>
      <h3><Sparkles size={16} aria-hidden="true" style={{ verticalAlign: -2 }} /> Generate an assessment with AI</h3>
      <p className="small muted" style={{ marginBottom: 12 }}>The assessment agent drafts the questions; coding problems are verified by running a reference solution. You review and edit everything before publishing.</p>
      <div className="form-grid">
        <div className="field"><label className="field-label" htmlFor="ab-job">Job *</label>
          <select id="ab-job" className="input" value={f.job_id} onChange={pickJob}>{jobs.map((j) => <option key={j.job_id} value={j.job_id}>{j.title}</option>)}</select></div>
        <div className="field"><label className="field-label" htmlFor="ab-title">Title</label>
          <input id="ab-title" className="input" placeholder={job ? `${job.title} assessment` : ''} value={f.title} onChange={set('title')} /></div>
        <div className="field"><label className="field-label" htmlFor="ab-type">Type</label>
          <select id="ab-type" className="input" value={f.assessment_type} onChange={set('assessment_type')}><option value="mixed">Mixed (MCQ + coding)</option><option value="mcq">MCQ only</option><option value="coding">Coding only</option></select></div>
        <div className="field"><label className="field-label" htmlFor="ab-diff">Difficulty</label>
          <select id="ab-diff" className="input" value={f.difficulty} onChange={set('difficulty')}><option>easy</option><option>medium</option><option>hard</option></select></div>
        <div className="field"><label className="field-label" htmlFor="ab-n">Number of questions</label>
          <input id="ab-n" className="input" type="number" min={1} max={30} value={f.num_questions} onChange={set('num_questions')} /></div>
        <div className="field"><label className="field-label" htmlFor="ab-time">Time limit (minutes)</label>
          <input id="ab-time" className="input" type="number" min={5} max={180} value={f.time_limit_minutes} onChange={set('time_limit_minutes')} /></div>
      </div>
      <div className="field"><TagInput id="ab-skills" label="Skills to assess" value={skills} onChange={set('skills')} placeholder="Add a skill and press Enter" /></div>
      {error && <p className="alert alert-danger small" role="alert">{error}</p>}
      <div className="row" style={{ justifyContent: 'flex-end', marginTop: 8 }}>
        <button className="btn btn-secondary" onClick={onCancel} disabled={busy}>Cancel</button>
        <button className="btn btn-primary" onClick={submit} disabled={busy || !f.job_id || !skills.length}>{busy ? 'Generating… (up to a minute)' : 'Generate draft'}</button>
      </div>
    </section>
  );
}

function QuestionCard({ q, i, onChange, onDelete, problems, locked }) {
  const set = (k, v) => onChange({ ...q, [k]: v });
  const setOpt = (j, text) => set('options', q.options.map((o, k) => (k === j ? { ...o, text } : o)));
  return (
    <div className="list-card">
      <div className="row" style={{ marginBottom: 8 }}>
        <b>Q{i + 1}</b><span className="pill pill-brand">{TYPE_LABEL[q.type]}</span><span className="small muted">{q.skill} · {q.difficulty}</span>
        <span className="spacer" />
        {!locked && <button className="btn btn-danger btn-sm" onClick={onDelete} aria-label={`Delete question ${i + 1}`}><Trash2 size={14} aria-hidden="true" /> Delete</button>}
      </div>
      {q.type === 'coding' ? (
        <>
          <label className="field-label" htmlFor={`q${i}-p`}>Coding problem</label>
          <select id={`q${i}-p`} className="input" disabled={locked} value={q.problem_id || ''}
                  onChange={(e) => { const p = problems.find((x) => String(x.problem_id) === e.target.value); onChange({ ...q, problem_id: p ? p.problem_id : null, question: p?.title || '', problem: null }); }}>
            <option value="">Choose a problem…</option>
            {problems.map((p) => <option key={p.problem_id} value={p.problem_id}>{p.title} ({p.difficulty}){p.library ? '' : ' · yours'}</option>)}
          </select>
          {q.problem && (
            <details style={{ marginTop: 8 }}><summary className="small">Preview problem · {q.problem.test_count} tests</summary>
              <p className="small" style={{ whiteSpace: 'pre-wrap', marginTop: 6 }}>{q.problem.statement}</p>
              {q.problem.constraints && <p className="small muted" style={{ whiteSpace: 'pre-wrap' }}><b>Constraints:</b> {q.problem.constraints}</p>}
              {q.problem.examples.map((ex, k) => <pre key={k} className="pre small">{`Input:\n${ex.input}\nOutput:\n${ex.output}`}</pre>)}
            </details>
          )}
        </>
      ) : (
        <>
          <label className="field-label" htmlFor={`q${i}-t`}>Question</label>
          <textarea id={`q${i}-t`} className="input" rows={2} disabled={locked} value={q.question} onChange={(e) => set('question', e.target.value)} />
          {q.type === 'mcq' && (
            <fieldset style={{ border: 0, padding: 0, marginTop: 8 }}>
              <legend className="small muted">Options — select the correct one</legend>
              {(q.options || []).map((o, j) => (
                <div key={o.label} className="row" style={{ flexWrap: 'nowrap', marginTop: 4 }}>
                  <input type="radio" name={`q${i}-correct`} aria-label={`Option ${o.label} is correct`} disabled={locked} checked={q.correct_option_label === o.label} onChange={() => set('correct_option_label', o.label)} />
                  <b className="small">{o.label}</b>
                  <input className="input" aria-label={`Option ${o.label}`} disabled={locked} value={o.text} onChange={(e) => setOpt(j, e.target.value)} />
                </div>
              ))}
            </fieldset>
          )}
          {q.type === 'short_answer' && (
            <><label className="field-label" htmlFor={`q${i}-r`} style={{ marginTop: 8 }}>Reference answer (used for grading)</label>
              <textarea id={`q${i}-r`} className="input" rows={2} disabled={locked} value={q.reference_answer || ''} onChange={(e) => set('reference_answer', e.target.value)} /></>
          )}
        </>
      )}
    </div>
  );
}

function Review({ id, onBack }) {
  const { toast } = useApp();
  const state = useAsync(() => api.assessmentTemplate(id), [id]);
  const problems = useAsync(() => api.codingProblems(), []);
  const [draft, setDraft] = useState(null);
  const [busy, setBusy] = useState(null);
  const [error, setError] = useState(null);
  const [confirmDelete, setConfirmDelete] = useState(false);

  const t = state.data;
  const d = draft || t;
  const locked = t?.status === 'archived';
  const edit = (patch) => setDraft({ ...d, ...patch });
  const act = async (kind, fn, message) => {
    setBusy(kind); setError(null);
    try { const r = await fn(); if (r?.template_id) { state.setData(r); setDraft(null); } toast(message, 'ok'); return r; }
    catch (e) { setError(e.message); return null; }
    finally { setBusy(null); }
  };
  const save = () => act('save', () => api.updateAssessmentTemplate(id, { title: d.title, time_limit_minutes: Number(d.time_limit_minutes), questions: d.questions }), 'Changes saved');
  const publish = async () => {
    if (draft && !(await save())) return;
    act('publish', () => api.publishAssessmentTemplate(id), 'Published — candidates for this job will get this assessment');
  };
  const addQuestion = (type) => {
    const base = { type, skill: t.skills[0] || 'general', difficulty: t.difficulty, question: '' };
    const q = type === 'mcq' ? { ...base, options: LETTERS.slice(0, 4).map((l) => ({ label: l, text: '' })), correct_option_label: 'A' } : { ...base, problem_id: null };
    edit({ questions: [...d.questions, q] });
  };

  return (
    <Async state={state} loadingLabel="Loading assessment…" errorLabel="Failed to load assessment">
      {() => (
        <section className="card section" style={{ marginTop: 0 }}>
          <div className="row" style={{ marginBottom: 10 }}>
            <button className="btn btn-secondary btn-sm" onClick={onBack}>← All assessments</button>
            <span className="spacer" /><span className={`pill ${STATUS[t.status][1]}`}>{STATUS[t.status][0]}</span>
          </div>
          <div className="form-grid">
            <div className="field"><label className="field-label" htmlFor="rv-title">Title</label><input id="rv-title" className="input" disabled={locked} value={d.title} onChange={(e) => edit({ title: e.target.value })} /></div>
            <div className="field"><label className="field-label" htmlFor="rv-time">Time limit (minutes)</label><input id="rv-time" className="input" type="number" min={5} max={180} disabled={locked} value={d.time_limit_minutes} onChange={(e) => edit({ time_limit_minutes: e.target.value })} /></div>
          </div>
          <p className="small muted">For <b>{t.job_title}</b> · {TYPE_LABEL[t.assessment_type]} · {t.difficulty} · skills: {t.skills.join(', ')}</p>
          {t.notes.length > 0 && <div className="alert alert-warn small" style={{ marginTop: 8 }}>{t.notes.map((n) => <p key={n}>{n}</p>)}</div>}
          {t.status === 'published' && <p className="alert alert-info small" style={{ marginTop: 8 }}>Published {formatDate(t.published_at, true)}. Edits apply to candidates who start after you save; attempts already started keep their questions.</p>}
          <div style={{ display: 'grid', gap: 10, marginTop: 12 }}>
            {d.questions.map((q, i) => (
              <QuestionCard key={i} q={q} i={i} locked={locked} problems={problems.data || []}
                            onChange={(nq) => edit({ questions: d.questions.map((x, k) => (k === i ? nq : x)) })}
                            onDelete={() => edit({ questions: d.questions.filter((_, k) => k !== i) })} />
            ))}
            {d.questions.length === 0 && <EmptyState title="No questions">Add a question below.</EmptyState>}
          </div>
          {error && <p className="alert alert-danger small" role="alert" style={{ marginTop: 10 }}>{error}</p>}
          {!locked && (
            <div className="row" style={{ marginTop: 12 }}>
              <button className="btn btn-secondary btn-sm" onClick={() => addQuestion('mcq')}><Plus size={14} aria-hidden="true" /> MCQ</button>
              <button className="btn btn-secondary btn-sm" onClick={() => addQuestion('coding')}><Plus size={14} aria-hidden="true" /> Coding</button>
              <span className="spacer" />
              <button className="btn btn-danger" onClick={() => setConfirmDelete(true)} disabled={!!busy}>Delete</button>
              {t.status === 'published' && <button className="btn btn-secondary" disabled={!!busy} onClick={() => act('unpub', () => api.unpublishAssessmentTemplate(id), 'Moved back to draft')}>Unpublish</button>}
              <button className="btn btn-secondary" onClick={save} disabled={!draft || !!busy}>{busy === 'save' ? 'Saving…' : 'Save changes'}</button>
              {t.status !== 'published' && <button className="btn btn-primary" onClick={publish} disabled={!!busy || !d.questions.length}>{busy === 'publish' ? 'Publishing…' : 'Publish'}</button>}
            </div>
          )}
          {confirmDelete && (
            <Modal title="Delete this assessment?" onClose={() => setConfirmDelete(false)}
                   footer={<><button className="btn btn-secondary" onClick={() => setConfirmDelete(false)}>Cancel</button>
                     <button className="btn btn-danger" onClick={async () => { setConfirmDelete(false); if (await act('delete', () => api.deleteAssessmentTemplate(id), 'Assessment deleted')) onBack(); }}>Delete</button></>}>
              <p>If candidates already took it, it is archived instead so their results stay intact.</p>
            </Modal>
          )}
        </section>
      )}
    </Async>
  );
}

export default function AssessmentBuilder() {
  const jobs = useAsync(() => api.getMyJobs(), []);
  const list = useAsync(() => api.assessmentTemplates(), []);
  const [mode, setMode] = useState('list');   // list | new | <template id>

  if (mode === 'new') {
    return (
      <Async state={jobs} loadingLabel="Loading jobs…">
        {(js) => js.length === 0 ? <EmptyState title="Post a job first">Assessments are created for a job.</EmptyState>
          : <GenerateForm jobs={js.filter((j) => j.status !== 'closed')} onCancel={() => setMode('list')} onCreated={(t) => { list.reload(); setMode(t.template_id); }} />}
      </Async>
    );
  }
  if (mode !== 'list') return <Review id={mode} onBack={() => { list.reload(); setMode('list'); }} />;
  return (
    <>
      <div className="row" style={{ marginBottom: 12 }}>
        <p className="small muted" style={{ flex: 1 }}>One published assessment per job. Candidates who start the job's assessment get the published version.</p>
        <button className="btn btn-primary" onClick={() => setMode('new')}><Sparkles size={15} aria-hidden="true" /> Create with AI</button>
      </div>
      <Async state={list} loadingLabel="Loading assessments…" errorLabel="Failed to load assessments">
        {(rows) => rows.length === 0 ? <EmptyState title="No assessments yet">Create one with AI, review it, then publish.</EmptyState> : (
          <div className="card table-wrap">
            <table className="table">
              <thead><tr><th scope="col">Assessment</th><th scope="col">Job</th><th scope="col">Questions</th><th scope="col">Time</th><th scope="col">Status</th><th scope="col"><span className="sr-only">Open</span></th></tr></thead>
              <tbody>{rows.map((t) => (
                <tr key={t.template_id}>
                  <td><b>{t.title}</b><br /><span className="small muted">{TYPE_LABEL[t.assessment_type]} · {t.difficulty}</span></td>
                  <td>{t.job_title}</td>
                  <td className="small">{t.question_counts.mcq} MCQ · {t.question_counts.coding} coding{t.question_counts.short_answer ? ` · ${t.question_counts.short_answer} short` : ''}</td>
                  <td>{t.time_limit_minutes} min</td>
                  <td><span className={`pill ${STATUS[t.status][1]}`}>{STATUS[t.status][0]}</span></td>
                  <td><button className="btn btn-secondary btn-sm" onClick={() => setMode(t.template_id)}>Review</button></td>
                </tr>
              ))}</tbody>
            </table>
          </div>
        )}
      </Async>
    </>
  );
}
