'use strict';
/* Untangle Review client. Comments anchor to a version and a frame on the cached constant-rate grid;
   playback uses the source video, and pausing snaps back to the exact cached frame. */

const $ = (selector, root = document) => root.querySelector(selector);
const store = {
  get(key, fallback) { try { const v = localStorage.getItem(key); return v === null ? fallback : JSON.parse(v); } catch (e) { return fallback; } },
  set(key, value) { try { localStorage.setItem(key, JSON.stringify(value)); } catch (e) { /* storage is a convenience */ } },
};

function h(tag, props, ...children) {
  const el = document.createElement(tag);
  for (const [key, value] of Object.entries(props || {})) {
    if (value === null || value === undefined || value === false) continue;
    if (key === 'class') el.className = value;
    else if (key === 'style' && typeof value === 'object') Object.assign(el.style, value);
    else if (key.startsWith('on')) el.addEventListener(key.slice(2), value);
    else if (key === 'text') el.textContent = value;
    else el.setAttribute(key, value === true ? '' : value);
  }
  for (const child of children.flat()) {
    if (child === null || child === undefined || child === false) continue;
    el.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return el;
}

function put(el, ...children) {
  el.replaceChildren(...children.flat(Infinity).filter((c) => c !== null && c !== undefined && c !== false));
}

const api = {
  async get(path, etag) {
    const response = await fetch(path, { headers: etag ? { 'If-None-Match': etag } : {} });
    if (response.status === 304) return null;
    const body = await response.json();
    if (!response.ok) throw new Error(body.error || response.statusText);
    return { body, etag: response.headers.get('ETag') };
  },
  async post(path, body) {
    const response = await fetch(path, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || response.statusText);
    return data;
  },
};

function toast(message, kind) {
  const el = h('div', { class: `toast ${kind || ''}` }, message);
  $('#toasts').append(el);
  setTimeout(() => el.remove(), kind === 'error' ? 6000 : 3200);
}

const pad = (n, width = 2) => String(n).padStart(width, '0');
function timecode(frame, fps) {
  const whole = Math.floor(frame / fps);
  const rest = Math.round(frame - whole * fps);
  return `${pad(Math.floor(whole / 60))}:${pad(whole % 60)}:${pad(rest)}`;
}
function parseTime(text, fps) {
  const value = text.trim();
  if (/^\d+$/.test(value)) return Number(value);
  const parts = value.split(':').map(Number);
  if (parts.some(Number.isNaN)) return null;
  if (parts.length === 3) return Math.round((parts[0] * 60 + parts[1]) * fps + parts[2]);
  if (parts.length === 2) return Math.round((parts[0] * 60 + parts[1]) * fps);
  return null;
}
function ago(iso) {
  const seconds = (Date.now() - Date.parse(iso)) / 1000;
  if (!Number.isFinite(seconds)) return '';
  if (seconds < 60) return 'just now';
  if (seconds < 3600) return `${Math.floor(seconds / 60)} min ago`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)} h ago`;
  return new Date(iso).toLocaleDateString(undefined, { day: 'numeric', month: 'short' });
}
const frameUrl = (name, version, frame) => `/api/reviews/${encodeURIComponent(name)}/frames/${encodeURIComponent(version)}/${frame}.jpg`;

/* Images retry while the server is still extracting (it answers 202). */
function loadFrame(img, url, onReady) {
  img.dataset.want = url;
  img.onload = () => { if (img.dataset.want === url && onReady) onReady(true); };
  img.onerror = () => {
    if (img.dataset.want !== url) return;
    if (onReady) onReady(false);
    setTimeout(() => { if (img.dataset.want === url) img.src = `${url}?retry=${Date.now()}`; }, 900);
  };
  if (img.getAttribute('src') !== url) img.src = url;
}

/* ---------------- theme + help ---------------- */
$('#themeBtn').addEventListener('click', () => {
  const dark = document.documentElement.dataset.theme
    ? document.documentElement.dataset.theme === 'dark'
    : matchMedia('(prefers-color-scheme: dark)').matches;
  const next = dark ? 'light' : 'dark';
  document.documentElement.dataset.theme = next;
  try { localStorage.setItem('ur-theme', next); } catch (e) { /* ignore */ }
});
$('#helpBtn').addEventListener('click', () => $('#help').showModal());

/* ---------------- home ---------------- */
async function home() {
  document.title = 'Reviews · Untangle';
  put($('#crumbs'), );
  put($('#barTools'), );
  const app = $('#app');
  app.className = '';
  let result;
  try { result = (await api.get('/api/reviews')).body; } catch (error) {
    put(app, h('div', { class: 'home' }, h('p', { class: 'notice error' }, error.message)));
    return;
  }
  const reviews = result.reviews;
  const cards = reviews.map((review) => {
    const latest = review.latest;
    const poster = h('img', { alt: '', loading: 'lazy' });
    if (latest) loadFrame(poster, frameUrl(review.name, latest.id, Math.floor(latest.frames * 0.35)));
    const counts = review.counts;
    return h('a', { class: 'card', href: `/r/${review.name}` },
      h('div', { class: 'poster' }, latest ? poster : h('span', { class: 'muted' }, 'No versions yet'),
        latest && h('span', { class: 'frame-tag tag' }, latest.label)),
      h('div', { class: 'body' },
        h('h2', {}, review.title),
        h('div', { class: 'meta' },
          counts.open ? h('span', { class: 'pill open' }, `${counts.open} open`) : null,
          counts.addressed ? h('span', { class: 'pill addressed' }, `${counts.addressed} addressed`) : null,
          !counts.open && !counts.addressed ? h('span', { class: 'pill' }, counts.resolved ? 'All resolved' : 'No comments') : null,
          h('span', {}, `${review.versions.length} version${review.versions.length === 1 ? '' : 's'} · ${ago(review.updated)}`))));
  });
  put(app, h('div', { class: 'home' },
    h('span', { class: 'eyebrow' }, 'Frame review'),
    h('h1', {}, 'Reviews'),
    h('p', { class: 'lede' }, 'Pick a video, step to the exact frame, and leave a note. Agents read every comment, reply in the thread, and send the next version back here.'),
    reviews.length ? h('div', { class: 'cards' }, cards) : h('div', { class: 'empty' },
      h('h2', {}, 'No reviews yet'),
      h('p', { class: 'muted' }, 'Add a render, a Google Drive link or a video URL. Agents can do the same through the untangle-review MCP server.'),
      h('pre', {}, 'untangle-review add my-video https://drive.google.com/file/d/…/view --create --label v1'),
      h('p', { class: 'muted' }, `Reviews live in ${result.root}.`))));
}

/* ---------------- review page ---------------- */
const MODES = [['single', 'Single'], ['side', 'Side by side'], ['wipe', 'Wipe'], ['diff', 'Difference']];
let S = null;

function versionOf(id) { return S.data.versions.find((v) => v.id === id); }
function sourceTime(version, seconds) {
  for (const seg of version.edl || []) if (seg.start <= seconds && seconds < seg.end) return seg.source_start + seconds - seg.start;
  return null;
}
function outputTime(version, source) {
  for (const seg of version.edl || []) if (seg.source_start <= source && source < seg.source_end) return seg.start + source - seg.source_start;
  return null;
}
function mapFrame(fromId, frame, toId) {
  const from = versionOf(fromId); const to = versionOf(toId);
  let seconds = frame / from.fps;
  const raw = sourceTime(from, seconds);
  if (raw !== null && to.edl) { const mapped = outputTime(to, raw); if (mapped !== null) seconds = mapped; }
  return Math.max(0, Math.min(to.frames - 1, Math.round(seconds * to.fps)));
}
function captionAt(version, frame) {
  const t = frame / version.fps;
  const seg = (version.captions || []).find((c) => c.start <= t && t <= c.end);
  return seg ? seg.text : '';
}
const head = () => versionOf(S.head);
const base = () => (S.base ? versionOf(S.base) : null);

async function reviewPage(name) {
  const params = new URLSearchParams(location.search);
  S = {
    name, data: null, etag: null, head: null, base: null, frame: 0, mode: store.get('ur-mode', 'single'), wipe: 50,
    region: null, active: null, filter: null, playing: false, muted: store.get('ur-muted', true), seen: new Set(),
    pendingThreads: false, boxes: {}, stripKey: '', urlTimer: null, videoFailed: {},
  };
  let first;
  try { first = await api.get(`/api/reviews/${encodeURIComponent(name)}`); } catch (error) {
    put($('#app'), h('div', { class: 'home' }, h('p', { class: 'notice error' }, error.message), h('a', { href: '/', class: 'btn' }, 'All reviews')));
    return;
  }
  S.data = first.body; S.etag = first.etag;
  S.data.comments.forEach((c) => c.thread.forEach((m) => S.seen.add(`${c.id}:${m.at}:${m.text}`)));
  const versions = S.data.versions;
  if (!versions.length) {
    put($('#app'), h('div', { class: 'home' }, h('div', { class: 'empty' }, h('h2', {}, `${S.data.title} has no versions yet`),
      h('pre', {}, `untangle-review add ${name} <file | Drive link | URL> --label v1`))));
    return;
  }
  const linked = params.get('c') && S.data.comments.find((c) => c.id === params.get('c'));
  S.head = (linked && linked.version) || (versionOf(params.get('v')) ? params.get('v') : versions[versions.length - 1].id);
  const index = versions.findIndex((v) => v.id === S.head);
  S.base = index > 0 ? versions[index - 1].id : null;
  if (!S.base && S.mode !== 'single') S.mode = 'single';
  S.frame = Math.min(head().frames - 1, Math.max(0, Number(linked ? linked.frame : params.get('f') || 0)));
  if (linked) S.active = linked.id;
  const unresolved = S.data.comments.filter((c) => c.status !== 'resolved').length;
  S.filter = unresolved ? 'unresolved' : 'all';
  document.title = `${S.data.title} · Review`;
  buildPage();
  setFrame(S.frame, { force: true });
  if (linked) requestAnimationFrame(() => scrollThread(linked.id));
  poll();
}

function buildPage() {
  put($('#crumbs'), h('a', { href: '/' }, 'Reviews'), h('span', { 'aria-hidden': 'true' }, '/'), h('strong', {}, S.data.title));
  const handoff = h('button', { class: 'btn small', type: 'button', title: 'Copy a prompt that tells an agent to work through the open comments',
    onclick: async () => {
      const prompt = `Work through the unresolved comments in Untangle review "${S.name}" using the untangle-review MCP tools: list_comments, get_frame with each comment_id, fix the edit, add_version for the new render, then mark_addressed each comment with that version.`;
      try { await navigator.clipboard.writeText(prompt); toast('Agent prompt copied. Paste it into your agent thread.'); } catch (e) { toast(prompt); }
    } }, 'Hand off to agent');
  put($('#barTools'), h('span', { id: 'countPills', class: 'compare' }), handoff);

  const versionSelect = (id, value, includeNone) => h('select', { class: 'select', id, 'aria-label': id === 'headSel' ? 'Version' : 'Compare with',
    onchange: (event) => (id === 'headSel' ? switchHead(event.target.value) : switchBase(event.target.value || null)) },
    includeNone ? h('option', { value: '' }, 'No comparison') : null,
    S.data.versions.map((v) => h('option', { value: v.id, selected: v.id === value ? 'selected' : null }, v.label)));

  const workspace = h('section', { class: 'workspace', 'aria-label': 'Viewer' },
    h('div', { class: 'toolbar' },
      h('label', { class: 'compare' }, h('span', { class: 'field-label' }, 'Version'), versionSelect('headSel', S.head, false)),
      h('label', { class: 'compare' }, h('span', { class: 'field-label' }, 'Compare with'), versionSelect('baseSel', S.base, true)),
      h('a', { class: 'origin', id: 'originLink', target: '_blank', rel: 'noopener noreferrer', hidden: true }),
      h('span', { class: 'spacer' }),
      h('div', { class: 'segmented', id: 'modes', role: 'group', 'aria-label': 'View' },
        MODES.map(([key, label], i) => h('button', { type: 'button', 'data-mode': key, title: `${label} (${i + 1})`, onclick: () => setMode(key) }, label)))),
    h('div', { id: 'notices' }),
    h('div', { class: 'stage-area', id: 'stages' }),
    h('div', { class: 'transport' },
      h('button', { class: 'btn', id: 'playBtn', type: 'button', onclick: togglePlay, 'aria-label': 'Play' }, '▶'),
      h('button', { class: 'btn quiet', type: 'button', title: 'Back 10 frames (Shift+←)', onclick: () => step(-10) }, '−10'),
      h('button', { class: 'btn quiet', type: 'button', title: 'Previous frame (←)', 'aria-label': 'Previous frame', onclick: () => step(-1) }, '‹'),
      h('button', { class: 'btn quiet', type: 'button', title: 'Next frame (→)', 'aria-label': 'Next frame', onclick: () => step(1) }, '›'),
      h('button', { class: 'btn quiet', type: 'button', title: 'Forward 10 frames (Shift+→)', onclick: () => step(10) }, '+10'),
      h('button', { class: 'time', id: 'timeBtn', type: 'button', title: 'Go to a frame or timecode', onclick: editTime }),
      h('span', { class: 'count mono', id: 'countLabel' }),
      h('span', { class: 'spacer', style: { flex: 1 } }),
      h('button', { class: 'icon-btn', id: 'muteBtn', type: 'button', onclick: toggleMute })),
    h('div', { class: 'caption-line', id: 'caption' }),
    h('div', { class: 'timeline', id: 'timeline', 'aria-label': 'Timeline' },
      h('div', { class: 'marks', id: 'marks' }), h('div', { class: 'strip', id: 'strip' }), h('div', { class: 'playhead', id: 'playhead' })));

  const side = h('aside', { class: 'side', 'aria-label': 'Comments' },
    h('form', { class: 'composer', id: 'composer', onsubmit: (event) => { event.preventDefault(); sendComment(); } },
      h('div', { class: 'where', id: 'where' }),
      h('textarea', { id: 'commentText', placeholder: 'What should change on this frame?', 'aria-label': 'Comment',
        oninput: (event) => store.set(`ur-draft-${S.name}`, event.target.value) }),
      h('div', { class: 'row' }, h('span', { class: 'hint' }, 'Drag on the frame for a region · Ctrl+Enter'),
        h('button', { class: 'btn primary', type: 'submit', id: 'sendBtn' }, 'Comment'))),
    h('div', { class: 'filters', id: 'filters', role: 'group', 'aria-label': 'Filter comments' }),
    h('div', { class: 'threads', id: 'threads', onfocusout: () => setTimeout(() => { if (S.pendingThreads && !$('#threads').contains(document.activeElement)) renderThreads(); }, 0) }));

  $('#app').className = 'review';
  put($('#app'), workspace, side);
  $('#commentText').value = store.get(`ur-draft-${S.name}`, '');
  $('#commentText').addEventListener('keydown', (event) => {
    if (event.key === 'Enter' && (event.ctrlKey || event.metaKey)) { event.preventDefault(); sendComment(); }
  });
  bindTimeline();
  buildStages();
  renderChrome();
  renderThreads();
  new ResizeObserver(() => { fitBoxes(); renderStrip(); }).observe($('#stages'));
}

function switchHead(id, frame) {
  stopPlay();
  const target = frame === undefined ? mapFrame(S.head, S.frame, id) : frame;
  S.head = id;
  if (S.base === id) S.base = null;
  $('#headSel').value = id;
  $('#baseSel').value = S.base || '';
  if (!S.base && S.mode !== 'single') S.mode = 'single';
  S.region = null; S.stripKey = '';
  buildStages(); renderChrome(); renderThreads();
  setFrame(target, { force: true });
}
function switchBase(id) {
  S.base = id === S.head ? null : id;
  $('#baseSel').value = S.base || '';
  if (S.base && S.mode === 'single') S.mode = 'side';
  if (!S.base) S.mode = 'single';
  buildStages(); renderChrome(); setFrame(S.frame, { force: true });
}
function setMode(mode) {
  if (mode !== 'single' && !S.base) {
    const others = S.data.versions.filter((v) => v.id !== S.head);
    if (!others.length) { toast('Add a second version to compare.'); return; }
    S.base = others[others.length - 1].id; $('#baseSel').value = S.base;
  }
  S.mode = mode; store.set('ur-mode', mode);
  stopPlay(); buildStages(); renderChrome(); setFrame(S.frame, { force: true });
}

/* ---- stages */
function buildStages() {
  const area = $('#stages');
  S.boxes = {};
  const views = S.mode === 'side' && S.base ? [S.base, S.head] : [S.head];
  put(area, ...views.map((id) => {
    const version = versionOf(id);
    const isHead = id === S.head;
    const img = h('img', { alt: `${version.label} frame` });
    const box = h('div', { class: 'frame-box' }, img);
    const parts = { box, img, version: id, regions: h('div', { class: 'over', style: { pointerEvents: 'none' } }) };
    if (isHead && (S.mode === 'wipe' || S.mode === 'diff') && S.base) {
      parts.overImg = h('img', { alt: '' });
      const over = h('div', { class: `over ${S.mode === 'diff' ? 'diff' : ''}` }, parts.overImg);
      parts.over = over;
      box.append(over);
      if (S.mode === 'wipe') {
        parts.handle = h('div', { class: 'wipe-handle' });
        box.append(parts.handle);
        bindWipe(parts);
      }
    }
    if (isHead) {
      parts.video = h('video', { playsinline: true, preload: 'none', style: { display: 'none' } });
      parts.video.muted = S.muted;
      box.append(parts.video);
      bindRegions(parts);
    }
    box.append(parts.regions);
    parts.loading = h('div', { class: 'loading', hidden: true }, h('span', {}, 'Preparing frames…'));
    parts.tag = h('span', { class: 'frame-tag stage-tag' });
    const screen = h('div', { class: 'screen' }, box, parts.tag, parts.loading);
    parts.screen = screen;
    S.boxes[id] = parts;
    const label = S.mode === 'side'
      ? h('div', { class: 'label' }, h('span', { class: 'pill' }, isHead ? 'Reviewing' : 'Earlier'), version.label)
      : null;
    return h('div', { class: 'viewer' }, label, screen);
  }));
  fitBoxes();
}

function fitBoxes() {
  for (const parts of Object.values(S.boxes)) {
    const version = versionOf(parts.version);
    const width = parts.screen.clientWidth; const height = parts.screen.clientHeight;
    if (!width || !height) continue;
    const scale = Math.min(width / version.width, height / version.height);
    parts.box.style.width = `${Math.floor(version.width * scale)}px`;
    parts.box.style.height = `${Math.floor(version.height * scale)}px`;
  }
}

function bindWipe(parts) {
  const apply = () => {
    parts.over.style.clipPath = `inset(0 ${100 - S.wipe}% 0 0)`;
    parts.handle.style.left = `${S.wipe}%`;
  };
  parts.handle.addEventListener('pointerdown', (event) => {
    event.stopPropagation(); event.preventDefault();
    parts.handle.setPointerCapture(event.pointerId);
    const move = (e) => {
      const rect = parts.box.getBoundingClientRect();
      S.wipe = Math.max(0, Math.min(100, ((e.clientX - rect.left) / rect.width) * 100));
      apply();
    };
    parts.handle.addEventListener('pointermove', move);
    parts.handle.addEventListener('pointerup', () => parts.handle.removeEventListener('pointermove', move), { once: true });
  });
  apply();
}

function bindRegions(parts) {
  const box = parts.box;
  let start = null; let draft = null;
  const point = (event) => {
    const rect = box.getBoundingClientRect();
    return [Math.max(0, Math.min(1, (event.clientX - rect.left) / rect.width)), Math.max(0, Math.min(1, (event.clientY - rect.top) / rect.height))];
  };
  box.addEventListener('pointerdown', (event) => {
    if (event.button !== 0 || event.target.closest('.region:not(.draft)') || event.target.closest('.wipe-handle')) return;
    if (S.playing) stopPlay();
    start = point(event);
    box.setPointerCapture(event.pointerId);
    draft = h('div', { class: 'region draft' });
    parts.regions.append(draft);
  });
  box.addEventListener('pointermove', (event) => {
    if (!start) return;
    const [x, y] = point(event);
    Object.assign(draft.style, { left: `${Math.min(x, start[0]) * 100}%`, top: `${Math.min(y, start[1]) * 100}%`,
      width: `${Math.abs(x - start[0]) * 100}%`, height: `${Math.abs(y - start[1]) * 100}%` });
  });
  box.addEventListener('pointerup', (event) => {
    if (!start) return;
    const [x, y] = point(event);
    const region = [Math.min(x, start[0]), Math.min(y, start[1]), Math.abs(x - start[0]), Math.abs(y - start[1])];
    start = null; draft.remove();
    if (region[2] > 0.015 && region[3] > 0.015) {
      S.region = region.map((v) => Math.round(v * 10000) / 10000);
      renderOverlays(); renderWhere();
      $('#commentText').focus();
    }
  });
}

/* ---- frame navigation */
function setFrame(frame, options = {}) {
  const version = head();
  const next = Math.max(0, Math.min(version.frames - 1, Math.round(frame)));
  if (next === S.frame && !options.force) return;
  if (next !== S.frame && S.region && !options.keepRegion) S.region = null;
  S.frame = next;
  const status = S.data.frames[S.head] || {};
  for (const parts of Object.values(S.boxes)) {
    const id = parts.version;
    const index = id === S.head ? next : mapFrame(S.head, next, id);
    const ready = (S.data.frames[id] || {}).state === 'ready';
    parts.loading.hidden = ready;
    if (!ready) parts.loading.firstChild.textContent = loadingText(id);
    loadFrame(parts.img, frameUrl(S.name, id, index), (ok) => { if (ok) parts.loading.hidden = true; });
    if (parts.overImg) loadFrame(parts.overImg, frameUrl(S.name, S.base, mapFrame(S.head, next, S.base)));
    parts.tag.textContent = `${versionOf(id).label} · f${index} · ${timecode(index, versionOf(id).fps)}`;
  }
  if (status.state === 'ready') preload(next);
  renderPosition();
  renderOverlays();
  renderWhere();
  clearTimeout(S.urlTimer);
  S.urlTimer = setTimeout(() => {
    const url = new URL(location.href);
    url.searchParams.set('v', S.head); url.searchParams.set('f', String(S.frame)); url.searchParams.delete('c');
    history.replaceState(null, '', url);
  }, 250);
}
function loadingText(id) {
  const status = S.data.frames[id] || {};
  if (status.state === 'downloading') return 'Downloading from Drive…';
  if (status.state === 'extracting') return `Extracting frames ${status.done} / ${status.total}`;
  if (status.state === 'missing-source') return 'The video file is not on this computer.';
  if (status.state === 'error') return 'Frames could not be prepared. See the notice above.';
  return 'Preparing frames…';
}
function preload(frame) {
  for (const delta of [1, 2, 3, -1]) {
    const n = frame + delta;
    if (n >= 0 && n < head().frames) { const img = new Image(); img.src = frameUrl(S.name, S.head, n); }
  }
}
function step(delta) { if (S.playing) stopPlay(); setFrame(S.frame + delta); }

function renderPosition() {
  const version = head();
  $('#timeBtn').textContent = timecode(S.frame, version.fps);
  $('#countLabel').textContent = `frame ${S.frame} / ${version.frames - 1} · ${version.fps.toFixed(version.fps % 1 ? 2 : 0)} fps`;
  $('#playhead').style.left = `${(S.frame / Math.max(1, version.frames - 1)) * 100}%`;
  const caption = captionAt(version, S.frame);
  put($('#caption'), caption ? h('q', {}, caption) : '');
  if (!S.playing) {
    const near = S.data.comments.find((c) => c.version === S.head && c.frame === S.frame);
    document.querySelectorAll('.mark').forEach((m) => m.classList.toggle('active', near && m.dataset.id === near.id));
  }
}

function renderOverlays() {
  const parts = S.boxes[S.head];
  if (!parts) return;
  const visible = S.playing ? [] : S.data.comments.filter((c) => c.version === S.head && c.region && Math.abs(c.frame - S.frame) <= 2);
  put(parts.regions, 
    ...visible.map((c) => h('div', {
      class: `region ${c.frame !== S.frame ? 'dim' : ''}`, title: c.thread[0].text,
      style: { left: `${c.region[0] * 100}%`, top: `${c.region[1] * 100}%`, width: `${c.region[2] * 100}%`, height: `${c.region[3] * 100}%` },
      onpointerdown: (event) => event.stopPropagation(),
      onclick: () => activate(c.id, { seek: false }),
    }, h('span', { class: `badge num ${c.status}` }, c.number))),
    S.region ? h('div', { class: 'region draft', style: { left: `${S.region[0] * 100}%`, top: `${S.region[1] * 100}%`, width: `${S.region[2] * 100}%`, height: `${S.region[3] * 100}%` } }) : null);
}

function renderWhere() {
  const version = head();
  put($('#where'), 
    'Comment on ', h('strong', {}, version.label), ' at ', h('strong', { class: 'mono' }, timecode(S.frame, version.fps)),
    h('span', { class: 'mono' }, `· f${S.frame}`),
    S.region ? h('span', { class: 'chip' }, 'Region', h('button', { type: 'button', 'aria-label': 'Remove region', title: 'Remove region (Esc)',
      onclick: () => { S.region = null; renderOverlays(); renderWhere(); } }, '×')) : null);
}

function editTime() {
  const button = $('#timeBtn');
  const input = h('input', { class: 'time mono', value: timecode(S.frame, head().fps), 'aria-label': 'Frame or timecode (mm:ss:ff)' });
  let finished = false;
  const done = (commit) => {
    if (finished) return;
    finished = true;
    const value = input.value;
    input.replaceWith(button);
    if (commit) {
      const frame = parseTime(value, head().fps);
      if (frame === null) toast('Type a frame number or mm:ss:ff.', 'error'); else setFrame(frame);
    }
  };
  input.addEventListener('keydown', (event) => {
    if (event.key === 'Enter') { event.preventDefault(); done(true); }
    if (event.key === 'Escape') { event.preventDefault(); done(false); }
  });
  input.addEventListener('blur', () => { if (input.isConnected) done(false); });
  button.replaceWith(input);
  input.select();
}

/* ---- playback: the real video for motion and sound, cached frames when paused */
function togglePlay() { if (S.playing) stopPlay(); else startPlay(); }
function startPlay() {
  const parts = S.boxes[S.head];
  const version = head();
  const status = S.data.frames[S.head] || {};
  if (!parts) return;
  if (S.frame >= version.frames - 1) setFrame(0);
  S.playing = true;
  $('#playBtn').textContent = '❚❚'; $('#playBtn').setAttribute('aria-label', 'Pause');
  renderOverlays();
  if (status.playable && !S.videoFailed[S.head]) {
    const video = parts.video;
    const source = `/api/reviews/${encodeURIComponent(S.name)}/media/${encodeURIComponent(S.head)}`;
    if (video.dataset.src !== source) { video.src = source; video.dataset.src = source; }
    video.muted = S.muted;
    video.currentTime = (S.frame + 0.5) / version.fps;
    video.onerror = () => { S.videoFailed[S.head] = true; if (S.playing) { stopPlay(); startPlay(); } };
    video.onended = () => stopPlay();
    const tick = (now, meta) => {
      if (!S.playing) return;
      const frame = Math.min(version.frames - 1, Math.round(meta.mediaTime * version.fps));
      S.frame = frame; renderPosition();
      video.requestVideoFrameCallback(tick);
    };
    video.play().then(() => {
      if (!S.playing) return;
      video.style.display = 'block'; parts.img.style.visibility = 'hidden';
      if (video.requestVideoFrameCallback) video.requestVideoFrameCallback(tick);
      else (function poll() { if (!S.playing) return; S.frame = Math.min(version.frames - 1, Math.round(video.currentTime * version.fps)); renderPosition(); requestAnimationFrame(poll); }());
    }).catch(() => { S.videoFailed[S.head] = true; stopPlay(); startPlay(); });
    return;
  }
  // Fallback: step through cached frames at the source rate, silently.
  const started = performance.now(); const from = S.frame;
  const loop = (now) => {
    if (!S.playing) return;
    const frame = from + Math.floor(((now - started) / 1000) * version.fps);
    if (frame >= version.frames) { stopPlay(); return; }
    if (frame !== S.frame) setFrame(frame);
    requestAnimationFrame(loop);
  };
  requestAnimationFrame(loop);
}
function stopPlay() {
  if (!S || !S.playing) return;
  S.playing = false;
  $('#playBtn').textContent = '▶'; $('#playBtn').setAttribute('aria-label', 'Play');
  const parts = S.boxes[S.head];
  if (parts && parts.video && !parts.video.paused) {
    parts.video.pause();
    S.frame = Math.min(head().frames - 1, Math.round(parts.video.currentTime * head().fps - 0.5));
  }
  if (parts && parts.video) { parts.video.style.display = 'none'; parts.img.style.visibility = ''; }
  setFrame(S.frame, { force: true });
}
function toggleMute() {
  S.muted = !S.muted; store.set('ur-muted', S.muted);
  const parts = S.boxes[S.head];
  if (parts && parts.video) parts.video.muted = S.muted;
  renderChrome();
  toast(S.muted ? 'Sound off' : 'Sound on during playback');
}

/* ---- timeline */
function bindTimeline() {
  const timeline = $('#timeline');
  let dragging = false; let card = null;
  const frameAt = (event) => {
    const rect = $('#strip').getBoundingClientRect();
    return Math.round(Math.max(0, Math.min(1, (event.clientX - rect.left) / rect.width)) * (head().frames - 1));
  };
  timeline.addEventListener('pointerdown', (event) => {
    if (event.target.closest('.mark')) return;
    if (S.playing) stopPlay();
    dragging = true; timeline.setPointerCapture(event.pointerId); setFrame(frameAt(event));
  });
  timeline.addEventListener('pointermove', (event) => {
    if (dragging) { setFrame(frameAt(event)); return; }
    const frame = frameAt(event);
    const rect = timeline.getBoundingClientRect();
    if (!card) { card = h('div', { class: 'hover-card' }, h('img', { alt: '' }), h('span')); timeline.append(card); }
    card.style.left = `${Math.max(80, Math.min(rect.width - 80, event.clientX - rect.left))}px`;
    if ((S.data.frames[S.head] || {}).state === 'ready') loadFrame(card.firstChild, frameUrl(S.name, S.head, frame));
    card.lastChild.textContent = `${timecode(frame, head().fps)} · f${frame}`;
  });
  timeline.addEventListener('pointerup', () => { dragging = false; });
  timeline.addEventListener('pointerleave', () => { if (card) { card.remove(); card = null; } });
}
function renderStrip() {
  const strip = $('#strip');
  if (!strip) return;
  const version = head();
  const width = strip.clientWidth || 600;
  const count = Math.max(4, Math.min(48, Math.floor(width / Math.max(24, 52 * (version.width / version.height)))));
  const ready = (S.data.frames[S.head] || {}).state === 'ready';
  const key = `${S.head}:${count}:${ready}`;
  if (key === S.stripKey) return;
  S.stripKey = key;
  put(strip, ...Array.from({ length: count }, (_, i) => {
    const img = h('img', { alt: '', loading: 'lazy' });
    if (ready) img.src = frameUrl(S.name, S.head, Math.floor(((i + 0.5) / count) * (version.frames - 1)));
    return img;
  }));
}
function renderMarks() {
  const version = head();
  put($('#marks'), ...S.data.comments.filter((c) => c.version === S.head).map((c) => h('button', {
    class: `mark ${c.status}`, type: 'button', 'data-id': c.id, 'aria-label': `Comment ${c.number}, ${c.status}, ${timecode(c.frame, version.fps)}`,
    title: `#${c.number} · ${c.status} · ${c.thread[0].text}`, style: { left: `${(c.frame / Math.max(1, version.frames - 1)) * 100}%` },
    onclick: () => activate(c.id),
  })));
}

