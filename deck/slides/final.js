function youtubeEmbedUrl(url) {
  try {
    const u = new URL(url);
    let id = u.searchParams.get('v');
    if (!id && u.hostname === 'youtu.be') id = u.pathname.slice(1);
    if (!id) return null;
    return `https://www.youtube.com/embed/${id}`;
  } catch {
    return null;
  }
}

export function finalSlide(effective) {
  const { raised, plan, final_music_url } = effective;

  let progressHtml = '';
  if (plan && plan > 0 && raised !== null) {
    const pct = Math.min(100, Math.round((raised / plan) * 100));
    progressHtml = `
  <div class="progress-bar-wrap"><div class="progress-bar-fill" style="width:${pct}%"></div></div>
  <div class="progress-label">Собрали ${raised.toLocaleString('ru-RU')} из ${plan.toLocaleString('ru-RU')} ₽ (${pct}%)</div>`;
  }

  let musicHtml = '';
  if (final_music_url) {
    const embed = youtubeEmbedUrl(final_music_url);
    if (embed) {
      musicHtml = `<iframe src="${embed}" style="width:100%;aspect-ratio:16/9;border:none;border-radius:4px;margin-top:1rem" allowfullscreen></iframe>`;
    }
  }

  return `<section>
  <div class="dc-label">Финал</div>
  <div class="final-thanks">Наама Намами 🙏</div>
  ${progressHtml}
  ${musicHtml}
</section>`;
}
