// ── State ──────────────────────────────────────────────────────────────────────
let catalog = [];
let selection = null;
let manifest = null;
let songImages = {};   // {number: path} — songs backed by a picture asset
let buildStatus = {};   // last Mac-build status (channel А, /api/build-status)

// progItems: {time, title, note, is_practice_end, _source:'telegram'|'override'|'manual', _dirty, _llm_uncertain}
let progItems = [];
let practiceEnd = null;   // "HH:MM" of the boundary item (overrides.practice_end), separate from program

// newsAuto: items from manifest.news (overridable as a batch)
// newsAutoOverridden: true when overrides.news was non-null at load time
// newsManual: items from overrides.news_manual
let newsAuto = [];
let newsAutoOverridden = false;
let newsManual = [];
// featuredNews: manual-only accent block (overrides.featured_news), separate from news
let featuredNews = [];
let songSource = 'fallback';   // 'manual' | 'auto' | 'fallback' — set by resolveSongs()

let saveTimer = null;
let dragSrc = null;
let dragKind = null;
const SAVE_DELAY = 1200;

// ── Init ───────────────────────────────────────────────────────────────────────
async function init() {
  setSave('idle', '☁ авто-сохранение');
  try {
    let serverThemeData;
    [catalog, selection, songImages, buildStatus, serverThemeData] = await Promise.all([
      fetch('/api/catalog').then(r => r.json()).catch(() => []),
      fetch('/api/selection').then(r => r.json()).catch(() => null),
      fetch('/api/song-images').then(r => r.json()).catch(() => ({})),
      fetch('/api/build-status').then(r => r.json()).catch(() => ({})),
      fetch('/api/theme-key').then(r => r.json()).catch(() => ({theme: 'warm'})),
    ]);
    const serverTheme = (serverThemeData && VALID_THEMES.includes(serverThemeData.theme))
      ? serverThemeData.theme : 'warm';
    _confirmedTheme = serverTheme;
    applyTheme(serverTheme); // server is authoritative
  } catch { setSave('error', '✗ нет связи'); }

  try {
    manifest = await fetch('/manifest.json').then(r => r.json());
    document.getElementById('week-label').textContent =
      manifest.date ? formatMeetingDate(manifest.date) : 'Дата не задана';
    document.getElementById('dada-auto-val').textContent =
      manifest.dada_comment || '(нет)';
  } catch {
    manifest = null;
    document.getElementById('week-label').textContent = 'manifest недоступен';
  }

  loadForm();
}

function loadForm() {
  const sel = selection || {};
  const ov  = sel.overrides || {};

  // Твоя часть
  document.getElementById('video-url').value = sel.video_url || '';
  document.getElementById('final-video-url').value = sel.final_video_url || '';
  document.getElementById('bg-music-url').value = sel.bg_music_url || '';
  renderAutoVideo();
  document.getElementById('raised').value   = sel.raised ?? '';
  document.getElementById('plan').value     = sel.plan ?? '';
  renderAutoMoney();
  document.getElementById('song-cards').innerHTML = '';
  const rs = resolveSongs();                 // mirrors deck/merge.js priority
  rs.numbers.forEach(renderSongCard);
  songSource = rs.source;                    // 'manual' | 'auto' | 'fallback'
  renderBuildStatus();     // channel А: last-build status line
  renderSongSource();      // where the current numbers come from
  renderTopAlert();        // channel А: chat songs not in base
  updateAutoStatus();      // summary badge in automatic section head

  // Дада
  document.getElementById('ov-dada').value = ov.dada_comment ?? '';

  // Уроки медитации: чекбокс всегда отражает сохранённое значение (чтобы save не
  // затирал hide=true, когда слайд временно отсутствует), а строка видна только
  // когда manifest реально испёк слайд.
  document.getElementById('hide-urokimeditacii').checked = !!ov.hide_urokimeditacii;
  document.getElementById('um-toggle-row').style.display =
    manifest?.urokimeditacii ? '' : 'none';

  // Программа
  if (ov.program) {
    progItems = ov.program.map(p => ({
      ...p, _source: 'override', _dirty: false, _llm_uncertain: p._llm_uncertain ?? false,
    }));
  } else {
    progItems = sortProgByTime((manifest?.program || []).map(p => ({
      ...p, _source: 'telegram', _dirty: false, _llm_uncertain: p._llm_uncertain ?? false,
    })));
  }
  // boundary marker: separate field practice_end ("HH:MM"), overlaid onto progItems for the radio UI
  practiceEnd = ov.practice_end ?? null;
  progItems.forEach(p => { p.is_practice_end = !!practiceEnd && p.time === practiceEnd; });

  // Новости
  if (ov.news) {
    newsAuto = ov.news.map(t => ({ text: t, _dirty: false }));
    newsAutoOverridden = true;
  } else {
    newsAuto = (manifest?.news || []).map(t => ({ text: t, _dirty: false }));
    newsAutoOverridden = false;
  }
  newsManual = (ov.news_manual || []).map(t => ({ text: t }));
  featuredNews = (ov.featured_news || []).map(t => ({ text: t }));

  renderProgram();
  renderNews();
  renderFeatured();
  updateAutoMeta();
}

// ── Program helpers ────────────────────────────────────────────────────────────
function timeToMin(t) {
  const m = (t || '').match(/^(\d{1,2}):(\d{2})$/);
  return m ? parseInt(m[1], 10) * 60 + parseInt(m[2], 10) : Infinity;
}
function sortProgByTime(items) {
  return [...items].sort((a, b) => timeToMin(a.time) - timeToMin(b.time));
}

