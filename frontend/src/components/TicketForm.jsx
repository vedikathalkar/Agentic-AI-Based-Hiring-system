import { useEffect, useState } from 'react';
import { api, session } from '../api';
import { FileUploader } from './ui';

const CATEGORIES = ['Technical issue', 'Application issue', 'Assessment issue', 'Interview issue', 'Payment', 'Account', 'Other'];

export default function TicketForm({ onCreated }) {
  const user = session.user();
  const [form, setForm] = useState({ name: user.name || '', email: user.email || '', category: 'Technical issue', subject: '', message: '' });
  const [file, setFile] = useState(null);
  const [categories, setCategories] = useState(CATEGORIES);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  useEffect(() => { api.supportCategories().then((c) => setCategories(c.categories)).catch(() => {}); }, []);
  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }));
  const submit = async (e) => {
    e.preventDefault();
    setBusy(true); setError(null);
    try {
      const t = await api.createTicket({ ...form, attachment: file || undefined });
      setForm((f) => ({ ...f, subject: '', message: '' })); setFile(null);
      onCreated?.(t);
    } catch (err) { setError(err.message); }
    finally { setBusy(false); }
  };
  return (
    <form onSubmit={submit}>
      <div className="form-grid">
        <div className="field"><label className="field-label" htmlFor="t-name">Name</label><input id="t-name" className="input" value={form.name} onChange={set('name')} required /></div>
        <div className="field"><label className="field-label" htmlFor="t-email">Email</label><input id="t-email" type="email" className="input" value={form.email} onChange={set('email')} required /></div>
        <div className="field"><label className="field-label" htmlFor="t-cat">Category</label>
          <select id="t-cat" className="input" value={form.category} onChange={set('category')}>{categories.map((c) => <option key={c}>{c}</option>)}</select></div>
      </div>
      <div className="field"><label className="field-label" htmlFor="t-sub">Subject</label><input id="t-sub" className="input" value={form.subject} onChange={set('subject')} required minLength={3} maxLength={200} /></div>
      <div className="field"><label className="field-label" htmlFor="t-msg">Message</label><textarea id="t-msg" className="input" rows={5} value={form.message} onChange={set('message')} required minLength={5} /></div>
      <FileUploader label="Attach a file (optional)" hint="Screenshot or document · max 5 MB" accept="image/*,.pdf,.doc,.docx,.txt" onFile={setFile} fileName={file?.name} id="t-file" />
      {error && <p className="alert alert-danger" role="alert" style={{ marginTop: 12 }}>{error}</p>}
      <button className="btn btn-primary" style={{ marginTop: 14 }} disabled={busy}>{busy ? 'Sending…' : 'Submit request'}</button>
    </form>
  );
}
