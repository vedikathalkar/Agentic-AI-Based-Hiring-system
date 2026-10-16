// The illustrated story behind the sign-in form (the design signed off on 2026-10-10).
// The scenes are SVG built from strings, exactly as in that design, and live inside a shadow root
// (see StoryStage.jsx) so their short class names (.pp, .dk, .bb …) can't collide with the app's CSS.

const MARK = `<svg viewBox="0 0 64 64" aria-hidden="true"><defs><clipPath id="hlbig"><path d="M28.33 10.01A24 24 0 1 0 52.38 39.41A19 19 0 0 1 28.33 10.01Z"/></clipPath></defs><g clip-path="url(#hlbig)"><path class="gs" style="--i:0" d="M29 34L55.30 40.12A27 27 0 0 1 49.00 52.14Z" fill="#FF7A45"/><path class="gs" style="--i:1" d="M29 34L47.95 53.23A27 27 0 0 1 36.20 60.02Z" fill="#FFC53D"/><path class="gs" style="--i:2" d="M29 34L34.74 60.38A27 27 0 0 1 21.18 59.84Z" fill="#9BE36B"/><path class="gs" style="--i:3" d="M29 34L19.75 59.37A27 27 0 0 1 8.58 51.66Z" fill="#4FD1C5"/><path class="gs" style="--i:4" d="M29 34L7.62 50.49A27 27 0 0 1 2.30 38.01Z" fill="#5AA9FF"/><path class="gs" style="--i:5" d="M29 34L2.12 36.51A27 27 0 0 1 4.29 23.12Z" fill="#A48BFF"/><path class="gs" style="--i:6" d="M29 34L4.94 21.75A27 27 0 0 1 13.94 11.59Z" fill="#FF78B6"/><path class="gs" style="--i:7" d="M29 34L15.21 10.79A27 27 0 0 1 28.25 7.01Z" fill="#F3F1EC"/></g><circle cx="41" cy="24" r="10" fill="#F3F1EC"/></svg>`;

function seeded(n) { let s = n; return function () { s = (s * 9301 + 49297) % 233280; return s / 233280; }; }
const COL = ['#FFC53D', '#4FD1C5', '#FF78B6', '#5AA9FF', '#A48BFF', '#9BE36B', '#FF7A45'];
function A(sx, sy, x2, y2, cls, d) { return '<g transform="translate(' + sx + ',' + sy + ')"><g class="ar ' + (cls || '') + '" style="--d:' + (d || 0) + 's"><line class="arm" x2="' + x2 + '" y2="' + y2 + '"/></g></g>'; }
function fig(x, y, o) {
  o = o || {};
  const s = o.s || 1.3; const sh = o.sit ? -96 : -118; let body;
  const arms = (o.arms || [[-6, 50], [6, 50]]).map(function (a) { return A(0, sh, a[0], a[1], a[2], a[3]); }).join('');
  if (o.sit) {
    body = '<path class="lg" d="M0 -50 H30 V0"/><rect class="sil" x="-17" y="-108" width="34" height="62" rx="15"/><circle class="sil" cx="0" cy="-127" r="15"/>';
  } else {
    body = '<g transform="translate(0,-68)"><g class="ar l1"><path class="lg" d="M0 0 L-3 68"/></g><g class="ar l2"><path class="lg" d="M0 0 L3 68"/></g></g><rect class="sil" x="-17" y="-130" width="34" height="68" rx="15"/><circle class="sil" cx="0" cy="-148" r="15"/>';
  }
  const tc = (o.turn != null ? 'turn ' : '') + (o.walk != null ? 'wk ' : '') + (o.slump ? 'slump ' : '');
  return '<g class="' + (o.mv || '') + '" style="' + (o.st || '') + '"><g transform="translate(' + x + ',' + y + ')"><g class="' + tc + '" style="--td:' + (o.turn || 0) + 's;--wd:' + (o.walk || 0) + 's;--d:' + (o.d || 2) + 's"><g transform="scale(' + (o.flip ? -s : s) + ',' + s + ')">' + body + arms + (o.extra || '') + '</g></g></g>' + (o.after || '') + '</g>';
}
function T(x, y, t, cl, d, a) { return '<text x="' + x + '" y="' + y + '" class="' + (cl || 'lbl') + (d != null ? ' fi' : '') + '"' + (a ? ' text-anchor="' + a + '"' : '') + ' style="--d:' + (d || 0) + 's">' + t + '</text>'; }
function BB(x, y, w, t, d, keep) { return '<g class="' + (keep ? 'bubk' : 'bub') + '" style="--d:' + d + 's"><rect class="bb" x="' + (x - w / 2) + '" y="' + y + '" width="' + w + '" height="32" rx="16"/><path class="bb" d="M' + (x - 7) + ' ' + (y + 30) + ' L' + x + ' ' + (y + 43) + ' L' + (x + 7) + ' ' + (y + 30) + 'Z"/><text class="bt" x="' + x + '" y="' + (y + 21) + '">' + t + '</text></g>'; }
function chip(x, y, w, t, col, d) { return '<g class="pop" style="--d:' + d + 's"><rect x="' + x + '" y="' + y + '" width="' + w + '" height="28" rx="14" fill="' + col + '" fill-opacity=".16" stroke="' + col + '" stroke-opacity=".7"/><text x="' + (x + w / 2) + '" y="' + (y + 19) + '" text-anchor="middle" class="ct" fill="' + col + '">' + t + '</text></g>'; }
function desk(x, w, top) { const l = 340 - top - 14; return '<rect class="dk" x="' + x + '" y="' + top + '" width="' + w + '" height="14" rx="4"/><rect class="dk2" x="' + (x + 14) + '" y="' + (top + 14) + '" width="10" height="' + l + '"/><rect class="dk2" x="' + (x + w - 24) + '" y="' + (top + 14) + '" width="10" height="' + l + '"/>'; }
function laptop(x, top, col) { return '<rect x="' + x + '" y="' + (top - 48) + '" width="74" height="48" rx="5" fill="#161922" stroke="#4A4F63" stroke-width="2"/><rect x="' + (x + 6) + '" y="' + (top - 42) + '" width="62" height="36" rx="3" fill="' + (col || '#4FD1C5') + '" fill-opacity=".28" class="dfl"/>'; }
function paper(x, y, r, cls, d, t, yy) { return '<g class="' + cls + '" style="--d:' + d + 's;--t:' + (t || 3.2) + 's;--y:' + (yy || 230) + 'px;--r0:' + (r - 14) + 'deg;--r1:' + (r + 16) + 'deg"><g transform="translate(' + x + ',' + y + ') rotate(' + r + ')"><rect class="pp" width="26" height="34" rx="3"/><rect class="ln" x="5" y="7" width="16" height="3"/><rect class="ln" x="5" y="14" width="13" height="3"/><rect class="ln" x="5" y="21" width="15" height="3"/></g></g>'; }
function mark(x, y, s, cls) { return MARK.replace('<svg ', '<svg x="' + x + '" y="' + y + '" width="' + s + '" height="' + s + '" class="' + (cls || '') + '" '); }
function conf(n, x0, x1, d0, seed) { const r = seeded(seed); let h = ''; for (let i = 0; i < n; i++) { const cx = x0 + r() * (x1 - x0); h += '<g class="fall" style="--d:' + (d0 + r() * 2.4).toFixed(2) + 's;--t:' + (2 + r() * 1.4).toFixed(2) + 's;--y:330px;--r0:0deg;--r1:' + Math.round(r() * 500) + 'deg"><rect x="' + cx.toFixed(0) + '" y="10" width="7" height="11" fill="' + COL[i % 7] + '"/></g>'; } return h; }
function city(x0, seed, col) {
  const r = seeded(seed); let h = ''; let x = x0;
  while (x < 790) {
    const w = 36 + r() * 34; const hh = 60 + r() * 90;
    h += '<rect x="' + x.toFixed(0) + '" y="' + (340 - hh).toFixed(0) + '" width="' + w.toFixed(0) + '" height="' + hh.toFixed(0) + '" fill="' + (col || '#1E212C') + '"/>';
    for (let k = 0; k < 4; k++) if (r() > 0.45) h += '<rect x="' + (x + 6 + r() * (w - 16)).toFixed(0) + '" y="' + (340 - hh + 10 + r() * (hh - 30)).toFixed(0) + '" width="5" height="6" fill="#FFC53D" fill-opacity=".5"/>';
    x += w + 6;
  }
  return h;
}

