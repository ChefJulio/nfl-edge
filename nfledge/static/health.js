// One reading of a player's injury status for every page (owner 2026-10-22 audit: "identify and consolidate any
// systems that could be combined ... less surface for bugs"). The rankings chip, the card's status pill and Health tile,
// the Injuries page, team pages, game pages and the fantasy tab all used to read the status text their own way (seven
// parsers, four sets of thresholds): a player could be "Out" in the pill, Q in the badge and "Healthy" in the tile.
// Pure functions over the week data's player entry (report.week_data: status, tag, src, days, gd, inactive) and
// ros.json rows; no DOM. UMD: NFLE.health in the browser, module.exports in Node (tools/health_check.mjs).
(function (root, factory) {
  const H = factory();
  if (typeof module === 'object' && module.exports) module.exports = H;
  else { root.NFLE = root.NFLE || {}; root.NFLE.health = H; }
})(typeof self !== 'undefined' ? self : this, () => {
  // Thresholds on his chance to play, one table; each consumer names the line it means.
  const AVAIL = {
    SURE: 0.985,    // at or over: shown as 99% / >99%, listed but all but certain (the Injuries page hides them)
    CONCERN: 0.95,  // under: an injury concern (the Health tile gives a chance, the rankings a chip)
    OK: 0.85,       // at or over: probably playing (the Injuries page's "Probably playing"; no warning color)
    EVEN: 0.5,      // under: more likely to sit than play (red); at or over in a later week: "back"
    OUT: 0.15,      // under: the Injuries page's "Expected out"
    ZERO: 0.1,      // under: the rankings project him 0 (owner 2026-10-16: "under 10% to play")
    NIL: 0.01,      // under: the Health tile says "Out" rather than a percentage
  };
  const level = play => (play == null ? '' : play < AVAIL.EVEN ? 'bad' : play < AVAIL.OK ? 'warn' : 'ok');

  // ---- the official tag ----
  const RESERVE = ['IR', 'PUP', 'NFI', 'SSPD'];
  const OFFICIAL = new Set(['Q', 'D', 'O', ...RESERVE]), FIRM = new Set(['O', ...RESERVE]);
  const TAG_WORD = { Q: 'Questionable', D: 'Doubtful', O: 'Out', IR: 'Injured reserve', PUP: 'Physically unable to perform',
    NFI: 'Non-football injury list', SSPD: 'Suspended' };
  // a status text's leading designation as a code (pages built before the structured fields, 2026-10-22, and the
  // return model's lookahead labels): Q / D / O / IR / PUP / NFI / SSPD / INA / ACT, else ''
  const code = st => {
    const t = String(st || '').trim();
    return /^(ir\b|injured reserve)/i.test(t) ? 'IR' : /^(susp|sspd)/i.test(t) ? 'SSPD' : /^(pup|physically)/i.test(t) ? 'PUP'
      : /^(nfi|non-football)/i.test(t) ? 'NFI' : /^inactive/i.test(t) ? 'INA' : /^active/i.test(t) ? 'ACT' : /^out/i.test(t) ? 'O'
      : /^doubt/i.test(t) ? 'D' : /^question/i.test(t) ? 'Q' : '';
  };
  // The tag (owner 2026-10-21: "we should use the official tags"): his entry's own (InjuryModel.designations), else the
  // week's map of every rostered player (tags), else the status text's official code; Q while hurt in this week's game
  // and not back (hurt), unless a firmer tag stands.
  const tag = (P, pid, tags, hurt) => {
    let t;
    if (P && P.tag != null) t = P.tag;
    else if (pid && tags) t = tags[pid] || '';
    else { const c = code(String((P && P.status) || '').split('(')[0]); t = c === 'INA' ? 'O' : OFFICIAL.has(c) ? c : ''; }
    return hurt && !FIRM.has(t) ? 'Q' : t;
  };
  // game day, once his team's actives / inactives are out: 'INA' / 'ACT' (a listed player who dressed) / ''
  const gameday = P => (!P ? '' : P.gd != null ? P.gd : (c => (c === 'INA' || c === 'ACT' ? c : ''))(code(P.status)));
  // on the injury report, or anything injury-related spoke (InjuryModel.status_label is '' only when nothing did): a
  // midweek DNP with no game status yet ("(D)") counts (2026-10-22: the Injuries page left those off)
  const listed = P => !!P && (!!String(P.status || '').trim() || !!P.tag);
  // his practice letters this week ("DLF"): the week data's days; pages before it, the status's trailing "(...)"
  const days = P => (!P ? '' : typeof P.days === 'string' ? P.days : (String(P.status || '').match(/\(([DLF-]{1,4})\)\s*$/) || [])[1] || '');
  // the status without its practice letters ("Questionable (ESPN)", "Hurt last game")
  const label = P => {
    const st = String((P && P.status) || '').trim(), d = days(P);
    return (d && st.endsWith(`(${d})`) ? st.slice(0, -(d.length + 2)) : st).trim();
  };

  // The card's status pill for the week: the official tag and game day, the same as the badge (2026-10-22: the pill
  // read the status text, so ESPN's "Out" showed an Out pill beside a Q badge). [kind, text, tip] or null.
  const pill = (P, t, week) => {
    const gd = gameday(P), why = (P && P.inactive_why) || '';
    return gd === 'INA' ? ['out', 'Inactive', `Declared inactive for week ${week}`]
      : t === 'IR' ? ['out', 'Injured reserve', 'On injured reserve'] : t === 'PUP' || t === 'NFI' ? ['out', t, TAG_WORD[t]]
      : t === 'SSPD' ? ['out', 'Suspended', TAG_WORD.SSPD] : t === 'O' ? ['out', 'Out', why || 'Out']
      : t === 'D' ? ['d', 'Doubtful', why] : t === 'Q' ? ['q', 'Questionable', why]
      : gd === 'ACT' ? ['act', 'Active', `Was questionable; declared active for week ${week}`] : null;
  };

  // ---- later weeks (ros.json: players[pid].w = [[week, takes the field, ..., injury only], ...]) ----
  // his injury-only chance in a ros.json week row: [6] (2026-10-22); older files only have [1], which also carries the
  // healthy-scratch risk and the backup-QB rule (a healthy backup QB read "not back this season")
  const rosChance = z => (z[6] != null ? z[6] : z[1]);
  // the first week our return model gives him at least an even chance: that week; 0 = not this season; null = no row,
  // or no injury on record (every week 99.5%+: e.g. hurt before his bye, before any report lists him)
  const back = row => {
    if (!row || !row.w.some(z => rosChance(z) < 0.995)) return null;
    const e = row.w.find(z => rosChance(z) >= AVAIL.EVEN);
    return e ? e[0] : 0;
  };

  return { AVAIL, level, RESERVE, OFFICIAL, FIRM, TAG_WORD, code, tag, gameday, listed, days, label, pill, rosChance, back };
});
