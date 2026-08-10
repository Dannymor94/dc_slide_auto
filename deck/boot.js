import { buildEffective } from './merge.js';
import { infoSlide } from './slides/info.js';
import { songSlide } from './slides/song.js';
import { videoSlide, youtubeEmbedUrl } from './slides/video.js';
import { dadaSlide } from './slides/dada.js';
import { musicSlide } from './slides/music.js';
import { urokimeditaciiSlide } from './slides/urokimeditacii.js';

async function safeFetch(url) {
  try {
    const r = await fetch(url);
    if (!r.ok) return null;
    return await r.json();
  } catch {
    return null;
  }
}

function applyTheme(t) {
  const root = document.documentElement;
  const map = {
    accent: '--accent',
    accent_light: '--accent-light',
    slide_bg: '--slide-bg',
    bg_card: '--bg-card',
    text_main: '--text-main',
    text_muted: '--text-muted',
    song_translit_color: '--song-translit-color',
    song_translation_color: '--song-translation-color',
    font_heading: '--font-heading',
    font_body: '--font-body',
    panel_bg: '--panel-bg',
    panel_radius: '--panel-radius',
    news_panel_bg: '--news-panel-bg',
    news_panel_text: '--news-panel-text',
    featured_bg: '--featured-bg',
    featured_border: '--featured-border',
    footer_opening_bg: '--footer-opening-bg',
    footer_continuation_bg: '--footer-continuation-bg',
  };
  for (const [key, prop] of Object.entries(map)) {
    if (t[key]) root.style.setProperty(prop, t[key]);
  }
}

function showBanner(msg) {
  const div = document.createElement('div');
  div.id = 'dc-banner';
  div.textContent = msg;
  document.body.prepend(div);
}

async function buildSlides() {
  const [theme, manifest, selection, catalog, songImages] = await Promise.all([
    safeFetch('theme.json'),
    safeFetch('manifest.json'),
    safeFetch('/api/selection'),
    safeFetch('/api/catalog'),
    safeFetch('/api/song-images'),
  ]);

  const apiDown = selection === null || catalog === null;
  if (apiDown) showBanner('Нет связи с формой — показываю авто-данные.');

  applyTheme(theme ?? {});

  const effective = buildEffective(
    manifest ?? {},
    apiDown ? null : selection,
    apiDown ? [] : (catalog ?? []),
    songImages ?? {},
  );

  // video XOR dada: if a playable video exists → show video, skip dada.
  // No video → skip video slide entirely, show dada instead.
  const hasVideo = !!youtubeEmbedUrl(effective.video_url || '');

  // slide order: info(opening) → song×N → video OR dada → info(continuation) → music
  const sections = [
    infoSlide(effective, 'opening'),
    ...effective.songs.map(s => songSlide(s, theme ?? {})),
    ...(hasVideo ? [videoSlide(effective)] : [dadaSlide(effective)]),
    infoSlide(effective, 'continuation'),
  ];

  // final music slide (from manifest) if present
  const music = musicSlide(effective);
  if (music) sections.push(music);

  // final video slide — last in the deck, only when final_video_url is set
  if (youtubeEmbedUrl(effective.final_video_url || '')) {
    sections.push(videoSlide({ ...effective, video_url: effective.final_video_url }));
  }

  // Уроки-медитации slide — appended LAST, only when the manifest baked it
  // (Sunday-КМ week) AND the operator hasn't hidden it via the toggle.
  if (effective.urokimeditacii && !effective.hide_urokimeditacii) {
    sections.push(urokimeditaciiSlide(effective.urokimeditacii, effective.bg_music_url));
  }

  const container = document.getElementById('dc-slides');
  container.innerHTML = sections.join('\n');

  // 191 = "/" key (Reveal's built-in help) — disabled so "?" opens OUR Russian help panel.
  // F (fullscreen) and arrows stay native.
  const revealCfg = {
    hash: true, transition: 'fade', controls: false, progress: false,
    keyboard: { 191: null, 70: null },   // disable Reveal's own "/" help and F (we toggle F ourselves)
  };
  const onRevealReady = () => Reveal.initialize(revealCfg).then(() => { buildFilmstrip(); setupCinema(); setupBgMusic(effective.bg_music_url); });
  if (typeof Reveal !== 'undefined') {
    onRevealReady();
  } else {
    document.querySelector('script[src*="reveal.js"]')?.addEventListener('load', onRevealReady);
  }

  setupControls();
}

