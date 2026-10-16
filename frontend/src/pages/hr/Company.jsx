import { useEffect, useState } from 'react';
import { Link, useLocation } from 'react-router-dom';
import { api, fileObjectUrl } from '../../api';
import { useApp } from '../../context/AppContext';
import ProfileCompletion from '../../components/ProfileCompletion';
import { Async, FileUploader, PageHeader, useAsync } from '../../components/ui';
import { formatDate, pill, VERIFICATION_STATE } from '../../utils/status';

const PERSONAL = [['name', 'Full name *'], ['phone', 'Phone *'], ['designation', 'Designation *'], ['department', 'Department'],
  ['linkedin', 'LinkedIn'], ['location', 'Location']];
const COMPANY = [['name', 'Company name *'], ['official_email', 'Official company email *', 'email'], ['website', 'Company website *', 'url'],
  ['industry', 'Industry *'], ['company_size', 'Company size *', 'size'], ['headquarters', 'Headquarters / location *'],
  ['contact_number', 'Company contact number *'], ['registration_number', 'Registration number (CIN / LLPIN)'], ['gst_number', 'GST number']];
const SIZES = ['1-10', '11-50', '51-200', '201-500', '501-1000', '1000+'];

function useBlobImage(path, enabled, version) {
  const [src, setSrc] = useState(null);
  useEffect(() => {
    if (!enabled) { setSrc(null); return undefined; }
    let url;
    fileObjectUrl(path).then((u) => { url = u; setSrc(u); }).catch(() => setSrc(null));
    return () => url && URL.revokeObjectURL(url);
  }, [path, enabled, version]);
  return src;
}