const IC = {
  env: '<rect x="3" y="6" width="18" height="12" rx="2"/><path d="M3 8l9 6 9-6"/>',
  clock: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
  warn: '<path d="M12 3L22 20H2Z"/><path d="M12 10v4M12 17v.5"/>',
  eye: '<path d="M2 12s4-7 10-7 10 7 10 7-4 7-10 7S2 12 2 12z"/><circle cx="12" cy="12" r="3"/>',
  moon: '<path d="M20 14A8 8 0 1 1 10 4a6 6 0 0 0 10 10z"/>',
  cal: '<rect x="3" y="5" width="18" height="16" rx="2"/><path d="M3 10h18M8 3v4M16 3v4"/>',
  exit: '<path d="M5 3h8v18H5zM13 12h8M18 9l3 3-3 3"/>',
  x: '<circle cx="12" cy="12" r="9"/><path d="M8.5 8.5l7 7M15.5 8.5l-7 7"/>',
  check: '<circle cx="12" cy="12" r="9"/><path d="M8 12l3 3 5-6"/>',
  bulb: '<path d="M9 18h6M10 21h4M12 3a6 6 0 0 0-4 10.5c.7.7 1 1.5 1 2.5h6c0-1 .3-1.8 1-2.5A6 6 0 0 0 12 3z"/>',
  plane: '<path d="M2 12L22 3l-6 18-4-7z"/>',
  help: '<circle cx="12" cy="12" r="9"/><path d="M9.5 9.5a2.5 2.5 0 1 1 3.5 2.3c-.7.4-1 1-1 1.7M12 17v.5"/>',
  user: '<circle cx="12" cy="8" r="4"/><path d="M4 21a8 8 0 0 1 16 0"/>',
  mic: '<rect x="9" y="3" width="6" height="11" rx="3"/><path d="M5 11a7 7 0 0 0 14 0M12 18v3"/>',
  target: '<circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="5"/><circle cx="12" cy="12" r="1.5"/>',
  star: '<path d="M12 3l2.7 5.6 6.1.9-4.4 4.3 1 6.1L12 17l-5.4 2.9 1-6.1L3.2 9.5l6.1-.9z"/>',
  hour: '<path d="M6 3h12M6 21h12M7 3c0 6 10 6 10 9s-10 3-10 9"/>',
};
function ic(n, x, y, c) { return '<g transform="translate(' + x + ',' + y + ')" fill="none" stroke="' + c + '" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">' + IC[n] + '</g>'; }
function cap(items) {
  const n = items.length; let h = '';
  items.forEach(function (it, i) {
    const cx = 800 / n * (i + 0.5); const w = 32 + it[1].length * 8.4; const x0 = cx - w / 2; const d = (1 + i * 1.3).toFixed(1);
    h += '<g class="pop" style="--d:' + d + 's">' + ic(it[0], x0, 366, it[2]) + '<text x="' + (x0 + 32) + '" y="383" font-size="15" font-weight="700" fill="' + it[2] + '">' + it[1] + '</text></g>';
    if (i) h += '<path class="fi" d="M' + (800 / n * i - 5) + ' 372 l6 8 -6 8" stroke="#6A6F83" fill="none" stroke-width="2.4" stroke-linecap="round" style="--d:' + (d - 0.3) + 's"/>';
  });
  return h;
}
function sweat(x, y, d) { let h = ''; for (let i = 0; i < 2; i++) h += '<g class="fall" style="--d:' + ((d || 0) + i * 0.7) + 's;--t:1.5s;--y:30px;--r0:0deg;--r1:0deg"><path d="M0 0q-5 8 0 11q5-3 0-11z" fill="#5AA9FF" transform="translate(' + (x + i * 9) + ',' + (y - i * 5) + ')"/></g>'; return h; }
function exc(x, y, d, col) { return '<g class="pop" style="--d:' + d + 's"><circle cx="' + x + '" cy="' + y + '" r="12" fill="' + (col || '#FF6B81') + '"/><text x="' + x + '" y="' + (y + 6) + '" text-anchor="middle" font-size="17" font-weight="800" fill="#14161C">!</text></g>'; }
function zz(x, y) { let h = ''; for (let i = 0; i < 3; i++) h += '<text class="qm" x="' + (x + i * 12) + '" y="' + y + '" fill="#9396A3" style="--d:' + (i * 0.9) + 's;font-size:' + (16 + i * 5) + 'px">z</text>'; return h; }
function spark(x, y, col, d) { return '<g class="pop" style="--d:' + d + 's"><path class="dfl" d="M' + x + ' ' + (y - 14) + 'L' + (x + 4) + ' ' + (y - 4) + 'L' + (x + 14) + ' ' + y + 'L' + (x + 4) + ' ' + (y + 4) + 'L' + x + ' ' + (y + 14) + 'L' + (x - 4) + ' ' + (y + 4) + 'L' + (x - 14) + ' ' + y + 'L' + (x - 4) + ' ' + (y - 4) + 'Z" fill="' + col + '"/></g>'; }
function glow(x, y, d) { return '<g class="pop" style="--d:' + d + 's"><circle class="dfl" cx="' + x + '" cy="' + y + '" r="26" fill="#FFC53D" fill-opacity=".25"/>' + ic('bulb', x - 12, y - 12, '#FFC53D') + '</g>'; }
const R_ = '#FF6B81'; const Y_ = '#FFC53D'; const G_ = '#9BE36B'; const B_ = '#5AA9FF'; const T_ = '#4FD1C5'; const P_ = '#A48BFF';

