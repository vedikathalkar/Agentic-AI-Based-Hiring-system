import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { Brain, CircleCheck, Clock, CodeXml, Keyboard, Mic, Play, RotateCcw, SkipForward, Sparkles, Square, Volume2 } from 'lucide-react';
import { api } from '../../api';
import { useApp } from '../../context/AppContext';
import CodeEditor, { CodeRunResult } from '../../components/CodeEditor';
import { Async, ErrorState, LoadingState, PageHeader, useAsync } from '../../components/ui';
import { HistoryList, RolePicker, ScoreBars, ScoreRing, Segmented, TimerRing, fmtClock, useCountdown } from '../../components/Practice';

const THINK_SECONDS = 15;
const LIMITS = { concept: [60, 90, 120], explain: [120, 180, 240], behavioural: [120, 180, 180], scenario: [240, 360, 480], coding: [480, 720, 900] };
const DIFF = ['easy', 'medium', 'hard'];
const SpeechRec = typeof window !== 'undefined' ? (window.SpeechRecognition || window.webkitSpeechRecognition) : null;

// ---------------------------------------------------------------- setup

function Setup() {
  const navigate = useNavigate();
  const roles = useAsync(() => api.practiceRoles(), []);
  const history = useAsync(() => api.mockInterviews(), []);
  const [role, setRole] = useState({ job_id: null, role_title: '', skills: [] });
  const [cfg, setCfg] = useState({ interview_type: 'mixed', difficulty: 'medium', num_questions: 5, mode: 'interview', total_limit_minutes: '' });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const set = (k) => (v) => setCfg((c) => ({ ...c, [k]: v }));

  const start = async () => {
    setBusy(true); setError(null);
    try {
      const iv = await api.createMockInterview({ ...role, ...cfg, total_limit_minutes: cfg.total_limit_minutes ? Number(cfg.total_limit_minutes) : null });
      navigate(`/mock-interview/${iv.interview_id}`);
    } catch (e) { setError(e.message); setBusy(false); }
  };
  // Rough plan preview using the same time table as the interviewer agent.
  const d = DIFF.indexOf(cfg.difficulty);
  const n = cfg.num_questions;
  const types = cfg.interview_type === 'behavioural' ? Array(n).fill('behavioural')
    : cfg.interview_type === 'technical' ? Array.from({ length: n }, (_, i) => ['concept', 'explain', 'scenario'][i % 3])
      : Array.from({ length: n }, (_, i) => (i % 3 === 1 ? 'behavioural' : ['concept', 'explain', 'scenario'][i % 3]));
  if (cfg.interview_type !== 'behavioural' && n >= (cfg.interview_type === 'technical' ? 4 : 5) && roles.data?.code_languages?.length) types[n - 2] = 'coding';
  const estimate = Math.round(types.reduce((a, t) => a + LIMITS[t][d], 0) / 60);
  const ready = (role.job_id || role.role_title.trim()) && role.skills.length > 0;

  return (
    <>
      <PageHeader eyebrow="Practice zone" title="AI mock interview"
                  subtitle="Rehearse with an AI interviewer that adapts to your answers. Practice results are private — employers never see them." />
      <div className="practice-layout">
        <section className="card section" style={{ marginTop: 0 }}>
          <h3 className="row" style={{ marginBottom: 12 }}><Brain size={18} aria-hidden="true" /> Set up your interview</h3>
          <Async state={roles} loadingLabel="Loading roles…">{(r) => <RolePicker roles={r} value={role} onChange={setRole} />}</Async>
          <div className="setup-grid">
            <Segmented id="mi-type" label="Interview type" value={cfg.interview_type} onChange={set('interview_type')}
                       options={[['technical', 'Technical'], ['mixed', 'Mixed'], ['behavioural', 'Behavioural']]} />
            <Segmented id="mi-diff" label="Difficulty" value={cfg.difficulty} onChange={set('difficulty')}
                       options={[['easy', 'Easy'], ['medium', 'Medium'], ['hard', 'Hard']]} />
            <div className="field">
              <label className="field-label" htmlFor="mi-n">Questions: <b>{cfg.num_questions}</b></label>
              <input id="mi-n" type="range" min={3} max={8} value={cfg.num_questions} onChange={(e) => set('num_questions')(Number(e.target.value))} className="range" />
            </div>
            <div className="field">
              <label className="field-label" htmlFor="mi-total">Overall time limit</label>
              <select id="mi-total" className="input" value={cfg.total_limit_minutes} onChange={(e) => set('total_limit_minutes')(e.target.value)}>
                <option value="">No overall limit</option>{[15, 20, 30, 45, 60].map((m) => <option key={m} value={m}>{m} minutes</option>)}
              </select>
            </div>
          </div>
          <div className="mode-cards" role="radiogroup" aria-label="Mode">
            {[['interview', 'Interview mode', 'Strict per-question limits. When time runs out your answer is submitted automatically.'],
              ['practice', 'Practice mode', 'Timers are shown but not enforced — you see how far you went over.']].map(([k, t, d2]) => (
              <button key={k} type="button" role="radio" aria-checked={cfg.mode === k} className={`mode-card${cfg.mode === k ? ' on' : ''}`} onClick={() => set('mode')(k)}>
                <b>{t}</b><span className="small muted">{d2}</span>
              </button>
            ))}
          </div>
          {error && <p className="alert alert-danger small" role="alert">{error}</p>}
          <div className="row" style={{ marginTop: 14 }}>
            <span className="small muted"><Clock size={13} aria-hidden="true" style={{ verticalAlign: -2 }} /> About {estimate} min · {n} questions{roles.data && !roles.data.ai_available ? ' · offline interviewer' : ' · AI interviewer'}</span>
            <span className="spacer" />
            <button className="btn btn-primary" disabled={!ready || busy} onClick={start}><Play size={15} aria-hidden="true" /> {busy ? 'Preparing questions…' : 'Start interview'}</button>
          </div>
        </section>

        <aside className="practice-side">
          <section className="card section" style={{ marginTop: 0 }}>
            <p className="section-title">How it works</p>
            <ol className="steps-list">
              <li><b>Read</b> — {THINK_SECONDS} seconds to think before the clock starts.</li>
              <li><b>Answer</b> by <Mic size={13} aria-hidden="true" /> speaking, <Keyboard size={13} aria-hidden="true" /> typing or <CodeXml size={13} aria-hidden="true" /> coding.</li>
              <li><b>Adapt</b> — vague answers get a follow-up question, like a real interviewer.</li>
              <li><b>Review</b> — score, key points you missed and a study plan.</li>
            </ol>
            <p className="small muted" style={{ marginTop: 8 }}>{SpeechRec ? 'Voice answers work in this browser. Audio is never stored — only the transcript.' : 'Voice answers need Chrome or Edge; you can type instead.'}</p>
          </section>
          <section className="card section">
            <p className="section-title">Your mock interviews</p>
            <Async state={history} loadingLabel="Loading…">
              {(rows) => <HistoryList scoreKey="overall_score" empty="No mock interviews yet — your first one takes about 15 minutes."
                                      onOpen={(r) => navigate(`/mock-interview/${r.id}`)}
                                      rows={rows.map((r) => ({ ...r, id: r.interview_id, title: r.role_title, sub: `${r.config.interview_type} · ${r.config.difficulty} · ${new Date(r.created_at).toLocaleDateString()}` }))} />}
            </Async>
          </section>
        </aside>
      </div>
    </>
  );
}