// ── Program editor ─────────────────────────────────────────────────────────────
function renderProgram() {
  const list = document.getElementById('prog-list');
  list.innerHTML = '';

  progItems.forEach((p, idx) => {
    const isModified = p._dirty || p._source === 'override' || p._source === 'manual';
    const badgeCls  = isModified ? 'badge badge-warn' : 'badge badge-src';
    const badgeTxt  = isModified ? 'изменено вручную'  : 'из Telegram';

    const div = document.createElement('div');
    div.className = 'prog-item' + (p._llm_uncertain ? ' uncertain' : '');
    div.draggable = true;
    div.dataset.idx = idx;

    div.innerHTML = `
      <div class="prog-inner">
        <span class="grip">⠿</span>
        <div class="prog-body">
          <div class="prog-r1">
            <input class="prog-time"  type="text" value="${x(p.time)}"  placeholder="ЧЧ:ММ">
            <input class="prog-title" type="text" value="${x(p.title)}" placeholder="Название пункта">
            <button class="btn-del" title="Удалить">✕</button>
          </div>
          <div class="prog-r2">
            <input class="prog-note" type="text" value="${x(p.note || '')}" placeholder="заметка (необязательно)">
          </div>
          <div class="prog-r3">
            <label class="radio-lbl${p.is_practice_end ? ' is-end' : ''}">
              <input type="radio" name="prog-end" value="${idx}" ${p.is_practice_end ? 'checked' : ''}>
              конец кол. части
            </label>
            <span class="${badgeCls}">${badgeTxt}</span>
            ${p._llm_uncertain ? '<span class="llm-note">⚠ LLM не уверен во времени — проверь</span>' : ''}
          </div>
        </div>
      </div>`;

    const markDirty = (field, value) => {
      progItems[idx][field] = value;
      progItems[idx]._dirty = true;
      const b = div.querySelector('.badge');
      b.className = 'badge badge-warn'; b.textContent = 'изменено вручную';
      const rl = div.querySelector('.radio-lbl');
      rl.classList.remove('is-end');
      scheduleSave();
    };
    div.querySelector('.prog-time').addEventListener('input',  e => markDirty('time',  e.target.value));
    div.querySelector('.prog-title').addEventListener('input', e => markDirty('title', e.target.value));
    div.querySelector('.prog-note').addEventListener('input',  e => markDirty('note',  e.target.value || null));

    div.querySelector('.btn-del').addEventListener('click', () => {
      progItems.splice(idx, 1);
      renderProgram(); updateAutoMeta(); scheduleSave();
    });

    div.querySelector('input[type=radio]').addEventListener('change', () => {
      // write the boundary time to the SEPARATE practice_end field; do NOT dirty the
      // program (marking the boundary must not freeze the Telegram-sourced program)
      practiceEnd = progItems[idx].time || null;
      progItems.forEach((q, j) => { q.is_practice_end = (j === idx); });
      document.querySelectorAll('.radio-lbl').forEach((lbl, j) => {
        lbl.classList.toggle('is-end', j === idx);
      });
      scheduleSave();
    });

    setupDrag(div, 'prog');
    list.appendChild(div);
  });

  // Source badge in sub-head
  const hasOverride = progItems.some(p => p._dirty || p._source !== 'telegram');
  const sb = document.getElementById('prog-src-badge');
  sb.className = hasOverride ? 'badge badge-warn' : 'badge badge-src';
  sb.textContent = hasOverride ? 'изменено вручную' : 'из Telegram';
}

function addProgItem() {
  progItems.push({ time: '', title: '', note: null, is_practice_end: false,
                   _source: 'manual', _dirty: true, _llm_uncertain: false });
  renderProgram(); updateAutoMeta();
  const ts = document.querySelectorAll('.prog-time');
  if (ts.length) ts[ts.length - 1].focus();
  scheduleSave();
}

function resetProg() {
  progItems = sortProgByTime((manifest?.program || []).map(p => ({
    ...p, _source: 'telegram', _dirty: false, _llm_uncertain: p._llm_uncertain ?? false,
  })));
  // re-apply the boundary overlay so the radio stays consistent (marker is independent)
  progItems.forEach(p => { p.is_practice_end = !!practiceEnd && p.time === practiceEnd; });
  renderProgram(); updateAutoMeta(); scheduleSave();
}

// ── News editor ────────────────────────────────────────────────────────────────
function renderNews() {
  const list = document.getElementById('news-list');
  list.innerHTML = '';

  newsAuto.forEach((item, idx) => {
    const isDirty = item._dirty || newsAutoOverridden;
    const div = makeNewsEl(item.text, false, isDirty, idx);
    list.appendChild(div);
  });
  newsManual.forEach((item, idx) => {
    const div = makeNewsEl(item.text, true, false, idx);
    list.appendChild(div);
  });

  const hasAutoChanges = newsAutoOverridden || newsAuto.some(n => n._dirty);
  const sb = document.getElementById('news-src-badge');
  sb.className = hasAutoChanges ? 'badge badge-warn' : 'badge badge-src';
  sb.textContent = hasAutoChanges ? 'изменено вручную' : 'из Airtable';
}

function makeNewsEl(text, isManual, isDirty, idx) {
  const div = document.createElement('div');
  div.className = 'news-item' + (isManual ? ' is-manual' : '');
  div.draggable = true;
  div.dataset.idx = idx;
  div.dataset.manual = isManual ? '1' : '0';

  const badgeCls = isManual ? 'badge badge-new' : (isDirty ? 'badge badge-warn' : 'badge badge-src');
  const badgeTxt = isManual ? 'вручную'         : (isDirty ? 'изменено вручную'  : 'из Airtable');

  div.innerHTML = `
    <span class="grip">⠿</span>
    <input class="news-inp" type="text" value="${x(text)}" placeholder="Текст новости">
    <span class="${badgeCls}">${badgeTxt}</span>
    <button class="btn-del">✕</button>`;

  div.querySelector('.news-inp').addEventListener('input', e => {
    if (isManual) {
      newsManual[idx].text = e.target.value;
    } else {
      newsAuto[idx].text = e.target.value;
      newsAuto[idx]._dirty = true;
      newsAutoOverridden = true;
      const b = div.querySelector('.badge');
      b.className = 'badge badge-warn'; b.textContent = 'изменено вручную';
      document.getElementById('news-src-badge').className = 'badge badge-warn';
      document.getElementById('news-src-badge').textContent = 'изменено вручную';
    }
    updateAutoMeta();
    scheduleSave();
  });

  div.querySelector('.btn-del').addEventListener('click', () => {
    if (isManual) newsManual.splice(idx, 1);
    else { newsAuto.splice(idx, 1); newsAutoOverridden = true; }
    renderNews(); updateAutoMeta(); scheduleSave();
  });

  setupDrag(div, 'news');
  return div;
}

function addManualNews() {
  newsManual.push({ text: '' });
  renderNews(); updateAutoMeta();
  const inps = document.querySelectorAll('.news-inp');
  if (inps.length) inps[inps.length - 1].focus();
  scheduleSave();
}

function resetNews() {
  newsAuto = (manifest?.news || []).map(t => ({ text: t, _dirty: false }));
  newsAutoOverridden = false;
  newsManual = [];
  renderNews(); updateAutoMeta(); scheduleSave();
}