const SC = {};
SC.e1 = function () {
  let h = desk(250, 330, 260) + laptop(440, 260);
  h += fig(330, 340, { sit: 1, arms: [[42, 34, 'a-type'], [40, 32, 'a-type2']] });
  for (let k = 1; k <= 7; k++) h += '<rect class="pp pop" x="510" y="' + (260 - k * 7) + '" width="52" height="7" rx="2" style="--d:' + (0.8 + k * 0.7) + 's"/>';
  for (let i = 0; i < 13; i++) { const x = 215 + i * 31 + (i % 3) * 6; h += paper(x, 10 + (i % 4) * 8, (i * 37 % 50) - 25, 'fall', (i * 0.27).toFixed(2), 3.4, i % 3 ? 215 : 300); }
  return h + '<text x="36" y="104" class="big" fill="#FF7A45" data-count="412">0</text>' + T(38, 132, 'new resumes since Friday', 'lbl', 0.2) + T(330, 354, 'You, Monday 9:00', 'lbl2', 0.6, 'middle');
};
SC.e2 = function () {
  let h = '<g transform="translate(400,74)"><circle class="ck" r="36"/><g class="ar spin"><line class="hand" y2="-28"/></g><g class="ar slow"><line class="hand" y2="-18"/></g><circle r="3.5" fill="#F3F1EC"/></g>';
  const lab = ['Sorting resumes', 'Reading resumes', 'Shortlisting', 'Re-reading resumes'];
  for (let i = 0; i < 4; i++) {
    const dx = 14 + i * 196; const n = 3 + (i % 2) * 3;
    h += desk(dx, 176, 282) + fig(dx + 48, 340, { s: 0.95, sit: 1, arms: [[40, 32, 'a-type'], [38, 30, 'a-type2']] });
    for (let k = 1; k <= n; k++) h += '<rect class="pp pop" x="' + (dx + 112) + '" y="' + (282 - k * 8) + '" width="48" height="8" rx="2" stroke="#171A23" style="--d:' + (0.6 + i * 0.3 + k * 0.5) + 's"/>';
    h += chip(dx + 4, 150, 160, lab[i], i % 2 ? '#FFC53D' : '#FF9E6B', 0.4 + i * 0.3);
  }
  return h + chip(40, 44, 150, '3 min per resume', '#FFC53D', 0.8) + chip(600, 44, 170, '20+ hours every week', '#FF6B81', 1.6) + sweat(262, 196, 1) + sweat(654, 196, 1.6);
};
SC.e3 = function () {
  let h = '<rect x="320" y="26" width="160" height="104" rx="10" fill="#1B1E29" stroke="#3A3F51" stroke-width="2"/><rect x="320" y="26" width="160" height="22" rx="10" fill="#5AA9FF" fill-opacity=".35"/>' + T(400, 42, 'INTERVIEW CALENDAR', 'lbl2', 0.2, 'middle');
  for (let r = 0; r < 4; r++) h += '<rect x="332" y="' + (56 + r * 17) + '" width="136" height="11" rx="3" fill="#2C303D"/>';
  h += '<rect class="dfl" x="344" y="73" width="70" height="11" rx="3" fill="#FF6B81"/><rect class="dfl" x="378" y="73" width="70" height="11" rx="3" fill="#FF6B81" fill-opacity=".8" style="animation-delay:.4s"/>';
  const lab = ['Scheduling interviews', 'Calling candidates', 'Emailing panelists', 'Fixing clashes'];
  for (let i = 0; i < 4; i++) { const dx = 14 + i * 196; h += desk(dx, 176, 282) + laptop(dx + 96, 282, i % 2 ? '#FF6B81' : '#5AA9FF') + fig(dx + 48, 340, { s: 0.95, sit: 1, arms: [[40, 32, 'a-type'], [38, 30, 'a-type2']] }); h += chip(dx + (i ? 0 : 4), 150, 170, lab[i], i % 2 ? '#FF6B81' : '#5AA9FF', 0.4 + i * 0.3); }
  for (let m = 0; m < 5; m++) h += '<g class="mvl" style="--a:-40px;--b:840px;--t:' + (5 + m * 0.6) + 's;--d:' + (m * 0.9) + 's"><g transform="translate(0,' + (116 + (m % 2) * 14) + ')"><rect width="22" height="15" rx="2" fill="#E9E5DA"/><path d="M0 1l11 8 11-8" stroke="#8A8577" fill="none" stroke-width="1.5"/></g></g>';
  return h + BB(600, 66, 230, 'Can we move to Friday?', 1.6) + exc(58, 128, 2, '#FF6B81');
};
SC.e4 = function () {
  let h = '<rect x="690" y="150" width="100" height="190" fill="#1E212C" stroke="#3A3F51"/><rect x="722" y="250" width="36" height="90" fill="#0B0C10"/>' + T(740, 142, 'OTHER OFFER', 'lbl2', 0.3, 'middle');
  h += desk(70, 200, 262) + laptop(150, 262, '#FF6B81') + fig(135, 340, { sit: 1, arms: [[8, -30, 'a-scr']] });
  const xs = [330, 390, 450, 510];
  xs.forEach(function (x, i) { const d = (4 - i) * 1.1 - 0.6; h += fig(x, 340, { s: 1.15, flip: 1, turn: d.toFixed(2), walk: d.toFixed(2), mv: 'mvxo', st: '--a:0px;--b:' + (740 - x) + 'px;--t:2.4s;--d:' + d.toFixed(2) + 's' }); });
  h += chip(560, 98, 170, 'Accepted elsewhere', '#FF6B81', 2.2);
  return h + '<text x="36" y="100" class="big" fill="#FF6B81" data-count="23">0</text>' + T(38, 128, 'days to fill one role', 'lbl', 0.2) + T(135, 354, 'You, week 3', 'lbl2', 0.5, 'middle');
};
SC.e5 = function () {
  let h = '';
  for (let i = 0; i < 4; i++) h += '<g class="mvlo" style="--a:0px;--b:96px;--t:2.4s;--d:' + (i * 0.6) + 's"><g transform="translate(30,' + (150 + i * 16) + ') rotate(' + (i * 7 - 10) + ')"><rect class="pp" width="24" height="32" rx="3"/><rect class="ln" x="4" y="7" width="15" height="3"/><rect class="ln" x="4" y="14" width="12" height="3"/></g></g>';
  h += '<rect x="140" y="82" width="190" height="124" rx="12" class="win"/>' + mark(204, 92, 58) + '<rect x="156" y="164" width="158" height="9" rx="4.5" fill="#4FD1C5" fill-opacity=".55"/><rect x="156" y="180" width="110" height="9" rx="4.5" fill="#FFC53D" fill-opacity=".5"/><rect x="226" y="206" width="18" height="40" class="dk2"/><rect x="170" y="246" width="130" height="14" rx="4" class="dk"/>' + T(235, 72, 'HIRELUNE', 'lbl2', 0.3, 'middle');
  const rows = [['AK', 'Asha K.', 'Why: strong React skills', '92%', '#FFC53D'], ['RM', 'Rohan M.', 'Why: 5 yrs, Node.js depth', '87%', '#4FD1C5'], ['SP', 'Sneha P.', 'Why: React with Vue', '81%', '#FF78B6']];
  h += '<path class="fi" d="M334 144 h12" stroke="#4A4F63" stroke-width="3" style="--d:1s"/>';
  rows.forEach(function (r, i) { const y = 44 + i * 40; h += '<g class="pop" style="--d:' + (1.2 + i * 0.5) + 's"><rect class="crd" x="350" y="' + y + '" width="236" height="34" rx="10"' + (i ? '' : ' stroke="#FFC53D" stroke-width="2"') + '/><circle cx="368" cy="' + (y + 17) + '" r="10" fill="' + r[4] + '"/><text x="368" y="' + (y + 21) + '" text-anchor="middle" font-size="9" font-weight="800" fill="#14161C">' + r[0] + '</text><text x="386" y="' + (y + 15) + '" class="cw">' + r[1] + '</text><text x="386" y="' + (y + 27) + '" class="cs" font-size="10">' + r[2] + '</text><text x="574" y="' + (y + 21) + '" text-anchor="end" font-size="12" font-weight="700" fill="#9BE36B">' + r[3] + '</text></g>'; });
  h += '<g class="pop" style="--d:2.2s">' + ic('star', 350, 168, '#FFC53D') + '<text x="380" y="186" class="cw" fill="#FFC53D">Top candidate</text></g>';
  h += fig(650, 340, { arms: [[40, 18, 'a-shake'], [-6, 50]] }) + fig(754, 340, { flip: 1, walk: 2.2, mv: 'mvx', st: '--a:70px;--b:0px;--t:2s;--d:2.2s', arms: [[40, 18, 'a-shake'], [-6, 50]] });
  return h + chip(600, 44, 170, 'Hired in 12 days', '#FFC53D', 4) + conf(24, 610, 780, 4.4, 5) + T(650, 354, 'You', 'lbl2', 0.5, 'middle') + T(748, 354, 'Candidate', 'lbl2', 0.5, 'middle');
};
SC.c1 = function () {
  let h = city(430, 3, '#1B1E29') + desk(90, 240, 262) + laptop(230, 262, '#5AA9FF') + fig(170, 340, { sit: 1, arms: [[42, 32, 'a-type'], [40, 30, 'a-type2']] });
  h += '<circle cx="640" cy="236" r="62" fill="#050608" stroke="#343846"/><circle cx="640" cy="236" r="40" fill="#000"/>';
  for (let i = 0; i < 9; i++) h += '<g class="fly" style="--d:' + (i * 0.45).toFixed(2) + 's;--dy:' + ((i % 3) * 12 - 8) + 'px;--dy2:' + (20 + (i % 3) * 10) + 'px"><g transform="translate(290,' + (190 + (i % 3) * 8) + ')"><path d="M0 0 L30 -10 L11 5 L9 15 L5 6Z" fill="#E9E5DA"/></g></g>';
  return h + '<text x="36" y="100" class="big" fill="#5AA9FF" data-count="100">0</text>' + T(38, 128, 'applications sent', 'lbl', 0.2) + chip(570, 314, 140, '0 replies', '#FF6B81', 3.6) + T(170, 354, 'You, week 1', 'lbl2', 0.5, 'middle');
};
SC.c2 = function () {
  let h = city(500, 8, '#1B1E29') + fig(250, 340, { slump: 1, d: 2.4, arms: [[22, 10, ''], [-6, 50]], extra: '<rect x="18" y="-116" width="10" height="17" rx="2" fill="#4A4F63"/>' });
  h += '<g class="pop" style="--d:2s"><circle cx="230" cy="60" r="24" fill="#3A3F51"/><circle cx="258" cy="52" r="30" fill="#3A3F51"/><circle cx="290" cy="62" r="22" fill="#3A3F51"/><rect x="230" y="60" width="60" height="22" fill="#3A3F51"/></g>';
  for (let i = 0; i < 7; i++) h += '<g class="fall" style="--d:' + (2.4 + i * 0.3) + 's;--t:1.1s;--y:150px;--r0:0deg;--r1:0deg"><line x1="' + (222 + i * 11) + '" y1="92" x2="' + (218 + i * 11) + '" y2="104" stroke="#5AA9FF" stroke-width="2.5" stroke-linecap="round"/></g>';
  const m = [['Northwind Labs', 'We regret to inform you that…'], ['Bluepeak', 'Moving forward with others'], ['Kiteflow', 'Position has been filled']];
  m.forEach(function (e, i) { const y = 44 + i * 62; h += '<g class="pop" style="--d:' + (0.5 + i * 1.2) + 's"><rect class="crd" x="480" y="' + y + '" width="290" height="52" rx="12"/><rect x="494" y="' + (y + 16) + '" width="26" height="20" rx="3" fill="#2C303D"/><path d="M494 ' + (y + 18) + ' l13 9 l13 -9" stroke="#9396A3" fill="none" stroke-width="1.6"/><text x="532" y="' + (y + 22) + '" class="cw">' + e[0] + '</text><text x="532" y="' + (y + 40) + '" class="cs">' + e[1] + '</text><circle cx="750" cy="' + (y + 26) + '" r="10" fill="#FF6B81" fill-opacity=".25" stroke="#FF6B81"/><path d="M745 ' + (y + 21) + ' l10 10 M755 ' + (y + 21) + ' l-10 10" stroke="#FF6B81" stroke-width="2" stroke-linecap="round"/></g>'; });
  return h + chip(520, 248, 160, 'No reason given', '#FF6B81', 4.4) + T(250, 354, 'You, week 3', 'lbl2', 0.5, 'middle');
};
SC.c3 = function () {
  let h = city(430, 12, '#1B1E29') + '<rect class="dk" x="110" y="276" width="170" height="14" rx="4"/><rect class="dk2" x="126" y="290" width="10" height="50"/><rect class="dk2" x="254" y="290" width="10" height="50"/>';
  h += fig(205, 340, { sit: 1, arms: [[8, -30, 'a-scr'], [3, -33, 'a-scr']] });
  const qs = [[170, '#A48BFF', 0], [200, '#FF6B81', 0.8], [235, '#A48BFF', 1.6], [185, '#FFC53D', 2.4], [220, '#FF6B81', 3.2]];
  qs.forEach(function (q) { h += '<text class="qm" x="' + q[0] + '" y="150" fill="' + q[1] + '" style="--d:' + q[2] + 's">?</text>'; });
  [[0, '0s'], [2.2, '0s'], [4.1, '0s']].forEach(function (w, i) { h += fig(820, 332, { s: 1.0, flip: 1, walk: '0', mv: 'mvl', st: '--a:0px;--b:-900px;--t:' + (7 + i) + 's;--d:' + w[0] + 's', arms: [[-4, 50], [4, 50]], after: '<g transform="translate(820,142)"><rect x="-34" y="-12" width="68" height="24" rx="12" fill="#9BE36B"/><path d="M-24 0l4 4 7-8" stroke="#14161C" stroke-width="2.4" fill="none" stroke-linecap="round" stroke-linejoin="round"/><text x="4" y="5" text-anchor="middle" font-size="13" font-weight="800" fill="#14161C">Hired</text></g>' }); });
  return h + BB(205, 58, 150, 'Why not me?', 1.2, 1) + T(205, 354, 'You, week 6', 'lbl2', 0.5, 'middle');
};
SC.c4 = function () {
  let h = desk(60, 250, 262) + laptop(200, 262, '#FFC53D') + fig(150, 340, { sit: 1, arms: [[42, 32, 'a-type'], [40, 30, 'a-type2']] });
  h += '<path class="fi" d="M276 214 C330 214 350 190 398 180" stroke="#FFC53D" stroke-width="2.5" stroke-dasharray="6 7" fill="none" style="--d:.6s"/>';
  h += '<g class="pop" style="--d:.4s"><rect class="crd" x="400" y="30" width="376" height="282" rx="16"/><rect x="400" y="30" width="376" height="40" rx="16" fill="#FFC53D" fill-opacity=".12"/>' + mark(414, 38, 24) + '<text x="446" y="56" class="cw">Hirelune practice</text><text x="760" y="56" text-anchor="end" class="cs">Mock interview</text></g>';
  h += '<g class="fi" style="--d:1.2s"><rect x="416" y="82" width="344" height="36" rx="10" fill="#2C303D"/><text x="430" y="105" class="cw" font-weight="600">Walk me through your last project.</text></g>';
  h += '<g class="bars fi" style="--d:1.8s" transform="translate(430,152)">'; for (let i = 0; i < 20; i++) h += '<rect x="' + (i * 9) + '" y="-18" width="5" height="36" rx="2.5" fill="#FFC53D" style="animation-delay:' + (i * 0.06).toFixed(2) + 's"/>'; h += '</g><text class="fi" style="--d:1.8s" x="760" y="157" text-anchor="end" font-size="12" fill="#9396A3">You are speaking</text>';
  h += '<g class="pop" style="--d:3s">' + ic('check', 414, 184, '#9BE36B') + '<text x="446" y="202" class="cw">Clear structure</text></g><g class="pop" style="--d:3.8s">' + ic('bulb', 414, 214, '#FFC53D') + '<text x="446" y="232" class="cw">Add one number to show impact</text></g>';
  h += '<g class="fi" style="--d:4.6s"><text x="416" y="270" class="cs">Fit for Senior React Developer</text><rect x="416" y="278" width="344" height="12" rx="6" fill="#2C303D"/><rect x="416" y="278" width="323" height="12" rx="6" fill="#9BE36B"/><text x="760" y="270" text-anchor="end" class="cw" fill="#9BE36B">94%</text></g>';
  return h + glow(150, 86, 1.2) + T(150, 354, 'You, practising on Hirelune', 'lbl2', 0.5, 'middle');
};
SC.c5 = function () {
  let h = '<g class="sun"><circle cx="400" cy="250" r="90" fill="#FFC53D" fill-opacity=".16"/><circle cx="400" cy="250" r="58" fill="#FFC53D" fill-opacity=".28"/></g>' + city(30, 21, '#1B1E29');
  h += fig(330, 340, { arms: [[54, 18, 'a-shake'], [-28, -62, 'a-wave']], extra: '<g transform="rotate(-10 -30 -200)"><rect class="pp" x="-48" y="-224" width="34" height="44" rx="3"/><rect class="ln" x="-42" y="-214" width="22" height="3"/><rect class="ln" x="-42" y="-206" width="18" height="3"/><path d="M-42 -192 q4 -8 8 0 t8 0" stroke="#4FD1C5" fill="none" stroke-width="2"/></g>' }) + fig(470, 340, { flip: 1, arms: [[54, 18, 'a-shake'], [-6, 50]] });
  return h + chip(310, 40, 180, 'Offer accepted', '#9BE36B', 2) + conf(30, 240, 580, 2.6, 9) + T(330, 354, 'You', 'lbl2', 0.5, 'middle') + T(470, 354, 'Your new manager', 'lbl2', 0.5, 'middle');
};

