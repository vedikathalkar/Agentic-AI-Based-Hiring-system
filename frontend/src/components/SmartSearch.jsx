import { useEffect, useRef, useState } from 'react';
import { Search, Sparkles, X } from 'lucide-react';

const KIND_CLASS = { skill: 'chip-req', location: 'chip-ok', work_mode: 'chip-ok', experience: '', min_score: '', status: '', keyword: '' };
const KIND_LABEL = { skill: 'Skill', location: 'Location', work_mode: 'Work mode', experience: 'Experience', min_score: 'Score', status: 'Status', keyword: 'Keyword' };

/** Debounce a fast-changing value. */
export function useDebounced(value, delay = 300) {
  const [v, setV] = useState(value);
  useEffect(() => { const id = setTimeout(() => setV(value), delay); return () => clearTimeout(id); }, [value, delay]);
  return v;
}

/**
 * Natural-language search box. The server parses the text into structured
 * filters and returns them as "understood" chips; removing a chip removes the
 * words it came from, so the text and the filters never disagree.
 */
export default function SmartSearch({ id, value, onChange, understood = [], corrections = [], examples = [], placeholder, count, loading, label = 'Smart search' }) {
  const inputRef = useRef(null);
  const removeChip = (chip) => {
    const src = chip.source || (typeof chip.value === 'string' ? chip.value : '');
    if (!src) return;
    const re = new RegExp(`(^|[^\\w+#])${src.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}(?=$|[^\\w+#])`, 'i');
    onChange(value.replace(re, '$1').replace(/\s{2,}/g, ' ').trim());
    inputRef.current?.focus();
  };
  return (
    <div className="smart-search">
      <div className="smart-search-box">
        <Search size={17} aria-hidden="true" className="smart-search-icon" />
        <label className="sr-only" htmlFor={id}>{label}</label>
        <input ref={inputRef} id={id} className="input" value={value} placeholder={placeholder} autoComplete="off"
               onChange={(e) => onChange(e.target.value)} onKeyDown={(e) => { if (e.key === 'Escape') onChange(''); }} />
        {value && <button type="button" className="icon-btn smart-search-clear" aria-label="Clear search" onClick={() => { onChange(''); inputRef.current?.focus(); }}><X size={15} /></button>}
        <span className="smart-search-badge" title="Understands skills, places, experience, work mode and typos"><Sparkles size={13} aria-hidden="true" /> NLP</span>
      </div>
      {(understood.length > 0 || corrections.length > 0) && (
        <div className="smart-search-understood" aria-live="polite">
          <span className="small muted">Understood:</span>
          {understood.map((c) => (
            <span key={`${c.kind}:${c.label}`} className={`chip ${KIND_CLASS[c.kind] || ''}`} title={`${KIND_LABEL[c.kind] || c.kind}${c.source ? ` — from “${c.source}”` : ''}`}>
              <span className="small muted">{KIND_LABEL[c.kind]}:</span> {c.label}
              {c.source && <button type="button" className="chip-x" aria-label={`Remove ${c.label}`} onClick={() => removeChip(c)}>×</button>}
            </span>
          ))}
          {corrections.length > 0 && <span className="small muted">· corrected {corrections.join(', ')}</span>}
          <span className="spacer" />
          {count != null && <span className="small muted">{loading ? 'Searching…' : `${count} result${count === 1 ? '' : 's'}`}</span>}
        </div>
      )}
      {!value && examples.length > 0 && (
        <div className="smart-search-examples">
          <span className="small muted">Try:</span>
          {examples.map((ex) => <button key={ex} type="button" className="chip-btn" onClick={() => onChange(ex)}>{ex}</button>)}
        </div>
      )}
    </div>
  );
}
