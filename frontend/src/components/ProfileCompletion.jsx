import { Link } from 'react-router-dom';
import { Check, Circle } from 'lucide-react';
import { ProgressBar } from './ui';

/** Reusable completion card. `completion` comes from the API: {percent, sections:[{key,label,complete,missing}]}. */
export default function ProfileCompletion({ completion, basePath = '/profile', title = 'Complete your profile', compact }) {
  if (!completion) return null;
  const { percent, sections } = completion;
  const firstMissing = sections.find((s) => !s.complete);
  return (
    <section className="card section" aria-label="Profile completion">
      <div className="row" style={{ marginBottom: 8 }}>
        <h3>{percent === 100 ? 'Profile complete' : title}</h3>
        <span className="spacer" />
        <span className={`pill ${percent === 100 ? 'pill-ok' : 'pill-warn'}`}>{percent === 100 ? 'Profile complete' : 'Profile incomplete'}</span>
      </div>
      <ProgressBar value={percent} label="Profile completion" tone={percent === 100 ? 'ok' : 'brand'} />
      {!compact && (
        <ul className="completion-list">
          {sections.map((s) => (
            <li key={s.key}>
              {s.complete ? <Check size={16} className="tone-ok" aria-hidden="true" /> : <Circle size={16} className="muted" aria-hidden="true" />}
              {s.complete ? <span>{s.label}</span> : (
                <Link to={`${basePath}#${s.key}`} title={s.missing.join(', ')}>{s.label}<span className="small muted"> — {s.missing.join(', ')}</span></Link>
              )}
              <span className="sr-only">{s.complete ? 'complete' : 'missing'}</span>
            </li>
          ))}
        </ul>
      )}
      {firstMissing && <Link className="btn btn-primary btn-sm" style={{ marginTop: 12 }} to={`${basePath}#${firstMissing.key}`}>Complete Profile</Link>}
    </section>
  );
}
