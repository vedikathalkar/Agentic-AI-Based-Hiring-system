import { useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { Download } from 'lucide-react';
import { api } from '../../api';
import { Async, Modal, PageHeader, useAsync } from '../../components/ui';
import { useApp } from '../../context/AppContext';
import { formatDate, OFFER_STATUS, pill } from '../../utils/status';

export default function OfferView() {
  const { id } = useParams();
  const { toast } = useApp();
  const state = useAsync(() => api.getOffer(id), [id]);
  const [confirm, setConfirm] = useState(null);
  const [note, setNote] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  const respond = async () => {
    setBusy(true); setError(null);
    try {
      state.setData(await api.respondOffer(id, confirm, note));
      toast(confirm === 'accept' ? 'Offer accepted — congratulations!' : 'Offer declined', confirm === 'accept' ? 'ok' : 'info');
      setConfirm(null);
    } catch (e) { setError(e.message); }
    finally { setBusy(false); }
  };

  return (
    <Async state={state} loadingLabel="Loading offer…" errorLabel="Failed to load offer">
      {(o) => {
        const p = pill(OFFER_STATUS, o.status);
        const open = ['sent', 'viewed'].includes(o.status);
        return (
          <div>
            <Link to="/offers" className="btn btn-secondary btn-sm" style={{ marginBottom: 14 }}>← All offers</Link>
            <PageHeader title={`${o.job_title} — ${o.company_name}`} subtitle={`Received ${formatDate(o.sent_at, true)}`}
                        actions={<><span className={`pill ${p.cls}`}>{p.text}</span>{o.has_pdf && <button className="btn btn-secondary btn-sm" onClick={() => api.openOfferPdf(o.offer_id, true)}><Download size={14} aria-hidden="true" /> Download PDF</button>}</>} />
            <div className="letter">{o.content}</div>
            {open && (
              <section className="card section">
                <p>Please respond by <b>{formatDate(o.expires_at)}</b>.</p>
                <div className="row" style={{ marginTop: 12 }}>
                  <button className="btn btn-primary" onClick={() => setConfirm('accept')}>Accept offer</button>
                  <button className="btn btn-danger" onClick={() => setConfirm('reject')}>Decline</button>
                </div>
              </section>
            )}
            {o.status === 'accepted' && <p className="alert alert-ok" style={{ marginTop: 16 }}>You accepted this offer on {formatDate(o.accepted_at, true)}.</p>}
            {o.status === 'rejected' && <p className="alert alert-warn" style={{ marginTop: 16 }}>You declined this offer on {formatDate(o.rejected_at, true)}.</p>}
            {o.status === 'expired' && <p className="alert alert-warn" style={{ marginTop: 16 }}>This offer expired on {formatDate(o.expires_at)}.</p>}
            {o.status === 'withdrawn' && <p className="alert alert-warn" style={{ marginTop: 16 }}>This offer was replaced by a revised offer.</p>}
            {confirm && (
              <Modal title={confirm === 'accept' ? 'Accept this offer?' : 'Decline this offer?'} onClose={() => setConfirm(null)}
                     footer={<><button className="btn btn-secondary" onClick={() => setConfirm(null)}>Cancel</button>
                       <button className={`btn ${confirm === 'accept' ? 'btn-primary' : 'btn-danger'}`} disabled={busy} onClick={respond}>{busy ? 'Saving…' : confirm === 'accept' ? 'Accept' : 'Decline'}</button></>}>
                <label className="field-label" htmlFor="offer-note">Message to the employer (optional)</label>
                <textarea id="offer-note" className="input" rows={3} value={note} onChange={(e) => setNote(e.target.value)} />
                {error && <p className="alert alert-danger small" role="alert" style={{ marginTop: 10 }}>{error}</p>}
              </Modal>
            )}
          </div>
        );
      }}
    </Async>
  );
}