/* ---- chrome + notices */
function renderChrome() {
  document.querySelectorAll('#modes button').forEach((b) => b.setAttribute('aria-pressed', String(b.dataset.mode === S.mode)));
  const counts = { open: 0, addressed: 0, resolved: 0 };
  S.data.comments.forEach((c) => { counts[c.status] += 1; });
  put($('#countPills'), 
    h('span', { class: 'pill open' }, `${counts.open} open`),
    counts.addressed ? h('span', { class: 'pill addressed' }, `${counts.addressed} addressed`) : null);
  const origin = head().origin;
  const link = $('#originLink');
  if (origin && /^https:\/\//.test(origin.url || '')) {
    link.hidden = false; link.href = origin.url;
    link.textContent = origin.kind === 'drive' ? 'Open in Drive ↗' : 'Source ↗';
  } else link.hidden = true;
  $('#muteBtn').textContent = S.muted ? '🔇' : '🔊';
  $('#muteBtn').setAttribute('aria-label', S.muted ? 'Sound off. Turn on (M)' : 'Sound on. Turn off (M)');
  $('#muteBtn').title = S.muted ? 'Sound off (M)' : 'Sound on (M)';
  const notices = [];
  for (const id of [S.head, S.base].filter(Boolean)) {
    const status = S.data.frames[id] || {}; const version = versionOf(id);
    if (status.state === 'error') notices.push(h('p', { class: 'notice error' }, `${version.label}: ${status.error}`));
    if (status.state === 'missing-source') notices.push(h('p', { class: 'notice warn' }, `${version.label}: the video is not on this computer and has no link to fetch it from.`));
    if (status.stale) notices.push(h('p', { class: 'notice warn' }, `${version.label}: the file changed after it was added. Add it again as a new version so comments keep pointing at the right frames.`));
    if (version.variable_rate) notices.push(h('p', { class: 'notice warn' }, `${version.label} has a variable frame rate. Frames follow a ${version.fps.toFixed(2)} fps grid and playback may differ by a frame.`));
  }
  put($('#notices'), ...notices);
  renderMarks();
  renderPosition();
}