// ---------------------------------------------------------------- room

function useSpeech(onText) {
  const rec = useRef(null);
  const [listening, setListening] = useState(false);
  const [interim, setInterim] = useState('');
  const started = useRef(null);
  const spoken = useRef(0);
  const stop = useCallback(() => {
    if (rec.current) { rec.current.onend = null; try { rec.current.stop(); } catch { /* already stopped */ } }
    if (started.current) { spoken.current += (Date.now() - started.current) / 1000; started.current = null; }
    setListening(false); setInterim('');
  }, []);
  const start = useCallback(() => {
    if (!SpeechRec) return;
    const r = new SpeechRec();
    r.continuous = true; r.interimResults = true; r.lang = navigator.language?.startsWith('en') ? navigator.language : 'en-IN';
    r.onresult = (e) => {
      let finalText = ''; let temp = '';
      for (let i = e.resultIndex; i < e.results.length; i += 1) {
        if (e.results[i].isFinal) finalText += e.results[i][0].transcript; else temp += e.results[i][0].transcript;
      }
      if (finalText) onText(finalText.trim());
      setInterim(temp);
    };
    r.onend = () => { try { r.start(); } catch { stop(); } };   // Chrome stops after silence; keep listening
    r.onerror = (e) => { if (e.error === 'not-allowed' || e.error === 'service-not-allowed') stop(); };
    rec.current = r; started.current = Date.now();
    try { r.start(); setListening(true); } catch { /* ignore */ }
  }, [onText, stop]);
  useEffect(() => () => stop(), [stop]);
  const takeSeconds = () => { const s = spoken.current + (started.current ? (Date.now() - started.current) / 1000 : 0); spoken.current = 0; return Math.round(s); };
  return { listening, interim, start, stop, takeSeconds, supported: !!SpeechRec };
}

