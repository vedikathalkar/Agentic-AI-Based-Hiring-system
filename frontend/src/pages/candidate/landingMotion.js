import { useEffect, useRef, useState } from 'react';

// All scroll/pointer motion for the home page, written without libraries.
// Reports `motion` for the root class so entrance states only apply when this runs,
// and `.ready` once the preloader has cleared.
export function useLandingMotion(rootRef, menuOpen) {
  const reduce = typeof window !== 'undefined' && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  const seen = (() => { try { return sessionStorage.getItem('hl_intro') === '1'; } catch { return false; } })();
  const [loader, setLoader] = useState({ show: !reduce && !seen, leaving: false, count: 0 });
  const [phase, setPhase] = useState({ motion: !reduce, ready: false });
  const [footIn, setFootIn] = useState(false);
  const startDemoRef = useRef(() => {});
  const menuRef = useRef(menuOpen);
  menuRef.current = menuOpen;

  // Preloader counter, then slide it away and trigger the hero entrance.
  useEffect(() => {
    const ready = () => setPhase((p) => ({ ...p, ready: true }));
    if (!loader.show) {
      const t = setTimeout(ready, 60);
      return () => clearTimeout(t);
    }
    let raf; const start = performance.now(); const timers = [];
    const step = (now) => {
      const p = Math.min(1, (now - start) / 1300);
      const eased = p < 0.5 ? 2 * p * p : 1 - Math.pow(-2 * p + 2, 2) / 2;
      setLoader((l) => ({ ...l, count: Math.round(eased * 100) }));
      if (p < 1) raf = requestAnimationFrame(step);
      else {
        setLoader((l) => ({ ...l, leaving: true }));
        timers.push(setTimeout(ready, 350));
        timers.push(setTimeout(() => setLoader((l) => ({ ...l, show: false })), 950));
        try { sessionStorage.setItem('hl_intro', '1'); } catch { /* private mode */ }
      }
    };
    raf = requestAnimationFrame(step);
    return () => { cancelAnimationFrame(raf); timers.forEach(clearTimeout); };
  }, []); // eslint-disable-line

  useEffect(() => {
    const root = rootRef.current;
    if (!root) return undefined;
    const cleanups = [];
    const $$ = (s) => [...root.querySelectorAll(s)];

    // Split section headings into words for the slide-up reveal.
    $$('h2.split').forEach((h) => {
      if (h.dataset.split) return;
      h.dataset.split = '1';
      const words = h.textContent.trim().split(/\s+/);
      h.setAttribute('aria-label', h.textContent.trim());
      h.innerHTML = words.map((w, i) => `<span class="w" aria-hidden="true"><span style="--i:${i}">${w}</span></span>`).join(' ');
    });
    // Statement words for the scroll-driven fill.
    const statement = root.querySelector('.statement');
    let sWords = [];
    if (statement && !statement.dataset.split) {
      statement.dataset.split = '1';
      statement.innerHTML = statement.textContent.trim().split(/\s+/).map((w) => `<span class="sw">${w}</span>`).join(' ');
    }
    if (statement) sWords = [...statement.querySelectorAll('.sw')];
    $$('[data-reveal]').forEach((g) => [...g.children].forEach((c, i) => c.style.setProperty('--i', i)));

    // Reveal on enter.
    const io = new IntersectionObserver((entries) => {
      entries.forEach((e) => {
        if (!e.isIntersecting) return;
        e.target.classList.add('in');
        if (e.target.id === 'lp-console') startDemoRef.current();
        if (e.target.classList.contains('foot-big')) setFootIn(true);
        io.unobserve(e.target);
      });
    }, { rootMargin: '0px 0px -12% 0px' });
    $$('h2.split, [data-reveal], .foot-big').forEach((el) => io.observe(el));
    const consoleEl = root.querySelector('#lp-console');
    if (consoleEl) io.observe(consoleEl);
    cleanups.push(() => io.disconnect());

    // Scroll-driven pieces.
    const hdr = root.querySelector('.hdr');
    const prog = root.querySelector('.lp-progress');
    const shapes = $$('.hshape');
    const pipe = root.querySelector('.pipe');
    const track = root.querySelector('.track');
    const bar = root.querySelector('.pipe-bar i');
    const nums = $$('.agent .num');
    let lastY = window.scrollY;
    let pinDist = 0;

    const measurePipe = () => {
      if (!pipe || !track) return;
      const desktop = window.innerWidth > 900 && !reduce;
      pipe.classList.toggle('pinned', desktop);
      if (!desktop) { pipe.style.height = ''; track.style.transform = ''; pinDist = 0; return; }
      pinDist = Math.max(0, track.scrollWidth - window.innerWidth);
      pipe.style.height = `${window.innerHeight + pinDist}px`;
    };

    const onScroll = () => {
      const y = window.scrollY;
      const vh = window.innerHeight;
      const max = document.documentElement.scrollHeight - vh;
      if (hdr && !menuRef.current) hdr.classList.toggle('hide', y > lastY && y > 200);
      lastY = y;
      if (prog) prog.style.transform = `scaleX(${max > 0 ? y / max : 0})`;
      if (reduce) return;

      shapes.forEach((s) => s.style.setProperty('--sy', (-y * 0.35 * Number(s.dataset.depth)).toFixed(1)));

      if (statement) {
        const r = statement.getBoundingClientRect();
        const p = Math.min(1, Math.max(0, (vh * 0.78 - r.top) / (r.height + vh * 0.33)));
        const lit = p * sWords.length;
        sWords.forEach((w, i) => { w.style.opacity = String(Math.min(1, Math.max(0.16, 0.16 + (lit - i) * 0.84))); });
      }

      if (pinDist > 0) {
        const top = pipe.getBoundingClientRect().top;
        const p = Math.min(1, Math.max(0, -top / pinDist));
        track.style.transform = `translate3d(${-p * pinDist}px,0,0)`;
        if (bar) bar.style.transform = `scaleX(${p})`;
        nums.forEach((n) => {
          const left = n.getBoundingClientRect().left / window.innerWidth;
          const k = Math.min(1, Math.max(0, (0.98 - left) / 0.35));
          n.style.transform = `translateY(${(1 - k) * 60}%)`;
          n.style.opacity = String(0.15 + k * 0.75);
        });
      }

    };

    measurePipe();
    onScroll();
    const onResize = () => { measurePipe(); onScroll(); };
    window.addEventListener('scroll', onScroll, { passive: true });
    window.addEventListener('resize', onResize);
    window.addEventListener('load', onResize);
    cleanups.push(() => {
      window.removeEventListener('scroll', onScroll);
      window.removeEventListener('resize', onResize);
      window.removeEventListener('load', onResize);
    });

    if (!reduce) {
      // Hero shapes drift away from the pointer.
      const onMove = (e) => {
        const cx = e.clientX / window.innerWidth - 0.5;
        const cy = e.clientY / window.innerHeight - 0.5;
        shapes.forEach((s) => {
          const d = Number(s.dataset.depth);
          s.style.setProperty('--mx', (cx * d * -50).toFixed(1));
          s.style.setProperty('--my', (cy * d * -50).toFixed(1));
        });
      };
      window.addEventListener('mousemove', onMove);
      cleanups.push(() => window.removeEventListener('mousemove', onMove));
    }

    return () => cleanups.forEach((fn) => fn());
  }, []); // eslint-disable-line

  return { loader, phase, footIn, startDemoRef };
}
