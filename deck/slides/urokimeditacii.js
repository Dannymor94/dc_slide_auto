// Optional "Уроки медитации" welcome slide — appended LAST, only on Sunday-КМ
// weeks (see build/urokimeditacii.py). Renders from manifest.urokimeditacii.
//
// Layout v11: two columns.
//   LEFT (39%)  — Намаскар + greeting + [meeting schedule, if any] + donate (QR).
//   RIGHT (61%) — month calendar (weekday row + grid, no legend, no highlight accent).
//   BOTTOM      — closing wisdom, centered.
//
// HARD REQUIREMENT: every style is scoped under `.um-slide` so the LIGHT palette
// never leaks into the dark deck. Container beats the dark base rule by
// specificity (`.reveal .slides section.um-slide`) + `display:flex !important`
// (Reveal stamps inline display on the active section).
//
// Empty fields are not drawn: meeting=null → no schedule card; wisdom=null → no
// wisdom row. highlight_day stays in the data but is NOT accented here (v11).

const _WD = ['пн', 'вт', 'ср', 'чт', 'пт', 'сб', 'вс'];

function _esc(s) {
  return String(s ?? '').replace(/[&<>"]/g, c =>
    ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
}

// Mon-start month grid; adjacent-month days are muted fillers.
function _cells(year, monthIdx, daysWithEvents) {
  const first = new Date(year, monthIdx, 1);
  const lead = (first.getDay() + 6) % 7;                 // Mon=0 … Sun=6
  const daysInMonth = new Date(year, monthIdx + 1, 0).getDate();
  const daysPrev = new Date(year, monthIdx, 0).getDate();
  const cells = [];
  for (let i = lead - 1; i >= 0; i--) cells.push({ num: daysPrev - i, adj: true });
  for (let d = 1; d <= daysInMonth; d++) cells.push({ num: d, adj: false, ev: daysWithEvents[d] || null });
  let next = 1;
  while (cells.length % 7 !== 0) cells.push({ num: next++, adj: true });
  return cells;
}

// Render-side abbreviations for narrow calendar cells. The manifest data is
// unchanged (v13 is render-only) — long event names are shortened only for display.
const _ABBR = [
  [/чтение пьес[а-яё]*( по ролям)?/gi, 'пьеса'],
  [/км с дадой[а-яё ]*/gi, 'КМ с Дадой'],
  [/книжный клуб/gi, 'книжный'],
  [/день открытых дверей/gi, 'ДОД'],
  [/садхана шивир/gi, 'СШ'],
  [/южный семинар/gi, 'семинар'],
  [/киноклуб/gi, 'кино'],
  [/коллективная медитац[а-яё]*/gi, 'КМ'],
  [/асана-класс/gi, 'Асаны'],
];
function _short(s) {
  let out = String(s ?? '');
  for (const [re, rep] of _ABBR) out = out.replace(re, rep);
  return out;
}

function _cellHtml(c) {
  if (c.adj) return `<div class="um-day um-adj"><span class="um-daynum">${c.num}</span></div>`;
  const kind = c.ev ? (c.ev.kind || 'other') : 'none';
  const label = c.ev ? `<span class="um-daylabel">${_esc(_short(c.ev.label))}</span>` : '';
  return `<div class="um-day um-k-${_esc(kind)}"><span class="um-daynum">${c.num}</span>${label}</div>`;
}

function _meetingHtml(meeting) {
  if (!meeting || !Array.isArray(meeting.items) || !meeting.items.length) return '';
  // items arrive time-sorted from the build; КМ is marked by accent (dot + weight),
  // not by position. Thin date caption above the rows (not a header pill).
  const date = meeting.date_label ? `<div class="um-mdate">${_esc(meeting.date_label)}</div>` : '';
  const rows = meeting.items.map(it => {
    const km = it.km ? ' um-km' : '';
    return `<div class="um-mrow"><span class="um-mtime${km}">${_esc(it.time)}</span>` +
           `<span class="um-mdot${km}"></span><span class="um-mname${km}">${_esc(it.name)}</span></div>`;
  }).join('');
  return `<h2 class="um-sr">Расписание встречи</h2><div class="um-meeting">${date}${rows}</div>`;
}

const _STYLE = `<style>
.reveal .slides section.um-slide{
  display:flex !important; flex-direction:column;
  height:100%; box-sizing:border-box; padding:22px 26px;
  background:#F4EEDE; color:#2C2A26; position:relative;   /* anchor the bg-music overlay */
  font-family:var(--font-body, Manrope, sans-serif);
}
.um-slide .um-sr{ position:absolute; width:1px; height:1px; padding:0; margin:-1px; overflow:hidden; clip:rect(0 0 0 0); white-space:nowrap; border:0; }
.um-slide .um-top{ flex:1 1 auto; display:flex; gap:22px; min-height:0; }

/* LEFT column — QR-донат и расписание = главные функциональные зоны (50%) */
/* flex:1 1 0 on BOTH columns → true equal halves that account for the gap
   (flex-basis:50% + gap would overflow the row since shrink is disabled). */
.um-slide .um-left{ flex:1 1 0; display:flex; flex-direction:column; min-width:0; }
.um-slide .um-namaskar{ font-size:36px; font-weight:500; line-height:1.05; color:#2C2A26; }
.um-slide .um-greeting{ font-size:16px; color:#6E675A; margin-top:6px; line-height:1.35; }
.um-slide .um-meeting{ margin-top:22px; background:#EBE4CE; border-radius:12px; padding:18px 22px; display:flex; flex-direction:column; gap:13px; }
.um-slide .um-mdate{ font-size:12px; color:#8A6D3B; margin-bottom:2px; }
.um-slide .um-mrow{ display:flex; align-items:center; gap:12px; font-size:21px; }
.um-slide .um-mtime{ font-variant-numeric:tabular-nums; font-weight:700; color:#5C5546; min-width:62px; }
.um-slide .um-mtime.um-km{ color:#5A4FB0; }
.um-slide .um-mdot{ width:12px; height:12px; border-radius:50%; background:#BCB194; flex:0 0 auto; }
.um-slide .um-mdot.um-km{ background:#8B7FD6; }
.um-slide .um-mname{ color:#2C2A26; line-height:1.25; }
.um-slide .um-mname.um-km{ font-weight:500; }
.um-slide .um-spacer{ flex:1 1 auto; min-height:16px; }
.um-slide .um-donate{ background:#EBE4CE; border-radius:12px; padding:20px 22px; display:flex; align-items:center; gap:20px; }
.um-slide .um-qr{ width:130px; height:130px; flex:0 0 auto; background:#fff; border-radius:10px; padding:9px; box-sizing:border-box; }
.um-slide .um-qr img{ width:100%; height:100%; object-fit:contain; display:block; }
.um-slide .um-donate-title{ font-size:19px; font-weight:700; color:#4A4438; }
.um-slide .um-donate-sub{ font-size:14px; color:#8A8372; margin-top:3px; }
.um-slide .um-donate-chan{ font-size:14px; color:#8A6D3B; font-weight:600; margin-top:3px; }

/* RIGHT column — calendar panel: full-height panel, but the grid itself is
   COMPACT (fixed row height) and centered vertically → quiet field around it,
   not 5 giant empty boxes. */
.um-slide .um-right{ flex:1 1 0; background:#EBE4CE; border-radius:12px; padding:12px 14px; display:flex; flex-direction:column; min-width:0; }
.um-slide .um-month{ align-self:flex-end; font-size:12px; letter-spacing:0.05em; color:#8A6D3B; text-transform:none; margin-bottom:10px; }
.um-slide .um-calbox{ flex:1 1 auto; display:flex; flex-direction:column; justify-content:center; min-height:0; }
.um-slide .um-wdrow{ display:grid; grid-template-columns:repeat(7,1fr); gap:5px; margin-bottom:6px; }
.um-slide .um-wd{ font-size:10px; text-transform:uppercase; letter-spacing:0.06em; color:#8A8372; padding-left:2px; }
.um-slide .um-grid{ display:grid; grid-template-columns:repeat(7,1fr); grid-auto-rows:42px; gap:5px; }
.um-slide .um-day{ border-radius:7px; padding:3px 5px; overflow:hidden; display:flex; flex-direction:column; gap:2px; background:#F4EEDE; }
.um-slide .um-daynum{ font-size:11px; font-weight:700; color:#4A4438; }
.um-slide .um-daylabel{ font-size:9px; line-height:1.12; color:#4A4438; overflow:hidden; }
.um-slide .um-k-km{ background:#C9C0E8; }
.um-slide .um-k-km .um-daynum{ color:#4A3F8C; }
.um-slide .um-k-asana{ background:#F2C79E; }
.um-slide .um-k-asana .um-daynum{ color:#8A5220; }
.um-slide .um-k-fk{ background:#CDE0E8; }
.um-slide .um-k-charity{ background:#E3DCF3; }
.um-slide .um-day.um-adj{ background:transparent; opacity:0.4; }
.um-slide .um-day.um-adj .um-daynum{ color:#8A8372; font-weight:500; }
.um-slide .um-note{ margin-top:10px; align-self:flex-end; font-size:9.5px; color:#A79A7E; text-align:right; }

/* BOTTOM — closing wisdom */
.um-slide .um-wisdom{ flex:0 0 auto; text-align:center; margin-top:14px;
  font-family:Georgia, 'PT Serif', 'Times New Roman', serif;
  font-style:italic; font-size:16px; line-height:1.4; color:#7A5C36; }
</style>`;

export function urokimeditaciiSlide(um, bgMusicUrl) {
  if (!um) return '';
  const chan = um.channel ? `<div class="um-donate-chan">${_esc(um.channel)}</div>` : '';

  const left = `
    <div class="um-left">
      <h2 class="um-sr">Приветствие</h2>
      <div class="um-namaskar">Намаскар</div>
      ${um.greeting ? `<div class="um-greeting">${_esc(um.greeting)}</div>` : ''}
      ${_meetingHtml(um.meeting)}
      <div class="um-spacer"></div>
      <div class="um-donate">
        <div class="um-qr"><img src="assets/qr-code.svg" alt="QR"
             onerror="this.parentNode.style.visibility='hidden'"></div>
        <div class="um-donate-txt">
          <div class="um-donate-title">Поддержать проект</div>
          <div class="um-donate-sub">донат по QR · подписаться</div>
          ${chan}
        </div>
      </div>
    </div>`;

  let cal = '';
  if (um.year && um.month) {
    const evByDay = {};
    (um.calendar || []).forEach(c => { evByDay[c.day] = c; });
    const cells = _cells(um.year, um.month - 1, evByDay);
    const wd = _WD.map(d => `<div class="um-wd">${d}</div>`).join('');
    const grid = cells.map(_cellHtml).join('');
    // compact grid, vertically centered in the full-height panel (um-calbox)
    cal = `<div class="um-calbox"><div class="um-wdrow">${wd}</div><div class="um-grid">${grid}</div></div>`;
  }
  const right = `
    <div class="um-right">
      <h2 class="um-sr">Календарь месяца</h2>
      ${um.month_label ? `<div class="um-month">${_esc(um.month_label)}</div>` : ''}
      ${cal}
      ${um.schedule_note ? `<div class="um-note">${_esc(um.schedule_note)}</div>` : ''}
    </div>`;

  const wisdom = um.wisdom
    ? `<h2 class="um-sr">Пожелание</h2><div class="um-wisdom">${_esc(um.wisdom)}</div>` : '';

  // Same background-music overlay as the info slides (welcome/schedule). Toggles the
  // shared hidden player via the global dcToggleBgMusic; boot.js keeps it playing here
  // (the um-slide is whitelisted alongside .slide-info). Only rendered when a URL is set.
  const music = bgMusicUrl ? `
    <button class="info-music-btn" onclick="window.dcToggleBgMusic&&window.dcToggleBgMusic()"
            tabindex="-1" title="Фоновая музыка" aria-label="Фоновая музыка">
      <span class="info-music-ico">▶</span><span class="info-music-lbl">Музыка</span>
    </button>` : '';

  return `<section class="um-slide">${_STYLE}<div class="um-top">${left}${right}</div>${wisdom}${music}</section>`;
}