// ── Featured (important) news — manual-only accent block ─────────────────────────
// Lives in overrides.featured_news; separate from news / news_manual. Survives
// manifest rebuild (it's in selection). Empty → deck hides the block entirely.
function renderFeatured() {
  const list = document.getElementById('featured-list');
  list.innerHTML = '';
  featuredNews.forEach((item, idx) => list.appendChild(makeFeaturedEl(item.text, idx)));
}

function makeFeaturedEl(text, idx) {
  const div = document.createElement('div');
  div.className = 'news-item is-featured';
  div.innerHTML = `
    <span class="featured-mark">⚡</span>
    <input class="news-inp" type="text" value="${x(text)}" placeholder="Важная новость">
    <button class="btn-del">✕</button>`;
  div.querySelector('.news-inp').addEventListener('input', e => {
    featuredNews[idx].text = e.target.value;
    scheduleSave();
  });
  div.querySelector('.btn-del').addEventListener('click', () => {
    featuredNews.splice(idx, 1);
    renderFeatured(); scheduleSave();
  });
  return div;
}

function addFeatured() {
  featuredNews.push({ text: '' });
  renderFeatured();
  const inps = document.querySelectorAll('#featured-list .news-inp');
  if (inps.length) inps[inps.length - 1].focus();
  scheduleSave();
}

function resetDada() {
  document.getElementById('ov-dada').value = '';
  scheduleSave();
}

// ── Meeting date display ───────────────────────────────────────────────────────
function formatMeetingDate(iso) {
  try {
    const d = new Date(iso + 'T12:00:00');
    const months = ['января','февраля','марта','апреля','мая','июня',
                    'июля','августа','сентября','октября','ноября','декабря'];
    const yr = d.getFullYear(), cur = new Date().getFullYear();
    return yr !== cur
      ? `${d.getDate()} ${months[d.getMonth()]} ${yr}`
      : `${d.getDate()} ${months[d.getMonth()]}`;
  } catch(e) { return iso; }
}

// ── Automatic section status badge ────────────────────────────────────────────
function updateAutoStatus() {
  const s = buildStatus || {};
  const BUILD_STEPS = ['program','money','video','news','deploy'];
  const buildBad = !!s.ts && BUILD_STEPS.some(k => s[k] && s[k].ok === false);
  const missing = (manifest?.suggested_songs || []).filter(n => songType(n) === 'none');
  const bad = buildBad || missing.length > 0;
  const badge = document.getElementById('auto-status');
  const head  = document.getElementById('head-auto');
  if (!badge || !head) return;
  if (bad) {
    badge.className = 'badge-warn-auto';
    badge.textContent = '⚠ внимание';
    head.classList.add('auto-warn');
  } else if (s.ts) {
    badge.className = 'badge-ok';
    badge.textContent = '✓ авто';
    head.classList.remove('auto-warn');
  } else {
    badge.className = 'badge-neutral-auto';
    badge.textContent = 'авто';
    head.classList.remove('auto-warn');
  }
}

// ── Section meta summary ───────────────────────────────────────────────────────
function updateAutoMeta() {
  const nProg = progItems.length;
  const nNews = newsAuto.length + newsManual.length;
  document.getElementById('auto-meta').textContent =
    `${nProg} пункт${ru_n(nProg)} · ${nNews} нов${ru_news(nNews)}`;
}

function ru_n(n) {
  return n === 1 ? '' : n >= 2 && n <= 4 ? 'а' : 'ов';
}
function ru_news(n) {
  const m = n % 10, h = n % 100;
  if (h >= 11 && h <= 19) return 'остей';
  if (m === 1) return 'ость';
  if (m >= 2 && m <= 4) return 'ости';
  return 'остей';
}

// ── Drag & Drop ────────────────────────────────────────────────────────────────
function setupDrag(el, kind) {
  el.addEventListener('dragstart', e => {
    dragSrc = el; dragKind = kind;
    e.dataTransfer.effectAllowed = 'move';
    requestAnimationFrame(() => el.classList.add('dragging'));
  });
  el.addEventListener('dragend', () => {
    el.classList.remove('dragging');
    document.querySelectorAll('.drag-over').forEach(x => x.classList.remove('drag-over'));
    dragSrc = null;
  });
  el.addEventListener('dragover', e => {
    if (!dragSrc || dragSrc === el || dragKind !== kind) return;
    e.preventDefault();
    e.dataTransfer.dropEffect = 'move';
    document.querySelectorAll('.drag-over').forEach(x => x.classList.remove('drag-over'));
    el.classList.add('drag-over');
  });
  el.addEventListener('drop', e => {
    if (!dragSrc || dragSrc === el || dragKind !== kind) return;
    e.preventDefault();
    el.classList.remove('drag-over');
    const si = parseInt(dragSrc.dataset.idx, 10);
    const di = parseInt(el.dataset.idx, 10);
    if (kind === 'prog') {
      const [item] = progItems.splice(si, 1);
      progItems.splice(di, 0, item);
      renderProgram(); scheduleSave();
    } else if (kind === 'news') {
      const srcM = dragSrc.dataset.manual === '1';
      const dstM = el.dataset.manual === '1';
      if (srcM === dstM) {
        const arr = srcM ? newsManual : newsAuto;
        const [item] = arr.splice(si, 1);
        arr.splice(di, 0, item);
        renderNews(); scheduleSave();
      }
    }
  });
}

// ── Song cards ─────────────────────────────────────────────────────────────────
function addSong() {
  const inp = document.getElementById('song-num-input');
  const raw = inp.value.trim();
  // Empty number → open catalog picker instead of no-op
  if (raw === '') { openSongPicker(); return; }
  const n = parseInt(raw, 10);
  if (isNaN(n) || n < 1) return;
  inp.value = '';
  renderSongCard(n);
  songSource = 'manual'; renderSongSource();   // operator edited → now a manual pick
  scheduleSave();
}
document.getElementById('song-num-input').addEventListener('keydown', e => {
  if (e.key === 'Enter') addSong();
});

// ── Song picker (choose from catalog) ────────────────────────────────────────────
// Catalog is seeded Mac-side (milestone M1). This only picks from what's already there.
function currentSongNums() {
  return [...document.querySelectorAll('#song-cards .song-card')]
    .map(c => parseInt(c.dataset.number, 10));
}

function openSongPicker() {
  document.getElementById('song-picker').classList.add('open');
  const s = document.getElementById('picker-search');
  s.value = '';
  renderPicker('');
  s.focus();
}
function closeSongPicker() {
  document.getElementById('song-picker').classList.remove('open');
}
function openNewSongFromPicker() {
  closeSongPicker();
  openSongUpload();
}

