import { useCallback, useEffect, useId, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { Upload, X } from 'lucide-react';

// ---- data loading ------------------------------------------------------------------

export function useAsync(fn, deps = []) {
  const [state, setState] = useState({ loading: true, error: null, data: null });
  const run = useCallback(async () => {
    setState((s) => ({ ...s, loading: true, error: null }));
    try {
      const data = await fn();
      setState({ loading: false, error: null, data });
      return data;
    } catch (error) {
      setState((s) => ({ ...s, loading: false, error }));
      return null;
    }
  }, deps); // eslint-disable-line
  useEffect(() => { run(); }, [run]);
  return { ...state, reload: run, setData: (data) => setState((s) => ({ ...s, data })) };
}

export function LoadingState({ label = 'Loading…' }) {
  return <div className="state-box" role="status"><span className="spinner" aria-hidden="true" /> {label}</div>;
}

export function ErrorState({ error, onRetry, label = 'Something went wrong' }) {
  return (
    <div className="state-box state-error" role="alert">
      <p><b>{label}.</b> {error?.message || String(error || '')}</p>
      {onRetry && <button className="btn btn-secondary btn-sm" onClick={onRetry}>Retry</button>}
    </div>
  );
}

export function EmptyState({ title, children, action }) {
  return (
    <div className="state-box state-empty">
      <p className="state-title">{title}</p>
      {children && <p className="muted small">{children}</p>}
      {action}
    </div>
  );
}

/** Renders loading/error states for a useAsync result, otherwise children(data). */
export function Async({ state, children, loadingLabel, errorLabel }) {
  if (state.loading && !state.data) return <LoadingState label={loadingLabel} />;
  if (state.error && !state.data) return <ErrorState error={state.error} onRetry={state.reload} label={errorLabel} />;
  return children(state.data);
}

// ---- layout bits -------------------------------------------------------------------

export function PageHeader({ title, subtitle, eyebrow, actions }) {
  return (
    <div className="page-head">
      <div>
        {eyebrow && <p className="eyebrow">{eyebrow}</p>}
        <h1>{title}</h1>
        {subtitle && <p>{subtitle}</p>}
      </div>
      {actions && <div className="row">{actions}</div>}
    </div>
  );
}

export function StatCard({ label, value, hint, tone, to }) {
  const body = (
    <div className={`card stat stat-${tone || 'default'}`}>
      <span className="stat-label">{label}</span>
      <b>{value ?? '—'}</b>
      {hint && <span className="small muted">{hint}</span>}
    </div>
  );
  return to ? <Link to={to} className="stat-link">{body}</Link> : body;
}

export function ProgressBar({ value, max = 100, label, tone = 'brand', showValue = true }) {
  const pct = Math.max(0, Math.min(100, (Number(value) / (max || 1)) * 100));
  return (
    <div>
      {(label || showValue) && (
        <div className="row small" style={{ justifyContent: 'space-between', marginBottom: 4 }}>
          <span>{label}</span>{showValue && <b>{Math.round(pct)}%</b>}
        </div>
      )}
      <div className="progress" role="progressbar" aria-label={label || 'Progress'} aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(pct)}>
        <span className={`bg-${tone}`} style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
}

export function Tabs({ tabs, value, onChange, label = 'Sections' }) {
  return (
    <div className="tabs" role="tablist" aria-label={label}>
      {tabs.map(([key, text]) => (
        <button key={key} type="button" role="tab" aria-selected={value === key} onClick={() => onChange(key)}>{text}</button>
      ))}
    </div>
  );
}

export function Modal({ title, onClose, children, footer, wide }) {
  const ref = useRef(null);
  const closeRef = useRef(onClose);
  closeRef.current = onClose;
  // Runs once per opening. Callers pass a new inline onClose on every render; depending on
  // it re-focused the first field (and scrolled) on every keystroke.
  useEffect(() => {
    const prev = document.activeElement;
    ref.current?.querySelector('input,select,textarea,button')?.focus({ preventScroll: true });
    const onKey = (e) => { if (e.key === 'Escape') closeRef.current(); };
    document.addEventListener('keydown', onKey);
    return () => { document.removeEventListener('keydown', onKey); prev?.focus?.({ preventScroll: true }); };
  }, []);
  return (
    <div className="modal-mask" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div className="modal" style={wide ? { width: 'min(760px, 100%)' } : undefined} role="dialog" aria-modal="true" aria-label={title} ref={ref}>
        <div className="row" style={{ marginBottom: 12 }}>
          <h2 style={{ fontSize: 19 }}>{title}</h2>
          <span className="spacer" />
          <button className="icon-btn" onClick={onClose} aria-label="Close dialog"><X size={18} /></button>
        </div>
        {children}
        {footer && <div className="row" style={{ justifyContent: 'flex-end', marginTop: 18 }}>{footer}</div>}
      </div>
    </div>
  );
}

export function FileUploader({ label, accept, hint, onFile, busy, fileName, id }) {
  const [drag, setDrag] = useState(false);
  const autoId = useId();
  const inputId = id || `file-${autoId}`;
  const inputRef = useRef(null);
  // The whole dashed box opens the file picker (click, Enter or Space), not just the label text.
  const open = () => { if (!busy) inputRef.current?.click(); };
  return (
    <div
      className={`uploader${drag ? ' drag' : ''}`}
      role="button" tabIndex={busy ? -1 : 0} aria-disabled={busy || undefined} aria-describedby={`${inputId}-hint`}
      style={{ cursor: busy ? 'progress' : 'pointer' }}
      onClick={(e) => { if (e.target !== inputRef.current && e.target.tagName !== 'LABEL') open(); }}
      onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); open(); } }}
      onDragOver={(e) => { e.preventDefault(); setDrag(true); }}
      onDragLeave={() => setDrag(false)}
      onDrop={(e) => { e.preventDefault(); setDrag(false); const f = e.dataTransfer.files?.[0]; if (f && !busy) onFile(f); }}
    >
      <Upload size={20} aria-hidden="true" />
      <div>
        <label htmlFor={inputId} className="uploader-label">{busy ? 'Uploading…' : label}</label>
        <div id={`${inputId}-hint`}>
          {hint && <p className="small muted">{hint}</p>}
          {fileName && <p className="small">Selected: <b>{fileName}</b></p>}
        </div>
      </div>
      <input ref={inputRef} id={inputId} type="file" accept={accept} className="sr-only" disabled={busy} tabIndex={-1}
             onClick={(e) => e.stopPropagation()}
             onChange={(e) => { const f = e.target.files?.[0]; if (f) onFile(f); e.target.value = ''; }} />
    </div>
  );
}

