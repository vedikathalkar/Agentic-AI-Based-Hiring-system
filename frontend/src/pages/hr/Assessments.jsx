import { useState } from 'react';
import { Link } from 'react-router-dom';
import { api } from '../../api';
import { useApp } from '../../context/AppContext';
import CodeEditor from '../../components/CodeEditor';
import AssessmentBuilder from './AssessmentBuilder';
import { Async, EmptyState, Modal, PageHeader, Tabs, useAsync } from '../../components/ui';
import { formatScore, scoreTone } from '../../utils/score';
import { ASSESSMENT_LABEL, formatDate } from '../../utils/status';

const EMPTY = { title: '', difficulty: 'medium', tags: '', statement: '', input_format: '', output_format: '', constraints: '',
  examples: [{ input: '', output: '', explanation: '' }], visible_tests: [{ input: '', output: '' }], hidden_tests: [{ input: '', output: '' }],
  time_limit_ms: 2000, memory_limit_mb: 256, active: true };

function CaseList({ label, items, onChange, withExplanation }) {
  const upd = (i, k, v) => onChange(items.map((x, j) => (j === i ? { ...x, [k]: v } : x)));
  return (
    <fieldset style={{ border: 0, padding: 0, margin: '0 0 12px' }}>
      <legend className="field-label">{label}</legend>
      {items.map((t, i) => (
        <div key={i} className="list-card split" style={{ gap: 8 }}>
          <div><label className="small muted" htmlFor={`${label}-${i}-in`}>Input</label><textarea id={`${label}-${i}-in`} className="input" rows={2} style={{ fontFamily: 'var(--font-mono)' }} value={t.input} onChange={(e) => upd(i, 'input', e.target.value)} /></div>
          <div><label className="small muted" htmlFor={`${label}-${i}-out`}>Expected output</label><textarea id={`${label}-${i}-out`} className="input" rows={2} style={{ fontFamily: 'var(--font-mono)' }} value={t.output} onChange={(e) => upd(i, 'output', e.target.value)} /></div>
          {withExplanation && <div style={{ gridColumn: '1 / -1' }}><label className="small muted" htmlFor={`${label}-${i}-ex`}>Explanation</label><input id={`${label}-${i}-ex`} className="input" value={t.explanation || ''} onChange={(e) => upd(i, 'explanation', e.target.value)} /></div>}
          {items.length > 1 && <button type="button" className="btn btn-danger btn-sm" onClick={() => onChange(items.filter((_, j) => j !== i))}>Remove</button>}
        </div>
      ))}
      <button type="button" className="btn btn-secondary btn-sm" onClick={() => onChange([...items, { input: '', output: '' }])}>+ Add case</button>
    </fieldset>
  );
}

