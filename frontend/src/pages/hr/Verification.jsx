import { useState } from 'react';
import { Link } from 'react-router-dom';
import { Check, Circle, ShieldCheck, TriangleAlert } from 'lucide-react';
import { api } from '../../api';
import { useApp } from '../../context/AppContext';
import { Async, FileUploader, Modal, PageHeader, useAsync } from '../../components/ui';
import { formatDate, pill, VERIFICATION_STATE } from '../../utils/status';

const DOCS = [
  ['id_proof', 'Official ID proof', 'Government ID or company ID card of the HR representative.'],
  ['visiting_card', 'Visiting card', 'Your business card showing name, designation and company. (ID proof or visiting card is required.)'],
  ['registration_proof', 'Company registration proof', 'Certificate of incorporation, GST certificate or similar (where applicable).'],
];

const STEPS = [
  ['profile', 'Profile complete'],
  ['submitted', 'Documents submitted'],
  ['pending', 'Verification pending'],
  ['result', 'Verified'],
];

function Stepper({ v }) {
  const status = v.status;
  const done = {
    profile: v.missing.length === 0 || ['pending', 'verified'].includes(status),
    submitted: ['pending', 'verified'].includes(status) || (status === 'rejected' && v.submitted_at),
    pending: status === 'verified' || status === 'rejected',
    result: status === 'verified',
  };
  return (
    <ol className="pipeline-steps" style={{ listStyle: 'none', padding: 0, margin: '0 0 4px' }} aria-label="Verification progress">
      {STEPS.map(([key, label]) => {
        const rejected = key === 'result' && status === 'rejected';
        const current = (key === 'pending' && status === 'pending');
        return (
          <li key={key} className={`pipeline-step${done[key] || current ? ' on' : ''}`} style={rejected ? { borderColor: 'var(--danger)', background: 'var(--danger-bg)' } : undefined}>
            <b aria-hidden="true">{rejected ? '✕' : done[key] ? '✓' : current ? '⏳' : '○'}</b>
            <span className="small">{rejected ? 'Needs correction' : label}</span>
            <span className="sr-only">{rejected ? 'rejected' : done[key] ? 'done' : current ? 'in progress' : 'not done'}</span>
          </li>
        );
      })}
    </ol>
  );
}

