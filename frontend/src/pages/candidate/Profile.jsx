import { useEffect, useState } from 'react';
import { useLocation } from 'react-router-dom';
import { Plus, Trash2 } from 'lucide-react';
import { api, fileObjectUrl } from '../../api';
import { useApp } from '../../context/AppContext';
import ProfileCompletion from '../../components/ProfileCompletion';
import { Async, FileUploader, PageHeader, TagInput, useAsync } from '../../components/ui';
import { formatDate } from '../../utils/status';

const ENTRY_FIELDS = {
  education: [['degree', 'Degree *'], ['specialization', 'Specialization'], ['institution', 'College / university *'],
    ['start_year', 'Start year'], ['graduation_year', 'Graduation year'], ['grade', 'CGPA / percentage']],
  experience: [['company', 'Company *'], ['role', 'Role *'], ['start_date', 'Start date', 'month'], ['end_date', 'End date', 'month'],
    ['current', 'I currently work here', 'checkbox'], ['responsibilities', 'Responsibilities', 'textarea'], ['achievements', 'Achievements', 'textarea']],
  projects: [['name', 'Project name'], ['technologies', 'Technologies'], ['url', 'GitHub / project URL'], ['description', 'Description', 'textarea']],
  certifications: [['name', 'Certificate name'], ['issuer', 'Issuer'], ['date', 'Date', 'month'], ['credential_url', 'Credential URL']],
};
const SKILL_GROUPS = [['technical_skills', 'Technical skills'], ['frameworks', 'Frameworks'], ['tools', 'Tools'],
  ['languages', 'Languages'], ['soft_skills', 'Soft skills']];

function EntryList({ kind, items, onChange }) {
  const fields = ENTRY_FIELDS[kind];
  const update = (i, key, value) => onChange(items.map((it, j) => (j === i ? { ...it, [key]: value } : it)));
  return (
    <div>
      {items.map((item, i) => (
        <div key={i} className="list-card">
          <div className="form-grid">
            {fields.map(([key, label, type]) => {
              const id = `${kind}-${i}-${key}`;
              if (type === 'checkbox') return (
                <label key={key} className="row small field" htmlFor={id}><input id={id} type="checkbox" checked={!!item.current} onChange={(e) => update(i, key, e.target.checked)} /> {label}</label>
              );
              if (type === 'textarea') return (
                <div key={key} className="field" style={{ gridColumn: '1 / -1' }}><label className="field-label" htmlFor={id}>{label}</label>
                  <textarea id={id} className="input" rows={2} value={item[key] || ''} onChange={(e) => update(i, key, e.target.value)} /></div>
              );
              return (
                <div key={key} className="field"><label className="field-label" htmlFor={id}>{label}</label>
                  <input id={id} className="input" type={type === 'month' ? 'month' : 'text'} value={item[key] || ''}
                         disabled={key === 'end_date' && item.current} onChange={(e) => update(i, key, e.target.value)} /></div>
              );
            })}
          </div>
          <button type="button" className="btn btn-danger btn-sm" onClick={() => onChange(items.filter((_, j) => j !== i))}><Trash2 size={14} aria-hidden="true" /> Remove</button>
        </div>
      ))}
      <button type="button" className="btn btn-secondary btn-sm" onClick={() => onChange([...items, {}])}><Plus size={14} aria-hidden="true" /> Add {kind === 'education' ? 'education' : kind.replace(/s$/, '')}</button>
    </div>
  );
}

function Section({ id, title, children }) {
  return <section id={id} className="card section" aria-labelledby={`${id}-h`}><h2 id={`${id}-h`} style={{ fontSize: 18, marginBottom: 14 }}>{title}</h2>{children}</section>;
}

