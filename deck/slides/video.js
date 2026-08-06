export function youtubeEmbedUrl(url) {
  try {
    const u = new URL(url);
    let id = u.searchParams.get('v');
    if (!id && u.hostname === 'youtu.be') id = u.pathname.slice(1);
    // Pass the playlist/mix through so it plays in order. Only PRIVATE lists can't be
    // embedded — Liked (LL…) and Watch-Later (WL…) → drop those and play the seed video.
    // Radio/mix (RD…) and curated playlists (PL…, UU…, OL…) embed fine in an iframe.
    const rawList = u.searchParams.get('list');
    const list = rawList && !/^(LL|WL)/.test(rawList) ? rawList : null;
    if (!id && !list) return null;
    // fs=0        → hide the player's fullscreen button (its own fullscreen is a
    //               cross-origin trap: it swallows the keyboard and the deck can't
    //               regain control until it's exited). Big video = cinema mode below.
    // disablekb=1 → the focused player ignores arrow keys (no accidental seeking).
    // playsinline=1 → never take over the screen on iOS.
    // enablejsapi=1 → boot.js drives cinema mode off the player's play/pause events.
    const p = new URLSearchParams({ rel: '0', fs: '0', disablekb: '1', playsinline: '1', enablejsapi: '1' });
    // pass the playlist through so it plays in order; a bare playlist (no seed video)
    // uses the videoseries endpoint.
    if (list) {
      p.set('list', list);
      const idx = u.searchParams.get('index');
      if (idx) p.set('index', idx);
    }
    return `https://www.youtube.com/embed/${id || 'videoseries'}?${p.toString()}`;
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
  // tabindex=-1 → the iframe never grabs focus by tabbing; edge arrows navigate
  // by mouse (the iframe can't swallow parent clicks). See boot.js blur-on-click.
  return `<section class="dc-slide slide-video">
  <div class="dc-label">Видео</div>
  <iframe id="yt-frame-video" class="yt-embed" src="${embed}" allow="autoplay; encrypted-media" tabindex="-1"></iframe>
  <a class="video-fallback" href="${href}" target="_blank" rel="noopener">▶ Открыть видео на YouTube ↗</a>
  <button class="slide-nav slide-nav-prev" onclick="Reveal.prev()" aria-label="Предыдущий слайд" tabindex="-1">‹</button>
  <button class="slide-nav slide-nav-next" onclick="Reveal.next()" aria-label="Следующий слайд" tabindex="-1">›</button>
</section>`;
}