/* ---- comments */
function scrollThread(id) {
  const el = document.querySelector(`.thread[data-id="${id}"]`);
  if (el) el.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
}
function activate(id, options = {}) {
  const comment = S.data.comments.find((c) => c.id === id);
  if (!comment) return;
  S.active = id;
  if (S.filter !== 'all' && !matches(comment)) S.filter = 'all';
  if (options.seek !== false) {
    if (comment.version !== S.head) switchHead(comment.version, comment.frame); else { stopPlay(); setFrame(comment.frame, { force: true }); }
  }
  renderThreads();
  scrollThread(id);
}
function matches(comment) {
  if (S.filter === 'all') return true;
  if (S.filter === 'unresolved') return comment.status !== 'resolved';
  return comment.status === S.filter;
}
async function sendComment() {
  const text = $('#commentText').value.trim();
  if (!text) { $('#commentText').focus(); toast('Write a note first.'); return; }
  $('#sendBtn').disabled = true;
  try {
    const comment = await api.post(`/api/reviews/${encodeURIComponent(S.name)}/comments`, { version: S.head, frame: S.frame, text, region: S.region });
    S.data.comments.push(comment);
    comment.thread.forEach((m) => S.seen.add(`${comment.id}:${m.at}:${m.text}`));
    $('#commentText').value = ''; store.set(`ur-draft-${S.name}`, '');
    S.region = null; S.active = comment.id;
    if (!matches(comment)) S.filter = 'unresolved';
    renderChrome(); renderOverlays(); renderWhere(); renderThreads(); scrollThread(comment.id);
    toast(`Comment #${comment.number} saved. Agents can read it now.`);
  } catch (error) { toast(error.message, 'error'); } finally { $('#sendBtn').disabled = false; }
}
async function act(comment, path, body, message) {
  try {
    const updated = await api.post(`/api/reviews/${encodeURIComponent(S.name)}/comments/${comment.id}/${path}`, body);
    Object.assign(comment, updated);
    updated.thread.forEach((m) => S.seen.add(`${comment.id}:${m.at}:${m.text}`));
    renderChrome(); renderOverlays(); renderThreads();
    if (message) toast(message);
  } catch (error) { toast(error.message, 'error'); }
}

