import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { Download, Gift, Info } from 'lucide-react';
import { api } from '../../api';
import { Async, EmptyState, Modal, PageHeader, StatCard, useAsync } from '../../components/ui';

const TYPE_LABEL = { signup_bonus: ['Signup bonus', 'pill-ok'], purchase: ['Credits purchased', 'pill-ok'], spend: ['Spent', 'pill-danger'],
  refund: ['Refund', 'pill-ok'], admin_adjustment: ['Adjustment', 'pill-brand'], referral_reward: ['Referral reward', 'pill-ok'] };
const COST_LABEL = { candidate_unlock: 'Unlock a candidate (contact + original resume)', ai_assessment: 'AI assessment (charged when a candidate starts it)',
  offer_letter: 'Send an offer letter', ats_check: 'Resume ATS check (candidates)' };

const fmtDay = (v) => { const d = new Date(/Z|[+-]\d\d:?\d\d$/.test(v) ? v : `${v}Z`); return { day: d.toLocaleDateString(undefined, { day: 'numeric', month: 'short' }), time: d.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' }) }; };
const thisMonth = () => new Date().toISOString().slice(0, 7);

export default function Credits() {
  const [month, setMonth] = useState(thisMonth());
  const [filters, setFilters] = useState({ q: '', direction: '', type: '', page: 1, size: 10 });
  const [query, setQuery] = useState('');
  const [showCosts, setShowCosts] = useState(false);
  const [exporting, setExporting] = useState(false);
  const [exportError, setExportError] = useState(null);
  const summary = useAsync(() => api.billingSummary(month), [month]);
  const usage = useAsync(() => api.billingUsage(month), [month]);
  const tx = useAsync(() => api.transactions({ month, ...filters }), [month, filters]);

  // Debounce the search box.
  useEffect(() => { const id = setTimeout(() => setFilters((f) => (f.q === query ? f : { ...f, q: query, page: 1 })), 300); return () => clearTimeout(id); }, [query]);
  const setF = (k) => (e) => setFilters((f) => ({ ...f, [k]: e.target.value, page: 1 }));

  const exportCsv = async () => {
    setExporting(true); setExportError(null);
    try {
      const rows = [];
      for (let page = 1; ; page += 1) {
        const r = await api.transactions({ month, ...filters, page, size: 100 });
        rows.push(...r.items);
        if (page >= r.pages) break;
      }
      const esc = (v) => `"${String(v ?? '').replace(/"/g, '""')}"`;
      const csv = ['Date,Description,Type,Credits,Balance after',
        ...rows.map((t) => [t.created_at, t.description, (TYPE_LABEL[t.type] || [t.type])[0], t.amount, t.balance_after].map(esc).join(','))].join('\n');
      const url = URL.createObjectURL(new Blob([csv], { type: 'text/csv' }));
      const a = document.createElement('a'); a.href = url; a.download = `hirelune-credits-${month}.csv`; a.click();
      setTimeout(() => URL.revokeObjectURL(url), 10_000);
    } catch (e) { setExportError(e.message); }
    finally { setExporting(false); }
  };

  return (
    <>
      <PageHeader title="Credits & usage" subtitle="Every credit you have spent, month by month."
                  actions={<>
                    <label className="sr-only" htmlFor="cr-month">Month</label>
                    <select id="cr-month" className="input" style={{ width: 170 }} value={month} onChange={(e) => { setMonth(e.target.value); setFilters((f) => ({ ...f, page: 1 })); }}>
                      {[...new Set([thisMonth(), ...(summary.data?.months || [])])].map((m) => <option key={m} value={m}>{new Date(`${m}-01T00:00:00`).toLocaleDateString(undefined, { month: 'short', year: 'numeric' })}</option>)}
                    </select>
                    <button className="btn btn-secondary" onClick={() => setShowCosts(true)}><Info size={15} aria-hidden="true" /> What things cost</button>
                    <Link className="btn btn-primary" to="/hr/credits/buy">Buy credits</Link>
                  </>} />
      <Async state={summary} loadingLabel="Loading credits…" errorLabel="Failed to load credits">
        {(s) => (
          <>
            <div className="banner">
              <Gift size={18} aria-hidden="true" style={{ color: 'var(--gold)' }} />
              <p><b>Every HR account starts with {s.signup_credits.toLocaleString()} free credits on signup</b> — enough to unlock your first candidates and run assessments. When you run low, top up on the <Link to="/hr/credits/buy">Buy credits</Link> page. Credits never expire.</p>
            </div>
            <div className="grid grid-stats">
              <StatCard label="Spent this month" value={s.spent.toLocaleString()} tone="gold" hint={s.previous_month_spent ? `${s.previous_month_spent.toLocaleString()} spent last month` : 'Nothing spent last month'} />
              <StatCard label="Credits added" value={s.added.toLocaleString()} tone="ok" hint="Purchases, bonuses and adjustments" />
              <StatCard label="Current balance" value={s.balance.toLocaleString()} hint="Available to spend right now" />
              <StatCard label="Transactions" value={s.transactions} hint={`Entries in ${s.month_label}`} />
            </div>
          </>
        )}
      </Async>

      <section className="card section">
        <div className="row"><h3>Where your credits went</h3><span className="spacer" />{usage.data && <span className="small muted"><b>{usage.data.total.toLocaleString()}</b> credits in {usage.data.month_label}</span>}</div>
        <Async state={usage} loadingLabel="Loading usage…" errorLabel="Failed to load usage">
          {(u) => u.features.length === 0 ? <p className="muted" style={{ textAlign: 'center', padding: '24px 0' }}>You did not spend any credits in {u.month_label}.</p> : (
            <div style={{ display: 'grid', gap: 12, marginTop: 12 }}>
              {u.features.map((f) => (
                <div key={f.feature}>
                  <div className="row small" style={{ justifyContent: 'space-between' }}><span>{f.feature} <span className="muted">· {f.count}×</span></span><b>{f.credits.toLocaleString()} credits</b></div>
                  <div className="progress" role="progressbar" aria-label={`${f.feature}: ${f.credits} credits`} aria-valuemin={0} aria-valuemax={u.total} aria-valuenow={f.credits}>
                    <span className="bg-brand" style={{ width: `${(f.credits / (u.total || 1)) * 100}%` }} />
                  </div>
                </div>
              ))}
            </div>
          )}
        </Async>
      </section>

      <section className="card section">
        <div className="row" style={{ marginBottom: 12 }}><h3>Your activity</h3><span className="spacer" />{tx.data && <span className="small muted">{tx.data.total === 0 ? '0' : `${(tx.data.page - 1) * tx.data.size + 1}–${Math.min(tx.data.total, tx.data.page * tx.data.size)}`} of {tx.data.total}</span>}</div>
        <div className="tools">
          <label className="sr-only" htmlFor="tx-q">Search description</label>
          <input id="tx-q" className="input" placeholder="Search description…" value={query} onChange={(e) => setQuery(e.target.value)} />
          <label className="sr-only" htmlFor="tx-dir">Direction</label>
          <select id="tx-dir" className="input" value={filters.direction} onChange={setF('direction')}>
            <option value="">All activity</option><option value="credit">Credits in</option><option value="debit">Credits out</option>
          </select>
          <label className="sr-only" htmlFor="tx-type">Type</label>
          <select id="tx-type" className="input" value={filters.type} onChange={setF('type')}>
            <option value="">All types</option>{Object.entries(TYPE_LABEL).map(([k, [l]]) => <option key={k} value={k}>{l}</option>)}
          </select>
          <button className="btn btn-secondary" onClick={exportCsv} disabled={exporting}><Download size={15} aria-hidden="true" /> {exporting ? 'Exporting…' : 'Export'}</button>
        </div>
        {exportError && <p className="alert alert-danger small" role="alert">{exportError}</p>}
        <Async state={tx} loadingLabel="Loading activity…" errorLabel="Failed to load activity">
          {(t) => t.items.length === 0 ? <EmptyState title="No activity">Nothing matches these filters in this month.</EmptyState> : (
            <div className="table-wrap">
              <table className="table" style={{ minWidth: 620 }}>
                <thead><tr><th scope="col">Date</th><th scope="col">Description</th><th scope="col">Type</th><th scope="col" style={{ textAlign: 'right' }}>Credits</th><th scope="col" style={{ textAlign: 'right' }}>Balance</th></tr></thead>
                <tbody>
                  {t.items.map((r) => {
                    const d = fmtDay(r.created_at);
                    const [label, cls] = TYPE_LABEL[r.type] || [r.type, 'pill-neutral'];
                    return (
                      <tr key={r.transaction_id}>
                        <td>{d.day}<br /><span className="small muted">{d.time}</span></td>
                        <td>{r.description}</td>
                        <td><span className={`pill ${cls}`}>{label}</span></td>
                        <td className={`num ${r.amount > 0 ? 'tone-ok' : 'tone-danger'}`} style={{ textAlign: 'right' }}><b>{r.amount > 0 ? '+' : ''}{r.amount.toLocaleString()}</b></td>
                        <td className="num" style={{ textAlign: 'right' }}>{r.balance_after.toLocaleString()}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </Async>
        {tx.data && (
          <div className="row" style={{ marginTop: 12 }}>
            <label className="small" htmlFor="tx-size">Rows</label>
            <select id="tx-size" className="input" style={{ width: 80 }} value={filters.size} onChange={setF('size')}>{[10, 25, 50].map((n) => <option key={n}>{n}</option>)}</select>
            <span className="spacer" />
            <button className="btn btn-secondary btn-sm" aria-label="Previous page" disabled={tx.data.page <= 1} onClick={() => setFilters((f) => ({ ...f, page: f.page - 1 }))}>‹</button>
            <span className="small">{tx.data.page} / {tx.data.pages}</span>
            <button className="btn btn-secondary btn-sm" aria-label="Next page" disabled={tx.data.page >= tx.data.pages} onClick={() => setFilters((f) => ({ ...f, page: f.page + 1 }))}>›</button>
          </div>
        )}
      </section>

      {showCosts && (
        <Modal title="What things cost" onClose={() => setShowCosts(false)} footer={<button className="btn btn-primary" onClick={() => setShowCosts(false)}>Got it</button>}>
          <Async state={summary}>
            {(s) => (
              <table className="table" style={{ minWidth: 0 }}>
                <tbody>{Object.entries(s.costs).filter(([k]) => k !== 'ats_check').map(([k, v]) => (
                  <tr key={k}><td>{COST_LABEL[k] || k}</td><td style={{ textAlign: 'right' }}><b>{v ? `${v} credits` : 'Free'}</b></td></tr>
                ))}</tbody>
              </table>
            )}
          </Async>
          <p className="small muted" style={{ marginTop: 10 }}>1 credit = ₹1. Unlocking the same candidate twice is never charged twice.</p>
        </Modal>
      )}
    </>
  );
}
