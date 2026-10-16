import { useState } from 'react';
import { api } from '../api';
import { formatDate } from '../utils/status';

export const TICKET_STATUS = { open: ['Open', 'pill-brand'], in_progress: ['In progress', 'pill-warn'], resolved: ['Resolved', 'pill-ok'], closed: ['Closed', 'pill-neutral'] };

export default function TicketThread({ ticket, onChange, admin }) {
  const [body, setBody] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const send = async (e) => {
    e.preventDefault();
    if (!body.trim()) return;
    setBusy(true); setError(null);
    try { onChange(await api.replyTicket(ticket.ticket_id, body)); setBody(''); }
    catch (err) { setError(err.message); }
    finally { setBusy(false); }
  };
  const setStatus = async (status) => {
    try { onChange(await api.setTicketStatus(ticket.ticket_id, status)); } catch (err) { setError(err.message); }
  };
  const [label, cls] = TICKET_STATUS[ticket.status] || [ticket.status, 'pill-neutral'];
  return (
    <div>
      <div className="row" style={{ marginBottom: 8 }}>
        <h3>#{ticket.ticket_id} · {ticket.subject}</h3><span className={`pill ${cls}`}>{label}</span><span className="spacer" />
        {admin ? (
          <select className="input" style={{ width: 160 }} value={ticket.status} onChange={(e) => setStatus(e.target.value)} aria-label="Ticket status">
            {Object.entries(TICKET_STATUS).map(([k, [l]]) => <option key={k} value={k}>{l}</option>)}
          </select>
        ) : ticket.status !== 'closed'
          ? <button className="btn btn-secondary btn-sm" onClick={() => setStatus('closed')}>Close ticket</button>
          : <button className="btn btn-secondary btn-sm" onClick={() => setStatus('open')}>Re-open</button>}
      </div>
      <p className="small muted">{ticket.category} · {ticket.name} ({ticket.email}) · opened {formatDate(ticket.created_at, true)}
        {ticket.has_attachment && <> · <button className="link-btn" onClick={() => api.openTicketAttachment(ticket.ticket_id)}>{ticket.attachment_name}</button></>}</p>
      <div style={{ display: 'grid', gap: 10, margin: '14px 0' }}>
        {(ticket.messages || []).map((m) => (
          <div key={m.message_id} className="list-card" style={{ marginBottom: 0, borderLeft: `3px solid ${m.author_role === 'admin' ? 'var(--gold)' : 'var(--brand)'}` }}>
            <div className="row small"><b>{m.author_role === 'admin' ? 'Hirelune Support' : m.author_name}</b><span className="spacer" /><span className="muted">{formatDate(m.created_at, true)}</span></div>
            <p style={{ whiteSpace: 'pre-wrap', marginTop: 4 }}>{m.body}</p>
          </div>
        ))}
      </div>
      {(admin || ticket.status !== 'closed') && (
        <form onSubmit={send}>
          <label className="field-label" htmlFor={`reply-${ticket.ticket_id}`}>Reply</label>
          <textarea id={`reply-${ticket.ticket_id}`} className="input" rows={3} value={body} onChange={(e) => setBody(e.target.value)} />
          {error && <p className="alert alert-danger small" role="alert" style={{ marginTop: 8 }}>{error}</p>}
          <button className="btn btn-primary btn-sm" style={{ marginTop: 8 }} disabled={busy || !body.trim()}>{busy ? 'Sending…' : 'Send reply'}</button>
        </form>
      )}
    </div>
  );
}
