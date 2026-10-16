import { useCallback, useLayoutEffect, useRef, useState } from 'react';

const PAIRS = { '(': ')', '[': ']', '{': '}', '"': '"', "'": "'", '`': '`' };
const CLOSERS = new Set([')', ']', '}', '"', "'", '`']);
const LANG_LABEL = { python: 'Python', java: 'Java', cpp: 'C++', javascript: 'JavaScript' };
const INDENT = '    ';

/**
 * Lightweight code editor used by the real assessment, the mock assessment and the mock interview.
 * Line numbers, Tab / Shift+Tab (also on multi-line selections), smart Enter, bracket & quote pairs,
 * Ctrl+/ comment toggle, Ctrl+Enter to run, Esc then Tab to leave. Edits go through the browser's
 * undo stack, so Ctrl+Z / Ctrl+Y work after automatic indentation too.
 */
export default function CodeEditor({ value, onChange, language, label = 'Code editor', readOnly, onRun, minHeight = 320 }) {
  const gutter = useRef(null);
  const escaped = useRef(false);
  const area = useRef(null);
  const pendingSel = useRef(null);
  const [pos, setPos] = useState({ line: 1, col: 1 });
  const text = value || '';
  const lines = text.split('\n').length;
  const comment = language === 'python' ? '#' : '//';

  const track = useCallback((el) => {
    const before = el.value.slice(0, el.selectionStart);
    const line = before.split('\n').length;
    setPos({ line, col: el.selectionStart - before.lastIndexOf('\n') });
  }, []);

  // Replace [start, end) with `insert` keeping native undo where the browser supports it.
  const edit = (el, start, end, insert, selStart, selEnd = selStart) => {
    el.focus();
    el.setSelectionRange(start, end);
    let ok = false;
    try { ok = document.execCommand(insert ? 'insertText' : 'delete', false, insert); } catch { ok = false; }
    const next = text.slice(0, start) + insert + text.slice(end);
    if (ok && el.value === next) {
      // The browser already applied the edit (and recorded it for undo): place the caret right away so
      // the very next keystroke - even from a fast typist or key repeat - lands in the right spot.
      el.setSelectionRange(selStart, selEnd);
      track(el);
    } else {
      pendingSel.current = [selStart, selEnd];   // applied after React re-renders the new value
      onChange(next);
    }
  };
  useLayoutEffect(() => {
    const el = area.current;
    if (el && pendingSel.current) { el.setSelectionRange(...pendingSel.current); pendingSel.current = null; track(el); }
  });

  const onKeyDown = (e) => {
    if (e.nativeEvent.isComposing) return;
    const el = e.currentTarget;
    const { selectionStart: start, selectionEnd: end } = el;
    const before = text[start - 1];
    const after = text[start];
    const mod = e.ctrlKey || e.metaKey;

    if (e.key === 'Escape') { escaped.current = true; return; }
    if (e.key === 'Tab' && escaped.current) { escaped.current = false; return; } // let focus move on
    escaped.current = false;

    if (mod && e.key === 'Enter') { e.preventDefault(); onRun?.(); return; }

    const lineStart = text.lastIndexOf('\n', start - 1) + 1;
    const blockEnd = (() => { const i = text.indexOf('\n', end - (end > start && text[end - 1] === '\n' ? 1 : 0)); return i === -1 ? text.length : i; })();

    if (mod && e.key === '/') { // toggle line comments on the selected lines
      e.preventDefault();
      const block = text.slice(lineStart, blockEnd).split('\n');
      const allCommented = block.filter((l) => l.trim()).every((l) => l.trimStart().startsWith(comment));
      const out = block.map((l) => {
        if (!l.trim()) return l;
        const pad = l.match(/^\s*/)[0];
        return allCommented ? pad + l.slice(pad.length).replace(new RegExp(`^${comment.replace(/\//g, '\\/')} ?`), '') : `${pad}${comment} ${l.slice(pad.length)}`;
      }).join('\n');
      edit(el, lineStart, blockEnd, out, lineStart, lineStart + out.length);
      return;
    }

    if (e.key === 'Tab') {
      e.preventDefault();
      const multi = start !== end && text.slice(start, end).includes('\n');
      if (!e.shiftKey && !multi) { edit(el, start, end, INDENT, start + INDENT.length); return; }
      const block = text.slice(lineStart, blockEnd).split('\n');
      let firstDelta = 0;
      const out = block.map((l, i) => {
        if (!e.shiftKey) { if (i === 0) firstDelta = INDENT.length; return INDENT + l; }
        const strip = l.startsWith('\t') ? 1 : Math.min(INDENT.length, l.match(/^ */)[0].length);
        if (i === 0) firstDelta = -strip;
        return l.slice(strip);
      }).join('\n');
      if (out === block.join('\n')) return;
      if (multi) edit(el, lineStart, blockEnd, out, lineStart, lineStart + out.length);
      else edit(el, lineStart, blockEnd, out, Math.max(lineStart, start + firstDelta));
      return;
    }

    if (e.key === 'Enter' && !e.shiftKey && !e.altKey && !mod) {
      e.preventDefault();
      const current = text.slice(lineStart, start);
      const pad = current.match(/^\s*/)[0];
      const opens = /[:{[(]\s*$/.test(current);
      const inner = opens ? pad + INDENT : pad;
      if (opens && after && PAIRS[before] === after && before !== after) { // {|} -> block with the caret inside
        const ins = `\n${inner}\n${pad}`;
        edit(el, start, end, ins, start + 1 + inner.length);
      } else {
        edit(el, start, end, `\n${inner}`, start + 1 + inner.length);
      }
      return;
    }

    if (e.key === 'Backspace' && start === end && start > 0 && !mod) {
      if (before && PAIRS[before] && PAIRS[before] === after) { e.preventDefault(); edit(el, start - 1, start + 1, '', start - 1); return; }
      const lead = text.slice(lineStart, start);
      if (lead.length >= INDENT.length && /^ +$/.test(lead)) {
        e.preventDefault();
        const n = lead.length % INDENT.length || INDENT.length;
        edit(el, start - n, start, '', start - n);
      }
      return;
    }

    if (e.key.length !== 1 || mod || e.altKey) return;

    // Step over an auto-inserted closer instead of doubling it.
    if (CLOSERS.has(e.key) && start === end && after === e.key) {
      e.preventDefault();
      el.setSelectionRange(start + 1, start + 1); track(el);
      return;
    }
    // Typing a closing brace on a blank line dedents it to the block's level.
    if ((e.key === '}' || e.key === ']' || e.key === ')') && start === end) {
      const lead = text.slice(lineStart, start);
      if (lead.length >= INDENT.length && /^ +$/.test(lead)) {
        e.preventDefault();
        const pad = lead.slice(INDENT.length);
        edit(el, lineStart, start, pad + e.key, lineStart + pad.length + 1);
        return;
      }
    }
    if (PAIRS[e.key]) {
      const quote = e.key === PAIRS[e.key];
      if (start !== end) { // wrap the selection
        e.preventDefault();
        const sel = text.slice(start, end);
        edit(el, start, end, e.key + sel + PAIRS[e.key], start + 1, end + 1);
        return;
      }
      const nextOk = !after || /[\s)\]};,]/.test(after);
      const prevOk = !quote || !before || !/[\w\\]/.test(before);
      if (nextOk && prevOk) {
        e.preventDefault();
        edit(el, start, end, e.key + PAIRS[e.key], start + 1);
      }
    }
  };

  const syncScroll = (e) => { if (gutter.current) gutter.current.scrollTop = e.target.scrollTop; };
  const hint = `${LANG_LABEL[language] || language || 'Code'} · Ln ${pos.line}, Col ${pos.col}`;

  return (
    <div className={`code-editor-wrap${readOnly ? ' is-readonly' : ''}`}>
      <div className="code-editor">
        <div className="gutter" ref={gutter} aria-hidden="true">
          {Array.from({ length: lines }, (_, i) => <span key={i} className={i + 1 === pos.line ? 'cur' : undefined}>{i + 1}</span>)}
        </div>
        <textarea ref={area} aria-label={label} spellCheck={false} autoCapitalize="off" autoCorrect="off" autoComplete="off"
                  wrap="off" value={text} readOnly={readOnly} style={{ minHeight }} data-gramm="false"
                  onChange={(e) => { onChange(e.target.value); track(e.target); }}
                  onKeyDown={readOnly ? undefined : onKeyDown}
                  onKeyUp={(e) => track(e.currentTarget)} onClick={(e) => track(e.currentTarget)} onSelect={(e) => track(e.currentTarget)}
                  onScroll={syncScroll} />
      </div>
      <div className="code-status small">
        <span>{hint}</span>
        <span className="spacer" />
        {readOnly
          ? <span>Read only</span>
          : <span className="code-keys" title="Tab / Shift+Tab indent · Ctrl+/ comment · Ctrl+Enter run · Esc then Tab leaves the editor"><kbd>Ctrl</kbd>+<kbd>/</kbd> comment{onRun ? <> · <kbd>Ctrl</kbd>+<kbd>↵</kbd> run</> : null} · <kbd>Esc</kbd> <kbd>Tab</kbd> exit</span>}
      </div>
    </div>
  );
}

