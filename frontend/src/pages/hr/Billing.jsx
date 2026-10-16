import { useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { Download, Pencil, Receipt, TriangleAlert } from 'lucide-react';
import { api } from '../../api';
import { useApp } from '../../context/AppContext';
import { Async, EmptyState, Modal, PageHeader, StatCard, money, useAsync } from '../../components/ui';
import { formatDate } from '../../utils/status';

const FIELDS = [['billed_to', 'Billed to'], ['company', 'Company'], ['email', 'Email'], ['mobile', 'Mobile'], ['address', 'Address'], ['gst_number', 'GST number']];

export default function Billing() {
  const { toast } = useApp();
  const profile = useAsync(() => api.billingProfile(), []);
  const orders = useAsync(() => api.orders(), []);
  const [editing, setEditing] = useState(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState(null);
  const [q, setQ] = useState('');
  const [month, setMonth] = useState('');
  const [status, setStatus] = useState('');

  const rows = useMemo(() => (orders.data?.orders || []).filter((o) => {
    const text = `${o.invoice_number || ''} ${o.provider_order_id || ''} ${o.provider_payment_id || ''}`.toLowerCase();
    return (!q || text.includes(q.toLowerCase())) && (!status || o.status === status)
      && (!month || String(o.paid_at || o.created_at).slice(0, 7) === month);
  }), [orders.data, q, status, month]);
  const months = useMemo(() => [...new Set((orders.data?.orders || []).map((o) => String(o.paid_at || o.created_at).slice(0, 7)))], [orders.data]);

  const save = async () => {
    setSaving(true); setError(null);
    try { profile.setData(await api.updateBillingProfile(editing)); setEditing(null); toast('Invoice details saved', 'ok'); }
    catch (e) { setError(e.message); }
    finally { setSaving(false); }
  };
  const download = async (o) => {
    try { await api.downloadInvoice(o.order_id, o.invoice_number); } catch (e) { toast(e.message, 'danger'); }
  };

  return (
    <>
      <PageHeader title="Billing" subtitle="Every credit purchase you have made, with a downloadable invoice for each."
                  actions={<Link className="btn btn-primary" to="/hr/credits/buy">Buy credits</Link>} />

      <section className="card section" style={{ marginTop: 0 }}>
        <div className="row"><div><h3>Invoice details</h3><p className="small muted">These appear on every invoice you download.</p></div><span className="spacer" />
          {profile.data && <button className="btn btn-secondary btn-sm" onClick={() => setEditing({ ...profile.data })}><Pencil size={14} aria-hidden="true" /> Edit</button>}</div>
        <Async state={profile} loadingLabel="Loading billing details…" errorLabel="Failed to load billing details">
          {(b) => (
            <>
              <dl className="billing-grid">
                {FIELDS.map(([k, label]) => (
                  <div key={k}><dt>{label}</dt><dd>{b[k] ? b[k] : <i className="muted">Not added</i>}</dd></div>
                ))}
              </dl>
              {!b.gst_number && (
                <p className="alert alert-warn small" style={{ marginTop: 12 }}><TriangleAlert size={14} aria-hidden="true" style={{ verticalAlign: -2 }} /> <b>No GST number on file.</b> Add it before your next purchase if your company needs to claim input tax credit — invoices already downloaded will not change.</p>
              )}
            </>
          )}
        </Async>
      </section>

      <Async state={orders} loadingLabel="Loading payments…" errorLabel="Failed to load payments">
        {(o) => (
          <>
            <div className="grid grid-stats" style={{ marginTop: 16 }}>
              <StatCard label="Total paid" value={money(o.totals.paid_paise)} hint="Across all successful payments" />
              <StatCard label="Credits purchased" value={o.totals.credits.toLocaleString()} tone="ok" hint="Total credited to your account" />
              <StatCard label="Invoices" value={o.totals.invoices} hint="Available to download" />
              <StatCard label="Last payment" value={o.totals.last_payment ? formatDate(o.totals.last_payment) : '—'} tone="gold" hint={o.totals.last_payment ? 'Most recent purchase' : 'No payments yet'} />
            </div>
            <section className="card section">
              <div className="row" style={{ marginBottom: 12 }}><h3>Payment history</h3><span className="spacer" /><span className="small muted">{rows.length ? `${rows.length} payment${rows.length === 1 ? '' : 's'}` : 'Nothing to show'}</span></div>
              <div className="tools">
                <label className="sr-only" htmlFor="pay-q">Search payment or order ID</label>
                <input id="pay-q" className="input" placeholder="Search payment, order or invoice ID…" value={q} onChange={(e) => setQ(e.target.value)} />
                <label className="sr-only" htmlFor="pay-m">Month</label>
                <select id="pay-m" className="input" value={month} onChange={(e) => setMonth(e.target.value)}>
                  <option value="">All months</option>{months.map((m) => <option key={m} value={m}>{new Date(`${m}-01T00:00:00`).toLocaleDateString(undefined, { month: 'short', year: 'numeric' })}</option>)}
                </select>
                <label className="sr-only" htmlFor="pay-s">Status</label>
                <select id="pay-s" className="input" value={status} onChange={(e) => setStatus(e.target.value)}>
                  <option value="">All statuses</option><option value="paid">Paid</option><option value="failed">Failed</option>
                </select>
              </div>
              {rows.length === 0 ? (
                <EmptyState title={o.orders.length ? 'No payments match these filters' : 'You have not bought any credits yet.'}>
                  {!o.orders.length && <Link to="/hr/credits/buy">Buy credits</Link>}
                </EmptyState>
              ) : (
                <div className="table-wrap">
                  <table className="table" style={{ minWidth: 700 }}>
                    <thead><tr><th scope="col">Date</th><th scope="col">Invoice</th><th scope="col">Credits</th><th scope="col">Amount</th><th scope="col">Payment</th><th scope="col">Status</th><th scope="col"><span className="sr-only">Invoice</span></th></tr></thead>
                    <tbody>
                      {rows.map((r) => (
                        <tr key={r.order_id}>
                          <td>{formatDate(r.paid_at || r.created_at, true)}</td>
                          <td>{r.invoice_number || '—'}</td>
                          <td>{r.credits.toLocaleString()}</td>
                          <td>{money(r.amount_paise)}{r.discount_paise > 0 && <span className="small muted"> (−{money(r.discount_paise)})</span>}</td>
                          <td className="small">{r.provider_payment_id || r.provider_order_id || '—'}{r.failure_reason && <><br /><span className="tone-danger">{r.failure_reason}</span></>}</td>
                          <td><span className={`pill ${r.status === 'paid' ? 'pill-ok' : 'pill-danger'}`}>{r.status === 'paid' ? 'Paid' : 'Failed'}</span></td>
                          <td>{r.status === 'paid' && <button className="btn btn-secondary btn-sm" onClick={() => download(r)}><Download size={14} aria-hidden="true" /> Invoice</button>}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
              <p className="small muted row" style={{ marginTop: 10 }}><Receipt size={14} aria-hidden="true" /> Credits spent on features are listed under <Link to="/hr/credits">Credits & usage</Link>.</p>
            </section>
          </>
        )}
      </Async>

      {editing && (
        <Modal title="Invoice details" onClose={() => setEditing(null)}
               footer={<><button className="btn btn-secondary" onClick={() => setEditing(null)}>Cancel</button><button className="btn btn-primary" disabled={saving} onClick={save}>{saving ? 'Saving…' : 'Save'}</button></>}>
          {FIELDS.map(([k, label]) => (
            <div key={k} className="field"><label className="field-label" htmlFor={`bill-${k}`}>{label}</label>
              {k === 'address'
                ? <textarea id={`bill-${k}`} className="input" rows={3} value={editing[k] || ''} onChange={(e) => setEditing({ ...editing, [k]: e.target.value })} />
                : <input id={`bill-${k}`} className="input" type={k === 'email' ? 'email' : 'text'} value={editing[k] || ''} onChange={(e) => setEditing({ ...editing, [k]: e.target.value })} />}
            </div>
          ))}
          {error && <p className="alert alert-danger small" role="alert">{error}</p>}
        </Modal>
      )}
    </>
  );
}
