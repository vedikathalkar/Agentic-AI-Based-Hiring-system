import { useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import Logo from '../../components/Logo';
import Cursor from '../../components/Cursor';
import { session } from '../../api';
import { useLandingMotion } from './landingMotion';
import '../../styles/landing.css';

const MENU = [
  { id: 'problem', label: 'Problem', c: 'var(--a1)' },
  { id: 'approach', label: 'Approach', c: 'var(--a2)' },
  { id: 'pipeline', label: 'Pipeline', c: 'var(--a4)' },
  { id: 'demo', label: 'Live run', c: 'var(--a5)' },
  { id: 'start', label: 'Get started', c: 'var(--a7)' },
];

const PERSONAS = [
  ['Screening', 'HR teams & recruiters', 'Read hundreds of resumes per opening with no consistent, defensible way to compare candidates.', 'var(--a1)'],
  ['Deciding', 'Hiring managers', 'Wait days for a shortlist and get little insight into why candidates were ranked the way they were.', 'var(--a2)'],
  ['Applying', 'Candidates', 'Face opaque rejections with no explanation, and bias that may go undetected in manual screening.', 'var(--a4)'],
  ['Scaling', 'Growing companies', "Screening effort scales linearly with applicant volume. There's no efficient way to hire at scale.", 'var(--a6)'],
];

const COMPARE = [
  ['HR staff read and rank resumes manually, or rely on keyword-matching ATS filters that miss context.', 'A custom-trained spaCy NER model, extended with SKILL and DEGREE labels, recognises skills it never saw in training. No keyword list to maintain.'],
  ['Evaluation criteria vary from reviewer to reviewer. No standardized, repeatable scoring.', 'Rule-based, deterministic scoring for skills and experience. Every score is explainable and reproducible.'],
  ["Bias mitigation is rarely built in. It's handled after the fact, if at all, through training or audits.", 'Names, gendered terms and photos are stripped before any scoring agent sees a profile.'],
  ['Ranking is a black box, with little or no plain-language justification recorded.', 'An LLM-generated “Why this ranking” panel explains every candidate\'s position.'],
  ['Interviews are scheduled over email and phone, one candidate at a time.', 'Automated, calendar-aware scheduling replaces the back-and-forth entirely.'],
];

const AGENTS = [
  ['Resume Parsing', 'PDF or DOCX to text, text to entities, entities to a structured profile.', 'pdfplumber · python-docx → NER → profile'],
  ['Skill Evaluation', "Matched skills against the role's required skills, weighted by the HR form.", 'matched / required → score'],
  ['Experience Evaluation', "Years of relevant experience measured against the role's minimum.", 'years vs. minimum → score'],
  ['Bias Detection', 'Strips name, gendered terms and photo before any scoring agent sees the profile.', 'redact → anonymised profile'],
  ['Assessment & Question Gen.', 'An LLM writes a role-specific test and grades descriptive answers.', 'LLM → questions → auto-grade'],
  ['Ranking', 'Combines every score into one weighted total and sorts the pool.', 'Σ weights × scores → order'],
  ['Explainability', 'Writes the “Why this ranking” justification stored with every result.', 'scores → plain-language reason'],
  ['Scheduling', 'Finds a common calendar slot, creates the event and notifies both sides.', 'Google Calendar API (OAuth)'],
];

// Sample run shown in the live demo. Figures are illustrative.
const DEMO_STEPS = [
  ['Parse', 'PARSE', '2 pages → 14 entities · 9 SKILL, 2 DEGREE'],
  ['Skill', 'SKILL', '7 of 9 required skills matched · 78 / 100'],
  ['Exp.', 'EXP', '3.5 yrs vs. 2 yrs minimum · 100 / 100'],
  ['Bias', 'BIAS', 'Removed name, 3 gendered terms, 1 photo'],
  ['Assess', 'ASSESS', '12 questions generated · graded 84 / 100'],
  ['Rank', 'RANK', 'Weighted total 86.4 · #3 of 142'],
  ['Explain', 'EXPLAIN', '“Strong FastAPI + SQL match; missing Docker.”'],
  ['Book', 'BOOK', 'Interview booked · Thu 2 Oct, 11:30 IST'],
];

const ENT_TYPES = ['DEGREE', 'ORG', 'SKILL', 'SKILL', 'SKILL', 'SKILL', 'DEGREE'];
const agentColor = (i) => `var(--a${i + 1})`;

// True when this browser already holds a session for the given portal.
const hasSession = (role) => { try { return !!session.token(role); } catch { return false; } };

function Roll({ children }) {
  return <span className="roll"><span>{children}</span><span aria-hidden="true">{children}</span></span>;
}

export default function Landing() {
  const navigate = useNavigate();
  const rootRef = useRef(null);
  const [menuOpen, setMenuOpen] = useState(false);
  const [view, setView] = useState('both');
  const [entCount, setEntCount] = useState(0);
  const [demo, setDemo] = useState({ step: -1, done: false, runId: 0 });
  const [score, setScore] = useState(0);
  const knobWrap = useRef(null);
  const [knob, setKnob] = useState({ w: 0, x: 0 });

  const { loader, phase, footIn, startDemoRef } = useLandingMotion(rootRef, menuOpen);

  const candidateIn = hasSession('candidate');
  const hrIn = hasSession('hr');
  // Where the main buttons lead, depending on who is already signed in.
  const candidateCta = candidateIn ? { label: 'Go to dashboard', to: '/dashboard' } : { label: 'Get started', to: '/signup' };
  const hrCta = hrIn ? { label: 'HR dashboard', to: '/hr' } : { label: "I'm hiring", to: '/hr/login' };
  const headerCta = candidateIn ? { label: 'Dashboard', to: '/dashboard' } : hrIn ? { label: 'HR dashboard', to: '/hr' } : { label: 'Log in', to: '/login' };

  // Close the menu with Escape.
  useEffect(() => {
    const onKey = (e) => { if (e.key === 'Escape') setMenuOpen(false); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, []);

  // Resume card: tag the entities one by one, pause, repeat.
  useEffect(() => {
    const reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    if (reduce) { setEntCount(7); return undefined; }
    let n = 0; let t;
    const tick = () => {
      if (n < 7) { n += 1; setEntCount(n); t = setTimeout(tick, 650); }
      else { t = setTimeout(() => { n = 0; setEntCount(0); t = setTimeout(tick, 700); }, 2600); }
    };
    t = setTimeout(tick, 1600);
    return () => clearTimeout(t);
  }, []);

  // Compare toggle knob follows the pressed button.
  useEffect(() => {
    const place = () => {
      const btn = knobWrap.current?.querySelector('button[aria-pressed="true"]');
      if (btn) setKnob({ w: btn.offsetWidth, x: btn.offsetLeft - 4 });
    };
    place();
    window.addEventListener('resize', place);
    return () => window.removeEventListener('resize', place);
  }, [view]);

  // AgentTrail demo run.
  useEffect(() => {
    if (demo.runId === 0) return undefined;
    const reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    const gap = reduce ? 0 : 900;
    const timers = DEMO_STEPS.map((_, i) => setTimeout(() => setDemo((d) => ({ ...d, step: i })), i * gap));
    timers.push(setTimeout(() => setDemo((d) => ({ ...d, done: true })), DEMO_STEPS.length * gap));
    return () => timers.forEach(clearTimeout);
  }, [demo.runId]);

  // Count the score up when the ranking step lands.
  const ranked = demo.step >= 5;
  useEffect(() => {
    if (!ranked) { setScore(0); return undefined; }
    let raf; const start = performance.now();
    const run = (now) => {
      const p = Math.min(1, (now - start) / 1200);
      setScore(86.4 * (1 - Math.pow(1 - p, 3)));
      if (p < 1) raf = requestAnimationFrame(run);
    };
    raf = requestAnimationFrame(run);
    return () => cancelAnimationFrame(raf);
  }, [ranked, demo.runId]);

  const runDemo = () => setDemo((d) => ({ step: -1, done: false, runId: d.runId + 1 }));
  startDemoRef.current = runDemo;

  const scrollToId = (id) => {
    const go = () => {
      const el = id === 'top' ? null : document.getElementById(id);
      const reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
      if (!el) window.scrollTo({ top: 0, behavior: reduce ? 'auto' : 'smooth' });
      else el.scrollIntoView({ behavior: reduce ? 'auto' : 'smooth' });
    };
    if (menuOpen) { setMenuOpen(false); setTimeout(go, 450); } else go();
  };
  const goTo = (path) => { setMenuOpen(false); navigate(path); };

  const ent = (t, text) => <span className={`ent${entCount > t ? ' on' : ''}`} data-t={ENT_TYPES[t]}>{text}</span>;
  const tab = menuOpen ? 0 : -1;

  return (
    <div className={['lp', 'theme-dark', phase.motion && 'motion', phase.ready && 'ready', menuOpen && 'menu-open'].filter(Boolean).join(' ')} ref={rootRef}>
      {loader.show && (
        <div className={`loader${loader.leaving ? ' leave' : ''}`} aria-hidden="true">
          <div className="loader-top"><Logo mode="loop" light word={false} fontSize={34} /><span className="mono">Hirelune · parsing resume.pdf</span></div>
          <div>
            <div className="loader-count">{loader.count}</div>
            <div className="loader-bar"><i style={{ transform: `scaleX(${loader.count / 100})` }} /></div>
          </div>
        </div>
      )}

      <div className="lp-progress" aria-hidden="true" />

      <header className="hdr">
        <div className="wrap hdr-in">
          <button className="logo-btn" onClick={() => scrollToId('top')} aria-label="Back to top" data-magnet>
            <Logo fontSize={21} start={phase.ready} />
          </button>
          <div className="hdr-right">
            <button className="lbtn lbtn-line hide-sm" style={{ '--fill': 'var(--a2)' }} onClick={() => goTo(headerCta.to)} data-magnet><Roll>{headerCta.label}</Roll></button>
            <button className="lbtn lbtn-solid" onClick={() => setMenuOpen((o) => !o)} aria-expanded={menuOpen} aria-controls="lp-menu" data-magnet>
              <Roll>{menuOpen ? 'Close' : 'Menu'}</Roll>
              <span className="burger" aria-hidden="true"><i /><i /></span>
            </button>
          </div>
        </div>
      </header>

      <nav className="menu" id="lp-menu" aria-label="Sections" aria-hidden={!menuOpen}>
        <div className="wrap menu-in">
          <ul className="mlinks">
            {MENU.map((m, i) => (
              <li key={m.id}>
                <button className="mlink" style={{ '--c': m.c, '--d': `${0.08 + i * 0.06}s` }} onClick={() => scrollToId(m.id)} tabIndex={tab}>
                  <Roll>{m.label}</Roll><i className="mdot" />
                </button>
              </li>
            ))}
          </ul>
          <div className="menu-side">
            <p>A multi-agent AI pipeline that takes hiring from resume upload to interview booking, with every decision explainable and auditable.</p>
            <div className="portal">
              <button className="lbtn lbtn-solid" style={{ '--fill': 'var(--a2)' }} onClick={() => goTo(candidateCta.to)} tabIndex={tab}><Roll>{candidateIn ? 'Go to dashboard' : 'Candidate sign up'}</Roll></button>
              {!candidateIn && <button className="lbtn lbtn-line" style={{ '--fill': 'var(--a2)' }} onClick={() => goTo('/login')} tabIndex={tab}><Roll>Log in</Roll></button>}
              <button className="lbtn lbtn-line" style={{ '--fill': 'var(--a5)' }} onClick={() => goTo(hrIn ? '/hr' : '/hr/login')} tabIndex={tab}><Roll>{hrIn ? 'HR dashboard' : 'HR portal'}</Roll></button>
            </div>
          </div>
        </div>
      </nav>

      <main id="top">
        {/* HERO */}
        <section className="hero">
          <div className="hshape s1" data-depth="0.6" aria-hidden="true" />
          <div className="hshape s2" data-depth="1.1" aria-hidden="true" />
          <div className="hshape s3" data-depth="0.35" aria-hidden="true" />
          <div className="hshape s4" data-depth="1.5" aria-hidden="true" />
          <div className="wrap">
            <div className="hero-meta">
              <span className="mono">Agentic AI hiring platform</span>
            </div>
            <h1>
              <span className="ln"><span>Hiring,</span></span>
              <span className="ln"><span>handled by</span></span>
              <span className="ln"><span><em>eight</em> agents.</span></span>
            </h1>
            <div className="hero-row">
              <div className="hero-fade">
                <p className="hero-lede">Upload a resume and watch it move through parsing, scoring, bias control, assessment, ranking and scheduling. Every score is reproducible and every ranking comes with a plain-language reason.</p>
                <div className="hero-cta">
                  <button className="lbtn lbtn-solid" style={{ '--fill': 'var(--a2)' }} onClick={() => goTo(candidateCta.to)} data-magnet><Roll>{candidateCta.label}</Roll></button>
                  <button className="lbtn lbtn-line" style={{ '--fill': 'var(--a5)' }} onClick={() => goTo(hrCta.to)} data-magnet><Roll>{hrCta.label}</Roll></button>
                  <button className="textlink" onClick={() => scrollToId('pipeline')}>See the pipeline ↓</button>
                </div>
              </div>
              <div className="resume hero-fade" aria-label="Example of the custom NER model tagging a resume">
                <div className="resume-top">
                  <span className="mono">resume_0412.pdf · spaCy NER</span>
                  <span className="live"><i />Tagging</span>
                </div>
                <div className="rtext">
                  Completed a {ent(0, 'B.E. in Information Technology')} at {ent(1, 'Vidyalankar Institute')}. Built REST services in {ent(2, 'FastAPI')} with {ent(3, 'SQLAlchemy')}, a dashboard in {ent(4, 'React')}, and trained a {ent(5, 'spaCy')} model. Earlier: {ent(6, 'Diploma in Computer Engg.')}
                </div>
                <div className="resume-foot">
                  <span className="key"><i style={{ background: 'var(--a2)' }} />SKILL</span>
                  <span className="key"><i style={{ background: 'var(--a4)' }} />DEGREE</span>
                  <span className="key"><i style={{ background: 'var(--a6)' }} />ORG</span>
                  <span style={{ marginLeft: 'auto' }}>entities <b>{entCount}</b>/7</span>
                </div>
              </div>
            </div>
          </div>
        </section>

        {/* PROBLEM */}
        <section className="sec sec-first" id="problem">
          <div className="wrap">
            <div className="duo">
              <h2 className="split">Hiring by hand doesn't scale.</h2>
              <p className="statement">Hiring teams screen every resume by hand, score on gut feel, and can rarely explain why one applicant ranked above another. As volume grows, screening time balloons, reviewers disagree, bias creeps into shortlists, and nothing is left to audit.</p>
            </div>
            <div className="personas" data-reveal>
              {PERSONAS.map(([tag, h, p, c]) => (
                <article key={h} className="persona" style={{ '--c': c }} data-cursor="View">
                  <span className="mono">{tag}</span>
                  <h3>{h}</h3>
                  <p>{p}</p>
                </article>
              ))}
            </div>
            <p className="cost">Every extra day spent screening by hand is a day a good candidate waits, and a day the process stays impossible to justify or audit.</p>
          </div>
        </section>

        {/* APPROACH */}
        <section className={`sec${view === 'old' ? ' show-old' : view === 'new' ? ' show-new' : ''}`} id="approach">
          <div className="wrap">
            <div className="sec-head">
              <h2 className="split">What changes with Hirelune.</h2>
              <div className="cmp-toggle" role="group" aria-label="Compare approaches" ref={knobWrap}>
                <span className="knob" aria-hidden="true" style={{ width: knob.w, transform: `translateX(${knob.x}px)`, background: view === 'new' ? 'var(--a3)' : 'var(--ink)' }} />
                {[['both', 'Side by side'], ['old', 'Today'], ['new', 'Hirelune']].map(([k, label]) => (
                  <button key={k} aria-pressed={view === k} onClick={() => setView(k)}>{label}</button>
                ))}
              </div>
            </div>
            <ul className="cmp" data-reveal>
              {COMPARE.map(([o, n], i) => (
                <li key={i}>
                  <p className="old"><span className="lbl">Today</span>{o}</p>
                  <p className="new"><span className="lbl">Hirelune</span>{n}</p>
                </li>
              ))}
            </ul>
          </div>
        </section>

        {/* PIPELINE */}
        <section className="pipe" id="pipeline">
          <div className="pipe-pin">
            <div className="wrap pipe-head">
              <h2 className="split">One application, eight agents.</h2>
              <p>Each agent owns one stage of hiring. Scroll to follow a candidate from upload to a booked interview.</p>
            </div>
            <div className="track">
              {AGENTS.map(([h, p, io], i) => (
                <article key={h} className="agent" style={{ '--c': agentColor(i) }} data-cursor="Scroll">
                  <span className="num">{String(i + 1).padStart(2, '0')}</span>
                  <h3>{h}</h3>
                  <p>{p}</p>
                  <div className="io">{io}</div>
                </article>
              ))}
            </div>
            <div className="pipe-bar" aria-hidden="true"><i /></div>
          </div>
        </section>

        {/* LIVE RUN */}
        <section className="sec" id="demo">
          <div className="wrap demo">
            <div className="demo-intro">
              <h2 className="split">Watch one application run.</h2>
              <p>The AgentTrail stepper lights up as each agent finishes. HR sees the extracted profile, the scores and the reasoning behind the rank.</p>
              <button className="lbtn lbtn-solid" style={{ '--fill': 'var(--a3)' }} onClick={runDemo} data-magnet><Roll>Replay the run</Roll></button>
            </div>
            <div>
              <div className="console" id="lp-console">
                <div className="console-top">
                  <div className="cand"><span className="cand-av" aria-hidden="true">ID</span><div><b>Candidate #0412</b><span>Backend Developer · Pune</span></div></div>
                  <span className="live" style={{ color: demo.done ? 'var(--ink)' : undefined }}>{!demo.done && <i />}{demo.done ? 'Complete' : demo.step < 0 ? 'Waiting' : 'Running'}</span>
                </div>
                <ol className="lsteps">
                  {DEMO_STEPS.map(([label], i) => {
                    const state = demo.done || i < demo.step ? 'done' : i === demo.step ? 'run' : '';
                    return <li key={label} className={state} style={{ '--c': agentColor(i) }}><span className="b">{i + 1}</span>{label}</li>;
                  })}
                </ol>
                <ul className="llog" aria-live="polite">
                  {DEMO_STEPS.slice(0, demo.step + 1).map(([, tag, text], i) => (
                    <li key={`${demo.runId}-${tag}`} style={{ '--c': agentColor(i) }}><span>{tag}</span><span>{text}</span></li>
                  ))}
                </ul>
                <div className="lscore">
                  <div><span className="mono">Weighted score</span><div className="big">{score.toFixed(1)}</div></div>
                  <div style={{ textAlign: 'right' }}><span className="mono">Pool rank</span><div className="big">{ranked ? '#3' : '—'}</div></div>
                </div>
              </div>
              <p className="demo-note">Sample candidate and figures for illustration.</p>
            </div>
          </div>
        </section>

        {/* GET STARTED */}
        <section className="sec sec-last" id="start">
          <div className="wrap">
            <div className="cta-band">
              <div>
                <h2>Ready to try the pipeline?</h2>
                <p>Join as a candidate to apply and track your application, or open the HR portal to post a role and see ranked candidates.</p>
              </div>
              <div className="btns">
                <button className="lbtn lbtn-solid" style={{ '--fill': 'var(--a1)' }} onClick={() => goTo(candidateCta.to)} data-magnet><Roll>{candidateIn ? 'Go to dashboard' : 'Candidate sign up'}</Roll></button>
                <button className="lbtn lbtn-line" style={{ '--fill': 'var(--bg)' }} onClick={() => goTo(hrIn ? '/hr' : '/hr/signup')} data-magnet><Roll>{hrIn ? 'HR dashboard' : 'HR sign up'}</Roll></button>
              </div>
            </div>
          </div>
        </section>
      </main>

      <footer className="foot">
        <div className="wrap">
          <div className="foot-big"><div><Logo fontSize="inherit" start={footIn} /></div></div>
          <div className="foot-row">
            <p className="credit">Built by Vedika Thalkar and Neha Dhumal, B.E. Information Technology, Vidyalankar Institute of Technology. Guided by Prof. Bhanu Tekwani.</p>
            <nav className="foot-links" aria-label="Footer">
              {!candidateIn && <button onClick={() => goTo('/login')}>Log in</button>}
              <button onClick={() => goTo(candidateCta.to)}>{candidateIn ? 'Dashboard' : 'Sign up'}</button>
              <button onClick={() => goTo(hrIn ? '/hr' : '/hr/login')}>HR portal</button>
              <button onClick={() => scrollToId('top')}>Back to top ↑</button>
            </nav>
          </div>
        </div>
      </footer>
      <Cursor />
    </div>
  );
}