/** Result panel shared by the real and mock assessments (and the interviewer's coding slot). */
export function CodeRunResult({ result, title }) {
  if (!result) return null;
  const tests = result.tests || [];
  const hidden = tests.filter((t) => t.hidden);
  const ok = result.status === 'accepted' || (result.total > 0 && result.passed === result.total);
  const status = String(result.status || '').replace(/_/g, ' ');
  return (
    <div className="card code-result" aria-live="polite">
      <div className="row">
        <b>{title || 'Sample run'}: {result.passed ?? 0} / {result.total ?? 0} test cases passed</b>
        <span className="spacer" />
        {status && <span className={`pill ${ok ? 'pill-ok' : 'pill-danger'}`}>{status}</span>}
      </div>
      {result.error && <pre className="pre tone-danger" style={{ marginTop: 8 }}>{result.error}</pre>}
      {!!tests.length && (
        <div style={{ display: 'grid', gap: 6, marginTop: 8 }}>
          {tests.filter((t) => !t.hidden).map((t, i) => (
            <div key={t.name || i} className={`test-row ${t.passed ? 'pass' : 'fail'}`}>
              <span aria-hidden="true">{t.passed ? '✓' : '✕'}</span>
              <div style={{ flex: 1, minWidth: 0 }}>
                <b>{t.name || `Test ${i + 1}`}</b> · {String(t.status || '').replace(/_/g, ' ')}{t.time_ms !== undefined && t.time_ms !== null ? ` · ${t.time_ms} ms` : ''}
                {!t.passed && t.status !== 'skipped' && (
                  <div className="small" style={{ color: 'var(--ink-950)' }}>
                    {t.input !== undefined && t.input !== null && <><span className="muted">Input</span><pre className="pre">{t.input}</pre></>}
                    <span className="muted">Expected</span><pre className="pre">{t.expected ?? ''}</pre>
                    <span className="muted">Your output</span><pre className="pre">{t.actual || '(empty)'}</pre>
                    {t.stderr && <pre className="pre tone-danger">{t.stderr}</pre>}
                  </div>
                )}
              </div>
            </div>
          ))}
          {!!hidden.length && (
            <p className="small muted">Hidden tests: <b>{hidden.filter((t) => t.passed).length} / {hidden.length}</b> passed (inputs stay hidden).</p>
          )}
        </div>
      )}
    </div>
  );
}
