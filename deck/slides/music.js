import { youtubeEmbedUrl } from './video.js';

// Returns null when final_music_url is absent or unresolvable — boot.js skips the slide.
export function musicSlide(effective) {
  const url = effective.final_music_url;
  if (!url) return null;

  const embed = youtubeEmbedUrl(url);
  if (!embed) return null;

  const href = url.replace(/"/g, '%22');
  // same iframe-focus fix as the video slide: no tab-focus + edge nav arrows
  return `<section class="dc-slide slide-music">
  <div class="dc-label">Финальная музыка</div>
  <iframe id="yt-frame-music" class="yt-embed" src="${embed}" allow="autoplay; encrypted-media" tabindex="-1"></iframe>
  <a class="video-fallback" href="${href}" target="_blank" rel="noopener">▶ Открыть на YouTube ↗</a>
  <button class="slide-nav slide-nav-prev" onclick="Reveal.prev()" aria-label="Предыдущий слайд" tabindex="-1">‹</button>
  <button class="slide-nav slide-nav-next" onclick="Reveal.next()" aria-label="Следующий слайд" tabindex="-1">›</button>
</section>`;
}
