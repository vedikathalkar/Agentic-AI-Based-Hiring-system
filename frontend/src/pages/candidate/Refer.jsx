import { Copy } from 'lucide-react';
import { api } from '../../api';
import { useApp } from '../../context/AppContext';
import { Async, PageHeader, StatCard, useAsync } from '../../components/ui';
import { formatDate } from '../../utils/status';

const STATUS = { signed_up: ['Signed up — pending', 'pill-warn'], qualified: ['Qualified', 'pill-brand'], rewarded: ['Rewarded', 'pill-ok'] };

export default function Refer() {
  const { toast } = useApp();
  const state = useAsync(() => api.createReferral(), []);
  const copy = async (text) => {
    try { await navigator.clipboard.writeText(text); toast('Copied to clipboard', 'ok'); }
    catch { toast('Copy blocked by the browser — select and copy manually', 'danger'); }
  };
  return (
    <Async state={state} loadingLabel="Loading referrals…" errorLabel="Failed to load referrals">
      {(r) => (
        <>
          <PageHeader title="Refer & Earn" subtitle={`Earn ${r.reward_per_referral} credits for every friend who joins. ${r.qualifying_event}`} />
          <section className="card section" style={{ marginTop: 0 }}>
            <p className="section-title">Your referral code</p>
            <div className="row"><code style={{ fontSize: 20, fontWeight: 700 }}>{r.code}</code><button className="btn btn-secondary btn-sm" onClick={() => copy(r.code)}><Copy size={14} aria-hidden="true" /> Copy code</button></div>
            <p className="section-title" style={{ marginTop: 14 }}>Your referral link</p>
            <div className="row"><input className="input" readOnly value={r.link} aria-label="Referral link" style={{ flex: 1, minWidth: 220 }} /><button className="btn btn-primary btn-sm" onClick={() => copy(r.link)}><Copy size={14} aria-hidden="true" /> Copy link</button></div>
          </section>
          <div className="grid grid-stats" style={{ marginTop: 16 }}>
            <StatCard label="Successful referrals" value={r.successful} tone="ok" />
            <StatCard label="Pending referrals" value={r.pending} tone="gold" />
            <StatCard label="Credits earned" value={r.credits_earned} />
            <StatCard label="Your credit balance" value={r.credit_balance} hint="Used for ATS checks" />
          </div>
          <section className="card section">
            <h3>Your referrals</h3>
            {r.referrals.length === 0 ? <p className="small muted" style={{ marginTop: 8 }}>No one has joined with your link yet.</p> : (
              <ul className="plain-list">{r.referrals.map((x) => (
                <li key={x.referral_id} className="row"><b>{x.name}</b><span className={`pill ${STATUS[x.status][1]}`}>{STATUS[x.status][0]}</span><span className="spacer" />
                  <span className="small muted">Joined {formatDate(x.created_at)}{x.reward_credits ? ` · +${x.reward_credits} credits` : ''}</span></li>
              ))}</ul>
            )}
          </section>
        </>
      )}
    </Async>
  );
}