const speak = (text) => {
  if (!window.speechSynthesis) return;
  window.speechSynthesis.cancel();
  const u = new window.SpeechSynthesisUtterance(text); u.rate = 1; u.lang = 'en-IN';
  window.speechSynthesis.speak(u);
};

function Feedback({ turn }) {
  const ev = turn.evaluation || {};
  const star = ev.star;
  return (
    <div className="feedback-card" aria-live="polite">
      <div className="row">
        <span className={`score-chip ${ev.score >= 7.5 ? 'ok' : ev.score >= 5 ? 'warn' : 'bad'}`}>{ev.score?.toFixed?.(1) ?? ev.score}<small>/10</small></span>
        <div style={{ flex: 1, minWidth: 0 }}>
          <b>{turn.kind === 'followup' ? 'Follow-up' : `Q${turn.slot + 1}`} · {turn.type_label}</b>
          <p className="small" style={{ marginTop: 2 }}>{ev.feedback}</p>
        </div>
      </div>
      {turn.answer && turn.qtype !== 'coding' && <blockquote className="answer-quote">{turn.answer.length > 420 ? `${turn.answer.slice(0, 420)}…` : turn.answer}</blockquote>}
      <div className="feedback-grid">
        {(turn.key_points || []).length > 0 && (
          <div>
            <p className="section-title" style={{ marginBottom: 6 }}>Key points</p>
            <ul className="check-list">{turn.key_points.map((p) => {
              const hit = (ev.covered || []).includes(p);
              return <li key={p} className={hit ? 'hit' : 'miss'}>{hit ? '✓' : '○'} {p}</li>;
            })}</ul>
          </div>
        )}
        <div>
          <p className="section-title" style={{ marginBottom: 6 }}>Details</p>
          <dl className="kv small">
            <dt>Time</dt><dd>{fmtClock(turn.time_used_s || 0)} of {fmtClock(turn.time_limit_s)}{turn.timed_out ? ' · time limit reached' : ''}{turn.overrun_s ? ` · ${turn.overrun_s}s over` : ''}</dd>
            <dt>Answered by</dt><dd>{turn.status === 'skipped' ? 'skipped' : turn.answer_mode}</dd>
            {turn.speech && <><dt>Speech</dt><dd>{turn.speech.wpm ? `${turn.speech.wpm} words/min · ` : ''}{turn.speech.filler_count || 0} filler word{turn.speech.filler_count === 1 ? '' : 's'}{turn.speech.filler_count ? ` (${Object.keys(turn.speech.fillers || {}).join(', ')})` : ''}</dd></>}
            {turn.code_result && <><dt>Tests</dt><dd>{turn.code_result.passed}/{turn.code_result.total} passed</dd></>}
            {star && <><dt>STAR</dt><dd>{['situation', 'task', 'action', 'result'].map((k) => <span key={k} className={`star-tag ${star[k] ? 'on' : ''}`}>{k[0].toUpperCase()}</span>)}</dd></>}
          </dl>
        </div>
      </div>
    </div>
  );
}

