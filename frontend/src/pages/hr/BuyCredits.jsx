import { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { Gift, ShieldCheck } from 'lucide-react';
import { api } from '../../api';
import { useApp } from '../../context/AppContext';
import { Async, PageHeader, money, useAsync } from '../../components/ui';

const CHECKOUT_SRC = 'https://checkout.razorpay.com/v1/checkout.js';

function loadRazorpay() {
  if (window.Razorpay) return Promise.resolve(true);
  return new Promise((resolve) => {
    const existing = document.querySelector(`script[src="${CHECKOUT_SRC}"]`);
    const s = existing || document.createElement('script');
    s.src = CHECKOUT_SRC;
    s.onload = () => resolve(!!window.Razorpay);
    s.onerror = () => resolve(false);
    if (!existing) document.body.appendChild(s);
  });
}

export default function BuyCredits() {
  const navigate = useNavigate();
  const { me, refreshMe, toast } = useApp();
  const pricing = useAsync(() => api.pricing(), []);
  const [selected, setSelected] = useState(1000);
  const [terms, setTerms] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  const pay = async (pack) => {
    setBusy(true); setError(null);
    let order;
    try {
      const ready = await loadRazorpay();
      if (!ready) throw new Error("Couldn't load the Razorpay checkout. Check your connection or ad-blocker and try again.");
      order = await api.createOrder(pack.credits, terms);
    } catch (e) { setError(e.message); setBusy(false); return; }

    const rzp = new window.Razorpay({
      key: order.key_id,
      amount: order.amount_paise,
      currency: order.currency,
      name: order.name || 'Hirelune',
      description: `${order.credits} credits`,
      order_id: order.provider_order_id,
      prefill: { name: order.prefill?.name || '', email: order.prefill?.email || '', contact: order.prefill?.contact || '' },
      theme: { color: '#FFC53D' },
      // The payment only counts after the backend verifies Razorpay's signature.
      handler: async (resp) => {
        try {
          const result = await api.verifyOrder(order.order_id, resp);
          toast(`${result.credits} credits added. New balance ${result.balance.toLocaleString()}.`, 'ok');
          setTerms(false);
          refreshMe();
          navigate('/hr/billing');
        } catch (e) {
          setError(`Payment received but verification failed: ${e.message}. Contact support with payment id ${resp.razorpay_payment_id}.`);
        } finally { setBusy(false); }
      },
      modal: {
        ondismiss: () => { api.failOrder(order.order_id, 'Checkout closed before payment').catch(() => {}); setBusy(false); },
      },
    });
    rzp.on('payment.failed', (resp) => {
      const reason = resp?.error?.description || 'Payment failed';
      api.failOrder(order.order_id, reason).catch(() => {});
      setError(`${reason}. You have not been charged credits — please try again.`);
      setBusy(false);
    });
    rzp.open();
  };

  return (
    <Async state={pricing} loadingLabel="Loading prices…" errorLabel="Failed to load prices">
      {(p) => {
        const pack = p.packs.find((x) => x.credits === selected) || p.packs[0];
        const covers = Object.entries({ 'candidate unlocks': p.costs.candidate_unlock, 'AI assessments': p.costs.ai_assessment, 'offer letters': p.costs.offer_letter })
          .filter(([, cost]) => cost > 0).map(([label, cost]) => [label, Math.floor(pack.credits / cost)]);
        const balance = me?.credits ?? 0;
        return (
          <>
            <PageHeader title="Buy credits" subtitle="Credits pay for unlocking candidates, AI assessments and other paid features. 1 credit = ₹1." />
            <div className="banner">
              <Gift size={18} aria-hidden="true" style={{ color: 'var(--gold)' }} />
              <p><b>Every HR account starts with {p.hr_signup_credits.toLocaleString()} free credits on signup</b> — you only buy more once those run out. Credits never expire.
                {p.early_bird.active && <><br /><b>Early bird sale: {p.early_bird.percent}% off every pack until {new Date(`${p.early_bird.until}T00:00:00`).toLocaleDateString(undefined, { day: 'numeric', month: 'short', year: 'numeric' })}</b> — already applied to the prices below.</>}</p>
            </div>
            {!p.payments_configured && (
              <p className="alert alert-warn" role="alert">Online payments are not configured on this server yet (RAZORPAY_KEY_ID / RAZORPAY_KEY_SECRET). You can review prices, but checkout is disabled — <Link to="/hr/support">contact support</Link> to add credits.</p>
            )}
            <div className="grid" style={{ gridTemplateColumns: 'minmax(0, 2fr) minmax(280px, 1fr)', alignItems: 'start' }} data-layout="buy">
              <section className="card section" style={{ marginTop: 0 }}>
                <h3 style={{ marginBottom: 12 }}>Choose an amount</h3>
                <div className="packs" role="radiogroup" aria-label="Credit packs">
                  {p.packs.map((x) => (
                    <button key={x.credits} type="button" role="radio" aria-checked={x.credits === selected} className={`pack${x.credits === selected ? ' on' : ''}`} onClick={() => setSelected(x.credits)}>
                      {x.credits === 1000 && <span className="pack-tag">Popular</span>}
                      <b>{x.credits.toLocaleString()}</b><span className="small muted">credits</span>
                      <span><b>{money(x.amount_paise)}</b> {x.discount_paise > 0 && <s className="small muted">{money(x.price_paise)}</s>}</span>
                    </button>
                  ))}
                </div>
              </section>
              <section className="card section" style={{ marginTop: 0 }} aria-label="Order summary">
                <h3>Order summary</h3>
                <dl className="summary-list">
                  <div><dt>Credits</dt><dd>{pack.credits.toLocaleString()}</dd></div>
                  <div><dt>Price</dt><dd>{money(pack.price_paise)}</dd></div>
                  {pack.discount_paise > 0 && <div className="tone-ok"><dt>Discount ({p.early_bird.percent}%)<br /><span className="small muted">Early bird sale</span></dt><dd>−{money(pack.discount_paise)}</dd></div>}
                  <div className="summary-total"><dt>Total</dt><dd>{money(pack.amount_paise)}</dd></div>
                </dl>
                {covers.length > 0 && (
                  <div className="list-card" style={{ marginTop: 12 }}>
                    <p className="section-title" style={{ marginBottom: 6 }}>That covers roughly</p>
                    {covers.map(([label, n]) => <p key={label} className="small"><b>{n.toLocaleString()}</b> {label}</p>)}
                  </div>
                )}
                <p className="small" style={{ margin: '10px 0' }}>New balance after this purchase: <b>{(balance + pack.credits).toLocaleString()} credits</b></p>
                <label className="row small" style={{ alignItems: 'flex-start', flexWrap: 'nowrap' }}>
                  <input type="checkbox" checked={terms} onChange={(e) => setTerms(e.target.checked)} style={{ marginTop: 3 }} />
                  <span>I accept the Terms, Privacy Policy and Refund Policy.</span>
                </label>
                {error && <p className="alert alert-danger small" role="alert" style={{ marginTop: 10 }}>{error}</p>}
                <button className="btn btn-primary btn-block" style={{ marginTop: 12 }} disabled={!terms || busy || !p.payments_configured} onClick={() => pay(pack)}>
                  {busy ? 'Opening checkout…' : `Pay ${money(pack.amount_paise)}`}
                </button>
                {!terms && <p className="small muted" style={{ textAlign: 'center', marginTop: 6 }}>Tick the box above to continue.</p>}
                <p className="small muted row" style={{ marginTop: 12, flexWrap: 'nowrap' }}><ShieldCheck size={15} aria-hidden="true" /> Secure payment handled by Razorpay. Your card details never reach Hirelune.</p>
                <p className="small muted">Invoices use your <Link to="/hr/billing">billing details</Link>.</p>
              </section>
            </div>
          </>
        );
      }}
    </Async>
  );
}
