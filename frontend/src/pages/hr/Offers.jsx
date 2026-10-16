import { useEffect, useMemo, useRef, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { Bold, CircleCheck, Eye, FileDown, Heading, List, Minus, Plus, Save, Send, Trash2 } from 'lucide-react';
import { api } from '../../api';
import { useApp } from '../../context/AppContext';
import { Async, EmptyState, Modal, PageHeader, Tabs, useAsync } from '../../components/ui';
import { formatDate, OFFER_STATUS, pill } from '../../utils/status';

const ELIGIBLE = ['assessed', 'shortlisted', 'scheduled', 'interviewed', 'selected', 'offered'];
const LABELS = {
  candidate_name: 'Candidate name', candidate_email: 'Candidate email', company_name: 'Company', job_title: 'Designation',
  department: 'Department', location: 'Work location', offer_date: 'Offer date', joining_date: 'Joining date',
  ctc_amount: 'Annual CTC', reporting_manager: 'Reporting manager', employment_type: 'Employment type',
  probation_period: 'Probation period', notice_period: 'Notice period', working_hours: 'Working hours',
  benefits: 'Benefits', hr_name: 'Signed by', hr_designation: 'Signatory designation', acceptance_deadline: 'Respond by',
};
const GROUPS = [
  ['Candidate & role', ['candidate_name', 'job_title', 'department', 'employment_type', 'location', 'reporting_manager']],
  ['Compensation', ['ctc_amount', 'benefits']],
  ['Joining & terms', ['joining_date', 'probation_period', 'notice_period', 'working_hours', 'offer_date']],
  ['Signature', ['hr_name', 'hr_designation', 'company_name']],
];
const REQUIRED = new Set(['joining_date', 'ctc_amount']);
const AUTO = new Set(['acceptance_deadline', 'candidate_email']);
const TOKEN = /\{\{\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*\}\}/g;
const SAMPLE = { candidate_name: 'Asha Verma', candidate_email: 'asha@example.com', company_name: 'Your Company', job_title: 'Software Engineer',
  department: 'Engineering', location: 'Pune · Hybrid', offer_date: '01 October 2026', joining_date: '01 December 2026', ctc_amount: '₹12,00,000 per annum',
  reporting_manager: 'Rahul Mehta', employment_type: 'Full-time', probation_period: '6 months', notice_period: '30 days',
  working_hours: 'Monday to Friday, 9:30 AM to 6:30 PM', benefits: 'Health insurance and paid leave', hr_name: 'Priya Sharma',
  hr_designation: 'HR Manager', acceptance_deadline: '15 October 2026' };

const tokensIn = (text) => [...new Set([...(text || '').matchAll(TOKEN)].map((m) => m[1]))];
const inr = (raw) => {
  const n = Number(String(raw).replace(/[^\d.]/g, ''));
  return n ? `₹${n.toLocaleString('en-IN')} per annum` : raw;
};
const toISO = (v) => { const d = new Date(v); return Number.isNaN(d.getTime()) ? '' : new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0, 10); };
const fromISO = (iso) => (iso ? new Date(`${iso}T00:00:00`).toLocaleDateString('en-GB', { day: '2-digit', month: 'long', year: 'numeric' }) : '');

