export function newsSlide(effective) {
  const news = effective.news;

  if (!news || news.length === 0) {
    return `<section>
  <div class="dc-label">Новости</div>
  <p class="dc-stub">Нет событий</p>
</section>`;
  }

  const items = news.map(n => `<li>${n}</li>`).join('');

  return `<section>
  <div class="dc-label">Новости</div>
  <ul class="news-list">${items}</ul>
</section>`;
}