// ── Filmstrip: light scaled clones of every slide (no iframes → no network) ──────
function buildFilmstrip() {
  const strip = document.getElementById('dc-filmstrip');
  if (!strip || typeof Reveal === 'undefined') return;
  const cfg = Reveal.getConfig();
  const W = cfg.width || 960, H = cfg.height || 700;
  const THUMB_W = 148;
  const scale = THUMB_W / W;
  const thumbH = Math.round(H * scale);

  const sections = [...document.querySelectorAll('#dc-slides > section')];
  strip.innerHTML = '';
  sections.forEach((sec, i) => {
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'dc-thumb';
    btn.style.width = THUMB_W + 'px';
    btn.style.height = thumbH + 'px';

    const inner = document.createElement('div');
    inner.className = 'dc-thumb-inner';
    inner.style.width = W + 'px';
    inner.style.height = H + 'px';
    inner.style.transform = `scale(${scale})`;

    const clone = sec.cloneNode(true);
    // undo Reveal's per-slide hidden/active state so the clone renders standalone
    clone.removeAttribute('hidden');
    clone.removeAttribute('aria-hidden');
    clone.classList.remove('present', 'past', 'future', 'stack');
    if (clone.style.display === 'none') clone.style.display = '';
    // drop iframes (video/music) → static placeholder; never re-load media for a thumbnail
    clone.querySelectorAll('iframe').forEach(f => {
      const ph = document.createElement('div');
      ph.className = 'dc-thumb-iframe';
      ph.textContent = '▶';
      f.replaceWith(ph);
    });
    // on-slide nav arrows + the music button are for the live slide only — no clutter
    clone.querySelectorAll('.slide-nav, .info-music-btn').forEach(n => n.remove());
    inner.appendChild(clone);
    btn.appendChild(inner);

    const num = document.createElement('span');
    num.className = 'dc-thumb-num';
    num.textContent = i + 1;
    btn.appendChild(num);

    btn.addEventListener('click', () => { if (Reveal.isReady?.()) Reveal.slide(i); });
    strip.appendChild(btn);
  });

  Reveal.on('slidechanged', updateThumbActive);
  updateThumbActive();
  if (Reveal.isReady?.()) Reveal.layout();   // fit the deck above the (now visible) strip
}

function updateThumbActive() {
  if (typeof Reveal === 'undefined') return;
  const idx = Reveal.getIndices?.().h ?? 0;
  const thumbs = document.querySelectorAll('.dc-thumb');
  thumbs.forEach((t, i) => t.classList.toggle('active', i === idx));
  thumbs[idx]?.scrollIntoView({ inline: 'center', block: 'nearest', behavior: 'smooth' });
}

// ── Cinema: a played YouTube video fills the viewport (no cross-origin fullscreen
// trap), the deck keeps the keyboard so arrows still switch slides, and YouTube's
// own controls show on pause. Driven by the IFrame Player API (play/pause events). ──
let ytPlayers = [];

function setupCinema() {
  // image-song slides fill the screen when shown; video/music fill on play.
  if (typeof Reveal !== 'undefined') Reveal.on('slidechanged', onCinemaSlideChanged);
  onCinemaSlideChanged();   // deck may open directly on an image-song slide

  const frames = [...document.querySelectorAll('.yt-embed')];
  if (!frames.length) return;
  loadYTApi(() => {
    frames.forEach(f => {
      try {
        ytPlayers.push(new YT.Player(f, {
          events: { onStateChange: e => {
            if (e.data === 1) enterCinema(f);          // PLAYING → cinema
            // PAUSED (2) / ENDED (0) stay in cinema: a playlist advances to the next
            // item without a flicker, and YouTube shows its controls on pause.
            // Cinema exits on slide change (arrows / ‹ ›) or Esc.
          } },
        }));
      } catch { /* API blocked → base embedded playback still works */ }
    });
  });
}

