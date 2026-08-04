const GREETING_MORNING = `Наута мауна врата экадашӣ!\nДобро пожаловать на Дхармачакру.`;
const GREETING_DAY = `Добро пожаловать на Дхармачакру.`;

export function welcomeSlide(effective) {
  const greeting = effective.is_morning ? GREETING_MORNING : GREETING_DAY;
  const dateStr = effective.date
    ? new Date(effective.date + 'T00:00:00').toLocaleDateString('ru-RU', { day: 'numeric', month: 'long', year: 'numeric' })
    : '';

  return `<section class="slide-welcome">
  <div class="greeting">${greeting.replace(/\n/g, '<br>')}</div>
  ${dateStr ? `<div class="date-line">${dateStr}</div>` : ''}
</section>`;
}
