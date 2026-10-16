import { useState } from 'react';
import { api } from '../../api';
import { Async, EmptyState, Modal, PageHeader, useAsync } from '../../components/ui';
import TicketForm from '../../components/TicketForm';
import TicketThread, { TICKET_STATUS } from '../../components/TicketThread';
import { formatDate } from '../../utils/status';

export default function Support() {
  const list = useAsync(() => api.getTickets(), []);
  const [selected, setSelected] = useState(null);
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState(null);
  const open = async (id) => { setError(null); try { setSelected(await api.getTicket(id)); } catch (e) { setError(e.message); } };
  return (
    <>
      <PageHeader title="Support" subtitle="Your support tickets and conversations with the Hirelune team."
                  actions={<button className="btn btn-primary" onClick={() => setCreating(true)}>New ticket</button>} />
      {error && <p className="alert alert-danger" role="alert">{error}</p>}
      <div className="grid support-grid">
        <section className="card" style={{ padding: 12 }}>
          <Async state={list} loadingLabel="Loading tickets…" errorLabel="Failed to load tickets">
            {(rows) => rows.length === 0 ? <EmptyState title="No tickets yet">Open a ticket and we'll reply here and by email.</EmptyState> : (
              <ul className="plain-list" style={{ marginTop: 0 }}>
                {rows.map((t) => {
                  const [label, cls] = TICKET_STATUS[t.status] || [t.status, 'pill-neutral'];
                  return (
                    <li key={t.ticket_id}>
                      <button className="notif-item" style={{ borderRadius: 8, border: selected?.ticket_id === t.ticket_id ? '1px solid var(--brand)' : undefined }} onClick={() => open(t.ticket_id)}>
                        <span className="row"><b>#{t.ticket_id} {t.subject}</b></span>
                        <span className="row small"><span className={`pill ${cls}`}>{label}</span><span className="muted">Updated {formatDate(t.updated_at)}</span></span>
                      </button>
                    </li>
                  );
                })}
              </ul>
            )}
          </Async>
        </section>
        <section className="card section" style={{ marginTop: 0 }}>
          {selected ? <TicketThread ticket={selected} onChange={(t) => { setSelected(t); list.reload(); }} />
            : <p className="muted">Select a ticket to view the conversation.</p>}
        </section>
      </div>
      {creating && (
        <Modal title="New support ticket" wide onClose={() => setCreating(false)}>
          <TicketForm onCreated={(t) => { setCreating(false); setSelected(t); list.reload(); }} />
        </Modal>
      )}
    </>
  );
}
