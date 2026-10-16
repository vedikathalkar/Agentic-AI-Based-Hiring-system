import { useState } from 'react';
import { Link } from 'react-router-dom';
import { PageHeader } from '../../components/ui';
import TicketForm from '../../components/TicketForm';

export default function ContactUs() {
  const [created, setCreated] = useState(null);
  return (
    <div>
      <PageHeader title="Contact us" subtitle="Tell us what's going on — every message becomes a support ticket you can track." />
      {created && (
        <p className="alert alert-ok" role="status">Ticket <b>#{created.ticket_id}</b> created. We emailed you a confirmation. <Link to="/support">View your tickets</Link></p>
      )}
      <section className="card section"><TicketForm onCreated={setCreated} /></section>
    </div>
  );
}