function renderThreads() {
  const container = $('#threads');
  if (!container) return;
  if (container.contains(document.activeElement)) { S.pendingThreads = true; return; }
  S.pendingThreads = false;
  const counts = { unresolved: 0, open: 0, addressed: 0, resolved: 0, all: S.data.comments.length };
  S.data.comments.forEach((c) => { counts[c.status] += 1; if (c.status !== 'resolved') counts.unresolved += 1; });
  put($('#filters'), ...[['unresolved', 'Unresolved'], ['resolved', 'Resolved'], ['all', 'All']]
    .map(([key, label]) => h('button', { type: 'button', 'aria-pressed': String(S.filter === key), onclick: () => { S.filter = key; renderThreads(); } }, `${label} ${counts[key]}`)));
  const shown = S.data.comments.filter(matches).sort((a, b) => (a.version === b.version ? a.frame - b.frame : a.version === S.head ? -1 : 1));
  if (!shown.length) {
    put(container, h('div', { class: 'side-empty' }, S.data.comments.length
      ? [h('b', {}, 'Nothing here'), 'Try another filter.']
      : [h('b', {}, 'No comments yet'), 'Step to a frame, drag over what needs work, and write a note. Agents pick it up from here.']));
    return;
  }
  put(container, ...shown.map(threadCard));
}

