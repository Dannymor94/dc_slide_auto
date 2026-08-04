export function programSlide(effective) {
  const items = effective.program;

  if (!items || items.length === 0) {
    return `<section>
  <div class="dc-label">Программа</div>
  <p class="dc-stub">Программа не задана</p>
</section>`;
  }

  const rows = items.map(item => `
  <div class="program-item">
    <div class="time">${item.time}</div>
    <div class="title">${item.title}</div>
    ${item.note ? `<div class="note">${item.note}</div>` : ''}
  </div>`).join('');

  return `<section>
  <div class="dc-label">Программа</div>
  ${rows}
</section>`;
}