// The <img> of the active image-song slide, else null.
function currentImageSong() {
  const cur = (typeof Reveal !== 'undefined' && Reveal.getCurrentSlide?.()) || null;
  return cur && cur.classList.contains('slide-song-image') ? cur.querySelector('img') : null;
}

// Image songs fill the screen ONLY during the show (deck fullscreen); in windowed
// preview they stay framed with the filmstrip. Reconciles song cinema against the
// current slide + fullscreen state WITHOUT touching a playing video's cinema (that
// lives on an <iframe>, not an <img>), so exiting fullscreen never stops a video.
function refreshSongCinema() {
  const img = currentImageSong();
  const inShow = document.body.classList.contains('dc-fs');
  if (img && inShow) {
    if (!img.classList.contains('cinema-fill')) enterCinema(img);   // no caption for songs
  } else if (document.querySelector('img.cinema-fill')) {
    exitCinema();
  }
}

// On every slide change: drop any prior cinema (pauses video, restores layout),
// then re-enter song cinema only if we're in the show.
// RE-ENTRANCY GUARD: exitCinema()/enterCinema() call Reveal.layout(), and in Reveal's
// SCROLL view layout() re-dispatches 'slidechanged' → this very handler → exitCinema →
// layout → … → infinite recursion (RangeError: Maximum call stack size exceeded). The
// flag makes the re-entrant call a no-op, breaking the loop; the layout still completes.
let _cinemaSyncing = false;
function onCinemaSlideChanged() {
  if (_cinemaSyncing) return;
  _cinemaSyncing = true;
  try {
    exitCinema();
    refreshSongCinema();
    // background music lives on the info slides AND the Уроки-медитации slide → pause elsewhere
    const cur = (typeof Reveal !== 'undefined' && Reveal.getCurrentSlide?.()) || null;
    const bgOk = cur && (cur.classList.contains('slide-info') || cur.classList.contains('um-slide'));
    if (!bgOk) pauseBg();
  } finally {
    _cinemaSyncing = false;
  }
}

function enterCinema(el) {
  pauseBg();   // mutual exclusion: no background music while a video/image fills the screen
  document.querySelectorAll('.cinema-fill').forEach(n => { if (n !== el) n.classList.remove('cinema-fill'); });
  el.classList.add('cinema-fill');
  document.body.classList.add('dc-cinema');
  document.getElementById('dc-cinema-ui')?.removeAttribute('hidden');
  if (typeof Reveal !== 'undefined' && Reveal.isReady?.()) Reveal.layout();
}

function exitCinema() {
  const was = document.body.classList.contains('dc-cinema');
  document.querySelectorAll('.cinema-fill').forEach(n => n.classList.remove('cinema-fill'));
  document.body.classList.remove('dc-cinema');
  document.getElementById('dc-cinema-ui')?.setAttribute('hidden', '');
  if (was) ytPlayers.forEach(p => { try { p.pauseVideo?.(); } catch {} });
  // restore Reveal's transform (removed via .dc-cinema) so the deck lays out normally
  if (typeof Reveal !== 'undefined' && Reveal.isReady?.()) Reveal.layout();
}

// Load the YouTube IFrame API once; run queued callbacks when ready.
let _ytLoading = false, _ytReady = false, _ytCbs = [];
function loadYTApi(cb) {
  if (_ytReady) return cb();
  _ytCbs.push(cb);
  if (_ytLoading) return;
  _ytLoading = true;
  const prev = window.onYouTubeIframeAPIReady;
  window.onYouTubeIframeAPIReady = () => {
    try { prev?.(); } catch {}
    _ytReady = true;
    _ytCbs.forEach(c => { try { c(); } catch {} });
    _ytCbs = [];
  };
  const s = document.createElement('script');
  s.src = 'https://www.youtube.com/iframe_api';
  document.head.appendChild(s);
}

// ── Background music: a SMALL real YouTube player (native controls) revealed by the ▶
// button on the info slides. Music is STARTED by a native click on YouTube's own play
// button — YouTube blocks PROGRAMMATIC start for many label tracks, but a native click
// works for ANY track. Once playing, the player is tucked invisible (opacity:0, kept
// in-viewport so audio continues) and the button becomes ⏸. Always mutually exclusive
// with the video/final players (never two sounds at once). ──
let bgPlayer = null;