function threadCard(comment) {
  const version = versionOf(comment.version);
  const latest = S.data.versions[S.data.versions.length - 1];
  const fresh = comment.thread.some((m) => !S.seen.has(`${comment.id}:${m.at}:${m.text}`));
  comment.thread.forEach((m) => S.seen.add(`${comment.id}:${m.at}:${m.text}`));
  let replyBox = null;
  const card = h('article', { class: `thread ${S.active === comment.id ? 'active' : ''} ${fresh ? 'fresh' : ''}`, 'data-id': comment.id },
    h('div', { class: 'head' },
      h('span', { class: `badge ${comment.status}` }, comment.number),
      h('button', { class: 'jump', type: 'button', title: 'Go to this frame', onclick: () => activate(comment.id) }, timecode(comment.frame, version.fps)),
      comment.version !== S.head ? h('span', { class: 'pill' }, version.label) : null,
      comment.region ? h('span', { class: 'muted', title: 'Marks a region', 'aria-label': 'Marks a region' }, '▭') : null,
      h('span', { class: `pill ${comment.status}` }, comment.status)),
    comment.caption ? h('div', { class: 'event' }, `“${comment.caption}”`) : null,
    comment.thread.map((m) => (m.event
      ? h('div', { class: 'event' }, `${m.author} ${m.text} · ${ago(m.at)}`)
      : h('div', { class: `msg ${m.role === 'agent' ? 'agent' : ''}` },
        h('div', { class: 'who' }, h('b', {}, m.author), m.role === 'agent' ? h('span', { class: 'pill agent' }, 'Agent') : null, h('span', {}, ago(m.at))),
        h('div', { class: 'text' }, m.text)))));
  if (comment.status === 'addressed' && comment.addressed_in) {
    const target = versionOf(comment.addressed_in);
    if (target && comment.addressed_in !== S.head) {
      card.append(h('div', { class: 'callout' }, `Addressed in ${target.label}`,
        h('button', { class: 'btn small primary', type: 'button', onclick: () => {
          const frame = mapFrame(comment.version, comment.frame, target.id);
          S.base = comment.version !== target.id ? comment.version : S.base;
          if (S.base) S.mode = 'side';
          switchHead(target.id, frame);
          S.active = comment.id; renderThreads();
        } }, `Check in ${target.label}`)));
    } else if (target) {
      card.append(h('div', { class: 'callout' }, 'Addressed in this version. Check the frame, then resolve or reopen.'));
    }
  } else if (comment.status === 'open' && latest.id !== comment.version && S.head === comment.version) {
    card.append(h('div', { class: 'event' }, `A newer version (${latest.label}) exists.`));
  }
  const actions = h('div', { class: 'actions' },
    h('button', { class: 'btn small quiet', type: 'button', onclick: () => {
      if (replyBox) { replyBox.remove(); replyBox = null; return; }
      const area = h('textarea', { 'aria-label': 'Reply', placeholder: 'Reply…' });
      const send = async () => { if (area.value.trim()) { const text = area.value; area.blur(); await act(comment, 'replies', { text }, 'Reply sent'); } };
      area.addEventListener('keydown', (event) => {
        if (event.key === 'Enter' && (event.ctrlKey || event.metaKey)) { event.preventDefault(); send(); }
        if (event.key === 'Escape') { event.preventDefault(); area.blur(); replyBox.remove(); replyBox = null; }
      });
      replyBox = h('div', { class: 'reply' }, area, h('div', { class: 'actions' }, h('button', { class: 'btn small primary', type: 'button', onclick: send }, 'Reply')));
      card.append(replyBox); area.focus();
    } }, 'Reply'),
    h('span', { style: { flex: 1 } }),
    comment.status === 'resolved'
      ? h('button', { class: 'btn small', type: 'button', onclick: () => act(comment, 'status', { status: 'open' }, `#${comment.number} reopened`) }, 'Reopen')
      : [comment.status === 'addressed' ? h('button', { class: 'btn small quiet', type: 'button', onclick: () => act(comment, 'status', { status: 'open' }, `#${comment.number} reopened`) }, 'Reopen') : null,
        h('button', { class: 'btn small', type: 'button', onclick: () => act(comment, 'status', { status: 'resolved' }, `#${comment.number} resolved`) }, 'Resolve')]);
  card.append(actions);
  return card;
}