function renderPicker(filter) {
  const body = document.getElementById('picker-body');
  const added = new Set(currentSongNums());
  const f = filter.trim().toLowerCase();

  // union: catalog (text) songs + image-only numbers, sorted by number
  const seen = new Set(catalog.map(s => s.number));
  const list = catalog.map(s => ({ ...s }));
  Object.keys(songImages).map(Number).forEach(n => {
    if (!seen.has(n)) list.push({ number: n, _imageOnly: true });
  });
  list.sort((a, b) => a.number - b.number);

  if (!list.length) {
    body.innerHTML = '<div class="picker-empty">Пусто.<br>Текст — сидом на Маке, картинки — в assets/songs/ (веха M1).</div>';
    return;
  }

  const rows = list.filter(s => {
    if (!f) return true;
    if (String(s.number).includes(f)) return true;
    if (s._imageOnly) return false;   // image-only rows match by number only
    return (s.title_translit || '').toLowerCase().includes(f)
      || (s.translation_first_line || '').toLowerCase().includes(f);
  });

  if (!rows.length) {
    body.innerHTML = `<div class="picker-empty">Ничего не найдено по «${x(filter)}».</div>`;
    return;
  }

  body.innerHTML = '';
  rows.forEach(s => {
    const isAdded = added.has(s.number);
    const type = songType(s.number);
    const icon = type === 'image' ? '🖼' : '📝';
    const title = s._imageOnly ? 'Картинка' : x(s.title_translit);
    const sub = s._imageOnly ? `assets/songs/${s.number}` : x(s.translation_first_line || '');
    const row = document.createElement('div');
    row.className = 'picker-row' + (isAdded ? ' added' : '');
    row.innerHTML = `
      <span class="picker-num">№${s.number}</span>
      <span class="picker-type" title="${type === 'image' ? 'картинка' : 'текст'}">${icon}</span>
      <div class="picker-text">
        <div class="picker-translit">${title}</div>
        <div class="picker-transl">${sub}</div>
      </div>
      ${isAdded ? '<span class="picker-added-lbl">✓ уже добавлена</span>' : ''}`;
    if (!isAdded) {
      row.addEventListener('click', () => {
        renderSongCard(s.number);
        songSource = 'manual'; renderSongSource();   // operator edited → manual pick
        scheduleSave();
        renderPicker(document.getElementById('picker-search').value);
      });
    }
    body.appendChild(row);
  });
}

document.getElementById('picker-search').addEventListener('input', e => renderPicker(e.target.value));
document.getElementById('picker-close').addEventListener('click', closeSongPicker);
document.getElementById('song-picker').addEventListener('click', e => {
  if (e.target.id === 'song-picker') closeSongPicker();   // click on backdrop
});
document.addEventListener('keydown', e => {
  if (e.key === 'Escape') closeSongPicker();
});

// ── Add a new image-backed PS (POST /api/song, OCR-assisted) ─────────────────────
// Tesseract.js runs in the operator's browser — no VPS OCR, no external calls.
// If /assets/ocr/tesseract.min.js is absent the form still works for manual entry.
//
// Race guard: each file selection gets a new _ocrToken. Stale OCR results are dropped.
// Dirty guard: a field the operator edited manually is never overwritten by OCR.

let _ocrWorker = null;    // Tesseract worker — created once, reused across sessions
let _ocrToken  = 0;       // incremented on each file selection; stale results are discarded
const _ocrDirty = new Set();  // upload-field ids the operator has edited manually

// Track manual edits — once touched, OCR won't overwrite that field
['upload-number', 'upload-title', 'upload-translation'].forEach(id => {
  document.getElementById(id).addEventListener('input', () => _ocrDirty.add(id));
});

function _setOcrStatus(msg) {
  const el = document.getElementById('upload-ocr-status');
  if (!el) return;
  el.textContent = msg;
  el.style.display = msg ? 'block' : 'none';
}

function openSongUpload() {
  document.getElementById('song-upload').classList.add('open');
  ['upload-file','upload-number','upload-title','upload-translation'].forEach(id => document.getElementById(id).value = '');
  const p = document.getElementById('upload-preview'); p.style.display = 'none'; p.src = '';
  document.getElementById('upload-error').style.display = 'none';
  _setOcrStatus('');
  _ocrToken++;        // invalidate any stale OCR from a previous modal session
  _ocrDirty.clear();
}
function closeSongUpload() { document.getElementById('song-upload').classList.remove('open'); }

document.getElementById('upload-close').addEventListener('click', closeSongUpload);
document.getElementById('song-upload').addEventListener('click', e => {
  if (e.target.id === 'song-upload') closeSongUpload();
});

document.getElementById('upload-file').addEventListener('change', e => {
  const f = e.target.files[0];
  const p = document.getElementById('upload-preview');
  if (!f) { p.style.display = 'none'; _setOcrStatus(''); return; }
  p.src = URL.createObjectURL(f); p.style.display = 'block';
  // New file → new OCR session; clear dirty state and start
  _ocrDirty.clear();
  const token = ++_ocrToken;
  _ocrRecognize(f, token);   // fire-and-forget; errors are silently suppressed
});

// ── OCR internals ─────────────────────────────────────────────────────────────

async function _getOcrWorker() {
  if (_ocrWorker) return _ocrWorker;
  if (typeof Tesseract === 'undefined') throw new Error('Tesseract.js не загружен');
  _ocrWorker = await Tesseract.createWorker('rus+eng', 1, {
    workerPath: '/assets/ocr/worker.min.js',
    corePath:   '/assets/ocr',
    langPath:   '/assets/ocr/langs',
  });
  return _ocrWorker;
}

// Crop image element to a canvas using relative coordinates (0–1)
function _cropCanvas(imgEl, rx, ry, rw, rh) {
  const W = imgEl.naturalWidth, H = imgEl.naturalHeight;
  const c = document.createElement('canvas');
  c.width  = Math.max(1, Math.floor(W * rw));
  c.height = Math.max(1, Math.floor(H * rh));
  c.getContext('2d').drawImage(imgEl,
    Math.floor(W * rx), Math.floor(H * ry),
    c.width, c.height, 0, 0, c.width, c.height);
  return c;
}

// Remove combining diacritical marks (stress marks Tesseract adds to Cyrillic)
function _stripDiacritics(s) { return s.replace(/[̀-ͯ]/g, ''); }

// Sentence-case with diacritics stripped: "ПУРНОТБЕР ГИТО" → "Пурнотбер гито"
function _sentenceCase(s) {
  s = _stripDiacritics(s.trim());
  return s ? s.charAt(0).toUpperCase() + s.slice(1).toLowerCase() : '';
}

