import { Link } from 'react-router-dom';
import { CircleCheck, Lightbulb, MessageSquareText, ShieldAlert, TriangleAlert } from 'lucide-react';
import { api } from '../api';
import { Async, useAsync } from './ui';
import HiringPipeline from './HiringPipeline';
import '../styles/pipeline.css';

const TONE = { positive: 'ok', negative: 'danger', neutral: 'brand' };

function ScoreBar({ label, value, weight, delay }) {
  if (value === null || value === undefined) return null;
  const tone = value >= 70 ? 'ok' : value >= 50 ? 'warn' : 'danger';
  return (
    <div className="df-bar">
      <div className="row small"><span>{label}{weight ? <span className="muted"> · weighs {weight}%</span> : null}</span><span className="spacer" /><b>{value}%</b></div>
      <div className="df-bar-track" role="img" aria-label={`${label} ${value} percent`}>
        <span className={`df-bar-fill tone-${tone}`} style={{ '--w': `${Math.max(2, value)}%`, '--d': `${delay}ms` }} />
      </div>
    </div>
  );
}

/**
 * The written explanation of where an application stands or why it ended: the pipeline, what counted,
 * what helped, where the gap was and what to do next. Loaded from the server, which builds it from the
 * stored scores and answers (and snapshots it when HR decides).
 */
export function FeedbackBody({ fb, showPipeline = true }) {
  const w = fb.scores?.weights || {};
  const tone = TONE[fb.tone] || 'brand';
  const topics = (fb.topics || []).filter((t) => t.skill);
  return (
    <div className={`df df-${fb.tone || 'neutral'}`}>
      <div className="df-head">
        <span className={`df-icon tone-${tone}`} aria-hidden="true">{fb.tone === 'negative' ? <MessageSquareText size={20} /> : <CircleCheck size={20} />}</span>
        <div>
          <h3>{fb.headline}</h3>
          <p className="df-summary">{fb.summary}</p>
        </div>
      </div>

      {showPipeline && fb.pipeline && <div className="df-section"><HiringPipeline pipeline={fb.pipeline} /></div>}

      {(fb.scores?.skill != null || fb.scores?.experience != null || fb.scores?.test != null) && (
        <div className="df-section">
          <h4>What was measured</h4>
          <ScoreBar label="Skills match" value={fb.scores.skill} weight={w.skill} delay={0} />
          <ScoreBar label="Experience match" value={fb.scores.experience} weight={w.experience} delay={150} />
          <ScoreBar label="Assessment" value={fb.scores.test} weight={w.assessment} delay={300} />
          {fb.scores.final != null && <ScoreBar label="Overall (weighted)" value={fb.scores.final} delay={450} />}
        </div>
      )}

      <div className="df-cols">
        {fb.strengths?.length > 0 && (
          <div className="df-section">
            <h4><CircleCheck size={15} aria-hidden="true" /> What worked in your favour</h4>
            <ul className="df-list df-ok">{fb.strengths.map((s) => <li key={s}>{s}</li>)}</ul>
          </div>
        )}
        {fb.gaps?.length > 0 && (
          <div className="df-section">
            <h4><TriangleAlert size={15} aria-hidden="true" /> Where the gap was</h4>
            <ul className="df-list df-gap">{fb.gaps.map((s) => <li key={s}>{s}</li>)}</ul>
          </div>
        )}
      </div>

      {(fb.skills?.matched?.length > 0 || fb.skills?.missing?.length > 0) && (
        <div className="df-section">
          <h4>Skills the role asked for</h4>
          <div className="chips">
            {fb.skills.matched.map((s) => <span key={`m${s}`} className="chip chip-ok">✓ {s}</span>)}
            {fb.skills.missing.map((s) => <span key={`x${s}`} className="chip chip-missing">{s}</span>)}
          </div>
        </div>
      )}

      {topics.length > 1 && (
        <div className="df-section">
          <h4>How each assessment topic went</h4>
          {topics.map((t, i) => <ScoreBar key={t.skill} label={t.skill} value={t.percent} delay={i * 90} />)}
        </div>
      )}

      {fb.integrity && (
        <p className="alert alert-warn small df-integrity"><ShieldAlert size={15} aria-hidden="true" /> {fb.integrity.note}</p>
      )}
      {fb.hr_note && (
        <div className="df-section df-note"><h4>Note from the hiring team</h4><p>{fb.hr_note}</p></div>
      )}

      {fb.next_steps?.length > 0 && (
        <div className="df-section">
          <h4><Lightbulb size={15} aria-hidden="true" /> What you can do next</h4>
          <ul className="df-list df-next">{fb.next_steps.map((s) => <li key={s}>{s}</li>)}</ul>
          {fb.tone === 'negative' && (
            <div className="row" style={{ marginTop: 12 }}>
              <Link className="btn btn-secondary btn-sm" to="/mock-assessment">Practise an assessment</Link>
              <Link className="btn btn-secondary btn-sm" to="/ats">Check your resume</Link>
              <Link className="btn btn-secondary btn-sm" to="/jobs">Find other roles</Link>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export default function DecisionFeedback({ applicationId, showPipeline = true }) {
  const state = useAsync(() => api.applicationFeedback(applicationId), [applicationId]);
  return (
    <Async state={state} loadingLabel="Preparing your explanation…" errorLabel="Couldn't load the explanation">
      {(fb) => <FeedbackBody fb={fb} showPipeline={showPipeline} />}
    </Async>
  );
}