/* ---- live updates */
async function poll() {
  if (!S) return;
  const name = S.name;
  try {
    const result = await api.get(`/api/reviews/${encodeURIComponent(name)}`, S.etag);
    if (S && S.name === name && result) {
      const before = new Set(S.data.versions.map((v) => v.id));
      const wasReady = JSON.stringify(Object.fromEntries(Object.entries(S.data.frames).map(([k, v]) => [k, v.state])));
      const incoming = [];
      result.body.comments.forEach((c) => c.thread.forEach((m) => {
        if (!S.seen.has(`${c.id}:${m.at}:${m.text}`) && m.role === 'agent') incoming.push([c, m]);
      }));
      S.data = result.body; S.etag = result.etag;
      const added = S.data.versions.filter((v) => !before.has(v.id));
      if (added.length) {
        const select = (id, none) => { const el = $(id); put(el, ...(none ? [h('option', { value: '' }, 'No comparison')] : []), ...S.data.versions.map((v) => h('option', { value: v.id }, v.label))); };
        select('#headSel'); select('#baseSel', true); $('#headSel').value = S.head; $('#baseSel').value = S.base || '';
        toast(`New version ${added[added.length - 1].label} is ready to review.`);
      }
      const nowReady = JSON.stringify(Object.fromEntries(Object.entries(S.data.frames).map(([k, v]) => [k, v.state])));
      for (const [c, m] of incoming.slice(0, 3)) toast(m.event ? `${m.author} ${m.text} on #${c.number}` : `${m.author} replied on #${c.number}`);
      renderChrome(); renderThreads();
      if (!S.playing) { if (nowReady !== wasReady) { S.stripKey = ''; renderStrip(); } setFrame(S.frame, { force: true, keepRegion: true }); }
    }
  } catch (error) { /* The server may be restarting; keep polling quietly. */ }
  setTimeout(poll, document.hidden ? 5000 : 1500);
}