export default function Company() {
  const { toast, refreshMe } = useApp();
  const location = useLocation();
  const state = useAsync(() => api.getHrProfile(), []);
  const [form, setForm] = useState(null);
  const [saving, setSaving] = useState(false);
  const [busy, setBusy] = useState(null);
  const [error, setError] = useState(null);
  const [version, setVersion] = useState(0);
  const photo = useBlobImage('/hr/profile/photo', !!state.data?.has_photo, version);
  const logo = useBlobImage('/hr/company/logo', !!state.data?.company?.has_logo, version);

  // Initialise once; uploads refresh server data without discarding unsaved edits.
  useEffect(() => {
    if (state.data) setForm((f) => f || { ...state.data, company: { ...state.data.company } });
  }, [state.data]);
  // Jump to a #section link once the form has loaded (or when the hash changes) —
  // not on every keystroke, which used to yank the page while the user typed.
  const formReady = form != null;
  useEffect(() => {
    if (formReady && location.hash) document.getElementById(location.hash.slice(1))?.scrollIntoView({ behavior: 'smooth' });
  }, [formReady, location.hash]);

  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }));
  const setC = (k) => (e) => setForm((f) => ({ ...f, company: { ...f.company, [k]: e.target.value } }));

  const save = async () => {
    setSaving(true); setError(null);
    try {
      const payload = Object.fromEntries(PERSONAL.map(([k]) => [k, form[k] ?? '']));
      payload.company = Object.fromEntries([...COMPANY.map(([k]) => k), 'description'].map((k) => [k, form.company[k] ?? '']));
      const saved = await api.updateHrProfile(payload);
      state.setData(saved);
      setForm({ ...saved, company: { ...saved.company } });
      toast(saved.note || 'Profile saved', saved.note ? 'info' : 'ok');
      refreshMe();
    } catch (e) { setError(e.message); }
    finally { setSaving(false); }
  };

  const upload = (kind) => async (file) => {
    setBusy(kind); setError(null);
    try {
      const data = kind === 'photo' ? await api.uploadHrPhoto(file) : await api.uploadCompanyLogo(file);
      state.setData(data);
      setVersion((v) => v + 1);
      toast(kind === 'photo' ? 'Photo updated' : 'Logo updated', 'ok');
    } catch (e) { setError(e.message); }
    finally { setBusy(null); }
  };

  return (
    <Async state={state} loadingLabel="Loading company profile…" errorLabel="Failed to load company profile">
      {(d) => form && (
        <div>
          <PageHeader title="Company profile" subtitle="Your details and your company's details. Completing them is required before you can request verification."
                      actions={<button className="btn btn-primary" onClick={save} disabled={saving}>{saving ? 'Saving…' : 'Save profile'}</button>} />
          {error && <p className="alert alert-danger" role="alert">{error}</p>}

          <div className="grid grid-2">
            <ProfileCompletion completion={d.completion} basePath="/hr/company" title="Complete your company profile" />
            <section className="card section" aria-label="Company verification">
              <div className="row"><h3>Company verification</h3><span className="spacer" />
                <span className={`pill ${pill(VERIFICATION_STATE, d.verification_state).cls}`}>{pill(VERIFICATION_STATE, d.verification_state).text}</span></div>
              <p className="small muted" style={{ margin: '8px 0 12px' }}>
                Profile completion and verification are separate: verification is a review of your documents by the Hirelune team.
              </p>
              <Link className="btn btn-secondary btn-sm" to="/hr/verification">Open verification</Link>
            </section>
          </div>

          <section id="personal" className="card section" aria-labelledby="personal-h">
            <h2 id="personal-h" style={{ fontSize: 18, marginBottom: 14 }}>Your details</h2>
            <div id="photo" className="row" style={{ gap: 16, marginBottom: 14 }}>
              <div className="avatar" style={{ width: 64, height: 64, fontSize: 22, overflow: 'hidden' }}>
                {photo ? <img src={photo} alt="Your profile" style={{ width: '100%', height: '100%', objectFit: 'cover' }} /> : (form.name || '?').slice(0, 1)}
              </div>
              <div style={{ flex: 1, minWidth: 240 }}><FileUploader id="hr-photo" label="Upload a profile photo" hint="JPG, PNG or WEBP · max 2 MB" accept=".jpg,.jpeg,.png,.webp" onFile={upload('photo')} busy={busy === 'photo'} /></div>
            </div>
            <div className="form-grid">
              {PERSONAL.map(([k, label]) => (
                <div key={k} className="field"><label className="field-label" htmlFor={`hp-${k}`}>{label}</label>
                  <input id={`hp-${k}`} className="input" value={form[k] || ''} onChange={set(k)} /></div>
              ))}
              <div className="field"><label className="field-label" htmlFor="hp-email">Email</label><input id="hp-email" className="input" value={form.email || ''} disabled /></div>
            </div>
          </section>

          <section id="company" className="card section" aria-labelledby="company-h">
            <h2 id="company-h" style={{ fontSize: 18, marginBottom: 6 }}>Company details</h2>
            {['verified', 'pending'].includes(d.company.verification_status) && (
              <p className="alert alert-warn small" style={{ marginBottom: 12 }}>Changing the company name, website, registration or GST number will require verification again.</p>
            )}
            <div className="form-grid">
              {COMPANY.map(([k, label, type]) => (
                <div key={k} className="field"><label className="field-label" htmlFor={`co-${k}`}>{label}</label>
                  {type === 'size' ? (
                    <select id={`co-${k}`} className="input" value={form.company[k] || ''} onChange={setC(k)}>
                      <option value="">Select…</option>{SIZES.map((s) => <option key={s} value={s}>{s} employees</option>)}
                    </select>
                  ) : <input id={`co-${k}`} className="input" type={type === 'email' ? 'email' : type === 'url' ? 'url' : 'text'}
                             placeholder={type === 'url' ? 'https://' : ''} value={form.company[k] || ''} onChange={setC(k)} />}
                </div>
              ))}
            </div>
            <div className="field"><label className="field-label" htmlFor="co-desc">Company description *</label>
              <textarea id="co-desc" className="input" rows={4} value={form.company.description || ''} onChange={setC('description')} /></div>
          </section>

          <section id="logo" className="card section" aria-labelledby="logo-h">
            <h2 id="logo-h" style={{ fontSize: 18, marginBottom: 14 }}>Company logo</h2>
            <div className="row" style={{ gap: 16 }}>
              <div style={{ width: 72, height: 72, borderRadius: 14, border: '1px solid var(--ink-100)', background: 'var(--ink-50)', display: 'grid', placeItems: 'center', overflow: 'hidden' }}>
                {logo ? <img src={logo} alt="Company logo" style={{ width: '100%', height: '100%', objectFit: 'contain' }} /> : <span className="small muted">No logo</span>}
              </div>
              <div style={{ flex: 1, minWidth: 240 }}><FileUploader id="co-logo" label={d.company.has_logo ? 'Replace logo' : 'Upload company logo'} hint="JPG, PNG or WEBP · strict 2 MB limit" accept=".jpg,.jpeg,.png,.webp" onFile={upload('logo')} busy={busy === 'logo'} /></div>
            </div>
          </section>

          <section id="identity" className="card section" aria-labelledby="docs-h">
            <h2 id="docs-h" style={{ fontSize: 18, marginBottom: 6 }}>Verification documents</h2>
            <p className="small muted">Official ID proof or visiting card, and company registration proof, are uploaded on the verification page.</p>
            <ul className="plain-list">
              {d.company.documents.length === 0 && <li className="small muted">No documents uploaded yet.</li>}
              {d.company.documents.map((doc) => (
                <li key={doc.document_id} className="row small">
                  <b>{{ id_proof: 'ID proof', visiting_card: 'Visiting card', registration_proof: 'Registration proof' }[doc.doc_type] || doc.doc_type}</b>
                  <span>{doc.file_name}</span><span className="muted">· {formatDate(doc.uploaded_at)}</span><span className="spacer" />
                  <button className="btn btn-secondary btn-sm" onClick={() => api.openCompanyDocument(doc.document_id).catch((e) => setError(e.message))}>View</button>
                </li>
              ))}
            </ul>
            <span id="registration" />
            <Link className="btn btn-secondary btn-sm" style={{ marginTop: 12 }} to="/hr/verification">Upload documents</Link>
          </section>

          <div className="row" style={{ justifyContent: 'flex-end', marginTop: 16 }}>
            <button className="btn btn-primary" onClick={save} disabled={saving}>{saving ? 'Saving…' : 'Save profile'}</button>
          </div>
        </div>
      )}
    </Async>
  );
}