function wrap(k, f) { const o = SC[k]; SC[k] = function () { return o() + f(); }; }
wrap('e1', function () { return sweat(352, 150, 1) + exc(300, 122, 1.4) + cap([['env', '412 resumes', Y_], ['clock', '3 min each', Y_], ['warn', '20+ hours a week', R_]]); });
wrap('e2', function () { return cap([['eye', 'Many people, one resume pile', Y_], ['clock', 'Hours per role', Y_], ['moon', 'Late nights', R_]]); });
wrap('e3', function () { return cap([['cal', 'Interviews to schedule', Y_], ['env', 'Endless back-and-forth', R_], ['x', 'Clashes and delays', R_]]); });
wrap('e4', function () { return sweat(155, 150, 1) + exc(182, 124, 1.6) + cap([['hour', 'Slow process', Y_], ['exit', 'Candidates leave', R_], ['x', 'Offers lost', R_]]); });
wrap('e5', function () { return cap([['check', 'Resumes read and ranked', G_], ['bulb', 'Reasons for every pick', Y_], ['star', 'Top candidate, hired fast', T_]]); });
wrap('c1', function () { return sweat(188, 150, 1) + zz(196, 128) + cap([['plane', 'Apply everywhere', B_], ['x', 'No reply', R_], ['help', 'No idea why', R_]]); });
wrap('c2', function () { return cap([['env', 'Form rejections', R_], ['x', 'Every week', R_], ['help', 'No reason given', R_]]); });
wrap('c3', function () { return cap([['help', 'No feedback', P_], ['check', 'Others get Hired', G_], ['exit', 'No way forward', R_]]); });
wrap('c4', function () { return cap([['user', 'Profile built', Y_], ['mic', 'Practise with feedback', T_], ['target', 'Ready: 94% fit', G_]]); });
wrap('c5', function () { return spark(330, 104, Y_, 1.5) + spark(470, 104, G_, 1.9) + cap([['check', 'Offer in hand', G_], ['star', 'You always knew where you stood', Y_]]); });