// Parse number from header text "Прабхат Самгит N"
function _ocrParseNumber(text) {
  const m = text.match(/[Пп]рабхат\s*[Сс]амгит\s*(\d+)/);
  if (m) return parseInt(m[1], 10);
  const nums = [...text.matchAll(/\b(\d{1,4})\b/g)]
    .map(x => parseInt(x[1], 10)).filter(n => n >= 1 && n <= 9999);
  return nums.length === 1 ? nums[0] : null;
}

// Is a string predominantly uppercase (works for Cyrillic + Latin)?
function _isAllCaps(s) {
  const letters = (s.match(/[а-яёА-ЯЁa-zA-Z]/g) || []);
  const upper   = letters.filter(c => c === c.toUpperCase() && c !== c.toLowerCase());
  return letters.length > 2 && upper.length / letters.length > 0.85;
}

// Parse an all-caps subtitle line into {title, translation}. Real formats observed:
//   "ПУРНОТБЕР ГИТО (ПЕСНЯ РЕАЛИЗАЦИИ)" → title:"Пурнотбер гито"  translation:"Песня реализации"
//   "ЧОМПОКО БОНЕ МОДХУРО ШОПОНЕ"       → title:"Чомпоко боне..."  translation:""
//   "ПЕСНЯ ОСВОБОЖДЕНИЯ"                 → title:"Песня освобождения" translation:""
// Called only when the input is already confirmed all-caps (see _ocrRecognize).
function _parseSubtitle(line) {
  line = _stripDiacritics(line.trim());
  if (!line || line.length < 3) return { title: '', translation: '' };

  const m = line.match(/^(.+?)\s*\(([^)]+)\)\s*$/);
  if (m) {
    const left = m[1].trim(), right = m[2].trim();
    if (_isAllCaps(left)) {
      return { title: _sentenceCase(left), translation: _sentenceCase(right) };
    }
  }
  // No parens or left side not ALL CAPS
  if (_isAllCaps(line)) return { title: _sentenceCase(line), translation: '' };
  // Starts with Cyrillic capital → Russian translation subtitle
  return { title: '', translation: line.charAt(0).toUpperCase() + line.slice(1) };
}

// Only write to a field if the operator hasn't touched it
function _ocrFill(fieldId, value) {
  if (_ocrDirty.has(fieldId) || !value) return;
  document.getElementById(fieldId).value = value;
}

async function _ocrRecognize(file, token) {
  try {
    _setOcrStatus('Распознаю данные слайда…');

    // Load into HTMLImageElement for canvas cropping
    const blobUrl = URL.createObjectURL(file);
    const img = await new Promise((res, rej) => {
      const el = new Image();
      el.onload  = () => res(el);
      el.onerror = () => rej(new Error('image load failed'));
      el.src = blobUrl;
    });
    if (_ocrToken !== token) { URL.revokeObjectURL(blobUrl); return; }

    const worker = await _getOcrWorker();
    if (_ocrToken !== token) { URL.revokeObjectURL(blobUrl); return; }

    // ── Single header crop: full width, top 25% ────────────────────────────
    // Real slides: "Прабхат Самгит N" on line 1, optional all-caps subtitle on line 2.
    // Body text always mixes transliteration CAPS + Russian lowercase on the same line,
    // so _isAllCaps() reliably separates subtitle from body.
    const headerResult = await worker.recognize(_cropCanvas(img, 0, 0, 1.0, 0.25));
    if (_ocrToken !== token) { URL.revokeObjectURL(blobUrl); return; }

    const headerLines = headerResult.data.text
      .split(/\r?\n/)
      .map(l => _stripDiacritics(l.trim()))
      .filter(l => l.length > 1);

    const number = _ocrParseNumber(headerLines[0] || '');
    _ocrFill('upload-number', number ? String(number) : null);

    // Some slides embed the subtitle on the same line as the number (e.g. "ПС 6 - ПЕСНЯ ПРОБУЖДЕНИЯ").
    // Others put it on a dedicated second line (e.g. "ПУРНОТБЕР ГИТО (ПЕСНЯ РЕАЛИЗАЦИИ)").
    const suffixM = (headerLines[0] || '').match(/[Пп]рабхат\s*[Сс]амгит\s*\d+\s*[-–—]?\s*(.+)/);
    const suffixCandidate = suffixM ? suffixM[1].trim() : '';
    const subtitleLine = (_isAllCaps(suffixCandidate) ? suffixCandidate : null)
      || (_isAllCaps(headerLines[1] || '') ? (headerLines[1] || '') : null);
    if (subtitleLine) {
      // Russian-only genre labels ("ПЕСНЯ ОСВОБОЖДЕНИЯ") belong to the subtitle DB field,
      // not to title_translit — skip them; upload-title requires Bengali transliteration.
      // The "TITLE (TRANSLATION)" format (parens) is handled by _parseSubtitle regardless.
      const isRussianLabel = subtitleLine.toUpperCase().includes('ПЕСНЯ') && !subtitleLine.includes('(');
      if (!isRussianLabel) {
        const { title, translation } = _parseSubtitle(subtitleLine);
        _ocrFill('upload-title', title);
        _ocrFill('upload-translation', translation);
      }
    }

    URL.revokeObjectURL(blobUrl);
    _setOcrStatus('');
  } catch (err) {
    console.warn('[ocr]', err.message || err);
    _setOcrStatus('');   // hide status; form remains fully functional for manual entry
  }
}

