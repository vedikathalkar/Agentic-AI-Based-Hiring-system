import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import { CircleCheck, Clock, LoaderCircle, Play, RotateCcw, Send, ShieldAlert } from 'lucide-react';
import { api } from '../../api';
import { useApp } from '../../context/AppContext';
import CodeEditor, { CodeRunResult } from '../../components/CodeEditor';
import { ErrorState, LoadingState, PageHeader } from '../../components/ui';
import ConfirmDialog from '../../components/ConfirmDialog';
import ProctorGate from '../../proctor/ProctorGate';
import ProctorSession from '../../proctor/ProctorSession';
import { formatScore, hasScore } from '../../utils/score';
import { formatDate } from '../../utils/status';

const fmtTime = (s) => `${String(Math.floor(s / 60)).padStart(2, '0')}:${String(s % 60).padStart(2, '0')}`;

const readDraft = (raw) => {
  if (!raw || typeof raw !== 'string' || !raw.trimStart().startsWith('{')) return null;
  try { const d = JSON.parse(raw); return d && typeof d.source === 'string' ? d : null; } catch { return null; }
};
// A coding question counts as answered once something was submitted or real code (not just the starter) was written.
const hasCode = (q, raw) => {
  if (q.coding?.last_submission) return true;
  const d = readDraft(raw);
  if (!d || !d.source.trim()) return false;
  const starter = (q.coding?.languages || []).find((l) => l.key === d.language)?.starter || '';
  return d.source.trim() !== starter.trim();
};

