export function songSlide(song, theme) {
  // 1. image-backed song → full-slide picture on a dark letterbox.
  //    onerror removes the <img> and the fallback caption shows through.
  if (song.image_path) {
    return `<section class="dc-slide slide-song-image">
  <div class="song-image-fallback">№${song.number} — изображение недоступно</div>
  <img src="${song.image_path}" alt="Прабхат Самгита №${song.number}" onerror="this.remove()">
</section>`;
  }

  const stanzas = song.stanzas ?? [];

  // 2. neither image nor text → stub
  if (song._stub || stanzas.length === 0) {
    return `<section class="dc-slide slide-song">
  <div class="song-header">
    <div class="song-number">Прабхат Самгита</div>
    <h2 class="song-title dc-stub">№${song.number} нет в каталоге</h2>
  </div>
</section>`;
  }

  // background: background_ref present → CSS var placeholder (ассет M1/M4)
  // file not exist yet → fall back to theme.song_background (also placeholder)
  const bgStyle = song.background_ref
    ? `style="background-image: url('assets/backgrounds/${song.background_ref}.jpg')"`
    : (theme?.song_background ? `style="background-image: url('${theme.song_background}')"` : '');

  const subtitle = song.subtitle
    ? `<div class="song-subtitle">${song.subtitle}</div>`
    : '';

  // 3. text song → two columns: left = translit, right = translation, aligned by stanza
  const leftLines = stanzas.map(st =>
    `<div class="stanza">${st.translit.map(l => `<div class="stanza-line translit">${l}</div>`).join('')}</div>`
  ).join('');
  const rightLines = stanzas.map(st =>
    `<div class="stanza">${st.translation.map(l => `<div class="stanza-line transl">${l}</div>`).join('')}</div>`
  ).join('');

  const footnote = song.footnote
    ? `<div class="song-footnote">${song.footnote}</div>`
    : '';

  return `<section class="dc-slide slide-song" ${bgStyle}>
  <div class="song-header">
    <div class="song-number">Прабхат Самгита № ${song.number}</div>
    <h2 class="song-title">${song.title_translit}</h2>
    ${subtitle}
  </div>
  <div class="song-body">
    <div class="song-col">
      <div class="song-col-label">Транслит</div>
      ${leftLines}
    </div>
    <div class="song-col">
      <div class="song-col-label">Перевод</div>
      ${rightLines}
    </div>
  </div>
  ${footnote}
</section>`;
}