async function submitSongUpload() {
  const err = document.getElementById('upload-error');
  const show = m => { err.textContent = m; err.style.display = 'block'; };
  const file = document.getElementById('upload-file').files[0];
  const number = parseInt(document.getElementById('upload-number').value, 10);
  const title = document.getElementById('upload-title').value.trim();
  const translation = document.getElementById('upload-translation').value.trim();
  if (!file)            return show('Выбери картинку слайда.');
  if (!(number >= 1))   return show('Укажи номер ПС.');
  if (!title)           return show('Укажи название.');

  const btn = document.getElementById('upload-submit');
  btn.disabled = true;
  try {
    const fd = new FormData();
    fd.append('image', file); fd.append('number', number);
    fd.append('title', title); fd.append('translation', translation);
    const r = await fetch('/api/song', { method: 'POST', body: fd });
    if (!r.ok) { show((await r.json().catch(() => ({}))).detail || `Ошибка ${r.status}`); return; }
    const data = await r.json();
    // Reflect new song in-memory so the card/picker/slide work without reload
    if (!catalog.find(s => s.number === number)) {
      catalog.push({ number, title_translit: title, translation_first_line: translation, stanzas: [], lang: 'translit' });
    }
    songImages[number] = data.image_path;
    closeSongUpload();
    renderSongCard(number);
    songSource = 'manual'; renderSongSource();
    scheduleSave();
  } catch (e) {
    show('Сеть недоступна: ' + e.message);
  } finally {
    btn.disabled = false;
  }
}
// ТГ-suggestion note + a roll-up of numbers with no image AND no catalog text.
// Канал А (статус-строка): последняя сборка + вердикт из /api/build-status.
function renderBuildStatus() {
  const el = document.getElementById('build-status');
  if (!el) return;
  const s = buildStatus || {};
  if (!s.ts) { el.style.display = 'none'; return; }
  const srcs = [['program','программа'],['money','деньги'],['video','видео'],['news','новости'],['deploy','деплой']];
  const failed = srcs.filter(([k]) => s[k] && s[k].ok === false).map(([, label]) => label);
  const date = String(s.ts).replace('T', ' ').slice(0, 16);
  const verdict = failed.length ? ('⚠️ не потянулось: ' + failed.join(', ')) : '✅ всё собралось';
  el.style.display = '';
  el.className = 'build-status ' + (failed.length ? 'bad' : 'ok');
  el.innerHTML = 'Последняя сборка: <b>' + x(date) + '</b> · ' + x(verdict);
}

// Канал А (верхний баннер): номера из чата, которых НЕТ ни в картинках, ни в каталоге.
function renderTopAlert() {
  const el = document.getElementById('top-alert');
  if (!el) return;
  const missing = (manifest?.suggested_songs || []).filter(n => songType(n) === 'none');
  if (!missing.length) { el.innerHTML = ''; el.style.display = 'none'; return; }
  el.style.display = '';
  el.innerHTML = '⚠️ Песни из чата, которых НЕТ в базе: <b>'
    + missing.map(n => '№' + n).join(', ')
    + '</b> — добавь картинку в <code>assets/songs/&lt;N&gt;.webp</code> (или текст в каталог).';
}

// ISO year×week for a "YYYY-MM-DD" string (same formula as deck/merge.js).
function isoWeekYear(dateStr) {
  if (!dateStr) return null;
  const d = new Date(dateStr + 'T12:00:00');
  const day = d.getDay() || 7;
  const thu = new Date(d);
  thu.setDate(d.getDate() + 4 - day);
  const y = thu.getFullYear();
  const jan1 = new Date(y, 0, 1);
  return y * 100 + Math.ceil(((thu - jan1) / 86400000 + 1) / 7);
}

// Song priority (mirrors deck/merge.js): manual pick wins ONLY when fresh
// (selection.week_date's ISO week == the build week); otherwise the chat's
// suggested_songs auto-apply; fallback keeps the old pick (never blank).
// Returns {numbers, source: 'manual'|'auto'|'fallback'}.
function resolveSongs() {
  const selSongs  = (selection?.song_numbers) || [];
  const suggested = (manifest?.suggested_songs) || [];
  const selWeek   = isoWeekYear(selection?.week_date);
  const buildWeek = isoWeekYear(manifest?.date);
  const fresh = selWeek && buildWeek && selWeek === buildWeek;
  if (fresh && selSongs.length) return { numbers: selSongs, source: 'manual' };
  if (suggested.length)         return { numbers: suggested, source: 'auto' };
  return { numbers: selSongs, source: 'fallback' };
}

// Where the currently-shown numbers come from. No «Применить» button — the chat's
// numbers auto-apply on the deck; the operator only edits when they want different.
function renderSongSource() {
  const el = document.getElementById('song-source-hint');
  if (!el) return;
  const nums = currentSongNums();
  el.style.display = '';
  if (songSource === 'manual') {
    el.style.color = '';
    el.innerHTML = '✋ Задано вручную на эту неделю.';
  } else if (songSource === 'auto') {
    el.style.color = '';
    el.innerHTML = '🎵 Из чата (авто): <b>' + x(nums.map(n => '№' + n).join(', '))
      + '</b> — встанут в дек сами. Правь, только если нужно другое.';
  } else {   // fallback: stale/empty selection and nothing from the chat
    if (!nums.length) {
      el.style.color = '';
      el.innerHTML = '➖ Песни не заданы и из чата не пришли.';
    } else {
      el.style.color = 'var(--warn)';
      const wd = (selection?.week_date || '').split('-').reverse().join('.');
      el.innerHTML = '⚠️ С прошлой недели (' + x(wd) + '), из чата ничего не пришло — проверь.';
    }
  }
}

// what backs song N on the deck: image (priority) → text → nothing
function songType(n) {
  if (songImages[n] != null || songImages[String(n)] != null) return 'image';
  if (catalog.find(s => s.number === n)) return 'text';
  return 'none';
}

// Drag-to-reorder song cards. Unlike program/news (array-backed), song order is just the
// DOM order of #song-cards .song-card — so we reorder the nodes directly, then save.
function setupSongDrag(card) {
  card.addEventListener('dragstart', e => {
    dragSrc = card; dragKind = 'song';
    e.dataTransfer.effectAllowed = 'move';
    requestAnimationFrame(() => card.classList.add('dragging'));
  });
  card.addEventListener('dragend', () => {
    card.classList.remove('dragging');
    document.querySelectorAll('.drag-over').forEach(x => x.classList.remove('drag-over'));
    dragSrc = null;
  });
  card.addEventListener('dragover', e => {
    if (!dragSrc || dragSrc === card || dragKind !== 'song') return;
    e.preventDefault(); e.dataTransfer.dropEffect = 'move';
    document.querySelectorAll('.drag-over').forEach(x => x.classList.remove('drag-over'));
    card.classList.add('drag-over');
  });
  card.addEventListener('drop', e => {
    if (!dragSrc || dragSrc === card || dragKind !== 'song') return;
    e.preventDefault(); card.classList.remove('drag-over');
    const cards = [...document.querySelectorAll('#song-cards .song-card')];
    if (cards.indexOf(dragSrc) < cards.indexOf(card)) card.after(dragSrc);
    else card.before(dragSrc);
    scheduleSave();
  });
}