function CodingQuestion({ question, applicationId, locked, draft, onDraft }) {
  const c = question.coding;
  const langs = c.languages || [];
  const starter = (key) => langs.find((l) => l.key === key)?.starter || '';
  const saved = readDraft(draft);
  const fallbackLang = c.last_language || langs[0]?.key || 'python';
  const language = saved?.language && langs.some((l) => l.key === saved.language) ? saved.language : fallbackLang;
  const source = saved ? saved.source : (c.last_source || starter(language));
  const [busy, setBusy] = useState(null);
  const [result, setResult] = useState(c.last_submission ? { ...c.last_submission, kind: 'submit', tests: [] } : null);
  const [error, setError] = useState(null);
  const lastSubmitted = useRef(c.last_submission ? { language: c.last_submission.language } : null);

  const setCode = (next) => {
    if (next.language && next.language !== language) setResult(null);
    onDraft(JSON.stringify({ language: next.language ?? language, source: next.source ?? source }));
  };
  // In-page confirms: native dialogs can knock a proctored test out of full screen.
  const [ask, setAsk] = useState(null);
  const changeLanguage = (key) => {
    if (key === language) return;
    const apply = () => setCode({ language: key, source: starter(key) });
    if (source.trim() && source !== starter(language)) setAsk({ title: 'Switch language?', text: 'Your current code will be replaced by the starter template.', label: 'Switch', apply });
    else apply();
  };
  const resetCode = () => {
    const apply = () => setCode({ source: starter(language) });
    if (source !== starter(language)) setAsk({ title: 'Reset to the starter template?', text: 'Your current code will be lost.', label: 'Reset', apply });
    else apply();
  };
  const run = async (kind) => {
    if (busy || locked) return;
    if (!source.trim()) { setError('Write some code first.'); return; }
    setBusy(kind); setError(null);
    try {
      const payload = { application_id: Number(applicationId), question_index: question.index, language, source };
      const r = await (kind === 'run' ? api.runCode(payload) : api.submitCode(payload));
      setResult(r);
      if (kind === 'submit') lastSubmitted.current = { language, source };
    } catch (e) { setError(e.message); }
    finally { setBusy(null); }
  };
  const changedSinceSubmit = result?.kind === 'submit' && lastSubmitted.current?.source !== undefined && lastSubmitted.current.source !== source;

  if (c.missing) return <p className="alert alert-danger">This coding problem is no longer available.</p>;
  if (!langs.length) return <p className="alert alert-warn">No programming language runtime is available on the server right now. Contact support.</p>;
  return (
    <div className="coding-split">
      {ask && <ConfirmDialog title={ask.title} confirmLabel={ask.label} danger onCancel={() => setAsk(null)} onConfirm={() => { ask.apply(); setAsk(null); }}>{ask.text}</ConfirmDialog>}
      <div className="problem-pane">
        <h3 style={{ marginBottom: 8 }}>{c.title}</h3>
        <p style={{ whiteSpace: 'pre-wrap' }}>{c.statement}</p>
        {c.input_format && <><p className="section-title" style={{ margin: '14px 0 4px' }}>Input format</p><p className="small" style={{ whiteSpace: 'pre-wrap' }}>{c.input_format}</p></>}
        {c.output_format && <><p className="section-title" style={{ margin: '14px 0 4px' }}>Output format</p><p className="small" style={{ whiteSpace: 'pre-wrap' }}>{c.output_format}</p></>}
        {c.constraints && <><p className="section-title" style={{ margin: '14px 0 4px' }}>Constraints</p><pre className="pre">{c.constraints}</pre></>}
        {(c.examples || []).map((ex, i) => (
          <div key={i} style={{ marginTop: 12 }}>
            <p className="section-title" style={{ marginBottom: 4 }}>Example {i + 1}</p>
            <p className="small muted">Input</p><pre className="pre">{ex.input}</pre>
            <p className="small muted">Output</p><pre className="pre">{ex.output}</pre>
            {ex.explanation && <p className="small muted">{ex.explanation}</p>}
          </div>
        ))}
        <p className="small muted" style={{ marginTop: 12 }}>Time limit {c.time_limit_ms} ms · memory {c.memory_limit_mb} MB · {c.sample_tests?.length || 0} sample + {c.hidden_test_count} hidden tests. Read from standard input, print to standard output.</p>
      </div>
      <div style={{ minWidth: 0 }}>
        <div className="code-toolbar">
          <label className="sr-only" htmlFor={`lang-${question.index}`}>Language</label>
          <select id={`lang-${question.index}`} className="input input-sm" style={{ width: 128 }} value={language} onChange={(e) => changeLanguage(e.target.value)} disabled={locked || !!busy}>
            {langs.map((l) => <option key={l.key} value={l.key}>{l.label}</option>)}
          </select>
          <button type="button" className="icon-btn" onClick={resetCode} disabled={locked || !!busy} title="Reset to starter template" aria-label="Reset to starter template"><RotateCcw size={15} aria-hidden="true" /></button>
          <span className="spacer" />
          <button className="btn btn-secondary btn-sm" onClick={() => run('run')} disabled={!!busy || locked}><Play size={14} aria-hidden="true" /> {busy === 'run' ? 'Running…' : 'Run Code'}</button>
          <button className="btn btn-primary btn-sm" onClick={() => run('submit')} disabled={!!busy || locked}><Send size={14} aria-hidden="true" /> {busy === 'submit' ? 'Submitting…' : 'Submit Code'}</button>
        </div>
        <CodeEditor value={source} onChange={(s) => setCode({ source: s })} language={language} label={`Code for ${c.title}`} readOnly={locked} onRun={() => run('run')} />
        <p className="small muted" style={{ marginTop: 6 }}>Your code is saved automatically. <b>Run Code</b> checks the sample tests; <b>Submit Code</b> also runs the hidden tests. If time runs out, your latest code is graded.</p>
        {error && <p className="alert alert-danger small" role="alert" style={{ marginTop: 10 }}>{error}</p>}
        {changedSinceSubmit && <p className="alert alert-warn small" style={{ marginTop: 10 }}>You've edited the code since your last submission — submit again (or it will be graded automatically when you finish).</p>}
        <CodeRunResult result={result} title={result?.kind === 'submit' ? 'Submission' : 'Sample run'} />
        {result?.kind === 'submit' && result.score !== null && result.score !== undefined && <p className="small" style={{ marginTop: 6 }}>Score for this question: <b>{formatScore(result.score)}</b> (your latest submission is what counts)</p>}
      </div>
    </div>
  );
}

export default function Assessment() {
  const navigate = useNavigate();
  const { refreshMe } = useApp();
  const [params] = useSearchParams();
  const applicationId = params.get('application') || localStorage.getItem('hirelune_application_id');

  const [status, setStatus] = useState(null);
  const [assessment, setAssessment] = useState(null);
  const [answers, setAnswers] = useState({});
  const [step, setStep] = useState(0);
  const [left, setLeft] = useState(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState(null);
  const [starting, setStarting] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState(null);
  const [review, setReview] = useState(null);
  const submittedRef = useRef(false);
  const deadlineRef = useRef(null);
  const saveTimer = useRef(null);
  // proctoring: the engine owns the camera/microphone; it is created by the gate and handed over here
  const [engine, setEngine] = useState(null);
  const [resumedViaGate, setResumedViaGate] = useState(false);
  const [confirming, setConfirming] = useState(null);       // { unanswered } while the submit dialog is open
  const answersRef = useRef({});

  const refreshStatus = useCallback(async () => {
    const s = await api.getAssessmentStatus(applicationId);
    setStatus(s);
    return s;
  }, [applicationId]);

  const loadQuestions = useCallback((data) => {
    setAssessment(data);
    setAnswers(Object.fromEntries(Object.entries(data.draft_answers || {}).map(([k, v]) => [Number(k), v])));
    // The server computed the remaining time; anchor it to this client's clock.
    if (data.remaining_seconds !== null && data.remaining_seconds !== undefined) {
      deadlineRef.current = Date.now() + data.remaining_seconds * 1000;
      setLeft(data.remaining_seconds);
    }
  }, []);

  const load = useCallback(async () => {
    if (!applicationId) { setLoading(false); setLoadError(new Error('No application selected. Open an application from My Applications.')); return; }
    setLoading(true); setLoadError(null);
    try {
      const s = await refreshStatus();
      if (s.status === 'in_progress') loadQuestions(await api.getAssessment(applicationId));
    } catch (e) { setLoadError(e); }
    finally { setLoading(false); }
  }, [applicationId, refreshStatus, loadQuestions]);

  useEffect(() => { load(); }, [load]);

  const questions = useMemo(() => assessment?.questions || [], [assessment]);
  answersRef.current = answers;

  const askSubmit = () => {
    const unanswered = questions.filter((q, i) => (q.type === 'coding' ? !hasCode(q, answers[i]) : !(answers[i] || '').trim())).length;
    setConfirming({ unanswered });
  };

  const submit = useCallback(async () => {
    if (submittedRef.current) return;
    setConfirming(null);
    submittedRef.current = true;
    setSubmitting(true); setError(null);
    try {
      const payload = questions.map((q, index) => ({ index, user_answer: answers[index] || '' }));
      await api.submitAssessment(applicationId, payload);
      await refreshStatus();
      refreshMe();
    } catch (err) {
      if (err.status === 409) await refreshStatus();
      else submittedRef.current = false;
      setError(err.message);
    } finally { setSubmitting(false); }
  }, [answers, applicationId, questions, refreshStatus, refreshMe]);


  // Countdown driven by the server deadline; auto-submits at zero.
  useEffect(() => {
    if (status?.status !== 'in_progress' || !assessment || !deadlineRef.current) return undefined;
    const id = setInterval(() => {
      const s = Math.max(0, Math.round((deadlineRef.current - Date.now()) / 1000));
      setLeft(s);
      if (s === 0) { clearInterval(id); submit(); }
    }, 1000);
    return () => clearInterval(id);
  }, [status, assessment, submit]);

  const persist = useCallback((next) => {
    clearTimeout(saveTimer.current);
    saveTimer.current = setTimeout(() => {
      api.saveAssessmentProgress(applicationId, Object.fromEntries(Object.entries(next).map(([k, v]) => [String(k), v])))
        .catch((e) => { if (e.status === 409) refreshStatus(); });
    }, 800);
  }, [applicationId, refreshStatus]);

  const setAnswer = (value) => setAnswers((a) => { const next = { ...a, [step]: value }; persist(next); return next; });

  const start = async (proctoring, eng) => {
    setStarting(true); setError(null);
    try {
      loadQuestions(await api.startAssessment(applicationId, { proctoring }));
      if (eng) setEngine(eng);
      setStep(0); await refreshStatus(); refreshMe();
    } catch (e) { setError(`Couldn't start the assessment: ${e.message}`); }
    finally { setStarting(false); }
  };

  // Release the camera and microphone as soon as the attempt is over, however it ended.
  const finished = status?.status === 'completed';
  useEffect(() => { if (finished && engine) { engine.stop(); setEngine(null); } }, [finished, engine]);
  useEffect(() => () => { engine?.stop(); }, [engine]);

  const onProctorEnded = async () => {
    setEngine(null);
    try { await refreshStatus(); refreshMe(); } catch { /* the status poll will pick it up */ }
  };

  const loadReview = async () => {
    if (review) { setReview(null); return; }
    try { setReview(await api.getCandidateAssessment(status.candidate_id)); } catch (e) { setError(e.message); }
  };

  if (loading) return <LoadingState label="Loading assessment…" />;
  if (loadError) return <ErrorState error={loadError} onRetry={load} label="Assessment unavailable" />;

  // ---- COMPLETED
  if (status.status === 'completed') {
    return (
      <div>
        <div className="card" style={{ padding: 32 }}>
          <p className="row" style={{ color: 'var(--ok)', fontWeight: 600, fontSize: 18 }}><CircleCheck size={22} aria-hidden="true" /> Assessment completed ✓</p>
          {status.job_title && <p className="muted small" style={{ marginTop: 4 }}>{status.job_title}</p>}
          <dl className="kv" style={{ marginTop: 18, fontSize: 15 }}>
            <dt>Test Score</dt><dd><b>{formatScore(status.test_score)}</b></dd>
            <dt>Completed</dt><dd>{formatDate(status.completed_at, true)}{status.auto_submitted ? ' (submitted automatically when time ran out)' : ''}</dd>
            <dt>Final Score</dt><dd>{hasScore(status.final_score) ? <b>{formatScore(status.final_score)}</b> : <span className="muted">— (being finalised by the hiring team)</span>}</dd>
          </dl>
          {status.integrity === 'terminated' && (
            <p className="alert alert-warn" role="status" style={{ marginTop: 14, display: 'flex', gap: 8 }}><ShieldAlert size={18} aria-hidden="true" /> This assessment was ended automatically after {status.strikes} proctoring strikes. Only the answers saved up to that point were graded.</p>
          )}
          {status.integrity === 'flagged' && (
            <p className="alert alert-info small" role="status" style={{ marginTop: 14 }}>{status.strikes} proctoring warning(s) were recorded during this attempt and shared with the hiring team.</p>
          )}
          {error && <p className="alert alert-danger" role="alert" style={{ marginTop: 14 }}>{error}</p>}
          <div className="row" style={{ marginTop: 22 }}>
            <button className="btn btn-primary" onClick={loadReview} aria-expanded={!!review}>{review ? 'Hide Results' : 'View Results'}</button>
            <Link className="btn btn-secondary" to="/applications">My Applications</Link>
            <Link className="btn btn-secondary" to="/applications">See where I stand</Link>
          </div>
        </div>
        {review && (
          <div className="card" style={{ padding: 24, marginTop: 16 }}>
            <h3 style={{ marginBottom: 12 }}>Your answers</h3>
            {review.questions.map((q) => (
              <div key={q.index} className="qa">
                <div className="row small muted"><b style={{ color: 'var(--ink-950)' }}>Question {q.index + 1}</b>{q.skill && <span className="pill pill-brand">{q.skill}</span>}<span className="spacer" />{q.correct !== null && q.correct !== undefined && <span className={`pill ${q.correct ? 'pill-ok' : 'pill-danger'}`}>{q.correct ? 'Correct' : 'Incorrect'}</span>}</div>
                <p style={{ fontWeight: 500, marginTop: 4 }}>{q.question}</p>
                {q.type === 'coding' && q.coding
                  ? <p className="small" style={{ marginTop: 6 }}>{q.coding.passed} / {q.coding.total} test cases passed ({q.coding.language || 'not submitted'})</p>
                  : <p className="small" style={{ marginTop: 6 }}>Your answer: {q.candidate_answer || <span className="muted">No answer</span>}</p>}
                {q.feedback && <p className="small muted">{q.feedback}</p>}
              </div>
            ))}
          </div>
        )}
      </div>
    );
  }

  // ---- NOT STARTED
  if (status.status === 'not_started' && status.proctoring_enabled) {
    return (
      <ProctorGate mode="start" title={status.job_title ? `${status.job_title} assessment` : 'Assessment'} minutes={status.time_limit_minutes}
                   codingQuestions={status.coding_questions} maxStrikes={status.max_strikes} busy={starting} error={error}
                   onReady={(eng, proctoring) => start(proctoring, eng)} onCancel={() => navigate('/applications')} />
    );
  }
  if (status.status === 'not_started') {
    return (
      <div className="card" style={{ padding: 32 }}>
        <p className="eyebrow">Assessment</p>
        <h1 style={{ marginTop: 8 }}>Assessment ready</h1>
        {status.job_title && <p className="muted" style={{ marginTop: 6 }}>{status.job_title}</p>}
        <ul style={{ marginTop: 16, paddingLeft: 18, lineHeight: 1.8, fontSize: 14 }}>
          <li>Questions are generated from the job's required skills{status.coding_questions ? `, plus ${status.coding_questions} coding problem${status.coding_questions > 1 ? 's' : ''}` : ''}.</li>
          <li>Time limit: <b>{status.time_limit_minutes || 30} minutes</b>, counted by our server from the moment you start.</li>
          <li>Answers are saved as you go. If you leave, you can continue until time runs out — then saved answers are submitted automatically.</li>
          <li>You can submit only once. You'll get an email confirming the start.</li>
        </ul>
        {error && <p className="alert alert-danger" role="alert" style={{ marginTop: 14 }}>{error}</p>}
        <button className="btn btn-primary" style={{ marginTop: 20 }} onClick={() => start()} disabled={starting}>
          {starting ? <><LoaderCircle size={16} className="spin" aria-hidden="true" /> Generating your assessment…</> : 'Take Assessment'}
        </button>
      </div>
    );
  }

  // ---- IN PROGRESS
  if (status.status === 'in_progress' && status.proctored && !engine) {
    // Came back (refresh / new tab): re-confirm camera and microphone before the questions are shown again.
    return (
      <ProctorGate mode="resume" title={status.job_title} minutes={status.time_limit_minutes} maxStrikes={status.max_strikes}
                   onReady={(eng) => { setResumedViaGate(true); setEngine(eng); }} />
    );
  }
  const question = questions[step];
  if (!question) return <ErrorState error={error || 'Could not load the assessment questions.'} onRetry={load} />;
  const answer = answers[step] || '';
  const codingDone = (q, i) => hasCode(q, answers[i]);
  const answered = questions.filter((q, i) => q.type === 'coding' ? codingDone(q, i) : (answers[i] || '').trim()).length;
  const timeUp = left === 0;
  const lowTime = left !== null && left <= 120;

  const page = (
    <>
      {confirming && (
        <ConfirmDialog title="Submit your assessment?" confirmLabel="Submit" busy={submitting} onCancel={() => setConfirming(null)} onConfirm={submit}>
          {confirming.unanswered ? <>You have <b>{confirming.unanswered}</b> unanswered question{confirming.unanswered > 1 ? 's' : ''}. Submit anyway?</> : 'Everything is answered.'} You can't change answers after submitting.
        </ConfirmDialog>
      )}
      <PageHeader title="Assessment" subtitle={status.job_title}
                  actions={<span className={`chip-btn${lowTime ? ' tone-danger' : ''}`} role="timer" aria-live={lowTime ? 'assertive' : 'off'} aria-label={`Time remaining ${left === null ? '' : fmtTime(left)}`}><Clock size={15} aria-hidden="true" /> {left === null ? '--:--' : fmtTime(left)}</span>} />
      {timeUp && <p className="alert alert-warn" role="alert">Time is up — submitting your saved answers…</p>}
      <div style={{ display: 'flex', gap: 20, alignItems: 'flex-start', flexWrap: 'wrap' }}>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 10, width: 210, flexShrink: 0 }}>
          <div className="card" style={{ padding: 14, background: 'var(--side)', borderColor: 'var(--side)' }}>
            <p style={{ fontSize: 11, color: 'var(--side-muted)' }}>Progress</p>
            <p style={{ fontSize: 14, fontWeight: 500, color: '#fff', marginTop: 2 }}>{answered} of {questions.length} answered</p>
          </div>
          <nav className="card" style={{ padding: 14 }} aria-label="Questions">
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 6 }}>
              {questions.map((q, i) => {
                const done = q.type === 'coding' ? codingDone(q, i) : (answers[i] || '').trim();
                return (
                  <button key={i} type="button" onClick={() => setStep(i)} aria-current={i === step ? 'step' : undefined}
                          aria-label={`Question ${i + 1}${q.type === 'coding' ? ' (coding)' : ''}${done ? ', answered' : ''}`}
                          style={{ padding: '6px 0', borderRadius: 6, border: `1px solid ${i === step ? 'var(--brand)' : 'var(--ink-100)'}`, background: done ? 'var(--brand-t)' : 'var(--white)', color: 'var(--ink-950)', fontSize: 12 }}>
                    {q.type === 'coding' ? '</>' : i + 1}
                  </button>
                );
              })}
            </div>
          </nav>
        </div>
        <div style={{ flex: 1, minWidth: 280 }}>
          <p className="eyebrow" style={{ marginBottom: 10 }}>Question {step + 1} of {questions.length} · {question.type === 'coding' ? 'Coding' : question.difficulty}{question.skill && question.skill.toLowerCase() !== 'coding' ? ` · ${question.skill}` : ''}</p>
          <div className="card" style={{ padding: 24 }}>
            {question.type === 'coding' ? (
              <CodingQuestion key={question.index} question={question} applicationId={applicationId} locked={timeUp || submitting}
                              draft={answers[step]} onDraft={setAnswer} />
            ) : (
              <fieldset style={{ border: 0, margin: 0, padding: 0 }}>
                <legend style={{ fontFamily: 'var(--font-display)', fontSize: 18, fontWeight: 600, marginBottom: 18, lineHeight: 1.5 }}>{question.question}</legend>
                {question.type === 'mcq' ? (
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
                    {question.options?.map((opt) => {
                      const selected = answer === opt.label;
                      return (
                        <label key={opt.label} style={{ display: 'flex', alignItems: 'flex-start', gap: 10, padding: '13px 14px', borderRadius: 'var(--radius-sm)', border: `1px solid ${selected ? 'var(--brand)' : 'var(--ink-100)'}`, background: selected ? 'var(--brand-t)' : 'transparent', cursor: 'pointer', fontSize: 14 }}>
                          <input type="radio" name={`q-${step}`} checked={selected} disabled={timeUp} onChange={() => setAnswer(opt.label)} style={{ marginTop: 3 }} />
                          <span><b style={{ marginRight: 8 }}>{opt.label}.</b>{opt.text}</span>
                        </label>
                      );
                    })}
                  </div>
                ) : (
                  <><label className="sr-only" htmlFor={`sa-${step}`}>Your answer</label>
                    <textarea id={`sa-${step}`} className="input" rows={7} placeholder="Write your answer here…" value={answer} disabled={timeUp} onChange={(e) => setAnswer(e.target.value)} /></>
                )}
              </fieldset>
            )}
          </div>
          {error && <p className="alert alert-danger" role="alert" style={{ marginTop: 14 }}>{error}</p>}
          <div className="row" style={{ justifyContent: 'space-between', marginTop: 18 }}>
            <button className="btn btn-secondary" disabled={step === 0} onClick={() => setStep((s) => Math.max(0, s - 1))}>Previous</button>
            <div className="row">
              {step < questions.length - 1 && <button className="btn btn-secondary" onClick={() => setStep(step + 1)}>Next</button>}
              <button className="btn btn-primary" disabled={submitting || timeUp} onClick={askSubmit}>
                {submitting ? <><LoaderCircle size={16} className="spin" aria-hidden="true" /> Submitting…</> : 'Submit Assessment'}
              </button>
            </div>
          </div>
          <p className="small muted" style={{ marginTop: 10 }}>Answers save automatically.{!status.proctored && <> <button className="link-btn" onClick={() => navigate('/assessments')}>Leave and continue later</button></>}</p>
        </div>
      </div>
    </>
  );

  if (!engine) return page;
  return (
    <ProctorSession engine={engine} applicationId={applicationId} maxStrikes={status.max_strikes} initialStrikes={status.strikes}
                    resumed={resumedViaGate} getAnswers={() => Object.fromEntries(Object.entries(answersRef.current).map(([k, v]) => [String(k), v]))}
                    onEnded={onProctorEnded}>
      {page}
    </ProctorSession>
  );
}