function setupBgMusic(url) {
  // Build the player from the SAME embed URL the video slide uses. It correctly keeps
  // radio mixes (RD…) and real playlists (PL/UU/OL…) so the queue advances, and drops
  // only private lists (LL/WL). The earlier bespoke parser dropped RD → a radio-mix URL
  // collapsed to its single seed video → "доиграл и встал на паузу". null → no button.
  const embed = youtubeEmbedUrl(url || '');
  if (!embed) return;
  loadYTApi(() => {
    // Small real player, bottom-left, above the ▶ button. Invisible until opened (opacity:0);
    // opacity — NOT display:none — so once started the audio keeps playing while tucked away,
    // and staying in-viewport means no letterbox peek and no OS auto-PiP.
    const host = document.createElement('div');
    host.id = 'dc-bg-music';
    host.style.cssText = 'position:fixed; left:1.5rem; bottom:8.5rem; width:264px; z-index:9999;'
      + ' opacity:0; pointer-events:none; transition:opacity .15s; border-radius:10px;'
      + ' overflow:hidden; background:#000; box-shadow:0 12px 32px rgba(0,0,0,.55);';
    const hint = document.createElement('div');
    hint.style.cssText = 'font:600 11px/1.35 var(--font-body,sans-serif); color:#fff;'
      + ' background:rgba(20,22,31,.96); padding:6px 10px; text-align:center;';
    hint.textContent = 'Нажмите ▶ в плеере, чтобы включить музыку';
    // A real iframe with the embed src (list preserved) — wrapped by YT.Player for
    // control/state, exactly like setupCinema wraps the video slide's iframes.
    const frame = document.createElement('iframe');
    frame.src = embed;
    frame.width = '264'; frame.height = '149';
    frame.setAttribute('allow', 'autoplay; encrypted-media');
    frame.setAttribute('tabindex', '-1');
    frame.style.cssText = 'border:0; display:block;';
    host.appendChild(hint); host.appendChild(frame);
    document.body.appendChild(host);

    try {
      bgPlayer = new YT.Player(frame, {
        events: {
          onStateChange: e => {
            if (e.data === 1) hideBgPlayer();   // PLAYING → tuck away, audio continues
            // ENDED (0): the browser's autoplay policy can block a playlist/radio's OWN
            // auto-advance (it counts as a gestureless play → pause). Force the next
            // track ourselves — allowed because the first native click already
            // "activated" the player, so programmatic advance keeps sound going.
            if (e.data === 0) { try { bgPlayer.nextVideo(); } catch {} }
            syncBgButtons(e.data === 1);
          },
          onError: () => setBgUnavailable(),
        },
      });
    } catch { setBgUnavailable(); }
  });
}

// Reveal / tuck-away the mini-player. Tuck = opacity:0 (NOT display:none, which would
// suspend playback); the player stays in-viewport so the browser keeps the audio going.
function showBgPlayer() { const h = document.getElementById('dc-bg-music'); if (h) { h.style.opacity = '1'; h.style.pointerEvents = 'auto'; } }
function hideBgPlayer() { const h = document.getElementById('dc-bg-music'); if (h) { h.style.opacity = '0'; h.style.pointerEvents = 'none'; } }

function syncBgButtons(playing) {
  document.querySelectorAll('.info-music-btn').forEach(b => {
    b.classList.toggle('playing', playing);
    const ico = b.querySelector('.info-music-ico');
    if (ico) ico.textContent = playing ? '⏸' : '▶';
  });
}

// Player couldn't load (e.g. YouTube blocked without VPN) → button inert, slide fine.
function setBgUnavailable() {
  document.querySelectorAll('.info-music-btn').forEach(b => b.classList.add('unavailable'));
}

function pauseBg() { try { if (bgPlayer && bgPlayer.pauseVideo) bgPlayer.pauseVideo(); } catch {} hideBgPlayer(); }

// Toggle from the info-slide button (global — the button uses inline onclick).
// Playing → pause (API pause is allowed; only programmatic START is blocked) + tuck away.
// Not playing → reveal the mini-player so the presenter clicks YouTube's ▶ (native start).
window.dcToggleBgMusic = () => {
  if (!bgPlayer) return;
  try {
    const playing = bgPlayer.getPlayerState && bgPlayer.getPlayerState() === 1;
    if (playing) {
      bgPlayer.pauseVideo();
      hideBgPlayer();
    } else {
      // mutual exclusion: silence any video/final player before showing the music player
      ytPlayers.forEach(p => { try { if (p.pauseVideo) p.pauseVideo(); } catch {} });
      showBgPlayer();
    }
  } catch {}
};

