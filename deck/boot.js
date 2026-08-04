import { buildEffective } from './merge.js';
import { infoSlide } from './slides/info.js';
import { songSlide } from './slides/song.js';
import { videoSlide, youtubeEmbedUrl } from './slides/video.js';
import { dadaSlide } from './slides/dada.js';
import { musicSlide } from './slides/music.js';

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

  const container = document.getElementById('dc-slides');
  container.innerHTML = sections.join('\n');

  if (typeof Reveal !== 'undefined') {
    Reveal.initialize({ hash: true, transition: 'fade', controls: false, progress: false });
  } else {
    document.querySelector('script[src*="reveal.js"]')?.addEventListener('load', () => {
      Reveal.initialize({ hash: true, transition: 'fade', controls: false, progress: false });
    });
  }
}

buildSlides();
