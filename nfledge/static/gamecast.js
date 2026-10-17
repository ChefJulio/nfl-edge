// NFL Edge: player cards, live scoring and the gamecast. Shared by every week page and game.html (copied to the
// site root as assets/gamecast.js by report.write_site_assets), so archived pages pick up fixes without a rebuild.
//
// Data: our numbers come from the week's JSON (<page>.json: projections, stat lines, pregame chances, battle bars);
// live scores, plays, box scores and live win probability come from ESPN's public feed (unofficial, CORS-open).
// If ESPN fails, everything here degrades to the static page.
(() => {
  'use strict';
  const CFG = window.NFLE_CFG || {};
  const Q = new URLSearchParams(location.search);
  const SIM = Q.get('sim') === '1';  // test switch: treat finished games as in progress
  // Both on site.web.api: site.api.espn.com's scoreboard drops the CORS header for Chromium browsers.
  const ESPN = {
    sb: 'https://site.web.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard',
    sum: 'https://site.web.api.espn.com/apis/site/v2/sports/football/nfl/summary?event=',
  };
  const DEF_KEYS = ['pass_yd', 'pass_td', 'interception', 'rush_yd', 'rush_td', 'reception', 'rec_yd', 'rec_td', 'fumble_lost'];
  const HALF = { pass_yd: 0.04, pass_td: 4, interception: -2, rush_yd: 0.1, rush_td: 6, reception: 0.5, rec_yd: 0.1,
                 rec_td: 6, fumble_lost: -2, te_bonus: 0 };

  // ---------------------------------------------------------------------------------------------------- helpers
  const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  // a team name / logo that opens its page (owner 2026-10-16: every one on the site, except the logo on a player photo)
  const tmL = (t, html) => t ? `<span class="tm-open" data-tm="${esc(t)}">${html == null ? esc(t) : html}</span>` : (html || '');
  const f1 = v => (v == null || isNaN(v)) ? '' : (Math.round(v * 10) / 10).toFixed(1);
  const f0 = v => (v == null || isNaN(v)) ? '' : String(Math.round(v));
  const pc = v => `${Math.round(v * 100)}%`;
  const ord = n => n ? `${n}${(n % 100 >= 11 && n % 100 <= 13) ? 'th' : ({ 1: 'st', 2: 'nd', 3: 'rd' }[n % 10] || 'th')}` : '';
  const el = (html) => { const t = document.createElement('template'); t.innerHTML = html.trim(); return t.content.firstChild; };
  // Plain GETs only: a cache-mode option makes Chromium add Cache-Control / Pragma request headers, which turns the
  // request into a CORS preflight that ESPN's feed does not answer (WebKit is fine either way). ESPN's own
  // max-age is 1-9 s, so the browser cache never holds live data for long.
  // Injury status as a compact tag: Q / D / O / IR / SSPD / PUP / NFI, the full status (incl. practice days, ESPN or
  // last-week notes) on hover. One look everywhere a status shows (rankings, cards, team pages, gamecast).
  const injCode = st => {
    const t = String(st || '').trim();
    return /^(ir\b|injured reserve)/i.test(t) ? 'IR' : /^(susp|sspd)/i.test(t) ? 'SSPD' : /^(pup|physically)/i.test(t) ? 'PUP'
      : /^(nfi|non-football)/i.test(t) ? 'NFI' : /^out/i.test(t) ? 'O' : /^doubt/i.test(t) ? 'D' : /^question/i.test(t) ? 'Q' : t.split(/\s/)[0].toUpperCase();
  };
  // status = "<game designation> (<practice days>)", e.g. "Questionable (DLF)" or just " (D)" midweek: the designation
  // is a colored tag, each practice day its own chip in the NFL's report terms (FP green, LP amber, DNP red), so a
  // Wednesday DNP never reads as "Doubtful"
  const PRAC = { D: 'Did not practice', L: 'Limited', F: 'Full' }, PRAB = { D: 'DNP', L: 'LP', F: 'FP' }, DAYS = ['Wed', 'Thu', 'Fri'];
  const injTag = st => {
    if (!st) return '';
    const m = String(st).match(/^(.*?)\s*\(([DLF]+)\)\s*$/), des = (m ? m[1] : String(st)).trim(), pr = m ? m[2] : '';
    const c = des ? injCode(des) : '';
    const tag = c ? `<span class="dc-tag dt-${c === 'Q' ? 'q' : c === 'D' ? 'd' : 'out'}" title="${esc(des)}">${esc(c)}</span>` : '';
    const days = pr ? `<span class="pr-days" title="Practice: ${esc([...pr].map((x, i) => `${DAYS[i] || ''} ${PRAC[x]}`).join(', '))}">${[...pr].map(x => `<i class="pr-${x}">${PRAB[x]}</i>`).join('')}</span>` : '';
    return tag + days;
  };
  const getJSON = async (url, ms = 12000) => {
    const c = new AbortController(), t = setTimeout(() => c.abort(), ms);
    try {
      const r = await fetch(url, { signal: c.signal });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      return await r.json();
    } finally { clearTimeout(t); }
  };
  const periodName = p => p >= 5 ? (p === 5 ? 'OT' : `${p - 4}OT`) : `Q${p}`;

  // ------------------------------------------------------------------------------------------------------- data
  let DATA = null;
  const KEYS = () => (DATA && DATA.score && DATA.score.keys) || DEF_KEYS;
  const ourCode = a => {
    const m = {};
    Object.entries((DATA && DATA.espn_team) || { LA: 'LAR', WAS: 'WSH' }).forEach(([k, v]) => { m[v] = k; });
    return m[a] || a;
  };
  const weights = () => {
    if (window.nfleWeights) return window.nfleWeights();
    try { const s = JSON.parse(localStorage.getItem('nfledge-scoring') || 'null'); if (s && s.w) return s.w; } catch (e) { /* default */ }
    return (DATA && DATA.score && DATA.score.presets && DATA.score.presets['Half PPR']) || HALF;
  };
  const pts = (c, w, pos) => c.reduce((t, v, i) => t + (v || 0) * (w[KEYS()[i]] || 0), 0) + (pos === 'TE' ? (c[5] || 0) * (w.te_bonus || 0) : 0);
  // A projection and its range under the viewer's scoring: exact re-score of the stat line, ratio for the rest.
  const scaled = (p, d = DATA) => {
    const w = weights(), built = (d && d.score && d.score.built) || HALF;
    const base = pts(p.sc.pj, built, p.pos), now = pts(p.sc.pj, w, p.pos);
    const r = base > 0.3 ? now / base : 1;
    return { proj: base > 0.3 ? p.proj * r : now, q: p.q.map(v => v * r), ratio: r };
  };
  const byEspn = () => {
    const m = {};
    if (DATA) Object.entries(DATA.players).forEach(([pid, p]) => { if (p.espn) m[p.espn] = pid; });
    return m;
  };
  const teamGame = (team, d = DATA) => d && d.games.find(g => g.away.team === team || g.home.team === team);
  const sideOf = (g, team) => g && (g.away.team === team ? g.away : g.home.team === team ? g.home : null);
  // ESPN's 500 px logos come out ragged when the browser shrinks them; its resizer downsamples them properly
  // (3x the display size, so retina screens stay sharp). Same rule as report.logo_src.
  // ESPN's resizer returns an empty image above ~600 px for some sources (the 4096 px dark Raiders logo): cap it
  const px = size => Math.min(600, Math.max(24, size * 3));
  const logoSrc = (url, size) => /a\.espncdn\.com\/i\/teamlogos\//.test(url)
    ? `https://a.espncdn.com/combiner/i?img=${url.split('a.espncdn.com')[1]}&w=${px(size)}&h=${px(size)}` : url;
  const logo = (url, bg, size = 22, alt = '') => url
    ? `<span class="nl" style="background:${esc(bg || '#333')};width:${size + 6}px;height:${size + 6}px"><img src="${esc(logoSrc(url, size))}" alt="${esc(alt)}" width="${size}" height="${size}" loading="lazy"></span>` : '';

  // ------------------------------------------------------------------------------------------------------- ESPN
  const weekEvents = async (season, week) => {
    const d = await getJSON(`${ESPN.sb}?seasontype=2&week=${week}&dates=${season}`);
    return d.events || [];
  };
  const evKey = ev => ev.competitions[0].competitors.map(t => ourCode(t.team.abbreviation)).sort().join('-');
  const gKey = (a, h) => [a, h].sort().join('-');
  // ESPN's two primaries can be near-identical (SEA / DEN both navy): the home side switches to its alternate color, or
  // either side lightens when both are too dark to read on the dark page (owner 2026-10-15, team stats bars)
  const rgb = h => { const m = String(h || '').replace('#', '').match(/^([0-9a-f]{2})([0-9a-f]{2})([0-9a-f]{2})$/i); return m ? m.slice(1).map(x => parseInt(x, 16)) : null; };
  const cdist = (a, b) => { const x = rgb(a), y = rgb(b); return x && y ? Math.hypot(x[0] - y[0], x[1] - y[1], x[2] - y[2]) : 999; };
  const luma = h => { const c = rgb(h); return c ? 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2] : 128; };
  const distinctColors = info => {
    const a = info.away, h = info.home;
    if (cdist(a.color, h.color) < 90 && h.alt && cdist(a.color, h.alt) >= 90) h.color = h.alt;
    else if (cdist(a.color, h.color) < 90 && a.alt && cdist(a.alt, h.color) >= 90) a.color = a.alt;
    [a, h].forEach(x => { if (luma(x.color) < 40 && x.alt && luma(x.alt) > luma(x.color) && cdist(x.alt, (x === a ? h : a).color) >= 90) x.color = x.alt; });
  };
  const evInfo = ev => {
    const c = ev.competitions[0], st = c.status || ev.status, t = st.type;
    const side = {};
    c.competitors.forEach(x => {
      side[x.homeAway] = { team: ourCode(x.team.abbreviation), espnTeam: x.team.abbreviation, id: x.team.id,
                           score: +x.score || 0, logo: x.team.logo, color: '#' + (x.team.color || '666666'),
                           alt: '#' + (x.team.alternateColor || '999999'), record: (x.records && x.records[0] && x.records[0].summary) || '' };
    });
    let state = t.state;
    if (SIM && state === 'post') state = 'in';
    return { id: ev.id, state, realState: t.state, detail: t.detail, short: t.shortDetail, period: st.period,
             clock: st.displayClock, home: side.home, away: side.away, sit: c.situation || null, date: ev.date };
  };
  // Every player's stat line from a box score, keyed by ESPN athlete id, in the scoring keys' order.
  const boxLines = sum => {
    const out = {};
    ((sum.boxscore && sum.boxscore.players) || []).forEach(tp => {
      const team = ourCode(tp.team.abbreviation);
      (tp.statistics || []).forEach(cat => {
        const ix = k => cat.keys.indexOf(k);
        (cat.athletes || []).forEach(a => {
          const id = a.athlete.id;
          const o = out[id] || (out[id] = { id, name: a.athlete.displayName, short: a.athlete.shortName || a.athlete.displayName,
                                            team, line: KEYS().map(() => 0), tgt: 0, car: 0, att: 0, comp: 0, cats: {} });
          const v = k => { const i = ix(k); return i < 0 ? 0 : (parseFloat(String(a.stats[i]).split('/')[0]) || 0); };
          const K = KEYS(), set = (k, val) => { const i = K.indexOf(k); if (i >= 0) o.line[i] = val; };
          o.cats[cat.name] = a.stats;
          if (cat.name === 'passing') {
            const ca = String(a.stats[ix('completions/passingAttempts')] || '0/0').split('/');
            o.comp = +ca[0] || 0; o.att = +ca[1] || 0;
            set('pass_yd', v('passingYards')); set('pass_td', v('passingTouchdowns')); set('interception', v('interceptions'));
          } else if (cat.name === 'rushing') {
            o.car = v('rushingAttempts'); set('rush_yd', v('rushingYards')); set('rush_td', v('rushingTouchdowns'));
          } else if (cat.name === 'receiving') {
            o.tgt = v('receivingTargets'); set('reception', v('receptions')); set('rec_yd', v('receivingYards')); set('rec_td', v('receivingTouchdowns'));
          } else if (cat.name === 'fumbles') {
            set('fumble_lost', v('fumblesLost'));
          }
        });
      });
    });
    return out;
  };
  const allPlays = sum => {
    const d = sum.drives || {};
    const drives = [...(d.previous || [])];
    if (d.current && !drives.some(x => x.id === d.current.id)) drives.push(d.current);
    return drives;
  };
  const clockSecs = c => {
    if (!c) return null;
    if (c.value != null && !isNaN(+c.value)) return +c.value;
    const m = String(c.displayValue || '').match(/^(\d+):(\d{2})$/);
    return m ? +m[1] * 60 + +m[2] : null;
  };
  const elapsed = p => {
    const per = (p.period && p.period.number) || 1, cs = clockSecs(p.clock), clk = cs == null ? (per <= 4 ? 900 : 600) : cs;
    return per <= 4 ? (per - 1) * 900 + (900 - clk) : 3600 + (per - 5) * 600 + (600 - clk);
  };
  const statLineText = (o, pos) => {
    const bits = [];
    if (o.att) bits.push(`${o.comp}/${o.att}, ${f0(o.line[0])} pass yd${o.line[1] ? `, ${o.line[1]} TD` : ''}${o.line[2] ? `, ${o.line[2]} INT` : ''}`);
    if (o.car) bits.push(`${o.car} car, ${f0(o.line[3])} yd${o.line[4] ? `, ${o.line[4]} TD` : ''}`);
    if (o.tgt || o.line[5]) bits.push(`${f0(o.line[5])}/${f0(o.tgt)} rec/tgt, ${f0(o.line[6])} yd${o.line[7] ? `, ${o.line[7]} TD` : ''}`);
    if (o.line[8]) bits.push(`${o.line[8]} fum lost`);
    return bits.join(' · ') || 'No stats yet';
  };

  // ------------------------------------------------------------------------------------------- field graphic
  // Away team's goal line on the left (it attacks right), home's on the right. Ball position from yards to the
  // end zone when ESPN gives it, else from "LAR 34"-style spot text.
  const spot = (s, info) => {
    if (!s || !info) return null;
    const posTeamId = (s.team && s.team.id) || s.possession;
    const offHome = posTeamId != null && String(posTeamId) === String(info.home.id);
    const offAway = posTeamId != null && String(posTeamId) === String(info.away.id);
    if (!offHome && !offAway) return null;
    const dir = offAway ? 1 : -1;
    let x = null;
    if (s.yardsToEndzone != null) x = offAway ? 100 - s.yardsToEndzone : s.yardsToEndzone;
    else {
      const m = String(s.possessionText || s.downDistanceText || '').match(/([A-Z]{2,3})?\s*(\d{1,2})\s*$/);
      if (m) {
        const n = +m[2], side = m[1] ? ourCode(m[1]) : null;
        x = n === 50 || !side ? 50 : (side === info.home.team ? 100 - n : n);
      }
    }
    if (x == null) return null;
    const goal = /goal/i.test(s.downDistanceText || s.shortDownDistanceText || '');
    const toGo = s.distance && !goal ? Math.min(100, Math.max(0, x + dir * s.distance)) : (dir === 1 ? 100 : 0);
    return { x, dir, toGo, offense: offAway ? info.away : info.home, down: s.down, distance: s.distance,
             text: s.downDistanceText || s.shortDownDistanceText || '', red: s.isRedZone || (dir === 1 ? x >= 80 : x <= 20) };
  };
  const fieldSvg = (sp, info) => {
    const X = y => 10 + y * 1.0;
    let lines = '';
    for (let y = 10; y < 100; y += 10) lines += `<line x1="${X(y)}" y1="1" x2="${X(y)}" y2="19" class="fd-l${y === 50 ? ' mid' : ''}"/>`;
    const ball = sp ? `<line x1="${X(sp.toGo)}" y1="1" x2="${X(sp.toGo)}" y2="19" class="fd-go"/>
      <ellipse cx="${X(sp.x)}" cy="10" rx="2.6" ry="1.8" class="fd-ball"/>
      <path d="M${X(sp.x) + sp.dir * 3.6} 10 l${-sp.dir * 2.2} -2.2 v4.4 z" class="fd-dir"/>` : '';
    return `<svg class="fd" viewBox="0 0 120 20" preserveAspectRatio="none" aria-hidden="true">
      <rect x="0" y="0" width="120" height="20" class="fd-turf"/>
      ${sp && sp.red ? `<rect x="${sp.dir === 1 ? X(80) : X(0)}" y="0" width="20" height="20" class="fd-red"/>` : ''}
      <rect x="0" y="0" width="10" height="20" style="fill:${esc(info.away.color)}"/><rect x="110" y="0" width="10" height="20" style="fill:${esc(info.home.color)}"/>
      ${lines}${ball}</svg>`;
  };
  // ---- Replay card (owner 2026-10-14: readable at a glance): "1st & 10 at ATL 35" / "Aaron Jones 8-yard run" /
  // "-> 2nd & 2", and the play drawn on the mini field (line of scrimmage, first-down line, an arrow from start to
  // finish: green gain, red loss, neutral kick / change of possession). Headlines come from ESPN's play type, the
  // yardage and the official text's names, made full names through the box score ("J.Williams" -> Javonte Williams).
  const NM = "[A-Z][a-z]?\\.[A-Za-z'.\\- ]+?";
  const RX = {
    lead: new RegExp(`^(${NM})\\s+(?:left|right|up the middle|middle|scrambles|kneels|pass|sacked|punts|kicks|spiked|\\d+ yard field goal|extra point|FUMBLES|Aborted)`),
    // a name ends at punctuation or a lowercase word ("to D.Moore ran ob at NE 49", "to J.Williams to DAL 38")
    to: new RegExp(` to (${NM})(?= [a-z]| \\(|\\.|,|$)`),
    picked: new RegExp(`INTERCEPTED by (${NM})(?= [a-z]| \\(|\\.|,)`),
    punt: /punts (\d+) yards/, kick: /kicks (\d+) yards/, fg: /(\d+) yard field goal is (GOOD|No Good|BLOCKED)/i,
    ret: new RegExp(`\\. (${NM}) (?:to|pushed|ran|for|MUFFS)`), pen: /PENALTY on ([A-Z]{2,4})-[^,]*, ([^,]+), (\d+) yards/,
  };
  const fullNames = (sum, ids = null) => {  // ids (optional): filled with the same keys -> ESPN athlete id
    const m = {};
    // the official text writes "D.Prescott", or "Ja.Chase" to tell apart a teammate with the same initial
    ((sum && sum.boxscore && sum.boxscore.players) || []).forEach(tp => (tp.statistics || []).forEach(c => (c.athletes || []).forEach(a => {
      const A = a.athlete, fn = String(A.firstName || ''), ln = String(A.lastName || '').replace(/\s+/g, '');
      const keys = [String(A.shortName || '').replace(/\s+/g, ''), fn && ln ? `${fn[0]}.${ln}` : '', fn.length > 1 && ln ? `${fn.slice(0, 2)}.${ln}` : ''];
      const bare = ln.replace(/(Jr|Sr|II|III|IV|V)\.?$/, '');  // "Godwin Jr." is "C.Godwin" in the text
      if (fn && bare !== ln) keys.push(`${fn[0]}.${bare}`, fn.length > 1 ? `${fn.slice(0, 2)}.${bare}` : '');
      keys.forEach(k => { if (k && !m[k]) { m[k] = A.displayName; if (ids) ids[k] = String(A.id); } });
    })));
    return m;
  };
  // ctx: { off, other } our team codes for the offense at the snap and its opponent (who lost a fumble)
  const ACT = new RegExp(`^${NM} (?:pass|scrambles|sacked|left|right|up the middle|middle|kneels)\\b`);
  const playHead = (pl, names, ctx = {}) => {
    // the official text leads with formation and eligibility notes: "(Shotgun) C.Lomu reported in as eligible. D.Maye ..."
    // also "Direct snap to C.Heyward." (a wildcat snap note) and ESPN's stray leading space (" R.Stevenson up the middle")
    const lead_ = new RegExp(`^(?:(?:\\([^)]*\\)|${NM} reported in as eligible\\.|Direct snap to ${NM}\\.)\\s*)+`);
    const full = String(pl.text || '').trim().replace(lead_, '');  // shown under the card
    // what's parsed: after a replay reversal only the ruling that stands ("...the play was REVERSED.D.Maye pass
    // incomplete..."), and without the 2-point try that follows a touchdown
    let raw = full;
    if (/REVERSED\./.test(raw)) raw = raw.slice(raw.lastIndexOf('REVERSED.') + 9).trim().replace(lead_, '');
    raw = raw.replace(/\s*TWO-POINT CONVERSION ATTEMPT\..*$/, '');
    const nm = x => x ? (names[x.replace(/\s+/g, '')] || x) : '';
    const g = (k, i = 1) => { const m = raw.match(RX[k]); return m ? m[i] : null; };
    const t = (pl.type && pl.type.text) || '', y = pl.statYardage || 0;
    const td = /touchdown/i.test(t) || /TOUCHDOWN/.test(raw);
    const yds = n => n === 0 ? 'no gain' : n < 0 ? `loss of ${-n}` : `${n} yard${n === 1 ? '' : 's'}`;
    // a scrimmage action read from the text alone (ESPN's play type names the fumble, not what led to it)
    const action = txt => {
      if (!ACT.test(txt)) return null;
      const ty = /pass incomplete/.test(txt) ? 'Pass Incompletion' : /INTERCEPTED/.test(txt) ? 'Interception'
        : /sacked/.test(txt) ? 'Sack' : / pass /.test(txt) ? 'Pass Reception' : 'Rush';
      const sy = /no gain/.test(txt) ? 0 : +((txt.match(/for (-?\d+) yards?/) || [])[1] || 0);
      return playHead({ text: txt, type: { text: ty }, statYardage: sy, isTurnover: ty === 'Interception', inner: true }, names, ctx);
    };
    let h, cls = '';
    // fumbles (owner 2026-10-15: "Fumble" alone misleads): say what the play was and who ended up with the ball. Kept
    // by the offense and the play went on ("FUMBLES, and recovers ... D.Maye pass ... to H.Henry for 20 yards") -> that
    // play, recovered; otherwise the action before the fumble, then lost to / recovered by the team that got it.
    const fi = raw.search(/FUMBLES/);
    if (fi >= 0 && !pl.inner) {
      const recs = [...raw.matchAll(/(?:RECOVERED|recovered) by ([A-Z]{2,4})-/g)], rec = recs.length ? ourCode(recs[recs.length - 1][1]) : '';
      const ret = /kickoff|punt/i.test(t), loser = ret ? ctx.other : ctx.off;  // on a kick the returner's team fumbles
      const lost = rec ? (loser ? rec !== loser : !!pl.isTurnover) : false;
      if (!lost) {
        const rest = raw.slice(fi).match(new RegExp(`\\. (${NM} (?:pass|scrambles|sacked|left|right|up the middle|middle)\\b.*)$`));
        const r = rest && action(rest[1]);
        if (r) return { h: `${r.h}${rec && rec !== loser ? `, fumble recovered by ${rec}` : ' (fumble recovered)'}`, cls: r.cls, raw: full, eff: raw };
      }
      // the action that led to the LAST fumble (a play can fumble twice: botched snap, recovered, then strip-sacked)
      const lf = raw.lastIndexOf('FUMBLES'), who = (raw.match(new RegExp(`^(${NM}) `)) || [])[1];
      const segs = raw.slice(0, lf).split(/\. (?=[A-Z][a-z]?\.)/).map(x => x.trim()).filter(Boolean);
      const head = ret ? raw.slice(0, fi).trim() : segs.reverse().find(x => ACT.test(x));
      const base = ret ? playHead(Object.assign({}, pl, { text: head, inner: true }), names, ctx).h : head ? action(head).h : '';
      const tdD = lost && /TOUCHDOWN/.test(raw.slice(lf));
      h = base ? `${base}, ${lost ? `fumble lost to ${rec}` : 'fumble recovered'}`
        : `${who ? nm(who) : 'Ball'} fumbles, ${lost ? `lost to ${rec}` : 'offense recovers'}`;
      return { h: `${h}${tdD ? `, ${rec} TD` : ''}`.replace(/\s{2,}/g, ' '), cls: lost ? 'bad' : '', raw: full, eff: raw, lost };
    }
    if (/interception/i.test(t)) { h = `${nm(g('lead'))} intercepted${g('picked') ? ` by ${nm(g('picked'))}` : ''}`; cls = 'bad'; }
    else if (/sack/i.test(t)) { h = `${nm(g('lead'))} sacked, ${yds(y)}`; cls = 'bad'; }
    else if (/pass reception|passing touchdown/i.test(t)) h = `${nm(g('lead'))} ${g('to') ? `to ${nm(g('to'))}` : 'pass'}, ${yds(y)}`;
    else if (/pass incompletion/i.test(t)) h = `${nm(g('lead'))} incomplete${g('to') ? ` to ${nm(g('to'))}` : ''}`;
    else if (/^rush|rushing touchdown/i.test(t)) h = y > 0 ? `${nm(g('lead'))} ${y}-yard run` : `${nm(g('lead'))} run, ${yds(y)}`;
    else if (/punt/i.test(t)) h = `${nm(g('lead'))} punts ${g('punt') || ''} yards${/Touchback/i.test(raw) ? ', touchback' : g('ret') ? `, ${nm(g('ret'))} returns ${pl.statYardage || 0}` : ''}`;
    else if (/kickoff/i.test(t)) h = /Touchback/i.test(raw) ? 'Kickoff, touchback' : `Kickoff: ${nm(g('ret'))} returns it ${pl.statYardage || 0} yards`;
    else if (/field goal/i.test(t)) { const r = g('fg', 2); h = `${g('fg') || ''}-yard field goal, ${/good/i.test(r || t) && !/no good/i.test(r || '') ? 'good' : r && /block/i.test(r) ? 'blocked' : 'no good'}`; cls = /good/i.test(t) ? 'good' : 'bad'; }
    else if (/penalty/i.test(t)) { const m = raw.match(RX.pen); h = m ? `Penalty, ${m[1]}: ${m[2]}, ${m[3]} yards` : 'Penalty'; cls = 'pen'; }  // not 'flag': site.css .flag is a white badge
    else h = t || raw.split('. ')[0];
    if (td) { h += ' · Touchdown'; cls = 'td'; }
    if (pl.isTurnover && cls !== 'bad') cls = 'bad';
    return { h: h.replace(/\s+,/g, ',').replace(/\s{2,}/g, ' ').trim(), cls, raw: full, eff: raw };
  };
  // ---- what one play put in the box score (owner 2026-10-15): yards, catches, touchdowns, picks and lost fumbles
  // per player, read from the official text (ESPN's play feed names no players). Every scrimmage action in the text
  // counts ("FUMBLES, and recovers ... D.Maye pass ... to H.Henry for 20 yards" credits the pass). Sacks, kicks,
  // 2-point tries and plays wiped out by a penalty credit nothing.
  const playStats = (raw, lost) => {
    if (/No Play|NULLIFIED/i.test(raw)) return [];
    const out = {}, who = k => out[k] || (out[k] = { key: k, s: {} });
    const add = (k, stat, v) => { const o = who(k); o.s[stat] = (o.s[stat] || 0) + v; };
    let carrier = null;
    raw.split(/\. (?=[A-Z][a-z]?\.)/).map(x => x.trim()).filter(x => ACT.test(x) && !/sacked|kneels|TWO-POINT/i.test(x)).forEach(seg => {
      const lead = seg.match(new RegExp(`^(${NM}) `))[1];
      const yd = /no gain/.test(seg) ? 0 : +((seg.match(/for (-?\d+) yards?/) || [])[1] || 0);
      const td = /TOUCHDOWN/.test(seg.split(/INTERCEPTED|FUMBLES/)[0]);
      if (/ pass /.test(seg)) {
        if (/INTERCEPTED/.test(seg)) { add(lead, 'interception', 1); carrier = null; return; }
        if (/pass incomplete/.test(seg)) { add(lead, 'pass_att', 0); carrier = null; return; }
        const to = seg.match(RX.to);
        add(lead, 'pass_yd', yd); if (td) add(lead, 'pass_td', 1);
        if (to) { add(to[1], 'reception', 1); add(to[1], 'rec_yd', yd); if (td) add(to[1], 'rec_td', 1); }
        carrier = to ? to[1] : lead;
      } else { add(lead, 'rush_yd', yd); if (td) add(lead, 'rush_td', 1); carrier = lead; }
    });
    if (lost && carrier) add(carrier, 'fumble_lost', 1);
    return Object.values(out);
  };
  const statText = s => {
    const sg = v => `${v < 0 ? '&minus;' : '+'}${Math.abs(v)}`, bits = [];
    if (s.pass_att != null && s.pass_yd == null && !s.interception) bits.push('incomplete');
    if (s.pass_yd != null) bits.push(`${sg(s.pass_yd)} pass yds`);
    if (s.pass_td) bits.push('pass TD');
    if (s.interception) bits.push('INT');
    if (s.rush_yd != null) bits.push(`${sg(s.rush_yd)} rush yds`);
    if (s.rush_td) bits.push('rush TD');
    if (s.reception) bits.push(`catch, ${sg(s.rec_yd || 0)} yds`);
    if (s.rec_td) bits.push('rec TD');
    if (s.fumble_lost) bits.push('fumble lost');
    return bits.join(' · ');
  };
  const WPI = new WeakMap();  // sum -> { playId: [win% before, win% after] } (home team's chance)
  const wpAround = (sum, pl) => {
    if (!WPI.has(sum)) {
      const m = {}, ser = wpSeries(sum);
      ser.forEach((x, i) => { m[String(x.play.id)] = [i ? ser[i - 1].home : x.home, x.home]; });
      WPI.set(sum, m);
    }
    return WPI.get(sum)[String(pl.id)] || null;
  };
  const playImpact = (pl, hd, info, sum, ids, names, off) => {
    const map = byEspn(), w = weights(), K = KEYS();
    const rows = playStats(hd.eff, hd.lost).map(o => {
      const id = ids[o.key.replace(/\s+/g, '')], pid = id && map[id], pp = pid && DATA && DATA.players[pid];
      const line = K.map(k => o.s[k] || 0), fp = pts(line, w, pp ? pp.pos : '');
      return `<div class="pi-row"${pid ? ` data-open-pid="${esc(pid)}"` : ''}>${id ? `<img class="pi-hs" src="${esc(NFLE.ui ? NFLE.ui.headshot(id) : '')}" alt="" loading="lazy" onerror="this.style.visibility='hidden'">` : '<span class="pi-hs"></span>'}
        <span class="pi-nm">${esc(names[o.key.replace(/\s+/g, '')] || o.key)}</span><span class="pi-st">${statText(o.s)}</span>
        <b class="pi-fp ${fp > 0.05 ? 'up' : fp < -0.05 ? 'dn' : ''}">${fp > 0.05 ? '+' : fp < -0.05 ? '&minus;' : ''}${f1(Math.abs(fp))}</b></div>`;
    }).slice(0, 2).join('');
    const wp = wpAround(sum, pl);
    let wpHtml = '';
    if (wp && off) {
      const home = off === info.home.team, b0 = Math.round(100 * (home ? wp[0] : 1 - wp[0])), b1 = Math.round(100 * (home ? wp[1] : 1 - wp[1])), d = b1 - b0;
      wpHtml = `<div class="pi-wp"><span>${esc(off)} win chance</span> <b>${b0}%</b> <span class="rp-ar">&rarr;</span> <b>${b1}%</b>
        <span class="pi-d ${d > 0 ? 'up' : d < 0 ? 'dn' : ''}">${d > 0 ? '+' : d < 0 ? '&minus;' : '±'}${Math.abs(d)}</span></div>`;
    }
    return `<div class="pi">${rows}${wpHtml}</div>`;
  };
  const playFieldSvg = (a, b, info) => {
    const X = v => 10 + v;
    let lines = '';
    for (let v = 10; v < 100; v += 10) lines += `<line x1="${X(v)}" y1="1" x2="${X(v)}" y2="19" class="fd-l${v === 50 ? ' mid' : ''}"/>`;
    let mark = '';
    if (a && b) {
      const same = a.offense.team === b.offense.team, d = b.x - a.x, gain = same && d * a.dir > 0, loss = same && d * a.dir < 0;
      const cls = !same ? 'fd-ar kick' : gain ? 'fd-ar gain' : loss ? 'fd-ar loss' : '';
      mark = `${a.down ? `<line x1="${X(a.toGo)}" y1="1" x2="${X(a.toGo)}" y2="19" class="fd-go"/>` : ''}<line x1="${X(a.x)}" y1="1" x2="${X(a.x)}" y2="19" class="fd-los"/>`;
      if (cls && Math.abs(d) >= 0.5) {
        const s0 = Math.sign(d);
        const x2 = X(b.x) - s0 * 1.6, tip = `M${X(b.x)} 10 l${-s0 * 2.6} -2.6 v5.2 z`;
        mark += `<line x1="${X(a.x)}" y1="10" x2="${x2}" y2="10" class="fd-halo"/><path d="${tip}" class="fd-halo"/>`
          + `<line x1="${X(a.x)}" y1="10" x2="${x2}" y2="10" class="${cls}"/><path d="${tip}" class="${cls} head"/>`;
      }
    } else if (a) mark = `<line x1="${X(a.x)}" y1="1" x2="${X(a.x)}" y2="19" class="fd-los"/>`;  // an event: just where the ball sits
    return `<svg class="fd" viewBox="0 0 120 20" preserveAspectRatio="none" aria-hidden="true"><rect x="0" y="0" width="120" height="20" class="fd-turf"/>
      <rect x="0" y="0" width="10" height="20" style="fill:${esc(info.away.color)}"/><rect x="110" y="0" width="10" height="20" style="fill:${esc(info.home.color)}"/>${lines}${mark}</svg>`;
  };
  const replayCard = (pl, info, sum) => {
    const a = spot(pl.start, info), b = spot(pl.end, info), ids = {}, names = fullNames(sum, ids);
    const hd = playHead(pl, names, a ?{ off: a.offense.team, other: a.offense.team === info.away.team ? info.home.team : info.away.team } : {});
    // timeouts, quarter ends, the two-minute warning: an event, not a play (no down line, nothing next)
    const event = /timeout|end period|end of|two-minute/i.test((pl.type && pl.type.text) || '');
    const off = a && !event ? a.offense.team : '';
    // top: who has it and where; bottom: the down before -> the down after (owner: "2nd & 10 -> 3rd & 2")
    const kick = /kickoff/i.test((pl.type && pl.type.text) || '');
    const where = event || kick || !pl.start ? '' : String(pl.start.possessionText || '').replace(/^50$/, 'midfield');
    const before = event ? '' : pl.start && pl.start.down ? (pl.start.shortDownDistanceText || pl.start.downDistanceText || '') : kick ? 'Kickoff' : '';
    const changed = a && b && a.offense.team !== b.offense.team;
    const after = !pl.end || !pl.end.downDistanceText ? '' : changed ? `${b.offense.team} ball, ${pl.end.downDistanceText}` : pl.end.shortDownDistanceText || pl.end.downDistanceText;
    // color code (owner 2026-10-15): the offense in its team color, the yards gained green / lost red, and the downs
    // by urgency (a fresh 1st down green, 3rd amber, 4th red)
    const offSide = off ? (info.away.team === off ? info.away : info.home) : null;
    const pill = t => { const sd = info.away.team === t ? info.away : info.home.team === t ? info.home : null;
      return `<span class="rp-tm tm-open" data-tm="${esc(t)}" style="--tc:${esc((sd && sd.color) || '#555')}">${esc(t)}</span>`; };
    const dc = t => /^1st/.test(t) ? 'd1' : /^3rd/.test(t) ? 'd3' : /^4th/.test(t) ? 'd4' : '';
    const net = a && b && !event && !changed && !kick && !/punt|field goal|extra point|kickoff/i.test((pl.type && pl.type.text) || '') ? Math.round((b.x - a.x) * a.dir) : null;
    const chip = net == null ? '' : `<span class="rp-yd ${net > 0 ? 'gain' : net < 0 ? 'loss' : 'zero'}">${net > 0 ? '+' : net < 0 ? '&minus;' : ''}${Math.abs(net)} yd${Math.abs(net) === 1 ? '' : 's'}</span>`;
    const afterHtml = !after ? '' : changed ? `${pill(b.offense.team)} <span class="rp-d chg">${esc(pl.end.shortDownDistanceText || pl.end.downDistanceText)}</span>`
      : `<span class="rp-d ${dc(after)}${/^1st/.test(after) && !/^1st/.test(before) ? ' new' : ''}">${esc(after)}</span>`;
    return `<section class="sit rp-card"><div class="rp-dd">${offSide ? `${pill(off)} <b>ball</b>` : ''}${where ? `${off ? ' · ' : ''}${esc(where)}` : ''}</div>
      <div class="rp-what ${hd.cls}${hd.h.length > 44 ? ' long' : ''}">${esc(hd.h)}</div>${playFieldSvg(event ? b : a, event ? null : b, info)}
      <div class="rp-next">${!event && (before || after) ? `<span class="rp-d ${dc(before)}">${esc(before)}</span>${after ? ` <span class="rp-ar">&rarr;</span> ${afterHtml}` : ''}${chip}` : ''}</div>
      ${event ? '<div class="pi"></div>' : playImpact(pl, hd, info, sum, ids, names, off)}
      <div class="rp-raw" title="Tap for the full play">${esc(hd.raw)}</div></section>`;
  };
  const sitFromPlays = (sum) => {  // after the last play (finished games, replay, or no live situation yet)
    const pl = allPlays(sum).flatMap(d => d.plays || []);
    const last = pl[pl.length - 1];
    return last ? Object.assign({}, last.end || {}, { lastPlay: { text: last.text } }) : null;
  };

  // ------------------------------------------------------------------------------------------------ player news
  // RotoWire's player blurbs (what happened + why it matters), as ESPN's fantasy app shows them. One request per
  // player, made when his card opens; cached for 5 minutes. Read live from ESPN, never stored by us.
  const NEWS = {};
  const ago = iso => {
    const s = (Date.now() - new Date(iso).getTime()) / 1000;
    if (s < 3600) return `${Math.max(1, Math.round(s / 60))}m ago`;
    if (s < 86400) return `${Math.round(s / 3600)}h ago`;
    if (s < 7 * 86400) return `${Math.round(s / 86400)}d ago`;
    return new Date(iso).toLocaleDateString([], { month: 'short', day: 'numeric' });
  };
  const newsHtml = (items, n = 6) => !items.length ? '<p class="pc-sub">No news in the last 60 days.</p>'
    : `<ol class="nw">${items.slice(0, n).map(a => {
        const story = String(a.story || a.description || '').replace(/<[^>]+>/g, '').trim();
        const long = story.length > 260;
        return `<li class="nw-i${Date.now() - new Date(a.published).getTime() < 86400000 ? ' fresh' : ''}">
          <div class="nw-t">${esc(ago(a.published))}${a.type ? ` · ${esc(a.type === 'Rotowire' ? 'RotoWire' : a.type)}` : ''}</div>
          <div class="nw-h">${esc(a.headline || '')}</div>
          ${story ? `<div class="nw-s${long ? ' clip' : ''}">${esc(story)}</div>${long ? '<button type="button" class="nw-more">More</button>' : ''}` : ''}</li>`;
      }).join('')}</ol>${n >= 6 ? '<div class="nw-src">Player news by RotoWire, via ESPN\'s public feed.</div>' : ''}`;
  const NEWSP = {};  // espn id -> in-flight request (the Week tab's preview and the News tab share one)
  const fetchNews = espn => NEWSP[espn] || (NEWSP[espn] = getJSON(`https://site.web.api.espn.com/apis/fantasy/v2/games/ffl/news/players?days=60&playerId=${encodeURIComponent(espn)}`)
    .then(d => {
      const items = (d.feed || []).filter(a => a.headline).sort((a, b) => new Date(b.published) - new Date(a.published));
      NEWS[espn] = { t: Date.now(), items };
      return items;
    }).finally(() => { delete NEWSP[espn]; }));
  const loadNews = (espn, box, n = 6) => {
    const show = items => { if (box.isConnected) { box.innerHTML = newsHtml(items, n); wireNews(box); } };
    const hit = NEWS[espn];
    if (hit && Date.now() - hit.t < 300000) { show(hit.items); return; }
    box.innerHTML = '<p class="pc-sub">Loading news&hellip;</p>';
    fetchNews(espn).then(show).catch(() => { if (box.isConnected) box.innerHTML = '<p class="pc-sub">News unavailable right now.</p>'; });
  };
  document.addEventListener('nfle-sheet', e => e.detail.querySelectorAll('.pc-news[data-espn]').forEach(nb => loadNews(nb.dataset.espn, nb, +nb.dataset.n || 3)));
  const wireNews = box => box.querySelectorAll('.nw-more').forEach(b => b.onclick = () => {
    const s = b.previousElementSibling; s.classList.toggle('clip'); b.textContent = s.classList.contains('clip') ? 'More' : 'Less';
  });

  // ------------------------------------------------------------------------------------------- career game log
  // data/players/<gsis>.json (tools/player_logs.py): every regular-season game, newest season first, all expanded.
  // Opponent colored by OUR pregame matchup rank that week (2021 on); rank = his position finish that week.
  const LOGS = {};
  const siteRoot = () => CFG.page === 'game' ? '' : (CFG.root || '');
  const league = () => {
    try { const s = JSON.parse(localStorage.getItem('nfledge-scoring') || 'null'); if (s && s.lg) return s.lg; } catch (e) { /* default */ }
    return { teams: 10, QB: 1, RB: 2, WR: 2, TE: 1 };
  };
  const mrClass = r => !r ? '' : r <= 8 ? 'mr-hard' : r <= 16 ? 'mr-tough' : r <= 24 ? 'mr-ok' : 'mr-easy';
  // each column: [label, value, index into the game row's weekly position ranks g.r (tools/player_logs.py RANKED), or none]
  const logCols = (pos, rushy) => {
    const c = (g, i) => g.c[i], x = (g, i) => g.x[i];
    const ypc = g => x(g, 2) ? (c(g, 3) / x(g, 2)).toFixed(1) : '';
    // every position gets all three groups (owner 2026-10-16), his own first so it's on screen without scrolling
    // sideways; a group outside his role (third element true: a WR's passing) shows its zeros plain, not as red chips
    const pass = ex => ['Passing', [['C/A', g => `${x(g, 0)}/${x(g, 1)}`, 9], ['Yd', g => f0(c(g, 0)), 0], ['TD', g => c(g, 1), 1], ['Int', g => c(g, 2), 2]], ex];
    const rec = ex => ['Receiving', [['Tgt', g => x(g, 3), 12], ['Rec', g => c(g, 5), 5], ['Yd', g => f0(c(g, 6)), 6], ['TD', g => c(g, 7), 7]], ex];
    const rush = ex => ['Rushing', [['Att', g => x(g, 2), 11], ['Yd', g => f0(c(g, 3)), 3], ...(pos === 'RB' ? [['YPC', ypc]] : []), ['TD', g => c(g, 4), 4]], ex];
    return pos === 'QB' ? [pass(false), rush(false), rec(true)]
      : pos === 'RB' ? [rush(false), rec(false), pass(true)]
      : [rec(false), rush(!rushy), pass(true)];
  };
  // Game logs: each section's column heads (Wk / Opp / Pts ..., with the Passing / Rushing group row) stay under the
  // page header while that section's games scroll past, and leave with its last game (owner 2026-10-16). The log scrolls
  // sideways, which traps position: sticky inside .lg-scroll, and moving rows from scroll events lagged on iOS. So: for
  // each section an invisible box over it, OUTSIDE the scroller, holding a native position: sticky copy of its heads
  // (the browser does the sticking: no lag, and the box's end is where it lets go). Script only lays the boxes out
  // when the table's size changes and keeps the copy's sideways scroll in step with the table's.
  const stickTop = () => {
    const h = document.querySelector('#pcOv:not([hidden]) .pc-head'), nav = document.querySelector('nav.tabs');
    return h ? (parseFloat(getComputedStyle(h).top) || 0) + h.offsetHeight : nav ? nav.offsetHeight : 0;
  };
  const layHeads = tbl => {
    const sc = tbl.closest('.lg-scroll'), box = sc && sc.parentElement;
    if (!box) return;
    box.querySelectorAll(':scope > .lg-fh').forEach(x => x.remove());
    if (!tbl.offsetParent) return;
    if (getComputedStyle(box).position === 'static') box.style.position = 'relative';
    const b0 = box.getBoundingClientRect().top, s0 = sc.getBoundingClientRect(), top = stickTop();
    const cs = getComputedStyle(sc);
    tbl.querySelectorAll('tbody tr.lg-ch').forEach(ch => {
      // the rows right above the heads ride along (owner 2026-10-16): group heads, the Playoffs / Regular season label
      // and the season row ("2026 NO - 5 games - 17.0 FP/G") when it sits directly above
      const lead = [];
      for (let pv = ch.previousElementSibling; pv && ['lg-gh', 'lg-sub', 'lg-season'].some(c => pv.classList.contains(c)); pv = pv.previousElementSibling) {
        lead.unshift(pv);
        if (pv.classList.contains('lg-season')) break;
      }
      let end = ch.parentElement.getBoundingClientRect().bottom;
      for (let n = ch.nextElementSibling; n; n = n.nextElementSibling) {
        if (n.classList.contains('lg-sub') || n.classList.contains('lg-season')) { end = n.getBoundingClientRect().top; break; }
      }
      const r0 = (lead[0] || ch).getBoundingClientRect().top;
      // under "Regular season" (after a playoffs block) the copy names the season too
      const seasonRow = ch.parentElement.querySelector('tr.lg-season'), yr = seasonRow && seasonRow.querySelector('b');
      const leadHtml = lead.map(r => r.classList.contains('lg-sub') && !lead.some(x => x.classList.contains('lg-season')) && yr
        ? r.outerHTML.replace('<span class="lg-pin">', `<span class="lg-pin">${esc(yr.textContent)} &middot; `) : r.outerHTML).join('');
      const widths = [...ch.cells].map(c => c.getBoundingClientRect().width);
      const lay = document.createElement('div');
      lay.className = 'lg-fh';
      lay.setAttribute('aria-hidden', 'true');
      lay.style.cssText = `top:${r0 - b0}px;height:${Math.max(0, end - r0)}px;left:${s0.left - box.getBoundingClientRect().left}px;width:${s0.width}px`;
      lay.innerHTML = `<div class="lg-fh-in" style="top:${top}px"><div class="lg-fh-x" style="padding:0 ${cs.paddingRight} 0 ${cs.paddingLeft}">
        <table class="${tbl.className}" style="width:${tbl.getBoundingClientRect().width}px"><colgroup>${widths.map(w => `<col style="width:${w}px">`).join('')}</colgroup>
        <tbody>${leadHtml}${ch.outerHTML}</tbody></table></div></div>`;
      box.appendChild(lay);
      lay.querySelector('.lg-fh-x').scrollLeft = sc.scrollLeft;
    });
    if (!sc.dataset.fh) {  // the copies follow the table sideways
      sc.dataset.fh = '1';
      sc.addEventListener('scroll', () => box.querySelectorAll(':scope > .lg-fh .lg-fh-x').forEach(x => { x.scrollLeft = sc.scrollLeft; }), { passive: true });
    }
  };
  const fhRO = typeof ResizeObserver === 'function' ? new ResizeObserver(es => es.forEach(e => layHeads(e.target))) : null;
  const fhSeen = new WeakSet();
  const watchLogs = root => (root.querySelectorAll ? root.querySelectorAll('.lg-scroll > table.lg') : []).forEach(tbl => {
    if (fhSeen.has(tbl) || !tbl.querySelector('tbody tr.lg-ch')) return;
    fhSeen.add(tbl);
    if (fhRO) fhRO.observe(tbl); else layHeads(tbl);
  });
  new MutationObserver(ms => ms.forEach(m => m.addedNodes.forEach(n => { if (n.nodeType === 1) watchLogs(n.parentElement || n); })))
    .observe(document.documentElement, { childList: true, subtree: true });
  addEventListener('resize', () => document.querySelectorAll('.lg-scroll > table.lg').forEach(tbl => fhSeen.has(tbl) && layHeads(tbl)), { passive: true });
  // A week without a game of his: why (roster status that week; tools/player_logs.py roster_tag). "Bye" sits in the
  // pinned Opp column so it stays put when the log scrolls sideways.
  const MISS_TIP = { DNP: 'Active, did not play', INA: 'Inactive on game day', IR: 'Injured reserve', PUP: 'PUP list', Res: 'Reserve list',
                     PS: 'Practice squad', Cut: 'Released', Ret: 'Retired', FA: 'Not on a roster' };
  const missTag = u => u.miss ? `<span class="lg-tag" title="${esc(MISS_TIP[u.miss] || u.miss)}">${esc(u.miss)}</span>` : '<span class="lg-tag" title="On the field, no stats">0</span>';
  const byeRow = (w, rest) => `<tr class="lg-bye"><td>${w}</td><td>Bye</td><td colspan="${rest}"></td></tr>`;
  // Week tab preview, no legend and no upcoming weeks: opts.season = this season's games so far with its byes;
  // opts.last = N = his N most recent games (the fallback before his first game this season, no season totals).
  const logHtml = (L, p, opts = {}) => {
    const w = weights(), built = (DATA && DATA.score && DATA.score.built) || HALF, pos = L.pos || (p && p.pos);
    let seasons = L.seasons, up = L.up || [];
    if (opts.season) {
      seasons = L.seasons.filter(S => S.s === L.cur && S.g.length);
      const end = Math.max(0, ...(seasons[0] ? seasons[0].g.map(g => g.w) : []));
      up = up.filter(u => u.bye && u.w < end);
    } else if (opts.last) {
      const keep = new Set(L.seasons.flatMap(S => S.g.map(g => [S.s, g])).sort((a, b) => b[0] - a[0] || b[1].w - a[1].w)
        .slice(0, opts.last).map(r => r[1]));
      seasons = L.seasons.map(S => ({ ...S, g: S.g.filter(g => keep.has(g)) })).filter(S => S.g.length);
      up = [];
    }
    const all = L.seasons.flatMap(s => s.g);
    const rushy = pos !== 'QB' && pos !== 'RB' && all.reduce((t, g) => t + g.x[2], 0) >= 8;
    const groups = logCols(pos, rushy), stat = groups.flatMap(([, cols, ex]) => cols.map(([n, fn, ri]) => [n, fn, ri, ex]));
    // a divider where each stat group starts (owner 2026-10-17: passing ran straight into rushing below the heads)
    const gstart = new Set();
    groups.reduce((k, [, cols], gi) => { if (gi) gstart.add(k); return k + cols.length; }, 0);
    const gcl = i => gstart.has(i) ? ' lg-gs' : '';
    const grpHead = lead => `<tr class="lg-gh"><th colspan="${lead}"></th>${groups.map(([n, cols], gi) => `<th colspan="${cols.length}" class="lg-grp${gi ? ' lg-gs' : ''}">${n}</th>`).join('')}</tr>`;
    const nil = v => +v === 0 || v === '0/0' || v === '';  // nothing in that column (C/A '0/0', YPC '')
    const offRole = (v, ex) => ex && nil(v) ? `<span class="muted">${v === '0/0' || v === '' ? '–' : v}</span>` : null;
    const lg = league(), need = (lg.teams || 10) * Math.max(1, lg[pos] || 1);
    const rkClass = r => r <= need ? 'rk-good' : r <= 2 * need ? 'rk-mid' : 'rk-bad';
    // a value's chip, colored by its finish at his position that week (owner 2026-10-16; Sleeper-style); older files
    // without per-stat ranks get plain chips
    const chip = (v, r) => r == null ? `${v}` : `<span class="sc ${rkClass(r)}">${v}</span>`;
    const snapTone = s => s == null ? '' : s >= 70 ? 'rk-good' : s >= 40 ? 'rk-mid' : 'rk-bad';
    const projOf = g => g.pjl ? g.pj * (pts(g.pjl, w, pos) / Math.max(0.1, pts(g.pjl, built, pos))) : null;
    // Opponent color: our pregame matchup, green / red when it was one of that week's bigger ones (mu, mh); week
    // files from before 2026-10-14 carry the old 1st-32nd rank (mr) instead.
    const oppTone = g => g.mu != null ? '' : mrClass(g.mr);
    const oppTip = g => g.mu != null ? `Our pregame matchup: ${muSigned(g.mu)} pts vs an average opponent`
      : g.mr ? `Our pregame matchup rank: ${ord(g.mr)} of 32 vs ${esc(pos)}s (1st = toughest)` : '';
    const opp = g => `<td class="lg-opp tm-opp ${oppTone(g)}"${g.mc ? ` style="--mc:${esc(g.mc)}"` : ''}${oppTip(g) ? ` title="${oppTip(g)}"` : ''}><button type="button" class="tm-open" data-tm="${esc(g.o)}">${g.h === 0 ? '@' : ''}${esc(g.o)}</button></td>`;
    const head = `${grpHead(6)}
      <tr class="lg-ch"><th>Wk</th><th>Opp</th><th class="num">Pts</th><th class="num">Proj</th><th class="num" title="His finish at his position that week">Rk</th><th class="num">Snap</th>${stat.map(([n], i) => `<th class="num${gcl(i)}">${n}</th>`).join('')}</tr>`;
    const blank = stat.map((c, i) => `<td class="num${gcl(i)}">–</td>`).join('');
    const body = seasons.map(S => {
      const isCur = S.s === L.cur, rows = S.g.map(g => ({ w: g.w, g }));
      if (isCur) up.forEach(u => rows.push({ w: u.w, u }));
      // weeks without a game of his (tools/player_logs.py missed_weeks): byes, and why he sat
      if (!opts.last) (S.m || []).forEach(m => rows.push({ w: m.w, u: m }));
      rows.sort((a, b) => b.w - a.w);  // newest first: scrolling down goes back in time (owner, 2026-10-14)
      const fps = S.g.map(g => pts(g.c, w, pos)), fpg = fps.length ? fps.reduce((a, b) => a + b, 0) / fps.length : 0;
      const team = S.g.length ? S.g[S.g.length - 1].t : '';
      const played = (g, label) => { const v = pts(g.c, w, pos), pj = projOf(g);
        return `<tr${tileAttrs(g)}><td>${esc(label)}</td>${opp(g)}<td class="num lg-fp">${g.r ? chip(f1(v), g.rk) : f1(v)}</td>
          <td class="num ${pj == null ? 'muted' : v >= pj ? 'lg-over' : 'lg-under'}">${pj != null ? f1(pj) : '–'}</td>
          <td class="num"><span class="lg-rk ${rkClass(g.rk)}">${g.rk}</span></td><td class="num">${g.sn != null ? (g.r ? `<span class="sc ${snapTone(g.sn)}">${g.sn}</span>` : g.sn) : '–'}</td>
          ${stat.map(([, fn, ri, ex], i) => { const v = fn(g);
            // a zero ties most of the position (0 rush TD can "rank" top 10): red (owner 2026-10-16), except Int / fumbles
            // (fewer is better)
            const off = offRole(v, ex);
            return `<td class="num${gcl(i)}">${off != null ? off : ri != null && g.r ? (+v === 0 && ri !== 2 && ri !== 8 ? `<span class="sc rk-bad">${v}</span>` : chip(v, g.r[ri])) : v}</td>`; }).join('')}</tr>`; };
      // season totals right under the column heads (owner 2026-10-16): the games summed into one stat line, so every
      // column (C/A, YPC) reads it as it reads a game; Snap = average, Proj = total only when every game had one.
      // Colored by the season total's finish at his position (rk = S.trk / S.tr from tools/player_logs.py; not playoffs)
      const totRow = (gs, rk) => {
        if (gs.length < 2 || opts.last) return '';
        const add = k => gs[0][k].map((_, i) => gs.reduce((t, g) => t + (+g[k][i] || 0), 0)), T = { c: add('c'), x: add('x') };
        const pjs = gs.map(projOf), sn = gs.filter(g => g.sn != null);
        const tc = (v, r) => rk && r != null ? chip(v, r) : v, avgSn = sn.length ? Math.round(sn.reduce((t, g) => t + g.sn, 0) / sn.length) : null;
        return `<tr class="lg-tot"><td>Tot</td><td></td><td class="num lg-fp">${tc(f1(pts(T.c, w, pos)), rk && rk.trk)}</td>
          <td class="num muted">${pjs.every(v => v != null) ? f1(pjs.reduce((a, b) => a + b, 0)) : '–'}</td>
          <td class="num">${rk && rk.trk ? `<span class="lg-rk ${rkClass(rk.trk)}" title="His ${esc(pos)} finish that season (fantasy points, site scoring)">${rk.trk}</span>` : ''}</td>
          <td class="num">${avgSn == null ? '–' : rk ? `<span class="sc ${snapTone(avgSn)}">${avgSn}</span>` : avgSn}</td>${stat.map(([, fn, ri, ex], i) => { const v = fn(T); return `<td class="num${gcl(i)}">${offRole(v, ex) ?? tc(v, rk && rk.tr && ri != null ? rk.tr[ri] : null)}</td>`; }).join('')}</tr>
          <tr class="lg-gap"><td colspan="${6 + stat.length}"></td></tr>`;
      };
      const trs = totRow(S.g, S.tr ? S : null) + rows.map(r => {
        if (r.u && r.u.bye) return byeRow(r.w, 4 + stat.length);
        if (r.u && r.u.miss != null) return `<tr class="lg-miss"${tileAttrs(r.u)}><td>${r.w}</td>${r.u.o ? opp(r.u) : '<td class="lg-opp">&ndash;</td>'}<td class="num">${missTag(r.u)}</td><td class="num">&ndash;</td><td class="num">&ndash;</td><td class="num">${r.u.sn != null ? r.u.sn : '&ndash;'}</td>${blank}</tr>`;
        if (r.u) {
          const pj = projOf(r.u);
          return `<tr class="lg-up"${tileAttrs(r.u)}><td>${r.w}</td>${opp(r.u)}<td class="num">–</td><td class="num">${pj != null ? f1(pj) : '–'}</td><td class="num">–</td><td class="num">–</td>${blank}</tr>`;
        }
        return played(r.g, r.g.w);
      }).join('');
      const sum = opts.last ? '' : ` · ${S.g.length} game${S.g.length === 1 ? '' : 's'}${S.g.length ? ` · ${f1(fpg)} FP/G` : ''}`;
      // playoffs first (as Sleeper does), their own block: not in the regular-season totals, finishes or FP/G
      const pg = opts.last || opts.season ? [] : (S.pg || []);
      const sub = (label, gs) => `<tr class="lg-sub"><td colspan="${6 + stat.length}"><span class="lg-pin">${label}${gs ? ` · ${gs.length} game${gs.length === 1 ? '' : 's'} · ${f1(gs.reduce((t, g) => t + pts(g.c, w, pos), 0) / gs.length)} FP/G` : ''}</span></td></tr>`;
      const po = pg.length ? `${sub('Playoffs', pg)}${head}${totRow(pg)}${[...pg].reverse().map(g => played(g, g.po)).join('')}${S.g.length || rows.length ? sub('Regular season') : ''}` : '';
      return `<tbody data-season="${S.s}"><tr class="lg-season"><td colspan="${6 + stat.length}"><span class="lg-pin"><b>${S.s}</b> ${tmL(team)}${sum}</span></td></tr>${po}${rows.length ? head + trs : ''}</tbody>`;
    }).join('');
    if (opts.last || opts.season) return `<div class="lg-scroll"><table class="lg">${body}</table></div>`;
    // Career view (owner 2026-10-16, after Sleeper's career table): one row per regular season, its totals on the
    // game log's own columns and chips (Wk -> season, Opp -> team, Proj -> FP/G); tap a season for its games.
    // Six fixed columns like the game log's (no snap average), so it fits a phone through TD as the log does;
    // a career total row on top (owner 2026-10-16), unchipped since there's no career rank.
    const sumOf = gs => { const add = k => gs[0][k].map((_, i) => gs.reduce((t, g) => t + (+g[k][i] || 0), 0)); return { c: add('c'), x: add('x') }; };
    const carS = L.seasons.filter(S => S.g.length);
    const car = carS.map(S => {
      const gs = S.g, T = sumOf(gs), rk = S.tr ? S : null, tc = (v, r) => rk && r != null ? chip(v, r) : v, tot = pts(T.c, w, pos);
      return `<tr class="lg-car" data-go-season="${S.s}" title="Show his ${S.s} games"><td><b>${S.s}</b></td><td class="lg-opp">${tmL(gs[gs.length - 1].t)}</td>
        <td class="num">${gs.length}</td><td class="num lg-fp">${tc(f1(tot), rk && rk.trk)}</td><td class="num">${f1(tot / gs.length)}</td>
        <td class="num">${rk && rk.trk ? `<span class="lg-rk ${rkClass(rk.trk)}">${rk.trk}</span>` : '–'}</td>
        ${stat.map(([, fn, ri, ex], i) => { const v = fn(T); return `<td class="num${gcl(i)}">${offRole(v, ex) ?? tc(v, rk && rk.tr && ri != null ? rk.tr[ri] : null)}</td>`; }).join('')}</tr>`;
    }).join('');
    const allG = carS.flatMap(S => S.g), CT = allG.length ? sumOf(allG) : null, ctot = CT ? pts(CT.c, w, pos) : 0;
    const carTot = CT && carS.length > 1 ? `<tr class="lg-tot" title="Regular season, ${carS[carS.length - 1].s}-${carS[0].s}"><td>Car</td><td class="lg-opp">${carS.length} yrs</td>
        <td class="num">${allG.length}</td><td class="num lg-fp">${f1(ctot)}</td><td class="num">${f1(ctot / allG.length)}</td><td class="num"></td>
        ${stat.map(([, fn, , ex], i) => { const v = fn(CT); return `<td class="num${gcl(i)}">${offRole(v, ex) ?? v}</td>`; }).join('')}</tr><tr class="lg-gap"><td colspan="${6 + stat.length}"></td></tr>` : '';
    const carHead = `${grpHead(6)}
      <tr class="lg-ch"><th>Year</th><th>Team</th><th class="num" title="Games played">G</th><th class="num">Pts</th><th class="num" title="Fantasy points per game">FP/G</th><th class="num" title="His ${esc(pos)} finish that season">Rk</th>${stat.map(([n], i) => `<th class="num${gcl(i)}">${n}</th>`).join('')}</tr>`;
    const view = carS.length > 1 ? logView : 'g';
    const legend = `<div class="lg-leg"><span>Opponent color = our pregame matchup (2021 on): green helped, red hurt, deeper = bigger</span>
      <span>· Rk = his ${esc(pos)} finish that week (green = starter in your league size) · Proj = our projection then (green = beat it) · Tap a game to open its gamecast</span></div>`;
    const games = `${legend}<div class="lg-scroll"><table class="lg">${body}</table></div>`;
    if (carS.length < 2) return games;
    return `<div class="seg lg-views" role="tablist"><button type="button" data-lv="g" class="${view === 'g' ? 'on' : ''}">Games</button><button type="button" data-lv="s" class="${view === 's' ? 'on' : ''}">Seasons</button></div>
      <div class="lg-v" data-lv="s"${view === 's' ? '' : ' hidden'}><div class="lg-leg"><span>Regular season. Chips = his ${esc(pos)} finish that season · Tap a season for its games</span></div>
        <div class="lg-scroll"><table class="lg lg-career"><tbody>${carHead}${carTot}${car}</tbody></table></div></div>
      <div class="lg-v" data-lv="g"${view === 'g' ? '' : ' hidden'}>${games}</div>`;
  };
  // Game log view: career seasons or every game; kept across re-renders and players for the session
  let logView = 'g';
  const showLogView = (box, v, season) => {
    logView = v;
    box.querySelectorAll('[data-lv]').forEach(x => x.matches('button') ? x.classList.toggle('on', x.dataset.lv === v) : (x.hidden = x.dataset.lv !== v));
    const tb = season && box.querySelector(`tbody[data-season="${season}"]`);
    // where the previous season's heads let go; inside a card the card scrolls, not the window
    const sc = tb && tb.closest('.pc-card .pc');
    if (tb && sc) sc.scrollTo({ top: tb.getBoundingClientRect().top - sc.getBoundingClientRect().top + sc.scrollTop - stickTop() });
    else if (tb) scrollTo({ top: tb.getBoundingClientRect().top + scrollY - stickTop() });
  };
  // A game's gamecast, with the week file that holds our numbers for it when we have one (2021 on: its Pregame
  // tab reads it). Older games open with ESPN's data only (box scores back to 1999, plays from about 2005).
  const gcUrl = (gid, f) => `${siteRoot()}game.html?${f ? `d=${encodeURIComponent(f)}&` : ''}g=${encodeURIComponent(gid)}`;
  // Every log row opens that game's gamecast. g.gid / g.f (week file) come from tools/player_logs.py.
  const tileAttrs = g => g.gid ? ` data-gid="${esc(g.gid)}"${g.f ? ` data-f="${esc(g.f)}"` : ''} title="Open the gamecast"` : '';
  const wireLogRows = box => box && box.addEventListener('click', e => {
    const lv = e.target.closest('button[data-lv]');
    if (lv) { showLogView(box, lv.dataset.lv); return; }
    if (e.target.closest('button, a, select, input')) return;
    const car = e.target.closest('tr[data-go-season]');
    if (car) { showLogView(box, 'g', car.dataset.goSeason); return; }
    const tr = e.target.closest('tr[data-gid]'); if (!tr) return;
    location.href = gcUrl(tr.dataset.gid, tr.dataset.f || '');
  });
  const LOGP = {};  // pid -> in-flight fetch, so a re-render while loading doesn't refetch
  const ensureLog = pid => LOGS[pid] ? Promise.resolve(LOGS[pid]) : (LOGP[pid] || (LOGP[pid] =
    getJSON(`${siteRoot()}data/players/${encodeURIComponent(pid)}.json`).then(L => (LOGS[pid] = L)).catch(() => (LOGS[pid] = { missing: 1, seasons: [] }))));

  // ----------------------------------------------------------------------------------------------- player card
  let cardPid = null, cardTab = 'ov';  // the open tab survives live refreshes; a new player starts on Week
  // each team / player page remembers its last tab for the session, so Back from another page lands where you were
  // (owner 2026-10-15); sessionStorage so a full page reload (a game page, the week picker) keeps it too
  const TABS = (() => { try { return JSON.parse(sessionStorage.getItem('nfle-tabs') || '{}'); } catch (e) { return {}; } })();
  const rememberTab = (k, v) => { TABS[k] = v; try { sessionStorage.setItem('nfle-tabs', JSON.stringify(TABS)); } catch (e) { /* private mode */ } };
  const ensureOverlay = () => {
    let ov = document.getElementById('pcOv');
    if (ov) return ov;
    ov = el(`<div class="pc-ov" id="pcOv" hidden><div class="pc" role="dialog" aria-modal="true" aria-labelledby="pcName">
      <button type="button" class="pc-x" aria-label="Close">&times;</button><div class="pc-body"></div></div></div>`);
    document.body.appendChild(ov);
    ov.addEventListener('click', e => { if (e.target === ov || e.target.closest('.pc-x')) closePlayer(); });
    document.addEventListener('keydown', e => { if (e.key === 'Escape' && !ov.hidden) closePlayer(); });
    return ov;
  };
  let prevHash = '';
  const closePlayer = () => {
    if (pageMode() && window.NFLE && NFLE.closeCard) { NFLE.closeCard(); return; }
    const ov = document.getElementById('pcOv'); if (ov) ov.hidden = true;
    document.documentElement.classList.remove('pc-open');
    cardPid = null; cardTeam = null;
    if (location.hash.startsWith('#player/') || location.hash.startsWith('#team/')) { try { history.replaceState(null, '', location.pathname + location.search + prevHash); } catch (e) { /* ignore */ } }
  };
  const rangeSvg = (q, proj) => {
    const top = Math.max(10, q[4] * 1.1), W = 260, x = v => 4 + (W - 8) * Math.min(Math.max(v, 0), top) / top;
    return `<svg class="pc-rng" viewBox="0 0 ${W} 26" width="100%" height="26" aria-hidden="true">
      <line x1="${x(q[0])}" y1="11" x2="${x(q[4])}" y2="11" class="rng-w"/>
      <rect x="${x(q[1])}" y="5" width="${Math.max(x(q[3]) - x(q[1]), 2)}" height="12" rx="3" class="rng-b"/>
      <line x1="${x(proj)}" y1="1" x2="${x(proj)}" y2="21" class="rng-p"/>
      <text x="${x(q[0])}" y="25" class="pc-rt">${f0(q[0])}</text><text x="${x(q[4])}" y="25" class="pc-rt" text-anchor="end">${f0(q[4])}</text></svg>`;
  };
  // Small bars over season-week slots, the rankings' Last 5 look: value above each bar, the week below, BYE for a
  // team bye and a dash for a game he missed. slots: [{w, v (null = no bar), bye, pj (projection tick), title}];
  // with a projection the bar is green when he beat it, red when he missed. Scales down to fit.
  const miniBars = (slots, { fmt = f0, top = 0, slotW = 30, H = 48, cls = '' } = {}) => {
    if (!slots.length) return '';
    const W = slots.length * slotW, bw = slotW - 8, mx = Math.max(top, 1, ...slots.map(s => Math.max(s.v || 0, s.v != null ? s.pj || 0 : 0)));
    const y = v => (H - 12) - (H - 25) * Math.max(v, 0) / mx;
    return `<svg class="mb ${cls}" viewBox="0 0 ${W} ${H}" width="${W}" height="${H}" role="img">${slots.map((s, i) => {
      const x = i * slotW + 4, mid = (x + bw / 2).toFixed(1);
      const tone = s.pj == null ? '' : s.v >= s.pj ? ' mb-hit' : ' mb-miss';
      const body = s.v == null
        ? (s.bye ? `<text x="${mid}" y="${H - 15}" class="mb-bye">BYE</text>`
          : `<line x1="${x + 4}" x2="${x + bw - 4}" y1="${H - 13}" y2="${H - 13}" class="mb-dnp"/>`)
        : `<rect x="${x}" y="${y(s.v).toFixed(1)}" width="${bw}" height="${Math.max(1.5, H - 12 - y(s.v)).toFixed(1)}" rx="2" class="mb-b${tone}"/>`
          + (s.pj != null ? `<line x1="${x - 1}" x2="${x + bw + 1}" y1="${y(s.pj).toFixed(1)}" y2="${y(s.pj).toFixed(1)}" class="mb-pj"/>` : '')
          + `<text x="${mid}" y="${(Math.min(y(s.v), s.pj != null ? y(s.pj) : 99) - 3).toFixed(1)}" class="mb-v">${fmt(s.v)}</text>`;
      return `<g>${s.title ? `<title>${esc(s.title)}</title>` : ''}${body}<text x="${mid}" y="${H - 1.5}" class="mb-w">${s.w}</text></g>`;
    }).join('')}</svg>`;
  };
  // Stat grid, the card's one building block: each cell is a value over a small label (v is HTML: callers escape).
  // Rows share the grid's columns (--n), so values line up down a box; an optional label column runs down the left.
  const cell = (v, k, title = '') => `<div class="sg-c"${title ? ` title="${esc(title)}"` : ''}><b>${v}</b><small>${esc(k)}</small></div>`;
  const sgRow = (label, cells) => {
    const c = cells.filter(Boolean);
    return c.length ? `<div class="sg-r">${label != null ? `<div class="sg-k">${esc(label)}</div>` : ''}${c.join('')}</div>` : '';
  };
  const sgChart = (label, svg) => svg ? `<div class="sg-r"><div class="sg-k">${esc(label)}</div><div class="sg-chart">${svg}</div></div>` : '';
  const sg = (rows, n, { labels = true, cls = '' } = {}) => {
    const r = rows.filter(Boolean);
    return r.length ? `<div class="sg${labels ? '' : ' sg-nolab'}${cls ? ` ${cls}` : ''}" style="--n:${n}">${r.join('')}</div>` : '';
  };
  // Team byes of his current season (from the career log), for the week charts.
  const logByes = L => new Set(((L && L.up) || []).filter(u => u.bye).map(u => u.w));
  // Our projection for a logged game, rescaled to the viewer's scoring (null before 2021 / no page).
  const logProj = (g, pos) => {
    if (!g.pjl) return null;
    const built = (DATA && DATA.score && DATA.score.built) || HALF;
    return g.pj * (pts(g.pjl, weights(), pos) / Math.max(0.1, pts(g.pjl, built, pos)));
  };
  // Expected line as grid cells: volume first, then yards, then touchdowns (TDs as the chance he scores one).
  const expectedCells = p => {
    const l = p.proj_line || {}, c = [];
    const n1 = (v, k) => v ? cell(f1(v), k) : '', n0 = (v, k) => v ? cell(f0(v), k) : '';
    const tdp = (v, k) => v >= 0.05 ? cell(`${Math.round((1 - Math.exp(-v)) * 100)}%`, k, 'Chance he scores at least one') : '';
    if (p.pos === 'QB') c.push(n1(l.att, 'Pass att'), n0(l.pass_yd, 'Pass yds'), n1(l.pass_td, 'Pass TD'), n1(l.int, 'INT'), n1(l.car, 'Carries'), n0(l.rush_yd, 'Rush yds'), tdp(l.rush_td, 'Rush TD'));
    else if (p.pos === 'RB') c.push(n1(l.car, 'Carries'), n0(l.rush_yd, 'Rush yds'), n1(l.tgt, 'Targets'), n1(l.rec, 'Catches'), n0(l.rec_yd, 'Rec yds'), tdp(l.rush_td, 'Rush TD'), tdp(l.rec_td, 'Rec TD'));
    else c.push(n1(l.tgt, 'Targets'), n1(l.rec, 'Catches'), n0(l.rec_yd, 'Rec yds'), tdp(l.rec_td, 'Rec TD'), l.rush_yd >= 3 ? n0(l.rush_yd, 'Rush yds') : '');
    return c.filter(Boolean);
  };
  // Season to date as one stat grid: Scoring, then Passing / Rushing / Receiving in his position's order, Usage
  // (QBs: scramble rate this season and career), then points and snap share by week on shared week columns.
  // sc.ss = season stat line in scoring-key order, ext = volume and shares; snaps and our past projections come
  // from the career log.
  const SNAP_FLAT = 95;  // every recent game at or above this share: the snap chart says nothing (most QBs) - hidden
  const seasonHtml = (p, d, L) => {
    const ss = p.sc.ss, e = p.ext || {}, K = KEYS(), v = k => ss ? ss[K.indexOf(k)] || 0 : 0, w = weights();
    if (!ss || !e.games) return '<p class="pc-sub">No games this season yet.</p>';
    const pct = x => `${Math.round(x * 100)}%`;
    const wk = [...(p.sc.wk || [])].sort((a, b) => a[0] - b[0]), byW = Object.fromEntries(wk.map(r => [r[0], pts(r.slice(1), w, p.pos)]));
    const last = wk.slice(-3).map(r => byW[r[0]]), fpg = p.sc.g ? pts(ss, w, p.pos) / p.sc.g : null;
    const scoring = sgRow('Scoring', [cell(f0(e.games), 'Games'), fpg != null ? cell(f1(fpg), 'FP/G') : '',
      last.length ? cell(f1(last.reduce((a, b) => a + b, 0) / last.length), `Last ${last.length}`) : '']);
    const pass = p.pos === 'QB' ? sgRow('Passing', [cell(`${f0(e.completions)}/${f0(e.attempts)}`, 'Cmp/Att'), cell(f0(v('pass_yd')), 'Yds'),
      cell(f0(v('pass_td')), 'TD'), cell(f0(v('interception')), 'INT')]) : '';
    const rush = e.carries || v('rush_yd') ? sgRow('Rushing', [e.carries ? cell(f0(e.carries), 'Att') : '', cell(f0(v('rush_yd')), 'Yds'),
      e.carries ? cell(f1(v('rush_yd') / e.carries), 'YPC') : '', cell(f0(v('rush_td')), 'TD')]) : '';
    const rec = e.targets ? sgRow('Receiving', [cell(f0(e.targets), 'Tgt'), cell(f0(v('reception')), 'Rec'), cell(f0(v('rec_yd')), 'Yds'), cell(f0(v('rec_td')), 'TD')]) : '';
    const scr = p.pos === 'QB' && L && L.scr ? (() => {
      const tot = Object.values(L.scr).reduce((a, [s, n]) => [a[0] + s, a[1] + n], [0, 0]), cur = L.scr[String(d.season)];
      const r = ([s, n]) => `${(100 * s / n).toFixed(1)}%`, t = 'Scrambles per dropback (designed runs not included)';
      return [cur && cur[1] ? cell(r(cur), 'Scramble %', `${t}, ${d.season}`) : '',
              tot[1] ? cell(r(tot), 'Career scr %', `${t}, since ${Math.min(...Object.keys(L.scr).map(Number))}`) : ''];
    })() : [];
    const use = sgRow('Usage', [e.snap != null ? cell(pct(e.snap), 'Snap %', 'Share of offensive snaps') : '', p.pos !== 'QB' && e.tgt_share ? cell(pct(e.tgt_share), 'Tgt %', 'Share of team targets') : '',
      e.carry_share ? cell(pct(e.carry_share), 'Carry %', 'Share of team carries') : '', ...scr]);
    // Week charts: the last 8 season weeks before this one, the same columns for points and snaps.
    const nweek = (d.week || 1) - 1, byes = L && +d.season === +L.cur ? logByes(L) : new Set();
    const S = L && L.seasons.find(x => +x.s === +d.season), lg = S ? Object.fromEntries(S.g.map(g => [g.w, g])) : {};
    const weeks = []; for (let k = Math.max(1, nweek - 7); k <= nweek; k++) weeks.push(k);
    const gap = k => byes.has(k) ? { w: k, v: null, bye: 1, title: `Week ${k}: bye` } : { w: k, v: null, title: `Week ${k}: did not play` };
    const ptsSlots = weeks.map(k => {
      if (byW[k] == null) return gap(k);
      const pj = lg[k] ? logProj(lg[k], p.pos) : null;
      return { w: k, v: byW[k], pj, title: `Week ${k}: ${f1(byW[k])} pts${pj != null ? ` · we projected ${f1(pj)}` : ''}` };
    });
    const snapSlots = weeks.map(k => lg[k] ? { w: k, v: lg[k].sn != null ? lg[k].sn : null, title: `Week ${k}: ${lg[k].sn != null ? `${lg[k].sn}% of snaps` : 'played (no snap count)'}` } : gap(k));
    const sv = snapSlots.filter(x => x.v != null).map(x => x.v);
    const snapsFlat = !sv.length || sv.every(x => x >= SNAP_FLAT);
    const opt = { slotW: 32, H: 52 };
    const order = p.pos === 'RB' || p.pos === 'QB' ? [pass, rush, rec] : [rec, rush];
    return sg([scoring, ...order, use,
               weeks.length ? sgChart('Points', miniBars(ptsSlots, { ...opt, cls: 'mb-pts' })) : '',
               weeks.length && !snapsFlat ? sgChart('Snap %', miniBars(snapSlots, { ...opt, top: 100, cls: 'mb-snap' })) : ''], 4, { cls: 'sg-season' })
      + (p.sched ? `<div class="pc-sub">${esc(p.sched)}</div>` : '');
  };
  // ------------------------------------------------------------------------------------------ card week picker
  // Cards belong to the player / team, not the page: header, game log and news are always current; a week picker
  // (default: the page's week) chooses which week's file feeds the weekly section. weeks.json = the site's week list.
  let WL = null, WLP = null, cardWk = '';
  const WEEKS = {};  // 'season-week' -> that week's data, null when there's no page for it, a Promise while loading
  const pageKey = () => DATA ? `${DATA.season}-${DATA.week}` : '';
  const weekList = () => WLP || (WLP = getJSON(`${siteRoot()}weeks.json`).then(j => (WL = j || {})).catch(() => (WL = {})));
  const fetchWeek = key => WEEKS[key] !== undefined ? Promise.resolve(WEEKS[key]) : (WEEKS[key] = (async () => {
    const [s, w] = key.split('-'), wl = await weekList(), href = wl[s] && wl[s][w];
    if (!href) return null;
    const rel = href.replace(/\.html$/, '.json');
    try { const d = await getJSON(siteRoot() + rel); d.__rel = rel; return d; } catch (e) { return null; }
  })().then(d => (WEEKS[key] = d)));
  // The selected week's data: DATA for the page's own week, undefined while loading, null when there's no page.
  const cardData = () => {
    if (cardWk === pageKey()) return DATA;
    const v = WEEKS[cardWk];
    return v instanceof Promise ? undefined : v;
  };
  const rerenderCard = () => { if (cardPid) renderCard(cardPid); else if (cardTeam) renderTeam(cardTeam); };
  // Kick off anything the card is still missing; re-render once it lands (if the same card and week are still up).
  const cardNeeds = () => {
    const pid = cardPid, tm = cardTeam, wk = cardWk;
    const again = () => { if (cardPid === pid && cardTeam === tm && cardWk === wk) rerenderCard(); };
    if (!WL) weekList().then(again);
    if (cardData() === undefined) fetchWeek(wk).then(again);
  };
  const wkOrder = () => Object.keys(WL || {}).sort((a, b) => a - b)
    .flatMap(s => Object.keys(WL[s]).sort((a, b) => a - b).map(w => `${s}-${w}`));
  const wkLabel = d => d === DATA ? `Week ${d.week}` : `${d.season} week ${d.week}`;
  const pickerHtml = () => {
    const [cs, cw] = cardWk.split('-'), wl = WL && Object.keys(WL).length ? WL : { [cs]: { [cw]: '' } };
    const o = wkOrder(), i = o.indexOf(cardWk);
    const opts = Object.keys(wl).sort((a, b) => b - a).map(s => `<optgroup label="${esc(s)}">${Object.keys(wl[s]).sort((a, b) => a - b).map(w => {
      const k = `${s}-${w}`;
      return `<option value="${esc(k)}"${k === cardWk ? ' selected' : ''}>${esc(s)} · Week ${esc(w)}${k === pageKey() ? ' (this page)' : ''}</option>`;
    }).join('')}</optgroup>`).join('');
    return `<div class="pc-wkbar"><button type="button" class="pc-wkstep" data-wkstep="-1" aria-label="Previous week"${i <= 0 ? ' disabled' : ''}>&lsaquo;</button>
      <select class="pc-wkpick" aria-label="Week shown in this card">${opts}</select>
      <button type="button" class="pc-wkstep" data-wkstep="1" aria-label="Next week"${i < 0 || i >= o.length - 1 ? ' disabled' : ''}>&rsaquo;</button>
      ${cardWk !== pageKey() ? '<button type="button" class="pc-wkback" data-wkback>Back to this page&rsquo;s week</button>' : ''}</div>`;
  };
  const wirePicker = body => {
    const go = k => { if (k && k !== cardWk) { cardWk = k; rerenderCard(); } };
    const sel = body.querySelector('.pc-wkpick');
    if (sel) sel.onchange = () => go(sel.value);
    body.querySelectorAll('[data-wkstep]').forEach(b => b.onclick = () => { const o = wkOrder(); go(o[o.indexOf(cardWk) + +b.dataset.wkstep]); });
    const back = body.querySelector('[data-wkback]'); if (back) back.onclick = () => go(pageKey());
  };
  const wkWait = d => d === undefined ? '<div class="pc-box"><div class="skel-zone sm"></div></div>'
    : '<div class="pc-box"><p class="pc-sub">We have no page for that week.</p></div>';

  // Matchup: points facing this opponent adds (+) or takes away (-) vs an average opponent, in its week-scaled
  // color (mu_c: green helps, red hurts, deeper = bigger). Week files from before 2026-10-14 carry the old rank.
  const muSigned = v => Math.abs(v) < 0.05 ? '0.0' : `${v > 0 ? '+' : ''}${f1(v)}`;
  const muHtml = (p, opp) => p.mu != null
    ? `<span class="muv" style="color:${esc(p.mu_c || '')}" title="Facing ${esc(opp || p.opp)} instead of an average opponent: ${muSigned(p.mu)} pts">${muSigned(p.mu)}</span>`
    : p.dvp ? `<span style="color:${esc(p.dvp_color || '')}" title="Old-style matchup rank: their defense vs ${esc(p.pos)}s (1st = toughest)">${esc(p.dvp)}</span>` : '';
  const gameHref = (g, d = DATA) => `${siteRoot()}game.html?d=${encodeURIComponent(d.__rel || CFG.data)}&g=${encodeURIComponent(g.id)}`;
  // A tappable summary tile: a label, one number (body) and a hidden detail that opens in a sheet (bottom of file)
  const tapTile = (k, body, title, detail, cls = '') => `<div class="pc-tap${cls}" role="button" tabindex="0" aria-haspopup="dialog" data-sheet="${esc(title)}">
      <div class="pc-k">${esc(k)}</div>${body}<template>${detail}</template></div>`;
  // ... or opens one of the page's tabs (goto), optionally in a game log view (lv)
  const goTile = (k, body, goto, lv = '') => `<div class="pc-tap" role="button" tabindex="0" data-goto="${goto}"${lv ? ` data-lv-go="${lv}"` : ''}>
      <div class="pc-k">${esc(k)}</div>${body}</div>`;
  // Last 5 tile: his latest regular-season game's points over his last five, bars against our projection then
  // his last five regular-season games as bar slots (points, our projection then)
  const last5Slots = (L, pos) => {
    if (!L) return [];
    const w = weights(), gs = L.seasons.flatMap(S => S.g.map(g => ({ s: S.s, g }))).sort((a, b) => b.s - a.s || b.g.w - a.g.w).slice(0, 5).reverse();
    const built = (DATA && DATA.score && DATA.score.built) || HALF;
    const pj = g => g.pjl ? g.pj * (pts(g.pjl, w, pos) / Math.max(0.1, pts(g.pjl, built, pos))) : null;
    return gs.map(({ s, g }) => { const v = pts(g.c, w, pos), p = pj(g);
      return { w: g.w, v, pj: p, title: `${s} week ${g.w}: ${f1(v)} pts${p != null ? ` · we projected ${f1(p)}` : ''}` }; });
  };
  // Form tile (owner 2026-10-17: Season and Last 5 combined): season points per game, the last five games as bars;
  // the season breakdown (with every week's points) in its sheet, else the game log
  const formTile = (L, pos, fpg, games, title, detail) => {
    const slots = last5Slots(L, pos);
    if (fpg == null && !slots.length) return '';
    const bars = slots.length ? `<div class="pc-tapbars">${miniBars(slots, { slotW: 22, H: 40, cls: 'mb-pts mb-sm' })}</div>` : '';
    const body = fpg != null ? `<div class="pc-big">${f1(fpg)} <small>FP/G</small></div><div class="pc-tapsub">${f0(games)} games · last ${slots.length}</div>${bars}`
      : `<div class="pc-big">${f1(slots[slots.length - 1].v)} <small>pts</small></div><div class="pc-tapsub">last game · last ${slots.length}</div>${bars}`;
    return fpg != null && detail ? tapTile('Form', body, title, detail) : goTile('Form', body, 'log', 'g');
  };
  // ---- Health (owner 2026-10-17: a tile instead of the Injuries tab, and a briefing that brings you up to speed) ----
  // ros.json for our return model's week (the first upcoming week he's more likely than not to play)
  const RJ = { d: undefined };
  const loadRos = () => { if (RJ.d !== undefined) return; RJ.d = null;
    NFLE.load('data/ros.json').then(j => { RJ.d = j; rerenderCard(); }).catch(() => {}); };
  // a week only when our return model is following him: every later week at 100% means no injury on record (e.g.
  // hurt in the game before his bye, before any report lists him), not a return estimate; ESPN's date fills in then
  const backWeek = pid => { const r = RJ.d && RJ.d.players[pid];
    if (!r || !r.w.some(z => z[1] < 0.995)) return null;
    const e = r.w.find(z => z[1] >= 0.5); return e && e[0] > RJ.d.from ? e[0] : e ? null : 'no'; };
  // the NFL week a date falls in (weeks run Tuesday to Monday), from this week's earliest kickoff in ros.json
  const weekOfDate = d => {
    if (!RJ.d) return null;
    if (RJ.t0 === undefined) { const ks = Object.values(RJ.d.players).map(x => x.k).filter(Boolean).sort();
      RJ.t0 = ks.length ? Date.parse(ks[0]) - 2 * 864e5 : null; }  // the Tuesday before Thursday night
    if (RJ.t0 == null) return null;
    return RJ.d.from + Math.max(0, Math.floor((Date.parse(d + 'T12:00:00Z') - RJ.t0) / (7 * 864e5)));
  };
  const espnDate = d => new Date(d + 'T12:00:00').toLocaleDateString([], { month: 'short', day: 'numeric' });
  const healthOf = (pid, p, L, espn) => {
    loadInj(); loadRos();
    const now = espn && DINJ && DINJ[espn];
    const wk = DATA ? +DATA.week : null;
    const ep = (L && L.inj || []).find(e => L && e.s === L.cur && wk && e.w1 >= wk - 1);  // listed this week or last
    const des = p && /^\s*(Questionable|Doubtful|Out|IR|PUP|NFI)/i.test(p.status || '');
    const inj = (p && p.inactive >= 0.05) || des || (now && now.status && now.status !== 'Active') || (!p && ep);
    const rw = !p && RJ.d && RJ.d.players[pid] && RJ.d.players[pid].w.find(z => z[0] === RJ.d.from);  // off the board: the return model
    const play = p && p.inactive != null ? 1 - p.inactive : rw ? rw[1] : null;
    const what = [...new Set([now && now.type, now && now.detail && now.detail !== 'Not Specified' ? now.detail : '', now && now.side && now.side !== 'Not Specified' ? now.side : '']
      .filter(Boolean))].join(' · ') || (ep && ep.part) || '';  // ESPN often repeats the type as the detail
    return { inj, play, what, now, ep, back: backWeek(pid), wk };
  };
  const healthTile = (pid, p, L, espn) => {
    const h = healthOf(pid, p, L, espn);
    const ret = h.back && h.back !== 'no' ? `back ~wk ${h.back}` : h.now && h.now.return_date ? `est. ${espnDate(h.now.return_date)}` : '';
    const big = !h.inj ? '<div class="pc-big good">Healthy</div>'
      : h.play != null && h.play > 0.01 ? `<div class="pc-big ${h.play >= 0.75 ? '' : 'bad'}">${Math.round(h.play * 100)}% <small>to play</small></div>`
      : '<div class="pc-big bad">Out</div>';
    const sub = !h.inj ? 'no injury listed' : [h.what, ret].filter(Boolean).join(' · ') || 'on the injury report';
    return tapTile('Health', `${big}<div class="pc-tapsub">${esc(sub)}</div>`, 'Health', injuryBrief(pid, p, L, espn, h));
  };
  // Practice and games, dated (owner 2026-10-17: "the date the report was out, show the last 6, include games in that
  // timeline"): his latest six practice days and games this season plus his next game (career log prac,
  // tools/player_logs.py practice_timeline)
  const PR_WORD = { D: 'Did not practice', L: 'Limited', F: 'Full' };
  const practiceTl = L => {
    const ev = (L && L.prac) || [];
    if (!ev.length) return '';
    const today = new Date().toISOString().slice(0, 10);
    const past = ev.filter(e => e[1] <= today).slice(-6), next = ev.find(e => e[1] > today && e[0] === 'g');
    const day = d => new Date(d + 'T12:00:00').toLocaleDateString([], { weekday: 'short', month: 'short', day: 'numeric' });
    const row = e => e[0] === 'p'
      ? `<div class="pt-row"><span class="pt-d">${day(e[1])}</span><span class="pr-chip pr-${e[2]}">${e[2] === 'D' ? 'DNP' : e[2] + 'P'}</span><span>${PR_WORD[e[2]] || ''}${e[3] ? ` · <b>${esc(e[3])}</b>` : ''}</span></div>`
      : `<div class="pt-row pt-g"><span class="pt-d">${day(e[1])}</span><span class="pt-gm">${esc(e[3])} ${tmL(e[2])}</span><span>${e[4] === '' ? '<b>next game</b>' : e[4] === 'out' ? '<b class="bad">did not play</b>' : `played · ${esc(e[4])}% of snaps`}</span></div>`;
    // newest first (owner 2026-10-17): the next game on top, then the latest six going back
    return `<div class="pc-box"><div class="pc-k">Practice and games</div><div class="pt-list">${next ? row(next) : ''}${past.slice().reverse().map(row).join('')}</div></div>`;
  };
  // the briefing: this week, the timeline (since when, games missed, return estimates), the latest news, then history
  const injuryBrief = (pid, p, L, espn, h) => {
    const now = h.now, ep = h.ep;
    // This week as a header (owner 2026-10-17: "make that look nicer and use the free space"): status, chance to play
    // and expected return side by side, then what and when he got hurt, then this week's practice in plain words
    const des = ((p && p.status) || '').replace(/\s*\(.*$/, '').replace(/\s*\(ESPN\)/, '').trim()
      || (now && now.status && now.status !== 'Active' ? now.status : '') || (h.inj ? 'Listed' : 'Healthy');
    const desCls = /^Out|Injured|IR/i.test(des) ? 'out' : /^Doubt/i.test(des) ? 'd' : /^Quest/i.test(des) ? 'q' : h.inj ? 'q' : 'ok';
    const pr = ((L && L.prac) || []).filter(e => e[0] === 'p' && e[1] >= new Date(Date.now() - 6 * 864e5).toISOString().slice(0, 10));
    const WORD = { D: 'did not practice', L: 'limited', F: 'full' };
    const prLine = pr.length ? 'Practiced: ' + Object.entries(pr.reduce((m, e) => { (m[e[2]] = m[e[2]] || []).push(new Date(e[1] + 'T12:00:00').toLocaleDateString([], { weekday: 'short' })); return m; }, {}))
      .map(([c, ds]) => `${WORD[c] || c} ${ds.join(', ')}`).join('; ') : '';
    // when he got hurt, as a date (owner 2026-10-17: "rather than trying to decipher it"): the in-game note's week, dated
    // from his games in the timeline; else the day he first appeared on the report
    const QN = { 1: '1st', 2: '2nd', 3: '3rd', 4: '4th', 5: 'overtime' };
    const gEv = w => ((L && L.prac) || []).find(e => e[0] === 'g' && e[5] === w);
    const longDay = d => new Date(d + 'T12:00:00').toLocaleDateString([], { weekday: 'short', month: 'short', day: 'numeric' });
    const firstListed = ep && ((L && L.prac) || []).find(e => e[0] === 'p' && e[1] >= (gEv(ep.w0 - 1) || [0, ''])[1]);
    const hurtWhen = ep && ep.ig ? (g => g ? `Hurt ${longDay(g[1])} ${g[3]} ${g[2]}${ep.ig[1] ? ` (${QN[ep.ig[1]] || `Q${ep.ig[1]}`}${ep.ig[1] < 5 ? ' quarter' : ''})` : ''}`
        : `Hurt in the week ${ep.ig[0]} game`)(gEv(ep.ig[0]))
      : ep && firstListed ? `First listed ${longDay(firstListed[1])}` : '';
    const hurt = [h.what, hurtWhen].filter(Boolean).join(' · ');
    // third cell (owner 2026-10-17: "expected back being a date seems weak"): a game, not a date. Likely to play this
    // week: his next game. Out: the game he's projected back for (our return model), ESPN's date as its game too.
    const games = ((L && L.prac) || []).filter(e => e[0] === 'g'), today = new Date().toISOString().slice(0, 10);
    const gameTxt = g => g ? `Week ${g[5]} ${g[3]} ${g[2]}` : '';
    // a week's game from the dated timeline, else his schedule in the career log (IR players have no practice report)
    const upG = w => { const u = ((L && L.up) || []).find(x => x.w === w && !x.bye); return u ? ['g', '', u.o, u.h === 0 ? '@' : 'vs', '', u.w] : null; };
    const nextG = games.find(e => e[1] > today);
    const ourG = h.back && h.back !== 'no' ? games.find(e => e[5] === h.back) || upG(h.back) : null;
    // our return model's chance he plays that game (owner 2026-10-17: the play % beside "Expected back")
    const backRow = ourG && RJ.d && RJ.d.players[pid] && RJ.d.players[pid].w.find(z => z[0] === h.back);
    const backP = backRow ? `${NFLE.fmt.toPlay(1 - backRow[1])} to play` : 'our return model';
    const espnG = now && now.return_date ? games.find(e => e[1] >= now.return_date) || upG(weekOfDate(now.return_date)) : null;
    const onBye = ((L && L.up) || []).some(x => x.w === h.wk && x.bye);  // no game this week: nothing to play
    const out = h.inj && (h.play == null || h.play < 0.5);
    const third = out
      ? (ourG || espnG || h.back === 'no' ? `<div><small>Expected back</small><b>${esc(ourG ? gameTxt(ourG) : h.back === 'no' ? 'Not this season' : gameTxt(espnG))}</b>
          <span class="muted">${ourG ? backP + (espnG && espnG[5] !== ourG[5] ? `<br>ESPN: ${esc(gameTxt(espnG).toLowerCase())}` : '') : h.back === 'no' ? 'our return model' : 'ESPN estimate'}</span></div>` : '')
      : nextG ? `<div><small>Next game</small><b>${esc(new Date(nextG[1] + 'T12:00:00').toLocaleDateString([], { weekday: 'short' }))} ${esc(nextG[3])} ${esc(nextG[2])}</b><span class="muted">week ${nextG[5]}</span></div>` : '';
    const thisWeek = `<div class="pc-box"><div class="pc-k">This week</div>
        <div class="ij-hero">
          <div><small>Status</small><b class="ij-st ij-${desCls}">${esc(des)}</b></div>
          <div><small>Chance to play</small><b class="ij-big ${!h.inj || (h.play != null && h.play >= 0.75) ? 'good' : h.play != null && h.play < 0.5 ? 'bad' : ''}">${h.play != null ? NFLE.fmt.toPlay(1 - h.play) : onBye ? '<span class="muted">Bye</span>' : h.inj ? '&ndash;' : '&gt;99%'}</b></div>
          ${third}
        </div>
        ${hurt ? `<div class="ij-what">${esc(hurt)}</div>` : ''}
        <p class="pc-sub">${h.inj ? esc(prLine || (p && p.inactive_why) || 'On the injury report.') : 'Not on the injury report and practicing fully.'}</p></div>`;
    const tl = [];
    if (ep) tl.push(`Listed since week ${ep.w0}${ep.missed ? `, ${ep.missed} game${ep.missed === 1 ? '' : 's'} missed` : ''}${ep.list ? ` · on ${esc(ep.list)}` : ''}`);
    const timeline = h.inj && (tl.length || (now && now.comment)) ? `<div class="pc-box"><div class="pc-k">Timeline</div>${tl.map(t => `<div class="ij-line">${t}</div>`).join('')}
        ${now && now.comment ? `<p class="pc-sub">${esc(now.comment)}</p>` : ''}</div>` : '';
    const news = espn ? `<div class="pc-box"><div class="pc-k">Latest news</div><div class="pc-news" data-espn="${esc(espn)}" data-n="2"></div></div>` : '';
    return thisWeek + practiceTl(L) + timeline + news + (L && (L.inj || L.dur) ? injuryTab(L, espn, true) : '');
  };
  // Grade tile (owner 2026-10-16: OVR moved here from the header, then the Grade tab folded into its sheet): his OVR;
  // the sheet holds the whole grade (gradeTab) from his history shard (GRH, loaded with the page)
  const gradeTile = pid => {
    const r = GR.cur && GR.cur.players[pid];
    if (GR.cur === undefined || GR.cur === null) return '';
    const detail = GRH[pid] ? gradeTab(pid, GRH[pid]) : '<div class="pc-box"><p class="pc-sub">Loading grade&hellip;</p></div>';
    return tapTile('Grade', r ? `<div class="pc-big ${r[9] ? '' : grTone(r[0])}">${ovr(r[0])}${uqMark(r)} <small>OVR</small></div><div class="pc-tapsub">${GR.cur.season} · ${esc(r[1])}</div>`
      : '<div class="pc-big">– <small>OVR</small></div><div class="pc-tapsub">Not graded</div>', 'NFL Edge grade', detail);
  };
  // The player's weekly section for the selected week (projection, matchup, availability, season to date).
  const playerWeek = (pid, p, d, L) => {
    const g = teamGame(p.team, d), opp = g && (g.away.team === p.team ? g.home : g.away);
    const s = scaled(p, d), w = weights(), live = d === DATA;
    const ln = live ? LIVE.lines[p.espn] : null, st = live && g ? LIVE.byGame[g.id] : null;
    const ac = ln ? ln.line : (p.sc.ac || null);
    let now = '';
    if (ac) {
      const v = pts(ac, w, p.pos), isLive = st && st.state === 'in';
      const tag = isLive ? `<span class="live-dot"></span>Live · ${esc(st.short || '')}` : 'Final';
      now = `<div class="pc-now${isLive ? ' is-live' : ''}"><div class="pc-k">${tag}</div><div class="pc-big">${f1(v)} <small>pts</small></div>
        <div class="pc-sub">${ln ? `${esc(statLineText(ln, p.pos))}${isLive ? '' : ' · '}` : ''}${isLive ? '' : (v > s.q[3] ? '<b class="good">above his likely range</b>' : v < s.q[1] ? '<b class="bad">below his likely range</b>' : 'within his likely range')}</div></div>`;
    }
    // Availability rides on the projection: a chip always, the reason spelled out once there's real risk.
    const ia = p.inactive || 0, av = ia >= 0.5 ? 'av-out' : ia >= 0.05 ? 'av-q' : 'av-ok';
    const avChip = `<span class="pc-av ${av}" title="${esc(p.inactive_why || '')}">${NFLE.fmt.toPlay(ia)} to play</span>`;
    const isLive = st && st.state === 'in';
    // One rank pill (our rank at his position), colored by roster tier: starter / flex range / bench.
    const slotTxt = { start: 'starter', flex: 'flex range', bench: 'bench depth' }[p.slot] || '';
    const rankPill = `<span class="pc-rk t-${esc(p.slot)}" title="Our #${p.rank} ${esc(p.pos)} for ${esc(wkLabel(d).toLowerCase())} · ${esc(p.tier)} tier${slotTxt ? ` (${slotTxt})` : ''}">${esc(p.pos)} #${p.rank}</span>`;
    const flags = [injTag(p.status),
                   p.boost >= 1 ? `<span class="flag f-up" title="Raised by volume vacated by ${esc(p.boost_from)}">+${f1(p.boost)} from injuries</span>` : '',
                   p.low_sample ? '<span class="flag" title="Few games to learn from: a wider range">low data</span>' : ''].join('');
    const exp = expectedCells(p);
    // Summary (owner 2026-10-16): one number per tile, the full story in a sheet on tap (pc-tap / the sheet below)
    const risk = ia >= 0.05 && d !== DATA ? avChip : '';  // this week the Health tile carries it
    const projDetail = `<div class="pc-box pc-proj"><div class="pc-kr"><span class="pc-k">Projection${ia >= 0.05 ? ' (if active)' : ''}</span>${avChip}</div>
          <div class="pc-bigrow"><div class="pc-big">${f1(s.proj)} <small>pts</small></div>${rankPill}${flags ? `<span class="pc-flags">${flags}</span>` : ''}</div>
          ${rangeSvg(s.q, s.proj)}
          ${sg([sgRow(null, [cell(f1(s.q[0]), 'Floor'), cell(`${f0(s.q[1])}–${f0(s.q[3])}`, 'Middle', `Middle half of outcomes: ${f1(s.q[1])} to ${f1(s.q[3])}`),
                cell(f1(s.q[4]), 'Ceiling'), cell(esc(p.conf), 'Confidence')])], 4, { labels: false, cls: 'sg-tight' })}
          ${ia >= 0.05 ? `<div class="pc-sub pc-why ${av}">${esc(p.inactive_why)}</div>` : ''}</div>
        <div class="pc-box"><div class="pc-k">Expected line</div>${exp.length ? sg([sgRow(null, exp)], 4, { labels: false, cls: 'sg-tight sg-wrap' }) : '<p class="pc-sub">No line projected.</p>'}</div>`;
    const muDetail = `<div class="pc-box"><div class="pc-mu">${opp ? tmL(opp.team, logo(opp.logo_url, opp.logo_bg, 22, opp.team)) : ''}<b>${esc(p.home)} ${opp ? `<button type="button" class="tm-open pc-tlink" data-tm="${esc(opp.team)}">${esc(opp.team)}</button>` : tmL(p.opp)}</b>
          ${p.mu != null ? `<span class="pc-muv">${muHtml(p, opp && opp.team)} <small>pts</small></span>` : muHtml(p)}</div>
        <div class="pc-sub">${p.mu != null ? `Facing ${tmL(p.opp)} instead of an average opponent ${Math.abs(p.mu) < 0.05 ? 'changes nothing' : `${p.mu > 0 ? 'adds' : 'takes away'} ${f1(Math.abs(p.mu))} pts`}: its Vegas total, the play volume and the defense ratings together.`
            : `This defense ${p.mpts >= 0 ? 'adds' : 'takes away'} ${f1(Math.abs(p.mpts || 0))} pts vs an average one.`}</div></div>`;
    const e = p.ext || {}, fpg = p.sc.ss && p.sc.g ? pts(p.sc.ss, w, p.pos) / p.sc.g : null;
    const html = `
      ${now}
      <div class="pc-tiles">
        ${tapTile('Projection', `<div class="pc-big">${f1(s.proj)} <small>pts</small></div><div class="pc-tapsub">${rankPill}${risk}</div>`, `${wkLabel(d)} projection`,
            projDetail + muDetail.replace('<div class="pc-box">', '<div class="pc-box"><div class="pc-k">Matchup effect</div>'))}
        ${formTile(L, p.pos, fpg, e.games || p.sc.g, `${d.season} season before week ${d.week}`, `<div class="pc-box pc-season">${seasonHtml(p, d, L)}</div>`)}
        ${d === DATA ? healthTile(pid, p, L, p.espn) : ''}
        ${GRADED[p.pos] ? gradeTile(pid) : ''}
      </div>
      ${g ? `<div class="pc-mt">${NFLE.ui.matchTile(g, gameHref(g, d))}</div>` : ''}`;
    return html;
  };
  // A player we didn't list that week: say so, and show what he did from the career log when he played.
  const playerOff = (L, d) => {
    const S = L && (L.seasons || []).find(x => +x.s === +d.season), g = S && S.g.find(x => x.w === +d.week);
    const pos = L && L.pos;
    const played = g ? `<div class="pc-now"><div class="pc-k">Final</div><div class="pc-big">${f1(pts(g.c, weights(), pos))} <small>pts</small></div>
      <div class="pc-sub">${g.h === 0 ? '@' : 'vs'} ${tmL(g.o)} · ${ord(g.rk)} among ${esc(pos)}s${g.gid ? ` · <a href="${esc(gcUrl(g.gid, g.f || ''))}">Gamecast &rsaquo;</a>` : ''}</div></div>` : '';
    // the tiles stay (owner 2026-10-17: "bye players missing tiles feels very wrong"): the Projection tile says why there
    // is no number (bye, back when and against whom; else the reason), the rest as for any week
    const ups = (L && L.up) || [], wk = +d.week;
    const bye = ups.some(u => u.w === wk && u.bye) || ((S && S.m) || []).some(m => m.w === wk && m.bye);
    const nxt = ups.find(u => u.w > wk && !u.bye);
    const h = d === DATA && L && L.pid ? healthOf(L.pid, null, L, L.espn) : null;
    const projBody = bye ? `<div class="pc-big">Bye</div><div class="pc-tapsub">${nxt ? `back week ${nxt.w} ${nxt.h === 0 ? '@' : 'vs'} ${esc(nxt.o)}` : 'no game this week'}</div>`
      : `<div class="pc-big">–</div><div class="pc-tapsub">${h && h.inj ? 'out this week' : 'not projected this week'}</div>`;
    const projTile = goTile('Projection', projBody, 'log', 'g');
    const cur = S ? S.g : [], fpg = cur.length ? cur.reduce((t, x) => t + pts(x.c, weights(), pos), 0) / cur.length : null;
    const tiles = L ? `<div class="pc-tiles">${projTile}${formTile(L, pos, fpg, cur.length, '', '')}${h ? healthTile(L.pid, null, L, L.espn) : ''}${GRADED[pos] ? gradeTile(L.pid) : ''}</div>` : '';
    return `${played}${tiles}${bye ? '' : `<div class="pc-box"><p class="pc-sub">Not on our ${esc(wkLabel(d).toLowerCase())} board: ruled out, not on a roster yet, or projected too low to list.</p></div>`}`;
  };
  // Header extras from the career log doc (tools/player_logs.py): photo, jersey number, bio, recent snap share and,
  // for QBs, how often he scrambles. All current, like the rest of the header.
  // NFL headshots come as ~4 MB originals; the image server's face crop is sharp at card size and ~13 KB
  // (player logs already store the cropped URL; this also covers older log files).
  const faceCrop = u => u.replace(/\/(upload|private)\/f_auto,q_auto\//, '/$1/c_thumb,g_face,z_0.75,w_160,h_160,f_auto,q_auto/');
  // the full-size headshot for the tap-to-zoom view (owner 2026-10-15): NFL's original upload, else ESPN's full PNG
  const photoBig = (L, espn) => (L && L.bio && L.bio.photo ? L.bio.photo : '') || (espn ? `https://a.espncdn.com/i/headshots/nfl/players/full/${encodeURIComponent(espn)}.png` : '');
  // NFL image-service URLs carry their crop / size in the path: drop it for the original upload
  const uncrop = u => String(u || '').replace(/\/(upload|private)\/[^/]*c_thumb[^/]*\//, '/$1/f_auto,q_auto,w_1000/');
  const photoUrl = (L, espn) => (L && L.bio && L.bio.photo ? faceCrop(L.bio.photo) : '')
    || (espn ? `https://a.espncdn.com/i/headshots/nfl/players/full/${encodeURIComponent(espn)}.png` : '');
  // Profile box under the header (current, like the header): bio, draft slot, and the current contract
  // (OverTheCap via nflverse; $M). Desktop: one row of six; phones: rows of three (CSS --n).
  const money = m => m >= 100 ? `$${f0(m)}M` : m >= 1 ? `$${f1(m)}M` : `$${f0(m * 1000)}K`;
  // Compact header (owner 2026-10-16, after a Sleeper reference): age / height / weight / NFL years in a slim strip
  // under the name; draft, college and contract in their own section lower on the Week tab.
  const bioStrip = (L, cls = '') => {
    if (!L || !L.bio) return '';
    const b = L.bio, it = [];
    const item = (v, k, t = '') => `<div${t ? ` title="${esc(t)}"` : ''}><small>${k}</small><b>${v}</b></div>`;
    if (b.born) it.push(item(((Date.now() - new Date(b.born + 'T12:00:00')) / 31557600000).toFixed(1), 'Age', `Born ${b.born}`));
    if (b.ht) it.push(item(esc(`${Math.floor(b.ht / 12)}'${b.ht % 12}"`), 'Height'));
    if (b.wt) it.push(item(`${esc(b.wt)}<i> lb</i>`, 'Weight'));
    if (b.exp != null) it.push(b.exp === 0 && b.exp_s === L.cur ? item('Rookie', 'Exp') : item(esc(b.exp), 'Exp', b.exp_s === L.cur ? 'NFL seasons' : `NFL seasons, as of ${b.exp_s}`));
    return it.length ? `<div class="pc-bio${cls}">${it.join('')}</div>` : '';
  };
  const profileBox = L => {
    if (!L || !L.bio) return '';
    const b = L.bio, bio = [];
    const dr = b.draft;
    if (dr) bio.push(dr.u ? cell('UDFA', 'Draft', 'Undrafted free agent')
      : cell(`R${dr.r}:${dr.p}`, `Draft '${String(dr.y).slice(2)}`, `${dr.y} draft: round ${dr.r}, pick ${dr.p} (${ord(dr.o)} overall)`));
    // Transfers list every school, final one first ("Wyoming; Reedley CC"): show that one, all of them on hover.
    if (b.college) bio.push(cell(esc(b.college.split(';')[0].trim()), 'College', b.college));
    // Free agent = the season after the last one he's paid (void years excluded); older log files lack it and show
    // the deal's length instead.
    const k = b.deal, deal = k ? [cell(money(k.apy), 'Per year'), k.val != null ? cell(money(k.val), 'Total', k.yrs ? `${k.yrs}-year deal as signed (an extension counts only its added years)` : '') : '',
      k.gtd != null ? cell(money(k.gtd), 'Guaranteed') : '', k.cap != null ? cell(`${(k.cap * 100).toFixed(1)}%`, 'Of cap', 'Per-year value as a share of the salary cap when signed') : '',
      cell(esc(k.from), 'Signed'),
      k.fa ? cell(esc(k.fa), 'Free agent', `Hits free agency in ${k.fa} if not extended (paid through ${k.fa - 1}; void years excluded)`)
        : k.yrs ? cell(esc(k.yrs), 'Years') : ''] : [];
    if (!bio.length && !deal.length) return '';
    return `<div class="pc-box pc-profile"><div class="pc-k">Draft & contract</div>${sg([bio.length ? sgRow(null, bio) : '', deal.length ? sgRow(null, deal) : ''], 6, { labels: false, cls: 'sg-prof' })}</div>`;
  };
  // Week tab, below the weekly section: his three latest news items and this season's games (his last five before
  // his first game of the season), each with a way into the full tab. Both are current, whatever week is picked.
  const newsMini = espn => espn ? `<div class="pc-box pc-mini"><div class="pc-k">Latest news</div><div class="pc-news" data-n="3"></div>
        <button type="button" class="pc-more" data-goto="news">Show more</button></div>` : '';
  const logMini = (pid, L, row) => {
    const cur = L && L.seasons.some(S => S.s === L.cur && S.g.length);
    const log = !LOGS[pid] ? '<div class="skel-zone sm"></div>'
      : L && L.seasons.length ? logHtml(L, row, cur ? { season: true } : { last: 5 }) : '';
    return log ? `<div class="pc-box pc-mini"><div class="pc-k">${cur ? 'This season' : 'Last 5 games'}</div><div class="pc-log">${log}</div>
        <button type="button" class="pc-more" data-goto="log">Show more</button></div>` : '';
  };
  const weekExtras = (pid, L, row, espn) => newsMini(espn) + logMini(pid, L, row);
  // ------------------------------------------------------------------------------------- non-fantasy player pages
  // Defense, line, specialists (and skill players without fantasy stats): the career log doc carries a kind and
  // its stat keys (tools/player_logs.py other_logs); no projections, points or ranks.
  const KIND_COLS = {
    def: { tk: ['Tk', 'Solo tackles'], ast: ['Ast', 'Assisted tackles'], tfl: ['TFL', 'Tackles for loss'], sk: ['Sk', 'Sacks'], qbh: ['QBH', 'QB hits'],
           int: ['Int', 'Interceptions'], pd: ['PD', 'Passes defended'], ff: ['FF', 'Forced fumbles'], fr: ['FR', 'Fumble recoveries'], td: ['TD', 'Defensive TDs'] },
    k: { fgm: ['FGM', 'Field goals made'], fga: ['FGA', 'Field goals attempted'], lng: ['Lng', 'Longest field goal'], xpm: ['XPM', 'Extra points made'], xpa: ['XPA', 'Extra points attempted'] },
    p: { pu: ['Punts', 'Punts'], yd: ['Yds', 'Punt yards'], net: ['Net', 'Net punt yards'], i20: ['In20', 'Inside the 20'], lng: ['Lng', 'Longest punt'] },
    off: { car: ['Car', 'Carries'], ryd: ['Rush yd', 'Rushing yards'], rec: ['Rec', 'Receptions'], yd: ['Rec yd', 'Receiving yards'], td: ['TD', 'Receiving TDs'] },
  };
  const RET_COLS = { kr: ['KR', 'Kick returns'], kry: ['KR yd', 'Kick return yards'], pr: ['PR', 'Punt returns'], pry: ['PR yd', 'Punt return yards'] };
  const KIND_NAME = { def: 'Defense', k: 'Kicking', p: 'Punting', ol: 'Offensive line', ls: 'Long snapper', off: 'Offense' };
  const kindTotals = (L, games) => {
    const t = {}, keys = L.keys || [], rk = L.ret_keys || [];
    games.forEach(g => {
      keys.forEach((k, i) => { const v = (g.d || [])[i] || 0; t[k] = k === 'lng' ? Math.max(t[k] || 0, v) : (t[k] || 0) + v; });
      rk.forEach((k, i) => { t['r_' + k] = (t['r_' + k] || 0) + ((g.r || [])[i] || 0); });
    });
    const sn = games.map(g => g.sn).filter(v => v != null);
    t.g = games.length; t.sn = sn.length ? sn.reduce((a, b) => a + b, 0) / sn.length : null;
    return t;
  };
  const nfmt = v => v == null ? '–' : Number.isInteger(v) ? String(v) : v.toFixed(1);
  // the stat grid for a stretch of games: games + snap share, his kind's totals (with rates), returns when he had any
  const kindGrid = (L, t) => {
    const cols = KIND_COLS[L.kind] || {};
    const main = [cell(f0(t.g), 'Games'), t.sn != null ? cell(`${Math.round(t.sn)}%`, 'Snaps', `Average share of ${L.kind === 'def' ? 'defensive' : L.kind === 'ol' || L.kind === 'off' ? 'offensive' : 'special-teams'} snaps (2013 on)`) : ''];
    const stats = (L.keys || []).map(k => cols[k] ? cell(nfmt(t[k] || 0), cols[k][0], cols[k][1]) : '');
    if (L.kind === 'k' && t.fga) stats.splice(2, 0, cell(`${Math.round(100 * t.fgm / t.fga)}%`, 'FG%'));
    if (L.kind === 'p' && t.pu) stats.splice(2, 0, cell(f1(t.yd / t.pu), 'Avg'), cell(f1(t.net / t.pu), 'Net avg'));
    const ret = t.r_kr || t.r_pr ? [t.r_kr ? cell(f0(t.r_kr), 'KR') : '', t.r_kr ? cell(f1(t.r_kry / t.r_kr), 'KR avg') : '',
      t.r_pr ? cell(f0(t.r_pr), 'PR') : '', t.r_pr ? cell(f1(t.r_pry / t.r_pr), 'PR avg') : ''] : [];
    return sg([sgRow(null, main), stats.length ? sgRow(KIND_NAME[L.kind], stats) : '', ret.length ? sgRow('Returns', ret) : ''], 5, { labels: true, cls: 'sg-season' });
  };
  // game log table for a kind: Wk, Opp, Snap, his stats, returns (only when he had any in those games)
  const kindLog = (L, seasons, opts = {}) => {
    const cols = KIND_COLS[L.kind] || {}, keys = (L.keys || []).filter(k => cols[k]);
    const hasRet = seasons.some(S => S.g.some(g => g.r) || (S.pg || []).some(g => g.r));
    const rk = hasRet ? (L.ret_keys || []) : [];
    const head = `<tr class="lg-ch"><th>Wk</th><th>Opp</th><th class="num">Snap</th>${keys.map(k => `<th class="num" title="${esc(cols[k][1])}">${cols[k][0]}</th>`).join('')}${rk.map(k => `<th class="num" title="${esc(RET_COLS[k][1])}">${RET_COLS[k][0]}</th>`).join('')}</tr>`;
    const n = 3 + keys.length + rk.length;
    const body = seasons.map(S => {
      const t = kindTotals(L, S.g), team = S.g.length ? S.g[S.g.length - 1].t : '';
      const row = (g, label) => `<tr${tileAttrs(g)}><td>${esc(label)}</td><td class="lg-opp tm-opp"><button type="button" class="tm-open" data-tm="${esc(g.o)}">${g.h === 0 ? '@' : ''}${esc(g.o)}</button></td>
        <td class="num">${g.sn != null ? g.sn : '–'}</td>${keys.map(k => `<td class="num">${nfmt((g.d || [])[(L.keys || []).indexOf(k)])}</td>`).join('')}${rk.map((k, i) => `<td class="num">${g.r ? nfmt(g.r[i]) : '–'}</td>`).join('')}</tr>`;
      // season totals under the column heads (owner 2026-10-16), as in the fantasy log: sums, snap share averaged
      const tot = gs => {
        if (gs.length < 2 || opts.compact) return '';
        const sum = (g2, i) => gs.reduce((a, g) => a + (+((g[g2] || [])[i]) || 0), 0), sn = gs.filter(g => g.sn != null);
        return `<tr class="lg-tot"><td>Tot</td><td></td><td class="num">${sn.length ? Math.round(sn.reduce((a, g) => a + g.sn, 0) / sn.length) : '–'}</td>${keys.map(k => `<td class="num">${nfmt(sum('d', (L.keys || []).indexOf(k)))}</td>`).join('')}${rk.map((k, i) => `<td class="num">${nfmt(sum('r', i))}</td>`).join('')}</tr>
          <tr class="lg-gap"><td colspan="${n}"></td></tr>`;
      };
      const miss = g => `<tr class="lg-miss"${tileAttrs(g)}><td>${g.w}</td>${g.o ? `<td class="lg-opp tm-opp"><button type="button" class="tm-open" data-tm="${esc(g.o)}">${g.h === 0 ? '@' : ''}${esc(g.o)}</button></td>` : '<td class="lg-opp">&ndash;</td>'}
        <td class="num">${g.sn != null ? g.sn : missTag(g)}</td>${'<td class="num">&ndash;</td>'.repeat(n - 3)}</tr>`;
      const trs = tot(S.g) + [...S.g, ...(opts.compact ? [] : (S.m || []))].sort((a, b) => b.w - a.w)  // newest first, every week
        .map(g => g.bye ? byeRow(g.w, n - 2) : g.miss != null ? miss(g) : row(g, g.w)).join('');
      const sum = opts.compact ? '' : ` · ${t.g} game${t.g === 1 ? '' : 's'}${keys.length ? ` · ${keys.slice(0, 4).map(k => `${nfmt(t[k] || 0)} ${cols[k][0]}`).join(', ')}` : ''}`;
      // playoffs first, their own block (not in the season totals above)
      const pg = opts.compact ? [] : (S.pg || []);
      const sub = (label, extra = '') => `<tr class="lg-sub"><td colspan="${n}"><span class="lg-pin">${label}${extra}</span></td></tr>`;
      const pt = pg.length ? kindTotals(L, pg) : null;
      const po = pg.length ? `${sub('Playoffs', ` · ${pg.length} game${pg.length === 1 ? '' : 's'}${keys.length ? ` · ${keys.slice(0, 4).map(k => `${nfmt(pt[k] || 0)} ${cols[k][0]}`).join(', ')}` : ''}`)}${head}${tot(pg)}${[...pg].reverse().map(g => row(g, g.po)).join('')}${S.g.length ? sub('Regular season') : ''}` : '';
      return `<tbody><tr class="lg-season"><td colspan="${n}"><span class="lg-pin"><b>${S.s}</b> ${tmL(team || (pg[0] && pg[0].t) || '')}${sum}</span></td></tr>${po}${S.g.length ? head + trs : ''}</tbody>`;
    }).join('');
    return `<div class="lg-scroll"><table class="lg">${body}</table></div>`;
  };
  // career by season: every season he was on an active roster (2002 on) or played, with team, games and totals
  const kindCareer = L => {
    const cols = KIND_COLS[L.kind] || {}, keys = (L.keys || []).filter(k => cols[k]).slice(0, 6);
    const ros = L.ros || {}, bySeason = Object.fromEntries(L.seasons.map(S => [S.s, S]));
    const years = [...new Set([...Object.keys(ros).map(Number), ...L.seasons.map(S => S.s)])].sort((a, b) => b - a);
    if (!years.length) return '';
    const rows = years.map(y => {
      const S = bySeason[y], t = S ? kindTotals(L, S.g) : null, r = ros[y];
      const team = r ? r[0] : S && S.g.length ? S.g[S.g.length - 1].t : '';
      return `<tr><td><b>${y}</b></td><td class="tm-opp">${team ? team.split('/').map(x => `<button type="button" class="tm-open" data-tm="${esc(x)}">${esc(x)}</button>`).join('/') : ''}</td>
        <td class="num">${t ? t.g : '–'}</td><td class="num">${r ? r[1] : '–'}</td><td class="num">${t && t.sn != null ? `${Math.round(t.sn)}%` : '–'}</td>
        ${keys.map(k => `<td class="num">${t ? nfmt(t[k] || 0) : '–'}</td>`).join('')}</tr>`;
    }).join('');
    return `<div class="lg-scroll"><table class="lg lg-career"><thead><tr class="lg-ch"><th>Season</th><th>Team</th><th class="num" title="Games with a stat or a snap">G</th>
      <th class="num" title="Weeks on the active roster">Wks</th><th class="num">Snap</th>${keys.map(k => `<th class="num" title="${esc(cols[k][1])}">${cols[k][0]}</th>`).join('')}</tr></thead><tbody>${rows}</tbody></table></div>`;
  };
  const kindOverview = (L, espn) => {
    const last = L.seasons.find(S => S.g.length);
    const season = last ? `<div class="pc-box"><div class="pc-k">${last.s === L.cur ? `${last.s} season so far` : `${last.s} season (his latest)`}</div>${kindGrid(L, kindTotals(L, last.g))}</div>` : '';
    const career = L.seasons.flatMap(S => S.g);
    const car = career.length ? `<div class="pc-box"><div class="pc-k">Career (regular season${career.some(g => g.sn != null) ? '; snaps from 2013' : ''})</div>${kindGrid(L, kindTotals(L, career))}</div>` : '';
    const recent = last ? `<div class="pc-box pc-mini"><div class="pc-k">${last.s === L.cur ? 'This season' : `${last.s} games`}</div><div class="pc-log">${kindLog(L, [last], { compact: true })}</div>
      <button type="button" class="pc-more" data-goto="log">Show more</button></div>` : '';
    const news = espn ? `<div class="pc-box pc-mini"><div class="pc-k">Latest news</div><div class="pc-news" data-n="3"></div><button type="button" class="pc-more" data-goto="news">Show more</button></div>` : '';
    const hist = kindCareer(L);
    return `${season}${!career.length ? '<div class="pc-box"><p class="pc-sub">No regular-season games with a recorded stat or snap yet.</p></div>' : ''}${recent}${news}${car}${hist ? `<div class="pc-box"><div class="pc-k">By season</div>${hist}</div>` : ''}`;
  };
  // Career by season for a fantasy-position player (retired / not on a roster this season): games, points per game
  // under the viewer's scoring, and his position's main totals. c / x = the log's stat line (scoring keys) / volume.
  const offCareer = L => {
    const pos = L.pos, w = weights();
    const cols = pos === 'QB' ? [['Pass yd', g => g.c[0]], ['Pass TD', g => g.c[1]], ['Int', g => g.c[2]], ['Rush yd', g => g.c[3]], ['Rush TD', g => g.c[4]]]
      : pos === 'RB' ? [['Car', g => g.x[2]], ['Rush yd', g => g.c[3]], ['Rush TD', g => g.c[4]], ['Rec', g => g.c[5]], ['Rec yd', g => g.c[6]], ['Rec TD', g => g.c[7]]]
        : [['Tgt', g => g.x[3]], ['Rec', g => g.c[5]], ['Rec yd', g => g.c[6]], ['Rec TD', g => g.c[7]], ['Rush yd', g => g.c[3]]];
    const sum = (gs, fn) => gs.reduce((t, g) => t + (fn(g) || 0), 0);
    const row = (label, gs, team) => `<tr><td><b>${label}</b></td><td class="tm-opp">${team ? `<button type="button" class="tm-open" data-tm="${esc(team)}">${esc(team)}</button>` : ''}</td>
      <td class="num">${gs.length}</td><td class="num">${gs.length ? f1(sum(gs, g => pts(g.c, w, pos)) / gs.length) : '–'}</td>${cols.map(([, fn]) => `<td class="num">${f0(sum(gs, fn))}</td>`).join('')}</tr>`;
    const seasons = L.seasons.filter(S => S.g.length);
    if (!seasons.length) return '';
    const all = seasons.flatMap(S => S.g);
    return `<div class="lg-scroll"><table class="lg lg-career"><thead><tr class="lg-ch"><th>Season</th><th>Team</th><th class="num">G</th><th class="num" title="Fantasy points per game, your scoring">FP/G</th>${cols.map(([n]) => `<th class="num">${n}</th>`).join('')}</tr></thead>
      <tbody>${seasons.map(S => row(S.s, S.g, S.g[S.g.length - 1].t)).join('')}${row('Career', all, '')}</tbody></table></div>`;
  };
  // ---------------------------------------------------------------------------------------- injuries tab
  // His injury history (tools/player_logs.py injury_history, 2009 on): episodes from the official injury reports and
  // weekly rosters, games missed per episode, and a durability score (share of his team's games he was available
  // for, shrunk toward the position average for short careers, as a percentile among his position).
  const GRP_LABEL = { QB: 'QBs', RB: 'RBs', WR: 'WRs', TE: 'TEs', OL: 'offensive linemen', DL: 'defensive linemen', LB: 'linebackers', DB: 'defensive backs', K: 'kickers', P: 'punters', LS: 'long snappers' };
  const loadInj = () => {
    if (DINJ !== null || loadInj.busy) return;
    loadInj.busy = 1;
    getJSON(`${siteRoot()}data/espn_injuries/latest.json`).then(x => { DINJ = {}; x.rows.forEach(r => { DINJ[String(r.espn_id)] = r; }); rerenderCard(); }).catch(() => {});
  };
  const injuryTab = (L, espn, brief = false) => {
    const eps = L.inj || [], d = L.dur;
    loadInj();
    const now = !brief && espn && DINJ && DINJ[espn];
    const cur = now && now.status !== 'Active' ? `<div class="pc-box"><div class="pc-k">Right now · ESPN</div>
      <div class="ij-now"><span class="dc-tag dt-${now.status === 'Questionable' ? 'q' : now.status === 'Doubtful' ? 'd' : 'out'}">${esc(now.status)}</span>
        <b>${esc([now.type, now.detail && now.detail !== 'Not Specified' ? now.detail : '', now.side && now.side !== 'Not Specified' ? now.side : ''].filter(Boolean).join(' · '))}</b>
        ${now.return_date ? `<span class="muted">est. return ${esc(new Date(now.return_date + 'T12:00:00').toLocaleDateString([], { month: 'short', day: 'numeric' }))}</span>` : ''}</div>
      ${now.comment ? `<p class="pc-sub">${esc(now.comment)}</p>` : ''}</div>` : '';
    let dur = '';
    if (d && d.games) {
      const pct = d.pct != null ? Math.round(d.pct * 100) : null, tone = pct == null ? '' : pct >= 67 ? 'good' : pct <= 33 ? 'bad' : '';
      dur = `<div class="pc-box"><div class="pc-k">Durability · since 2013</div>
        <div class="ij-dur"><div class="pc-big ${tone}">${pct != null ? `${ord(pct)}` : '–'} <small>percentile</small></div>
          <div class="pc-sub">${pct != null ? `More durable than ${pct}% of ${esc(GRP_LABEL[d.grp] || d.grp)} with a season or more of games` : ''}${d.small ? ' (few games yet: pulled toward the position average)' : ''}.</div></div>
        ${sg([sgRow(null, [cell(`${Math.round(d.avail * 100)}%`, 'Available', 'Share of his team\'s games he was not out injured'), cell(f0(d.games), 'Team games'), cell(f0(d.missed), 'Missed', 'Games missed injured'), cell(f0(eps.length), 'Injuries', 'Injury episodes listed')])], 4, { labels: false, cls: 'sg-tight' })}
        <p class="pc-sub">Counts his team's games while he was on the roster, from 2013 (snap counts tell who played); games missed inside an injury episode count against him (healthy scratches and suspensions don't). Ranked after pulling short careers toward the position average by one season of games.</p></div>`;
    }
    if (!eps.length) return cur + dur + '<div class="pc-box"><p class="pc-sub">No injuries on the official reports since 2009.</p></div>';
    // recurring body parts: by games missed, then by how often listed
    const parts = {};
    eps.forEach(e => { const k = e.part || 'Undisclosed'; parts[k] = parts[k] || { n: 0, m: 0 }; parts[k].n++; parts[k].m += e.missed || 0; });
    const top = Object.entries(parts).sort((a, b) => b[1].m - a[1].m || b[1].n - a[1].n).slice(0, 5);
    const rec = `<div class="pc-box"><div class="pc-k">Most often</div><div class="ij-parts">${top.map(([k, v]) => `<span class="ij-part"><b>${esc(k)}</b> ${v.n}x${v.m ? ` · ${v.m} missed` : ''}</span>`).join('')}</div></div>`;
    const wk = e => e.w0 === e.w1 ? `Wk ${e.w0}` : `Wk ${e.w0}-${e.w1}`;
    const rows = eps.map(e => `<tr${e.missed ? '' : ' class="ij-played"'}><td><b>${e.s}</b></td><td>${wk(e)}</td><td>${esc(e.part || 'Undisclosed')}${e.ig ? `<span class="ij-ig" title="From the play-by-play injury notes or a news blurb">hurt in the week ${e.ig[0]} game${e.ig[1] ? `, Q${e.ig[1]}` : ''}</span>` : ''}</td>
      <td class="num">${e.missed == null ? '–' : e.missed ? `<b>${e.missed}</b>` : '0'}</td><td class="num">${e.played == null ? '–' : e.played || 0}</td>
      <td>${e.list ? `<span class="dc-tag dt-out">${esc(e.list)}</span>` : e.worst ? `<span class="dc-tag dt-${e.worst === 'Questionable' ? 'q' : e.worst === 'Doubtful' ? 'd' : 'out'}">${esc(e.worst === 'Questionable' ? 'Q' : e.worst === 'Doubtful' ? 'D' : 'Out')}</span>` : ''}</td></tr>`).join('');
    return `${cur}${dur}${rec}<div class="pc-box pc-logbox"><div class="pc-k">Every injury listed</div>
      <div class="lg-scroll"><table class="lg ij-tbl"><thead><tr class="lg-ch"><th>Season</th><th>Weeks</th><th>Injury</th><th class="num" title="Games missed">Missed</th><th class="num" title="Games played while listed">Played</th><th title="Worst game status or reserve list">Status</th></tr></thead><tbody>${rows}</tbody></table></div>
      <p class="pc-sub">From the official injury reports and weekly rosters (2009 on); "hurt in the week N game" comes from the play-by-play's injury notes or this season's news blurbs (not every in-game injury is noted); games missed and played come from snap counts, so they start in 2013 ('–' before). An episode runs while he is on the report or a reserve list; a bye doesn't end it, a game played without a listing does. IR players drop off the weekly report, so a later IR stint can show as undisclosed.</p></div>`;
  };
  // ---- Penalties (data/penalties/<season>.json, tools/penalties_build.py): regular season; one flagged play = one
  // penalty (nflverse records each play's main penalty); yards are 0 when declined or offset.
  const PEN = { ix: null, s: {} };
  const penIndex = () => PEN.ix || (PEN.ix = NFLE.load('data/penalties/index.json').catch(() => null));
  const penSeason = s => PEN.s[s] || (PEN.s[s] = NFLE.load(`data/penalties/${s}.json`).catch(() => null));
  const penTypes = types => types.length ? `<div class="pen-types">${types.slice(0, 6).map(([t, n, y]) => `<span class="pen-t"><b>${n}</b> ${esc(t)}<i>${y} yd</i></span>`).join('')}</div>` : '';
  // team: the latest season with games; per game and league rank (1 = fewest flags), drawn, top calls, top players
  const teamPenBox = (abbr, D) => {
    const T = D && D.teams[abbr];
    if (!T || !T.g) return '';
    const all = Object.entries(D.teams).filter(([, x]) => x.g), per = x => x.n / x.g, yper = x => x.y / x.g, dper = x => x.dn / x.g;
    const rank = (f, asc) => 1 + all.filter(([, x]) => asc ? f(x) < f(T) : f(x) > f(T)).length;
    const tone = r => r <= 8 ? 'good' : r >= 25 ? 'bad' : '';
    // the same tile as the season stats above it (label, value, rank chip; second visual audit: one tile spec)
    const cellR = (v, lab, r, tip) => `<div class="tm-st"><div class="pc-k">${lab}</div><div class="tm-stv">${v}</div>${rkChip(r, tip)}</div>`;
    const pl = T.players.map(([g, n, y]) => { const ps = (D.pos || {})[g];
      return `<button type="button" class="pen-p" data-open-pid="${esc(g)}">${ps ? `<span class="pen-pos">${esc(ps)}</span>` : ''}<b>${esc(D.names[g] || g)}</b> <span class="muted">${n} &middot; ${y} yd</span></button>`; }).join('');
    return `<div class="pc-box"><div class="pc-k">Penalties · ${D.season} · ${T.g} games</div>
      <div class="pen-grid">${cellR((per(T)).toFixed(1), 'Flags / game', rank(per, true), 'League rank, fewest flags = 1st')}
        ${cellR(Math.round(yper(T)), 'Yards / game', rank(yper, true), 'League rank, fewest yards = 1st')}
        ${cellR((dper(T)).toFixed(1), 'Drawn / game', rank(dper, false), "Opponents' flags; most drawn = 1st")}</div>
      ${penTypes(T.types)}${pl ? `<div class="pc-k pen-sub">Most flagged</div><div class="pen-pl">${pl}</div>` : ''}
      <p class="pc-sub">Regular season. Counts each play's main penalty, declined ones included (0 yards).</p></div>`;
  };
  // Summary tile (owner 2026-10-16): flags in his current season (his last one if he's not playing now), 0 included,
  // career total under it; the sheet has that season's calls and every season he played, flagged or not.
  // seasons: from his career log (games played; team = his last game's), flags from the penalty shard (1999 on)
  const penSeasons = (pid, docs, L) => {
    const by = Object.fromEntries(docs.filter(d => d && d.players[pid]).map(d => [d.season, d.players[pid]]));
    const played = ((L && L.seasons) || []).filter(S => S.g.length && S.s >= 1999).map(S => ({ s: S.s, t: S.g[S.g.length - 1].t || '' }));
    const ss = new Set([...played.map(x => x.s), ...Object.keys(by).map(Number)]);
    return [...ss].sort((a, b) => b - a).map(y => { const x = by[y], pl = played.find(q => q.s === y);
      return { s: y, t: x ? x[0] : pl ? pl.t : '', n: x ? x[1] : 0, y: x ? x[2] : 0, types: x ? x[3] : [] }; });
  };
  const playerPenTile = (pid, docs, L) => {
    const rows = penSeasons(pid, docs, L);
    const cs = L && rows.some(r => r.s === L.cur) ? L.cur : rows.length ? rows[0].s : L && L.cur;
    if (!cs) return '';
    const r = rows.find(x => x.s === cs) || { s: cs, n: 0, y: 0, types: [] };
    const tot = rows.reduce((a, x) => [a[0] + x.n, a[1] + x.y], [0, 0]);
    const hist = rows.map(x => `<tr${x.n ? '' : ' class="muted"'}><td><b>${x.s}</b></td><td>${esc(x.t)}</td><td class="num">${x.n}</td><td class="num">${x.y}</td><td class="pen-top">${esc((x.types[0] || [''])[0])}</td></tr>`).join('');
    const box = `<div class="pc-box"><div class="pc-k">${r.s}: ${r.n ? `${r.n} for ${r.y} yards` : 'no flags'}</div>${penTypes(r.types)}
      ${rows.length ? `<div class="pc-k pen-sub">Career: ${tot[0] ? `${tot[0]} for ${tot[1]} yards` : 'no flags'} in ${rows.length} ${rows.length === 1 ? 'season' : 'seasons'}</div>
      <div class="lg-scroll"><table class="lg"><thead><tr class="lg-ch"><th>Season</th><th>Team</th><th class="num">Flags</th><th class="num">Yds</th><th>Most often</th></tr></thead><tbody>${hist}</tbody></table></div>` : ''}
      <p class="pc-sub">Regular season, accepted and declined, since 1999.</p></div>`;
    // a slim row under draft & contract (owner 2026-10-16: extra stats, not a headline tile)
    return tapTile('Penalties', `<div class="pc-penrow"><b>${r.n}</b> ${r.n === 1 ? 'flag' : 'flags'} in ${r.s} · <b>${tot[0]}</b> career</div>`, 'Penalties', box, ' pc-tap-row');
  };
  // ---- NFL Edge grade (data/grades/<season>.json, tools/grade_build.py): percentile of EPA over replacement per game
  // over his last three seasons (weighted to the latest, shrunk by sample size) among his position's players that season.
  const GR = { ix: null, s: {} };
  const GRH = {};  // pid -> his grade history docs (data/grades/players/<last 2 digits>.json); null while loading
  const grIndex = () => GR.ix || (GR.ix = NFLE.load('data/grades/index.json').catch(() => null));
  const grSeason = s => GR.s[s] || (GR.s[s] = NFLE.load(`data/grades/${s}.json`).catch(() => null));
  const GRADED = { QB: 1, RB: 1, WR: 1, TE: 1 };
  const grTone = g => g >= 80 ? 'good' : g <= 30 ? 'bad' : '';  // by percentile
  // OVR on a 50-99 scale (owner 2026-10-14): only qualified players are graded, so the least of them is a 50, not a
  // 0; linear in his percentile among the qualified. The sentence and the stat bars keep the plain percentile.
  const ovr = p => 50 + Math.round(p * 49 / 99);
  // [9] = 1: under the qualifying minimum but with a real role (2+ games at half the snaps), graded on those games
  const uqMark = r => r && r[9] ? '*' : '';
  const gradeTab = (pid, docs) => {
    const all = docs.filter(d => d && d.players[pid]).sort((a, b) => b.season - a.season);
    const rows = all.filter(d => d.players[pid][0] != null);  // graded seasons (the rest: played, not graded)
    if (!rows.length) return '<div class="pc-box"><p class="pc-sub">No grade: grades cover quarterbacks, running backs, receivers and tight ends since 1999 who met the NFL\'s qualifying minimum in a season (per team game: 14 pass attempts, 6.25 carries, or 1.875 catches).</p></div>';
    const D = rows[0], r = D.players[pid], pos = r[1], labels = D.stats[pos] || [];
    const posName = { QB: 'quarterbacks', RB: 'running backs', WR: 'wide receivers', TE: 'tight ends' }[pos] || pos;
    const f1 = v => v == null ? '–' : v.toFixed(1), nq = (D.qualified || {})[pos];
    // grade files built before 2026-10-15 label the flipped stats "X rate (lower is better)": plain names now, with one
    // note above the bars that high / green is good for every stat (rates where less is better are flipped)
    const FLIP = { 'Sack rate (lower is better)': 'Sack rate', 'INT rate (lower is better)': 'INT rate', 'Drop rate (lower is better)': 'Drop rate' };
    const bars = labels.map((l, i) => { const v = r[5][i]; l = FLIP[l] || l; return `<div class="eg-row"><span class="eg-l">${esc(l)}</span><b class="eg-v">${v}</b><span class="eg-bar"><i class="${grTone(v)}" style="width:${Math.max(2, v)}%"></i></span></div>`; }).join('');
    // by season: that season's play only ([6], [7]); older files without it fall back to the window grade
    // every season from his first to his last, none skipped (owner 2026-10-15: a missing year reads as consecutive)
    const have = new Set(all.map(d => d.season)), years = [];
    for (let y = all[0].season; y >= all[all.length - 1].season; y--) years.push(y);
    const dnp = y => `<tr class="muted gr-dnp"><td><b>${y}</b></td><td class="num" colspan="3">Did not play</td></tr>`;
    const hist = years.map(y => have.has(y) ? all.find(d => d.season === y) : y).map(d => { if (typeof d === 'number') return dnp(d);
      const x = d.players[pid], g = x[6] ?? x[0];
      if (x[0] == null) return `<tr class="muted"><td><b>${d.season}</b></td><td class="num" title="Not graded: too few games with a real role (needs the qualifying minimum, or 2+ games with a starter's workload)">–</td><td class="num">${x[8] ?? '–'}</td><td class="num">${f1(x[7])}</td></tr>`;
      return `<tr><td><b>${d.season}</b>${d.basis === 'box' ? ' <small class="muted" title="Box-score stats only before 2018: same OVR, simpler stats behind it">box</small>' : ''}</td><td class="num"><span class="eg-chip ${x[9] ? 'eg-uq' : grTone(g)}"><b>${ovr(g)}${uqMark(x)}</b></span></td><td class="num">${x[8] ?? '–'}</td><td class="num">${f1(x[7])}</td></tr>`; }).join('');
    return `<div class="pc-box"><div class="pc-k">Current form</div>
        <div class="ij-dur"><div class="pc-big ${r[9] ? '' : grTone(r[0])}">${ovr(r[0])}${uqMark(r)} <small>OVR</small></div>
          <div class="pc-sub">Over his last three seasons weighted to ${D.season}, he produced <b>${f1(r[4])}</b> fantasy points per game, more than ${r[0]}% of the ${nq ? `${nq} ` : ''}qualified ${posName}${r[9] ? ` (*under the qualifying minimum: graded on his ${r[8]} games with half the snaps or more, not counted in the rankings)` : ''}${r[3] < 8 ? ' (a small sample so far, so it leans on the position average)' : ''}.</div></div></div>
      <div class="pc-box"><div class="pc-k">The stats behind it · percentile among ${posName}</div><p class="pc-sub">Higher and greener is better for every stat. For rates where less is better (drops, sacks, interceptions) the percentile is flipped: 99 = fewest.</p><div class="eg-bars">${bars}</div></div>
      <div class="pc-box pc-logbox"><div class="pc-k">By season · that season only</div><div class="lg-scroll"><table class="lg"><thead><tr class="lg-ch"><th>Season</th><th class="num">OVR</th><th class="num" title="Games played">G</th><th class="num" title="Fantasy points per game (site scoring)">Pts / g</th></tr></thead><tbody>${hist}</tbody></table></div>
        <p class="pc-sub">How it works: the overall measures output: fantasy points per game in this site's scoring (yards, touchdowns, catches, turnovers), pulled toward the position average by an amount measured from game-to-game swings, so a few big games can't make a 99. The rankings use players who met the NFL's qualifying minimum that season (per team game: 14 pass attempts, 6.25 carries, or 1.875 catches). A player under it who still played half the snaps or more in at least two games (a spot starter) gets an asterisked grade from those games, measured against the qualified players. Current form weights his last three seasons 1 / 0.6 / 0.3; each season in the table uses that season alone. OVR runs 50-99: his percentile among the qualified at his position, scaled so the lowest is a 50. The stats above show how he gets there (efficiency, role, and tracking measures as percentiles). Stats: nflverse play-by-play, Next Gen Stats, PFR advanced stats (2018 on). Seasons before 2018 (marked <i>box</i>) have the same OVR, but the stats behind it are box-score rates, and a spot starter's games are picked by workload instead of snaps. A dash means he played but too little to grade.</p></div>`;
  };
  const renderCard = pid => {
    const body = document.querySelector('#pcOv .pc-body');
    const d = cardData(), L = LOGS[pid] && !LOGS[pid].missing ? LOGS[pid] : null;
    const p = d ? d.players[pid] : null;
    // Identity is current: the career log's roster team / position, else the page's row, else the week's row.
    const row = (DATA && DATA.players[pid]) || p || Object.values(WEEKS).map(x => x && x.players && x.players[pid]).find(Boolean) || {};
    const name = row.name || (L && L.name), pos = (L && L.pos) || row.pos, team = (L && L.team) || row.team, espn = row.espn || (L && L.espn);
    if (!LOGS[pid]) ensureLog(pid).then(() => { if (cardPid === pid) renderCard(pid); });
    cardNeeds();
    if (!name) { body.innerHTML = `<p class="pc-none">${LOGS[pid] ? 'No card for this player.' : 'Loading&hellip;'}</p>`; return; }
    const info = tInfo(team), news = !!espn;
    const photo = photoUrl(L, espn), num = L && L.bio ? L.bio.num : null;
    if (cardTab === 'news' && !news) cardTab = 'ov';
    const graded = !!GRADED[pos];
    if (cardTab === 'gr' || cardTab === 'inj') cardTab = 'ov';  // Grade and Injuries became tile sheets  // the Grade tab became the Grade tile's sheet (a remembered tab may still say gr)
    if (graded && GRH[pid] === undefined) {
      GRH[pid] = null;
      NFLE.load(`data/grades/players/${pid.slice(-2)}.json`).catch(() => null).then(sh => {
        GRH[pid] = ((sh || {})[pid] || []).map(([season, basis, rec, labels, nq]) => ({ season, basis, players: { [pid]: rec }, stats: { [rec[1]]: labels }, qualified: { [rec[1]]: nq } }));
        if (cardPid === pid) renderCard(pid);
      });
    }
    // the current season's grades drive the header chip; the Grade tab loads every season on first open
    if (graded && GR.cur === undefined) { GR.cur = null; grIndex().then(ix => ix && grSeason(ix.current)).then(d => { GR.cur = d || null; if (cardPid === pid) renderCard(pid); }); }
    const isKind = !!(L && L.kind);  // a non-fantasy page (defense, line, specialists): no week projections
    // retired / off every roster this season and not on the picked week's board: a career overview, no week picker
    const lastPlayed = L ? (L.seasons.find(S => S.g.length) || {}).s : null;
    const retired = !isKind && !!L && !L.team && !p && !(DATA && DATA.players[pid]) && lastPlayed && lastPlayed < L.cur;
    const overview = isKind || retired;
    const week = isKind ? kindOverview(L, espn) + profileBox(L)
      : retired ? weekExtras(pid, L, row, espn) + (offCareer(L) ? `<div class="pc-box"><div class="pc-k">By season (regular season)</div>${offCareer(L)}</div>` : '') + profileBox(L)
      // two columns on wide screens (owner 2026-10-16): the summary tiles, game and this season's games on the left;
      // news and draft & contract on the right. Fixed sides (owner).
      : `<div class="pc-cols"><div class="pc-col">${d === undefined || d === null ? wkWait(d) : p ? playerWeek(pid, p, d, L) : playerOff(L, d)}${logMini(pid, L, p || row)}</div>
         <div class="pc-col">${newsMini(espn)}${profileBox(L)}<div class="pc-pen"></div></div></div>`;
    body.innerHTML = `
      <div class="pc-head pc-head-hero" style="--tc:${esc(info.color || '#666')};--tc2:${esc(info.color2 || info.color || '#999')}${info.logo ? `;--tlogo:url('${esc(logoSrc(info.logo, 300))}')` : ''}">
        ${photo ? `<div class="pc-pic" data-zoom="${esc(uncrop(photoBig(L, espn) || photo))}" role="button" tabindex="0" aria-label="Show a bigger photo"><img src="${esc(photo)}" alt="" width="72" height="72" loading="lazy" onerror="this.parentNode.classList.add('nopic')">${team ? `<span class="pc-pic-tm">${tLogo(team, 16)}</span>` : ''}</div>`
          : team ? tmL(team, tLogo(team, 34)) : ''}
        <div class="pc-id"><h3 id="pcName">${num != null ? `<span class="pc-num">#${esc(num)}</span>` : ''}${esc(name)}</h3>
          <div class="pc-meta">${pos ? `<span class="posb posb-${esc(pos)}">${esc(pos)}</span>` : ''}${team ? `<button type="button" class="tm-open pc-tlink" data-tm="${esc(team)}">${esc(info.name || team)}</button>` : L && lastPlayed && lastPlayed < L.cur ? `<span class="muted">Last played ${esc(lastPlayed)}</span>` : '<span class="muted">Free agent</span>'}</div>
</div>
        ${bioStrip(L, ' pc-bio-in')}
      </div>
      ${bioStrip(L)}
      <div class="seg pc-tabs" role="tablist">${[['ov', 'Summary'], ['log', 'Game log'], ...(news ? [['news', 'News']] : [])]
        .map(([k, l]) => `<button type="button" role="tab" data-pt="${k}" class="${cardTab === k ? 'on' : ''}">${l}</button>`).join('')}</div>
      <div class="pc-tab" data-pt="ov"${cardTab === 'ov' ? '' : ' hidden'}>${overview ? '' : pickerHtml()}${week}${overview ? '<div class="pc-pen"></div>' : ''}</div>
      <div class="pc-tab" data-pt="log"${cardTab === 'log' ? '' : ' hidden'}><div class="pc-box pc-logbox"><div class="pc-k">Every career game</div><div class="pc-log">${
        !LOGS[pid] ? '<div class="skel-zone"></div>' : !L ? '<p class="pc-sub">Game log unavailable.</p>'
          : isKind ? (L.seasons.length ? kindLog(L, L.seasons) : '<p class="pc-sub">No regular-season games with a recorded stat or snap.</p>')
          : L.seasons.length || (L.up || []).length ? logHtml(L, p || row) : '<p class="pc-sub">No NFL games yet.</p>'}</div></div></div>
      ${news ? `<div class="pc-tab" data-pt="news"${cardTab === 'news' ? '' : ' hidden'}><div class="pc-box pc-newsbox"><div class="pc-k">Recent news</div><div class="pc-news"></div></div></div>` : ''}`;
    body.querySelectorAll('.pc-news').forEach(nb => loadNews(espn, nb, +nb.dataset.n || 6));
    // his career from one small shard (data/penalties/players/<last 2 digits>.json) instead of every season's file
    if (L) body.querySelectorAll('.pc-pen').forEach(pb => NFLE.load(`data/penalties/players/${pid.slice(-2)}.json`).catch(() => null)
      .then(sh => { if (cardPid === pid) { pb.innerHTML = playerPenTile(pid, ((sh || {})[pid] || []).map(([season, ...x]) => ({ season, players: { [pid]: x } })), L); } }));
    body.querySelectorAll('.pc-log').forEach(wireLogRows);
    const showTab = k => {
      cardTab = k;
      rememberTab(`p:${pid}`, k);
      body.querySelectorAll('.pc-tabs [data-pt]').forEach(x => x.classList.toggle('on', x.dataset.pt === k));
      body.querySelectorAll('.pc-tab').forEach(t => { t.hidden = t.dataset.pt !== cardTab; });
    };
    body.querySelectorAll('.pc-tabs [data-pt]').forEach(b => b.onclick = () => {
      // the Game log tab always opens on Games (owner 2026-10-16); Seasons is a tap away inside it
      const lb = b.dataset.pt === 'log' && body.querySelector('.pc-tab[data-pt="log"] .pc-log');
      if (lb) showLogView(lb, 'g');
      showTab(b.dataset.pt);
    });
    // "Show more" opens the full tab, scrolled to the top of the card (the tabs bar) so it reads from the start.
    body.querySelectorAll('[data-goto]').forEach(b => b.onclick = () => {
      const lb = b.dataset.lvGo && body.querySelector('.pc-tab[data-pt="log"] .pc-log');
      if (lb) showLogView(lb, b.dataset.lvGo);
      showTab(b.dataset.goto);
      body.querySelector('.pc-tabs').scrollIntoView({ block: 'start', behavior: 'smooth' });
    });
    // The matchup tile opens the gamecast from anywhere on it; its team code opens that team's card instead.
    body.querySelectorAll('.pc-mutile[data-href]').forEach(t => {
      t.onclick = e => { if (!e.target.closest('.tm-open, a, button')) location.href = t.dataset.href; };
      t.onkeydown = e => { if (e.key === 'Enter' && e.target === t) location.href = t.dataset.href; };
    });
    wirePicker(body);
    NFLE.paintTiles();
  };
  // ------------------------------------------------------------------------------------------------- team card
  // Same overlay and look as the player card. Week tab from the picked week's data (Power, matchup, players);
  // season stats and the career game log from data/teams/<TEAM>.json (tools/player_logs.py).
  let cardTeam = null, teamTab = 'ov', teamOpp = '';
  const TLOGS = {};
  // Depth tab: a team's depth chart for any week since 2001 (data/depth/<season>/<TEAM>.json, tools/depth_build.py;
  // nflverse: team charts through 2024, ESPN's daily charts after), its own season / week pickers starting on the
  // page's week. Each player's tag is that week's official one (injury report O / D / Q, or a reserve list: IR, PUP,
  // NFI, SUSP, HOLD); the latest week of the current season shows ESPN's live injury list instead (it moves daily).
  let DIDX, DINJ = null;
  const DFILES = {}, dSel = {};  // dSel[team] = { s, w }
  let dMode = 'use';  // 'use' = by playing time (default when the week has it), 'list' = the listed chart
  const GRP_NAME = { QB: 'Quarterback', RB: 'Running backs', WR: 'Wide receivers', TE: 'Tight ends', OL: 'Offensive line',
                     DL: 'Defensive line', LB: 'Linebackers', CB: 'Cornerbacks', S: 'Safeties' };
  const TAG_TONE = { Q: 'q', D: 'd' };  // everything else (O, IR, PUP, NFI, SUSP, HOLD) = out
  const ESPN_TAG = { 'Out': 'O', 'Injured Reserve': 'IR', 'Doubtful': 'D', 'Questionable': 'Q', 'Suspension': 'SUSP',
                     'Physically Unable to Perform': 'PUP' };
  const TAG_NAME = { O: 'Out', D: 'Doubtful', Q: 'Questionable', IR: 'Injured reserve', PUP: 'Physically unable to perform list',
                     NFI: 'Non-football injury list', SUSP: 'Suspended', HOLD: 'Did not report' };
  const dKey = (s, t) => `${s}/${t}`;
  const loadDepth = (s, abbr) => {
    const again = () => { if (cardTeam === abbr && teamTab === 'dc') renderTeam(abbr); };
    if (DIDX === undefined) {
      DIDX = null;
      getJSON(`${siteRoot()}data/depth/index.json`).then(x => { DIDX = x; again(); }).catch(() => { DIDX = false; again(); });
      getJSON(`${siteRoot()}data/espn_injuries/latest.json`).then(x => { DINJ = {}; x.rows.forEach(r => { DINJ[String(r.espn_id)] = r; }); again(); }).catch(() => {});
    }
    const k = dKey(s, abbr);
    if (s && DFILES[k] === undefined) {
      DFILES[k] = null;
      getJSON(`${siteRoot()}data/depth/${s}/${encodeURIComponent(abbr)}.json`).then(x => { DFILES[k] = x; again(); }).catch(() => { DFILES[k] = false; again(); });
    }
  };
  const regWeeks = s => s >= 2021 ? 18 : 17;
  const wkName = (s, w, post) => w <= regWeeks(s) ? `Week ${w}` : (['Wild card', 'Divisional', 'Conference', 'Super Bowl'][post.indexOf(w)] || `Week ${w}`);
  const depthHtml = abbr => {
    if (DIDX === undefined || DIDX === null) { loadDepth(null, abbr); return '<div class="pc-box"><p class="pc-sub">Loading depth chart&hellip;</p></div>'; }
    if (!DIDX) return '<div class="pc-box"><p class="pc-sub">Depth charts unavailable right now.</p></div>';
    if (!dSel[abbr]) {  // start on the page's week (or the latest season we have)
      const [cs, cw] = String(cardWk || '').split('-').map(Number);
      dSel[abbr] = DIDX.seasons.includes(cs) ? { s: cs, w: cw } : { s: DIDX.seasons[DIDX.seasons.length - 1], w: null };
    }
    const sel = dSel[abbr], f = DFILES[dKey(sel.s, abbr)];
    if (f === undefined) loadDepth(sel.s, abbr);
    const seasonSel = `<select class="pc-wkpick dc-season" aria-label="Season">${[...DIDX.seasons].reverse().map(y => `<option value="${y}"${y === sel.s ? ' selected' : ''}>${y}</option>`).join('')}</select>`;
    if (!f) return `<div class="pc-wkbar">${seasonSel}</div><div class="pc-box"><p class="pc-sub">${f === false ? `No depth chart for ${esc(abbr)} in ${sel.s}.` : 'Loading depth chart&hellip;'}</p></div>`;
    const weeks = Object.keys(f.weeks).map(Number).sort((a, b) => a - b), post = weeks.filter(w => w > regWeeks(sel.s));
    if (!weeks.includes(sel.w)) sel.w = weeks.filter(w => w <= (sel.w || 99)).pop() || weeks[weeks.length - 1];
    const W = f.weeks[sel.w];
    const liveWk = sel.s === DIDX.current && sel.w === weeks[weeks.length - 1];  // the current chart: ESPN's live injury list
    const weekSel = `<select class="pc-wkpick dc-week" aria-label="Week">${weeks.map(w => `<option value="${w}"${w === sel.w ? ' selected' : ''}>${wkName(sel.s, w, post)}</option>`).join('')}</select>`;
    const who = ([pi, rank, tag], i, pct = null, starter = null, hurt = false) => {
      const [name, pid, espn] = f.players[pi];
      const live = liveWk && espn && DINJ && DINJ[espn];
      const t = liveWk && DINJ ? (live ? ESPN_TAG[live.status] : null) : tag;
      const title = live ? `${live.status}${live.type ? ` (${live.type})` : ''}` : TAG_NAME[t] || t;
      // our player page when he has one (offensive skill players), else his ESPN page
      const nm = pid ? `<button type="button" class="bx-n dc-n" data-open-pid="${esc(pid)}">${esc(name)}</button>`
        : espn ? `<a class="dc-n dc-ext" href="https://www.espn.com/nfl/player/_/id/${esc(espn)}" target="_blank" rel="noopener" title="ESPN player page">${esc(name)}</a>` : `<span class="dc-n">${esc(name)}</span>`;
      const bold = starter != null ? starter : i === 0 || rank === 1;
      return `<span class="dc-p${bold && !hurt ? ' first' : ''}${hurt ? ' dc-hurt' : ''}"${hurt ? ' title="Starter by playing time, out this week"' : ''}>${nm}${pct != null ? `<span class="dc-pct" title="Average share of snaps, last ${esc(f.window || 3)} games">${pct}%</span>` : ''}${t ? `<span class="dc-tag dt-${TAG_TONE[t] || 'out'}" title="${esc(title)}">${esc(t)}</span>` : ''}</span>`;
    };
    const box = (title, rows) => rows && rows.length ? `<div class="pc-box"><div class="pc-k">${esc(title)}</div>
      ${rows.map(([abb, name, pl]) => `<div class="dc-row"><span class="dc-pos" title="${esc(name)}">${esc(abb)}</span><span class="dc-pl">${pl.map((x, i) => who(x, i)).join('')}</span></div>`).join('')}</div>` : '';
    // by playing time: snap leaders over the team's last 3 games (from its 2nd game on), starters in bold
    const mode = W.u ? dMode : 'list';
    const ubox = (title, grps) => {
      const rows = (W.u || []).filter(r => grps.includes(r[0]));
      return rows.length ? `<div class="pc-box"><div class="pc-k">${esc(title)}</div>
        ${rows.map(([g, n, pl]) => { const up = pl.filter(x => !x[3]), hurt = pl.filter(x => x[3]);
          return `<div class="dc-row"><span class="dc-pos" title="${esc(GRP_NAME[g] || g)}">${esc(g)}</span><span class="dc-pl">${up.map(([pi, pct, tag], i) => who([pi, 0, tag], i, pct, i < n)).join('')}${hurt.map(([pi, pct, tag], i) => who([pi, 0, tag], i, pct, false, true)).join('')}</span></div>`; }).join('')}</div>` : '';
    };
    const seg = W.u ? `<div class="seg dc-mode" role="tablist"><button type="button" role="tab" data-dm="use" class="${mode === 'use' ? 'on' : ''}">Playing time</button><button type="button" role="tab" data-dm="list" class="${mode === 'list' ? 'on' : ''}">Listed chart</button></div>` : '';
    const tags = liveWk ? "ESPN's injury list, updated daily" : "that week's injury report (O / D / Q) or reserve list (IR, PUP, NFI, SUSP, HOLD = did not report)";
    const listedName = sel.s >= 2025 ? "ESPN's depth chart" : "The team's depth chart";
    const body = mode === 'use'
      ? `${ubox('Offense', ['QB', 'RB', 'WR', 'TE', 'OL'])}${ubox('Defense', ['DL', 'LB', 'CB', 'S'])}${box('Special teams (listed chart)', W.st)}
        <p class="pc-sub">Who actually plays: each position's snap leaders, from each player's last 3 healthy games this season (share of snaps, the newest weighted most: 50 / 30 / 20%). Games he missed hurt or left hurt are skipped, reaching further back; a game missed for any other reason counts 0, leaving out players no longer on the team; a starter ruled out that week or on a reserve list is shown faded at the end of his group with his tag. Starters in bold, as many as the listed chart has. Tested on 2025-26: these starters were the game's top snap-getters 88% of the time, ESPN's listed starters 76%; the recency and injury rules added more (tested 2019-2026), most for starters back from injury. Tags: ${tags}.</p>`
      : `${box(`Offense${W.f ? ` · ${W.f}` : ''}`, W.off)}${box(`Defense${W.d ? ` · ${String(W.d).replace(/ D$/, '')}` : ''}`, W.def)}${box('Special teams', W.st)}
        <p class="pc-sub">${listedName} for that week (starters in bold, backups in order)${W.u ? '' : sel.s >= 2012 ? ". A team's first game shows the listed chart: before it has played, the preseason chart beats last season's playing time (83% vs 71% of starters right in 2025-26)" : ''}. Tags: ${tags}. Team depth charts are labeled "unofficial" and can lag reality.</p>`;
    return `<div class="pc-wkbar">${seasonSel}${weekSel}</div>${seg}${body}`;
  };
  const wireDepth = (body, abbr) => {
    const box = body.querySelector('.pc-tab[data-tt="dc"]'); if (!box) return;
    const ss = box.querySelector('.dc-season'), ws = box.querySelector('.dc-week');
    const redraw = () => { box.innerHTML = depthHtml(abbr); wireDepth(body, abbr); };
    if (ss) ss.onchange = () => { dSel[abbr] = { s: +ss.value, w: dSel[abbr].w }; redraw(); };
    if (ws) ws.onchange = () => { dSel[abbr].w = +ws.value; redraw(); };
    box.querySelectorAll('[data-dm]').forEach(b => { b.onclick = () => { dMode = b.dataset.dm; redraw(); }; });
  };
  const rkChip = (r, title = '') => r ? `<span class="rk-b ${r <= 8 ? 'rk1' : r <= 16 ? 'rk2' : r <= 24 ? 'rk3' : 'rk4'}"${title ? ` title="${esc(title)}"` : ''}>${ord(r)}</span>` : '';
  const sgn = v => v == null || isNaN(v) ? '' : `${v >= 0 ? '+' : ''}${(+v).toFixed(1)}`;
  const tInfo = t => (DATA && DATA.teams && DATA.teams[t]) || {};
  const tLogo = (t, size = 20) => { const i = tInfo(t); return logo(i.logo, i.logo_bg, size, t); };
  const gcHref = (gid, f) => `${siteRoot()}game.html?g=${encodeURIComponent(gid)}${f ? `&d=${encodeURIComponent(f)}` : ''}`;
  const rankTrend = hist => {
    const wk = Object.keys(hist || {}).map(Number).sort((a, b) => a - b);
    if (wk.length < 2) return '';
    // 1-32 on the full height keeps the league position readable (top teams near the top); 60 high (was 80, mostly empty)
    const W = 300, H = 60, X = w => 14 + (W - 28) * (w - wk[0]) / Math.max(1, wk[wk.length - 1] - wk[0]), Y = r => 8 + (H - 26) * (r - 1) / 31;
    const pts_ = wk.map(w => `${X(w).toFixed(1)},${Y(hist[w]).toFixed(1)}`).join(' ');
    return `<svg class="tm-trend" viewBox="0 0 ${W} ${H}" width="100%" height="${H}" aria-label="Power rank by week">
      <line x1="14" x2="${W - 14}" y1="${Y(16.5)}" y2="${Y(16.5)}" class="tm-tr-mid"/><polyline points="${pts_}" class="tm-tr-line"/>
      ${wk.map(w => `<circle cx="${X(w)}" cy="${Y(hist[w])}" r="3.2" class="tm-tr-pt"><title>Week ${w}: ${ord(hist[w])}</title></circle>
        <text x="${X(w)}" y="${Y(hist[w]) - 6}" class="tm-tr-v">${hist[w]}</text><text x="${X(w)}" y="${H - 2}" class="tm-tr-w">${w}</text>`).join('')}</svg>`;
  };
  const teamLogHtml = (L, abbr) => {
    const opps = [...new Set(L.seasons.flatMap(s => s.g.map(g => g.o)))].sort();
    const sel = `<label class="tm-filter">Opponent <select data-topp><option value="">All teams</option>${opps.map(o => `<option value="${esc(o)}"${o === teamOpp ? ' selected' : ''}>${esc(o)}</option>`).join('')}</select></label>`;
    let h2h = '';
    if (teamOpp) {
      const gs = L.seasons.flatMap(s => s.g).filter(g => g.o === teamOpp);
      const w = gs.filter(g => g.r === 'W').length, l = gs.filter(g => g.r === 'L').length, t = gs.filter(g => g.r === 'T').length;
      h2h = `<div class="tm-h2h">${tmL(teamOpp, tLogo(teamOpp, 18))} <b>${esc(abbr)} vs ${tmL(teamOpp)} since 1999: ${w}-${l}${t ? `-${t}` : ''}</b> <span class="muted">(${gs.length} games)</span></div>`;
    }
    const oppCell = (o, h, opr) => `<td class="lg-opp tm-opp ${opr ? (opr <= 8 ? 'mr-hard' : opr <= 16 ? 'mr-tough' : opr <= 24 ? 'mr-ok' : 'mr-easy') : ''}"><button type="button" class="tm-open" data-tm="${esc(o)}"${opr ? ` title="Their power rank that week: ${ord(opr)}"` : ''}>${h === 0 ? '@' : h === 2 ? 'vs ' : ''}${esc(o)}</button></td>`;
    const pct = (v, m) => v == null && m == null ? '–' : `${v != null ? `${v}%` : '–'}<small> / ${m != null ? `${m}%` : '–'}</small>`;
    const head = `<tr class="lg-gh"><th colspan="7"></th><th colspan="5" class="lg-grp">Offense</th><th colspan="3" class="lg-grp">Allowed</th><th></th></tr>
      <tr class="lg-ch"><th>Wk</th><th>Opp</th><th>Result</th><th class="num">Line</th><th class="num" title="Pregame win chance: Vegas / our model (2021 on)">Odds</th><th class="num" title="Our power rank that week">Pwr</th><th class="num" title="Elo going in">Elo</th>
      <th class="num">Yds</th><th class="num">Pass</th><th class="num">Rush</th><th class="num" title="Yards per play">YPP</th><th class="num" title="Turnovers">TO</th>
      <th class="num">Yds</th><th class="num">YPP</th><th class="num" title="Takeaways">TA</th><th></th></tr>`;
    const body = L.seasons.map(S => {
      let rows = S.g.map(g => ({ w: g.w, g }));
      if (S.s === L.cur && !teamOpp) { (L.up || []).forEach(u => rows.push({ w: u.w, u })); (L.byes || []).forEach(b => rows.push({ w: b, bye: 1 })); }
      if (teamOpp) rows = rows.filter(r => r.g && r.g.o === teamOpp);
      const pg = (S.pg || []).filter(g => !teamOpp || g.o === teamOpp);
      if (!rows.length && !pg.length) return '';
      rows.sort((a, b) => b.w - a.w);  // newest first
      const rk = S.rk || {}, av = S.avg || {};
      const played = (g, label) => {
        const s = g.s || [], os = g.os || [];
        const res = `<span class="tm-res ${g.r === 'W' ? 'w' : g.r === 'L' ? 'l' : ''}">${g.r}</span> ${g.ps}-${g.pa}${g.ot ? ' <small>OT</small>' : ''}`;
        const line = g.ln != null ? `${g.ln > 0 ? '-' : g.ln < 0 ? '+' : ''}${g.ln === 0 ? 'PK' : Math.abs(g.ln).toFixed(1)}${g.ats ? ` <small class="ats-${g.ats}">${g.ats === 'W' ? 'cov' : g.ats === 'L' ? 'no' : 'push'}</small>` : ''}` : '–';
        return `<tr${tileAttrs(g)}><td>${esc(label)}</td>${oppCell(g.o, g.h, g.opr)}<td class="tm-rc">${res}</td><td class="num">${line}</td><td class="num">${pct(g.vc, g.mc)}</td>
          <td class="num">${g.pr ? `<span class="lg-rk ${g.pr <= 8 ? 'rk-good' : g.pr <= 20 ? 'rk-mid' : 'rk-bad'}">${g.pr}</span>` : '–'}</td><td class="num muted">${g.elo || ''}</td>
          <td class="num">${f0(s[0])}</td><td class="num">${f0(s[1])}</td><td class="num">${f0(s[2])}</td><td class="num">${s[3] != null ? s[3].toFixed(1) : ''}</td><td class="num">${s[4] ?? ''}</td>
          <td class="num">${f0(os[0])}</td><td class="num">${os[3] != null ? os[3].toFixed(1) : ''}</td><td class="num">${os[4] ?? ''}</td>
          <td><a class="tm-gc" href="${gcHref(g.gid, g.f)}" title="Gamecast">&rsaquo;</a></td></tr>`;
      };
      const trs = rows.map(r => {
        if (r.bye) return `<tr class="lg-bye"><td>${r.w}</td><td colspan="15">Bye</td></tr>`;
        if (r.u) {
          const u = r.u;
          return `<tr class="lg-up"${tileAttrs(u)}><td>${u.w}</td>${oppCell(u.o, u.h, u.opr)}<td class="muted">upcoming</td><td class="num">${u.ln != null ? sgn(-u.ln).replace('+0.0', 'PK') : '–'}</td>
            <td class="num">${pct(u.vc, u.mc)}</td><td class="num">–</td><td class="num">–</td><td colspan="8"></td><td><a class="tm-gc" href="${gcHref(u.gid, u.f)}" title="Gamecast">&rsaquo;</a></td></tr>`;
        }
        return played(r.g, r.g.w);
      }).join('');
      const sub = label => `<tr class="lg-sub"><td colspan="16"><span class="lg-pin">${label}</span></td></tr>`;
      const pw = pg.filter(g => g.r === 'W').length;
      const po = pg.length ? `${sub(`Playoffs · ${pw}-${pg.length - pw}`)}${head}${[...pg].reverse().map(g => played(g, g.po)).join('')}${rows.length ? sub('Regular season') : ''}` : '';
      const sumBits = [S.rec, av.pf != null ? `${f1(av.pf)} PF/G${rk.pf ? ` (${ord(rk.pf)})` : ''}` : '', av.pa != null ? `${f1(av.pa)} PA/G${rk.pa ? ` (${ord(rk.pa)})` : ''}` : ''].filter(Boolean).join(' · ');
      return `<tbody><tr class="lg-season"><td colspan="16"><span class="lg-pin"><b>${S.s}</b> ${esc(sumBits)}</span></td></tr>${po}${rows.length ? head + trs : ''}</tbody>`;
    }).join('');
    const legend = `<div class="lg-leg"><span>Opponent color = their power rank that week (2021 on):</span><span class="mr-hard">top 8</span><span class="mr-tough">9-16</span><span class="mr-ok">17-24</span><span class="mr-easy">25-32</span>
      <span>· Odds = pregame win chance, Vegas / our model · Line = Vegas spread for ${esc(abbr)} (cov = covered) · Tap a game to open its gamecast</span></div>`;
    return `<div class="tm-bar">${sel}</div>${h2h}${legend}<div class="lg-scroll"><table class="lg tm-lg">${body}</table></div>`;
  };
  const teamSeasonBox = (L) => {
    const S = L && L.seasons.find(s => s.s === L.cur);
    if (!S) return '';
    const a = S.avg || {}, r = S.rk || {};
    const cell = (k, label, v) => `<div class="tm-st"><div class="pc-k">${label}</div><div class="tm-stv">${v}</div>${rkChip(r[k], `League rank this season (1st = best)`)}</div>`;
    return `<div class="pc-box"><div class="pc-k">${S.s} season · ${esc(S.rec)} · per game</div><div class="tm-stats">
      ${cell('pf', 'Points for', f1(a.pf))}${cell('pa', 'Points against', f1(a.pa))}${cell('yd', 'Yards', f0(a.yd))}${cell('oyd', 'Yards allowed', f0(a.oyd))}
      ${cell('ep', 'Yards / play', a.ep != null ? a.ep.toFixed(2) : '')}${cell('oep', 'Allowed / play', a.oep != null ? a.oep.toFixed(2) : '')}${cell('tom', 'Turnover margin', sgn(a.tom))}</div></div>`;
  };
  // Team page: Playoffs tab (data/playoffs/teams.json, tools/playoffs_build.py team_summaries): every postseason since
  // 1933 (champions before), records overall and by round, titles, best finish, the playoff rate since the merger.
  let TPO;
  const RD_NAME = { WC: 'Wild Card', DIV: 'Divisional', CONF: 'Conference', SB: 'Super Bowl', LCH: 'League championship', OTHER: 'Other (tiebreakers)' };
  const TITLE_NAME = { SB: 'Super Bowl', NFL: 'NFL championship', AFL: 'AFL championship', AAFC: 'AAFC championship' };
  const teamPlayoffs = abbr => {
    if (TPO === undefined) {
      TPO = null;
      getJSON(`${siteRoot()}data/playoffs/teams.json`).then(x => { TPO = x; if (cardTeam) renderTeam(cardTeam); }).catch(() => { TPO = false; if (cardTeam) renderTeam(cardTeam); });
    }
    if (!TPO) return `<div class="pc-box"><p class="pc-sub">${TPO === false ? 'Playoff history unavailable right now.' : 'Loading playoff history&hellip;'}</p></div>`;
    const t = TPO[abbr];
    if (!t) return '<div class="pc-box"><p class="pc-sub">No playoff games yet.</p></div>';
    const pct = (w, l) => w + l ? `${Math.round(100 * w / (w + l))}%` : '–';
    const nfl = t.titles.filter(x => x.kind !== 'AAFC'), aafc = t.titles.filter(x => x.kind === 'AAFC');
    const r = t.rate;
    const top = sg([sgRow(null, [cell(f0(nfl.length), 'Titles', 'Super Bowls, NFL championships before them, AFL championships'), cell(`${t.sb.w}-${t.sb.apps - t.sb.w}`, 'Super Bowls', 'Super Bowl record'),
        cell(`${t.w}-${t.l}`, 'Record', `Playoff games won-lost (${pct(t.w, t.l)})`), cell(f0(t.apps), 'Appearances', 'Postseasons with a playoff game (NFL / AFL)')]),
      sgRow(null, [r ? cell(`${Math.round(100 * r.apps / Math.max(1, r.seasons))}%`, `Since ${r.since}`, `In the playoffs ${r.apps} of ${r.seasons} seasons since ${r.since === 1970 ? 'the 1970 merger' : `${r.since} (first season)`}`) : '',
        cell(t.last ? esc(t.last) : '–', 'Last trip'), cell(t.drought != null ? f0(t.drought) : '–', 'Drought', 'Seasons since the last playoff appearance'), cell(f0(t.streak), 'Best streak', 'Most consecutive playoff seasons')])], 4, { labels: false, cls: 'sg-tight' });
    const titles = nfl.length || aafc.length ? `<div class="po-titles">${nfl.map(x => `<span class="ij-part"><b>${x.s}</b> ${esc(TITLE_NAME[x.kind])}</span>`).join('')}${aafc.map(x => `<span class="ij-part muted" title="AAFC titles are not NFL records"><b>${x.s}</b> AAFC (not NFL)</span>`).join('')}</div>` : '';
    const best = t.best ? `<p class="pc-sub">Best finish: <b>${esc(t.best)}</b> (${t.best_s.slice(0, 8).join(', ')}${t.best_s.length > 8 ? '&hellip;' : ''})</p>` : '';
    const order = ['SB', 'CONF', 'DIV', 'WC', 'LCH', 'OTHER'].filter(k => t.rounds[k]);
    const rounds = `<table class="bx tpo-rd"><thead><tr><th>Round</th><th class="num">W-L</th><th class="num">Win %</th></tr></thead><tbody>${order.map(k => `<tr><td>${esc(RD_NAME[k])}</td><td class="num">${t.rounds[k].w}-${t.rounds[k].l}</td><td class="num">${pct(t.rounds[k].w, t.rounds[k].l)}</td></tr>`).join('')}</tbody></table>`;
    const RD_SHORT = { WC: 'WC', DIV: 'DIV', CONF: 'CON', SB: 'SB', LCH: 'CH', OTHER: 'TB' };
    const seasons = t.seasons.map(S => `<div class="tpo-s${S.fin === 'title' ? ' champ' : ''}"><div class="tpo-h"><b>${S.s}</b>${S.seed ? ` <span class="muted">#${S.seed} seed</span>` : ''}${S.name && S.name !== (tInfo(abbr).name || '') ? ` <span class="muted">${esc(S.name)}</span>` : ''}
        <span class="tpo-fin${S.fin === 'title' ? ' good' : ''}">${esc(S.fin_label)}${S.aafc ? ' (AAFC)' : ''}</span></div>
        ${[...S.games].reverse().map(g => `<div class="tpo-g"${g.gid ? ` data-gid="${esc(g.gid)}" role="link" title="Open the gamecast"` : ''}><span class="tpo-rd" title="${esc(g.label)}">${esc(RD_SHORT[g.rd] || g.rd)}</span>
          <span class="tm-res ${g.r === 'W' ? 'w' : 'l'}">${g.r}</span> <b>${g.ps}-${g.pa}</b> <span>${g.h === 0 ? '@' : g.h === 2 ? 'vs' : 'vs'} <button type="button" class="tm-open" data-tm="${esc(g.o)}">${esc(g.on)}</button></span></div>`).join('')}</div>`).join('');
    return `<div class="pc-box"><div class="pc-k">Postseason history</div>${top}${titles}${best}</div>
      <div class="pc-box"><div class="pc-k">By round</div>${rounds}</div>
      <div class="pc-box"><div class="pc-k">Every postseason · newest first</div>${seasons}
        <p class="pc-sub">Every playoff game since 1933 (1920-32 champions from the standings). AFL games count; AAFC games and titles (1946-49) are shown but are not NFL records.</p></div>`;
  };
  // Playoff odds by week + rooting guide (data/playoffs/odds.json, tools/playoff_odds.py; owner 2026-10-15). The guide
  // covers the current week only: each unplayed game's effect on this team's chances, from the same simulated seasons
  // with only that game flipped (PFF's paired method), so small swings aren't noise. Ranked by the chance that's still
  // in play: making the playoffs, else the division, else the top seed.
  let ODDS;
  const oddsData = () => {
    if (ODDS === undefined) {
      ODDS = null;
      NFLE.load('data/playoffs/odds.json').then(x => { ODDS = x || false; if (cardTeam) renderTeam(cardTeam); }).catch(() => { ODDS = false; });
    }
    return ODDS || null;
  };
  const RT_GOAL = ['make the playoffs', 'win the division', 'get the top seed'], RT_SHORT = ['Playoffs', 'Division', 'Top seed'];
  const rtPct = v => v >= 0.9995 ? '>99.9%' : v > 0 && v < 0.0005 ? '<0.1%' : `${(v * 100).toFixed(1)}%`;
  const rtPts = v => `${v >= 0 ? '+' : '−'}${Math.abs(v * 100).toFixed(1)}`;
  const rtGoal = r => r.p_playoffs > 0.03 && r.p_playoffs < 0.95 ? 0 : r.p_div > 0.03 && r.p_div < 0.97 ? 1 : r.p_bye > 0.02 && r.p_bye < 0.98 ? 2 : 0;
  const rtTeam = (O, t) => (O.teams || []).find(r => r.team === t) || {};
  const rtRows = (O, abbr) => {
    const R = O && O.root, T = R && R.teams && R.teams[abbr];
    if (!T) return null;
    const m = rtGoal(rtTeam(O, abbr));
    const games = R.games.map((g, i) => {
      const [sw, se, ph, pa] = T.g[i], own = g.home === abbr || g.away === abbr;
      const home = own ? g.home === abbr : sw[m] >= 0;
      const gain = k => home ? sw[k] : -sw[k];  // this team's change if the side it roots for wins
      const real = k => Math.abs(sw[k]) >= 0.005 && Math.abs(sw[k]) >= 2 * se[k];
      return { g, own, root: home ? g.home : g.away, vs: home ? g.away : g.home, v: gain(m), sig: real(m), gain, real,
               pw: home ? ph : pa, pl: home ? pa : ph };
    }).sort((a, b) => b.own - a.own || Math.abs(b.v) - Math.abs(a.v));
    return { m, T, games };
  };
  // one line for the Week tab (current week only)
  const rootLine = (abbr, d) => {
    const O = oddsData(), x = O && +O.season === +d.season && O.root && +O.root.week === +d.week ? rtRows(O, abbr) : null;
    if (!x) return '';
    const sig = x.games.filter(r => !r.own && r.sig && r.v > 0).slice(0, 3);
    return `<div class="pc-box rt-line"><span class="pc-k">Rooting interests</span> ${sig.length
      ? sig.map(r => `${tmL(r.root, `<b>${esc(rtTeam(O, r.root).nick || r.root)}</b>`)} <small class="muted">${rtPts(r.v)}</small>`).join(' · ')
      : '<span class="muted">no other game moves their odds much</span>'} <button type="button" class="rt-more" data-tt-go="po">Full guide</button></div>`;
  };
  // odds by week: lines going into each week, dashed to next week's best / worst case; schedule along the bottom
  const oddsChart = (abbr, O) => {
    const H = O.hist || {}, weeks = Object.keys(H).map(Number).filter(w => H[w] && H[w][abbr]).sort((a, b) => a - b);
    if (!weeks.length) return '';
    const sch = (O.sched || {})[abbr] || [], byW = Object.fromEntries(sch.map(g => [g[0], g]));
    const nW = Math.max(18, ...sch.map(g => g[0])), R = O.root, T = R && R.teams && R.teams[abbr];
    const W = 360, L = 26, Rt = 34, top = 12, ch = 140, Hh = top + ch + 58;
    const X = w => L + (W - L - Rt) * (w - 1) / (nW - 1), Y = v => top + ch * (1 - v);
    const last = weeks[weeks.length - 1], nx = R && T && +R.week === last && last < nW ? last + 1 : null;
    const grid = [0, 0.2, 0.4, 0.6, 0.8, 1].map(v => `<line x1="${L}" x2="${W - Rt}" y1="${Y(v)}" y2="${Y(v)}" class="oc-grid"/><text x="${L - 4}" y="${Y(v) + 3}" class="oc-y">${v * 100}%</text>`).join('');
    const ser = [[0, 'po', 'Make playoffs'], [1, 'dv', 'Win division'], [2, 'ts', 'Top seed']].map(([k, c, label]) => {
      const pts = weeks.map(w => [X(w), Y(H[w][abbr][k]), H[w][abbr][k], w]);
      const [lx, ly] = pts[pts.length - 1];
      const dash = nx ? [T.best[k], T.worst[k]].map((v, i) => `<line x1="${lx}" y1="${ly}" x2="${X(nx)}" y2="${Y(v)}" class="oc-l oc-${c} oc-dash"/>
          <circle cx="${X(nx)}" cy="${Y(v)}" r="2.6" class="oc-p oc-${c} oc-open"><title>Week ${nx} if every week ${last} game goes ${i ? 'against them' : 'their way'}: ${rtPct(v)}</title></circle>
          <text x="${X(nx) + 5}" y="${Y(v) + (i ? 8 : -2)}" class="oc-v oc-${c}">${(v * 100).toFixed(0)}</text>`).join('') : '';
      return `<polyline points="${pts.map(q => `${q[0].toFixed(1)},${q[1].toFixed(1)}`).join(' ')}" class="oc-l oc-${c}"/>${dash}
        ${pts.map(([x, y, v, w]) => `<circle cx="${x}" cy="${y}" r="2.8" class="oc-p oc-${c}"><title>${label}, going into week ${w}: ${rtPct(v)}</title></circle>`).join('')}`;
    }).join('');
    const axis = Array.from({ length: nW }, (_, i) => i + 1).map(w => {
      const g = byW[w], x = X(w), y0 = top + ch + 12, lg = g && rtTeam(O, g[1]).logo;
      if (!g) return `<text x="${x}" y="${y0}" class="oc-w">${w}</text><text x="${x}" y="${y0 + 22}" class="oc-bye">BYE</text>`;
      const res = g[3] == null ? `<text x="${x}" y="${y0 + 38}" class="oc-r">${g[2] ? 'vs' : '@'}</text>`
        : `<text x="${x}" y="${y0 + 38}" class="oc-r ${g[3] > g[4] ? 'w' : g[3] < g[4] ? 'l' : ''}">${g[3] > g[4] ? 'W' : g[3] < g[4] ? 'L' : 'T'}</text><text x="${x}" y="${y0 + 46}" class="oc-sc">${g[3]}-${g[4]}</text>`;
      return `<g class="tm-open" data-tm="${esc(g[1])}"><title>Week ${w} · ${esc(g[5])} · ${g[2] ? 'vs' : '@'} ${esc(rtTeam(O, g[1]).nick || g[1])}${g[3] != null ? ` · ${g[3]}-${g[4]}` : ''}</title>
        <text x="${x}" y="${y0}" class="oc-w">${w}</text>${lg ? `<image href="${esc(lg)}" x="${x - 7}" y="${y0 + 5}" width="14" height="14"/>` : `<text x="${x}" y="${y0 + 16}" class="oc-r">${esc(g[1])}</text>`}${res}</g>`;
    }).join('');
    return `<svg class="oc" viewBox="0 0 ${W} ${Hh}" width="100%" role="img" aria-label="Playoff chances by week">${grid}${ser}${axis}</svg>
      <div class="oc-key"><span class="oc-k oc-po">Make playoffs</span><span class="oc-k oc-dv">Win division</span><span class="oc-k oc-ts">Top seed</span>${nx ? `<span class="muted">dashed: week ${nx} if every week ${last} game goes their way / against them</span>` : ''}</div>`;
  };
  const rootGuide = (abbr, O) => {
    const x = rtRows(O, abbr);
    if (!x) return '';
    const nick = t => rtTeam(O, t).nick || t, goal = RT_GOAL[x.m];
    const own = x.games.find(r => r.own), rest = x.games.filter(r => !r.own);
    const sig = rest.filter(r => r.sig), quiet = rest.length - sig.length;
    const chips = r => [0, 1, 2].filter(k => k !== x.m && r.real(k) && Math.abs(r.gain(k)) >= 0.01).map(k => {
      const v = r.gain(k);
      return `<span class="rt-chip ${v > 0 ? 'good' : 'bad'}"${v < 0 ? ` title="Helps their chance to ${goal}, hurts their chance to ${RT_GOAL[k]}"` : ''}>${RT_SHORT[k]} ${rtPts(v)}</span>`;
    }).join('');
    const detail = r => `<table class="bx rt-dt"><thead><tr><th></th><th class="num">If ${tmL(r.root, esc(nick(r.root)))} win</th><th class="num">If ${tmL(r.vs, esc(nick(r.vs)))} win</th></tr></thead><tbody>
      ${[0, 1, 2].map(k => `<tr${k === x.m ? ' class="rt-main"' : ''}><td>${RT_SHORT[k]}</td><td class="num">${rtPct(r.pw[k])}</td><td class="num">${rtPct(r.pl[k])}</td></tr>`).join('')}</tbody></table>`;
    const row = r => `<details class="rt-g"><summary>${tmL(r.root, tLogo(r.root, 20))}<span class="rt-nm">${tmL(r.root, `<b>${esc(nick(r.root))}</b>`)} over ${tmL(r.vs, esc(nick(r.vs)))}</span>
        ${chips(r)}<span class="rt-v ${r.v > 0 ? 'good' : ''}">${rtPts(r.v)}</span></summary>${detail(r)}</details>`;
    const say = sig.filter(r => r.v > 0).slice(0, 4).map(r => tmL(r.root, esc(nick(r.root))));
    const ownHtml = own ? `<div class="rt-own"><div class="pc-k">Their game</div>${tmL(own.vs, tLogo(own.vs, 20))}<span>${own.g.home === abbr ? 'vs' : '@'} ${tmL(own.vs, `<b>${esc(nick(own.vs))}</b>`)}</span>
        <span class="rt-wl"><span>Win <b>${rtPct(own.pw[x.m])}</b></span><span>Lose <b>${rtPct(own.pl[x.m])}</b></span></span></div>`
      : `<p class="pc-sub">Bye this week: how the rest of the league's games move their chances.</p>`;
    return `<div class="pc-box rt-box"><div class="pc-k">Rooting guide · week ${O.root.week}</div>
      <p class="rt-say">${say.length ? `Root for the <b>${say.length > 1 ? `${say.slice(0, -1).join(', ')}</b> and <b>${say[say.length - 1]}` : say[0]}</b>.` : 'No other game this week moves their odds much.'}</p>
      ${ownHtml}
      ${sig.length ? `<div class="rt-list"><div class="rt-hd"><span>Root for</span><span>Chance to ${goal}, pts</span></div>${sig.map(row).join('')}</div>` : ''}
      ${quiet ? `<p class="pc-sub">${quiet} other game${quiet > 1 ? 's' : ''}: negligible (under half a point, or within simulation noise).</p>` : ''}
      <p class="pc-sub">Each number is the change in their chance to ${goal} between the two results: the same ${O.root.n_flip.toLocaleString()} simulated seasons with only that game flipped. Tap a game for both outcomes. Green / red tags: the game also moves another chance by a point or more (red means the two pull opposite ways).</p></div>`;
  };
  const rootingHtml = abbr => {
    const O = oddsData();
    if (O === null && ODDS !== false) return '<div class="pc-box"><p class="pc-sub">Loading playoff odds&hellip;</p></div>';
    if (!O || !O.teams || !rtTeam(O, abbr).team) return '';
    const r = rtTeam(O, abbr), H = O.hist || {}, prev = H[O.as_of_week - 1] && H[O.as_of_week - 1][abbr];
    const stat = (k, label, v) => `<div class="tm-st"><div class="pc-k">${label}</div><div class="tm-stv">${rtPct(v)}</div>${prev ? `<div class="pc-sub" title="Going into week ${O.as_of_week - 1}">was ${rtPct(prev[k])}</div>` : ''}</div>`;
    return `<div class="pc-box oc-box"><div class="pc-k">${O.season} playoff chances · going into each week</div>
        <div class="tm-stats oc-stats">${stat(0, 'Make playoffs', r.p_playoffs)}${stat(1, 'Win division', r.p_div)}${stat(2, 'Top seed', r.p_bye)}</div>
        ${oddsChart(abbr, O)}<p class="pc-sub">${O.sims.toLocaleString()} simulated seasons with the real tiebreakers (Teams &rsaquo; Playoffs has the method and its track record).</p></div>
      ${rootGuide(abbr, O)}`;
  };
  // Games > Matchups: the week's biggest games for the playoff race (playoff-odds swing summed over every team,
  // weighted by how close the game is) get a one-line note on their tile.
  NFLE.rootStakes = () => NFLE.load('data/playoffs/odds.json').then(O => {
    const R = O && O.root;
    if (!R || !R.games) return [];
    return R.games.map((g, i) => {
      const hit = Object.entries(R.teams).map(([t, T]) => [t, Math.abs(T.g[i][0][0]), T.g[i][1][0]]).filter(([, v, se]) => v >= 0.02 && v >= 2 * se)
        .sort((a, b) => b[1] - a[1]);
      const tot = hit.reduce((a, [, v]) => a + v, 0);
      return { id: g.id, tot, lev: 2 * g.p_home * (1 - g.p_home) * tot, teams: hit.map(h => h[0]) };
    }).filter(x => x.tot >= 0.05).sort((a, b) => b.lev - a.lev).slice(0, 3);
  }).catch(() => []);
  const renderTeam = abbr => {
    const body = document.querySelector('#pcOv .pc-body');
    const d = cardData(), L = TLOGS[abbr], info = tInfo(abbr);
    cardNeeds();
    // Header, season box and game log are current; the Week tab (matchup, Power, players) follows the picker.
    const wk = d ? teamWeek(abbr, d) : { html: wkWait(d), players: '' };
    body.innerHTML = `
      <div class="pc-head" style="--tc:${esc(info.color || '#666')}"><span class="pc-logo-z" data-zoom="${esc(info.logo ? logoSrc(info.logo, 500) : '')}" role="button" tabindex="0" aria-label="Show a bigger logo">${tLogo(abbr, 34)}</span>
        <div class="pc-id"><h3 id="pcName">${esc(info.name || abbr)}</h3>
          <div class="pc-meta"><b>${esc((L && (L.seasons.find(s => s.s === L.cur) || {}).rec) || '')}</b>${info.division ? ` <span class="muted">${esc(info.division)}</span>` : ''}</div></div></div>
      <div class="seg pc-tabs" role="tablist">${[['ov', 'Week'], ['log', 'Game log'], ['pl', 'Players'], ['dc', 'Depth'], ['po', 'Playoffs']].map(([k, l]) => `<button type="button" role="tab" data-tt="${k}" class="${teamTab === k ? 'on' : ''}">${l}</button>`).join('')}</div>
      <div class="pc-tab" data-tt="ov"${teamTab === 'ov' ? '' : ' hidden'}>${pickerHtml()}<div class="pc-cols"><div class="pc-col">${wk.html}</div><div class="pc-col"><div class="tm-season">${L ? teamSeasonBox(L) : ''}</div><div class="tm-pen"></div></div></div></div>
      <div class="pc-tab" data-tt="log"${teamTab === 'log' ? '' : ' hidden'}><div class="pc-box pc-logbox"><div class="pc-k">Every game since 1999</div><div class="tm-log">${L ? teamLogHtml(L, abbr) : '<p class="pc-sub">Loading game log&hellip;</p>'}</div></div></div>
      <div class="pc-tab" data-tt="pl"${teamTab === 'pl' ? '' : ' hidden'}>${pickerHtml()}${d ? `<div class="pc-box"><div class="pc-k">Fantasy players · ${esc(wkLabel(d).toLowerCase())}</div>
        ${wk.players ? `<table class="bx tm-pl tiles"><thead><tr><th>Player</th><th class="num">Proj</th><th>Tier</th><th class="num">FP/G</th></tr></thead><tbody>${wk.players}</tbody></table>` : '<p class="pc-sub">No fantasy-relevant players listed that week.</p>'}</div>` : wkWait(d)}</div>
      <div class="pc-tab" data-tt="dc"${teamTab === 'dc' ? '' : ' hidden'}>${teamTab === 'dc' ? depthHtml(abbr) : ''}</div>
      <div class="pc-tab" data-tt="po"${teamTab === 'po' ? '' : ' hidden'}>${teamTab === 'po' ? rootingHtml(abbr) + teamPlayoffs(abbr) : ''}</div>`;
    body.querySelectorAll('[data-tt]').forEach(b => b.onclick = () => {
      teamTab = b.dataset.tt;
      rememberTab(`t:${abbr}`, teamTab);
      if (teamTab === 'dc') { body.querySelector('.pc-tab[data-tt="dc"]').innerHTML = depthHtml(abbr); wireDepth(body, abbr); }
      if (teamTab === 'po') body.querySelector('.pc-tab[data-tt="po"]').innerHTML = rootingHtml(abbr) + teamPlayoffs(abbr);
      body.querySelectorAll('.pc-tabs [data-tt]').forEach(x => x.classList.toggle('on', x === b));
      body.querySelectorAll('.pc-tab').forEach(t => { t.hidden = t.dataset.tt !== teamTab; });
    });
    body.querySelectorAll('[data-tt-go]').forEach(b => b.onclick = () => { const t = body.querySelector(`.pc-tabs [data-tt="${b.dataset.ttGo}"]`); if (t) { t.click(); t.scrollIntoView({ block: 'nearest' }); } });
    wireTeamLog(body, abbr);
    wireDepth(body, abbr);
    // penalties: the current season once it has games, else the last one
    const tp = body.querySelector('.tm-pen');
    if (tp) penIndex().then(ix => ix && penSeason(ix.current).then(D => D && D.teams[abbr] && D.teams[abbr].g >= 1 ? D : penSeason(ix.current - 1)))
      .then(D => { if (cardTeam === abbr && D) tp.innerHTML = teamPenBox(abbr, D); });
    body.addEventListener('click', e => {  // playoff game rows open their gamecast
      const g = e.target.closest('.tpo-g[data-gid]'); if (!g || e.target.closest('button, a')) return;
      location.href = gcUrl(g.dataset.gid, '');
    });
    wireLogRows(body.querySelector('.tm-log'));
    wirePicker(body);
    NFLE.paintTiles();
    if (!L) loadTeamLog(abbr);
  };
  // The team's Week tab for one week's data: result / live score, matchup and odds, Power box; plus its player rows.
  const teamWeek = (abbr, d) => {
    const pw = (d.power || []).find(x => x.team === abbr), g = teamGame(abbr, d);
    const opp = g && (g.away.team === abbr ? g.home : g.away), home = g && g.home.team === abbr;
    // the Games tab's tile (win chances, line, ours; the score once it starts, repainted live)
    const week = g ? `<div class="pc-k pc-mtk">${esc(wkLabel(d))}</div><div class="pc-mt">${NFLE.ui.matchTile(g, gameHref(g, d))}</div>`
      : `<div class="pc-box"><div class="pc-k">${esc(wkLabel(d))}</div><b>Bye</b></div>`;
    const unit = (label, v, rk, pp, total) => `<div class="tm-u${total ? ' tm-tot' : ''}"><span class="tm-ul">${label}</span><span class="tm-uv">${sgn(v)}</span>${rkChip(rk)}
      <span class="tm-ub"><span style="${v >= 0 ? `left:50%;width:${Math.min(50, Math.abs(v) * 10)}%` : `right:50%;width:${Math.min(50, Math.abs(v) * 10)}%`}" class="${v >= 0 ? 'pos' : 'neg'}"></span></span>
      ${pp != null ? `<span class="tm-pp muted" title="EPA per 100 plays">${sgn(pp)}</span>` : '<span></span>'}</div>`;
    // one full-width box (it was alone in a two-column grid, leaving the right half empty); wide screens split it:
    // rank + unit bars left, the note + rank-by-week chart right
    const power = pw ? `<div class="pc-box tm-pwbox"><div class="tm-pwl"><div class="pc-k">Power ranking</div>
        <div class="tm-pw"><div><div class="pc-big">${ord(pw.rank)}</div><div class="pc-sub">rank range ${esc(pw.range)}${pw.move ? ` · ${pw.move > 0 ? '▲' : '▼'}${Math.abs(pw.move)} from the week before` : ''}</div></div>
          <div><div class="pc-big sm">${sgn(pw.net)} <small>pts/g vs avg</small></div></div></div>
        <div class="tm-units">${unit('Offense', pw.off, pw.off_rk, null, true)}${unit('Pass O', pw.pass_o, pw.pass_o_rk, pw.pass_o_pp)}${unit('Run O', pw.rush_o, pw.rush_o_rk, pw.rush_o_pp)}
          ${unit('Defense', pw.def, pw.def_rk, null, true)}${unit('Pass D', pw.pass_d, pw.pass_d_rk, pw.pass_d_pp)}${unit('Run D', pw.rush_d, pw.rush_d_rk, pw.rush_d_pp)}
          ${unit('Special teams', pw.st, pw.st_rk, null, true)}</div></div>
        <div class="tm-pwr"><div class="pc-sub">Points per game vs an average team (opponent-adjusted). Schedule so far ${ord(pw.sos_past_rk)} hardest · rest of season ${ord(pw.sos_next_rk)} hardest.</div>
        ${rankTrend(pw.rank_hist) ? `<div class="pc-k" style="margin-top:10px">Power rank by week</div>${rankTrend(pw.rank_hist)}` : ''}</div></div>` : '';
    const players = Object.entries(d.players).filter(([, p]) => p.team === abbr).sort((a, b) => b[1].proj - a[1].proj);
    const plRows = players.map(([pid, p]) => { const s = scaled(p, d);
      return `<tr class="teamrow" style="${NFLE.fmt.rowStyle(d.teams, p.team)}" data-open-pid="${esc(pid)}"><td>${NFLE.ui.player({ name: p.name, pos: p.pos, team: p.team, photo: p.photo, espn: p.espn, badges: injTag(p.status) }, d.teams)}</td>
        <td class="num"><b>${f1(s.proj)}</b></td><td><span class="tier t-${esc(p.slot)}">${esc(p.tier)}</span></td><td class="num muted">${p.fpg != null ? f1(p.fpg) : ''}</td></tr>`; }).join('');
    return { html: `${week}${rootLine(abbr, d)}<div class="pc-grid tm-grid">${power}</div>`, players: plRows };
  };
  const wireTeamLog = (body, abbr) => {
    const sel = body.querySelector('[data-topp]');
    if (sel) sel.onchange = () => { teamOpp = sel.value; body.querySelector('.tm-log').innerHTML = teamLogHtml(TLOGS[abbr], abbr); wireTeamLog(body, abbr); };
  };
  // one fetch per team: renders while it's in flight used to start their own (4 copies of a 97 KB file)
  const TLOGP = {};
  const loadTeamLog = abbr => TLOGP[abbr] || (TLOGP[abbr] = (async () => {
    try { TLOGS[abbr] = await getJSON(`${siteRoot()}data/teams/${encodeURIComponent(abbr)}.json`); }
    catch (e) { delete TLOGP[abbr]; const b = document.querySelector('#pcOv .tm-log'); if (b) b.innerHTML = '<p class="pc-sub">Game log unavailable.</p>'; return; }
    if (cardTeam === abbr) renderTeam(abbr);
  })());
  // Page mode (week pages with the app shell): players and teams are PAGES at #player/<id> / #team/<abbr>. Opening
  // one sets the hash (a real history entry, so Back works); the shell routes it and calls NFLE.showPlayer / showTeam.
  const pageMode = () => !!(window.NFLE && window.NFLE.pageMode);
  const openTeam = abbr => {
    if (pageMode()) { if (location.hash !== `#team/${abbr}`) location.hash = `team/${abbr}`; else showTeam(abbr); return; }
    showTeam(abbr);
  };
  const showTeam = abbr => {
    if (!DATA) return;
    const ov = ensureOverlay();
    if (!location.hash.startsWith('#player/') && !location.hash.startsWith('#team/')) prevHash = location.hash;
    // a team you tap opens on Summary (owner 2026-10-17); one you come back to down the card stack keeps its tab
    if (window.NFLE && NFLE.cardRestore) teamTab = TABS[`t:${abbr}`] || 'ov';
    else if (abbr !== cardTeam || ov.hidden || (window.NFLE && NFLE.freshPage)) teamTab = 'ov';
    if (abbr !== cardTeam) teamOpp = '';
    // a fresh card starts on the page's week; card-to-card keeps the picked one (page mode: the shell flags fresh)
    if (ov.hidden || !cardWk || (window.NFLE && NFLE.freshPage)) cardWk = pageKey();
    cardPid = null; cardTeam = abbr;
    renderTeam(abbr);
    ov.hidden = false;
    document.documentElement.classList.add('pc-open');
    if (!pageMode()) { try { history.replaceState(null, '', location.pathname + location.search + '#team/' + abbr); } catch (e) { /* ignore */ } }
    ov.querySelector('.pc').scrollTop = 0; ov.scrollTop = 0;
  };

  const openPlayer = pid => {
    if (pageMode()) { if (location.hash !== `#player/${pid}`) location.hash = `player/${pid}`; else showPlayer(pid); return; }
    showPlayer(pid);
  };
  const showPlayer = pid => {
    if (!DATA) return;
    const ov = ensureOverlay();
    if (!location.hash.startsWith('#player/') && !location.hash.startsWith('#team/')) prevHash = location.hash;
    // a player you tap opens on Summary (owner 2026-10-17: "not remember what tab i was on before"); one you come back
    // to down the card stack keeps its tab
    if (window.NFLE && NFLE.cardRestore) cardTab = TABS[`p:${pid}`] || 'ov';
    else if (pid !== cardPid || ov.hidden || (window.NFLE && NFLE.freshPage)) cardTab = 'ov';
    if (ov.hidden || !cardWk || (window.NFLE && NFLE.freshPage)) cardWk = pageKey();
    cardPid = pid; cardTeam = null;
    renderCard(pid);
    ov.hidden = false;
    document.documentElement.classList.add('pc-open');
    if (!pageMode()) { try { history.replaceState(null, '', location.pathname + location.search + '#player/' + pid); } catch (e) { /* ignore */ } }
    ov.querySelector('.pc').scrollTop = 0;
  };

  // ------------------------------------------------------------------------------------------- live (week page)
  const LIVE = { byGame: {}, lines: {}, sums: {}, fetched: {}, timer: null };
  const rowsFor = espn => [...document.querySelectorAll(`tr.main[data-espn="${CSS.escape(espn)}"]`)];
  const paintRows = () => {
    const w = weights();
    Object.entries(LIVE.lines).forEach(([espn, o]) => {
      rowsFor(espn).forEach(tr => {
        const g = teamGame(tr.dataset.team), st = g && LIVE.byGame[g.id];
        if (!st) return;
        if (!tr._sc && !tr.dataset.sc) return;  // client-rendered rows (Rankings) paint their own actuals
        const sc = tr._sc || (tr._sc = JSON.parse(tr.dataset.sc));
        const live = st.state === 'in';
        if (!live && sc.ac && !tr.dataset.live) return;  // our own final stats are already on the page
        sc.ac = o.line;
        tr.dataset.live = live ? '1' : '0';
        const cell = tr.querySelector('td.actc'); if (!cell) return;
        const v = pts(o.line, w, tr.dataset.pos);
        const ratio = (() => { const p = DATA.players[tr.dataset.pid]; return p ? scaled(p).ratio : 1; })();
        const q = tr._q || tr.dataset.p.split(' ').map(x => parseFloat(x) * ratio);
        cell.innerHTML = `${live ? '<span class="live-dot"></span>' : ''}<span class="act-v">${f1(v)}</span>`;
        cell.title = `${live ? 'Live' : 'Final'} (${st.short || ''}): ${statLineText(o, tr.dataset.pos)}`;
        cell.dataset.v = v.toFixed(2);
        cell.classList.toggle('act-hi', !live && v > q[2]); cell.classList.toggle('act-lo', !live && v < q[1]);
      });
    });
  };
  // How the pregame forecast fared, as the build's final tiles say it (fav_won from our own final scores).
  const verdict = (fc, winner) => !winner ? '<span class="gf-pick toss">Tie</span>'
    : fc.tossup ? `<span class="gf-pick toss">Tossup · ${tmL(winner)} won</span>`
      : fc.fav === winner ? `<span class="gf-pick ok">Favorite won · ${fc.pct}%</span>`
        : `<span class="gf-pick miss">Upset · a ${100 - fc.pct}% chance</span>`;
  // Matchups tiles: live (and just-finished) games painted from ESPN over the build's pregame tile. Finals the
  // build already knows stay as built.
  const paintTiles = () => {
    document.querySelectorAll('a.mt[data-gid]').forEach(tile => {
      const st = LIVE.byGame[tile.dataset.gid];
      if (!st || st.state === 'pre' || tile.classList.contains('is-final')) return;
      const live = st.state === 'in', g = DATA.games.find(x => x.id === tile.dataset.gid);
      const sit = live ? (st.sit || (LIVE.sums[st.id] && sitFromPlays(LIVE.sums[st.id]))) : null;
      const sp = sit ? spot(sit, st) : null;
      // The big numbers switch from pregame win chances to the score.
      tile.classList.remove('is-pre', 'toss');
      const tag = tile.querySelector('.mt-at small'); if (tag) tag.remove();  // pregame "Tossup" label
      ['away', 'home'].forEach(k => {
        const side = tile.querySelector(`.mt-side.${k}`); if (!side) return;
        side.querySelector('.mt-num').textContent = st[k].score;
        side.classList.remove('dog');
        side.classList.toggle('lost', !live && st[k].score < st[k === 'away' ? 'home' : 'away'].score);
        side.classList.toggle('has-ball', !!(sp && sp.offense.team === st[k].team));
        // once it's final, ESPN's record includes this game (the built page has the record from before kickoff)
        const rec = side.querySelector('.mt-nm small');
        if (rec && !live && st[k].record) rec.textContent = st[k].record;
      });
      const winner = st.away.score > st.home.score ? st.away.team : st.home.score > st.away.score ? st.home.team : null;
      tile.querySelector('.mt-st').innerHTML = live
        ? `<span class="mt-live"><span class="live-dot"></span>${esc(st.short || '')}</span>${sp && sp.text ? `<span>${tmL(sp.offense.team)} ball · ${esc(sp.text)}</span>` : ''}${sp && sp.red ? '<span class="mt-red">red zone</span>' : ''}`
        : `<span class="mt-fin">${esc(st.detail || 'Final')}</span>${g && g.fc ? verdict(g.fc, winner) : ''}`;
    });
  };
  const paintPill = () => {
    const pill = document.getElementById('livePill'); if (!pill) return;
    const sts = Object.values(LIVE.byGame), live = sts.filter(s => s.state === 'in').length;
    if (!live) { pill.hidden = true; return; }
    pill.innerHTML = `<i class="live-dot"></i><b>${live} live</b>${SIM ? ' (test mode)' : ''}`;
    pill.hidden = false;
  };
  const pollWeek = async () => {
    clearTimeout(LIVE.timer);
    let evs = [];
    try { evs = await weekEvents(DATA.season, DATA.week); } catch (e) { LIVE.timer = setTimeout(pollWeek, 120000); return; }
    const games = Object.fromEntries(DATA.games.map(g => [gKey(g.away.team, g.home.team), g]));
    evs.forEach(ev => { const g = games[evKey(ev)]; if (g) LIVE.byGame[g.id] = evInfo(ev); });
    const now = Date.now();
    const jobs = Object.entries(LIVE.byGame).filter(([, st]) =>
      st.state === 'in' ? now - (LIVE.fetched[st.id] || 0) > 55000 : st.realState === 'post' && !LIVE.fetched[st.id]);
    await Promise.all(jobs.map(async ([, st]) => {
      try {
        const sum = await getJSON(ESPN.sum + st.id);
        LIVE.sums[st.id] = sum; LIVE.fetched[st.id] = Date.now();
        Object.assign(LIVE.lines, boxLines(sum));
      } catch (e) { /* keep last good */ }
    }));
    paintRows(); paintTiles(); paintPill();
    if (cardPid) renderCard(cardPid); else if (cardTeam) renderTeam(cardTeam);
    const sts = Object.values(LIVE.byGame);
    const soon = sts.some(s => s.state === 'pre' && new Date(s.date).getTime() - now < 30 * 60000);
    const live = sts.some(s => s.state === 'in');
    const later = sts.some(s => s.state === 'pre');
    const next = live ? 30000 : soon ? 60000 : later ? 300000 : 0;
    if (next && !SIM) LIVE.timer = setTimeout(pollWeek, next);
  };
  const startLive = () => {
    // after the first paint, not during it: the scoreboard + finished-game box scores (~75 KB) and the repaint they
    // trigger were landing in the middle of the first render (Lighthouse 2026-10-16). Safari has no requestIdleCallback.
    const idle = window.requestIdleCallback || (f => setTimeout(f, 600));
    idle(() => pollWeek(), { timeout: 1500 });
    document.addEventListener('visibilitychange', () => {
      if (document.hidden) clearTimeout(LIVE.timer); else pollWeek();
    });
  };

  // ------------------------------------------------------------------------------------------------- game page
  const GP = { sum: null, info: null, g: null, timer: null, view: 'drive', filter: 'all', q: '', sort: 'new', replay: null, tab: null, pane: 'box' };
  const parseGid = gid => { const m = String(gid || '').match(/^(\d{4})_(\d{2})_([A-Z]{2,3})_([A-Z]{2,3})$/); return m ? { season: +m[1], week: +m[2], away: m[3], home: m[4] } : null; };
  const wpSeries = (sum) => {
    const plays = allPlays(sum).flatMap(d => d.plays || []);
    const byId = Object.fromEntries(plays.map(p => [String(p.id), p]));
    return (sum.winprobability || []).map(w => ({ w, p: byId[String(w.playId)] })).filter(x => x.p)
      .map(x => ({ t: elapsed(x.p), home: x.w.homeWinPercentage, play: x.p }));
  };
  const wpChart = (ser, info, upto) => {
    const pts_ = upto != null ? ser.filter(s => s.t <= upto) : ser;
    if (pts_.length < 2) return `<p class="muted">${info.state === 'post' ? 'ESPN has no win probability for this game (older games don\'t have one).'
      : 'ESPN has no live win probability for this game yet.'}</p>`;
    const ot = ser.some(s => s.t > 3600), T = ot ? 4200 : 3600, W = 640, H = 200, pad = 6;
    const X = t => pad + (W - 2 * pad) * t / T, Y = v => pad + (H - 2 * pad) * (1 - v);
    const line = pts_.map((s, i) => `${i ? 'L' : 'M'}${X(s.t).toFixed(1)} ${Y(s.home).toFixed(1)}`).join(' ');
    const area = `${line} L${X(pts_[pts_.length - 1].t).toFixed(1)} ${Y(0.5)} L${X(pts_[0].t).toFixed(1)} ${Y(0.5)} Z`;
    let grid = '';
    [900, 1800, 2700, 3600].concat(ot ? [] : []).forEach(t => { if (t < T) grid += `<line x1="${X(t)}" y1="${pad}" x2="${X(t)}" y2="${H - pad}" class="wp-g"/>`; });
    ['Q1', 'Q2', 'Q3', 'Q4'].concat(ot ? ['OT'] : []).forEach((q, i) => { grid += `<text x="${X(i * 900 + 450)}" y="${H - 10}" class="wp-q">${q}</text>`; });
    const marks = pts_.filter(s => s.play.scoringPlay || s.play.isTurnover).map(s => {
      const tm = s.play.scoringPlay ? 'score' : 'to';
      return `<circle cx="${X(s.t).toFixed(1)}" cy="${Y(s.home).toFixed(1)}" r="${tm === 'score' ? 3.4 : 3}" class="wp-m wp-${tm}"><title>${esc(s.play.text)}</title></circle>`;
    }).join('');
    const lastPt = pts_[pts_.length - 1];
    return `<svg class="wp" viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" role="img" aria-label="ESPN win probability over the game">
      <defs><clipPath id="wpTop"><rect x="0" y="0" width="${W}" height="${Y(0.5)}"/></clipPath><clipPath id="wpBot"><rect x="0" y="${Y(0.5)}" width="${W}" height="${H}"/></clipPath></defs>
      <rect x="0" y="0" width="${W}" height="${H}" class="wp-bg"/>${grid}
      <path d="${area}" style="fill:${esc(info.home.color)}" class="wp-a" clip-path="url(#wpTop)"/>
      <path d="${area}" style="fill:${esc(info.away.color)}" class="wp-a" clip-path="url(#wpBot)"/>
      <line x1="${pad}" y1="${Y(0.5)}" x2="${W - pad}" y2="${Y(0.5)}" class="wp-50"/>
      <path d="${line}" class="wp-line"/>${marks}
      <circle cx="${X(lastPt.t)}" cy="${Y(lastPt.home)}" r="4" class="wp-now"/>
      <line class="wp-hair" x1="0" x2="0" y1="${pad}" y2="${H - pad}" style="display:none"/></svg>`;
  };
  // One battle bar (report.tug): away team on the left, home on the right, the edge on the winner's side.
  const btChip = (r, what) => `<span class="bt-rk">${r ? `<span class="rk-b sm ${r <= 8 ? 'rk1' : r <= 16 ? 'rk2' : r <= 24 ? 'rk3' : 'rk4'}" title="${esc(what)}: ${ord(r)} of 32">${ord(r)}</span>` : ''}</span>`;
  const btRow = (x, label) => {
    const v = `+${(+x.pts || 0).toFixed(1)}`;
    return `<div class="bt-row" title="${esc(x.title)}"><span class="bt-lbl">${esc(label || x.label)}</span>${btChip(x.away_rk, x.away_what)}
      <span class="bt-v">${x.side === 'away' ? v : x.side === 'even' ? '<i>even</i>' : ''}</span>
      <span class="tug"><span class="tug-o" style="width:${(+x.split).toFixed(1)}%"></span><span class="tug-mid"></span></span>
      <span class="bt-v r">${x.side === 'home' ? v : x.side === 'even' ? '<i>even</i>' : ''}</span>${btChip(x.home_rk, x.home_what)}</div>`;
  };
  const teamStats = (sum, info) => {
    const T = (sum.boxscore && sum.boxscore.teams) || [];
    if (T.length < 2) return '';
    const by = {}; T.forEach(t => { by[ourCode(t.team.abbreviation)] = Object.fromEntries((t.statistics || []).map(s => [s.label, s.displayValue])); });
    const a = by[info.away.team] || {}, h = by[info.home.team] || {};
    const num = s => { if (s == null) return null; s = String(s); if (/^\d+:\d+$/.test(s)) { const [m, x] = s.split(':'); return +m * 60 + +x; }
                        if (/^\d+-\d+$/.test(s)) { const [m, n] = s.split('-').map(Number); return n ? m / n : 0; } const v = parseFloat(s); return isNaN(v) ? null : v; };
    const rows = ['Total Yards', 'Passing', 'Rushing', '1st Downs', '3rd down efficiency', '4th down efficiency', 'Red Zone (Made-Att)',
                  'Yards per Play', 'Total Plays', 'Turnovers', 'Sacks-Yards Lost', 'Penalties', 'Possession']
      .filter(k => a[k] != null || h[k] != null).map(k => {
        const x = num(a[k]), y = num(h[k]), tot = (x || 0) + (y || 0), sa = tot > 0 && x != null && y != null ? x / tot : 0.5;
        return `<div class="ts-row"><span class="ts-v">${esc(a[k] ?? '')}</span><span class="ts-k">${esc(k)}</span><span class="ts-v r">${esc(h[k] ?? '')}</span>
          <span class="ts-bar"><span style="width:${(sa * 100).toFixed(1)}%;background:${esc(info.away.color)}"></span><span style="flex:1;background:${esc(info.home.color)}"></span></span></div>`;
      }).join('');
    return `<div class="ts-head">${tmL(info.away.team, `<b>${esc(info.away.team)}</b>`)}${tmL(info.home.team, `<b>${esc(info.home.team)}</b>`)}</div>${rows}`;
  };
  // Drive results from the OFFENSE's side: ESPN's "Interception" on a DAL drive means DAL threw it.
  const driveResult = (d, tm, info, current) => {
    const r = String(d.displayResult || d.result || '');
    const opp = tm && tm.team === info.home.team ? info.away.team : info.home.team;
    if (!r) return { text: current ? 'In progress' : '', cls: '' };
    if (/intercept/i.test(r)) return { text: `Intercepted by ${opp}`, cls: 'bad' };
    if (/fumble/i.test(r)) return { text: `Fumble lost to ${opp}`, cls: 'bad' };
    if (/downs/i.test(r)) return { text: 'Turnover on downs', cls: 'bad' };
    if (/blocked/i.test(r)) return { text: `${r.replace(/^blocked\s*/i, '')} blocked by ${opp}`.trim(), cls: 'bad' };
    if (/safety/i.test(r)) return { text: `Safety (2 points to ${opp})`, cls: 'bad' };
    if (/missed/i.test(r)) return { text: r, cls: 'bad' };
    return { text: r, cls: d.isScore ? 'good' : '' };
  };
  // ESPN play text names players "D.Prescott" / "A.St. Brown": link the ones we have cards for (on either team in
  // this game; ambiguous initials are left as plain text).
  let ABBR = null;
  const abbrMap = () => {
    if (ABBR) return ABBR;
    ABBR = {};
    if (DATA) Object.entries(DATA.players).forEach(([pid, p]) => {
      const parts = String(p.name).split(' ');
      if (parts.length < 2) return;
      const key = `${parts[0][0]}.${parts.slice(1).join(' ')}`;
      (ABBR[key] = ABBR[key] || []).push({ pid, team: p.team });
    });
    return ABBR;
  };
  const linkNames = (html, teams) => {
    if (!DATA) return html;
    const m = abbrMap();
    return html.replace(/\b([A-Z])\.((?:St\. )?[A-Z][A-Za-z'\-]+(?: (?:Jr\.|Sr\.|II|III|IV))?)/g, (all, i, rest) => {
      const c = (m[`${i}.${rest}`] || []).filter(x => !teams || teams.includes(x.team));
      return c.length === 1 ? `<button type="button" class="nm-link" data-open-pid="${esc(c[0].pid)}">${all}</button>` : all;
    });
  };
  // opts overrides the Live tab's controls (the Postgame tab asks for just the top few swings).
  const gameLog = (sum, info, ser, upto, opts) => {
    const o = Object.assign({ sort: GP.sort, filter: GP.filter, q: GP.q, view: GP.view, limit: 40, note: true }, opts);
    const drives = allPlays(sum);
    const wpAfter = {}; ser.forEach((s, i) => { wpAfter[s.play.id] = { now: s.home, prev: i ? ser[i - 1].home : s.home }; });
    const teamOf = id => String(id) === String(info.home.id) ? info.home : String(id) === String(info.away.id) ? info.away : null;
    const q = o.q.trim().toLowerCase();
    const keep = p => (upto == null || elapsed(p) <= upto) && (o.filter === 'all' || (o.filter === 'score' && p.scoringPlay)
      || (o.filter === 'to' && p.isTurnover) || (o.filter === 'pen' && p.isPenalty)) && (!q || String(p.text).toLowerCase().includes(q));
    // First downs: ESPN doesn't flag them; a down-and-distance play earned one if the drive's next real play starts
    // at 1st down (a touchdown is its own highlight).
    const ttype = p => String((p.type && p.type.text) || '');
    const isNonPlay = p => /timeout|end period|end of|two-minute|end game|official|end quarter/i.test(ttype(p))
      || /^(END (GAME|QUARTER|OF)|Timeout|Two-Minute)/i.test(String(p.text || ''));
    const isST = p => /kickoff|punt|field goal|extra point|two-point|onside|blocked/i.test(ttype(p)) && !/return \(offense\)/i.test(ttype(p))
      || /\bkicks\b|\bpunts\b|extra point|field goal/i.test(String(p.text || ''));
    const firstDown = new Set();
    drives.forEach(d => {
      const real = (d.plays || []).filter(p => p.start && p.start.down && !isNonPlay(p) && !isST(p));
      real.forEach((p, i) => {
        const nx = real[i + 1];
        if (!nx || nx.start.down !== 1 || p.scoringPlay || p.isTurnover) return;
        if (/goal/i.test(p.start.downDistanceText || p.start.shortDownDistanceText || '')) return;  // goal to go: only a TD
        // from 1st down a new set needs the full distance gained (else it's e.g. a replayed down after a no-play)
        if (p.start.down === 1 && !(p.statYardage >= (p.start.distance || 10))) return;
        firstDown.add(p.id);
      });
    });
    const teams = [info.away.team, info.home.team];
    const playRow = (p) => {
      const wp = wpAfter[p.id], d = wp ? wp.now - wp.prev : 0;
      const swing = Math.abs(d) >= 0.01 ? `<span class="pl-wp" title="Change in ESPN's live win probability on this play">${tmL(d > 0 ? info.home.team : info.away.team)} +${Math.round(Math.abs(d) * 100)}%</span>` : '';
      const when = `${p.period ? periodName(p.period.number) : ''} ${esc(p.clock ? p.clock.displayValue : '')}`;
      // Not plays (timeouts, two-minute warning, end of quarter / game): thin muted divider rows.
      if (isNonPlay(p)) return `<li class="pl pl-np"><div class="pl-when">${when}</div><div class="pl-what"><div class="pl-txt">${esc(p.text)}</div></div><div></div></li>`;
      const dd = (p.start && (p.start.downDistanceText || p.start.shortDownDistanceText)) || '';
      const fd = firstDown.has(p.id), st = isST(p), t = ttype(p), txt = String(p.text || '');
      // Tint = the team with the ball; special-teams plays stay neutral. Event types are chips, not row colors.
      const off = st ? null : teamOf(p.start && p.start.team && p.start.team.id);
      const chips = [];
      if (p.scoringPlay) chips.push(/field goal/i.test(t + txt) ? ['FG', 'c-sc'] : /extra point/i.test(t + txt) ? ['XP', 'c-sc'] : /safety/i.test(t + txt) ? ['SAFETY', 'c-sc'] : ['TD', 'c-sc']);
      else if (st) chips.push([/kickoff|kicks/i.test(t + txt) ? 'KICKOFF' : /punt/i.test(t + txt) ? 'PUNT' : /field goal/i.test(t + txt) ? 'FG' : 'ST', 'c-st']);
      // ESPN doesn't flag lost fumbles on kickoffs / punts as turnovers: the kicking team recovering is one.
      const kicker = st && (txt.match(/(?:kicks|punts)\b.*?\bfrom ([A-Z]{2,3}) \d/) || [])[1];
      const recBy = (txt.match(/RECOVERED by ([A-Z]{2,3})-/) || [])[1];
      const stLost = st && /FUMBLES/.test(txt) && kicker && recBy && ourCode(recBy) === ourCode(kicker);
      if (p.isTurnover || stLost) chips.push([/intercept/i.test(t + txt) ? 'INT' : /fumble/i.test(t + txt) ? 'FUM' : 'TO', 'c-to']);
      if (/sack/i.test(t)) chips.push(['SACK', 'c-sk']);
      if (p.isPenalty) chips.push(['FLAG', 'c-pen']);
      if (fd) chips.push(['1ST', 'c-1st']);
      const CHIP_TIP = { TD: 'Touchdown', FG: 'Field goal', XP: 'Extra point', SAFETY: 'Safety', KICKOFF: 'Kickoff (special teams)',
                         PUNT: 'Punt (special teams)', ST: 'Special teams play', INT: 'Interception (turnover)', FUM: 'Fumble lost (turnover)',
                         TO: 'Turnover', SACK: 'Sack', FLAG: 'Penalty on the play', '1ST': 'Gained a first down' };
      const chipHtml = chips.map(([c, k]) => `<span class="pc-chip ${k}" title="${CHIP_TIP[c] || ''}">${c}</span>`).join('');
      const cls = `${p.scoringPlay ? ' pl-score' : ''}${p.isPenalty && !p.scoringPlay ? ' pl-pen' : ''}${st ? ' pl-st' : ''}`;
      return `<li class="pl${cls}"${off ? ` style="--pt:${esc(off.color)}"` : ''}><div class="pl-when">${when}</div>
        <div class="pl-what">${dd || chipHtml ? `<div class="pl-dd">${chipHtml}${esc(dd)}</div>` : ''}<div class="pl-txt">${linkNames(esc(p.text), teams)}</div></div>
        <div class="pl-side">${p.scoringPlay ? `<b class="pl-sc">${tmL(info.away.team)} ${p.awayScore}–${p.homeScore} ${tmL(info.home.team)}</b>` : ''}${swing}</div></li>`;
    };
    const order = o.sort !== 'old';  // newest first unless asked otherwise
    const swingOf = p => { const w = wpAfter[p.id]; return w ? Math.abs(w.now - w.prev) : 0; };
    let html = '';
    if (o.sort === 'impact') {
      // Biggest swings in ESPN's live win probability, one flat list (impact order doesn't fit inside drives).
      const pl = drives.flatMap(d => d.plays || []).filter(keep).filter(p => wpAfter[p.id]).sort((a, b) => swingOf(b) - swingOf(a)).slice(0, o.limit);
      html = pl.length ? `${o.note ? `<p class="gcs-note">The ${pl.length} plays that moved ESPN's win probability the most.</p>` : ''}<ol class="pls">${pl.map(playRow).join('')}</ol>`
        : '<p class="muted">No win-probability data for these plays yet.</p>';
    } else if (o.view === 'every') {
      let pl = drives.flatMap(d => d.plays || []).filter(keep);
      if (order) pl = pl.reverse();
      html = pl.length ? `<ol class="pls">${pl.map(playRow).join('')}</ol>` : '<p class="muted">No plays match.</p>';
    } else {
      let ds = drives.map(d => ({ d, plays: (d.plays || []).filter(keep) })).filter(x => x.plays.length);
      if (order) ds = ds.reverse().map(x => ({ d: x.d, plays: [...x.plays].reverse() }));
      html = ds.map(({ d, plays }) => {
        const tm = teamOf(d.team && d.team.id) || {};
        const res = driveResult(d, tm, info, d === sum.drives.current);
        return `<div class="dr"><div class="dr-h" style="--tc:${esc(tm.color || '#666')}"><span class="tm-open dr-tm" data-tm="${esc(tm.team || '')}">${tm.logo ? logo(tm.logo, '#111', 16, tm.team) : ''}<b>${esc(tm.team || '')} drive</b></span>
          <span class="dr-res ${res.cls}">${esc(res.text)}</span>
          <span class="muted">${esc(d.description || '')}</span></div><ol class="pls">${plays.map(playRow).join('')}</ol></div>`;
      }).join('') || '<p class="muted">No plays match.</p>';
    }
    return html;
  };
  // Pregame depth charts: both teams' charts for the game's week (data/depth/<season>/<TEAM>.json; playing time when the
  // team has played this season, else the listed chart), starters plus the next man up at each position.
  const preDepth = g => {
    const season = +g.id.slice(0, 4), week = +g.id.slice(5, 7), teams = [g.away.team, g.home.team];
    teams.forEach(t => {
      const k = dKey(season, t);
      if (DFILES[k] === undefined) {
        DFILES[k] = null;
        getJSON(`${siteRoot()}data/depth/${season}/${encodeURIComponent(t)}.json`)
          .then(x => { DFILES[k] = x; renderGame(); }).catch(() => { DFILES[k] = false; renderGame(); });
      }
    });
    if (DINJ === null && !preDepth.inj) {  // the current week's tags come from ESPN's live list (daily)
      preDepth.inj = 1;
      getJSON(`${siteRoot()}data/espn_injuries/latest.json`).then(x => { DINJ = {}; x.rows.forEach(r => { DINJ[String(r.espn_id)] = r; }); renderGame(); }).catch(() => {});
    }
    const team = t => {
      const f = DFILES[dKey(season, t)];
      if (!f) return `<div class="pd-team"><p class="muted">${f === false ? `No depth chart for ${esc(t)}.` : 'Loading depth chart&hellip;'}</p></div>`;
      const wks = Object.keys(f.weeks).map(Number).sort((a, b) => a - b), wk = wks.filter(x => x <= week).pop() || wks[0];
      const W = f.weeks[wk], live = wk === wks[wks.length - 1] && !(g.final);  // the latest chart of a game not played yet
      const chip = ([pi, pct, ftag], bold) => {
        const [name, pid, espn] = f.players[pi];
        const li = live && DINJ && espn ? DINJ[espn] : null, tag = live && DINJ ? (li ? ESPN_TAG[li.status] : null) : ftag;
        const nm = pid ? `<button type="button" class="bx-n dc-n" data-open-pid="${esc(pid)}">${esc(name)}</button>` : `<span class="dc-n">${esc(name)}</span>`;
        return `<span class="dc-p${bold ? ' first' : ''}">${nm}${pct != null ? `<span class="dc-pct">${pct}%</span>` : ''}${tag ? `<span class="dc-tag dt-${tag === 'Q' ? 'q' : tag === 'D' ? 'd' : 'out'}" title="${esc(TAG_NAME[tag] || tag)}">${esc(tag)}</span>` : ''}</span>`;
      };
      let rows;
      if (W.u) {  // playing time: [group, n starters, [[player, snap %, tag], ...]]
        rows = W.u.map(([grp, n, pl]) => [grp, pl.slice(0, n + 1).map((x, i) => chip(x, i < n))]);
      } else {  // listed chart: [abb, name, [[player, rank, tag], ...]]; first in each slot + the next one
        rows = [...(W.off || []), ...(W.def || [])].map(([abb, , pl]) => [abb, pl.slice(0, 2).map(([pi, , tag], i) => chip([pi, null, tag], i === 0))]);
      }
      const half = W.u ? ['QB', 'RB', 'WR', 'TE', 'OL'] : null;
      const block = rs => rs.map(([k, chips]) => `<div class="dc-row"><span class="dc-pos">${esc(k)}</span><span class="dc-pl">${chips.join('')}</span></div>`).join('');
      const off = half ? rows.filter(r => half.includes(r[0])) : rows.slice(0, (W.off || []).length);
      const def = half ? rows.filter(r => !half.includes(r[0])) : rows.slice((W.off || []).length);
      const src = W.u ? 'playing time, last 3 games' : (season >= 2025 ? "ESPN's listed chart" : 'listed chart');
      const pageHref = DATA && DATA.__rel ? `${siteRoot()}${DATA.__rel.replace(/\.json$/, '.html')}#team/${encodeURIComponent(t)}` : '';
      return `<div class="pd-team"><div class="bx-th tm-open" data-tm="${esc(t)}" style="--tc:${esc(g.colors[t])}">${logo(t === g.away.team ? g.away.logo_url : g.home.logo_url, t === g.away.team ? g.away.logo_bg : g.home.logo_bg, 20, t)}<b>${esc(t)}</b><span class="muted pd-src">${esc(src)}</span></div>
        <div class="pd-k">Offense</div>${block(off)}<div class="pd-k">Defense</div>${block(def)}
        ${pageHref ? `<a class="pd-more" href="${esc(pageHref)}">Full depth chart &rsaquo;</a>` : ''}</div>`;
    };
    return `<section class="gcs"><h3>Depth charts <span class="bt-unit">starters in bold</span></h3>${teams.map(team).join('')}
      <p class="gcs-note">From a team's second game on: each position's snap leaders over its last 3 games (share of snaps), leaving out players ruled out or on a reserve list; before that, the team's listed chart. Tags: that week's injury report or reserve list.</p></section>`;
  };
  // Kickoff in the visitor's own time zone everywhere on the gamecast (owner 2026-10-16: the header said CDT, the card
  // ET): ESPN's exact time when it has loaded, else the week page's Eastern string.
  const kickText = (g, long = true) => GP.info && GP.info.date
    ? new Date(GP.info.date).toLocaleString([], long ? { weekday: 'short', month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit', timeZoneName: 'short' }
      : { weekday: 'short', hour: 'numeric', minute: '2-digit', timeZoneName: 'short' })
    : (g && g.kickoff) || '';
  // ---- Pregame tab: everything the Matchups tile used to carry, from the week file (made before kickoff).
  const preTab = (g) => {
    if (!g) return '<section class="gcs"><p class="muted">NFL Edge has no pregame numbers for this game (no week page for it).</p></section>';
    const f = g.fc, tp = (DATA && DATA.tossup_pct) || 59, a = g.away, h = g.home;
    const lg = (s, n = 18) => logo(s.logo_url, s.logo_bg, n, s.team);
    const odds = `<section class="gcs"><h3>Win chances <span class="src us">NFL Edge, before kickoff</span></h3>
      <p class="gcs-note">${esc(kickText(g))}${g.neutral ? ' · neutral site' : ''}</p>
      <div class="wp${f.tossup ? ' toss' : ''}" style="${esc(g.bt_style)}">
        <div class="wp-src">${f.src === 'Vegas' ? 'Vegas odds' : 'Our model · no Vegas line yet'}</div>
        <div class="wp-head">${f.tossup ? '<span class="wp-call">Tossup</span><span class="wp-why">too close to call</span>'
          : `${tmL(f.fav, lg(f.fav === a.team ? a : h, 20))}<span class="wp-call">${tmL(f.fav, esc(f.nick))} ${f.pct}%</span><span class="wp-why">to win</span>`}</div>
        <div class="wp-bar" role="img" aria-label="${esc(a.team)} ${f.p_away}%, ${esc(h.team)} ${f.p_home}%"><span class="wp-a" style="width:${f.p_away}%"></span><span class="wp-h"></span>
          <i class="wp-zone" style="left:${100 - tp}%;width:${2 * tp - 100}%"></i></div>
        <div class="wp-ends"><span>${tmL(a.team)} ${f.p_away}%</span><span>${f.p_home}% ${tmL(h.team)}</span></div>
        ${g.vegas_line ? `<div class="wp-meta"><span>Vegas ${esc(g.vegas_line)}${g.vegas_total ? ` · O/U ${f1(g.vegas_total)}` : ''}</span>
          <span title="${esc(f.model_why)}">Our model: <b>${f.model_tossup ? 'tossup' : `${tmL(f.model_fav, esc(f.model_nick))} ${f.model_pct}%`}</b>${f.model_tossup ? ` (${tmL(f.model_fav, esc(f.model_nick))} ${f.model_pct}%)` : ''}</span></div>`
          : `<div class="wp-meta"><span>${esc(f.model_why)}</span></div>`}
      </div></section>`;
    const battles = `<section class="gcs"><div class="battles" style="${esc(g.bt_style)}">
      <h3>Who wins each battle <span class="bt-unit">EPA per 100 plays</span></h3>
      <div class="bt-teams"><span>${tmL(a.team, `${lg(a, 15)}<b>${esc(a.team)}</b>`)}${btChip(g.power_rk[0], `${a.team} power rank`)}</span><span>${btChip(g.power_rk[1], `${h.team} power rank`)}${tmL(h.team, `<b>${esc(h.team)}</b>${lg(h, 15)}`)}</span></div>
      ${g.battles.map(b => `<details class="battle grp"><summary><div class="bt-grp"><span class="bt-chev" aria-hidden="true"></span><span>${esc(b.head.left)}</span><span>${esc(b.head.right)}</span></div>${btRow(b.head, 'Total')}</summary>
        <div class="bt-units">${b.rows.map(x => btRow(x)).join('')}</div></details>`).join('')}
      <div class="battle extras">${g.extras.map(x => btRow(x)).join('')}</div>
      <div class="bt-plays">Projected plays: ${g.plays.map(p => `${tmL(p.team)} <b>${f0(p.n)}</b> (${f0(p.pass * 100)}% pass)`).join(' · ')}</div></div></section>`;
    const ratings = `<section class="gcs"><h3>Team ratings <span class="bt-unit">EPA per 100 plays vs average</span></h3><table class="bx gc-rt"><thead><tr><th></th><th class="num">Pass O</th><th class="num">Run O</th><th class="num">Pass D</th><th class="num">Run D</th><th class="num">ST</th></tr></thead>
      <tbody>${[a, h].map(s => `<tr><td><span class="tm-open bx-th-in" data-tm="${esc(s.team)}">${lg(s, 14)}<b>${esc(s.team)}</b></span></td><td class="num">${sgn(s.off_pass)}</td><td class="num">${sgn(s.off_rush)}</td><td class="num">${sgn(s.def_pass)}</td><td class="num">${sgn(s.def_rush)}</td><td class="num">${sgn(s.st)}</td></tr>`).join('')}</tbody></table></section>`;
    const players = Object.entries((DATA && DATA.players) || {}).filter(([, p]) => p.team === a.team || p.team === h.team).sort((x, y) => y[1].proj - x[1].proj);
    const plTable = s => {
      const rows = players.filter(([, p]) => p.team === s.team).map(([pid, p]) => { const sc = scaled(p);
        return `<tr><td class="bx-who"><button type="button" class="bx-n" data-open-pid="${esc(pid)}">${esc(p.name)}</button> <span class="posb posb-${esc(p.pos)}">${esc(p.pos)}</span>${injTag(p.status)}</td>
          <td class="num"><b>${f1(sc.proj)}</b></td><td class="num muted">${f0(sc.q[0])}–${f0(sc.q[4])}</td><td class="num">${muHtml(p, s === a ? h.team : a.team)}</td></tr>`; }).join('');
      return `<div class="bx-team" style="--tc:${esc(g.colors[s.team])}"><div class="bx-th tm-open" data-tm="${esc(s.team)}">${lg(s, 20)}<b>${esc(s.team)}</b></div>
        ${rows ? `<table class="bx"><thead><tr><th>Player</th><th class="num">Proj</th><th class="num">Range</th><th class="num">Matchup</th></tr></thead><tbody>${rows}</tbody></table>` : '<p class="muted">No fantasy-relevant players listed.</p>'}</div>`;
    };
    return `<div class="gc-grid"><div class="gc-col">${odds}${battles}${ratings}</div>
      <div class="gc-col"><section class="gcs"><h3>Fantasy projections <span class="bt-unit">your scoring</span></h3>${plTable(a)}${plTable(h)}</section>${preDepth(g)}</div></div>`;
  };
  // ---- Postgame player stats (owner 2026-10-14): ESPN's full box score, every category it keeps (passing through
  // punting, defense included), one team at a time, each player in the site's tile row; tapping opens our player page
  // when we have one (ESPN id -> gsis via data/espn_ids.json).
  const PST_NAME = { passing: 'Passing', rushing: 'Rushing', receiving: 'Receiving', fumbles: 'Fumbles', defensive: 'Defense',
                     interceptions: 'Interceptions', kickReturns: 'Kick returns', puntReturns: 'Punt returns', kicking: 'Kicking', punting: 'Punting' };
  let GSIS_OF = null;  // ESPN id -> gsis, built once from NFLE.ui.ids
  const playerStats = (sum, info, opt = {}) => {
    const P = sum && sum.boxscore && sum.boxscore.players;
    if (!P || !P.length) return opt.empty ? `<section class="gcs" id="${opt.id || 'gcPst'}"><h3>${esc(opt.title || 'Player stats')}</h3><p class="muted">${esc(opt.empty)}</p></section>` : '';
    // owner 2026-10-14: no projection comparisons here, just what happened. Passing, rushing and receiving stay separate
    // tables (a QB who runs shows in both); each of those rows ends with the player's whole-game fantasy points in the
    // viewer's scoring, so the same total repeats across his tables.
    const lines = boxLines(sum), map = byEspn(), w = weights();
    const FP_CATS = ['passing', 'rushing', 'receiving'];
    const fpOf = id => { const o = lines[id]; if (!o) return null; const pid = map[id], pp = pid && DATA && DATA.players[pid]; return pts(o.line, w, pp ? pp.pos : ''); };
    const U = NFLE.ui, teams = (DATA && DATA.teams) || {};
    if (!GSIS_OF && U && U.ids && Object.keys(U.ids).length) { GSIS_OF = {}; Object.entries(U.ids).forEach(([g, e]) => { GSIS_OF[e] = g; }); }
    const sides = [info.away, info.home];
    const pick = sides.some(x => x.team === GP.pst) ? GP.pst : info.away.team;
    const block = side => {
      const tp = P.find(x => ourCode(x.team.abbreviation) === side.team);
      if (!tp) return '';
      const style = teams[side.team] ? NFLE.fmt.rowStyle(teams, side.team) : `--tc:${side.color || '#666'};--tc2:${side.color || '#999'};--tfg:#ffffff`;
      const cats = (tp.statistics || []).filter(c => (c.athletes || []).length).map(c => {
        const withFp = FP_CATS.includes(c.name);
        const rows = c.athletes.map(a => {
          const id = String(a.athlete.id), pid = GSIS_OF && GSIS_OF[id];
          const dp = map[id] && DATA && DATA.players[map[id]];
          const sub = a.athlete.jersey ? `#${a.athlete.jersey}` : '';
          const cell = U ? U.player({ name: a.athlete.displayName, team: side.team, espn: id, pos: dp ? dp.pos : '', sub }, teams)
            : `<b>${esc(a.athlete.displayName)}</b>`;
          const fp = withFp ? fpOf(id) : null;
          return `<tr class="teamrow" style="${style}"${pid ? ` data-open-pid="${esc(pid)}"` : ''}><td class="pst-who">${cell}</td>${(a.stats || []).map(v => `<td class="num"><span class="sc">${esc(v)}</span></td>`).join('')}${withFp ? `<td class="num pst-fp">${fp == null ? '' : `<span class="sc fp">${f1(fp)}</span>`}</td>` : ''}</tr>`;
        }).join('');
        const tot = (c.totals || []).length ? `<tr class="pst-tot"><td>Team</td>${c.totals.map(v => `<td class="num"><span class="sc">${esc(v)}</span></td>`).join('')}${withFp ? '<td></td>' : ''}</tr>` : '';
        const head = (c.labels || []).map((l, i) => `<th class="num" title="${esc((c.descriptions || [])[i] || '')}"><span class="sc h">${esc(l)}</span></th>`).join('')
          + (withFp ? '<th class="num pst-fp" title="Fantasy points for the whole game, your scoring"><span class="sc h">FP</span></th>' : '');
        return `<div class="pst-cat"><div class="bx-h">${esc(PST_NAME[c.name] || c.text || c.name)}</div>
          <div class="lg-scroll"><table class="bx tiles pst-tbl"><thead><tr><th>Player</th>${head}</tr></thead><tbody>${rows}${tot}</tbody></table></div></div>`;
      }).join('');
      return `<div class="pst-team" data-pst="${esc(side.team)}"${side.team === pick ? '' : ' hidden'}>${cats || '<p class="muted">No player stats.</p>'}</div>`;
    };
    const seg = `<div class="seg pst-seg" role="tablist">${sides.map(x => `<button type="button" role="tab" data-pst="${esc(x.team)}" class="${x.team === pick ? 'on' : ''}">${logo(x.logo, '#111', 18, x.team)} ${esc(x.team)}</button>`).join('')}</div>`;
    return `<section class="gcs" id="${opt.id || 'gcPst'}"><h3>${esc(opt.title || 'Player stats')} <span class="src">ESPN</span></h3>${opt.note ? `<p class="gcs-note">${esc(opt.note)}</p>` : ''}${seg}${sides.map(block).join('')}</section>`;
  };
  // ---- Postgame tab: the recap once it's final.
  const postTab = (sum, info, g, ser) => {
    if (info.state !== 'post') return `<section class="gcs"><p class="muted">${info.state === 'pre' ? 'The recap appears once the game is over.' : 'The game is still going; the recap appears at the final whistle. Follow it on the Live tab.'}</p></section>`;
    const a = info.away, h = info.home, winner = a.score > h.score ? a.team : h.score > a.score ? h.team : null;
    const f = g && g.fc;
    const call = f ? `<div class="pg-call">${verdict(f, winner)}
      <span class="muted">${f.src === 'Vegas' ? `Vegas gave ${f.tossup ? `a tossup (${tmL(f.fav, esc(f.nick))} ${f.pct}%)` : `${tmL(f.fav, esc(f.nick))} ${f.pct}%`}` : 'No Vegas line'} · our model gave ${tmL(f.model_fav, esc(f.model_nick))} ${f.model_pct}%${f.model_tossup ? ' (tossup)' : ''}</span></div>` : '';
    const result = `<section class="gcs"><h3>Result</h3><div class="pg-res">
      <span class="tm-open${winner === a.team ? ' won' : ''}" data-tm="${esc(a.team)}">${logo(a.logo, '#111', 26, a.team)}<b>${esc(a.team)}</b> ${a.score}</span><span class="muted">${esc(info.detail || 'Final')}</span>
      <span class="tm-open${winner === h.team ? ' won' : ''}" data-tm="${esc(h.team)}">${h.score} <b>${esc(h.team)}</b>${logo(h.logo, '#111', 26, h.team)}</span></div>${call}
      ${GP.canReplay ? '<div class="rp"><button type="button" data-rp="on">Replay this game play by play</button></div>' : ''}</section>`;
    // Older games: ESPN has no win probability (and before ~2005 no plays), so those sections are left out, and
    // without our week file there are no projections: the box score takes that slot.
    const hasWp = ser.length >= 2;
    return `<div class="gc-grid"><div class="gc-col">${result}
        ${hasWp ? `<section class="gcs"><h3>Win probability <span class="src">ESPN</span></h3><p class="gcs-note">ESPN's in-game model over the whole game, not NFL Edge's forecast.</p>
          <div class="wp-wrap">${wpChart(ser, info, null)}<div class="wp-tip" hidden></div></div></section>
        <section class="gcs"><h3>Turning points</h3><p class="gcs-note">The plays that moved ESPN's win probability the most.</p>
          ${gameLog(sum, info, ser, null, { sort: 'impact', filter: 'all', q: '', limit: 6, note: false })}</section>` : ''}</div>
      <div class="gc-col"><section class="gcs"><h3>Team stats</h3>${sum ? teamStats(sum, info) || '<p class="muted">Not available.</p>' : ''}</section></div></div>
      ${playerStats(sum, info)}`;
  };
  // ESPN unreachable: still show the game from our own week file (Pregame works; final score if we have it).
  const infoFromG = g => {
    const side = (s, k) => ({ team: s.team, id: null, score: g.final ? g.final[k] : 0, logo: s.logo_url, color: g.colors[s.team], record: s.record || '' });
    const st = g.final ? 'post' : 'pre';
    return { id: null, state: st, realState: st, detail: g.final ? 'Final' : g.kickoff, short: '', period: 0, clock: '',
             away: side(g.away, 'away'), home: side(g.home, 'home'), sit: null, date: null, offline: true };
  };
  const GTABS = [['pre', 'Pregame'], ['live', 'Live'], ['post', 'Postgame']];
  // Live tab: one pane at a time, picked here (owner 2026-10-15: "if i pick stats i see stats"); box score first
  const GPANES = [['box', 'Box score'], ['plays', 'Plays'], ['wp', 'Win %'], ['team', 'Team stats']];
  const renderGame = () => {
    const root = document.getElementById('gc'), { sum, info, g } = GP;
    const rp = GP.replay;
    const ser = sum ? wpSeries(sum) : [];
    const upto = rp ? rp.t : null;
    // Opens on the tab that fits the game's state; the viewer's pick sticks after that.
    const tab = GP.tab || (rp ? 'live' : info.state === 'pre' ? 'pre' : info.state === 'in' ? 'live' : 'post');
    // header numbers: live/final from ESPN, or the replay position
    let hs = info.home.score, as = info.away.score, status = info.state === 'in' ? `${periodName(info.period)} ${info.clock}` : (info.detail || '');
    let sit = info.state === 'in' ? (info.sit || (sum && sitFromPlays(sum))) : null;
    if (rp && rp.play) {
      hs = rp.play.homeScore; as = rp.play.awayScore;
      status = `${rp.play.period ? periodName(rp.play.period.number) : ''} ${rp.play.clock ? rp.play.clock.displayValue : ''} · replay`;
      sit = Object.assign({}, rp.play.end || {}, { lastPlay: { text: rp.play.text } });
    }
    const sp = sit ? spot(sit, info) : null;
    const wpNow = (() => { const s = upto != null ? ser.filter(x => x.t <= upto) : ser; return s.length ? s[s.length - 1].home : null; })();
    if (info.state === 'pre' && !rp) {  // no 0-0 before kickoff, and a short kickoff time (ESPN's long one crowds phones)
      hs = ''; as = '';
      if (info.date) status = new Date(info.date).toLocaleString([], { weekday: 'short', hour: 'numeric', minute: '2-digit', timeZoneName: 'short' });
    }
    const side = (s, isHome) => `<div class="sb-t tm-open${isHome ? ' home' : ''}" data-tm="${esc(s.team)}" style="--tc:${esc(s.color)}">${logo(s.logo, '#111', 40, s.team)}
      <div class="sb-id"><div class="sb-n"><span class="sb-full">${esc((g && (isHome ? g.home.nick : g.away.nick)) || s.team)}</span><span class="sb-ab">${esc(s.team)}</span></div><div class="sb-r">${esc(s.record || '')}</div></div>
      <div class="sb-s">${isHome ? hs : as}</div>${sp && sp.offense.team === s.team ? '<i class="sb-ball" title="Has the ball"></i>' : ''}</div>`;
    const live = () => info.state === 'pre'
      ? `<section class="gcs"><p class="muted">Kicks off ${esc(kickText(g) || 'soon')}. The live view (field position, ESPN's win probability, every play, box score) starts at kickoff.</p></section>`
      : info.offline ? '<section class="gcs"><p class="muted">Live data from ESPN is unavailable right now. Try again in a minute.</p></section>'
      : `${rp && rp.play ? replayCard(rp.play, info, sum) : sp ? `<section class="sit"><div class="sit-dd"><b>${tmL(sp.offense.team)} ball</b>${sp.text ? ` · ${esc(sp.text)}` : ''}${sp.red ? ' · <span class="gl-red">red zone</span>' : ''}</div>
        ${fieldSvg(sp, info)}${sit.lastPlay && sit.lastPlay.text ? `<div class="sit-last"><span class="muted">Last play:</span> ${linkNames(esc(sit.lastPlay.text), [info.away.team, info.home.team])}</div>` : ''}</section>` : ''}
      ${GP.canReplay ? `<section class="rp">${rp ? `<button type="button" data-rp="first">&laquo;</button><button type="button" data-rp="prev">&lsaquo;</button>
        <button type="button" data-rp="play">${rp.timer ? 'Pause' : 'Play'}</button><button type="button" data-rp="next">&rsaquo;</button><button type="button" data-rp="last">&raquo;</button>
        <span class="seg rp-speed">${[['slow', 'Slow'], ['normal', 'Normal'], ['fast', 'Fast']].map(([k, l]) => `<button type="button" data-rps="${k}" class="${(GP.rpSpeed || 'normal') === k ? 'on' : ''}">${l}</button>`).join('')}</span>
        <input type="range" min="0" max="${rp.plays.length - 1}" value="${rp.i}" aria-label="Replay position"><span class="muted rp-pos">Play ${rp.i + 1} of ${rp.plays.length}</span>
        <button type="button" data-rp="off">Exit replay</button>` : '<button type="button" data-rp="on">Replay this game play by play</button>'}</section>` : ''}
      <div class="seg gc-panes" role="tablist">${GPANES.map(([k, l]) => `<button type="button" role="tab" data-pane="${k}" class="${GP.pane === k ? 'on' : ''}">${l}</button>`).join('')}</div>
      ${GP.pane === 'wp' ? `<section class="gcs" id="gcWp"><h3>Live win probability <span class="src">ESPN</span></h3>
            <p class="gcs-note">ESPN's in-game model, updated every play. Not NFL Edge's forecast: our pregame chances are on the Pregame tab.</p>
            ${wpNow != null ? `<div class="wp-now-t"><span style="color:${esc(info.away.color)}">${tmL(info.away.team)} ${pc(1 - wpNow)}</span><span style="color:${esc(info.home.color)}">${tmL(info.home.team)} ${pc(wpNow)}</span></div>` : ''}
            <div class="wp-wrap">${sum ? wpChart(ser, info, upto) : ''}<div class="wp-tip" hidden></div></div>
            <div class="wp-leg"><span><i class="wp-m wp-score"></i>score</span><span><i class="wp-m wp-to"></i>turnover</span><span class="muted">Above the line: ${tmL(info.home.team)} favored · below: ${tmL(info.away.team)}</span></div></section>`
      : GP.pane === 'plays' ? `<section class="gcs" id="gcLog"><h3>Game log</h3>
            <div class="lg-bar"><div class="seg">${[['drive', 'By drive'], ['every', 'Every play']].map(([k, l]) => `<button type="button" data-view="${k}" class="${GP.view === k ? 'on' : ''}">${l}</button>`).join('')}</div>
              <div class="seg">${[['all', 'All'], ['score', 'Scoring'], ['to', 'Turnovers'], ['pen', 'Penalties']].map(([k, l]) => `<button type="button" data-filter="${k}" class="${GP.filter === k ? 'on' : ''}">${l}</button>`).join('')}</div>
              <input type="search" id="lgQ" placeholder="Player or text" value="${esc(GP.q)}" aria-label="Filter plays">
              <div class="seg">${[['new', 'Newest'], ['old', 'Oldest'], ['impact', 'Biggest swings']].map(([k, l]) => `<button type="button" data-sort="${k}" class="${GP.sort === k ? 'on' : ''}">${l}</button>`).join('')}</div></div>
            <div id="lgBody">${!sum ? '<p class="muted">Plays appear once the game starts.</p>'
              : !allPlays(sum).length && info.state === 'post' ? '<p class="muted">ESPN has no play-by-play for this game (games before about 2005 only have box scores).</p>'
              : gameLog(sum, info, ser, upto)}</div></section>`
      : GP.pane === 'team' ? `<section class="gcs" id="gcTeam"><h3>Team stats</h3>${sum ? teamStats(sum, info) || '<p class="muted">Not available yet.</p>' : ''}</section>`
      : playerStats(sum, info, { id: 'gcBox', title: 'Box score', note: rp ? 'Box score shows the final totals during a replay.' : '', empty: 'The box score fills in once the game starts.' })}`;
    root.innerHTML = `
      <section class="sb">${side(info.away, false)}<div class="sb-mid">${info.state === 'in' && !rp ? '<span class="live-dot"></span>' : ''}<b>${esc(status)}</b></div>${side(info.home, true)}</section>
      <div class="seg gc-tabs" role="tablist">${GTABS.map(([k, l]) => `<button type="button" role="tab" data-gtab="${k}" class="${tab === k ? 'on' : ''}">${k === 'live' && info.state === 'in' ? '<span class="live-dot"></span>' : ''}${l}</button>`).join('')}</div>
      ${tab === 'pre' ? preTab(g) : tab === 'live' ? live() : postTab(sum, info, g, ser)}`;
    wireGame();
  };
  const wireGame = () => {
    const root = document.getElementById('gc');
    root.querySelectorAll('[data-gtab]').forEach(b => b.onclick = () => { GP.tab = b.dataset.gtab; renderGame(); });
    root.querySelectorAll('[data-pane]').forEach(b => b.onclick = () => { GP.pane = b.dataset.pane; renderGame(); });
    root.querySelectorAll('[data-view]').forEach(b => b.onclick = () => { GP.view = b.dataset.view; renderGame(); });
    root.querySelectorAll('[data-filter]').forEach(b => b.onclick = () => { GP.filter = b.dataset.filter; renderGame(); });
    root.querySelectorAll('[data-sort]').forEach(b => b.onclick = () => { GP.sort = b.dataset.sort; renderGame(); });
    const lq = root.querySelector('#lgQ');
    if (lq) lq.oninput = () => { GP.q = lq.value; document.getElementById('lgBody').innerHTML = gameLog(GP.sum, GP.info, wpSeries(GP.sum), GP.replay ? GP.replay.t : null); };
    root.querySelectorAll('.bx-n[data-pid]').forEach(b => b.onclick = () => openPlayer(b.dataset.pid));
    // win-probability hover: nearest play
    const svg = root.querySelector('svg.wp'), tip = root.querySelector('.wp-tip');
    if (svg && tip) {
      const ser = wpSeries(GP.sum).filter(s => !GP.replay || s.t <= GP.replay.t);
      const T = ser.some(s => s.t > 3600) ? 4200 : 3600;
      const hair = svg.querySelector('.wp-hair');
      const move = ev => {
        const r = svg.getBoundingClientRect(), x = ((ev.touches ? ev.touches[0].clientX : ev.clientX) - r.left) / r.width;
        const t = x * T; let best = ser[0];
        ser.forEach(s => { if (Math.abs(s.t - t) < Math.abs(best.t - t)) best = s; });
        if (!best) return;
        const vx = 6 + (640 - 12) * best.t / T;
        hair.setAttribute('x1', vx); hair.setAttribute('x2', vx); hair.style.display = '';
        tip.innerHTML = `<b>${best.play.period ? periodName(best.play.period.number) : ''} ${esc(best.play.clock ? best.play.clock.displayValue : '')}</b> · ${esc(GP.info.home.team)} ${pc(best.home)} / ${esc(GP.info.away.team)} ${pc(1 - best.home)}<br>${esc(best.play.text)}`;
        // keep the whole tooltip inside the chart: centered on the finger, clamped by its measured width (a % clamp
        // let the wide play text run off the screen edge near the ends)
        tip.hidden = false;
        const W = tip.parentElement.getBoundingClientRect().width, tw = tip.offsetWidth;
        tip.style.transform = 'none';
        tip.style.left = `${Math.max(0, Math.min(W - tw, x * W - tw / 2))}px`;
      };
      svg.addEventListener('mousemove', move); svg.addEventListener('touchstart', move, { passive: true });
      svg.addEventListener('touchmove', move, { passive: true });
      svg.addEventListener('mouseleave', () => { tip.hidden = true; hair.style.display = 'none'; });
    }
    // postgame player stats: one team at a time
    root.querySelectorAll('.pst-seg [data-pst]').forEach(b => b.onclick = () => {
      GP.pst = b.dataset.pst;
      root.querySelectorAll('.pst-team').forEach(t => { t.hidden = t.dataset.pst !== GP.pst; });
      root.querySelectorAll('.pst-seg [data-pst]').forEach(x => x.classList.toggle('on', x === b));
    });
    // replay controls
    root.querySelectorAll('[data-rp]').forEach(b => b.onclick = () => replayCmd(b.dataset.rp));
    root.querySelectorAll('.rp-card .rp-raw').forEach(e => e.onclick = () => e.classList.toggle('open'));  // clamped to 3 lines
    root.querySelectorAll('[data-rps]').forEach(b => b.onclick = () => {
      GP.rpSpeed = b.dataset.rps;
      if (GP.replay && GP.replay.timer) startReplayTimer(GP.replay);
      root.querySelectorAll('[data-rps]').forEach(x => x.classList.toggle('on', x === b));
    });
    const rng = root.querySelector('.rp input[type=range]');
    if (rng) rng.oninput = () => { replayTo(+rng.value); };
  };
  const replayTo = i => {
    const rp = GP.replay; if (!rp) return;
    rp.i = Math.max(0, Math.min(rp.plays.length - 1, i)); rp.play = rp.plays[rp.i]; rp.t = elapsed(rp.play);
    renderGame();
  };
  const replayCmd = cmd => {
    if (cmd === 'on') {
      const plays = allPlays(GP.sum).flatMap(d => d.plays || []);
      GP.replay = { plays, i: 0, play: plays[0], t: elapsed(plays[0]), timer: null };
      GP.sort = 'new'; GP.tab = 'live'; renderGame(); scrollTo(0, 0); return;
    }
    const rp = GP.replay; if (!rp) return;
    if (cmd === 'off') { clearInterval(rp.timer); GP.replay = null; renderGame(); return; }
    if (cmd === 'first') replayTo(0);
    if (cmd === 'last') replayTo(rp.plays.length - 1);
    if (cmd === 'prev') replayTo(rp.i - 1);
    if (cmd === 'next') replayTo(rp.i + 1);
    if (cmd === 'play') {
      if (rp.timer) { clearInterval(rp.timer); rp.timer = null; renderGame(); }
      else { startReplayTimer(rp); renderGame(); }
    }
  };
  // seconds per play: long enough to read the card (owner: "plays by itself too fast")
  const RP_MS = { slow: 4000, normal: 2500, fast: 1300 };
  const startReplayTimer = rp => {
    clearInterval(rp.timer);
    rp.timer = setInterval(() => { if (rp.i >= rp.plays.length - 1) { clearInterval(rp.timer); rp.timer = null; } replayTo(rp.i + 1); }, RP_MS[GP.rpSpeed || 'normal']);
  };
  const pollGame = async () => {
    clearTimeout(GP.timer);
    try {
      const evs = await weekEvents(GP.season, GP.week);
      const ev = evs.find(e => evKey(e) === gKey(GP.away, GP.home));
      if (!ev) throw new Error('game not found on ESPN');
      GP.info = evInfo(ev);
      // Our Matchups colors are already chosen to be distinct from each other (ESPN's can be near-identical).
      if (GP.g && GP.g.colors) { GP.info.away.color = GP.g.colors[GP.away] || GP.info.away.color; GP.info.home.color = GP.g.colors[GP.home] || GP.info.home.color; }
      else distinctColors(GP.info);  // a link without the week file: ESPN's colors, made distinct here
      // the box score links players to our pages through the id map (NFLE.ui.ready, fetched on first use)
      if (GP.info.realState !== 'pre') [GP.sum] = await Promise.all([getJSON(ESPN.sum + ev.id), NFLE.ui && NFLE.ui.ready]);
      // Player cards opened from this page show the live / final line too.
      if (GP.sum) Object.assign(LIVE.lines, boxLines(GP.sum));
      if (GP.g) LIVE.byGame[GP.g.id] = GP.info;
      GP.canReplay = GP.info.realState === 'post' && GP.sum && allPlays(GP.sum).length > 0;
      if (!GP.replay) renderGame();
    } catch (e) {
      // ESPN down: the game still shows from our own week file (Pregame, plus the final score if we have it).
      if (!GP.info && GP.g) { GP.info = infoFromG(GP.g); renderGame(); }
      else if (!GP.info) document.getElementById('gc').innerHTML = `<p class="gc-loading">Live data unavailable right now (${esc(e.message)}). Try again in a minute.</p>`;
    }
    if (GP.info && GP.info.realState === 'in' && !document.hidden) GP.timer = setTimeout(pollGame, 15000);
  };
  const initGame = async () => {
    const d = Q.get('d') || '', gid = Q.get('g') || '';
    const id = parseGid(gid);
    if (!id) { document.getElementById('gc').innerHTML = '<p class="gc-loading">No game selected.</p>'; return; }
    Object.assign(GP, id);
    if (d) {
      try { DATA = await getJSON(d, 12000, false); DATA.__rel = d; } catch (e) { DATA = null; }
      const back = document.getElementById('gcBack');
      if (back) back.href = d.replace(/\.json$/, '.html') + '#games';
    }
    GP.g = DATA ? DATA.games.find(x => x.id === gid) : null;
    document.title = `${id.away} @ ${id.home} · Gamecast · NFL Edge`;
    await pollGame();
    if (location.hash.startsWith('#player/')) openPlayer(location.hash.slice(8));
    document.addEventListener('visibilitychange', () => { if (!document.hidden && GP.info && GP.info.realState === 'in') pollGame(); });
    document.addEventListener('nfle-scoring', () => renderGame());
    if (Q.get('replay') === '1' && GP.canReplay) replayCmd('on');
  };

  // ------------------------------------------------------------------------------------------------------ init
  const initWeek = async () => {
    try { DATA = await getJSON(CFG.root + CFG.data, 12000, false); DATA.__rel = CFG.data; } catch (e) { DATA = null; return; }
    if (location.hash.startsWith('#player/')) openPlayer(location.hash.slice(8));
    else if (location.hash.startsWith('#team/')) openTeam(location.hash.slice(6));
    else if (location.hash.startsWith('#g-')) {  // old links to a matchup tile now open that game's gamecast
      const g = DATA.games.find(x => x.id === location.hash.slice(3));
      if (g) { location.replace(gameHref(g)); return; }
    }
    document.addEventListener('nfle-scoring', () => { paintRows(); if (cardPid) renderCard(cardPid); else if (cardTeam) renderTeam(cardTeam); });
    if (CFG.current || SIM) startLive();
  };
  // One click rule for the whole site: the innermost clickable thing wins - a player name or player row opens his
  // card, a team name / logo / tile header opens the team card (so a team inside a player row opens the team).
  document.addEventListener('click', e => {
    // A team inside a link or a <summary> (Matchups tile, rooting guide) opens the team and cancels the outer action
    // (owner 2026-10-16: every team name and logo opens its page); a player element closer to the tap still wins.
    const tm = e.target.closest('.tm-open[data-tm]');
    if (tm) {
      const outer = e.target.closest('a[href], summary'), pid = e.target.closest('[data-open-pid]');
      if (outer && outer.contains(tm) && !(pid && tm.contains(pid))) {
        e.preventDefault(); openTeam(tm.dataset.tm); return;
      }
    }
    if (e.target.closest('a[href], input, select, .pc-tabs, .seg')) return;
    for (let n = e.target; n && n !== document; n = n.parentElement) {
      if (n.dataset && n.dataset.openPid) { openPlayer(n.dataset.openPid); return; }
      if (n.classList && n.classList.contains('tm-open') && n.dataset.tm) { openTeam(n.dataset.tm); return; }
      if (n.matches && n.matches('tr.main[data-pid]')) { openPlayer(n.dataset.pid); return; }
    }
  });
  // paintTiles / gameHref: the Matchups tab (assets/matchups.js) draws the tiles, then paints live games at once
  window.NFLE = Object.assign(window.NFLE || {}, { openPlayer, closePlayer, openTeam, showPlayer, showTeam, weights,
    weekData: () => DATA, injTag, paintTiles: () => { if (DATA) paintTiles(); }, gameHref });  // shared with shell.js, table.js, area modules
  if (CFG.page === 'game') initGame(); else initWeek();
})();

// Tap-to-zoom (owner 2026-10-15): any [data-zoom] element opens its full-size image over the page; tap or Esc closes.
(() => {
  const open = url => {
    if (!url) return;
    const ov = document.createElement('div');
    ov.className = 'zoom-ov';
    ov.innerHTML = `<img src="${url.replace(/"/g, '&quot;')}" alt="">`;
    const close = () => { ov.remove(); document.removeEventListener('keydown', esc); };
    const esc = e => { if (e.key === 'Escape') close(); };
    ov.addEventListener('click', close);
    document.addEventListener('keydown', esc);
    document.body.appendChild(ov);
  };
  document.addEventListener('click', e => { const z = e.target.closest && e.target.closest('[data-zoom]'); if (z && z.dataset.zoom) { e.preventDefault(); e.stopPropagation(); open(z.dataset.zoom); } }, true);
  document.addEventListener('keydown', e => { if (e.key === 'Enter' && e.target.dataset && e.target.dataset.zoom) open(e.target.dataset.zoom); });
})();

// Detail sheet (owner 2026-10-16): a .pc-tap tile opens its <template> in a bottom sheet (phones) or a centered panel
// (desktop); Esc, the backdrop or the close button shut it, and a link or team / player inside it navigates and closes.
(() => {
  let last = null;
  const onKey = e => { if (e.key === 'Escape') close(); };
  const close = () => {
    const ov = document.querySelector('.sheet-ov');
    if (!ov) return;
    ov.remove(); document.removeEventListener('keydown', onKey);
    if (last && last.isConnected) last.focus();
  };
  const open = tile => {
    close(); last = tile;
    const ov = document.createElement('div');
    ov.className = 'sheet-ov';
    ov.innerHTML = '<div class="sheet" role="dialog" aria-modal="true"><div class="sheet-h"><i class="sheet-grab" aria-hidden="true"></i><b></b><button type="button" class="sheet-x" aria-label="Close">&times;</button></div><div class="sheet-b"></div></div>';
    ov.querySelector('.sheet-h b').textContent = tile.dataset.sheet;
    ov.querySelector('.sheet').setAttribute('aria-label', tile.dataset.sheet);
    ov.querySelector('.sheet-b').appendChild(tile.querySelector('template').content.cloneNode(true));
    document.dispatchEvent(new CustomEvent('nfle-sheet', { detail: ov.querySelector('.sheet-b') }));
    ov.addEventListener('click', e => {
      if (e.target === ov || e.target.closest('.sheet-x')) { close(); return; }
      if (e.target.closest('a[href], .tm-open, [data-open-pid]')) setTimeout(close);  // the page's click rule runs first
    });
    document.addEventListener('keydown', onKey);
    document.body.appendChild(ov);
    ov.querySelector('.sheet-x').focus();
    if (matchMedia('(max-width: 699px)').matches) drag(ov, ov.querySelector('.sheet'));
  };
  // Phones (owner 2026-10-16): the sheet follows the finger. It opens at up to SNAP of the screen; dragging up grows
  // it to FULL; dragging down shrinks it back from full, or slides it away from its opening size (far or fast
  // enough), else it springs back. Content scrolls as usual: a downward drag only moves the sheet once its content
  // is at the top, and from the grab bar / title row always.
  const SNAP = 0.62, FULL = 0.92;
  const drag = (ov, sh) => {
    const vh = () => innerHeight, cap = () => Math.min(sh.scrollHeight, FULL * vh());
    let full = false;
    const setH = (h, anim) => { sh.classList.toggle('sheet-anim', !!anim); sh.style.maxHeight = `${Math.round(h)}px`; };
    setH(Math.min(sh.scrollHeight, SNAP * vh()));
    let y0 = 0, t0 = 0, h0 = 0, mode = null, lastY = 0, lastT = 0, v = 0;
    sh.addEventListener('touchstart', e => {
      if (e.touches.length !== 1) return;
      y0 = lastY = e.touches[0].clientY; t0 = lastT = e.timeStamp; h0 = sh.offsetHeight; v = 0;
      mode = e.target.closest('.sheet-h') ? 'drag' : null;  // body touches decide on the first move
    }, { passive: true });
    sh.addEventListener('touchmove', e => {
      const y = e.touches[0].clientY, dy = y - y0;
      if (e.timeStamp > lastT) { v = (y - lastY) / (e.timeStamp - lastT); lastY = y; lastT = e.timeStamp; }
      if (mode === null && Math.abs(dy) > 4) {
        mode = (dy > 0 && sh.scrollTop <= 0) || (dy < 0 && !full && sh.offsetHeight < cap() - 1) ? 'drag' : 'scroll';
      }
      if (mode !== 'drag') return;
      e.preventDefault();
      if (dy < 0) { sh.style.transform = ''; setH(Math.min(cap(), h0 - dy)); }  // up: grow
      else { setH(h0); sh.style.transform = `translateY(${dy}px)`; }  // down: slide, the height kept
    }, { passive: false });
    sh.addEventListener('touchend', () => {
      if (mode !== 'drag') { mode = null; return; }
      mode = null;
      const dy = lastY - y0, snapH = Math.min(sh.scrollHeight, SNAP * vh());
      sh.classList.add('sheet-anim');
      if (dy < 0) {  // grew: settle full, or back
        full = dy < -50 || v < -0.4;
        setH(full ? cap() : h0, true);
        return;
      }
      const far = dy > 0.3 * h0 || v > 0.6;
      sh.style.transform = '';
      if (full && far && h0 - dy > snapH * 0.6) { full = false; setH(snapH, true); return; }  // full -> opening size
      if (far) {  // away
        sh.style.transform = `translateY(${h0 + 40}px)`;
        ov.classList.add('sheet-out');
        setTimeout(close, 200);
        return;
      }
      setH(h0, true);  // not far enough: spring back
    });
  };
  document.addEventListener('click', e => {
    const t = e.target.closest && e.target.closest('.pc-tap[data-sheet]');
    if (t && !e.target.closest('a[href], .tm-open, [data-open-pid]')) open(t);
  });
  document.addEventListener('keydown', e => {
    if ((e.key === 'Enter' || e.key === ' ') && e.target.matches && e.target.matches('.pc-tap[data-sheet]')) { e.preventDefault(); open(e.target); }
    else if ((e.key === 'Enter' || e.key === ' ') && e.target.matches && e.target.matches('.pc-tap[data-goto]')) { e.preventDefault(); e.target.click(); }
  });
})();