// ── Wake Lock: keep the screen awake during the show so the display never sleeps
// mid-presentation. The Screen Wake Lock API auto-releases when the tab goes to the
// background (или экран блокируется) → re-acquire on visibilitychange while the show
// is on. Held only during the show (deck fullscreen); released on exit to free the
// lock. No-op where unsupported (older Safari) or blocked → the deck stays intact. ──
let _wakeLock = null;
let _wakeWanted = false;

async function acquireWakeLock() {
  if (!('wakeLock' in navigator)) return;
  if (_wakeLock) return;
  try {
    _wakeLock = await navigator.wakeLock.request('screen');
    // The browser can drop the lock on its own (tab hidden, power event) — clear our
    // handle so a later re-acquire attempt actually re-requests.
    _wakeLock.addEventListener('release', () => { _wakeLock = null; });
  } catch { _wakeLock = null; }   // rejected (no user gesture / blocked) → screen may sleep, deck fine
}

async function releaseWakeLock() {
  const l = _wakeLock; _wakeLock = null;
  try { await l?.release(); } catch {}
}

function setupWakeLock() {
  // Re-acquire when the tab becomes visible again while the show is on (the API drops
  // the lock whenever the document is hidden).
  document.addEventListener('visibilitychange', () => {
    if (_wakeWanted && document.visibilityState === 'visible') acquireWakeLock();
  });
}

// Called from the fullscreenchange handler: show on → hold the lock, show off → drop it.
function setWakeLockForShow(on) {
  _wakeWanted = on;
  if (on) acquireWakeLock(); else releaseWakeLock();
}

