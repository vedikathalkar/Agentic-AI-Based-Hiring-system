import { useEffect, useRef } from 'react';

// Dot + trailing ring cursor, with a gentle magnetic pull on [data-magnet]
// elements. Used on the home page only. Runs for a fine pointer when motion
// is allowed; otherwise it renders nothing visible.
export default function Cursor() {
  const dot = useRef(null);
  const ring = useRef(null);

  useEffect(() => {
    const fine = window.matchMedia('(hover: hover) and (pointer: fine)').matches;
    const reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    if (!fine || reduce) return undefined;
    let mx = -100, my = -100, rx = -100, ry = -100, raf;
    const move = (e) => {
      mx = e.clientX; my = e.clientY;
      if (dot.current) dot.current.style.transform = `translate(${mx}px, ${my}px) translate(-50%, -50%)`;
      const m = e.target.closest?.('[data-magnet]');
      if (m) {
        const r = m.getBoundingClientRect();
        m.style.transform = `translate(${(mx - r.left - r.width / 2) * 0.22}px, ${(my - r.top - r.height / 2) * 0.32}px)`;
      }
    };
    const loop = () => {
      rx += (mx - rx) * 0.16; ry += (my - ry) * 0.16;
      if (ring.current) ring.current.style.transform = `translate(${rx}px, ${ry}px) translate(-50%, -50%)`;
      raf = requestAnimationFrame(loop);
    };
    const over = (e) => {
      const el = ring.current; if (!el) return;
      const view = e.target.closest?.('[data-cursor]');
      const link = e.target.closest?.('a, button');
      el.classList.toggle('is-view', !!view && !link);
      el.classList.toggle('is-link', !!link);
      if (view) el.querySelector('span').textContent = view.getAttribute('data-cursor');
    };
    const leave = (e) => {
      const m = e.target.closest?.('[data-magnet]');
      if (m && !m.contains(e.relatedTarget)) {
        m.style.transition = 'transform .6s cubic-bezier(.2,1.4,.4,1)';
        m.style.transform = '';
        setTimeout(() => { m.style.transition = ''; }, 600);
      }
    };
    window.addEventListener('mousemove', move);
    document.addEventListener('mouseover', over);
    document.addEventListener('mouseout', leave);
    raf = requestAnimationFrame(loop);
    return () => {
      window.removeEventListener('mousemove', move);
      document.removeEventListener('mouseover', over);
      document.removeEventListener('mouseout', leave);
      cancelAnimationFrame(raf);
    };
  }, []);

  return (
    <>
      <div className="cursor" ref={dot} aria-hidden="true" />
      <div className="cursor-ring" ref={ring} aria-hidden="true"><span>View</span></div>
    </>
  );
}