export function TagInput({ value = [], onChange, placeholder, label, id }) {
  const [draft, setDraft] = useState('');
  const add = () => {
    const parts = draft.split(/[,;\n]/).map((s) => s.trim()).filter(Boolean);
    if (!parts.length) return;
    const lower = value.map((v) => v.toLowerCase());
    onChange([...value, ...parts.filter((p) => !lower.includes(p.toLowerCase()))]);
    setDraft('');
  };
  return (
    <div>
      {label && <label className="field-label" htmlFor={id}>{label}</label>}
      <div className="tag-input">
        {value.map((v) => (
          <span key={v} className="chip">{v}<button type="button" className="chip-x" aria-label={`Remove ${v}`} onClick={() => onChange(value.filter((x) => x !== v))}>×</button></span>
        ))}
        <input id={id} value={draft} placeholder={placeholder} onChange={(e) => setDraft(e.target.value)}
               onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ',') { e.preventDefault(); add(); } }} onBlur={add} />
      </div>
    </div>
  );
}

export function Field({ label, children, hint, id }) {
  return (
    <div className="field">
      <label className="field-label" htmlFor={id}>{label}</label>
      {children}
      {hint && <p className="small muted" style={{ marginTop: 4 }}>{hint}</p>}
    </div>
  );
}

export function money(paise) {
  return `₹${(Number(paise || 0) / 100).toLocaleString('en-IN', { maximumFractionDigits: 2 })}`;
}