export default function Verification() {
  const { toast, refreshMe } = useApp();
  const state = useAsync(() => api.getVerification(), []);
  const [busy, setBusy] = useState(null);
  const [error, setError] = useState(null);
  const [confirm, setConfirm] = useState(false);

  const upload = (type) => async (file) => {
    setError(null);
    if (!/\.(pdf|jpe?g|png|webp)$/i.test(file.name)) { setError(`"${file.name}" is not supported. Upload a PDF, JPG, JPEG, PNG or WEBP file.`); return; }
    if (file.size > 2 * 1024 * 1024) { setError(`"${file.name}" is ${(file.size / 1048576).toFixed(1)} MB. The limit is 2 MB.`); return; }
    setBusy(type);
    try { await api.uploadCompanyDocument(type, file); await state.reload(); toast('Document uploaded', 'ok'); }
    catch (e) { setError(e.message); }
    finally { setBusy(null); }
  };
  const submit = async () => {
    setConfirm(false); setBusy('submit'); setError(null);
    try { state.setData(await api.submitVerification()); toast('Submitted for verification', 'ok'); refreshMe(); }
    catch (e) { setError(e.message); }
    finally { setBusy(null); }
  };

  return (
    <Async state={state} loadingLabel="Loading verification…" errorLabel="Failed to load verification">
      {(v) => {
        const p = pill(VERIFICATION_STATE, v.state);
        const locked = v.status === 'pending' || v.status === 'verified';
        const docs = Object.fromEntries(v.company.documents.map((d) => [d.doc_type, d]));
        const canSubmit = !locked && v.missing.length === 0;
        return (
          <div>
            <PageHeader title="Company verification" subtitle="We verify that only legitimate HR professionals and real companies can post jobs, unlock candidates and send offers."
                        actions={<span className={`pill ${p.cls}`}>{p.text}</span>} />
            {error && <p className="alert alert-danger" role="alert">{error}</p>}

            <section className="card section" style={{ marginTop: 0 }}>
              <Stepper v={v} />
              {v.status === 'verified' && (
                <p className="alert alert-ok" style={{ marginTop: 12 }}><ShieldCheck size={16} aria-hidden="true" style={{ verticalAlign: -3 }} /> <b>{v.company.name}</b> was verified on {formatDate(v.verified_at, true)}. You can post jobs, unlock candidates and send offers.</p>
              )}
              {v.status === 'pending' && (
                <p className="alert alert-info" style={{ marginTop: 12 }}>Submitted on {formatDate(v.submitted_at, true)}. Our team is reviewing your documents — you'll get an email and a notification with the result. Documents can't be changed during review.</p>
              )}
              {v.status === 'rejected' && (
                <div className="alert alert-danger" style={{ marginTop: 12 }} role="alert">
                  <b><TriangleAlert size={15} aria-hidden="true" style={{ verticalAlign: -2 }} /> Verification needs correction.</b>
                  <p style={{ marginTop: 4 }}>Reason: {v.rejection_reason || 'Not specified'}</p>
                  <p className="small" style={{ marginTop: 4 }}>Update your details or documents below and submit again.</p>
                </div>
              )}
              {v.status === 'unverified' && (
                <p className="alert alert-warn" style={{ marginTop: 12 }}><b>Mandatory step:</b> without verification, posting jobs, unlocking candidates and sending offers are disabled.</p>
              )}
            </section>

            <section className="card section">
              <h3>Checklist</h3>
              <ul className="completion-list" style={{ gridTemplateColumns: '1fr' }}>
                {v.checklist.map((c) => (
                  <li key={c.key}>{c.done ? <Check size={16} className="tone-ok" aria-hidden="true" /> : <Circle size={16} className="muted" aria-hidden="true" />}
                    <span>{c.label}</span><span className="sr-only">{c.done ? 'done' : 'not done'}</span></li>
                ))}
              </ul>
              {v.missing.length > 0 && !locked && (
                <p className="small" style={{ marginTop: 10 }}>Still needed: <b>{v.missing.join(', ')}</b>. <Link to="/hr/company">Complete company profile</Link></p>
              )}
            </section>

            <section className="card section">
              <h3>Documents</h3>
              <p className="small muted" style={{ marginBottom: 12 }}>PDF, JPG, JPEG, PNG or WEBP · strict 2 MB limit. Documents are stored privately and only visible to you and Hirelune reviewers.</p>
              <div style={{ display: 'grid', gap: 14 }}>
                {DOCS.map(([type, label, hint]) => {
                  const doc = docs[type];
                  return (
                    <div key={type} className="list-card" style={{ marginBottom: 0 }}>
                      <div className="row" style={{ marginBottom: 8 }}>
                        <b>{label}</b>{doc ? <span className="pill pill-ok">Uploaded · {v.status === 'verified' ? 'Verified' : v.status === 'pending' ? 'Under review' : v.status === 'rejected' ? 'Needs correction' : 'Not yet submitted'}</span> : <span className="pill pill-neutral">Not uploaded</span>}
                        <span className="spacer" />
                        {doc && <button className="btn btn-secondary btn-sm" onClick={() => api.openCompanyDocument(doc.document_id).catch((e) => setError(e.message))}>View {doc.file_name}</button>}
                      </div>
                      <p className="small muted" style={{ marginBottom: 8 }}>{hint}</p>
                      {!locked && <FileUploader id={`doc-${type}`} label={doc ? 'Replace file' : `Upload ${label.toLowerCase()}`} hint={doc ? `Current file: ${doc.file_name} · uploaded ${formatDate(doc.uploaded_at, true)}` : 'Drag & drop or click anywhere in this box'}
                                                accept=".jpg,.jpeg,.png,.webp,.pdf" onFile={upload(type)} busy={busy === type} />}
                    </div>
                  );
                })}
              </div>
            </section>

            {!locked && (
              <div className="row" style={{ justifyContent: 'flex-end', marginTop: 16 }}>
                {!canSubmit && <span className="small muted">Complete the checklist to submit.</span>}
                <button className="btn btn-primary" disabled={!canSubmit || busy === 'submit'} onClick={() => setConfirm(true)}>
                  {busy === 'submit' ? 'Submitting…' : v.status === 'rejected' ? 'Resubmit for verification' : 'Submit for verification'}
                </button>
              </div>
            )}
            {confirm && (
              <Modal title="Submit for verification?" onClose={() => setConfirm(false)}
                     footer={<><button className="btn btn-secondary" onClick={() => setConfirm(false)}>Cancel</button><button className="btn btn-primary" onClick={submit}>Submit</button></>}>
                <p>Your company details and documents will be sent to the Hirelune team for review. You won't be able to change documents until the review is complete.</p>
              </Modal>
            )}
          </div>
        );
      }}
    </Async>
  );
}
