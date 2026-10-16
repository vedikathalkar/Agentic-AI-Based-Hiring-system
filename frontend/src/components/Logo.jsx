import { useEffect, useId, useState } from 'react';
import '../styles/logo.css';

// Hirelune logo: a crescent cut into eight segments (one per agent) around a dot.
//   size:  height of the mark in px; the name scales with it
//   mode:  'play'  – intro animation once, then a slow shimmer and a hover wave (default)
//          'loop'  – segments chase round; use as a loading indicator
//          'still' – no animation
//   start: for mode 'play', set false to hold the intro until you flip it to true
//   word:  show the "Hirelune" name next to the mark
//   light: for light backgrounds (last segment and dot turn dark)
//   tone:  'light' keeps the light version on surfaces that are always dark (the sidebar);
//          without it the logo follows the page theme
const SEGS = [
  ['M29 34L55.30 40.12A27 27 0 0 1 49.00 52.14Z', '#FF7A45'],
  ['M29 34L47.95 53.23A27 27 0 0 1 36.20 60.02Z', '#FFC53D'],
  ['M29 34L34.74 60.38A27 27 0 0 1 21.18 59.84Z', '#9BE36B'],
  ['M29 34L19.75 59.37A27 27 0 0 1 8.58 51.66Z', '#4FD1C5'],
  ['M29 34L7.62 50.49A27 27 0 0 1 2.30 38.01Z', '#5AA9FF'],
  ['M29 34L2.12 36.51A27 27 0 0 1 4.29 23.12Z', '#A48BFF'],
  ['M29 34L4.94 21.75A27 27 0 0 1 13.94 11.59Z', '#FF78B6'],
  ['M29 34L15.21 10.79A27 27 0 0 1 28.25 7.01Z', '#F3F1EC'],
];
const CRESCENT = 'M28.33 10.01A24 24 0 1 0 52.38 39.41A19 19 0 0 1 28.33 10.01Z';
const INTRO_MS = 2800;

export function LogoMark({ light = false }) {
  const id = useId();
  return (
    <svg className="hl-mark" viewBox="0 0 64 64" aria-hidden="true">
      <defs><clipPath id={id}><path d={CRESCENT} /></clipPath></defs>
      <g clipPath={`url(#${id})`}>
        {SEGS.map(([d, c], i) => (
          <path key={i} className="hl-seg" style={{ '--i': i }} d={d} fill={i === 7 && light ? '#0E0F13' : c} />
        ))}
      </g>
      <circle className="hl-ping" cx="41" cy="24" r="10" />
      <circle className="hl-dot" cx="41" cy="24" r="10" />
    </svg>
  );
}

export default function Logo({ size = 30, mode = 'play', start = true, word = true, light = false, tone, fontSize, style }) {
  // phase: wait → play → idle (shimmer + hover wave)
  const [phase, setPhase] = useState(() => {
    if (mode !== 'play') return mode;
    if (typeof window !== 'undefined' && window.matchMedia?.('(prefers-reduced-motion: reduce)').matches) return 'still';
    return start ? 'play' : 'wait';
  });

  useEffect(() => {
    if (phase === 'wait' && start) setPhase('play');
  }, [start, phase]);

  useEffect(() => {
    if (phase !== 'play') return undefined;
    const t = setTimeout(() => setPhase('idle'), INTRO_MS);
    return () => clearTimeout(t);
  }, [phase]);

  const cls = ['hl-logo',
    phase === 'wait' && 'hl-wait',
    phase === 'play' && 'hl-play',
    phase === 'idle' && 'hl-idle hl-hover',
    phase === 'loop' && 'hl-loop',
    light && 'hl-light',
    !light && tone !== 'light' && 'hl-auto',
  ].filter(Boolean).join(' ');

  return (
    <span className={cls} style={{ fontSize: fontSize ?? size * 0.7, ...style }} role="img" aria-label="Hirelune">
      <LogoMark light={light} />
      {word && (
        <span className="hl-word" aria-hidden="true">
          {'Hirelune'.split('').map((ch, i) => (
            <span className="hl-l" key={i}><span style={{ '--i': i }}>{ch}</span></span>
          ))}
        </span>
      )}
    </span>
  );
}