function renderSongCard(n) {
  const type = songType(n);
  const s = catalog.find(q => q.number === n);
  const card = document.createElement('div');
  card.className = (type === 'none') ? 'song-card stub' : 'song-card found';
  card.dataset.number = n;
  if (type === 'image') {
    // image wins even if text also exists; title is the primary identifier, image badge is secondary
    const imgTitle = s ? x(s.title_translit) : '';
    const imgSub   = s ? x(s.translation_first_line || '') : 'assets/songs/' + n;
    card.innerHTML = `
      <span class="song-num">№${n}</span>
      <div class="song-text">
        <div class="song-translit">${imgTitle || '<span style="opacity:0.45;font-style:italic">нет названия</span>'}&ensp;<span style="opacity:0.45;font-size:0.8em">🖼</span></div>
        <div class="song-transl">${imgSub}</div>
      </div>
      <button class="btn-rm-song">✕</button>`;
  } else if (type === 'text') {
    card.innerHTML = `
      <span class="song-num">№${n}</span>
      <div class="song-text">
        <div class="song-translit">📝 ${x(s.title_translit)}</div>
        <div class="song-transl">${x(s.translation_first_line || '')}</div>
      </div>
      <button class="btn-rm-song">✕</button>`;
  } else {
    // neither image nor catalog text → warn the operator (non-blocking)
    card.innerHTML = `
      <span class="song-num">№${n}</span>
      <div class="song-text">
        <div class="song-stub-lbl">⚠ Нет ни картинки, ни текста</div>
        <div class="song-transl">добавь картинку в assets/songs/${n}.webp</div>
      </div>
      <button class="btn-rm-song">✕</button>`;
  }
  // grip + drag-to-reorder: song order on the deck = DOM order of the cards (doSave reads it)
  card.insertAdjacentHTML('afterbegin', '<span class="grip" title="Перетащите, чтобы изменить порядок">⠿</span>');
  card.draggable = true;
  setupSongDrag(card);
  card.querySelector('.btn-rm-song').addEventListener('click', () => {
    card.remove();
    songSource = 'manual'; renderSongSource();   // operator edited → now a manual pick
    scheduleSave();
  });
  document.getElementById('song-cards').appendChild(card);
}

// ── Live progress bar ──────────────────────────────────────────────────────────
// raised/plan mirror the video pattern: an empty field falls through to the
// manifest auto value (Telegram finance post) for DISPLAY only. doSave still
// sends null for an empty field, so leaving it blank never freezes selection.
function autoRaised() { return Number.isFinite(manifest?.raised) ? manifest.raised : 0; }
function autoPlan()   { return Number.isFinite(manifest?.plan)   ? manifest.plan   : 0; }

function updateBar() {
  const rf = document.getElementById('raised').value;
  const pf = document.getElementById('plan').value;
  const r = rf !== '' ? (parseInt(rf, 10) || 0) : autoRaised();
  const p = pf !== '' ? (parseInt(pf, 10) || 0) : autoPlan();
  const bar = document.getElementById('live-bar');
  const lbl = document.getElementById('live-bar-lbl');
  if (!p) {
    bar.style.width = '0%';
    lbl.textContent = 'введите план, чтобы увидеть прогресс';
    return;
  }
  const pct = Math.min(100, Math.round(r / p * 100));
  bar.style.width = pct + '%';
  lbl.textContent = `${r.toLocaleString('ru-RU')} из ${p.toLocaleString('ru-RU')} ₽ · ${pct}%`;
}

// Show the auto sum as placeholder + hint so an empty field reads as the auto
// value, not a bare 0. Called on load and after «↻ проверить» re-reads manifest.
function renderAutoMoney() {
  document.getElementById('raised').placeholder = autoRaised() ? String(autoRaised()) : '0';
  document.getElementById('plan').placeholder   = autoPlan()   ? String(autoPlan())   : '30000';
  const hint = document.getElementById('money-auto-hint');
  if (hint) {
    hint.textContent = autoRaised()
      ? `💰 Авто из ТГ-поста финансов: ${autoRaised().toLocaleString('ru-RU')} ₽ из `
        + `${(autoPlan() || 0).toLocaleString('ru-RU')} ₽ — в баре, если поля пусты. `
        + `Заполни, только чтобы перекрыть.`
      : 'Авто-сбор из ТГ не найден — заполни вручную.';
  }
  updateBar();
}
document.getElementById('raised').addEventListener('input',    () => { updateBar(); scheduleSave(); });
document.getElementById('plan').addEventListener('input',      () => { updateBar(); scheduleSave(); });
// ── Auto-video (Dada video from СВАДХЬЯЯ, baked into manifest on the Mac) ─────────
// The VPS never scans Telegram itself; the form only reflects manifest.video_url.
// «↻ проверить» re-reads the freshest manifest (e.g. after a new Mac push).
function renderAutoVideo() {
  const el = document.getElementById('video-auto-hint');
  if (!el) return;
  const url = manifest?.video_url;
  const overridden = document.getElementById('video-url').value.trim();
  if (url) {
    el.innerHTML = `🎬 Авто из СВАДХЬЯЯ: <a href="${x(url)}" target="_blank" rel="noopener">${x(url)}</a>`
      + (overridden ? ' <span style="color:var(--warn)">(перекрыто полем выше)</span>' : ' — играет, если поле пусто');
  } else {
    el.textContent = 'Авто-видео не найдено — покажется слайд Дады';
  }
}
async function refreshAutoVideo() {
  const el = document.getElementById('video-auto-hint');
  if (el) el.textContent = 'Проверяю manifest…';
  try {
    manifest = await fetch('/manifest.json?_=' + Date.now()).then(r => r.json());
  } catch { /* keep old manifest */ }
  renderAutoVideo();
  renderAutoMoney();
}

document.getElementById('video-url').addEventListener('input', () => { renderAutoVideo(); scheduleSave(); });
document.getElementById('final-video-url').addEventListener('input', scheduleSave);
document.getElementById('bg-music-url').addEventListener('input', scheduleSave);
document.getElementById('ov-dada').addEventListener('input',   scheduleSave);
document.getElementById('hide-urokimeditacii').addEventListener('change', scheduleSave);

// ── Save ───────────────────────────────────────────────────────────────────────
function scheduleSave() {
  setSave('saving', '… сохраняю');
  clearTimeout(saveTimer);
  saveTimer = setTimeout(doSave, SAVE_DELAY);
}

// Amount from a money field. Empty → null (fall through to the manifest/Telegram
// auto value). Any number INCLUDING 0 → that number (overrides the auto). The old
// `parseInt(v) || null` turned an explicit 0 into null, so «0» never overrode.
function amountVal(id) {
  const v = document.getElementById(id).value.trim();
  if (v === '') return null;
  const n = parseInt(v, 10);
  return Number.isNaN(n) ? null : n;
}