function CodingAnswer({ problem, source, setSource, language, setLanguage, interviewId, locked }) {
  const [result, setResult] = useState(null);
  const [busy, setBusy] = useState(false);
  const langs = problem?.languages || [];
  const starter = (key) => langs.find((l) => l.key === key)?.starter || '';
  const run = async () => {
    if (busy || locked) return;
    if (!source.trim()) { setResult({ error: 'Write some code first.', tests: [] }); return; }
    setBusy(true);
    try { setResult(await api.mockInterviewRunCode(interviewId, { language, source })); } catch (e) { setResult({ error: e.message, tests: [] }); }
    finally { setBusy(false); }
  };
  const changeLanguage = (key) => {
    if (key === language) return;
    if (source.trim() && source !== starter(language) && !window.confirm('Switch language? Your current code will be replaced by the starter template.')) return;
    setLanguage(key); setSource(starter(key)); setResult(null);
  };
  if (!problem) return <p className="alert alert-warn">This coding problem is unavailable — answer in words instead.</p>;
  if (!langs.length) return <p className="alert alert-warn">No programming language runtime is available on the server right now — explain your approach in words instead.</p>;
  return (
    <div className="code-answer">
      <details className="problem-box" open>
        <summary><b>{problem.title}</b></summary>
        <p className="small" style={{ whiteSpace: 'pre-wrap' }}>{problem.statement}</p>
        {problem.constraints && <pre className="pre small">{problem.constraints}</pre>}
        {(problem.examples || []).slice(0, 2).map((ex, i) => <pre key={i} className="pre small">{`Input:\n${ex.input}\nOutput:\n${ex.output}`}</pre>)}
      </details>
      <div className="code-toolbar" style={{ marginTop: 8 }}>
        <label className="sr-only" htmlFor="mi-lang">Language</label>
        <select id="mi-lang" className="input input-sm" style={{ width: 150 }} value={language} disabled={locked || busy}
                onChange={(e) => changeLanguage(e.target.value)}>
          {langs.map((l) => <option key={l.key} value={l.key}>{l.label}</option>)}
        </select>
        <span className="spacer" />
        <button className="btn btn-secondary btn-sm" disabled={busy || locked} onClick={run}><Play size={14} aria-hidden="true" /> {busy ? 'Running…' : 'Run sample tests'}</button>
      </div>
      <CodeEditor value={source} onChange={setSource} language={language} label="Your solution" readOnly={locked} onRun={run} minHeight={260} />
      <CodeRunResult result={result} title="Sample run" />
    </div>
  );
}

