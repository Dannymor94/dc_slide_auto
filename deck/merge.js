const MORNING_CUTOFF_HOUR = 12;
const JHA_THRESHOLD = 0.5;  // raised/plan ratio: below → poor, at or above → rich

// ISO year×week number (e.g. 202633) for a "YYYY-MM-DD" string.
// Used to detect stale selection overrides from a previous ДЧ week.
function _isoWeekYear(dateStr) {
  if (!dateStr) return null;
  const d = new Date(dateStr + 'T12:00:00');
  const day = d.getDay() || 7;           // 1=Mon … 7=Sun
  const thu = new Date(d);
  thu.setDate(d.getDate() + 4 - day);   // nearest Thursday of the ISO week
  const y = thu.getFullYear();
  const jan1 = new Date(y, 0, 1);
  return y * 100 + Math.ceil(((thu - jan1) / 86400000 + 1) / 7);
}

export const DEFAULT_DADA = 'Наш Дада даст комментарий позже.';

const GREETING_MORNING = 'Пожалуйста, соблюдайте <span class="maunavrata">маунаврату</span> до начала ДЧ';

// Bubble text constants — swap source here when wiring form/percent logic
const JHA_BUBBLE_POOR = 'Поддержите джа!';
const JHA_BUBBLE_RICH = 'Вы красавчики!';

// Persistent override keys survive across ДЧ weeks (operator sets them once,
// they stay until explicitly changed). All other override keys are weekly —
// they expire when selection.week_date moves to a different ISO week.
// Add new persistent fields here; omitting a field = it expires (safe default).
const PERSISTENT_OVERRIDE_KEYS = ['featured_news', 'hide_urokimeditacii'];

