import { useState } from 'react';
import { Modal } from './ui';

const COPY = {
  rejected: {
    title: 'Reject this application',
    confirm: 'Reject and notify',
    body: (name) => `${name} will be told the process stopped, with a written explanation built from their scores, matched and missing skills and assessment topics — plus your note below.`,
    placeholder: 'Optional — what made the difference? e.g. “We needed stronger SQL for this role.”',
  },
  shortlisted: {
    title: 'Shortlist this candidate',
    confirm: 'Shortlist and notify',
    body: (name) => `${name} will be told they are through to the interview stage, with a short explanation of what worked in their favour.`,
    placeholder: 'Optional — anything to tell them about next steps?',
  },
  selected: {
    title: 'Select this candidate',
    confirm: 'Select and notify',
    body: (name) => `${name} will be told they are selected and that an offer letter is being prepared.`,
    placeholder: 'Optional — a personal note.',
  },
};

/** Confirms an HR decision and lets HR add a note that is shown to the candidate with the explanation. */
export default function DecisionDialog({ name, status, busy, onCancel, onConfirm }) {
  const copy = COPY[status] || COPY.shortlisted;
  const [note, setNote] = useState('');
  return (
    <Modal title={copy.title} onClose={onCancel}
           footer={<>
             <button className="btn btn-secondary" onClick={onCancel} disabled={busy}>Cancel</button>
             <button className={`btn ${status === 'rejected' ? 'btn-danger' : 'btn-primary'}`} disabled={busy} onClick={() => onConfirm(note.trim())}>{busy ? 'Saving…' : copy.confirm}</button>
           </>}>
      <p className="small" style={{ marginBottom: 12 }}>{copy.body(name)}</p>
      <label className="field-label" htmlFor="decision-note">Note to the candidate</label>
      <textarea id="decision-note" className="input" rows={4} maxLength={1000} value={note} onChange={(e) => setNote(e.target.value)} placeholder={copy.placeholder} />
      <p className="small muted" style={{ marginTop: 6 }}>{note.length}/1000 · Don't include other candidates' details.</p>
    </Modal>
  );
}