export default function CandidateProfile() {
  const { toast, refreshMe } = useApp();
  const location = useLocation();
  const state = useAsync(() => api.getCandidateProfile(), []);
  const [form, setForm] = useState(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(null);
  const [photo, setPhoto] = useState(null);

  // Initialise the editable form once; uploads refresh server data without discarding unsaved edits.
  useEffect(() => { if (state.data) setForm((f) => f || state.data); }, [state.data]);
  useEffect(() => {
    if (!state.data?.has_photo) return undefined;
    let url;
    fileObjectUrl('/candidate/profile/photo').then((u) => { url = u; setPhoto(u); }).catch(() => setPhoto(null));
    return () => url && URL.revokeObjectURL(url);
  }, [state.data?.has_photo, state.data?.updated_at]);
  // Jump to a #section link once the form has loaded (or when the hash changes) —
  // not on every keystroke, which used to yank the page while the user typed.
  const formReady = form != null;
  useEffect(() => {
    if (formReady && location.hash) document.getElementById(location.hash.slice(1))?.scrollIntoView({ behavior: 'smooth' });
  }, [formReady, location.hash]);

  const set = (key) => (e) => setForm((f) => ({ ...f, [key]: e.target ? e.target.value : e }));
  const save = async () => {
    setSaving(true); setError(null);
    try {
      const payload = {};
      ['name', 'headline', 'phone', 'location', 'date_of_birth', 'linkedin', 'github', 'portfolio',
        'education', 'experience', 'projects', 'certifications', ...SKILL_GROUPS.map(([k]) => k)].forEach((k) => { payload[k] = form[k]; });
      const saved = await api.updateCandidateProfile(payload);
      state.setData(saved);
      setForm(saved);
      toast('Profile saved', 'ok');
      refreshMe();
    } catch (e) { setError(e.message); }
    finally { setSaving(false); }
  };
  const upload = (kind) => async (file) => {
    setBusy(kind); setError(null);
    try {
      state.setData(kind === 'photo' ? await api.uploadCandidatePhoto(file) : await api.uploadProfileResume(file));
      toast(kind === 'photo' ? 'Photo updated' : 'Resume saved', 'ok');
    } catch (e) { setError(e.message); }
    finally { setBusy(null); }
  };

  return (
    <Async state={state} loadingLabel="Loading your profile…" errorLabel="Failed to load your profile">
      {() => form && (
        <div>
          <PageHeader title="My profile" subtitle="Employers see this profile when you apply. Completion is calculated from what you've saved."
                      actions={<button className="btn btn-primary" onClick={save} disabled={saving}>{saving ? 'Saving…' : 'Save profile'}</button>} />
          {error && <p className="alert alert-danger" role="alert">{error}</p>}
          <ProfileCompletion completion={state.data.completion} basePath="/profile" />

          <Section id="personal" title="Personal details">
            <div className="row" style={{ gap: 16, marginBottom: 14 }}>
              <div className="avatar" style={{ width: 64, height: 64, fontSize: 22, overflow: 'hidden' }}>
                {photo ? <img src={photo} alt="Profile" style={{ width: '100%', height: '100%', objectFit: 'cover' }} /> : (form.name || '?').slice(0, 1)}
              </div>
              <div style={{ flex: 1, minWidth: 240 }}><FileUploader label="Upload a profile photo" hint="JPG, PNG or WEBP · max 2 MB" accept="image/*" onFile={upload('photo')} busy={busy === 'photo'} id="photo" /></div>
            </div>
            <div className="form-grid">
              <div className="field"><label className="field-label" htmlFor="p-name">Full name *</label><input id="p-name" className="input" value={form.name || ''} onChange={set('name')} /></div>
              <div className="field"><label className="field-label" htmlFor="p-email">Email</label><input id="p-email" className="input" value={form.email || ''} disabled /></div>
              <div className="field"><label className="field-label" htmlFor="p-phone">Phone *</label><input id="p-phone" className="input" value={form.phone || ''} onChange={set('phone')} /></div>
              <div className="field"><label className="field-label" htmlFor="p-loc">Location *</label><input id="p-loc" className="input" value={form.location || ''} onChange={set('location')} /></div>
              <div className="field"><label className="field-label" htmlFor="p-dob">Date of birth</label><input id="p-dob" type="date" className="input" value={form.date_of_birth || ''} onChange={set('date_of_birth')} /></div>
              <div className="field"><label className="field-label" htmlFor="p-head">Headline</label><input id="p-head" className="input" placeholder="e.g. Data analyst · SQL & Tableau" value={form.headline || ''} onChange={set('headline')} /></div>
            </div>
          </Section>

          <Section id="links" title="Professional links">
            <div className="form-grid">
              <div className="field"><label className="field-label" htmlFor="p-li">LinkedIn</label><input id="p-li" className="input" value={form.linkedin || ''} onChange={set('linkedin')} /></div>
              <div className="field"><label className="field-label" htmlFor="p-gh">GitHub</label><input id="p-gh" className="input" value={form.github || ''} onChange={set('github')} /></div>
              <div className="field"><label className="field-label" htmlFor="p-pf">Portfolio</label><input id="p-pf" className="input" value={form.portfolio || ''} onChange={set('portfolio')} /></div>
            </div>
          </Section>

          <Section id="education" title="Education"><EntryList kind="education" items={form.education || []} onChange={set('education')} /></Section>
          <Section id="experience" title="Experience"><EntryList kind="experience" items={form.experience || []} onChange={set('experience')} /></Section>
          <Section id="skills" title="Skills">
            <div style={{ display: 'grid', gap: 14 }}>
              {SKILL_GROUPS.map(([key, label]) => <TagInput key={key} id={`sk-${key}`} label={label} value={form[key] || []} onChange={set(key)} placeholder="Type and press Enter" />)}
            </div>
          </Section>
          <Section id="projects" title="Projects"><EntryList kind="projects" items={form.projects || []} onChange={set('projects')} /></Section>
          <Section id="certifications" title="Certifications"><EntryList kind="certifications" items={form.certifications || []} onChange={set('certifications')} /></Section>

          <Section id="resume" title="Resume">
            {state.data.resume_file_name ? (
              <div className="row" style={{ marginBottom: 12 }}>
                <span>✓ <b>{state.data.resume_file_name}</b> · uploaded {formatDate(state.data.resume_uploaded_at, true)}</span>
                <button className="btn btn-secondary btn-sm" onClick={() => api.openProfileResume()}>View resume</button>
                <button className="btn btn-secondary btn-sm" onClick={() => api.openProfileResume(true)}>Download</button>
              </div>
            ) : <p className="small muted" style={{ marginBottom: 12 }}>No resume uploaded yet. Your profile resume can be reused when applying.</p>}
            <FileUploader label={state.data.resume_file_name ? 'Replace resume' : 'Upload resume'} hint="PDF or DOCX · max 5 MB" accept=".pdf,.docx" onFile={upload('resume')} busy={busy === 'resume'} id="resume-up" />
          </Section>

          <div className="row" style={{ justifyContent: 'flex-end', marginTop: 16 }}>
            <button className="btn btn-primary" onClick={save} disabled={saving}>{saving ? 'Saving…' : 'Save profile'}</button>
          </div>
        </div>
      )}
    </Async>
  );
}