/* ---- keyboard */
document.addEventListener('keydown', (event) => {
  if (!S || !$('#composer')) return;
  const typing = event.target.closest('input, textarea, select, [contenteditable]');
  if (event.key === 'Escape') {
    if (typing) { event.target.blur(); return; }
    if (S.region) { S.region = null; renderOverlays(); renderWhere(); }
    return;
  }
  if (typing || event.ctrlKey || event.metaKey || event.altKey || $('#help').open) return;
  const key = event.key;
  if (key === 'ArrowLeft' || key === 'ArrowRight') { event.preventDefault(); step((key === 'ArrowLeft' ? -1 : 1) * (event.shiftKey ? 10 : 1)); }
  else if (key === ' ') { event.preventDefault(); togglePlay(); }
  else if (key === 'c' || key === 'C') { event.preventDefault(); stopPlay(); $('#commentText').focus(); }
  else if (key === 'm' || key === 'M') toggleMute();
  else if (key === '?') $('#help').showModal();
  else if (['1', '2', '3', '4'].includes(key)) setMode(MODES[Number(key) - 1][0]);
  else if (key === '[' || key === ']') {
    const list = S.data.comments.filter((c) => c.version === S.head && matches(c)).sort((a, b) => a.frame - b.frame);
    if (!list.length) return;
    const target = key === ']' ? list.find((c) => c.frame > S.frame) || list[0] : [...list].reverse().find((c) => c.frame < S.frame) || list[list.length - 1];
    activate(target.id);
  }
});

/* ---- route */
(function route() {
  const match = location.pathname.match(/^\/r\/([a-z0-9][a-z0-9-]{0,63})\/?$/);
  if (match) reviewPage(match[1]); else home();
}());