export function buildEffective(manifest, selection, catalog, songImages = {}) {
  // Stale-override guard: if selection.week_date is from a different ISO week than
  // manifest.date, the operator hasn't opened the form this week yet → expire the
  // weekly overrides so fresh manifest data (news, program, etc.) shows through.
  // Persistent fields are kept as-is. song_numbers/video_url/raised/bg_music_url
  // live at the top level of selection and are never touched by this guard.
  const _overridesStale = !!manifest.date && !!selection?.week_date
    && _isoWeekYear(manifest.date) !== _isoWeekYear(selection.week_date);
  const rawOv = selection?.overrides ?? {};
  const ov = _overridesStale
    ? Object.fromEntries(
        Object.entries(rawOv).filter(([k]) => PERSISTENT_OVERRIDE_KEYS.includes(k))
      )
    : rawOv;
  if (_overridesStale) {
    console.warn('[merge] overrides stale — selection.week_date', selection.week_date,
      '≠ manifest.date', manifest.date,
      '— weekly fields expired, persistent kept:', PERSISTENT_OVERRIDE_KEYS);
  }

  // boundary marker lives in a separate field (overrides.practice_end = "HH:MM"),
  // overlaid onto the active program so it survives manifest rebuilds & never freezes it
  const practice_end = ov.practice_end ?? null;
  const program = (ov.program ?? manifest.program ?? []).map(p => ({
    ...p, is_practice_end: !!practice_end && p.time === practice_end,
  }));
  const today = new Date().toISOString().slice(0, 10);
  const yesterday = new Date(Date.now() - 86400000).toISOString().slice(0, 10);
  // Try to parse a Russian date ("14 ноября") from a bare override string.
  // Used so manually-entered news obeys the same since-filter as manifest items.
  const _RU_MON = ['янв','фев','мар','апр','ма','июн','июл','авг','сен','окт','ноя','дек'];
  function _guessDate(text) {
    const m = text.match(/(\d{1,2})\s+([а-яё]+)/i);
    if (!m) return null;
    const mon = _RU_MON.findIndex(p => m[2].toLowerCase().startsWith(p));
    if (mon < 0) return null;
    const yr = new Date().getFullYear();
    return `${yr}-${String(mon + 1).padStart(2, '0')}-${String(parseInt(m[1])).padStart(2, '0')}`;
  }
  function _newsDate(n) { return typeof n === 'object' ? (n.since ?? null) : _guessDate(n.text ?? n); }
  const manifestNews = (ov.news ?? manifest.news ?? [])
    .filter(n => { const d = _newsDate(n); return !d || d >= yesterday; })
    .map(n => {
      const text = n.text ?? n;
      const since = _newsDate(n);
      return (since && since < today) ? { text, past: true } : text;
    });
  const news = [...manifestNews, ...(ov.news_manual ?? [])];
  // featured_news: manual-only accent block, separate from news / news_manual.
  // Lives in selection.overrides → survives manifest rebuild. Empty → block hidden.
  const featured_news = ov.featured_news ?? [];
  const dada_comment = ov.dada_comment ?? manifest.dada_comment ?? DEFAULT_DADA;
  const final_music_url = manifest.final_music_url ?? null;

  // is_morning: rule on program[0].time МСК
  const start = program[0]?.time ?? '';
  const hour = start ? parseInt(start.split(':')[0], 10) : NaN;
  const is_morning = isNaN(hour) || hour < MORNING_CUTOFF_HOUR;

  // greeting constant chosen by rule
  const greeting = is_morning ? GREETING_MORNING : null;

  // continuation_program: items AFTER the boundary (item whose time == practice_end).
  // No marker / no matching item → endIdx -1 → whole program shown.
  const endIdx = program.findIndex(p => p.is_practice_end);
  const continuation_program = endIdx >= 0 ? program.slice(endIdx + 1) : program;

  // song numbers: suggested_songs from Telegram are primary — when the chat post
  // has songs, they win. Manual selection (operator form) is the fallback when
  // the manifest has no suggestions yet. Never blanks.
  const selSongs = selection?.song_numbers ?? [];
  const suggestedSongs = manifest.suggested_songs ?? [];
  const song_numbers = suggestedSongs.length
    ? suggestedSongs                        // Telegram chat → primary
    : selSongs;                             // manual/fallback, never blank
  const songs = song_numbers.map(n => {
    const image_path = songImages[n] ?? songImages[String(n)];
    if (image_path) return { number: n, image_path };
    const found = catalog.find(s => s.number === n);
    return found ?? { _stub: true, number: n };
  });

  // three-layer: form override → manifest auto (Dada video from СВАДХЬЯЯ) → empty.
  // || (not ??) so an empty form field falls through to the auto-pulled video.
  const video_url = selection?.video_url || manifest.video_url || '';
  const final_video_url = selection?.final_video_url ?? '';
  // sticky background music (from selection) → play/pause button on the info slides
  const bg_music_url = selection?.bg_music_url || '';
  // three-layer: form override → manifest auto (Telegram finance post) → null
  const raised = selection?.raised ?? manifest.raised ?? null;
  const plan = selection?.plan ?? manifest.plan ?? null;

  const date = manifest.date ?? null;

  // optional Уроки-медитации slide: manifest bakes the object only on Sunday-КМ
  // weeks (absent → no slide). Operator toggle hides it: overrides.hide_urokimeditacii.
  const urokimeditacii = manifest.urokimeditacii ?? null;
  const hide_urokimeditacii = !!ov.hide_urokimeditacii;

  // jha character: derived from raised/plan ratio
  const jha_pct = (raised && plan && plan > 0) ? raised / plan : 0;
  const jha_image = jha_pct >= JHA_THRESHOLD ? 'assets/jha_rich.png' : 'assets/jha_poor.png';
  const jha_bubble_text = jha_pct >= JHA_THRESHOLD ? JHA_BUBBLE_RICH : JHA_BUBBLE_POOR;

  return {
    program,
    continuation_program,
    news,
    featured_news,
    dada_comment,
    final_music_url,
    final_video_url,
    bg_music_url,
    songs,
    video_url,
    raised,
    plan,
    is_morning,
    greeting,
    date,
    jha_image,
    jha_bubble_text,
    urokimeditacii,
    hide_urokimeditacii,
  };
}