function Room({ iv, setIv }) {
  const { toast } = useApp();
  const turn = iv.turns.find((t) => t.index === iv.current_index);
  const answered = iv.turns.filter((t) => t.evaluation);
  const lastFeedback = answered[answered.length - 1];
  const [showFeedback, setShowFeedback] = useState(!!lastFeedback && turn?.status === 'pending' && answered.length > 0);
  const [mode, setMode] = useState(turn?.qtype === 'coding' ? 'code' : SpeechRec ? 'voice' : 'text');
  const [text, setText] = useState('');
  const [source, setSource] = useState('');
  const [language, setLanguage] = useState('python');
  const [busy, setBusy] = useState(false);
  const [think, setThink] = useState(null);       // deadline for the reading time
  const [deadline, setDeadline] = useState(null); // deadline for answering
  const warned = useRef(false);
  const speech = useSpeech(useCallback((t) => setText((v) => (v ? `${v} ${t}` : t)), []));
  const strict = iv.config.mode === 'interview';

  // New question → reset the answer area.
  useEffect(() => {
    if (!turn) return;
    setText(''); warned.current = false;
    setMode(turn.qtype === 'coding' ? 'code' : (SpeechRec ? 'voice' : 'text'));
    if (turn.qtype === 'coding') {
      const l = turn.problem?.languages?.[0]; setLanguage(l?.key || 'python'); setSource(l?.starter || '');
    }
    if (turn.status === 'active' && turn.remaining_s != null) { setThink(null); setDeadline(Date.now() + turn.remaining_s * 1000); }
    else { setDeadline(null); setThink(showFeedback ? null : Date.now() + THINK_SECONDS * 1000); }
  }, [turn?.index]); // eslint-disable-line react-hooks/exhaustive-deps

  const begin = useCallback(async () => {
    setThink(null);
    try {
      const next = await api.mockInterviewBegin(iv.interview_id);
      const t = next.turns.find((x) => x.index === next.current_index);
      setDeadline(Date.now() + (t?.remaining_s ?? turn.time_limit_s) * 1000);
      setIv(next);
      if (mode === 'voice' && speech.supported) speech.start();
    } catch (e) { toast(e.message, 'danger'); }
  }, [iv.interview_id, mode, setIv, speech, toast, turn]);

  const submit = useCallback(async ({ skipped = false, auto = false } = {}) => {
    if (busy || !turn) return;
    speech.stop();
    setBusy(true);
    const answer = mode === 'code' ? source : [text, speech.interim].filter(Boolean).join(' ').trim();
    try {
      const next = await api.mockInterviewAnswer(iv.interview_id, {
        answer: skipped ? '' : answer, answer_mode: mode, language, skipped, auto_submitted: auto,
        speaking_seconds: mode === 'voice' ? speech.takeSeconds() : null,
      });
      setDeadline(null); setShowFeedback(true); setIv(next);
      if (auto) toast('Time is up — your answer was submitted', 'info');
    } catch (e) { toast(e.message, 'danger'); }
    finally { setBusy(false); }
  }, [busy, turn, speech, mode, source, text, iv.interview_id, language, setIv, toast]);

  const thinkLeft = useCountdown(think, begin);
  const left = useCountdown(deadline, () => { if (strict) submit({ auto: true }); });
  useEffect(() => {
    if (left != null && left === 30 && !warned.current && turn?.time_limit_s > 60) {
      warned.current = true; toast('30 seconds left', 'info');
      if (mode === 'voice' && !speech.listening) speak('Thirty seconds left');
    }
  }, [left]); // eslint-disable-line react-hooks/exhaustive-deps

  const totalDeadline = useMemo(() => (iv.total_remaining_s != null ? Date.now() + iv.total_remaining_s * 1000 : null), [iv.total_remaining_s]);
  const totalLeft = useCountdown(totalDeadline, null);
  const finish = async () => {
    if (!window.confirm('End the interview now? Unanswered questions count as skipped.')) return;
    speech.stop();
    try { setIv(await api.mockInterviewFinish(iv.interview_id)); } catch (e) { toast(e.message, 'danger'); }
  };

  const mains = iv.plan || [];
  const scoreOf = (slot) => { const t = iv.turns.find((x) => x.slot === slot && x.kind === 'question'); return t?.evaluation?.score; };

  return (
    <div className="practice-layout room">
      <div style={{ minWidth: 0, display: 'grid', gap: 14 }}>
        {showFeedback && lastFeedback && (
          <section className="card section" style={{ marginTop: 0 }}>
            <Feedback turn={lastFeedback} />
            {turn && <div className="row" style={{ marginTop: 12 }}><span className="small muted">{turn.kind === 'followup' ? 'The interviewer has a follow-up question.' : 'Ready for the next question?'}</span><span className="spacer" />
              <button className="btn btn-primary" onClick={() => { setShowFeedback(false); setThink(Date.now() + THINK_SECONDS * 1000); }}>{turn.kind === 'followup' ? 'Answer follow-up' : 'Next question'} →</button></div>}
          </section>
        )}
        {turn && !showFeedback && (
          <section className="card section question-card" style={{ marginTop: 0 }}>
            <div className="row">
              <span className="pill pill-brand">{turn.kind === 'followup' ? `Follow-up to question ${turn.slot + 1}` : `Question ${turn.slot + 1} of ${mains.length}`}</span>
              {turn.kind !== 'followup' && <span className="pill pill-neutral">{turn.type_label}</span>}
              <span className="pill pill-neutral">{turn.topic}</span>
              <span className="small muted">{turn.difficulty} · limit {fmtClock(turn.time_limit_s)}</span>
              <span className="spacer" />
              {deadline ? <TimerRing left={left ?? turn.time_limit_s} total={turn.time_limit_s} /> : null}
            </div>
            <h2 className="question-text">{turn.question}</h2>
            <div className="row" style={{ gap: 6 }}>
              <button type="button" className="btn btn-secondary btn-sm" onClick={() => speak(turn.question)}><Volume2 size={14} aria-hidden="true" /> Read aloud</button>
              {!deadline && think && <span className="think-pill"><Clock size={13} aria-hidden="true" /> Thinking time {thinkLeft}s</span>}
              {!deadline && think && <button type="button" className="btn btn-primary btn-sm" onClick={begin}>Start answering now</button>}
              {!deadline && !think && <button type="button" className="btn btn-primary btn-sm" onClick={begin}>Start the clock</button>}
            </div>

            {deadline && (
              <div className="answer-area">
                {turn.qtype !== 'coding' && !speech.supported && <p className="small muted">Voice answers need Chrome or Edge — type your answer below.</p>}
                {turn.qtype !== 'coding' && speech.supported && (
                  <div className="seg seg-sm" role="radiogroup" aria-label="Answer by">
                    {<button type="button" role="radio" aria-checked={mode === 'voice'} className={mode === 'voice' ? 'on' : ''} onClick={() => setMode('voice')}><Mic size={13} aria-hidden="true" /> Speak</button>}
                    <button type="button" role="radio" aria-checked={mode === 'text'} className={mode === 'text' ? 'on' : ''} onClick={() => { speech.stop(); setMode('text'); }}><Keyboard size={13} aria-hidden="true" /> Type</button>
                  </div>
                )}
                {mode === 'code' ? (
                  <CodingAnswer problem={turn.problem} source={source} setSource={setSource} language={language} setLanguage={setLanguage} interviewId={iv.interview_id} locked={busy} />
                ) : (
                  <>
                    {mode === 'voice' && (
                      <div className={`mic-bar${speech.listening ? ' live' : ''}`}>
                        <span className="mic-dot" aria-hidden="true" />
                        <span className="small">{speech.listening ? 'Listening… speak naturally, then press Stop.' : 'Microphone is off.'}</span>
                        <span className="spacer" />
                        {speech.listening
                          ? <button type="button" className="btn btn-secondary btn-sm" onClick={speech.stop}><Square size={13} aria-hidden="true" /> Stop</button>
                          : <button type="button" className="btn btn-secondary btn-sm" onClick={speech.start}><Mic size={13} aria-hidden="true" /> {text ? 'Continue speaking' : 'Start speaking'}</button>}
                        {text && !speech.listening && <button type="button" className="btn btn-secondary btn-sm" onClick={() => setText('')}><RotateCcw size={13} aria-hidden="true" /> Clear</button>}
                      </div>
                    )}
                    <label className="sr-only" htmlFor="mi-answer">Your answer</label>
                    <textarea id="mi-answer" className="input answer-box" rows={7} value={speech.interim ? `${text} ${speech.interim}` : text}
                              placeholder={mode === 'voice' ? 'Your words appear here as you speak — you can fix any mistakes before submitting.' : 'Type your answer. Use a concrete example from your experience.'}
                              onChange={(e) => setText(e.target.value)} readOnly={speech.listening} />
                    <p className="small muted">{text.split(/\s+/).filter(Boolean).length} words{turn.qtype === 'behavioural' ? ' · structure it as Situation → Task → Action → Result' : ''}</p>
                  </>
                )}
                <div className="row" style={{ marginTop: 10 }}>
                  <button type="button" className="btn btn-secondary btn-sm" disabled={busy} onClick={() => submit({ skipped: true })}><SkipForward size={14} aria-hidden="true" /> Skip</button>
                  {!strict && left != null && left <= 0 && <span className="small tone-danger">Over the limit by {fmtClock(-left)}</span>}
                  <span className="spacer" />
                  <button type="button" className="btn btn-primary" disabled={busy || (mode !== 'code' && !text.trim() && !speech.interim)} onClick={() => submit()}>
                    {busy ? 'Evaluating…' : 'Submit answer'}
                  </button>
                </div>
              </div>
            )}
          </section>
        )}
      </div>

      <aside className="practice-side">
        <section className="card section" style={{ marginTop: 0 }}>
          <div className="row" style={{ marginBottom: 8 }}>
            <p className="section-title" style={{ margin: 0 }}>{iv.role_title}</p><span className="spacer" />
            {totalLeft != null && <span className={`pill ${totalLeft < 120 ? 'pill-danger' : 'pill-neutral'}`}><Clock size={12} aria-hidden="true" /> {fmtClock(Math.max(0, totalLeft))}</span>}
          </div>
          <p className="small muted" style={{ marginBottom: 10 }}>{iv.config.interview_type} · {iv.config.difficulty} · {strict ? 'interview mode' : 'practice mode'}</p>
          <ol className="plan-list">
            {mains.map((p) => {
              const s = scoreOf(p.slot);
              const active = turn && turn.slot === p.slot;
              return (
                <li key={p.slot} className={active ? 'active' : s != null ? 'done' : ''}>
                  <span className="plan-num">{s != null ? <CircleCheck size={14} aria-hidden="true" /> : p.slot + 1}</span>
                  <span className="plan-body"><b>{p.qtype === 'coding' ? 'Coding' : p.topic}</b><span className="small muted">{p.qtype === 'behavioural' ? 'behavioural competency' : `${p.qtype} · ${p.reason}`}</span></span>
                  {s != null && <span className="small"><b>{s}</b>/10</span>}
                </li>
              );
            })}
          </ol>
          <button type="button" className="btn btn-secondary btn-sm btn-block" style={{ marginTop: 12 }} onClick={finish}>End interview & see report</button>
        </section>
        {!showFeedback && lastFeedback && (
          <section className="card section">
            <p className="section-title">Previous answer</p>
            <p className="small"><b>{lastFeedback.evaluation?.score}/10</b> — {lastFeedback.evaluation?.feedback}</p>
          </section>
        )}
      </aside>
    </div>
  );
}