async function doSave() {
  const songNums = [...document.querySelectorAll('#song-cards .song-card')]
    .map(c => parseInt(c.dataset.number, 10)).filter(n => !isNaN(n));

  const hasProgChanges = progItems.some(p => p._dirty || p._source !== 'telegram');
  const progOv = hasProgChanges
    ? progItems.map(({ time, title, note, is_practice_end, _llm_uncertain }) =>
        ({ time, title, note: note || null, is_practice_end, _llm_uncertain }))
    : null;

  const hasNewsChanges = newsAutoOverridden || newsAuto.some(n => n._dirty);
  const newsOv    = hasNewsChanges ? newsAuto.map(n => n.text) : null;
  const manualArr = newsManual.map(n => n.text).filter(Boolean);
  const featuredArr = featuredNews.map(n => n.text).filter(Boolean);

  const body = {
    // week_date = the ДЧ week this selection is FOR (the build's target Sunday).
    // Saving stamps the CURRENT week → the selection becomes "fresh" so manual
    // picks win THIS week; next week the manifest date moves on and it goes stale,
    // letting the chat's suggested_songs auto-apply again.
    week_date:    manifest?.date ?? selection?.week_date ?? new Date().toISOString().slice(0, 10),
    song_numbers: songNums,
    video_url:       document.getElementById('video-url').value.trim(),
    final_video_url: document.getElementById('final-video-url').value.trim(),
    bg_music_url:    document.getElementById('bg-music-url').value.trim(),
    raised:       amountVal('raised'),
    plan:         amountVal('plan'),
    overrides: {
      program:       progOv,
      news:          newsOv,
      news_manual:   manualArr.length ? manualArr : null,
      featured_news: featuredArr.length ? featuredArr : null,
      practice_end:  practiceEnd || null,
      dada_comment:  document.getElementById('ov-dada').value.trim() || null,
      hide_urokimeditacii: document.getElementById('hide-urokimeditacii').checked,
    },
  };

  try {
    const r = await fetch('/api/selection', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    if (r.ok) {
      setSave('saved', '✓ сохранено');
      setTimeout(() => setSave('idle', '☁'), 3000);
    } else {
      setSave('error', `✗ ошибка ${r.status}`);
    }
  } catch {
    setSave('error', '✗ нет связи');
  }
}

const SAVE_BANNER = {
  idle:   ['☁', 'Правки сохраняются автоматически'],
  saving: ['⏳', 'Сохраняю…'],
  saved:  ['✓', 'Сохранено'],
  error:  ['✗', 'Ошибка сохранения — проверь связь'],
};
function setSave(state, text) {
  const el = document.getElementById('save-ind');
  el.className = 'save-ind ' + state;
  document.getElementById('save-text').textContent = text;
  // prominent, always-visible banner right above the «Собрать» button
  const b = document.getElementById('save-banner');
  if (b) {
    b.className = 'save-banner ' + state;
    const [ic, tx] = SAVE_BANNER[state] || SAVE_BANNER.idle;
    document.getElementById('save-banner-icon').textContent = ic;
    document.getElementById('save-banner-text').textContent = tx;
  }
}

// ── Collapse ───────────────────────────────────────────────────────────────────
function toggleSection(hId, bId) {
  const h = document.getElementById(hId);
  const b = document.getElementById(bId);
  const open = !b.classList.contains('hidden');
  b.classList.toggle('hidden', open);
  h.classList.toggle('open', !open);
}
document.getElementById('head-auto').addEventListener('click',  () => toggleSection('head-auto',  'body-auto'));
document.getElementById('head-yours').addEventListener('click', () => toggleSection('head-yours', 'body-yours'));

// ── Button wiring (replaces onclick= attributes — CSP script-src 'unsafe-inline' avoided) ──
document.getElementById('btn-open-deck')    ?.addEventListener('click', openDeck);
document.getElementById('theme-sel')        ?.addEventListener('change', e => onThemeChange(e.target.value));
document.getElementById('btn-reset-prog')   ?.addEventListener('click', resetProg);
document.getElementById('btn-add-prog')     ?.addEventListener('click', addProgItem);
document.getElementById('btn-reset-news')   ?.addEventListener('click', resetNews);
document.getElementById('btn-add-news')     ?.addEventListener('click', addManualNews);
document.getElementById('btn-add-featured') ?.addEventListener('click', addFeatured);
document.getElementById('btn-reset-dada')   ?.addEventListener('click', resetDada);
document.getElementById('btn-done-auto')    ?.addEventListener('click', () => toggleSection('head-auto', 'body-auto'));
document.getElementById('btn-add-song')     ?.addEventListener('click', addSong);
document.getElementById('btn-refresh-video')?.addEventListener('click', refreshAutoVideo);
document.getElementById('btn-open-pdf')     ?.addEventListener('click', openPdf);
document.getElementById('upload-submit')    ?.addEventListener('click', submitSongUpload);
document.getElementById('btn-new-song-picker')?.addEventListener('click', openNewSongFromPicker);

// ── Utils ──────────────────────────────────────────────────────────────────────
function x(s) {
  return String(s ?? '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}
function openDeck() { window.open('/', '_blank'); }
function openPdf()  { window.open('/?print-pdf', '_blank'); }

// ── Theme ──────────────────────────────────────────────────────────────────────
const VALID_THEMES = ['warm', 'midnight', 'charcoal'];
let _confirmedTheme = 'warm';

function applyTheme(t) {
  if (!VALID_THEMES.includes(t)) t = 'warm';
  document.documentElement.setAttribute('data-theme', t);
  try { localStorage.setItem('operator-theme', t); } catch(e) {}
  const sel = document.getElementById('theme-sel');
  if (sel) sel.value = t;
}

async function onThemeChange(key) {
  if (!VALID_THEMES.includes(key)) return;
  const prev = _confirmedTheme;
  applyTheme(key); // optimistic
  try {
    const r = await fetch('/api/theme-key', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({theme: key}),
    });
    if (!r.ok) throw new Error(r.status);
    _confirmedTheme = key;
  } catch {
    applyTheme(prev); // revert to last server-confirmed
    setSave('error', '✗ тема не сохранена');
  }
}

(function initTheme() {
  let t = 'warm';
  try { t = localStorage.getItem('operator-theme') || 'warm'; } catch(e) {}
  if (!VALID_THEMES.includes(t)) t = 'warm';
  applyTheme(t); // fast first paint from cache; overridden by server in init()
})();

// ── Boot ───────────────────────────────────────────────────────────────────────
init();
