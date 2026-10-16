import { useCallback, useEffect, useRef, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { FileText, Download, ClipboardList, Check, X, Lock, CalendarClock, Award } from 'lucide-react';
import HiringPipeline from '../../components/HiringPipeline';
import DecisionDialog from '../../components/DecisionDialog';
import IntegrityReport from '../../components/IntegrityReport';
import ScoreCard from '../../components/ScoreCard';
import StatusBadge from '../../components/StatusBadge';
import { api } from '../../api';
import { useApp } from '../../context/AppContext';
import { formatScore, hasScore } from '../../utils/score';
import { ASSESSMENT_LABEL, applicationStageLabel, formatDate, splitList } from '../../utils/status';

function Section({ title, id, children, action }) {
  return (
    <section className="card section" id={id} aria-labelledby={`${id}-title`}>
      <div className="row" style={{ marginBottom: 12 }}>
        <h2 id={`${id}-title`} style={{ fontSize: 17 }}>{title}</h2>
        <span className="spacer" />
        {action}
      </div>
      {children}
    </section>
  );
}

function Chips({ items, kind, empty, icon }) {
  if (!items.length) return <p className="muted small">{empty}</p>;
  return (
    <ul className="chips" style={{ listStyle: 'none', margin: 0, padding: 0 }}>
      {items.map((s, i) => (
        <li key={`${s}-${i}`} className={`chip ${kind ? `chip-${kind}` : ''}`}>
          {icon === 'ok' && <Check size={13} aria-hidden="true" />}
          {icon === 'missing' && <X size={13} aria-hidden="true" />}
          <span>{icon === 'ok' ? <span className="sr-only">Matched: </span> : icon === 'missing' ? <span className="sr-only">Missing: </span> : null}{s}</span>
        </li>
      ))}
    </ul>
  );
}

function AssessmentAnswers({ assessment }) {
  if (!assessment.questions?.length) return <p className="muted small">No questions stored for this assessment.</p>;
  const done = assessment.status === 'completed';
  return (
    <div>
      {assessment.questions.map((q) => {
        const chosen = (q.candidate_answer || '').trim().toUpperCase();
        return (
          <article key={q.index} className="qa">
            <div className="row small muted" style={{ marginBottom: 4 }}>
              <b style={{ color: 'var(--ink-950)' }}>Question {q.index + 1}</b>
              {q.skill && <span className="pill pill-brand">{q.skill}</span>}
              {q.difficulty && <span className="pill pill-neutral">{q.difficulty}</span>}
              {q.type && <span>{{ mcq: 'Multiple choice', coding: 'Coding', short_answer: 'Short answer' }[q.type] || q.type}</span>}
              <span className="spacer" />
              {done && q.correct !== null && q.correct !== undefined && (
                <span className={`pill ${q.correct ? 'pill-ok' : 'pill-danger'}`}>{q.correct ? 'Correct' : 'Incorrect'}</span>
              )}
            </div>
            <p style={{ fontWeight: 500 }}>{q.question}</p>
            {q.type === 'coding' && q.coding && (
              <div style={{ margin: '8px 0' }}>
                <p className="small">{q.coding.status === 'not_submitted' ? 'No code submitted.' : <><b>{q.coding.passed} / {q.coding.total}</b> test cases passed · {q.coding.language} · score {formatScore(q.coding.score)} · {q.coding.exec_time_ms ?? '—'} ms{q.coding.memory_kb ? ` · ${Math.round(q.coding.memory_kb / 1024)} MB` : ''}</>}</p>
                {q.coding.error && <pre className="pre tone-danger">{q.coding.error}</pre>}
                {q.coding.source_code && <details><summary className="small">View submitted code</summary><pre className="pre">{q.coding.source_code}</pre></details>}
              </div>
            )}
            {q.options && (
              <ul className="opts" style={{ listStyle: 'none', padding: 0 }}>
                {q.options.map((o) => {
                  const isCorrect = done && o.label === q.correct_answer;
                  const isChosenWrong = done && o.label === chosen && !isCorrect;
                  return (
                    <li key={o.label} className={`opt${isCorrect ? ' correct' : ''}${isChosenWrong ? ' chosen-wrong' : ''}`}>
                      <b>{o.label}.</b> {o.text}
                      {done && o.label === chosen && <span className="small"> — candidate's answer</span>}
                      {isCorrect && <span className="small"> — correct answer</span>}
                    </li>
                  );
                })}
              </ul>
            )}
            {done && (
              <dl className="kv" style={{ marginTop: 8 }}>
                <dt>Candidate answer</dt>
                <dd>{q.candidate_answer ? q.candidate_answer : <span className="muted">No answer</span>}</dd>
                {q.type === 'mcq' && q.correct_answer && (
                  <><dt>Correct answer</dt><dd>{q.correct_answer}{q.correct_answer_text ? ` — ${q.correct_answer_text}` : ''}</dd></>
                )}
                {q.type !== 'mcq' && q.reference_answer && (<><dt>Reference answer</dt><dd>{q.reference_answer}</dd></>)}
                {q.score !== null && q.score !== undefined && q.type !== 'mcq' && (<><dt>Points</dt><dd>{Number(q.score).toFixed(2)} / 1</dd></>)}
                {q.feedback && (<><dt>Grading feedback</dt><dd>{q.feedback}</dd></>)}
              </dl>
            )}
          </article>
        );
      })}
    </div>
  );
}

export default function CandidateDetail() {
  const navigate = useNavigate();
  const { id } = useParams();
  const [candidate, setCandidate] = useState(null);
  const [scores, setScores] = useState(null);
  const [assessment, setAssessment] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [partialError, setPartialError] = useState(null);
  const [showAnswers, setShowAnswers] = useState(false);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState(null);
  const answersRef = useRef(null);
  const { refreshMe } = useApp();

  const unlock = async () => {
    if (!window.confirm(`Unlock ${candidate.name}'s contact details and original resume for ${candidate.unlock_cost} credits?`)) return;
    setBusy(true); setNotice(null);
    try { const r = await api.unlockCandidate(id); await load(); refreshMe(); setNotice(r.charged ? `Unlocked for ${r.charged} credits.` : 'Already unlocked.'); }
    catch (err) { setError(err.message); }
    finally { setBusy(false); }
  };
  const viewResume = async (download = false) => {
    try { await api.openResume(id, download); } catch (err) { setError(err.message); }
  };

  const load = useCallback(async () => {
    setError(null); setPartialError(null);
    try {
      const c = await api.getCandidate(id);
      setCandidate(c);
      if (!c.applications?.length) return;
      const [s, a] = await Promise.allSettled([api.getCandidateScores(id), api.getCandidateAssessment(id)]);
      if (s.status === 'fulfilled') setScores(s.value); else setPartialError(`Scores: ${s.reason.message}`);
      if (a.status === 'fulfilled') setAssessment(a.value); else setPartialError(`Assessment: ${a.reason.message}`);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }, [id]);

  useEffect(() => { load(); }, [load]);

  const application = candidate?.applications?.[0];
  const resume = candidate?.resume;

  const [pendingStatus, setPendingStatus] = useState(null);
  const setStatus = (status) => { if (application) setPendingStatus(status); };
  const confirmStatus = async (note) => {
    setBusy(true); setNotice(null);
    try {
      await api.updateApplicationStatus(application.application_id, pendingStatus, note);
      setPendingStatus(null);
      await load();
      setNotice(`Status updated to ${pendingStatus}. The candidate has been notified with an explanation.`);
    } catch (err) { setError(err.message); setPendingStatus(null); }
    finally { setBusy(false); }
  };

  useEffect(() => {
    if (showAnswers) answersRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }, [showAnswers]);

  const openAnswers = () => {
    if ((assessment?.status || application?.assessment_status) === 'completed') {
      if (showAnswers) answersRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' });
      setShowAnswers(true);
    } else {
      document.getElementById('assessment')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }
  };

  const shell = (children) => children;

  if (loading) return shell(<p className="muted">Loading candidate…</p>);
  if (error && !candidate) return shell(<p className="alert alert-danger" role="alert">Couldn't load candidate: {error}</p>);

  const job = scores?.job;
  const requirements = job?.requirements_list || [];
  const matched = scores?.matched_skills || [];
  const missing = scores?.missing_skills || [];
  const skillScore = scores?.skill_score ?? application?.skill_score ?? null;
  const screeningStatus = scores?.screening_status ?? application?.screening_status;
  const assessmentStatus = assessment?.status || application?.assessment_status || 'not_started';
  const candidateSkills = splitList(resume?.skills);
  const initials = candidate.name.split(' ').map((n) => n[0]).join('').slice(0, 2).toUpperCase();

  return shell(
    <>
      {pendingStatus && <DecisionDialog name={candidate.name} status={pendingStatus} busy={busy} onCancel={() => setPendingStatus(null)} onConfirm={confirmStatus} />}
      <Link to="/hr/applications" className="btn btn-secondary btn-sm" style={{ marginBottom: 18 }}>← Back to Applications</Link>

      {/* Header */}
      <div className="page-head">
        <div className="row" style={{ gap: 14, alignItems: 'center' }}>
          <div className="avatar" style={{ width: 52, height: 52, fontSize: 18 }} aria-hidden="true">{initials}</div>
          <div>
            <h1 style={{ fontSize: 26 }}>{candidate.name}</h1>
            <p className="small muted" style={{ marginTop: 2 }}>
              Candidate #{candidate.candidate_id} · {candidate.email}{candidate.phone ? ` · ${candidate.phone}` : ''}
              {!candidate.contact_unlocked && <> · <button className="link-btn" onClick={unlock} disabled={busy}><Lock size={12} aria-hidden="true" /> Unlock contact · {candidate.unlock_cost} credits</button></>}
            </p>
            {application ? (
              <p className="small" style={{ marginTop: 2 }}>
                Applied for: <b>{application.job_title}</b> · Applied: {formatDate(application.applied_at)} · Application #{application.application_id}
              </p>
            ) : <p className="small muted">No application on record.</p>}
          </div>
        </div>
        {application && <StatusBadge label={applicationStageLabel(application)} />}
      </div>

      {error && <p className="alert alert-danger" role="alert">{error}</p>}
      {partialError && <p className="alert alert-warn" role="alert">Some data could not be loaded — {partialError}</p>}
      {notice && <p className="alert alert-ok" role="status">{notice}</p>}

      {application && (
        <>
          <section className="card section" aria-label="Pipeline progress">
            <p className="section-title">Pipeline</p>
            <HiringPipeline pipeline={application.pipeline} />
          </section>

          {/* Scores */}
          <div style={{ marginTop: 16 }}>
            <p className="section-title">Scores</p>
            <div className="grid grid-scores">
              <ScoreCard label="Skill Score" value={skillScore} hint={hasScore(skillScore) && job ? `${matched.length} of ${requirements.length} required skills` : undefined} />
              <ScoreCard label="Experience Score" value={scores?.experience_score ?? application.experience_score} hint={resume?.experience_years != null ? `${resume.experience_years} years detected` : undefined} />
              <ScoreCard label="Test Score" value={scores?.test_score ?? application.test_score} hint={assessmentStatus !== 'completed' ? 'Assessment not taken' : undefined} />
              <ScoreCard label="Final Score" value={scores?.final_score ?? application.final_score} hint={assessmentStatus !== 'completed' ? 'Available after assessment' : undefined} />
            </div>
            {screeningStatus === 'failed' && (
              <p className="alert alert-warn" style={{ marginTop: 12 }}>
                Resume screening failed{scores?.screening_error ? `: ${scores.screening_error}` : ''}. Scores stay “—” until screening succeeds (it is retried automatically when the assessment is submitted).
              </p>
            )}
          </div>

          {/* Actions */}
          <section className="card section" aria-label="Candidate actions">
            <div className="row">
              {!resume?.file_available ? <button className="btn btn-secondary" disabled title="No resume file available"><FileText size={16} aria-hidden="true" /> View Resume</button>
                : candidate.contact_unlocked ? <button className="btn btn-secondary" onClick={() => viewResume()}><FileText size={16} aria-hidden="true" /> View Resume</button>
                  : <button className="btn btn-secondary" onClick={unlock} disabled={busy}><Lock size={16} aria-hidden="true" /> Unlock resume · {candidate.unlock_cost} credits</button>}
              <button className="btn btn-secondary" onClick={openAnswers} disabled={assessmentStatus === 'not_started'}><ClipboardList size={16} aria-hidden="true" /> View Assessment</button>
              <span className="spacer" />
              <button className="btn btn-ok" disabled={busy || ['shortlisted', 'scheduled', 'interviewed', 'selected', 'offered', 'hired'].includes(application.status)} onClick={() => setStatus('shortlisted')}>Shortlist</button>
              <button className="btn btn-danger" disabled={busy || ['rejected', 'hired'].includes(application.status)} onClick={() => setStatus('rejected')}>Reject</button>
              <button className="btn btn-secondary" disabled={application.status === 'rejected'} onClick={() => navigate(`/hr/interviews?application=${application.application_id}`)}><CalendarClock size={16} aria-hidden="true" /> Schedule Interview</button>
              <button className="btn btn-primary" disabled={!['assessed', 'shortlisted', 'scheduled', 'interviewed', 'selected', 'offered'].includes(application.status)}
                      title="Available for assessed, shortlisted or interviewed candidates"
                      onClick={() => navigate(`/hr/offers?application=${application.application_id}`)}><Award size={16} aria-hidden="true" /> Create Offer</button>
            </div>
          </section>

          <div className="grid grid-2">
            {/* Job requirements */}
            <Section id="requirements" title="Job requirements">
              <p className="small muted" style={{ marginBottom: 8 }}>The exact requirements of <b>{job?.title || application.job_title}</b> used to calculate the skill score.</p>
              <Chips items={requirements} kind="req" empty="This job has no requirements listed." />
              {job && (
                <dl className="kv" style={{ marginTop: 14 }}>
                  <dt>Minimum experience</dt><dd>{job.min_experience ?? 0} {Number(job.min_experience) === 1 ? 'year' : 'years'}</dd>
                  <dt>Weights</dt><dd>Skill {job.weights.skill}% · Experience {job.weights.experience}% · Assessment {job.weights.assessment}%</dd>
                </dl>
              )}
            </Section>

            {/* Skill match */}
            <Section id="skill-match" title="Skill match" action={<span className="small muted">Skill score {formatScore(skillScore)}</span>}>
              {!hasScore(skillScore) ? (
                <p className="muted small">Skill match has not been calculated yet.</p>
              ) : (
                <>
                  <p className="section-title" style={{ marginBottom: 6 }}>Matched</p>
                  {matched.length ? <Chips items={matched} kind="ok" icon="ok" /> : <p className="small">None</p>}
                  <p className="section-title" style={{ margin: '14px 0 6px' }}>Missing</p>
                  {missing.length ? <Chips items={missing} kind="missing" icon="missing" /> : <p className="small tone-ok">All required skills matched</p>}
                  {Number(skillScore) === 0 && requirements.length > 0 && (
                    <p className="alert alert-info small" style={{ marginTop: 12 }}>
                      0% is a calculated score: none of the {requirements.length} required skills were found among the candidate's extracted skills.
                    </p>
                  )}
                </>
              )}
            </Section>
          </div>
        </>
      )}

      {/* Extracted profile */}
      <Section id="profile" title="Extracted profile" action={resume ? <span className="small muted">Uploaded {formatDate(resume.uploaded_at, true)}</span> : null}>
        {!resume ? <p className="muted small">No resume uploaded for this candidate yet.</p> : (
          <div className="grid" style={{ gap: 18 }}>
            <div>
              <p className="section-title" style={{ marginBottom: 6 }}>Resume</p>
              <div className="row small">
                <FileText size={16} aria-hidden="true" />
                <span>{resume.file_name || 'Resume'}</span>
                {!resume.file_available ? <span className="tone-danger">Original file is not available on the server.</span>
                  : candidate.contact_unlocked ? (
                    <>
                      <button className="btn btn-secondary btn-sm" onClick={() => viewResume()}>View Resume</button>
                      <button className="btn btn-secondary btn-sm" onClick={() => viewResume(true)}><Download size={14} aria-hidden="true" /> Download Resume</button>
                      {!/\.pdf$/i.test(resume.file_name || '') && <span className="muted">Word files open in your browser's download flow.</span>}
                    </>
                  ) : <button className="btn btn-secondary btn-sm" onClick={unlock} disabled={busy}><Lock size={14} aria-hidden="true" /> Unlock to view · {candidate.unlock_cost} credits</button>}
              </div>
            </div>
            <div>
              <p className="section-title" style={{ marginBottom: 6 }}>Candidate skills (extracted)</p>
              <Chips items={candidateSkills} empty="No skills detected in the resume." />
            </div>
            <div>
              <p className="section-title" style={{ marginBottom: 6 }}>Experience</p>
              <p style={{ lineHeight: 1.7 }}>{resume.experience || <span className="muted">Not extracted</span>}</p>
              {resume.experience_entries?.length > 0 && (
                <ul style={{ margin: '8px 0 0', paddingLeft: 18, fontSize: 14 }}>
                  {resume.experience_entries.map((e, i) => (
                    <li key={i}>
                      <b>{e.title_or_role || e.role || 'Role'}</b>{e.organization ? ` · ${e.organization}` : ''}
                      {typeof e.duration_months === 'number' ? <span className="muted"> · {e.duration_months} months</span> : null}
                    </li>
                  ))}
                </ul>
              )}
            </div>
            <div>
              <p className="section-title" style={{ marginBottom: 6 }}>Education</p>
              <p style={{ lineHeight: 1.7 }}>{resume.education || <span className="muted">Not extracted</span>}</p>
              <p className="small muted" style={{ marginTop: 4 }}>Education is informational only and does not affect scoring.</p>
            </div>
          </div>
        )}
      </Section>

      {application && (
        <>
          {/* Assessment */}
          <Section id="integrity" title="Assessment integrity">
            {assessmentStatus === 'not_started' ? <p className="muted">Assessment not taken.</p> : <IntegrityReport applicationId={application.application_id} />}
          </Section>

          <Section id="assessment" title="Assessment">
            {assessmentStatus === 'not_started' ? (
              <p className="muted">Assessment not taken.</p>
            ) : (
              <>
                <dl className="kv">
                  <dt>Status</dt><dd>{ASSESSMENT_LABEL[assessmentStatus]}</dd>
                  <dt>Test score</dt><dd>{assessmentStatus === 'completed' ? formatScore(assessment?.test_score ?? scores?.test_score) : '—'}</dd>
                  <dt>Started</dt><dd>{formatDate(assessment?.started_at, true)}</dd>
                  {assessmentStatus === 'completed' && (<><dt>Completed</dt><dd>{formatDate(assessment?.completed_at, true)}</dd></>)}
                  {assessment?.skills_covered?.length > 0 && (<><dt>Skills covered</dt><dd>{assessment.skills_covered.join(', ')}</dd></>)}
                </dl>
                {assessmentStatus === 'completed' ? (
                  <button className="btn btn-secondary btn-sm" style={{ marginTop: 12 }} onClick={() => (showAnswers ? setShowAnswers(false) : openAnswers())} aria-expanded={showAnswers} aria-controls="assessment-answers">
                    {showAnswers ? 'Hide answers' : 'View Assessment'}
                  </button>
                ) : <p className="small muted" style={{ marginTop: 10 }}>The candidate has started but not submitted the assessment. Answers appear here once it is submitted.</p>}
              </>
            )}
          </Section>

          {assessmentStatus === 'completed' && showAnswers && assessment && (
            <section className="card section" id="assessment-answers" ref={answersRef} aria-label="Assessment answers">
              <h2 style={{ fontSize: 17, marginBottom: 12 }}>Assessment answers</h2>
              <AssessmentAnswers assessment={assessment} />
            </section>
          )}

          <div className="grid grid-2">
            <Section id="ranking" title="Ranking explanation">
              <p style={{ lineHeight: 1.7 }}>{scores?.ranking_explanation || application.ranking_explanation || <span className="muted">No ranking explanation yet.</span>}</p>
            </Section>
            <Section id="recommendation" title="Recommendation">
              {hasScore(scores?.final_score) ? (
                <p style={{ fontSize: 18, fontWeight: 600 }}>{scores.recommendation || '—'}</p>
              ) : (
                <p className="muted">{scores?.recommendation === 'Pending assessment' || assessmentStatus !== 'completed' ? 'Pending assessment' : 'Not available — final ranking has not completed.'}</p>
              )}
            </Section>
          </div>
        </>
      )}
    </>,
  );
}
