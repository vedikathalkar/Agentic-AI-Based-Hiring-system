import { formatScore, scoreTone, hasScore } from '../utils/score';

export default function ScoreCard({ label, value, hint }) {
  const tone = scoreTone(value);
  const width = hasScore(value) ? Math.max(0, Math.min(100, Number(value))) : 0;
  return (
    <div className="card score-card">
      <p className="label">{label}</p>
      <p className={`value tone-${tone}`}>{formatScore(value)}</p>
      <div
        className="progress"
        role="progressbar"
        aria-label={`${label}: ${hasScore(value) ? formatScore(value) : 'not calculated'}`}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={hasScore(value) ? Math.round(Number(value)) : undefined}
      >
        <span className={`bg-${tone}`} style={{ width: `${width}%` }} />
      </div>
      <p className="small muted" style={{ marginTop: 8 }}>{hint || (hasScore(value) ? '' : 'Not calculated yet')}</p>
    </div>
  );
}
