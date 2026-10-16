import { Link } from 'react-router-dom';
import { api } from '../../api';
import { Async, EmptyState, PageHeader, useAsync } from '../../components/ui';
import { formatDate, OFFER_STATUS, pill } from '../../utils/status';

export default function CandidateOffers() {
  const state = useAsync(() => api.getOffers(), []);
  return (
    <>
      <PageHeader title="Offers" subtitle="Offer letters sent to you by employers." />
      <Async state={state} loadingLabel="Loading offers…" errorLabel="Failed to load offers">
        {(rows) => rows.length === 0 ? <EmptyState title="No offers yet">Offers appear here after an employer sends one.</EmptyState> : (
          <div style={{ display: 'grid', gap: 12 }}>
            {rows.map((o) => {
              const p = pill(OFFER_STATUS, o.status);
              return (
                <article key={o.offer_id} className="card section" style={{ marginTop: 0 }}>
                  <div className="row"><h3>{o.job_title}</h3><span className={`pill ${p.cls}`}>{p.text}</span><span className="spacer" />
                    <Link className="btn btn-primary btn-sm" to={`/offers/${o.offer_id}`}>View Offer</Link></div>
                  <p className="small muted">{o.company_name}</p>
                  <dl className="kv" style={{ marginTop: 10 }}>
                    <dt>Joining date</dt><dd>{o.joining_date || '—'}</dd>
                    <dt>Compensation</dt><dd>{o.ctc_amount || '—'}</dd>
                    <dt>Received</dt><dd>{formatDate(o.sent_at, true)}</dd>
                    {['sent', 'viewed'].includes(o.status) && (<><dt>Respond by</dt><dd>{formatDate(o.expires_at)}</dd></>)}
                  </dl>
                </article>
              );
            })}
          </div>
        )}
      </Async>
    </>
  );
}