// role 'ent' = Enterprise (HR), 'talent' = Candidate
export const STORIES = {
  ent: [
    { c: 'Chapter 1 of 5 · Monday, 9:00', h: '400 resumes. One Monday.', s: 'Every opening floods your inbox before the week has even started.', tint: 'rgba(255,122,69,.13)', tc: '#FF7A45', html: SC.e1 },
    { c: 'Chapter 2 of 5 · Tuesday, 6:40 pm', h: 'Read by hand, one by one.', s: 'Hours go into skimming resumes that a clear system could sort in minutes.', tint: 'rgba(255,197,61,.12)', tc: '#FFC53D', html: SC.e2 },
    { c: 'Chapter 3 of 5 · Wednesday, all day', h: 'Gut feel scores. Email schedules.', s: 'Spreadsheets, back-and-forth threads and double-booked calendars.', tint: 'rgba(90,169,255,.12)', tc: '#5AA9FF', html: SC.e3 },
    { c: 'Chapter 4 of 5 · Three weeks later', h: 'Good people slip away.', s: 'While you screen, the best candidates accept someone else’s offer.', tint: 'rgba(255,107,129,.12)', tc: '#FF6B81', html: SC.e4 },
    { c: 'Chapter 5 of 5 · Then Hirelune', h: 'Then Hirelune.', s: 'Resumes read, ranked and explained. Interviews booked. Hired in days, not weeks.', tint: 'rgba(255,197,61,.18)', tc: '#FFC53D', html: SC.e5 },
  ],
  talent: [
    { c: 'Chapter 1 of 5 · Week one', h: 'Apply. Apply. Apply.', s: 'Dozens of applications, and no idea if anyone has read them.', tint: 'rgba(90,169,255,.12)', tc: '#5AA9FF', html: SC.c1 },
    { c: 'Chapter 2 of 5 · Week three', h: 'Then silence, or a form “no”.', s: 'Rejections arrive with no reason and nothing to learn from.', tint: 'rgba(255,107,129,.12)', tc: '#FF6B81', html: SC.c2 },
    { c: 'Chapter 3 of 5 · Week six', h: 'No feedback. No way forward.', s: 'You can’t improve what nobody will explain.', tint: 'rgba(164,139,255,.12)', tc: '#A48BFF', html: SC.c3 },
    { c: 'Chapter 4 of 5 · Then Hirelune', h: 'Then Hirelune.', s: 'Your profile builds itself, you practise for free, and roles find you.', tint: 'rgba(255,197,61,.18)', tc: '#FFC53D', html: SC.c4 },
    { c: 'Chapter 5 of 5 · Offer accepted', h: 'Offer accepted.', s: 'From first application to final offer, you always know where you stand.', tint: 'rgba(155,227,107,.14)', tc: '#9BE36B', html: SC.c5 },
  ],
};