function ProblemEditor({ problem, onClose, onSaved }) {
  const [form, setForm] = useState(problem ? { ...EMPTY, ...problem, hidden_tests: problem.hidden_tests || EMPTY.hidden_tests } : EMPTY);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target ? e.target.value : e }));
  const save = async () => {
    setBusy(true); setError(null);
    try {
      const payload = { ...form, time_limit_ms: Number(form.time_limit_ms), memory_limit_mb: Number(form.memory_limit_mb) };
      onSaved(problem?.problem_id ? await api.updateCodingProblem(problem.problem_id, payload) : await api.createCodingProblem(payload));
    } catch (e) { setError(e.message); }
    finally { setBusy(false); }
  };
  return (
    <Modal wide title={problem ? 'Edit coding problem' : 'New coding problem'} onClose={onClose}
           footer={<><button className="btn btn-secondary" onClick={onClose}>Cancel</button><button className="btn btn-primary" disabled={busy} onClick={save}>{busy ? 'Saving…' : 'Save problem'}</button></>}>
      <div className="form-grid">
        <div className="field"><label className="field-label" htmlFor="cp-title">Title</label><input id="cp-title" className="input" value={form.title} onChange={set('title')} /></div>
        <div className="field"><label className="field-label" htmlFor="cp-diff">Difficulty</label><select id="cp-diff" className="input" value={form.difficulty} onChange={set('difficulty')}><option>easy</option><option>medium</option><option>hard</option></select></div>
        <div className="field"><label className="field-label" htmlFor="cp-tags">Skill tags (comma separated)</label><input id="cp-tags" className="input" value={form.tags} onChange={set('tags')} placeholder="python, sql" /></div>
      </div>
      <div className="field"><label className="field-label" htmlFor="cp-st">Problem statement</label><textarea id="cp-st" className="input" rows={4} value={form.statement} onChange={set('statement')} /></div>
      <div className="form-grid">
        <div className="field"><label className="field-label" htmlFor="cp-in">Input format</label><textarea id="cp-in" className="input" rows={2} value={form.input_format} onChange={set('input_format')} /></div>
        <div className="field"><label className="field-label" htmlFor="cp-out">Output format</label><textarea id="cp-out" className="input" rows={2} value={form.output_format} onChange={set('output_format')} /></div>
        <div className="field"><label className="field-label" htmlFor="cp-con">Constraints</label><textarea id="cp-con" className="input" rows={2} value={form.constraints} onChange={set('constraints')} /></div>
      </div>
      <CaseList label="Examples (shown to candidates)" items={form.examples} onChange={set('examples')} withExplanation />
      <CaseList label="Sample tests (visible)" items={form.visible_tests} onChange={set('visible_tests')} />
      <CaseList label="Hidden tests (never shown)" items={form.hidden_tests} onChange={set('hidden_tests')} />
      <div className="form-grid">
        <div className="field"><label className="field-label" htmlFor="cp-tl">Time limit (ms)</label><input id="cp-tl" type="number" className="input" value={form.time_limit_ms} onChange={set('time_limit_ms')} /></div>
        <div className="field"><label className="field-label" htmlFor="cp-ml">Memory limit (MB)</label><input id="cp-ml" type="number" className="input" value={form.memory_limit_mb} onChange={set('memory_limit_mb')} /></div>
        <label className="row small field" htmlFor="cp-active"><input id="cp-active" type="checkbox" checked={form.active} onChange={(e) => setForm({ ...form, active: e.target.checked })} /> Active (can be used in assessments)</label>
      </div>
      {error && <p className="alert alert-danger small" role="alert">{error}</p>}
    </Modal>
  );
}

function VerifyModal({ problem, onClose }) {
  const langs = useAsync(() => api.codingLanguages(), []);
  const [language, setLanguage] = useState('python');
  const [source, setSource] = useState('');
  const [result, setResult] = useState(null);
  const [busy, setBusy] = useState(false);
  const run = async () => {
    setBusy(true); setResult(null);
    try { setResult(await api.verifyCodingProblem(problem.problem_id, { language, source })); }
    catch (e) { setResult({ status: 'error', error: e.message }); }
    finally { setBusy(false); }
  };
  return (
    <Modal wide title={`Verify tests — ${problem.title}`} onClose={onClose}
           footer={<><button className="btn btn-secondary" onClick={onClose}>Close</button><button className="btn btn-primary" disabled={busy || !source.trim()} onClick={run}>{busy ? 'Running…' : 'Run reference solution'}</button></>}>
      <p className="small muted" style={{ marginBottom: 8 }}>Runs your reference solution in the sandbox against {problem.editable ? 'all sample and hidden' : 'the sample'} tests.</p>
      <select className="input" aria-label="Language" style={{ width: 180, marginBottom: 8 }} value={language} onChange={(e) => setLanguage(e.target.value)}>
        {(langs.data?.languages || []).map((l) => <option key={l.key} value={l.key}>{l.label}</option>)}
      </select>
      <CodeEditor value={source} onChange={setSource} language={language} label="Reference solution" />
      {result && <p className={`alert ${result.status === 'accepted' ? 'alert-ok' : 'alert-danger'} small`} style={{ marginTop: 10 }}>{result.status}: {result.passed ?? 0} / {result.total ?? 0} passed{result.error ? ` — ${result.error}` : ''}</p>}
    </Modal>
  );
}

