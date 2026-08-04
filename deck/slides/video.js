export function youtubeEmbedUrl(url) {
  try {
    const u = new URL(url);
    let id = u.searchParams.get('v');
    if (!id && u.hostname === 'youtu.be') id = u.pathname.slice(1);
    return id ? `https://www.youtube.com/embed/${id}?rel=0` : null;
  } catch {
    return null;
  }
}

export function videoSlide(effective) {
  const url = effective.video_url;
  if (!url) {
    return `<section class="dc-slide slide-video">
  <div class="dc-label">Видео</div>
  <p class="dc-stub">Видео сегодня нет</p>
</section>`;
  }
  const embed = youtubeEmbedUrl(url);
  if (!embed) {
    return `<section class="dc-slide slide-video">
  <div class="dc-label">Видео</div>
  <p class="dc-stub">Видео сегодня нет</p>
</section>`;
  }
  // Fallback link: some videos refuse to embed (owner-disabled, age-gated,
  // region-blocked, or a transient YouTube error). The link lets the human
  // open the original in a new tab instead of being stuck on the error frame.
  const href = url.replace(/"/g, '%22');
  return `<section class="dc-slide slide-video">
  <div class="dc-label">Видео</div>
  <iframe src="${embed}" allow="autoplay; fullscreen" allowfullscreen></iframe>
  <a class="video-fallback" href="${href}" target="_blank" rel="noopener">▶ Открыть видео на YouTube ↗</a>
</section>`;
}