export const sceneMarkup = (role) => STORIES[role].map((c) => `<div class="scn"><div class="artbox"><svg viewBox="0 0 800 400" preserveAspectRatio="xMidYMid meet" aria-hidden="true"><rect class="flr" x="0" y="340" width="800" height="60"/><line class="flr2" x1="0" x2="800" y1="340" y2="340"/>${c.html()}</svg></div></div>`).join('');

export function countUp(el) {
  const to = +el.getAttribute('data-count'); const t0 = performance.now();
  (function f(n) { const p = Math.min(1, (n - t0) / 1800); el.textContent = Math.round(to * (1 - Math.pow(1 - p, 3))); if (p < 1) requestAnimationFrame(f); }(t0));
}

// Scene styles, verbatim from the design. They are applied inside a shadow root only.
export const SCENE_CSS = `
:host{display:block;position:fixed;inset:0;z-index:0}
*{box-sizing:border-box}
.stage{position:absolute;inset:0;overflow:hidden;background:#0E0F13}
.stage:before{content:"";position:absolute;inset:0;background:radial-gradient(90% 70% at 25% 80%,var(--tint,rgba(255,197,61,.10)),transparent 65%);transition:background .8s}
.scn{position:absolute;inset:0;opacity:0;visibility:hidden;transition:opacity .7s,visibility 0s .7s;pointer-events:none}
.scn.on{opacity:1;visibility:visible;transition:opacity .7s}
.shade{position:absolute;inset:0;pointer-events:none;background:linear-gradient(0deg,rgba(14,15,19,.72) 0%,rgba(14,15,19,.38) 28%,rgba(14,15,19,0) 46%),linear-gradient(90deg,rgba(14,15,19,.0) 0%,rgba(14,15,19,.0) 46%,rgba(14,15,19,.55) 78%,rgba(14,15,19,.8) 100%)}
.artbox{position:absolute;left:clamp(16px,3vw,48px);top:clamp(70px,9vh,110px);width:calc(100% - 600px);min-width:300px;max-width:860px;aspect-ratio:2/1;max-height:50vh;border-radius:26px;overflow:hidden;border:1px solid rgba(255,255,255,.09);background:linear-gradient(180deg,#262A38,#171A23);box-shadow:0 30px 80px rgba(0,0,0,.45)}
.artbox:before{content:"";position:absolute;inset:0;background:radial-gradient(70% 90% at 50% 100%,var(--tint,rgba(255,197,61,.2)),transparent 70%);opacity:1}
.artbox>svg{position:relative;width:100%;height:100%;display:block}
.artbox text{font-family:'Instrument Sans',system-ui,-apple-system,'Segoe UI',sans-serif}
.flr{fill:rgba(0,0,0,.28)}.flr2{stroke:rgba(255,255,255,.12)}
.sil{fill:#08090C;stroke:rgba(255,255,255,.16);stroke-width:1}
.lg{fill:none;stroke:#08090C;stroke-width:14;stroke-linecap:round;stroke-linejoin:round}
.arm{fill:none;stroke:#08090C;stroke-width:12;stroke-linecap:round}
.ar{transform-origin:0 0}
.dk{fill:#3A3F51}.dk2{fill:#2C303D}
.win{fill:#1B1E29;stroke:#3A3F51;stroke-width:3}
.pp{fill:#E9E5DA}.ln{fill:#B3AEA1}
.bb{fill:#F3F1EC}
.bt{font-size:13px;font-weight:600;fill:#14161C;text-anchor:middle}
.ct{font-size:12.5px;font-weight:700}
.big{font-family:'Syne','Arial Black',system-ui,sans-serif;font-weight:800;font-size:62px}
.lbl{font-size:14px;fill:#C9C7C1}
.lbl2{font-size:12px;fill:#9396A3;text-anchor:middle;letter-spacing:.08em;text-transform:uppercase}
.ck{fill:#12141A;stroke:#4A4F63;stroke-width:3}
.hand{stroke:#F3F1EC;stroke-width:3;stroke-linecap:round}
.crd{fill:#1C1F28;stroke:#3A3F51}
.cw{font-size:13px;fill:#F3F1EC;font-weight:700}
.cs{font-size:12px;fill:#9396A3}
.qm{font-weight:800;font-size:30px}
@keyframes afi{from{opacity:0}to{opacity:1}}
@keyframes pop{from{transform:scale(.2);opacity:0}to{transform:scale(1);opacity:1}}
@keyframes bubk{0%{opacity:0;transform:scale(.6)}12%{opacity:1;transform:scale(1)}85%{opacity:1}100%{opacity:0}}
@keyframes fallk{0%{transform:translateY(-60px) rotate(var(--r0,-20deg));opacity:0}12%{opacity:1}85%{opacity:1}100%{transform:translateY(var(--y,230px)) rotate(var(--r1,25deg));opacity:0}}
@keyframes mvx{from{transform:translateX(var(--a,0px))}to{transform:translateX(var(--b,0px))}}
@keyframes mvxo{0%{transform:translateX(var(--a,0px));opacity:1}85%{opacity:1}100%{transform:translateX(var(--b,0px));opacity:0}}
@keyframes turnA{from{transform:scaleX(1)}to{transform:scaleX(-1)}}
@keyframes stepA{0%{transform:rotate(0)}25%{transform:rotate(-24deg)}75%{transform:rotate(24deg)}100%{transform:rotate(0)}}
@keyframes stepB{0%{transform:rotate(0)}25%{transform:rotate(24deg)}75%{transform:rotate(-24deg)}100%{transform:rotate(0)}}
@keyframes aType{from{transform:rotate(-6deg)}to{transform:rotate(7deg)}}
@keyframes aWave{from{transform:rotate(-18deg)}to{transform:rotate(22deg)}}
@keyframes aScr{from{transform:rotate(-9deg)}to{transform:rotate(11deg)}}
@keyframes aShake{from{transform:rotate(-5deg)}to{transform:rotate(6deg)}}
@keyframes spin{to{transform:rotate(360deg)}}
@keyframes slump{to{transform:rotate(8deg)}}
@keyframes flyp{0%{transform:translate(0,0) rotate(-10deg) scale(1);opacity:0}10%{opacity:1}70%{transform:translate(250px,var(--dy,10px)) rotate(6deg) scale(.8);opacity:1}100%{transform:translate(330px,var(--dy2,26px)) rotate(14deg) scale(.1);opacity:0}}
@keyframes bar{0%,100%{transform:scaleY(.25)}50%{transform:scaleY(1)}}
@keyframes qup{0%{transform:translateY(0) scale(.5);opacity:0}20%{opacity:.9}100%{transform:translateY(-120px) scale(1.15);opacity:0}}
@keyframes rise{from{transform:translateY(90px)}to{transform:translateY(0)}}
@keyframes dfl{0%,100%{opacity:.5}50%{opacity:1}}
.on .pop,.on .bubp{animation:pop .5s cubic-bezier(.3,1.6,.5,1) var(--d,0s) both;transform-box:fill-box;transform-origin:center}
.on .fi{animation:afi .8s ease var(--d,0s) both}
.on .bub{animation:bubk 1.9s ease var(--d,0s) both;transform-box:fill-box;transform-origin:50% 100%}
.on .bubk{animation:pop .5s cubic-bezier(.3,1.6,.5,1) var(--d,0s) both;transform-box:fill-box;transform-origin:50% 100%}
.on .fall{animation:fallk var(--t,3.2s) cubic-bezier(.4,.1,.6,1) var(--d,0s) infinite both}
.on .mvx{animation:mvx var(--t,3s) ease-in-out var(--d,0s) both}
.on .mvxo{animation:mvxo var(--t,3s) linear var(--d,0s) both}
.on .mvlo{animation:mvxo var(--t,3s) linear var(--d,0s) infinite both}
.on .mvl{animation:mvx var(--t,6s) linear var(--d,0s) infinite both}
.on .turn{animation:turnA .01s linear var(--td,0s) both}
.on .wk .l1{animation:stepA .8s linear var(--wd,0s) infinite both}
.on .wk .l2{animation:stepB .8s linear var(--wd,0s) infinite both}
.on .slump{animation:slump 1.2s ease var(--d,2s) both}
.on .a-type{animation:aType .35s ease-in-out infinite alternate}
.on .a-type2{animation:aType .35s ease-in-out .17s infinite alternate}
.on .a-wave{animation:aWave .5s ease-in-out infinite alternate}
.on .a-scr{animation:aScr .22s ease-in-out infinite alternate}
.on .a-shake{animation:aShake .28s ease-in-out infinite alternate}
.on .spin{animation:spin 1.4s linear infinite}
.on .slow{animation:spin 16s linear infinite}
.on .fly{animation:flyp var(--t,2.8s) ease-in var(--d,0s) infinite both}
.on .bars rect{transform-box:fill-box;transform-origin:center;animation:bar .7s ease-in-out infinite}
.on .qm{animation:qup 3s ease-out var(--d,0s) infinite both}
.on .sun{animation:rise 5s ease-out both}
.on .dfl{animation:dfl 1.2s ease-in-out infinite}
@media (prefers-reduced-motion:reduce){*,*:before,*:after{animation:none!important;transition-duration:.01ms!important}}
@media (max-width:900px){.artbox{left:3%;width:94%;top:62px;max-width:none;max-height:none}.shade{background:rgba(14,15,19,.55)}}
`;