export default function HrAssessments() {
  const { toast } = useApp();
  const [tab, setTab] = useState(() => new URLSearchParams(window.location.search).get('tab') || 'builder');
  const apps = useAsync(() => api.getCandidates(), []);
  const problems = useAsync(() => api.codingProblems(), []);
  const langs = useAsync(() => api.codingLanguages(), []);
  const [editing, setEditing] = useState(null);
  const [verifying, setVerifying] = useState(null);

  return (
    <>
      <PageHeader title="Assessments" subtitle="Create assessments with AI, review and publish them, and see your applicants' results." />
      <Tabs tabs={[['builder', 'AI assessments'], ['results', 'Candidate results'], ['bank', 'Coding problem bank']]} value={tab} onChange={setTab} />
      {tab === 'builder' ? <AssessmentBuilder /> : tab === 'results' ? (
        <Async state={apps} loadingLabel="Loading assessments…" errorLabel="Failed to load assessments">
          {(rows) => rows.length === 0 ? <EmptyState title="No applicants yet" /> : (
            <div className="card table-wrap">
              <table className="table">
                <thead><tr><th scope="col">Candidate</th><th scope="col">Role</th><th scope="col">Assessment</th><th scope="col">Completed</th><th scope="col">Test</th><th scope="col">Final</th><th scope="col"><span className="sr-only">Open</span></th></tr></thead>
                <tbody>
                  {rows.map((a) => (
                    <tr key={a.application_id}>
                      <td><b>{a.candidate_name}</b></td><td>{a.job_title}</td>
                      <td><span className={`pill ${a.assessment_status === 'completed' ? 'pill-ok' : a.assessment_status === 'in_progress' ? 'pill-warn' : 'pill-neutral'}`}>{ASSESSMENT_LABEL[a.assessment_status]}</span></td>
                      <td>{formatDate(a.assessment_completed_at, true)}</td>
                      <td className={`num tone-${scoreTone(a.test_score)}`}>{formatScore(a.test_score)}</td>
                      <td className={`num tone-${scoreTone(a.final_score)}`}><b>{formatScore(a.final_score)}</b></td>
                      <td><Link className="btn btn-secondary btn-sm" to={`/hr/candidate/${a.candidate_id}`}>View</Link></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Async>
      ) : (
        <>
          <div className="row" style={{ marginBottom: 12 }}>
            <p className="small muted" style={{ flex: 1 }}>
              Sandbox: {langs.data ? `${langs.data.sandbox.mode} mode · languages ${langs.data.languages.map((l) => l.label).join(', ') || 'none'}${langs.data.sandbox.production_ready ? '' : ' · use CODE_RUNNER=docker in production'}` : '…'}
            </p>
            <button className="btn btn-primary" onClick={() => setEditing({})}>+ New problem</button>
          </div>
          <Async state={problems} loadingLabel="Loading problems…" errorLabel="Failed to load problems">
            {(rows) => (
              <div className="card table-wrap">
                <table className="table" style={{ minWidth: 700 }}>
                  <thead><tr><th scope="col">Problem</th><th scope="col">Difficulty</th><th scope="col">Tags</th><th scope="col">Tests</th><th scope="col">Source</th><th scope="col"><span className="sr-only">Actions</span></th></tr></thead>
                  <tbody>
                    {rows.map((p) => (
                      <tr key={p.problem_id}>
                        <td><b>{p.title}</b>{!p.active && <span className="pill pill-neutral" style={{ marginLeft: 6 }}>Inactive</span>}</td>
                        <td>{p.difficulty}</td><td className="small">{p.tags}</td>
                        <td>{p.visible_tests.length} sample · {p.hidden_test_count} hidden</td>
                        <td>{p.library ? 'Hirelune library' : 'Your company'}</td>
                        <td><div className="row" style={{ flexWrap: 'nowrap' }}>
                          {p.editable && <button className="btn btn-secondary btn-sm" onClick={() => setEditing(p)}>Edit</button>}
                          <button className="btn btn-secondary btn-sm" onClick={() => setVerifying(p)}>Verify</button>
                        </div></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </Async>
        </>
      )}
      {editing && <ProblemEditor problem={editing.problem_id ? editing : null} onClose={() => setEditing(null)} onSaved={() => { setEditing(null); problems.reload(); toast('Problem saved', 'ok'); }} />}
      {verifying && <VerifyModal problem={verifying} onClose={() => setVerifying(null)} />}
    </>
  );
}