// ── Presenter controls: fullscreen (start overlay + corner toggle) + hotkeys help ──
function setupControls() {
  setupWakeLock();
  const fsEl = document.documentElement;
  const isFs = () => !!document.fullscreenElement;
  const enterFs = () => { try { fsEl.requestFullscreen?.(); } catch {} };
  const exitFs  = () => { try { document.exitFullscreen?.(); } catch {} };
  const gotoFirst = () => {
    if (typeof Reveal !== 'undefined' && Reveal.isReady?.()) Reveal.slide(0);
  };

  // Filmstrip visibility: shown in normal mode, hidden in fullscreen, T toggles.
  const strip = document.getElementById('dc-filmstrip');
  let stripVisible = true;
  const applyStrip = () => {
    strip?.classList.toggle('hidden', !stripVisible);
    document.body.classList.toggle('dc-strip-on', stripVisible);
    if (typeof Reveal !== 'undefined' && Reveal.isReady?.()) Reveal.layout();
  };

  // Play = start the show: enter fullscreen + jump to the first slide.
  document.getElementById('dc-play-btn')?.addEventListener('click', () => { enterFs(); gotoFirst(); });

  // Corner fullscreen toggle
  const fsBtn = document.getElementById('dc-fs-btn');
  // "Deck fullscreen" = the whole page (F / corner btn), NOT some iframe's own
  // fullscreen — the strip auto-hide must key off the deck only.
  const isDeckFs = () => document.fullscreenElement === document.documentElement;
  fsBtn?.addEventListener('click', () => { isFs() ? exitFs() : enterFs(); });
  document.addEventListener('fullscreenchange', () => {
    const deckFs = isDeckFs();
    document.body.classList.toggle('dc-fs', deckFs);
    setWakeLockForShow(deckFs);   // keep the screen awake while the show is fullscreen
    if (fsBtn) fsBtn.textContent = document.fullscreenElement ? '🗕' : '⛶';
    // hide strip on entering deck fullscreen, restore on exit; applyStrip() also
    // re-runs Reveal.layout() → fixes any scale drift after a fullscreen episode
    stripVisible = !deckFs;
    applyStrip();
    // entering the show fills the current image song; leaving it re-frames the song
    refreshSongCinema();
  });

  // Hotkeys help panel
  const help = document.getElementById('dc-help');
  const toggleHelp = (force) => {
    if (!help) return;
    const show = force ?? help.hasAttribute('hidden');
    if (show) help.removeAttribute('hidden'); else help.setAttribute('hidden', '');
  };
  document.getElementById('dc-help-btn')?.addEventListener('click', () => toggleHelp());
  document.getElementById('dc-help-close')?.addEventListener('click', () => toggleHelp(false));
  help?.addEventListener('click', e => { if (e.target === help) toggleHelp(false); });

  // Keyboard: "?" help · T filmstrip toggle · Esc closes help first (before overview).
  // T uses e.code (physical key) → works on any layout (incl. ЙЦУКЕН).
  document.addEventListener('keydown', e => {
    if (e.key === '?') { toggleHelp(); e.preventDefault(); }
    else if (e.code === 'KeyT' && !e.metaKey && !e.ctrlKey && !e.altKey) {
      stripVisible = !stripVisible; applyStrip(); e.preventDefault();
    }
    else if (e.code === 'KeyF' && !e.metaKey && !e.ctrlKey && !e.altKey) {
      isFs() ? exitFs() : enterFs(); e.preventDefault();   // F toggles fullscreen (enter AND exit)
    }
    else if (e.code === 'KeyM' && !e.metaKey && !e.ctrlKey && !e.altKey) {
      window.dcToggleBgMusic && window.dcToggleBgMusic(); e.preventDefault();   // M → фоновая музыка
    }
    else if (e.key === 'Escape' && help && !help.hasAttribute('hidden')) {
      toggleHelp(false); e.preventDefault(); e.stopImmediatePropagation();
    }
    else if (e.key === 'Escape' && document.body.classList.contains('dc-cinema')) {
      exitCinema(); e.preventDefault(); e.stopImmediatePropagation();
    }
  }, true);

  // Video/music YouTube iframes steal arrow keys once the player is focused (the
  // keydown fires inside the cross-origin iframe, so Reveal never sees it). Any
  // click OFF the player blurs the iframe → focus returns to the page → arrows work
  // again. Clicks ON the iframe (to play/pause) are left untouched. Blur never
  // stops playback. Capture phase so it runs before the nav buttons' own handlers.
  document.addEventListener('click', e => {
    if (e.target.tagName === 'IFRAME') return;
    const a = document.activeElement;
    if (a && a.tagName === 'IFRAME') a.blur();
  }, true);

  // Belt-and-suspenders: the instant a YouTube iframe grabs focus (e.g. the play
  // click), hand focus straight back to the page so arrow keys keep reaching
  // Reveal. Playback keeps going; clicking the player still plays/pauses.
  document.addEventListener('focusin', e => {
    if (e.target.tagName === 'IFRAME') setTimeout(() => { try { e.target.blur(); } catch {} }, 0);
  });

  // A one-shot blur isn't enough: YouTube re-grabs focus INTERNALLY after playback
  // starts (no new focusin fires), so keydowns then happen inside the cross-origin
  // iframe and never reach the deck — T / Esc / ‹ › stop working. While a video is in
  // cinema, poll and keep focus on the page. Player clicks still register (before the
  // blur), and disablekb=1 means the player ignores the keyboard anyway.
  setInterval(() => {
    if (!document.body.classList.contains('dc-cinema')) return;
    const a = document.activeElement;
    if (a && a.tagName === 'IFRAME') { try { a.blur(); } catch {} }
  }, 300);

  // Auto-hide controls + cursor when the mouse sits still (effect gated to the show
  // via CSS body.dc-fs.dc-idle). Any activity brings them back and restarts the timer.
  let idleTimer = null;
  const IDLE_MS = 2500;
  const markActive = () => {
    document.body.classList.remove('dc-idle');
    clearTimeout(idleTimer);
    idleTimer = setTimeout(() => document.body.classList.add('dc-idle'), IDLE_MS);
  };
  ['mousemove', 'mousedown', 'touchstart', 'keydown', 'wheel'].forEach(ev =>
    document.addEventListener(ev, markActive, { passive: true }));
  markActive();

  applyStrip();   // normal mode on load → strip visible, deck shrinks above it
}

buildSlides();