// ---------------------------------------------------------------- report

function Report({ iv }) {
  const navigate = useNavigate();
  const r = iv.report;
  const mains = iv.turns.filter((t) => t.evaluation);
  return (
    <div className="practice-layout">
      <div style={{ minWidth: 0, display: 'grid', gap: 14 }}>
        <section className="card section report-hero" style={{ marginTop: 0 }}>
          <ScoreRing value={r.overall_score} label="overall" />
          <div style={{ flex: 1, minWidth: 220 }}>
            <p className="eyebrow">{iv.role_title} · {iv.config.interview_type} · {iv.config.difficulty}</p>
            <h2 style={{ margin: '4px 0 6px' }}>Interview report</h2>
            <p className="small">{r.summary}</p>
            <div className="mini-stats" style={{ marginTop: 12 }}>
              <div><b>{r.answered}/{r.planned}</b><span>answered</span></div>
              <div><b>{r.skipped}</b><span>skipped</span></div>
              <div><b>{r.speaking?.wpm ?? '—'}</b><span>words/min</span></div>
              <div><b>{iv.engine === 'ai' ? 'AI' : 'Offline'}</b><span>interviewer</span></div>
            </div>
          </div>
        </section>
        <div className="grid grid-2">
          <section className="card section" style={{ marginTop: 0 }}>
            <p className="section-title">Competencies</p>
            <ScoreBars items={r.competencies} />
          </section>
          <section className="card section" style={{ marginTop: 0 }}>
            <p className="section-title">Strengths</p>
            <ul className="tick-list ok">{r.strengths.map((s) => <li key={s}>{s}</li>)}</ul>
            <p className="section-title" style={{ marginTop: 14 }}>To improve</p>
            <ul className="tick-list warn">{r.improvements.map((s) => <li key={s}>{s}</li>)}</ul>
          </section>
        </div>
        <section className="card section" style={{ marginTop: 0 }}>
          <p className="section-title">Question by question</p>
          <div className="review-list">
            {mains.map((t) => (
              <details key={t.index} className="review-item">
                <summary>
                  <span className={`score-chip ${t.evaluation.score >= 7.5 ? 'ok' : t.evaluation.score >= 5 ? 'warn' : 'bad'}`}>{t.evaluation.score}<small>/10</small></span>
                  <span className="review-q"><b>{t.kind === 'followup' ? 'Follow-up' : `Q${t.slot + 1}`}</b> {t.question}</span>
                  <span className="small muted">{fmtClock(t.time_used_s || 0)}/{fmtClock(t.time_limit_s)}</span>
                </summary>
                <div className="review-body">
                  {t.answer && t.qtype === 'coding' && <pre className="pre small">{t.answer}</pre>}
                  <Feedback turn={t} />
                </div>
              </details>
            ))}
          </div>
        </section>
      </div>
      <aside className="practice-side">
        <section className="card section" style={{ marginTop: 0 }}>
          <p className="section-title">Time management</p>
          <ul className="tick-list">{r.time_notes.map((n) => <li key={n}>{n}</li>)}</ul>
          {r.speaking && <p className="small" style={{ marginTop: 8 }}><b>Speaking:</b> {r.speaking.wpm} words/min, {r.speaking.fillers} filler words. {r.speaking.note}</p>}
          <p className="small muted" style={{ marginTop: 8 }}>Time isn't part of your score.</p>
        </section>
        <section className="card section">
          <p className="section-title">Study plan</p>
          <div className="chips">{(r.study_topics.length ? r.study_topics : ['Keep practising at the next difficulty']).map((s) => <span key={s} className="chip">{s}</span>)}</div>
        </section>
        <section className="card section">
          <p className="section-title">Next steps</p>
          <div style={{ display: 'grid', gap: 8 }}>
            <button className="btn btn-primary btn-block" onClick={() => navigate('/mock-interview')}><RotateCcw size={14} aria-hidden="true" /> Practise again</button>
            <Link className="btn btn-secondary btn-block" to="/mock-assessment"><Sparkles size={14} aria-hidden="true" /> Take a mock assessment</Link>
          </div>
        </section>
      </aside>
    </div>
  );
}

// ---------------------------------------------------------------- page

function Session({ id }) {
  const [iv, setIv] = useState(null);
  const [error, setError] = useState(null);
  useEffect(() => { api.mockInterview(id).then(setIv).catch(setError); }, [id]);
  if (error) return <ErrorState error={error} label="Couldn't load this mock interview" />;
  if (!iv) return <LoadingState label="Loading interview…" />;
  return (
    <>
      <PageHeader eyebrow="Practice zone · private to you" title={iv.status === 'completed' ? 'Mock interview report' : 'Mock interview'}
                  actions={<Link className="btn btn-secondary btn-sm" to="/mock-interview">All mock interviews</Link>} />
      {iv.status === 'completed' ? <Report iv={iv} /> : <Room iv={iv} setIv={setIv} />}
    </>
  );
}

export default function MockInterview() {
  const { id } = useParams();
  return id ? <Session key={id} id={id} /> : <Setup />;
}
