import { statusPill } from '../utils/status';

export default function StatusBadge({ status, label }) {
  const pill = label || statusPill(status);
  return <span className={`pill ${pill.cls}`}>{pill.text}</span>;
}
