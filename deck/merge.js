const MORNING_CUTOFF_HOUR = 12;
const JHA_THRESHOLD = 0.5;  // raised/plan ratio: below → poor, at or above → rich

export const DEFAULT_DADA = 'Наш Дада даст комментарий позже.';

const GREETING_MORNING = 'Пожалуйста, соблюдайте <span class="maunavrata">маунаврату</span> до начала ДЧ';

// Bubble text constants — swap source here when wiring form/percent logic
const JHA_BUBBLE_POOR = 'Поддержите джа!';
const JHA_BUBBLE_RICH = 'Вы красавчики!';

export function buildEffective(manifest, selection, catalog, songImages = {}) {
  const ov = selection?.overrides ?? {};

  // boundary marker lives in a separate field (overrides.practice_end = "HH:MM"),
  // overlaid onto the active program so it survives manifest rebuilds & never freezes it
  const practice_end = ov.practice_end ?? null;
  const program = (ov.program ?? manifest.program ?? []).map(p => ({
    ...p, is_practice_end: !!practice_end && p.time === practice_end,
  }));
  const news = [...(ov.news ?? manifest.news ?? []), ...(ov.news_manual ?? [])];
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

  // resolve songs: image takes priority over catalog text
  //   image exists → { image_path }; else catalog text → stanzas; else stub
  const song_numbers = selection?.song_numbers ?? [];
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
  };
}
