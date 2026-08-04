import { youtubeEmbedUrl } from './video.js';

// Returns null when final_music_url is absent or unresolvable — boot.js skips the slide.
export function musicSlide(effective) {
  const url = effective.final_music_url;
  if (!url) return null;

  const embed = youtubeEmbedUrl(url);
  if (!embed) return null;

  const href = url.replace(/"/g, '%22');
  return `<section class="dc-slide slide-music">
  <div class="dc-label">Финальная музыка</div>
  <iframe src="${embed}" allow="autoplay; fullscreen" allowfullscreen></iframe>
  <a class="video-fallback" href="${href}" target="_blank" rel="noopener">▶ Открыть на YouTube ↗</a>
</section>`;
}
