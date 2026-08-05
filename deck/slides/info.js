function programItems(items) {
  if (!items || items.length === 0) return '<p class="dc-stub">Программа не задана</p>';
  return items.map(p => `
    <div class="program-item">
      <span class="time">${p.time}</span>
      <span class="prog-title">${p.title}</span>
      ${p.note ? `<div class="prog-note">${p.note}</div>` : ''}
    </div>`).join('');
}

function newsList(news) {
  if (!news || news.length === 0) {
    return '<p class="news-panel-empty">Нет событий</p>';
  }
  return `<ul class="news-panel-list">${news.map(n => `<li>${n}</li>`).join('')}</ul>`;
}

// Accent block for hand-picked important news. No caption — just a visually
// distinct block. Empty → returns '' so the slot stays empty (no block).
function featuredBlock(items) {
  if (!items || items.length === 0) return '';
  const lis = items.map(t =>
    `<li><span class="featured-icon">⚡</span><span>${t}</span></li>`).join('');
  return `<div class="info-featured-panel"><ul class="featured-list">${lis}</ul></div>`;
}

function progressPanel(raised, plan) {
  if (!plan || plan <= 0) return '';
  const pct = Math.min(100, Math.round((raised ?? 0) / plan * 100));
  const raisedFmt = (raised ?? 0).toLocaleString('ru-RU');
  const planFmt = plan.toLocaleString('ru-RU');
  return `
  <div class="info-panel info-progress-panel">
    <div class="progress-top-row">
      <span>Собрали</span><span>План</span>
    </div>
    <div class="progress-amounts">
      <span class="progress-raised">${raisedFmt}</span>
      <span class="progress-plan">из ${planFmt} ₽</span>
    </div>
    <div class="progress-track">
      <div class="progress-fill" style="width:${pct}%"></div>
    </div>
    <div class="progress-pct">${pct} %</div>
  </div>`;
}

export function infoSlide(effective, mode) {
  const isOpening = mode === 'opening';

  // Greeting panel (grid row 1 of info-left)
  const subline = isOpening
    ? (effective.greeting ? `<div class="greeting-sub">${effective.greeting}</div>` : '')
    : '<div class="greeting-sub">Благодарим за коллективную практику</div>';
  const greetingPanel = `
    <div class="info-panel info-greeting-panel">
      <div class="greeting-main">Намаскар!</div>
      ${subline}
    </div>`;

  // Program label (grid row 2) + items (grid row 3 = 1fr) — separate grid children
  // so label never shrinks and items fill remaining height independently
  const programLabel = isOpening ? 'Программа на сегодня:' : 'Далее в программе:';
  const items = isOpening ? effective.program : effective.continuation_program;

  // Footer bar (grid row 4)
  const footerText = isOpening
    ? 'Пожалуйста, выключите таймеры и звуковые сигналы на смартфонах'
    : 'Благодарим, что соблюдали тишину';
  const footerCls = isOpening ? 'footer-opening' : 'footer-continuation';
  const footerIcon = isOpening ? '📵' : '🙏';
  const footerBar = `
    <div class="info-footer-bar ${footerCls}">
      <span class="footer-icon">${footerIcon}</span>${footerText}
    </div>`;

  // Left column: 5-row grid (row 5 = progress, collapses to 0 when absent)
  const left = `
    <div class="info-left">
      ${greetingPanel}
      <div class="info-program-label">${programLabel}</div>
      <div class="info-program-items">${programItems(items)}</div>
      ${footerBar}
      ${progressPanel(effective.raised, effective.plan)}
    </div>`;

  // Right column: news panel (row 1) + jha zone (row 2)
  const newsPanel = `
    <div class="info-news-panel">
      <div class="news-panel-title">Новости Юнита</div>
      <div class="news-panel-subtitle">Планируйте участие в событиях</div>
      ${newsList(effective.news)}
    </div>`;

  // bottom zone: character (left, bottom-pinned) with a comic speech bubble
  // floating over its head + QR square at bottom-right. Whole zone max 50%.
  const bottom = `
    <div class="info-bottom">
      <div class="jha-cell">
        <img src="${effective.jha_image}" alt="">
        <div class="jha-bubble">${effective.jha_bubble_text}</div>
      </div>
      <div class="qr-wrap">
        <img class="qr-image" src="assets/qr-code.svg" alt="QR"
             onerror="this.style.visibility='hidden'">
      </div>
    </div>`;

  // right column: news panel → featured accent block (fills the gap) → jha/QR zone
  const featured = featuredBlock(effective.featured_news);
  const right = `<div class="info-right">${newsPanel}${featured}${bottom}</div>`;

  return `<section class="dc-slide slide-info">${left}${right}</section>`;
}