/** Renders the same "markdown-lite" the PDF uses: # heading, **bold line**, - bullet, ---. */
function LetterPreview({ text, values, company, onPick }) {
  const fillPlain = (text, k) => text.split(/(\{\{\s*[a-zA-Z_][a-zA-Z0-9_]*\s*\}\})/g).map((part, i) => {
    const m = part.match(/^\{\{\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*\}\}$/);
    if (!m) return <span key={`${k}-${i}`}>{part}</span>;
    const v = values[m[1]];
    return v ? <span key={`${k}-${i}`} className="letter-value">{v}</span>
      : <button key={`${k}-${i}`} type="button" className="letter-missing" title={`Fill in “${LABELS[m[1]] || m[1]}”`} onClick={() => onPick?.(m[1])}>{LABELS[m[1]] || m[1]}</button>;
  });
  // Inline **bold** first, then {{fields}} inside each piece.
  const fill = (line, k) => line.split(/(\*\*.+?\*\*)/g).map((seg, j) => (
    /^\*\*.+\*\*$/.test(seg) ? <b key={`${k}b${j}`}>{fillPlain(seg.slice(2, -2), `${k}b${j}`)}</b> : <span key={`${k}s${j}`}>{fillPlain(seg, `${k}s${j}`)}</span>
  ));
  const blocks = [];
  let list = null;
  (text || '').replace(/\r\n/g, '\n').split('\n').forEach((raw, i) => {
    const line = raw.trim();
    if (/^[-*•]\s+/.test(line)) { (list ||= []).push(<li key={i}>{fill(line.replace(/^[-*•]\s+/, ''), i)}</li>); return; }
    if (list) { blocks.push(<ul key={`ul${i}`}>{list}</ul>); list = null; }
    if (/^(---|\*\*\*|___)$/.test(line)) blocks.push(<hr key={i} />);
    else if (/^#{1,2}\s/.test(line)) blocks.push(<h4 key={i}>{fill(line.replace(/^#+\s*/, ''), i)}</h4>);
    else if (/^\*\*.+\*\*$/.test(line)) blocks.push(<p key={i}><b>{fill(line.slice(2, -2), i)}</b></p>);
    else if (!line) blocks.push(<div key={i} className="letter-gap" />);
    else blocks.push(<p key={i}>{fill(raw, i)}</p>);
  });
  if (list) blocks.push(<ul key="ul-end">{list}</ul>);
  return (
    <div className="letter letter-rich" aria-label="Offer letter preview">
      <div className="letter-head"><b>{values.company_name || company || 'Company name'}</b></div>
      {blocks}
    </div>
  );
}

/** Plain-text letter editor with a formatting toolbar that works at the cursor. */
function LetterTextEditor({ value, onChange, fields, rows = 18 }) {
  const ref = useRef(null);
  const apply = (fn) => {
    const el = ref.current;
    if (!el) return;
    const { selectionStart: a, selectionEnd: b } = el;
    const [next, caret] = fn(value, a, b);
    onChange(next);
    requestAnimationFrame(() => { el.focus(); el.setSelectionRange(caret, caret); });
  };
  const insert = (text) => apply((v, a, b) => [v.slice(0, a) + text + v.slice(b), a + text.length]);
  const linePrefix = (prefix) => apply((v, a) => { const s = v.lastIndexOf('\n', a - 1) + 1; return [v.slice(0, s) + prefix + v.slice(s), a + prefix.length]; });
  const wrap = () => apply((v, a, b) => [`${v.slice(0, a)}**${v.slice(a, b) || 'bold text'}**${v.slice(b)}`, b + 4 + (a === b ? 9 : 0)]);
  return (
    <div className="letter-editor">
      <div className="letter-toolbar" role="toolbar" aria-label="Formatting">
        <button type="button" className="icon-btn" title="Section heading" aria-label="Heading" onClick={() => linePrefix('# ')}><Heading size={15} /></button>
        <button type="button" className="icon-btn" title="Bold" aria-label="Bold" onClick={wrap}><Bold size={15} /></button>
        <button type="button" className="icon-btn" title="Bullet point" aria-label="Bullet" onClick={() => linePrefix('- ')}><List size={15} /></button>
        <button type="button" className="icon-btn" title="Divider line" aria-label="Divider" onClick={() => insert('\n---\n')}><Minus size={15} /></button>
        <span className="letter-toolbar-sep" />
        <label className="sr-only" htmlFor="ins-field">Insert field</label>
        <select id="ins-field" className="input input-sm" style={{ width: 'auto' }} value="" onChange={(e) => { if (e.target.value) insert(`{{${e.target.value}}}`); }}>
          <option value="">Insert field at cursor…</option>
          {fields.map((k) => <option key={k} value={k}>{LABELS[k] || k}</option>)}
        </select>
      </div>
      <label className="sr-only" htmlFor="letter-text">Letter text</label>
      <textarea id="letter-text" ref={ref} className="input letter-textarea" rows={rows} value={value} onChange={(e) => onChange(e.target.value)} spellCheck />
      <p className="small muted">Formatting: <code># Heading</code> · <code>**bold line**</code> · <code>- bullet</code> · <code>---</code> divider · fields look like <code>{'{{joining_date}}'}</code>. Type any new <code>{'{{your_field}}'}</code> to add a custom field.</p>
    </div>
  );
}

function FieldInput({ k, value, onChange, required }) {
  const id = `of-${k}`;
  const common = { id, className: `input${required && !value ? ' input-missing' : ''}`, value: value || '', onChange: (e) => onChange(e.target.value) };
  let control;
  if (k === 'employment_type') {
    control = <select {...common}>{['Full-time', 'Part-time', 'Contract', 'Internship'].map((x) => <option key={x}>{x}</option>)}</select>;
  } else if (k === 'joining_date' || k === 'offer_date') {
    control = <input {...common} type="date" value={toISO(value)} onChange={(e) => onChange(fromISO(e.target.value))} />;
  } else if (k === 'benefits' || k === 'working_hours') {
    control = <textarea {...common} rows={2} />;
  } else if (k === 'ctc_amount') {
    control = (
      <div className="row" style={{ flexWrap: 'nowrap', gap: 6 }}>
        <input {...common} placeholder="e.g. 1200000" onBlur={(e) => onChange(inr(e.target.value))} inputMode="numeric" />
      </div>
    );
  } else {
    control = <input {...common} />;
  }
  return (
    <div className="field" data-field={k}>
      <label className="field-label" htmlFor={id}>{LABELS[k] || k.replace(/_/g, ' ')}{required ? ' *' : ''}</label>
      {control}
    </div>
  );
}

function Editor({ offer, templates, onChanged, onRemoved, onUpdated }) {
  const { toast, refreshMe } = useApp();
  const draft = offer.status === 'draft';
  const [fields, setFields] = useState(offer.fields || {});
  const [content, setContent] = useState(offer.template_content || '');
  const [validDays, setValidDays] = useState(offer.valid_days || 14);
  const [view, setView] = useState('preview');
  const [saveState, setSaveState] = useState('saved');   // saved | dirty | saving | error
  const [busy, setBusy] = useState(null);
  const [error, setError] = useState(null);
  const [confirm, setConfirm] = useState(null);
  const formRef = useRef(null);
  const first = useRef(true);

  useEffect(() => {
    setFields(offer.fields || {}); setContent(offer.template_content || ''); setValidDays(offer.valid_days || 14);
    setError(null); setSaveState('saved'); first.current = true;
  }, [offer.offer_id]); // eslint-disable-line react-hooks/exhaustive-deps

  const used = useMemo(() => tokensIn(content), [content]);
  const custom = used.filter((k) => !LABELS[k]);
  const editable = used.filter((k) => !AUTO.has(k));
  const missing = editable.filter((k) => !String(fields[k] || '').trim());
  const values = { ...fields, acceptance_deadline: fromISO(new Date(Date.now() + validDays * 86400000).toISOString().slice(0, 10)) };

  // Autosave drafts 1.2 s after the last change.
  useEffect(() => {
    if (!draft) return undefined;
    if (first.current) { first.current = false; return undefined; }
    setSaveState('dirty');
    const id = setTimeout(async () => {
      setSaveState('saving');
      try { onUpdated?.(await api.updateOffer(offer.offer_id, { template_content: content, fields, valid_days: Number(validDays) })); setSaveState('saved'); }
      catch (e) { setSaveState('error'); setError(e.message); }
    }, 1200);
    return () => clearTimeout(id);
  }, [fields, content, validDays]); // eslint-disable-line react-hooks/exhaustive-deps

  const saveNow = async () => {
    setSaveState('saving'); setError(null);
    try { const o = await api.updateOffer(offer.offer_id, { template_content: content, fields, valid_days: Number(validDays) }); setSaveState('saved'); onUpdated?.(o); return o; }
    catch (e) { setSaveState('error'); setError(e.message); return null; }
  };
  const pick = (k) => {
    const el = formRef.current?.querySelector(`[data-field="${k}"] .input`);
    if (el) { el.scrollIntoView({ behavior: 'smooth', block: 'center' }); el.focus({ preventScroll: true }); }
  };
  const run = async (kind, fn, ok) => {
    setBusy(kind); setError(null);
    try { const r = await fn(); if (ok) toast(ok, 'ok'); return r; } catch (e) { setError(e.message); return null; } finally { setBusy(null); }
  };
  const send = async () => {
    setConfirm(null);
    if (!(await saveNow())) return;
    const o = await run('send', () => api.sendOffer(offer.offer_id), 'Offer sent — the candidate has been emailed a secure link');
    if (o) { refreshMe(); onChanged(o); }
  };
  const preview = async () => { if (draft && saveState !== 'saved') await saveNow(); run('pdf', () => api.previewOfferPdf(offer.offer_id)); };
  const saveAsTemplate = async (name) => {
    setConfirm(null);
    await run('tpl', () => api.createOfferTemplate({ name, content }), 'Saved as a template');
  };
  const p = pill(OFFER_STATUS, offer.status);

  if (!draft) {
    return (
      <div>
        <div className="row" style={{ marginBottom: 10 }}>
          <h3>{offer.candidate_name} · {offer.job_title}</h3><span className={`pill ${p.cls}`}>{p.text}</span><span className="spacer" />
          <button className="btn btn-secondary btn-sm" onClick={() => run('pdf', () => api.openOfferPdf(offer.offer_id))}><FileDown size={14} aria-hidden="true" /> PDF</button>
          {offer.status !== 'accepted' && <button className="btn btn-secondary btn-sm" onClick={async () => { const o = await run('rev', () => api.reviseOffer(offer.offer_id)); if (o) onChanged(o); }}>Create revision</button>}
        </div>
        <ol className="offer-timeline">
          <li className="on">Created {formatDate(offer.created_at, true)}</li>
          <li className={offer.sent_at ? 'on' : ''}>Sent {formatDate(offer.sent_at, true)} · email {offer.email_status || '—'}</li>
          <li className={offer.viewed_at ? 'on' : ''}>{offer.viewed_at ? `Viewed ${formatDate(offer.viewed_at, true)}` : 'Not viewed yet'}</li>
          <li className={['accepted', 'rejected'].includes(offer.status) ? 'on' : ''}>
            {offer.status === 'accepted' ? `Accepted ${formatDate(offer.accepted_at, true)}` : offer.status === 'rejected' ? `Declined ${formatDate(offer.rejected_at, true)}` : `Respond by ${formatDate(offer.expires_at)}`}
          </li>
        </ol>
        {offer.response_note && <p className="small" style={{ margin: '8px 0' }}>Candidate note: “{offer.response_note}”</p>}
        <LetterPreview text={offer.content} values={{}} company={offer.company_name} />
        {error && <p className="alert alert-danger" role="alert" style={{ marginTop: 12 }}>{error}</p>}
        <p className="small muted" style={{ marginTop: 8 }}>Sent offers are kept exactly as the candidate received them. To change one, create a revision.</p>
      </div>
    );
  }

  return (
    <div>
      <div className="row" style={{ marginBottom: 12 }}>
        <h3>{offer.candidate_name} · {offer.job_title}</h3><span className={`pill ${p.cls}`}>{p.text}</span>
        {offer.revision_of_id && <span className="small muted">revision of #{offer.revision_of_id}</span>}
        <span className="spacer" />
        <span className={`small save-state save-${saveState}`} aria-live="polite">
          {saveState === 'saving' ? 'Saving…' : saveState === 'dirty' ? 'Unsaved changes' : saveState === 'error' ? 'Not saved' : <><CircleCheck size={13} aria-hidden="true" /> Saved</>}
        </span>
      </div>
      <div className="offer-progress">
        <div className="progress" role="progressbar" aria-label="Letter completeness" aria-valuemin={0} aria-valuemax={editable.length} aria-valuenow={editable.length - missing.length}>
          <span className="bg-brand" style={{ width: `${editable.length ? ((editable.length - missing.length) / editable.length) * 100 : 100}%` }} />
        </div>
        <span className="small">{missing.length === 0 ? 'All fields filled — ready to send' : <>{missing.length} field{missing.length === 1 ? '' : 's'} left: {missing.slice(0, 4).map((k) => <button key={k} type="button" className="link-btn" onClick={() => pick(k)}>{LABELS[k] || k}</button>)}{missing.length > 4 ? '…' : ''}</>}</span>
      </div>

      <div className="offer-workspace">
        <div ref={formRef} className="offer-form">
          {GROUPS.map(([title, keys]) => {
            const shown = keys.filter((k) => used.includes(k) || REQUIRED.has(k));
            if (!shown.length) return null;
            return (
              <fieldset key={title} className="offer-group"><legend>{title}</legend>
                {shown.map((k) => <FieldInput key={k} k={k} value={fields[k]} required={REQUIRED.has(k)} onChange={(v) => setFields((f) => ({ ...f, [k]: v }))} />)}
              </fieldset>
            );
          })}
          <fieldset className="offer-group"><legend>Offer validity</legend>
            <div className="field"><label className="field-label" htmlFor="of-valid">Candidate can respond for <b>{validDays}</b> days (until {values.acceptance_deadline})</label>
              <input id="of-valid" type="range" min={1} max={60} value={validDays} onChange={(e) => setValidDays(Number(e.target.value))} /></div>
          </fieldset>
          <fieldset className="offer-group"><legend>Custom fields</legend>
            {custom.length === 0 && <p className="small muted">Add your own field (e.g. joining bonus) — it appears in the letter and must be filled before sending.</p>}
            {custom.map((k) => <FieldInput key={k} k={k} value={fields[k]} onChange={(v) => setFields((f) => ({ ...f, [k]: v }))} />)}
            <button type="button" className="btn btn-secondary btn-sm" onClick={() => {
              const name = window.prompt('Field name (letters, numbers, underscores), e.g. joining_bonus');
              const key = (name || '').trim().toLowerCase().replace(/[^a-z0-9_]+/g, '_').replace(/^_+|_+$/g, '');
              if (key) { setContent((c) => `${c.trimEnd()}\n- ${key.replace(/_/g, ' ').replace(/^./, (x) => x.toUpperCase())}: {{${key}}}\n`); setView('edit'); }
            }}><Plus size={14} aria-hidden="true" /> Add custom field</button>
          </fieldset>
        </div>

        <div className="offer-canvas">
          <div className="row" style={{ marginBottom: 8 }}>
            <Tabs tabs={[['preview', 'Preview'], ['edit', 'Edit letter text']]} value={view} onChange={setView} />
            <span className="spacer" />
            <label className="sr-only" htmlFor="of-tpl">Start from template</label>
            <select id="of-tpl" className="input input-sm" style={{ width: 210 }} value="" onChange={(e) => {
              const t = templates.find((x) => String(x.template_id) === e.target.value);
              if (t && window.confirm(`Replace the letter text with “${t.name}”? Field values are kept.`)) setContent(t.content);
            }}>
              <option value="">Load a template…</option>{templates.map((t) => <option key={t.template_id} value={t.template_id}>{t.name}</option>)}
            </select>
          </div>
          {view === 'preview'
            ? <LetterPreview text={content} values={values} company={offer.company_name} onPick={pick} />
            : <LetterTextEditor value={content} onChange={setContent} fields={[...Object.keys(LABELS), ...custom]} />}
        </div>
      </div>

      {error && <p className="alert alert-danger" role="alert" style={{ marginTop: 12 }}>{error}</p>}
      <div className="row offer-actions">
        <button className="btn btn-danger btn-sm" disabled={!!busy} onClick={() => setConfirm('delete')}><Trash2 size={14} aria-hidden="true" /> Delete draft</button>
        <button className="btn btn-secondary btn-sm" disabled={!!busy} onClick={() => setConfirm('template')}><Save size={14} aria-hidden="true" /> Save as template</button>
        <span className="spacer" />
        <button className="btn btn-secondary" disabled={!!busy} onClick={preview}><Eye size={15} aria-hidden="true" /> {busy === 'pdf' ? 'Opening…' : 'Preview PDF'}</button>
        <button className="btn btn-primary" disabled={!!busy || missing.length > 0} title={missing.length ? 'Fill in every field first' : ''} onClick={() => setConfirm('send')}>
          <Send size={15} aria-hidden="true" /> {busy === 'send' ? 'Sending…' : 'Send offer'}
        </button>
      </div>

      {confirm === 'send' && (
        <Modal title="Send this offer?" onClose={() => setConfirm(null)}
               footer={<><button className="btn btn-secondary" onClick={() => setConfirm(null)}>Cancel</button><button className="btn btn-primary" onClick={send}>Send offer</button></>}>
          <dl className="summary-list">
            <div><dt>Candidate</dt><dd>{values.candidate_name}</dd></div>
            <div><dt>Role</dt><dd>{values.job_title}</dd></div>
            <div><dt>CTC</dt><dd>{values.ctc_amount}</dd></div>
            <div><dt>Joining</dt><dd>{values.joining_date}</dd></div>
            <div><dt>Respond by</dt><dd>{values.acceptance_deadline}</dd></div>
          </dl>
          <p className="small muted" style={{ marginTop: 10 }}>The letter is frozen, a PDF is generated and the candidate is emailed a secure link. Any earlier unanswered offer for this application is withdrawn.</p>
        </Modal>
      )}
      {confirm === 'delete' && (
        <Modal title="Delete this draft?" onClose={() => setConfirm(null)}
               footer={<><button className="btn btn-secondary" onClick={() => setConfirm(null)}>Cancel</button>
                 <button className="btn btn-danger" onClick={async () => { setConfirm(null); const r = await run('del', () => api.deleteOffer(offer.offer_id), 'Draft deleted'); if (r) onRemoved(); }}>Delete</button></>}>
          <p>The draft is removed. Sent offers are never deleted.</p>
        </Modal>
      )}
      {confirm === 'template' && <TemplateNameModal onClose={() => setConfirm(null)} onSave={saveAsTemplate} defaultName={`${offer.job_title || 'Offer'} letter`} />}
    </div>
  );
}

function TemplateNameModal({ onClose, onSave, defaultName }) {
  const [name, setName] = useState(defaultName);
  return (
    <Modal title="Save as template" onClose={onClose}
           footer={<><button className="btn btn-secondary" onClick={onClose}>Cancel</button><button className="btn btn-primary" disabled={name.trim().length < 2} onClick={() => onSave(name.trim())}>Save</button></>}>
      <div className="field"><label className="field-label" htmlFor="tpl-name">Template name</label><input id="tpl-name" className="input" value={name} onChange={(e) => setName(e.target.value)} /></div>
      <p className="small muted">Saves the letter text with its {'{{fields}}'}, not this candidate's values.</p>
    </Modal>
  );
}

function Templates({ data, reload }) {
  const { toast } = useApp();
  const [editing, setEditing] = useState(null);
  const [view, setView] = useState('edit');
  const [error, setError] = useState(null);
  const save = async () => {
    setError(null);
    try {
      if (editing.template_id && !editing.built_in) await api.updateOfferTemplate(editing.template_id, { name: editing.name, content: editing.content });
      else await api.createOfferTemplate({ name: editing.name, content: editing.content });
      setEditing(null); reload(); toast('Template saved', 'ok');
    } catch (e) { setError(e.message); }
  };
  const remove = async (t) => {
    if (!window.confirm(`Delete template “${t.name}”?`)) return;
    try { await api.deleteOfferTemplate(t.template_id); reload(); toast('Template deleted', 'ok'); } catch (e) { toast(e.message, 'danger'); }
  };
  if (editing) {
    const custom = tokensIn(editing.content).filter((k) => !LABELS[k]);
    return (
      <section className="card section" style={{ marginTop: 0 }}>
        <div className="row" style={{ marginBottom: 10 }}>
          <div className="field" style={{ flex: 1, marginBottom: 0 }}><label className="field-label" htmlFor="tp-name">Template name</label>
            <input id="tp-name" className="input" value={editing.name} onChange={(e) => setEditing({ ...editing, name: e.target.value })} /></div>
        </div>
        <div className="row" style={{ marginBottom: 8 }}><Tabs tabs={[['edit', 'Edit'], ['preview', 'Preview with sample data']]} value={view} onChange={setView} /></div>
        {view === 'edit' ? <LetterTextEditor value={editing.content} onChange={(c) => setEditing({ ...editing, content: c })} fields={[...Object.keys(LABELS), ...custom]} rows={22} />
          : <LetterPreview text={editing.content} values={SAMPLE} />}
        {error && <p className="alert alert-danger small" role="alert" style={{ marginTop: 10 }}>{error}</p>}
        <div className="row offer-actions"><span className="spacer" />
          <button className="btn btn-secondary" onClick={() => setEditing(null)}>Cancel</button>
          <button className="btn btn-primary" disabled={editing.name.trim().length < 2 || editing.content.trim().length < 20} onClick={save}>Save template</button></div>
      </section>
    );
  }
  return (
    <>
      <div className="row" style={{ marginBottom: 10 }}><p className="small muted" style={{ flex: 1 }}>Templates use {'{{fields}}'} and simple formatting. Built-in templates can be copied and changed.</p>
        <button className="btn btn-primary" onClick={() => { setView('edit'); setEditing({ name: 'New template', content: data.templates[0]?.content || '' }); }}><Plus size={15} aria-hidden="true" /> New template</button></div>
      <div className="template-grid">
        {data.templates.map((t) => (
          <article key={t.template_id} className="card template-card">
            <div className="row"><b>{t.name}</b><span className={`pill ${t.built_in ? 'pill-neutral' : 'pill-brand'}`}>{t.built_in ? 'Built-in' : 'Yours'}</span></div>
            <p className="small muted template-snippet">{t.content.replace(/\{\{\s*(\w+)\s*\}\}/g, (_, k) => `[${LABELS[k] || k}]`).replace(/[#*]/g, '').slice(0, 180)}…</p>
            <div className="row" style={{ marginTop: 'auto' }}>
              <button className="btn btn-secondary btn-sm" onClick={() => { setView('edit'); setEditing(t.built_in ? { name: `${t.name} (copy)`, content: t.content } : { ...t }); }}>{t.built_in ? 'Copy & edit' : 'Edit'}</button>
              {!t.built_in && <button className="btn btn-danger btn-sm" onClick={() => remove(t)}><Trash2 size={14} aria-hidden="true" /> Delete</button>}
            </div>
          </article>
        ))}
      </div>
    </>
  );
}

export default function HrOffers() {
  const [params, setParams] = useSearchParams();
  const offers = useAsync(() => api.getOffers(), []);
  const templates = useAsync(() => api.offerTemplates(), []);
  const apps = useAsync(() => api.getCandidates(), []);
  const [tab, setTab] = useState('offers');
  const [selectedId, setSelectedId] = useState(params.get('offer') ? Number(params.get('offer')) : null);
  const [creating, setCreating] = useState(params.get('application') || '');
  const [templateId, setTemplateId] = useState('');
  const [filter, setFilter] = useState('all');
  const [error, setError] = useState(null);
  const eligible = useMemo(() => (apps.data || []).filter((a) => ELIGIBLE.includes(a.status)), [apps.data]);
  const list = (offers.data || []).filter((o) => filter === 'all' || (filter === 'open' ? ['sent', 'viewed'].includes(o.status) : o.status === filter));
  const selected = (offers.data || []).find((o) => o.offer_id === selectedId);

  const create = async () => {
    setError(null);
    try {
      const o = await api.createOffer({ application_id: Number(creating), template_id: templateId ? Number(templateId) : undefined, fields: {} });
      setCreating(''); setParams({}); await offers.reload(); setSelectedId(o.offer_id);
    } catch (e) { setError(e.message); }
  };
  const refreshTo = async (o) => { await offers.reload(); setSelectedId(o ? o.offer_id : null); };
  const counts = (offers.data || []).reduce((acc, o) => ({ ...acc, [o.status]: (acc[o.status] || 0) + 1 }), {});

  return (
    <>
      <PageHeader title="Offer letters" subtitle="Fill in the details, shape the letter, preview the PDF and send. Drafts save automatically." />
      <Tabs tabs={[['offers', 'Offers'], ['templates', 'Templates']]} value={tab} onChange={setTab} />
      {tab === 'templates' ? (
        <Async state={templates} loadingLabel="Loading templates…">{(t) => <Templates data={t} reload={templates.reload} />}</Async>
      ) : (
        <>
          <section className="card section" style={{ marginTop: 0 }}>
            <div className="row">
              <label className="field-label" htmlFor="new-offer" style={{ margin: 0 }}>New offer for</label>
              <select id="new-offer" className="input" style={{ maxWidth: 380 }} value={creating} onChange={(e) => setCreating(e.target.value)}>
                <option value="">Select a shortlisted / interviewed candidate…</option>
                {eligible.map((a) => <option key={a.application_id} value={a.application_id}>{a.candidate_name} — {a.job_title} ({a.status})</option>)}
              </select>
              <label className="sr-only" htmlFor="new-offer-tpl">Template</label>
              <select id="new-offer-tpl" className="input" style={{ maxWidth: 240 }} value={templateId} onChange={(e) => setTemplateId(e.target.value)}>
                <option value="">Standard template</option>
                {(templates.data?.templates || []).filter((t) => !t.built_in).map((t) => <option key={t.template_id} value={t.template_id}>{t.name}</option>)}
              </select>
              <button className="btn btn-primary" disabled={!creating} onClick={create}><Plus size={15} aria-hidden="true" /> Create offer</button>
            </div>
            {eligible.length === 0 && apps.data && <p className="small muted" style={{ marginTop: 8 }}>Offers can be made once a candidate is assessed, shortlisted or interviewed.</p>}
            {error && <p className="alert alert-danger small" role="alert" style={{ marginTop: 10 }}>{error}</p>}
          </section>
          <div className="grid offers-grid" style={{ marginTop: 16 }}>
            <section className="card" style={{ padding: 12 }}>
              <div className="chips" style={{ marginBottom: 10 }} role="tablist" aria-label="Filter offers">
                {[['all', 'All'], ['draft', 'Drafts'], ['open', 'Awaiting reply'], ['accepted', 'Accepted'], ['rejected', 'Declined']].map(([k, l]) => (
                  <button key={k} type="button" role="tab" aria-selected={filter === k} className={`chip ${filter === k ? 'chip-req' : ''}`} onClick={() => setFilter(k)}>
                    {l}{k === 'all' ? '' : ` ${k === 'open' ? (counts.sent || 0) + (counts.viewed || 0) : counts[k] || 0}`}
                  </button>
                ))}
              </div>
              <Async state={offers} loadingLabel="Loading offers…" errorLabel="Failed to load offers">
                {() => list.length === 0 ? <EmptyState title={offers.data.length ? 'Nothing in this filter' : 'No offers yet'}>{offers.data.length ? '' : 'Create your first offer above.'}</EmptyState> : (
                  <ul className="plain-list" style={{ marginTop: 0 }}>
                    {list.map((o) => {
                      const p = pill(OFFER_STATUS, o.status);
                      return (
                        <li key={o.offer_id}>
                          <button className={`notif-item offer-item${o.offer_id === selectedId ? ' is-active' : ''}`} onClick={() => setSelectedId(o.offer_id)}>
                            <span className="row"><b>{o.candidate_name}</b><span className={`pill ${p.cls}`}>{p.text}</span></span>
                            <span className="small muted">{o.job_title} · {o.ctc_amount || 'CTC not set'} · {formatDate(o.sent_at || o.created_at)}</span>
                          </button>
                        </li>
                      );
                    })}
                  </ul>
                )}
              </Async>
            </section>
            <section className="card section" style={{ marginTop: 0, minWidth: 0 }}>
              {selected && templates.data
                ? <Editor key={selected.offer_id} offer={selected} templates={templates.data.templates} onChanged={refreshTo} onRemoved={() => refreshTo(null)}
                          onUpdated={(o) => offers.setData((offers.data || []).map((x) => (x.offer_id === o.offer_id ? { ...x, ...o } : x)))} />
                : <EmptyState title="Select an offer">Pick an offer on the left, or create a new one.</EmptyState>}
            </section>
          </div>
        </>
      )}
    </>
  );
}
