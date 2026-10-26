// NFL Edge app shell: navigation (parent tabs + sub-tab chips) and hash routing.
// Routes: #players/rankings, #teams/power, #games ... Old one-level hashes (#players, #games, #power, #roles,
// #model) map onto the new routes; #player/<id>, #team/<abbr> and #g-<game> stay with gamecast.js (cards).
// Every tab renders in the browser (Phase 6, 2026-10-14): the page is a static shell (nfledge/pages/week.html) plus
// the week's JSON; sections not in the shell get a placeholder section here. Loaded on every week page (current, lookahead, archived) from assets/, so nav changes
// reach archived weeks without a rebuild.
// NFLE.load(path): lazy JSON loader with an in-memory cache, paths relative to the site root (the folder holding
// assets/), so it works from index.html and from archived <season>/week-NN.html pages alike.
// iOS only applies :active (ui.css: the pressed look on rows, tiles and buttons) when the page listens for touches.
document.addEventListener('touchstart', () => {}, { passive: true });
(() => {
  const NFLE = window.NFLE = window.NFLE || {};
  const root = new URL('..', document.currentScript ? document.currentScript.src : location.href);
  const cache = new Map();
  NFLE.root = root.href;
  NFLE.load = path => {
    if (!cache.has(path)) {
      cache.set(path, fetch(new URL(path, root), { cache: 'no-cache' })
        .then(r => r.ok ? r.json() : Promise.reject(new Error(`${r.status} ${path}`)))
        .catch(e => { cache.delete(path); throw e; }));
    }
    return cache.get(path);
  };
  // The page's week data (loaded by gamecast.js): resolves once it is in, or null after 15 s (missing / failed).
  NFLE.week = () => new Promise(ok => {
    const t0 = Date.now();
    const f = () => { const d = NFLE.weekData && NFLE.weekData(); if (d || Date.now() - t0 > 15000) ok(d || null); else setTimeout(f, 100); };
    f();
  });
  // Shared cell helpers for the client-rendered tabs (same markup the old server template drew).
  const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  NFLE.esc = NFLE.esc || esc;
  const f1 = v => v == null || isNaN(v) ? '' : (Math.round(v * 10) / 10).toFixed(1);
  // ESPN's resizer returns an empty image above ~600 px for some sources (the 4096 px dark Raiders logo): cap it
  const px = size => Math.min(600, Math.max(24, size * 3));
  const logoSrc = (url, size) => !url ? '' : !/a\.espncdn\.com\/i\/teamlogos\//.test(url) ? url
    : `https://a.espncdn.com/combiner/i?img=${encodeURIComponent(new URL(url).pathname)}&w=${px(size)}&h=${px(size)}`;
  // relocated clubs since 1999 (the site's history): today's code -> the old one, used before the move's season
  const ERA = { LV: { until: 2020, code: 'OAK' }, LAC: { until: 2017, code: 'SD' }, LA: { until: 2016, code: 'STL' } };
  // the old codes as teams-map entries: today's club with the era's name, ESPN's logo of the time and its colors
  const OLD = {
    OAK: { of: 'LV', name: 'Oakland Raiders' },
    SD: { of: 'LAC', name: 'San Diego Chargers', color: '#0C2340', color2: '#FFC20E', logo_bg: '#0C2340' },
    STL: { of: 'LA', name: 'St. Louis Rams', color: '#002244', color2: '#B3995D', logo_bg: '#002244' },
  };
  const oldTeam = (teams, t) => { const o = OLD[t]; if (!o) return null; const cur = (teams || {})[o.of] || {};  // logo + colors even before the teams map loads
    const { of, ...rest } = o;
    return { ...cur, ...rest, logo: `https://a.espncdn.com/i/teamlogos/nfl/500/${t.toLowerCase()}.png` }; };
  NFLE.fmt = {
    signed1: v => `${v >= 0 ? '+' : '-'}${Math.abs(v).toFixed(1)}`,  // a change in points: +0.9 / -0.7
    // Availability is shown one way everywhere (owner 2026-10-17): his chance to PLAY, "62%"; never the chance to sit
    toPlay: inactive => { const p = 1 - (inactive || 0); return p > 0.995 ? '&gt;99%' : p < 0.005 ? '&lt;1%' : `${Math.round(p * 100)}%`; },
    // kickoff (ms) of a team's game in a week's games: gameday + gametime are Eastern (EDT mid-March to early November)
    kickoff: (games, t) => { const k = NFLE.clock && NFLE.clock.kick(t); if (k != null) return k;  // the week clock first
      const g = (games || []).find(x => x.away.team === t || x.home.team === t);
      if (!g || !g.gameday || !g.gametime) return null;
      // Eastern offset from the browser's time-zone data (a hand-made EDT rule had Nov 1 2026 as EDT: kickoffs an hour early)
      const guess = Date.parse(`${g.gameday}T${g.gametime}:00-05:00`);
      const tz = new Intl.DateTimeFormat('en-US', { timeZone: 'America/New_York', timeZoneName: 'shortOffset' }).formatToParts(new Date(guess)).find(x => x.type === 'timeZoneName');
      const off = tz && /GMT([+-]\d+)/.exec(tz.value);
      return Date.parse(`${g.gameday}T${g.gametime}:00${off ? `${+off[1] < 0 ? '-' : '+'}${String(Math.abs(+off[1])).padStart(2, '0')}:00` : '-05:00'}`); },
    f1, logoSrc,
    sgn: v => v == null || isNaN(v) ? '' : Math.abs(v) < 0.05 ? '0.0' : `${v > 0 ? '+' : ''}${f1(v)}`,
    pct: v => v == null || isNaN(v) ? '' : `${Math.round(v * 100)}%`,
    ord: n => !n ? '' : `${n}${n % 100 >= 10 && n % 100 <= 20 ? 'th' : ({ 1: 'st', 2: 'nd', 3: 'rd' }[n % 10] || 'th')}`,
    rkc: n => n <= 8 ? 'rk1' : n <= 16 ? 'rk2' : n <= 24 ? 'rk3' : 'rk4',  // league-rank badge color (top 8 green ... bottom 8 red)
    posb: p => p ? `<span class="posb posb-${esc(String(p).replace(/[^A-Za-z]/g, ''))}">${esc(p)}</span>` : '',  // every position has a color (ui.css)
    short: n => { const i = String(n).indexOf(' '); return i < 0 ? String(n) : String(n).slice(i + 1); },  // 'Josh Allen' -> 'Allen'
    // [first, last] for two-line names (owner 2026-10-17): 'Amon-Ra St. Brown' -> ['Amon-Ra', 'St. Brown'],
    // 'Marvin Harrison Jr.' -> ['Marvin', 'Harrison Jr.']; one word -> ['', word]
    split: n => { const s = String(n || '').trim(), i = s.indexOf(' '); return i < 0 ? ['', s] : [s.slice(0, i), s.slice(i + 1)]; },
    // Relocated franchises (owner 2026-10-21: "LT never played against LV, they were OAK then right?"): the data keeps
    // today's codes everywhere (links, a franchise's seasons together); a past season shows the club as it was:
    // era('LV', 2008) -> 'OAK'. The old codes have their own logo and colors (teamOf) and open today's team page (ui.tm).
    era: (t, season) => { const e = ERA[t]; return e && season && +season < e.until ? e.code : t; },
    franchise: t => (OLD[t] ? OLD[t].of : t),
    teamOf: (teams, t) => (teams || {})[t] || oldTeam(teams, t) || {},
    // One rule for every team picker (owner 2026-10-26): the nickname, sorted by the name shown (sorting by code read as
    // random: Cardinals, Falcons, Ravens...); two clubs with one nickname (LV and OAK, Raiders) add their code.
    // teamOpts -> [[code, label]]; teamOptHtml -> the <option>s, cur selected. Tables and tiles keep the code.
    teamOpts: (teams, codes) => {
      const rows = [...new Set(codes.filter(Boolean))].map(t => [t, NFLE.fmt.teamOf(teams, t).nick || t]), n = {};
      rows.forEach(r => { n[r[1]] = (n[r[1]] || 0) + 1; });
      return rows.map(([t, l]) => [t, n[l] > 1 ? `${l} (${t})` : l]).sort((a, b) => a[1].localeCompare(b[1]));
    },
    teamOptHtml: (teams, codes, cur) => NFLE.fmt.teamOpts(teams, codes)
      .map(([t, l]) => `<option value="${esc(t)}"${t === cur ? ' selected' : ''}>${esc(l)}</option>`).join(''),
    // team logo on its picked background, and a row's team trim (--tc / --tc2), from the week data's teams map
    logo: (teams, t, size = 18) => { const i = NFLE.fmt.teamOf(teams, t); return i.logo ? `<span class="logo" style="background:${esc(i.logo_bg || '#333')}"><img src="${esc(logoSrc(i.logo, size))}" alt="${esc(t)}" width="${size}" height="${size}" loading="lazy"></span>` : ''; },
    rowStyle: (teams, t) => { const i = NFLE.fmt.teamOf(teams, t); return `--tc:${i.color || '#666'};--tc2:${i.color2 || '#999'};--tfg:#ffffff`; },
    // a player photo circle in his team's colors: primary fill, secondary ring (owner 2026-10-16)
    picStyle: (teams, t) => { const i = NFLE.fmt.teamOf(teams, t); return i.color ? ` style="--pc1:${i.color};--pc2:${i.color2 || i.color}"` : ''; },
  };
  // One look everywhere (owner 2026-10-14): every list of players or teams is a row of team-colored tiles (table cls
  // 'tiles', row class 'teamrow', row style from tileStyle) with the same name cell, and every matchup is the Games
  // tab's tile. Teams map = the week data's (NFLE.week() -> D.teams: logo, logo_bg, color, color2, nick).
  const F = NFLE.fmt;
  F.ERA = ERA;
  NFLE.ui = {
    headshot: espn => espn ? `https://a.espncdn.com/i/headshots/nfl/players/full/${encodeURIComponent(espn)}.png` : '',
    ids: {},  // gsis -> ESPN id (data/espn_ids.json, tools/stats_build.py): a headshot for any list with a player id
    tileStyle: (teams, t) => `style="${F.rowStyle(teams, t)}"`,
    // A team name or logo that opens the team page (owner 2026-10-16: every one on the site, except the small logo on
    // a player's photo). html: what to show (default: the abbreviation).
    // AFC / NFC with the conference logo (owner 2026-10-18: "the red and blue ones"; ESPN's marks, assets/conf/); a
    // division name ("AFC East") gets the logo before it; anything else passes through
    conf: (label, size = 16) => { const m = /^(AFC|NFC)\b/.exec(String(label || ''));
      return m ? `<span class="conf-n"><img class="conf-lg" src="${esc(NFLE.root || '')}assets/conf/${m[1]}.png" alt="" height="${size}" style="height:${size}px">${esc(label)}</span>` : esc(label); },
    tm: (t, html, cls = '') => t ? `<span class="tm-open${cls ? ` ${cls}` : ''}" data-tm="${esc(F.franchise(t))}">${html == null ? esc(t) : html}</span>` : (html || ''),
    // p: { name, team, pos, grp (badge color group), photo | espn | pid, sub (default: team, linked) | subHtml, badges }
    player: (p, teams) => {
      const photo = p.photo || NFLE.ui.headshot(p.espn || (p.pid && NFLE.ui.ids[p.pid]));
      const pic = photo
        ? `<span class="pic"${F.picStyle(teams, p.team)}><span class="pic-img"><img src="${esc(photo)}" alt="" width="34" height="34" loading="lazy" onerror="this.closest('.pic').classList.add('nopic')"></span><span class="pic-tm">${F.logo(teams, p.team, 11)}</span></span>`
        // no photo (a team defense, a player without a headshot): the team logo in the headshot's own frame, same size
        // as a photo in every list (owner 2026-10-18: D/ST logos were smaller than the headshots beside them)
        : `<span class="pic nopic"${F.picStyle(teams, p.team)}><span class="pic-img"></span><span class="pic-tm">${F.logo(teams, p.team, 34)}</span></span>`;
      const pos = p.pos ? `<span class="posb posb-${esc(p.grp || p.pos)}">${esc(p.pos)}</span> ` : '';
      const sub = p.subHtml != null ? p.subHtml : p.sub != null ? esc(p.sub) : NFLE.ui.tm(p.team);
      // two lines (owner 2026-10-17): first name with the small details (position, team) on top, last name below,
      // badges to the right; narrower than "full name / details", and each line truncates when the table scrolls
      const [first, last] = F.split(p.name);
      return `<div class="who">${pic}<div class="nmw nm2w"><span class="nm2"><span class="l1">${first ? `<span class="fnm">${esc(first)}</span> ` : ''}${pos}<span class="sub">${sub}</span></span><b class="nm l2">${esc(last)}</b></span>${p.badges ? `<span class="nm-b">${p.badges}</span>` : ''}</div></div>`;
    },
    // a team: logo, nickname, sub line (default "KC")
    team: (t, teams, sub, extra = '') => {
      const i = F.teamOf(teams, t);
      return `<div class="who">${F.logo(teams, t, 26)}<div><b>${esc(i.nick || t)}</b>${extra}<span class="sub">${sub == null ? esc(t) : sub}</span></div></div>`;
    },
    // the Games tab's matchup tile: logos outside, team colors blending, win chance (score once it starts); live
    // games are repainted by gamecast.js (NFLE.paintTiles finds tiles by data-gid wherever they are)
    matchTile: (g, href) => {
      // the team's wordmark (owner 2026-10-17, as on All teams: tools/wordmarks_build.py), the typed nickname if it fails
      // the line in words (owner 2026-10-17): "JAX -2.5" -> "JAX by 2.5", "PK" -> "pick'em"
      const vegas = l => { const m = /^([A-Z]{2,3}) -(\d+(?:\.\d)?)$/.exec(l || '');
        return m ? `<b>${esc(m[1])} by ${+m[2]}</b>` : l === 'PK' ? "<b>pick'em</b>" : `<b>${esc(l)}</b>`; };
      // the team name in one scoreboard font (owner 2026-10-18, Barlow Condensed ExtraBold italic, self-hosted, OFL): the
      // official wordmarks are each team's own drawn lettering, so weight, spacing and height never matched; the images
      // stay on All teams (teamgrid.js), the per-mark sizing is in git history (b562159)
      const wordmark = s => `<span class="mt-tn">${esc(s.nick)}</span>`;
      const f = g.fc || {}, fin = g.final;
      const sides = [[g.away, fin && fin.away, fin && fin.home, f.p_away], [g.home, fin && fin.home, fin && fin.away, f.p_home]];
      // (the playoff-stakes line, matchups.js, likewise)
      // the whole tile opens the gamecast (owner 2026-10-18: "tapping anywhere on a matchup tile should bring to the
      // gamecast"): team names, logos and codes in it are plain text, not team links
      const T = (t, html) => html == null ? esc(t) : html;
      const verdict = !fin ? '' : !fin.winner ? '<span class="gf-pick toss">Tie</span>'
        : f.tossup ? `<span class="gf-pick toss">Tossup &middot; ${T(fin.winner)} won</span>`
          : fin.fav_won ? `<span class="gf-pick ok">Favorite won &middot; ${f.pct}%</span>`
            : `<span class="gf-pick miss">Upset &middot; a ${100 - f.pct}% chance</span>`;
      const main = sides.map(([s, sc, os, pct], i) => {
        const side = i ? 'home' : 'away';
        const cls = `${fin && sc < os ? ' lost' : ''}${fin && sc > os ? ' won' : ''}${!fin && !f.tossup && pct < 50 ? ' dog' : ''}`;
        return `${s.logo_url ? `<img class="mt-lg ${side}" src="${esc(F.logoSrc(s.logo_url, 112))}" alt="" loading="lazy">` : ''}
          <div class="mt-side ${side}${cls}"><span class="mt-num">${fin ? esc(sc) : `${esc(pct)}<small>%</small>`}</span>
            <span class="mt-nm">${T(s.team, `<b>${wordmark(s)}</b>`)} <small>${NFLE.recSpan(s.team, s.record)}</small></span></div>
          ${i ? '' : `<span class="mt-at">${g.neutral ? 'vs' : '@'}${f.tossup && !fin ? '<small>Tossup</small>' : ''}</span>`}`;
      }).join('');
      // when (owner 2026-10-17): kickoff / Final / the live clock at the top middle; the footer keeps the rest
      const when = fin ? `<span class="mt-fin">${fin.ot ? 'Final/OT' : 'Final'}</span>` : `${esc(g.kickoff)}${g.neutral ? ` &middot; ${esc(g.site || 'neutral')}` : ''}`;
      const st = fin ? verdict
        // the Vegas line when there is one (owner 2026-10-17: then no "ours", the big win chances above are ours); before
        // a line is posted, our pick in its place
        : g.vegas_line ? `<span class="mt-odds">Vegas: ${vegas(g.vegas_line)}</span>`
          : f.model_fav || f.model_tossup ? `<span class="mt-odds" title="${esc(f.model_why || '')}">No Vegas line yet &middot; ours ${f.model_tossup ? 'tossup' : `<b>${T(f.model_fav)} ${esc(f.model_pct)}%</b>`}</span>` : '';
      return `<a class="mt ${fin ? 'is-final' : 'is-pre'}${f.tossup && !fin ? ' toss' : ''}" data-gid="${esc(g.id)}" href="${esc(href || (NFLE.gameHref ? NFLE.gameHref(g) : '#'))}" style="${esc(g.bt_style || '')}">
        <div class="mt-main"><div class="mt-when">${when}</div>${main}</div><div class="mt-st">${st}</div></a>`;
    },
  };
  // A team's record as of now (owner 2026-10-18: "records aren't updating once their game is final"): the week build's
  // record until the live scoreboard (gamecast.js, NFLE.live) has the team, then ESPN's, which counts a game the moment
  // it ends (before that it is the record going in, so it is never behind the build). Anything showing a record carries
  // data-rec="<team>" and is refreshed on every live update.
  NFLE.rec = (team, fallback = '') => {
    const by = NFLE.live && NFLE.live.byGame;
    if (by) for (const st of Object.values(by)) for (const k of ['away', 'home']) if (st[k] && st[k].team === team && st[k].record) return st[k].record;
    return fallback;
  };
  NFLE.recSpan = (team, fallback) => `<span data-rec="${NFLE.esc ? NFLE.esc(team) : team}">${NFLE.esc ? NFLE.esc(NFLE.rec(team, fallback || '')) : NFLE.rec(team, fallback || '')}</span>`;
  document.addEventListener('nfle-live', () => document.querySelectorAll('[data-rec]').forEach(e => {
    const r = NFLE.rec(e.dataset.rec, e.textContent); if (r && r !== e.textContent) e.textContent = r; }));
  // lists that show players by id wait for this (with NFLE.week()) before drawing, so their rows come up with faces.
  // Fetched on first use, not on every page load: 77 KB the landing Rankings page doesn't need (its players carry
  // their ESPN ids), and it competed with index.json for the first paint (Lighthouse 2026-10-16).
  let idsP = null;
  Object.defineProperty(NFLE.ui, 'ready', { get: () => idsP || (idsP = NFLE.load('data/espn_ids.json').then(m => { NFLE.ui.ids = m || {}; }).catch(() => {})) });
})();
// Tap tips (owner 2026-10-17: "tooltips everywhere"): on a touch screen (no hover), tapping anything with a title shows
// it in a small bubble; tapping elsewhere, scrolling or tapping it again closes it. Things that already do something
// on a tap keep it: names (open a card), links, buttons, tiles, column headers, form fields.
(() => {
  const TOUCH = matchMedia('(hover: none)');
  const ACTS = '.who, .tm-open, [data-open-pid]:not(tr), a[href], button, summary, th, input, select, label, .seg, [role="button"], [data-sheet], [data-zoom], [data-goto]';
  let pop = null, at = null;
  const hide = () => { if (pop) pop.remove(); pop = at = null; };
  document.addEventListener('click', e => {
    if (!TOUCH.matches) return;
    // the tapped thing's tip, else its table cell's when the cell has just one (a tap needn't land on the number itself)
    const cell = e.target.closest('td'), inCell = cell ? cell.querySelectorAll('[title]') : [];
    const el = e.target.closest('[title]') || (inCell.length === 1 ? inCell[0] : null);
    const tt = el && el.getAttribute('title');  // SVG elements have no .title property
    if (!el || !tt || e.target.closest(ACTS)) { hide(); return; }
    if (at === el) { hide(); return; }
    hide();
    at = el; pop = document.createElement('div'); pop.className = 'tip-pop'; pop.textContent = tt;
    document.body.appendChild(pop);
    const r = el.getBoundingClientRect(), w = pop.offsetWidth, h = pop.offsetHeight;
    const x = Math.max(8, Math.min(innerWidth - w - 8, r.left + r.width / 2 - w / 2));
    const y = r.top - h - 8 >= 8 ? r.top - h - 8 : r.bottom + 8;
    pop.style.left = `${x}px`; pop.style.top = `${y}px`;
  });
  addEventListener('scroll', hide, { passive: true, capture: true });
  addEventListener('resize', hide);
})();
// The week clock in the browser (nfledge/week_clock.py writes D.clock into every week page): kickoffs, practice-report
// deadlines, rollover and the waiver run as ISO times, applied to the current time here, so the page knows where the
// week stands between builds (owner 2026-10-18: "make every day of the week a day where we expect things").
(() => {
  const NFLE = window.NFLE;
  let C = null;
  NFLE.week && NFLE.week().then(D => { C = D && D.clock; });
  const ms = iso => iso ? Date.parse(iso) : null;
  const team = t => C && C.teams && C.teams[t];
  // today's date in Eastern time (not UTC: after 8 pm ET the UTC date is already tomorrow)
  const etDate = (d = new Date()) => new Intl.DateTimeFormat('en-CA', { timeZone: 'America/New_York', year: 'numeric', month: '2-digit', day: '2-digit' }).format(d);
  NFLE.clock = {
    ready: () => !!C,
    data: () => C,
    today: () => etDate(),
    etDate,
    kick: t => { const x = team(t); return x ? ms(x.kick) : null; },
    // 'final' | 'live' | 'upcoming' | null (bye / unknown); live games ESPN marks final are 'final' via finals()
    state: (t, finals) => { const x = team(t); if (!x) return null;
      if (x.final || (finals && finals.has(t))) return 'final';
      return Date.now() >= ms(x.kick) ? 'live' : 'upcoming'; },
    started: t => { const x = team(t); return !!x && (x.final || Date.now() >= ms(x.kick)); },
    // this week's report days for a team: [{date, due, weekday, in}] (in = its 4 pm ET deadline has passed)
    reports: t => { const x = team(t); if (!x) return [];
      return x.reports.map(r => ({ date: r.date, due: ms(r.due), in: Date.now() >= ms(r.due),
        weekday: new Date(r.date + 'T12:00:00').toLocaleDateString([], { weekday: 'short' }) })); },
    reportsIn: t => NFLE.clock.reports(t).filter(r => r.in).length,
    finalReportIn: t => { const r = NFLE.clock.reports(t); return r.length > 0 && r[r.length - 1].in; },
    rollover: () => C ? ms(C.rollover) : null,
    waivers: () => C ? ms(C.waivers) : null,
  };
})();
// A page left open keeps showing what it loaded, and phones keep tabs alive for days. When you come back to the
// current week's page (and at most every 10 minutes), ask the site for its build stamp (build.json, report.render);
// if it's newer than this page's numbers or code, offer a refresh. Never reloads on its own: you may be mid-read. Nothing is
// cached across visits, so a reload always gets the new build.
(() => {
  const NFLE = window.NFLE, CFG = window.NFLE_CFG || {};
  if (!CFG.current || !NFLE) return;
  let last = Date.now(), shown = false;
  // the asset version this page loaded (its own shell.js link: ?v=<hash>)
  const MYV = ((document.querySelector('script[src*="shell.js?v="]') || {}).src || '').split('?v=')[1] || '';
  const show = () => {
    shown = true;
    const b = document.createElement('button');
    b.type = 'button'; b.className = 'stale-pill'; b.innerHTML = '<i></i>Site updated &middot; <b>Refresh</b>';
    // past the HTTP cache first (GitHub Pages serves the page with max-age 600: a plain reload in a home-screen app can
    // bring back the old page for up to 10 minutes)
    b.onclick = async () => {
      try { await Promise.all([fetch(location.href, { cache: 'reload' }), fetch(new URL('build.json', NFLE.root), { cache: 'reload' })]); } catch (e) { /* offline */ }
      location.reload();
    };
    document.body.appendChild(b);
  };
  const check = async (force = false) => {
    if (shown || document.hidden || (!force && Date.now() - last < 10 * 60000)) return;
    last = Date.now();
    try {
      const r = await fetch(new URL('build.json', NFLE.root), { cache: 'no-store' });
      const b = r.ok ? await r.json() : null, D = NFLE.weekData && NFLE.weekData();
      // new numbers (a full build), or new site code (a UI-only deploy keeps the numbers but changes the assets)
      if (b && D && b.generated && D.generated && b.generated !== D.generated) show();
      else if (b && b.assets && MYV && b.assets !== MYV) show();
    } catch (e) { /* offline: try again next time */ }
  };
  document.addEventListener('visibilitychange', () => check());
  addEventListener('pageshow', e => { if (e.persisted) check(true); });  // restored from the back/forward cache
})();
// Week page header: the season / week picker (every week links to its own page; weeks.json at the site root lists
// them, rewritten every build, so old pages list new weeks), where this page sits in time, and the page details.
(() => {
  const NFLE = window.NFLE, esc = NFLE.esc, CFG = window.NFLE_CFG || {};
  const ws = document.getElementById('pickWeek');
  if (!ws || CFG.page !== 'week') return;
  const prev = document.getElementById('wkPrev'), next = document.getElementById('wkNext');
  const here = `${CFG.season}-${CFG.week}`;
  const narrow = matchMedia('(max-width: 420px)').matches;  // phones: "2026 · Wk 6" keeps the header on one row
  let seasons = { [CFG.season]: { [CFG.week]: location.pathname } };
  const href = p => new URL(p, NFLE.root).href;
  const fill = () => {
    const years = Object.keys(seasons).sort((a, b) => b - a);
    ws.replaceChildren(...years.map(y => {
      const g = document.createElement('optgroup'); g.label = y;
      Object.keys(seasons[y]).sort((a, b) => a - b).forEach(w => g.appendChild(new Option(`${y} · ${narrow ? 'Wk' : 'Week'} ${w}`, `${y}-${w}`)));
      return g;
    }));
    ws.value = here;
    const order = Object.keys(seasons).sort((a, b) => a - b).flatMap(y => Object.keys(seasons[y]).sort((a, b) => a - b).map(w => [y, w]));
    const i = order.findIndex(([y, w]) => `${y}-${w}` === here);
    [[prev, i > 0 ? order[i - 1] : null], [next, i >= 0 ? order[i + 1] : null]].forEach(([a, t]) => {
      a.classList.toggle('off', !t);
      if (t) { a.dataset.to = href(seasons[t[0]][t[1]]); a.href = a.dataset.to + location.hash; a.title = `${t[0]} week ${t[1]}`; }
      else a.removeAttribute('href');
    });
  };
  fill();
  NFLE.load('weeks.json').then(j => { seasons = j; fill(); }).catch(() => {});
  // the tab (hash) carries over, so you stay on the same view
  [prev, next].forEach(a => a.addEventListener('click', () => { if (a.dataset.to) a.href = a.dataset.to + location.hash; }));
  ws.onchange = () => { const [y, w] = ws.value.split('-'); location.href = href(seasons[y][w]) + location.hash; };
  const tag = document.getElementById('wkTag');
  const [cls, txt] = CFG.archive ? ['past', 'Past week'] : CFG.lookahead ? ['ahead', 'Upcoming'] : ['now', 'This week'];
  tag.className = `wk-tag ${cls}`; tag.textContent = txt; tag.hidden = false;
  document.getElementById('wkNow').hidden = !!CFG.current;
  const note = document.getElementById('wkNote');
  if (CFG.archive) { note.textContent = 'Projected before kickoff with only the data available then; actual results alongside.'; note.hidden = false; }
  else if (CFG.lookahead) {
    note.textContent = `${CFG.lookahead} week${CFG.lookahead > 1 ? 's' : ''} out: projected from games so far, no injury report or weather yet. Less certain the further out.`;
    note.title = 'Everyone on the active roster is assumed healthy (injured reserve stays out) and weather is neutral; Vegas lines are used once posted.';
    note.hidden = false;
  }
  // Page details: a tooltip on the (i) (hover on desktop, tap on phones); amber while the injury report is pending.
  const hw = document.querySelector('.hinfo-w'), hb = hw.querySelector('.hinfo');
  // injury reports from the week clock (owner 2026-10-18): how many teams' final reports are in, which are next
  const repLine = D => {
    const ts = Object.keys((D.clock && D.clock.teams) || {});
    if (!ts.length || !NFLE.clock) return D.head.injury_report ? '<span>Injury report <b>in</b></span>' : '';
    const fin = ts.filter(t => NFLE.clock.finalReportIn(t)).length;
    if (fin === ts.length) return '<span>Final injury reports <b>in</b> for every team</span>';
    const nxt = ts.flatMap(t => NFLE.clock.reports(t).filter(r => !r.in)).sort((a, b) => a.due - b.due)[0];
    const when = nxt ? new Date(nxt.due).toLocaleString([], { weekday: 'short', hour: 'numeric', minute: '2-digit' }) : '';
    return `<span${fin ? '' : ' class="alert"'}>Final injury reports in for <b>${fin} of ${ts.length}</b> teams${when ? ` · next report due ${esc(when)}` : ''}</span>`;
  };
  NFLE.week().then(D => {
    if (!D || !D.head) return;
    const h = D.head, live = !(CFG.archive || CFG.lookahead), pending = live && !h.injury_report && !(D.clock && Object.keys(D.clock.teams || {}).some(t => NFLE.clock.reportsIn(t)));
    const sc = h.scoring === 'half' ? 'Half PPR' : h.scoring === 'ppr' ? 'PPR' : String(h.scoring || '').replace(/^./, c => c.toUpperCase());
    hw.querySelector('.hpop').innerHTML = [
      // two different weeks (owner 2026-10-17 read them as one): what the projections are built on, and how far
      // this week's own games have got (a live week's projections use only earlier weeks, as before kickoff)
      `<span>Projections use games through <b>week ${esc(h.data_week)}</b>${CFG.lookahead ? ' (all games played so far)' : ''}</span>`,
      h.n_final ? `<span>Week ${esc(D.week)} so far: <b>${h.n_final} of ${h.n_games}</b> games final</span>` : '',
      `<span>Scoring <b id="scoreName">${esc(sc)}</b></span>`,
      live ? repLine(D) : '',
      `<span>Updated ${esc(D.generated || '')}</span>`].join('');
    hb.classList.toggle('warn', pending);
    hw.hidden = false;
  });
  // keep the popup on screen (owner 2026-10-18: on phones the header wraps, the button sits at the left and the popup,
  // anchored to its right edge, ran off the left side): measured when it opens, shifted back inside a 12px margin
  const fitPop = () => {
    const pop = hw.querySelector('.hpop'); if (!pop) return;
    pop.style.transform = '';
    const r = pop.getBoundingClientRect(), vw = document.documentElement.clientWidth;
    const dx = r.left < 12 ? 12 - r.left : r.right > vw - 12 ? vw - 12 - r.right : 0;
    if (dx) pop.style.transform = `translateX(${Math.round(dx)}px)`;
  };
  hb.addEventListener('click', e => { e.stopPropagation(); const on = hw.classList.toggle('open'); hb.setAttribute('aria-expanded', on); if (on) fitPop(); });
  hw.addEventListener('mouseenter', () => requestAnimationFrame(fitPop));
  document.addEventListener('click', e => { if (!hw.contains(e.target)) { hw.classList.remove('open'); hb.setAttribute('aria-expanded', 'false'); } });
})();
(() => {
  // Four parents (owner, 2026-10-14): Players (incl. transactions = player news) and Teams (incl. playoffs, draft).
  const NAV = [
    { key: 'players', label: 'Players', subs: [['rankings', 'Rankings', 'tab-players'], ['stats', 'Stats'], ['roles', 'Roles', 'tab-roles'], ['injuries', 'Injuries'], ['moves', 'Moves'], ['trends', 'Trends']] },
    { key: 'teams', label: 'Teams', subs: [['all', 'All teams'], ['power', 'Power', 'tab-power'], ['standings', 'Standings'], ['playoffs', 'Playoffs'], ['stats', 'Stats'], ['draft', 'Draft']] },
    { key: 'games', label: 'Games', subs: [['matchups', 'Matchups', 'tab-games']] },  // one view, no sub-tab row (owner 2026-10-23: space)
    // your own fantasy league (Sleeper / public ESPN import; owner 2026-10-15)
    // tab named Fantasy (owner 2026-10-16); its views are the site's sub-tabs (owner 2026-10-18: "uniform with the rest of the
    // site"), all one section (league.js switches views on nfle-route)
    { key: 'league', label: 'Fantasy', subs: [['lineup', 'Lineup', 'tab-league'], ['matchup', 'Matchup', 'tab-league'], ['live', 'Live', 'tab-league'],
                                              ['teams', 'Teams', 'tab-league'], ['waivers', 'Waivers', 'tab-league'], ['trade', 'Trade', 'tab-league']] },
    { key: 'model', label: 'Model', subs: [['model', 'Model', 'tab-model'], ['reference', 'Reference'], ['calc', 'Calc']] },  // Reference: league rates (owner 2026-10-18); Calc: decisions (owner 2026-10-23)
    // Home (owner 2026-10-20: a landing page, "I want to..." tiles): not in the tab bars; the logo opens it, and it is
    // where a first visit lands (a returning visitor still gets the last tab used)
    { key: 'home', label: 'Home', subs: [['home', 'Home', 'tab-home']], hidden: true },
  ];
  // Client-rendered tabs: section id -> area module (assets/<area>.js + .css), loaded the first time the tab opens.
  // A module registers NFLE.areas[<area>] = { mount(section) } and renders into its section.
  const AREAS = { 'tab-teams-all': 'teamgrid', 'tab-teams-standings': 'standings', 'tab-teams-stats': 'teamstats', 'tab-players-stats': 'playerstats',
                  'tab-players-injuries': 'injuries', 'tab-players': 'rankings', 'tab-teams-draft': 'draft',
                  'tab-teams-playoffs': 'playoffs', 'tab-players-moves': 'moves', 'tab-power': 'power',
                  'tab-games': 'matchups', 'tab-roles': 'roles', 'tab-model': 'model',
                  'tab-players-trends': 'trends', 'tab-league': 'league', 'tab-model-reference': 'reference', 'tab-home': 'home',
                  'tab-model-calc': 'calc' };
  const ver = (document.currentScript && new URL(document.currentScript.src).search) || '';
  const loaded = {};
  const NFLE = window.NFLE = window.NFLE || {};
  NFLE.areas = NFLE.areas || {};
  const mountArea = id => {
    const area = AREAS[id], sec = document.getElementById(id);
    if (!area || !sec || sec.dataset.mounted) return;
    sec.dataset.mounted = '1';
    const go = () => { try { NFLE.areas[area].mount(sec); } catch (e) { sec.insertAdjacentHTML('beforeend', `<p class="muted">Couldn't load this tab (${String(e.message || e)}).</p>`); } };
    if (loaded[area]) { loaded[area].then(go); return; }
    const css = document.createElement('link'); css.rel = 'stylesheet'; css.href = new URL(`assets/${area}.css${ver}`, NFLE.root).href;
    document.head.appendChild(css);
    loaded[area] = new Promise((ok, bad) => {
      const js = document.createElement('script'); js.src = new URL(`assets/${area}.js${ver}`, NFLE.root).href;
      js.onload = ok; js.onerror = () => bad(new Error(`assets/${area}.js`)); document.head.appendChild(js);
    });
    loaded[area].then(go, e => sec.insertAdjacentHTML('beforeend', `<p class="muted">Couldn't load this tab (${e.message}).</p>`));
  };
  const OLD = { players: 'players/rankings', roles: 'players/roles', power: 'teams/power', games: 'games', model: 'model',
               playoffs: 'teams/playoffs', draft: 'teams/draft', transactions: 'players/moves', 'games/calc': 'model/calc' };
  const CARD = /^g-/;  // old matchup-tile links: gamecast.js turns them into gamecast links
  const PAGE = /^(player|team)\/(.+)$/;  // player / team cards (rendered by gamecast.js into #pcOv)
  // The card stack lives in the URL (owner 2026-10-20: "make the nested navigation part of the url? so if i share a url
  // it has the stack"): cards in order, joined by "+", each with the sheet open over it after ":", e.g.
  // #team/PHI:players+player/00-0033885 = the Eagles card with its Players sheet, Goedert's card on top. Back pops one.
  const SEG = /^(player|team)\/([^:+]+)(?::([a-z0-9-]+))?$/;
  const segsOf = h => { const t = (h || '').replace(/^#/, ''); if (!t) return null;
    const m = t.split('+').map(x => x.match(SEG)); return m.every(Boolean) ? m.map(x => ({ kind: x[1], id: x[2], sheet: x[3] || '' })) : null; };
  const segStr = x => `${x.kind}/${x.id}${x.sheet ? ':' + x.sheet : ''}`;
  NFLE.slug = t => String(t || '').toLowerCase().normalize('NFD').replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '');
  const nav = document.querySelector('nav.tabs');
  const main = document.querySelector('main .wrap');
  // Pages without the tab bar (game.html) still run the cards (owner 2026-10-17: a player tapped in the gamecast opened
  // over the Players tab of another page): the card opens over the page itself and closing returns to it.
  const listless = !nav || !main;
  if (main && !document.getElementById('tab-home')) main.insertAdjacentHTML('afterbegin', '<section id="tab-home"></section>');
  // the logo opens Home (pages built before Home existed link it to #players)
  document.querySelectorAll('a.brand').forEach(a => { a.href = a.getAttribute('href').replace(/#.*$/, '') + '#home'; a.title = 'Home'; });
  const parent = k => NAV.find(p => p.key === k) || NAV[0];
  const sectionId = (p, s) => s[2] || `tab-${p.key}-${s[0]}`;
  // Player / team CARDS (owner 2026-10-17: "make player pages cards again"): #player/<id> and #team/<abbr> open the
  // card renderer's container (#pcOv, found by gamecast.js) over whatever list you were on, which stays put underneath
  // (its scroll too). Links stay shareable; Back, the close button, a tap outside or Esc closes it. Phones: nearly full
  // screen, sliding up; desktop: a large centered panel. Tile sheets open above it.
  document.body.insertAdjacentHTML('beforeend', `<div class="pc-ov pc-page pc-card" id="pcOv" hidden><div class="pc-wrap">
    <i class="sheet-grab" aria-hidden="true"></i><button type="button" class="pc-x" aria-label="Close">&times;</button>
    <div class="pc" role="dialog" aria-modal="true" aria-labelledby="pcName"><div class="pc-body"></div></div></div></div>`);
  // Stacked cards (owner 2026-10-17: "if i click on a player from a team card, then swipe that player card away, the
  // team card is still there"): opening a card from a card leaves a still copy of the one below in #pcUnder (outside
  // #pcOv, so the renderer never touches it), slightly smaller behind the new card; dragging the top card reveals it.
  // Closing steps back one card (history), which renders the live card below again where you left it.
  document.body.insertAdjacentHTML('beforeend', '<div class="pc-ov pc-page pc-card pc-under" id="pcUnder" hidden aria-hidden="true" inert></div>');
  const cardOv = document.getElementById('pcOv'), cardBox = cardOv.querySelector('.pc'), under = document.getElementById('pcUnder');
  cardOv.parentNode.appendChild(cardOv);  // above the stack copy
  NFLE.pageMode = true;
  // Placeholder sections for tabs not built yet (one per sub-tab), so routing is uniform.
  if (!listless) NAV.forEach(p => p.subs.forEach(s => {
    if (!document.getElementById(sectionId(p, s))) {
      main.insertAdjacentHTML('beforeend', `<section id="${sectionId(p, s)}" class="soon"><div class="sec-head"><div><h2>${s[1] === p.label ? p.label : `${p.label} &middot; ${s[1]}`}</h2><p>Coming soon.</p></div></div></section>`);
    }
  }));
  // Phones show the short label where one exists, so all seven parent tabs fit on one line (owner's pick).
  if (!listless) nav.innerHTML = `<div class="wrap nav-par" role="tablist">${NAV.filter(p => !p.hidden).map(p => `<button type="button" role="tab" data-par="${p.key}">${p.short
      ? `<span class="lbl-long">${p.label}</span><span class="lbl-short">${p.short}</span>` : p.label}</button>`).join('')}</div>
    <div class="wrap nav-sub" hidden></div>`;
  // --navh: the sticky top bar's height (0 where it's hidden), so things that stick below it (the player / team page
  // header) know where to stop.
  const setNavH = () => document.documentElement.style.setProperty('--navh', `${getComputedStyle(nav).display === 'none' ? 0 : nav.offsetHeight}px`);
  if (!listless) { if (window.ResizeObserver) new ResizeObserver(setNavH).observe(nav); window.addEventListener('resize', setNavH); }
  // Phones: a bottom tab bar (owner's choice, 2026-10-14). Five slots: the four busiest parents + More (a sheet with
  // the rest); the sub-tab chips stay in the top bar. The top strip (parent tabs in the top bar, short labels) is
  // kept for a possible future setting: set NAV_MODE = 'top'. Desktop always uses the top strip.
  const NAV_MODE = 'bottom';
  const ICON = {
    players: '<circle cx="12" cy="8" r="3.6"/><path d="M5 20c.8-3.6 3.6-5.6 7-5.6s6.2 2 7 5.6"/>',
    teams: '<path d="M12 3l7 3v5c0 4.4-3 8-7 10-4-2-7-5.6-7-10V6z"/>',
    games: '<rect x="3.5" y="5" width="17" height="15" rx="2.5"/><path d="M3.5 10h17M8 3v4M16 3v4"/>',
    model: '<path d="M4 19V5M4 19h16M8 15l3-4 3 2 5-6"/>',
    league: '<path d="M7 4h10v4a5 5 0 0 1-10 0z"/><path d="M7 6H4.5a2.5 2.5 0 0 0 2.5 3.5M17 6h2.5A2.5 2.5 0 0 1 17 9.5M12 13v4M8.5 20h7"/>',
    more: '<circle cx="5.5" cy="12" r="1.4"/><circle cx="12" cy="12" r="1.4"/><circle cx="18.5" cy="12" r="1.4"/>',
  };
  const svg = k => `<svg viewBox="0 0 24 24" width="22" height="22" aria-hidden="true">${ICON[k]}</svg>`;
  NFLE.navIcon = svg;  // Home's tiles (home.js)
  const navMode = NAV_MODE;
  const BOTTOM = NAV.filter(p => !p.hidden).map(p => p.key);  // all five parents fit: no More sheet (Home isn't a tab)
  let bot = null;
  if (navMode === 'bottom' && !listless) {
    document.documentElement.classList.add('nav-bottom');
    // keyboard up (a text field focused, owner 2026-10-18: "when i search and type i can't see the players being
    // filtered"): the fixed bottom bar rides on top of the keyboard on phones, so it steps aside while typing
    const typing = el => el && el.matches && el.matches('input:not([type=checkbox]):not([type=radio]):not([type=button]), textarea');
    document.addEventListener('focusin', e => { if (typing(e.target)) document.documentElement.classList.add('kb-open'); });
    document.addEventListener('focusout', e => { if (typing(e.target)) document.documentElement.classList.remove('kb-open'); });
    // the page's first-paint copy (pages/week.html) when there is one; older archived pages have none
    bot = document.querySelector('body > .botbar') || document.createElement('div');
    bot.className = 'botbar';
    bot.removeAttribute('aria-hidden');
    const extra = NAV.filter(p => !p.hidden && !BOTTOM.includes(p.key));  // parents beyond the bar go in a More sheet (none today)
    bot.innerHTML = `<nav class="bb-row">${BOTTOM.map(k => `<button type="button" data-par="${k}">${svg(k)}<span>${parent(k).label}</span></button>`).join('')}
      ${extra.length ? `<button type="button" data-more>${svg('more')}<span>More</span></button>` : ''}</nav>
      ${extra.length ? `<div class="bb-sheet" hidden>${extra.map(p => `<button type="button" data-par="${p.key}">${p.label}</button>`).join('')}</div>` : ''}`;
    if (!bot.isConnected) document.body.appendChild(bot);
    // Phones: the sub-tab chips ride in the bottom bar too (all navigation in thumb reach; owner, 2026-10-14) and the
    // top bar is hidden. Wider screens keep everything in the top bar. --bbh = the bar's height, for page padding.
    const phone = matchMedia('(max-width: 640px)');
    const place = () => {
      if (phone.matches) bot.insertBefore(subBar, bot.firstChild); else nav.appendChild(subBar);
      document.documentElement.style.setProperty('--bbh', `${phone.matches ? bot.offsetHeight : 0}px`);
    };
    phone.addEventListener('change', place);
    NFLE.placeBar = place;
  }
  const subBar = listless ? null : nav.querySelector('.nav-sub');
  const parse = h => {
    h = (h || '').replace(/^#/, '');
    if (!h || CARD.test(h)) return null;
    if (OLD[h]) h = OLD[h];
    const [pk, sk] = h.split('/');
    const p = parent(pk);
    const s = p.subs.find(x => x[0] === sk) || p.subs[0];
    return { p, s };
  };
  let lastRoute = null;  // the list route a page was opened from (breadcrumb), with its scroll position
  // The page's tab strip sticks just under its sticky header (second visual audit): the header's height varies (names,
  // phone vs desktop, re-renders), so it's read after each render and while scrolling (one cheap layout read a frame).
  // the card's tab strip sticks just under its sticky header, whose height varies (names, phone vs desktop,
  // re-renders): read after each render and while the card scrolls (one cheap layout read a frame)
  const pcHead = () => { const h = cardBox.querySelector('.pc-head'); if (h) cardOv.style.setProperty('--pchead', `${h.offsetHeight}px`); };
  let phRaf = 0;
  cardBox.addEventListener('scroll', () => { if (!phRaf) phRaf = requestAnimationFrame(() => { phRaf = 0; pcHead(); }); }, { passive: true });
  const scrolls = {};
  let onPage = false, depth = 0, deep = false;  // depth: cards opened since the list (card-to-card adds one)
  const snaps = [];  // snaps[d]: the card at depth d as last seen ({ el: a still copy, top: its scroll })
  const snapshot = () => { const el = cardOv.querySelector('.pc-wrap').cloneNode(true);
    el.querySelectorAll('[id]').forEach(x => x.removeAttribute('id'));
    el.style.transform = ''; el.style.transition = '';
    return { el, top: cardBox.scrollTop }; };
  const sheetAt = {}, sheetPend = {};  // sheets set aside under cards (below), by depth
  cardOv.insertAdjacentHTML('afterbegin', '<button type="button" class="pc-peek" hidden><span class="pc-peek-a" aria-hidden="true">&lsaquo;</span><span class="pc-peek-t"></span></button>');
  const peek = cardOv.querySelector('.pc-peek');
  const showUnder = d => { const s = snaps[d - 1]; under.replaceChildren(); under.hidden = !s; cardOv.classList.toggle('pc-stacked', !!s);
    if (s) { under.appendChild(s.el); s.el.querySelector('.pc').scrollTop = s.top; }
    // that card's sheet, if it had one open, sits on it (visible as the card above slides away)
    const sh = s && sheetAt[d - 1];
    if (sh) { sh.ov.classList.add('sheet-still'); under.appendChild(sh.ov); const x = sh.ov.querySelector('.sheet'); if (x) x.scrollTop = sh.top; }
    // (owner 2026-10-20: "the view directly behind current view showing its header text ... so i can see what to expect
    // if i swipe down"): its name (and its sheet's title) in the strip above the top card; tapping it goes back
    peek.hidden = !s;
    if (s) { const h = s.el.querySelector('.pc-id h3'), name = h ? [...h.childNodes].filter(n => !(n.classList && n.classList.contains('pc-num'))).map(n => n.textContent).join('').trim() : '';
      const st = sh && sh.ov.querySelector('.sheet-h b');
      peek.querySelector('.pc-peek-t').textContent = [name, st ? st.textContent : ''].filter(Boolean).join(' \u00b7 ');
      peek.setAttribute('aria-label', `Back to ${peek.querySelector('.pc-peek-t').textContent}`); } };
  // Sheets ride the card stack (owner 2026-10-20: "we open the depth chart and that slide disappears when we click on
  // a player"): a sheet open when a card opens over it is set aside under the depth it belongs to (0 = the list) and
  // comes back, scrolled where it was, when you return to that depth; closing past it discards it.
  const stashSheet = d => { const ov = document.querySelector('body > .sheet-ov');
    if (!ov) return; const sh = ov.querySelector('.sheet'); sheetAt[d] = { ov, top: sh ? sh.scrollTop : 0 };
    ov.classList.add('sheet-still');
    if (d === 0) ov.classList.add('sheet-behind'); else ov.remove(); };  // depth >= 1: showUnder puts it on its card
  const restoreSheet = d => { Object.keys(sheetAt).forEach(k => { if (+k > d) delete sheetAt[k]; });
    const s = sheetAt[d]; delete sheetAt[d];
    const pend = sheetPend[d]; delete sheetPend[d];
    if (!s && pend) { setTimeout(() => openSheetSlug(pend), 0); return; }  // a shared link's sheet, first visit
    if (!s || document.querySelector('body > .sheet-ov:not(.sheet-behind)')) return;
    s.ov.classList.remove('sheet-behind');
    document.body.appendChild(s.ov); const sh = s.ov.querySelector('.sheet'); if (sh) sh.scrollTop = s.top; };
  const hideCard = () => { cardOv.hidden = true; document.documentElement.classList.remove('pc-open'); onPage = false; depth = 0;
    snaps.length = 0; showUnder(0); settle(); restoreSheet(0); };
  const settle = () => { cardWrap.style.transition = 'none'; cardWrap.style.transform = ''; cardOv.style.backgroundColor = ''; peek.style.opacity = ''; };
  // (owner 2026-10-20: "views that are underneath are sunken visually before popping into the right place"): the
  // still copy underneath is shrunk, raised and dimmed (gamecast.css .pc-under); k = how far the top card has left
  // (0..1) brings it to full size and brightness and fades the backdrop, so the real card lands where the copy is
  const SUNK = () => matchMedia('(min-width: 641px)').matches ? [0.96, -18] : [0.94, -14];
  const PEEK_H = 40;  // phones: the strip a stacked card leaves for the peek (gamecast.css .pc-stacked)
  const rise = (k, ms = 0) => {
    const w = under.querySelector(':scope > .pc-wrap');
    const [sc, ty] = SUNK(), t = ms ? `transform ${ms}ms var(--ease), filter ${ms}ms var(--ease)` : 'none';
    const land = depth - 1 > 1 && matchMedia('(max-width: 640px)').matches ? PEEK_H : 0;
    if (w) { w.style.transition = t; w.style.transform = `scale(${sc + (1 - sc) * k}) translateY(${ty * (1 - k) + land * k}px)`; w.style.filter = `brightness(${0.8 + 0.2 * k})`; }
    peek.style.opacity = String(1 - k);
    cardOv.style.transition = ms ? `background-color ${ms}ms var(--ease)` : 'none';
    cardOv.style.backgroundColor = k > 0 ? `rgba(5,7,10,${(0.4 * (1 - k)).toFixed(3)})` : '';
  };
  // close: back one card (stacked), else back to the list, or, for a card opened from a link, onto the list in place
  const closeCard = () => {
    if (cardOv.hidden) return;
    if (depth > 1 || (!deep && depth > 0)) { history.back(); return; }
    hideCard(); deep = false;
    if (listless) { try { history.replaceState(null, '', location.pathname + location.search); } catch (e) { /* file:// */ } return; }
    const r = lastRoute || parse('players');
    try { history.replaceState(null, '', '#' + (r.p.subs.length < 2 ? r.p.key : `${r.p.key}/${r.s[0]}`)); } catch (e) { /* file:// */ }
  };
  NFLE.closeCard = closeCard;
  // Phones (owner 2026-10-17: "the same behavior we have for sheets"): the card follows a downward drag from its header,
  // or from anywhere once it is scrolled to the top; far or fast enough slides it away and closes it (as the close
  // button does, so Back stays in step), else it springs back. Sideways swipes (a game log scrolling) are left alone.
  const cardWrap = cardOv.querySelector('.pc-wrap');
  let dy0 = 0, dx0 = 0, dmode = null, dlast = 0, dlastT = 0, dv = 0;
  cardBox.addEventListener('touchstart', e => {
    if (e.touches.length !== 1 || !matchMedia('(max-width: 640px)').matches) { dmode = 'off'; return; }
    dy0 = dlast = e.touches[0].clientY; dx0 = e.touches[0].clientX; dlastT = e.timeStamp; dv = 0;
    // tables scroll sideways only, so up / down is always the card's, on a table too (owner 2026-10-25): one rule
    dmode = e.target.closest('.pc-head') && cardBox.scrollTop <= 0 ? 'maybe' : null;
  }, { passive: true });
  cardBox.addEventListener('touchmove', e => {
    if (dmode === 'off' || dmode === 'no') return;
    const y = e.touches[0].clientY, dy = y - dy0, dx = e.touches[0].clientX - dx0;
    if (e.timeStamp > dlastT) { dv = (y - dlast) / (e.timeStamp - dlastT); dlast = y; dlastT = e.timeStamp; }
    if (dmode !== 'drag') {
      if (Math.abs(dy) < 6 && Math.abs(dx) < 6) return;
      dmode = dy > 0 && Math.abs(dy) > Math.abs(dx) && cardBox.scrollTop <= 0 ? 'drag' : 'no';
      if (dmode !== 'drag') return;
    }
    e.preventDefault();
    cardWrap.style.transition = 'none';
    cardWrap.style.transform = `translateY(${Math.max(0, dy)}px)`;
    if (!under.hidden) rise(Math.min(1, Math.max(0, dy) / cardWrap.offsetHeight));
  }, { passive: false });
  cardBox.addEventListener('touchend', () => {
    if (dmode !== 'drag') { dmode = null; return; }
    dmode = null;
    const dy = dlast - dy0;
    cardWrap.style.transition = 'transform .22s var(--ease)';
    if (dy > 0.25 * cardWrap.offsetHeight || dv > 0.6) {
      cardWrap.style.transform = 'translateY(100%)';
      if (!under.hidden) rise(1, 210);
      setTimeout(closeCard, 210);  // it stays off screen until the card below renders or the overlay hides (settle)
    } else { cardWrap.style.transform = ''; if (!under.hidden) rise(0, 220); }
  });
  // a card opened on a card slides up over it (the first one animates from CSS as the overlay appears)
  const playIn = () => { cardWrap.style.animation = 'none'; void cardWrap.offsetWidth; cardWrap.style.animation = ''; };
  const slideClose = () => {
    if (under.hidden || matchMedia('(prefers-reduced-motion: reduce)').matches) { closeCard(); return; }
    cardWrap.style.transition = 'transform .21s var(--ease)';
    cardWrap.style.transform = 'translateY(100%)';
    rise(1, 210);
    setTimeout(closeCard, 210);
  };
  cardOv.addEventListener('click', e => { if (e.target === cardOv || e.target.closest('.pc-x, .pc-peek')) slideClose(); });
  document.addEventListener('keydown', e => { if (e.key === 'Escape' && !cardOv.hidden && !document.querySelector('.sheet-ov, .zoom-ov')) closeCard(); });
  const showPage = (kind, id, dAt) => {
    // a direct link has no list behind it: a team card opens over Teams, a player card over Players
    if (!lastRoute && !listless) { const home = kind === 'team' ? 'teams' : 'players'; show(parse(home), false); deep = true; }
    const fresh = !onPage;  // opened from a list (not card-to-card): the card starts on this page's week
    const fn = kind === 'player' ? NFLE.showPlayer : NFLE.showTeam;
    // depth of this card: its history entry's (Back / Forward), else one deeper than the open card
    const st = history.state && history.state.nfleCard, was = cardOv.hidden ? 0 : depth, d = dAt || st || was + 1;
    let top = 0;
    if (d > was) stashSheet(was);  // a sheet on the card (or list) you're leaving waits for you to come back
    if (d > was && was > 0) { snaps[was] = snapshot(); playIn(); }  // card on card: the one below, as you leave it
    else if (d < was) { top = snaps[d] ? snaps[d].top : 0; snaps.length = d; }  // back down: where you were on it
    cardOv.hidden = false;
    document.documentElement.classList.add('pc-open');
    NFLE.freshPage = fresh;
    NFLE.cardRestore = d < was;  // back down the stack: the card keeps the tab it was on; any other open starts on Summary
    if (fn) fn(decodeURIComponent(id));
    NFLE.freshPage = NFLE.cardRestore = false;
    settle();
    cardBox.scrollTop = top;
    requestAnimationFrame(pcHead);
    // each card's history entry remembers how many cards deep it is, so Back (card 2 -> card 1) counts down, not up
    depth = d;
    if (!st) { try { history.replaceState({ nfleCard: depth }, ''); } catch (e) { /* file:// */ } }
    showUnder(depth);
    if (d < was) restoreSheet(d);
    onPage = true;
    document.dispatchEvent(new CustomEvent('nfle-route', { detail: { parent: lastRoute ? lastRoute.p.key : '', sub: 'card', section: 'pcOv' } }));
  };
  const show = (r, push) => {
    if (lastRoute && lastRoute !== r) scrolls[sectionId(lastRoute.p, lastRoute.s)] = window.scrollY;
    nav.querySelectorAll('[data-par]').forEach(b => b.classList.toggle('on', b.dataset.par === r.p.key));
    if (bot) {
      bot.querySelectorAll('.bb-row [data-par]').forEach(b => b.classList.toggle('on', b.dataset.par === r.p.key));
      const more = bot.querySelector('[data-more]'), sheet = bot.querySelector('.bb-sheet');
      if (more) more.classList.toggle('on', !BOTTOM.includes(r.p.key));
      if (sheet) { sheet.querySelectorAll('[data-par]').forEach(b => b.classList.toggle('on', b.dataset.par === r.p.key)); sheet.hidden = true; }
    }
    subBar.hidden = r.p.subs.length < 2;
    subBar.innerHTML = r.p.subs.length < 2 ? '' : r.p.subs.map(s => `<button type="button" class="chip${s === r.s ? ' on' : ''}" data-sub="${s[0]}">${s[1]}</button>`).join('');
    const id = sectionId(r.p, r.s);
    // the rise-in (ui.css section.enter) on a switch to another section only, not the page's first paint (owner
    // 2026-10-26: the page "flickering" as it loaded, the rise playing while it filled in)
    const switching = !!lastRoute && sectionId(lastRoute.p, lastRoute.s) !== id;
    main.querySelectorAll(':scope > section').forEach(x => { x.classList.toggle('on', x.id === id); x.classList.toggle('enter', switching && x.id === id); });
    const route = r.p.subs.length < 2 ? r.p.key : `${r.p.key}/${r.s[0]}`;
    try { localStorage.setItem('nfledge-tab', route); } catch (e) { /* private mode */ }
    if (push && location.hash.slice(1) !== route) { try { history.replaceState(null, '', '#' + route); } catch (e) { /* file:// */ } }
    if (NFLE.placeBar) NFLE.placeBar();  // the chip row comes and goes with the parent: re-measure the bar
    lastRoute = r; onPage = false;
    mountArea(id);
    // a tab picked starts at its top (owner 2026-10-23: "our scroll position doesn't get cleared when navigating");
    // the back button (hashchange, push false) returns to where that view was left
    if (!push && scrolls[id] != null) requestAnimationFrame(() => window.scrollTo({ top: scrolls[id] }));
    else if (push) window.scrollTo({ top: 0 });
    document.dispatchEvent(new CustomEvent('nfle-route', { detail: { parent: r.p.key, sub: r.s[0], section: id } }));
  };
  const onNav = e => {
    const pb = e.target.closest('[data-par]'), sb = e.target.closest('[data-sub]');
    if (bot && e.target.closest('[data-more]')) { const sh = bot.querySelector('.bb-sheet'); sh.hidden = !sh.hidden; return; }
    if (pb) {  // a parent tab always opens its first sub-tab (owner 2026-10-23: "not to remember the sub tab you were
      // last on. default to rankings, all teams, lineup, and model")
      const p = parent(pb.dataset.par);
      show({ p, s: p.subs[0] }, true);
      window.scrollTo({ top: 0 });
    } else if (sb) {
      const p = parent(nav.querySelector('[data-par].on').dataset.par);
      const s = p.subs.find(x => x[0] === sb.dataset.sub);
      show({ p, s }, true);
    }
  };
  if (!listless) nav.addEventListener('click', onNav);
  if (bot) {
    bot.addEventListener('click', onNav);
    document.addEventListener('click', e => { const sh = bot.querySelector('.bb-sheet'); if (sh && !bot.contains(e.target)) sh.hidden = true; });
  }
  // a card's sheet named in the URL: open it once the card has drawn its tiles (some fill in after data loads)
  const openSheetSlug = (slug, tries = 0, at = depth) => {
    if (!slug || document.querySelector('body > .sheet-ov') || cardOv.hidden || depth !== at) return;  // moved on: drop it
    const t = [...cardOv.querySelectorAll('.pc-tap[data-sheet]')].find(x => NFLE.slug(x.dataset.sheet) === slug);
    if (t) t.click(); else if (tries < 20) setTimeout(() => openSheetSlug(slug, tries + 1, at), 150);
  };
  // the URL for opening a card from where you are: on a card, one deeper in the stack; on a list, a new stack
  NFLE.cardHref = (kind, id) => { const cur = !cardOv.hidden && segsOf(location.hash);
    return '#' + (cur ? cur.map(segStr).join('+') + '+' : '') + `${kind}/${id}`; };
  // a sheet opened or closed over the top card: recorded on its segment (same history entry)
  NFLE.sheetMark = slug => { const cur = !cardOv.hidden && segsOf(location.hash); if (!cur) return;
    cur[cur.length - 1].sheet = slug || '';
    try { history.replaceState(history.state, '', location.pathname + location.search + '#' + cur.map(segStr).join('+')); } catch (e) { /* file:// */ } };
  // a shared stack: each card in order (its own history entry, so Back steps down it), its sheet opened as it was
  // (the sheets of cards below the top one open when you step back to them: sheetPend)
  const buildStack = segs => segs.forEach((x, i) => {
    const h = location.pathname + location.search + '#' + segs.slice(0, i + 1).map(segStr).join('+');
    try { if (i === 0) history.replaceState({ nfleCard: 1 }, '', h); else history.pushState({ nfleCard: i + 1 }, '', h); } catch (e) { /* file:// */ }
    showPage(x.kind, x.id, i + 1);
    if (i < segs.length - 1) { if (x.sheet) sheetPend[i + 1] = x.sheet; } else openSheetSlug(x.sheet);
  });
  const route = (h, push) => {
    const segs = segsOf(h);
    if (segs) { const top = segs[segs.length - 1]; showPage(top.kind, top.id, segs.length); openSheetSlug(top.sheet); return true; }
    if (listless) { hideCard(); deep = false; return true; }  // the card's entry left: the page itself
    const r = parse(h);
    if (r) { const back = !cardOv.hidden && lastRoute && r.p === lastRoute.p && r.s === lastRoute.s;
      hideCard(); deep = false;
      if (!back) show(r, push);  // closing a card over the same list leaves it as it was (scroll included)
      return true; }
    return false;
  };
  window.addEventListener('hashchange', () => route(location.hash, false));
  document.addEventListener('click', e => {
    const a = !cardOv.hidden && e.target.closest && e.target.closest('a[href^="#player/"], a[href^="#team/"]');
    if (!a || e.defaultPrevented || e.metaKey || e.ctrlKey) return;
    const m = a.getAttribute('href').slice(1).match(PAGE);
    if (!m) return;
    e.preventDefault(); location.hash = NFLE.cardHref(m[1], m[2]).slice(1);
  });
  let saved = null; try { saved = localStorage.getItem('nfledge-tab'); } catch (e) { /* ignore */ }
  // A card link opened directly: over the tab you last used in that section (Teams for a team, Players for a player)
  if (listless) {
    const sg = segsOf(location.hash);
    if (sg) { deep = true; NFLE.runStack = () => { NFLE.runStack = null; buildStack(sg); }; }
  } else if (segsOf(location.hash)) {
    const sg = segsOf(location.hash);
    const sec = sg[0].kind === 'team' ? 'teams' : 'players';
    show((saved && saved.startsWith(sec) ? parse(saved) : null) || parse(sec), false);
    deep = true;
    // the cards need the week's data (gamecast.js loads it, then calls this); a stack built before it would be empty
    NFLE.runStack = () => { NFLE.runStack = null; buildStack(sg); };
  }
  else show(parse(location.hash) || parse(saved) || parse('home'), !CARD.test(location.hash.slice(1)));
  window.NFLE_SHELL = { go: h => { const r = parse(h); if (r) show(r, true); } };
})();
// Number chips in every data table (owner 2026-10-15, after the box score): a cell whose value is a stat (digits with
// / - . , % : and the like, plain or inside one simple wrapper such as a colored span) gets it wrapped in a small chip
// (span.sc); a column's header gets a chip (span.sc.h) when its cells have them, so heads and values match. Cells with
// their own visuals (bars, badges, photos, links, several parts) are left alone, a column chips only when 80%+ of
// its values qualify, and a table with class "no-chips" is skipped. One observer covers tables rendered later too
// (sorting, paging, tab switches, live repaints).
(() => {
  const NFLE = window.NFLE = window.NFLE || {};
  const OK = new Set(['B', 'STRONG', 'ABBR', 'SMALL', 'SPAN']);
  const STAT = /^[\s\d.,%+\-\u2212\u2013\u2014/:()]+$/;
  const STAT2 = /^(?:[WLT]\d+|R\d+:\d+|[+\-\u2212]?\$?[\d.,]+[MK]?)$/;  // streaks, draft slots, contracts
  const plain = el => {
    const kids = [...el.childNodes], elems = kids.filter(n => n.nodeType === 1);
    if (!kids.length || elems.length > 1) return false;
    if (elems.some(n => !OK.has(n.tagName) || n.children.length || n.classList.contains('sc'))) return false;
    return kids.every(n => n.nodeType === 1 || n.nodeType === 3 && (elems.length === 0 || !n.textContent.trim()));
  };
  const wrapIn = (el, cls) => {
    const sp = document.createElement('span');
    sp.className = cls;
    [...el.childNodes].forEach(n => sp.appendChild(n));
    el.appendChild(sp);
  };
  // 1 = chip it, 0 = blank (doesn't count), -1 = not a plain stat
  const kind = td => {
    if (td.querySelector('.sc')) return 2;  // already chipped (by the helper, or by a table that marks its own value)
    const t = td.textContent.trim();
    if (!t || /^[–—-]+$/.test(t)) return 0;
    return !td.classList.contains('stick') && plain(td) && /\d/.test(t) && (STAT.test(t) || STAT2.test(t)) ? 1 : -1;
  };
  const table = tb => {
    if (tb.classList.contains('no-chips')) return;
    const by = new Map();  // column -> [[cell, kind]]
    // columns by position (a cell spanning several columns, like a season header row, sits out)
    const cols_of = r => { let c = 0; return [...r.cells].map(td => { const at = c; c += td.colSpan || 1; return [td, at]; }); };
    [...tb.tBodies].forEach(b => [...b.rows].forEach(r => cols_of(r).forEach(([td, at]) => {
      if ((td.colSpan || 1) > 1 || td.tagName === 'TH') return;  // header cells inside a body (per-season blocks) don't vote
      if (!by.has(at)) by.set(at, []);
      by.get(at).push([td, kind(td)]);
    })));
    const cols = new Set();
    by.forEach((list, i) => {
      // a column chips when at least 80% of its values are plain stats (playoff rows' "WC", a rank's "(4lw)" note stay plain)
      const yes = list.filter(([, k]) => k > 0).length, no = list.filter(([, k]) => k < 0).length;
      if (!yes || yes < 4 * no) return;
      list.forEach(([td, k]) => { if (k === 1) wrapIn(td, 'sc'); });
      cols.add(i);
    });
    // the sticky header copy (Table's .fhead) has no body: it follows its twin's columns
    const twin = !tb.tBodies.length && tb.closest('.fhead') && tb.closest('.dt-wrap') ? tb.closest('.dt-wrap').querySelector('.scroll table') : null;
    if (twin && twin.tBodies[0] && twin.tBodies[0].rows[0]) {
      cols_of(twin.tBodies[0].rows[0]).forEach(([td, at]) => { if (td.querySelector(':scope > .sc')) cols.add(at); });
    }
    // headers wherever they sit (thead, or header rows inside each body block); group headers span columns: skipped
    [...tb.rows].forEach(r => cols_of(r).forEach(([th, at]) => {
      if (th.tagName === 'TH' && (th.colSpan || 1) === 1 && cols.has(at) && !th.querySelector(':scope > .sc') && plain(th) && th.textContent.trim()) wrapIn(th, 'sc h');
    }));
    if (!twin) {  // keep the copy in step
      const cp = tb.closest('.dt-wrap') && tb.closest('.dt-wrap').querySelector('.fhead table');
      if (cp && cp !== tb) table(cp);
    }
  };
  NFLE.chips = root => {
    if (!root || !root.querySelectorAll) return;
    const t = root.closest ? root.closest('table') : null;
    if (t) { table(t); return; }
    root.querySelectorAll('table').forEach(table);
  };
  const pending = new Set();
  let raf = 0;
  const run = () => { raf = 0; const ns = [...pending]; pending.clear(); ns.forEach(n => { if (n.isConnected) NFLE.chips(n); }); };
  const start = () => {
    NFLE.chips(document.body);
    new MutationObserver(ms => {
      ms.forEach(m => m.addedNodes.forEach(n => {
        if (n.nodeType === 1 && !(n.classList && n.classList.contains('sc'))) pending.add(n);
        else if (n.nodeType === 3 && n.parentElement && !n.parentElement.classList.contains('sc')) pending.add(n.parentElement);
      }));
      if (pending.size && !raf) raf = requestAnimationFrame(run);
    }).observe(document.body, { childList: true, subtree: true });
  };
  if (document.body) start(); else document.addEventListener('DOMContentLoaded', start);
})();
// How to read pop-outs close on a tap outside them or Esc (site.css details.howto)
(() => {
  const closeAll = keep => document.querySelectorAll('details.howto[open]:not(.od-track)').forEach(d => { if (d !== keep) d.open = false; });
  document.addEventListener('click', e => { closeAll(e.target.closest && e.target.closest('details.howto')); });
  document.addEventListener('keydown', e => { if (e.key === 'Escape') closeAll(null); });
})();
// The page never sits scrolled past its own end (owner 2026-10-25, screenshot: Box score > Fantasy with half a screen of
// blank space under the footer). When content shrinks under the reader (a sub-tab that hides long tables, a live
// re-render with a shorter pane), iOS keeps the old scroll position and paints empty space below the page until the
// next touch; whenever the body shrinks, snap back to the real bottom.
(() => {
  if (!window.ResizeObserver) return;
  let raf = 0;
  const clamp = () => { raf = 0; if (window.NFLE && NFLE.scroller) return;  // an inner scroller clamps itself (the app shell)
    const max = Math.max(0, document.documentElement.scrollHeight - innerHeight);
    if (scrollY > max + 1) scrollTo({ top: max }); };
  const start = () => new ResizeObserver(() => { if (!raf) raf = requestAnimationFrame(clamp); }).observe(document.body);
  if (document.body) start(); else document.addEventListener('DOMContentLoaded', start);
})();
// Kicker and D/ST scoring from data/kdst.json lines (tools/kdst_build.py): shared by Rankings and the Fantasy tab.
// STD = standard ESPN scoring, the rules both models were tested on (nfledge/kickers.py STANDARD, defenses.py ESPN_STD).
(() => {
  const NFLE = window.NFLE = window.NFLE || {};
  // (2026-10-25) + 3-and-outs, 4th-down stops, special-teams forced fumbles / recoveries (Sleeper scores them)
  const DSTAT = ['sack', 'int', 'fum_rec', 'ff', 'def_td', 'st_td', 'safe', 'blk', 'pass_def', 'tkl_loss', 'forced_punts', 'def_2pt',
                 'three_out', 'fourth_stop', 'st_ff', 'st_fum_rec'];
  const erf = x => { const t = 1 / (1 + 0.3275911 * Math.abs(x)), y = 1 - (((((1.061405429 * t - 1.453152027) * t) + 1.421413741) * t - 0.284496736) * t + 0.254829592) * t * Math.exp(-x * x); return x >= 0 ? y : -y; };
  const Phi = z => 0.5 * (1 + erf(z / Math.SQRT2));
  // P(lo <= X <= hi) for an integer outcome of normal(mu, sd); below 0 counts as 0
  const pBetween = (mu, sd, lo, hi) => (hi === Infinity ? 1 : Phi((hi + 0.5 - mu) / sd)) - (lo <= 0 ? 0 : Phi((lo - 0.5 - mu) / sd));
  const dstScore = (ln, w) => {
    let t = DSTAT.reduce((a, k) => a + (ln[k] || 0) * (w[k] || 0), 0);
    (w.pa_tiers || []).forEach(([lo, hi, pts]) => { t += pts * pBetween(ln.pa_mu, ln.pa_sd, lo, hi); });
    (w.ya_tiers || []).forEach(([lo, hi, pts]) => { t += pts * pBetween(ln.ya_mu, ln.ya_sd, lo, hi); });
    return t + (w.pts_allow || 0) * ln.pa_mu + (w.yds_allow || 0) * ln.ya_mu;
  };
  const kScore = (keys, line, w) => keys.reduce((t, k, i) => t + (line[i] || 0) * (w[k] || 0), 0);
  const STD_K = { fgm_0_19: 3, fgm_20_29: 3, fgm_30_39: 3, fgm_40_49: 4, fgm_50_59: 5, fgm_60_: 5, fgmiss_0_19: -1, fgmiss_20_29: -1,
                  fgmiss_30_39: -1, fgmiss_40_49: -1, fgmiss_50_59: -1, fgmiss_60_: -1, xpm: 1, xpmiss: -1 };
  const STD_D = { sack: 1, int: 2, fum_rec: 2, def_td: 6, st_td: 6, safe: 2, blk: 2,
                  pa_tiers: [[0, 0, 5], [1, 6, 4], [7, 13, 3], [14, 17, 1], [18, 27, 0], [28, 34, -1], [35, 45, -3], [46, Infinity, -5]] };
  NFLE.kdst = { DSTAT, Phi, pBetween, dstScore, kScore, STD_K, STD_D };
})();
// Home-screen app (iOS "Add to Home Screen" / installed PWA): no browser chrome, so two things the browser normally
// handles are ours. ?standalone=1 turns this on in a normal tab (testing).
(() => {
  const NFLE = window.NFLE, html = document.documentElement;
  const standalone = navigator.standalone === true || matchMedia('(display-mode: standalone)').matches
    || /[?&]standalone=1\b/.test(location.search);
  if (!standalone) return;
  html.classList.add('standalone');
  // (0) The top safe area, measured (owner 2026-10-25, screenshot: "NFL Edge" under the status bar after switching back;
  // "when switching back to the app can we have a strict check every single time to reposition the view accounting for
  // safe areas"). iOS reports env(safe-area-inset-top) as 0 for a moment after a resume and WebKit doesn't always
  // re-apply env() afterwards, so the page's top padding and the status-bar cover collapsed. A probe sized by env() is
  // measured instead, the last good value kept per orientation (a 0 read in portrait right after a resume never replaces
  // a known inset; landscape's 0 is real), and set as --sat, which the top padding, the cover and every sticky offset
  // read (shell.css). Re-checked on every return, in steps as the viewport settles, with the rest of the measured layout.
  const probe = document.createElement('div');
  probe.setAttribute('aria-hidden', 'true');
  probe.style.cssText = 'position:fixed;top:0;left:0;width:0;visibility:hidden;pointer-events:none';
  document.body.appendChild(probe);
  const known = {};
  try { Object.assign(known, JSON.parse(localStorage.getItem('nfle-sat') || '{}')); } catch (e) { /* private mode */ }
  const setSat = () => {
    probe.style.height = '0px'; void probe.offsetHeight;  // force WebKit to re-resolve env() rather than reuse a stale value
    probe.style.height = 'env(safe-area-inset-top)';
    const m = probe.offsetHeight, o = innerWidth > innerHeight ? 'l' : 'p';
    if (m > 0 && m !== known[o]) { known[o] = m; try { localStorage.setItem('nfle-sat', JSON.stringify(known)); } catch (e) { /* ignore */ } }
    const v = m > 0 ? m : (known[o] || 0);
    if (html.style.getPropertyValue('--sat') !== `${v}px`) html.style.setProperty('--sat', `${v}px`);
  };
  setSat();
  // every measured offset after the safe area: the top bar's height and the sticky rows (resize listeners), the bottom
  // bar (fixBar), the matchup tiles' fit (paintMini)
  const relayout = () => {
    setSat();
    dispatchEvent(new Event('resize'));
    if (NFLE.fixBar) NFLE.fixBar();
    if (NFLE.paintMini && document.querySelector('.mgrid') && document.querySelector('.mgrid').offsetParent) NFLE.paintMini();
  };
  const settleTop = () => [0, 60, 250, 600, 1200, 2000].forEach(t => setTimeout(relayout, t));
  document.addEventListener('visibilitychange', () => { if (!document.hidden) settleTop(); });
  addEventListener('pageshow', settleTop);
  addEventListener('focus', settleTop);
  addEventListener('orientationchange', settleTop);
  if (window.visualViewport) visualViewport.addEventListener('resize', setSat);
  NFLE.relayout = relayout;
  // (0b) App shell (owner 2026-10-25, after the bottom bar rode up to mid-screen on a return to the app once more:
  // "any rearchitecture worth considering?" ... "i want it working correctly and less bugs to squash"). iOS anchors
  // position: fixed to a layout viewport that can be stale after the keyboard or an app switch, and every fix so far
  // re-measured and nudged the bar on timers. Here the page itself never scrolls: the body is the drawn area (fixed,
  // inset 0: see "The column's size" below), the content scrolls in #appScroll, and the bar is the column's
  // last row, so there is nothing to drift. Window scrolling (scrollY, pageYOffset, scrollTo / scroll / scrollBy, the
  // window's scroll event) is redirected to #appScroll so the rest of the site works unchanged. Overlays (cards,
  // sheets), scripts and the pull-to-refresh stay direct children of the body. Lost: iOS's tap-the-clock-to-top, which
  // only scrolls the page itself.
  const bar = document.querySelector('body > .botbar, body > nav.gc-bot');
  const sc = document.createElement('div');
  sc.id = 'appScroll';
  const stays = el => el === bar || el === probe || /^(SCRIPT|STYLE|LINK|TEMPLATE)$/.test(el.tagName)
    || el.matches('.pc-ov, .sheet-ov, .ptr') || getComputedStyle(el).position === 'fixed';
  [...document.body.children].forEach(el => { if (!stays(el)) sc.appendChild(el); });
  document.body.insertBefore(sc, bar || document.body.firstChild);
  // its rules travel with it (game.html loads ui.css and gamecast.css, not shell.css): one screen-tall column, the
  // content scrolling from under the status bar (an opaque cover over it; sticky offsets keep their --sat), the bar in
  // the flow
  const st = document.createElement('style');
  // (2026-10-25, after research: see the comment below st) the column is pinned to the area WebKit draws (fixed,
  // inset 0), never sized from lvh / vh / screen
  st.textContent = `html.app-shell { height: 100%; overflow: hidden; overscroll-behavior: none; }
html.app-shell body { position: fixed; inset: 0; display: flex; flex-direction: column; overflow: hidden; overscroll-behavior: none;
  margin: 0; padding-top: 0 !important; padding-bottom: 0 !important; }
html.app-shell #appScroll { flex: 1 1 auto; min-height: 0; overflow-x: hidden; overflow-y: auto; -webkit-overflow-scrolling: touch;
  overscroll-behavior-y: contain; padding-top: var(--sat, 0px); }
html.app-shell body::before { content: ""; position: fixed; top: 0; left: 0; right: 0; height: var(--sat, 0px); background: var(--bg); z-index: 95; }
html.app-shell body > .botbar, html.app-shell body > nav.gc-bot { position: relative !important; top: auto !important; bottom: auto !important;
  left: auto !important; right: auto !important; flex: none; }
html.app-shell nav.tabs, html.app-shell nav.gc-tabs, html.app-shell .gc-jump, html.app-shell .gc-panes { top: var(--sat, 0px); }
html.app-shell.pc-open #appScroll { overflow: hidden; }
html.app-shell .ptr { position: fixed; left: 50%; top: calc(var(--sat, 0px) + 8px); z-index: 80; width: 38px; height: 38px; margin-left: -19px;
  border-radius: 50%; background: var(--panel2); border: 1px solid var(--line); display: grid; place-items: center;
  opacity: 0; transform: translateY(-44px) scale(.6); pointer-events: none; }
html.app-shell .ptr svg { width: 19px; height: 19px; fill: none; stroke: var(--muted); stroke-width: 2.2; stroke-linecap: round; stroke-linejoin: round; }
html.app-shell .ptr.ready svg, html.app-shell .ptr.busy svg { stroke: var(--accent); }
html.app-shell .ptr.busy svg { animation: ptr-spin .8s linear infinite; }
@keyframes ptr-spin { to { transform: rotate(360deg); } }`;
  document.head.appendChild(st);
  html.classList.add('app-shell');
  // The column's size (owner 2026-10-25: the bottom bar's icons cut off below the screen, twice; "instead of more
  // guesses, research"). Findings (sources in docs/INSIGHTS.md (DL)): the site has no apple-mobile-web-app-status-bar-
  // style, so the installed app has iOS's default opaque status bar: WebKit draws the page BELOW it, innerHeight =
  // screen - status bar (~873 on a Pro Max), while 100vh / 100lvh and screen.height report the full screen (932; WebKit
  // 316008, "Incorrect 100vh and -lvh in standalone web apps without apple-mobile-web-app-status-bar-style"). A column
  // sized from either lost its bottom ~59 px: the bar's icons. So: fixed, inset 0 (the area WebKit actually draws).
  // Separately, in standalone the keyboard (and sometimes a return to the app) leaves innerHeight short by a status bar
  // and it doesn't come back by itself (WebKit 254868 family; cederhook, lifekit reports): heal() below.
  // heal(): the tallest innerHeight seen at this width; when the current one is short by more than a few px with no
  // keyboard up, hide and show the column, which makes WebKit re-measure the viewport (the cederhook pattern), keeping
  // the content's scroll
  let maxH = innerHeight, lastW = innerWidth;
  const heal = () => {
    if (innerWidth !== lastW) { lastW = innerWidth; maxH = innerHeight; return; }
    maxH = Math.max(maxH, innerHeight);
    if (maxH - innerHeight <= 4 || html.classList.contains('kb-open')) return;
    const top = sc.scrollTop;
    document.body.style.display = 'none'; void document.body.offsetHeight; document.body.style.display = '';
    sc.scrollTop = top;
    maxH = Math.max(innerHeight, maxH);
  };
  document.addEventListener('focusout', e => { if (e.target.matches && e.target.matches('input, textarea, [contenteditable]')) [150, 500].forEach(t => setTimeout(heal, t)); });
  addEventListener('pageshow', () => setTimeout(heal, 300));
  document.addEventListener('visibilitychange', () => { if (!document.hidden) [300, 1000].forEach(t => setTimeout(heal, t)); });
  addEventListener('orientationchange', () => setTimeout(() => { lastW = -1; heal(); }, 500));
  if (window.visualViewport) visualViewport.addEventListener('resize', () => { if (innerWidth === lastW) maxH = Math.max(maxH, innerHeight); });
  // the document itself never scrolls here: iOS still scrolls an overflow: hidden page to bring a focused field or a
  // link target into view, which would slide the whole column (the bar with it) off the screen
  const pin = () => { const se = document.scrollingElement; if (se && se.scrollTop) se.scrollTop = 0; };
  document.addEventListener('scroll', e => { if (e.target === document) pin(); }, { passive: true, capture: true });
  document.addEventListener('visibilitychange', () => { if (!document.hidden) [0, 300, 1000].forEach(t => setTimeout(pin, t)); });
  Object.defineProperty(window, 'scrollY', { configurable: true, get: () => sc.scrollTop });
  Object.defineProperty(window, 'pageYOffset', { configurable: true, get: () => sc.scrollTop });
  const to = (a, b) => { if (a && typeof a === 'object') sc.scrollTo(a); else sc.scrollTo(+a || 0, +b || 0); };
  window.scrollTo = to; window.scroll = to;
  window.scrollBy = (a, b) => { if (a && typeof a === 'object') sc.scrollBy(a); else sc.scrollBy(+a || 0, +b || 0); };
  sc.addEventListener('scroll', () => dispatchEvent(new Event('scroll')), { passive: true });
  NFLE.scroller = sc;
  // (0c) Layout readout (owner 2026-10-25: the bar still cut off after two fixes built on guesses about which iOS number
  // was wrong): 5 quick taps on the page header toggle a small panel of every height iOS reports and where the column
  // and the bar actually are; it stays on (across reloads and app switches) until toggled off, so a screenshot taken
  // when the bar is wrong shows which measure was off.
  const KEY = 'nfle-layout-debug';
  let dbg = null, dbgT = 0, taps = [];
  const px = v => Math.round(v * 10) / 10;
  const measure = css => { const d = document.createElement('div'); d.style.cssText = `position:fixed;top:0;left:0;width:0;visibility:hidden;height:${css}`;
    document.body.appendChild(d); const h = d.getBoundingClientRect().height; d.remove(); return px(h); };
  const drawDbg = () => {
    if (!dbg) return;
    const vv = window.visualViewport, b = bar && bar.getBoundingClientRect(), s = sc.getBoundingClientRect(), bd = document.body.getBoundingClientRect();
    const v = ([...document.scripts].find(x => /shell\.js/.test(x.src)) || {}).src || '';
    const ios = (navigator.userAgent.match(/OS (\d+[_\d]*) like Mac/) || [])[1];
    dbg.textContent = [
      `v ${(v.match(/v=([^&]+)/) || [])[1] || '?'}  iOS ${ios ? ios.replace(/_/g, '.') : '?'}  shell ${html.classList.contains('app-shell')}  ${innerWidth > innerHeight ? 'landscape' : 'portrait'}`,
      `standalone ${navigator.standalone} display-mode ${matchMedia('(display-mode: standalone)').matches}  kb ${html.classList.contains('kb-open')}`,
      `screen ${screen.width}x${screen.height} dpr ${devicePixelRatio}  max inner seen ${maxH}`,
      `inner ${innerWidth}x${innerHeight}  docEl ${document.documentElement.clientHeight}  100% ${measure('100%')}`,
      vv ? `vv ${px(vv.width)}x${px(vv.height)} top ${px(vv.offsetTop)} scale ${px(vv.scale)}` : 'vv none',
      `100vh ${measure('100vh')} lvh ${measure('100lvh')} svh ${measure('100svh')} dvh ${measure('100dvh')}`,
      `safe top ${measure('env(safe-area-inset-top)')} bottom ${measure('env(safe-area-inset-bottom)')}  --sat ${html.style.getPropertyValue('--sat') || '-'}`,
      `body ${px(bd.top)}..${px(bd.bottom)} (h ${px(bd.height)})  scroller ${px(s.top)}..${px(s.bottom)}`,
      b ? `bar ${px(b.top)}..${px(b.bottom)} (h ${px(b.height)})` : 'bar none',
      `doc scroll ${document.scrollingElement.scrollTop}  content scroll ${Math.round(sc.scrollTop)}`,
    ].join('\n');
  };
  const toggleDbg = on => {
    try { if (on) localStorage.setItem(KEY, '1'); else localStorage.removeItem(KEY); } catch (e) { /* ignore */ }
    if (on && !dbg) {
      dbg = document.createElement('pre');
      dbg.style.cssText = 'position:fixed;left:6px;right:6px;top:calc(var(--sat, 0px) + 4px);z-index:400;margin:0;padding:6px 8px;border-radius:8px;'
        + 'background:rgba(0,0,0,.82);color:#9fe870;font:10.5px/1.35 ui-monospace,Menlo,monospace;white-space:pre-wrap;pointer-events:none;';
      document.body.appendChild(dbg);
      dbgT = setInterval(drawDbg, 500); drawDbg();
    } else if (!on && dbg) { clearInterval(dbgT); dbg.remove(); dbg = null; }
  };
  // the taps are counted across reloads (the title is the home link: each tap reloads the page)
  document.addEventListener('click', e => {
    if (!e.target.closest || !e.target.closest('header')) return;
    try { taps = JSON.parse(sessionStorage.getItem('nfle-dbg-taps') || '[]'); } catch (x) { /* keep the in-memory list */ }
    const now = Date.now(); taps = taps.filter(t => now - t < 12000); taps.push(now);
    if (taps.length >= 5) { taps = []; toggleDbg(!dbg); }
    try { sessionStorage.setItem('nfle-dbg-taps', JSON.stringify(taps)); } catch (x) { /* ignore */ }
  }, true);
  try { if (localStorage.getItem(KEY)) toggleDbg(true); } catch (e) { /* ignore */ }
  // (1) Bottom bar drift (owner 2026-10-20, screenshot: the bar rides up to mid-screen). WebKit bug in standalone mode
  // (bugs.webkit.org 297779, Apple forums 800154): after the keyboard closes the layout viewport keeps its keyboard-
  // shrunk height, and position: fixed anchors to it. When the visual viewport's bottom and the layout viewport's
  // bottom disagree by more than a toolbar's worth, pin the bar to the visual bottom; otherwise plain CSS (bottom: 0).
  const bot = document.querySelector('body > .botbar'), vv = window.visualViewport;
  if (bot && vv && !NFLE.scroller) {  // (0b) the app shell has no fixed bar to drift: this fallback never runs there
    let raf = 0, touching = false;
    // never during a gesture or a rubber-band bounce (owner 2026-10-20: pulling to refresh slid the bar up): the
    // visual viewport moves then by design; the keyboard drift is a steady state, re-checked once the page settles
    const overscrolled = () => scrollY < 0 || scrollY > html.scrollHeight - innerHeight + 1;
    const fix = () => {
      raf = 0;
      if (touching || overscrolled()) return;
      const drift = vv.offsetTop + vv.height - html.clientHeight;
      // the bar's BOTTOM edge goes to the visible bottom, never its top (2026-10-23, owner: after switching apps the
      // bar sat in the home-indicator area): right after a resume iOS reports the safe area as 0 for a moment, so a
      // top computed from the bar's height then was too low once the safe-area padding came back and the bar grew
      if (Math.abs(drift) > 40 && !html.classList.contains('kb-open')) {
        bot.style.bottom = `${Math.round(-drift)}px`;
        bot.style.top = 'auto';
      } else if (bot.style.bottom || bot.style.top) {
        bot.style.top = ''; bot.style.bottom = '';
      }
    };
    const soon = () => { if (!raf) raf = requestAnimationFrame(fix); };
    addEventListener('touchstart', () => { touching = true; }, { passive: true });
    const settle = () => { touching = false; setTimeout(soon, 600); };  // after the bounce / momentum ends
    addEventListener('touchend', settle, { passive: true });
    addEventListener('touchcancel', settle, { passive: true });
    vv.addEventListener('resize', soon);
    vv.addEventListener('scroll', soon);
    addEventListener('scroll', soon, { passive: true });
    // the keyboard just closed: nudge WebKit to re-measure the viewport (a same-position scroll), then re-check
    document.addEventListener('focusout', () => setTimeout(() => { scrollTo(scrollX, scrollY); fix(); }, 350));
    // back from another app (owner 2026-10-22, screenshot: the bar mid-screen again after switching apps): the swipe up
    // from the bottom edge that opens the app switcher starts as a touch here and ends outside, so no touchend came and
    // "touching" stayed true, which blocked every later fix; and nothing re-checked on return. On return: forget the
    // touch, nudge WebKit to re-measure, and re-check as the viewport settles (it does in steps after a resume).
    const resumed = () => { touching = false; [60, 350, 900].forEach(t => setTimeout(() => { scrollTo(scrollX, scrollY); fix(); }, t)); };
    document.addEventListener('visibilitychange', () => { if (!document.hidden) resumed(); });
    addEventListener('pageshow', resumed);
    addEventListener('focus', resumed);
    addEventListener('orientationchange', resumed);
    NFLE.fixBar = fix;
  }
  // (2) Pull down to refresh (owner 2026-10-20: "where the browser doesn't already handle it"): from the top of the
  // page, pull past the line and let go. Refresh = refetch the page and the build stamp past the HTTP cache, then
  // reload, so new numbers and new site code both arrive (a home-screen app otherwise keeps old code until it's killed).
  const TH = 70, MAX = 110;
  const ptr = document.createElement('div');
  ptr.className = 'ptr'; ptr.setAttribute('aria-hidden', 'true');
  ptr.innerHTML = '<svg viewBox="0 0 24 24"><path d="M20 12a8 8 0 1 1-2.34-5.66"/><path d="M20 4v5h-5"/></svg>';
  document.body.appendChild(ptr);
  let y0 = null, x0 = 0, pull = 0, busy = false;
  const blocked = t => html.classList.contains('pc-open') || html.classList.contains('kb-open')
    || document.querySelector('.sheet-ov, .zoom-ov') || (t && t.closest && t.closest('input, textarea, select, .bb-sheet'));
  const draw = () => {
    const d = Math.min(pull, MAX) * 0.6, k = Math.min(1, pull / TH);
    ptr.style.opacity = String(Math.min(1, pull / 30));
    ptr.style.transform = `translateY(${d - 44}px) scale(${0.6 + 0.4 * k})`;
    ptr.querySelector('svg').style.transform = `rotate(${Math.round(k * 300)}deg)`;
    ptr.classList.toggle('ready', pull >= TH);
  };
  const reset = () => { pull = 0; ptr.classList.remove('ready'); ptr.style.opacity = '0'; ptr.style.transform = ''; };
  const go = async () => {
    busy = true;
    ptr.classList.add('busy'); ptr.style.opacity = '1'; ptr.style.transform = 'translateY(14px) scale(1)';
    ptr.querySelector('svg').style.transform = '';
    try {
      await Promise.all([fetch(location.href, { cache: 'reload' }), fetch(new URL('build.json', NFLE.root), { cache: 'reload' })]);
    } catch (e) { /* offline: the reload shows what the cache has */ }
    location.reload();
  };
  const start = (x, y, t) => { y0 = (busy || scrollY > 0 || blocked(t)) ? null : y; x0 = x; pull = 0; };
  const move = (x, y) => {
    if (y0 == null) return;
    const dy = y - y0, dx = x - x0;
    if (pull === 0 && Math.abs(dx) > Math.abs(dy)) { y0 = null; return; }  // a sideways swipe (tables, chips)
    if (dy <= 0 || scrollY > 0) { reset(); return; }
    pull = dy; draw();
  };
  const end = () => { if (y0 == null) return; y0 = null; if (pull >= TH) go(); else reset(); };
  addEventListener('touchstart', e => { if (e.touches.length === 1) start(e.touches[0].clientX, e.touches[0].clientY, e.target); else y0 = null; }, { passive: true });
  addEventListener('touchmove', e => { if (e.touches.length === 1) move(e.touches[0].clientX, e.touches[0].clientY); }, { passive: true });
  addEventListener('touchend', end, { passive: true });
  addEventListener('touchcancel', () => { y0 = null; reset(); }, { passive: true });
  NFLE.ptr = { start, move, end };  // tests drive it directly (Playwright WebKit has no multi-point touch drag)
})();

// Player finder (owner 2026-10-21: "a list that pops out ... when searching by name so it doesn't filter the list, just
// provides a list of most relevant players by their name/relevance"): a search box's matches drop down under it, the
// page's list stays as it is. Everyone on a roster is findable, projected this week or not (data/roster.json,
// tools/depth_build.py roster_directory: active, reserve lists, practice squads), plus the teams. A pick opens the
// card (the site's click rule, gamecast.js). Ranked by how well the name matches, then by fantasy relevance.
// Past players (owner 2026-10-21: "no tomlinson? ... a section for historical players, active players should have
// priority"): everyone with a career since 1999, in their own section under the current ones. Loaded per search, not
// up front (owner: "lazy load everything but the name/position/years active"): tools/stats_build.py write_finder_past
// files each player under every two-letter pair in his name, and a search fetches the file of its rarest pair
// (data/stats/finder_past/<pair>.json, ~2 KB typical), which holds every name containing it ("linson" finds Tomlinson).
// Players from it who played this season (linemen, defenders: not on the fantasy roster list) join the current ones.
// NFLE.finder(input, { value(pid) -> html for the right side (a page's own number, e.g. Rankings' points in your
// scoring), limit })
(() => {
  const NFLE = window.NFLE, esc = NFLE.esc;
  const norm = t => String(t || '').normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase().replace(/[.'’]/g, '').replace(/[^a-z0-9]+/g, ' ').trim();
  const TAG = { PS: 'Practice squad', IR: 'IR', PUP: 'PUP', NFI: 'NFI', SSPD: 'Suspended', SUSP: 'Suspended', HOLD: 'Holdout', RES: 'Reserve list' };  // SUSP: files before 2026-10-22
  let IDX = null;
  const index = () => IDX || (IDX = Promise.all([NFLE.week(), NFLE.load('data/roster.json').catch(() => null), NFLE.ui.ready]).then(([D, R]) => {
    const out = [], seen = new Set(), teams = (D && D.teams) || {};
    const playing = new Set(((D && D.games) || []).flatMap(g => [g.away.team, g.home.team]));
    const add = e => { if (!e.pid || seen.has(e.pid)) return; seen.add(e.pid); e.n = norm(e.name); e.t = e.n.split(' '); out.push(e); };
    Object.entries((D && D.players) || {}).forEach(([pid, p]) => add({ pid, name: p.name, pos: p.pos, team: p.team, photo: p.photo, status: p.status, inactive: p.inactive, proj: p.proj,
      rel: 1 + Math.min(1, (p.proj || 0) / 20) }));
    Object.entries(((D && D.rk) || {}).byes || {}).forEach(([pos, l]) => l.forEach(b => add({ pid: b.pid, name: b.name, pos, team: b.team, bye: true, fpg: b.fpg,
      rel: 0.9 + Math.min(1, (b.fpg || 0) / 20) })));
    if (R && R.rows) {
      const c = Object.fromEntries(R.cols.map((k, i) => [k, i]));
      R.rows.forEach(r => add({ pid: r[c.pid], name: r[c.name], pos: r[c.pos], team: r[c.team], tag: r[c.tag], espn: r[c.espn], dir: true,
        bye: D && D.games && !playing.has(r[c.team]), rel: r[c.tag] === 'PS' ? 0.2 : r[c.tag] ? 0.3 : 0.5 }));
    }
    Object.entries(teams).forEach(([t, i]) => { const e = { team: t, name: i.name || t, isTeam: true, rel: 1.5 };
      e.n = norm(`${i.name || ''} ${t}`); e.t = e.n.split(' '); out.push(e); });
    return { list: out, teams, season: D && D.season, have: new Set(out.map(e => e.pid)) };
  }));
  const PAIRS = {};  // pair -> parsed rows
  let PIDX = null;
  const pairIndex = () => PIDX || (PIDX = NFLE.load('data/stats/finder_past/index.json').then(j => j.n).catch(() => ({})));
  const pairsOf = q => [...new Set(q.split(' ').flatMap(w => [...Array(Math.max(0, w.length - 1)).keys()].map(i => w.slice(i, i + 2))))];
  // a search's past players: { old (before this season), now (played this season, not on a fantasy roster) }
  const pastFor = q => Promise.all([index(), pairIndex()]).then(([cur, n]) => {
    const ps = pairsOf(q);
    if (!ps.length || ps.some(p => !n[p])) return { old: [], now: [] };  // a pair no name has: no past match
    const k = ps.reduce((a, b) => (n[a] <= n[b] ? a : b));
    return (PAIRS[k] || (PAIRS[k] = NFLE.load(`data/stats/finder_past/${k}.json`).then(j => String(j.d || '').split('\n').map(line => {
      const [id, name, pos, a, b, w, hof] = line.split('|'), nn = norm(name);
      return { pid: /^\d{5}$/.test(id) ? `00-00${id}` : id, name, pos, first: +a, last: +b, w: +w / 9, hof: hof ? +hof : 0, n: nn, t: nn.split(' ') };
    })).catch(() => { delete PAIRS[k]; return []; }))).then(rows => {
      const old = [], now = [];
      rows.forEach(r => { if (cur.have.has(r.pid)) return;
        if (cur.season && r.last >= cur.season) now.push({ ...r, rel: 0.4 * r.w, years: true });
        else old.push({ ...r, rel: r.w, years: true, past: true }); });
      return { old, now };
    });
  });
  // how well a name matches: a name word starting with it (first or last name alike; relevance breaks the tie: "brady"
  // is Tom Brady before Brady Poppinga), every word of it starting a name word, or anywhere inside ("linson")
  const matchScore = (e, q, qt) => {
    if (e.n.startsWith(q)) return 4;
    if (e.isTeam && e.t.includes(q)) return 4;  // "phi", "eagles"
    if (qt.length === 1 && e.t.some(w => w.startsWith(q))) return 4;
    if (qt.every(x => e.t.some(w => w.startsWith(x)))) return 3;
    if (q.length >= 3 && e.n.replace(/ /g, '').includes(q.replace(/ /g, ''))) return 1;
    return 0;
  };
  const right = (e, opts) => {
    const v = !e.isTeam && opts.value ? opts.value(e.pid) : '';
    if (v) return v;
    if (e.isTeam) return '<span class="muted">Team</span>';
    if (e.years) return `<span class="fnd-tag">${e.first === e.last ? e.first : `${e.first}-${e.last}`}</span>`;
    if (e.tag) return `<span class="fnd-tag">${esc(TAG[e.tag] || e.tag)}</span>`;
    if (e.bye) return `<span class="fnd-tag">Bye${e.fpg ? ` · ${(Math.round(e.fpg * 10) / 10).toFixed(1)} FP/G` : ''}</span>`;
    if (e.proj != null) return `<b>${(Math.round(e.proj * 10) / 10).toFixed(1)}</b>`;
    return '<span class="muted">Not projected</span>';
  };
  NFLE.finder = (input, opts = {}) => {
    const limit = opts.limit || 8;
    const host = input.parentElement;
    host.classList.add('fnd-host');
    const pop = document.createElement('div');
    pop.className = 'fnd-pop'; pop.hidden = true; pop.setAttribute('role', 'listbox');
    pop.id = `fnd-${Math.random().toString(36).slice(2, 8)}`;
    input.setAttribute('aria-controls', pop.id); input.setAttribute('aria-autocomplete', 'list'); input.setAttribute('autocomplete', 'off');
    host.appendChild(pop);
    let act = 0, seq = 0, pastT = 0;
    const close = () => { pop.hidden = true; input.setAttribute('aria-expanded', 'false'); };
    const mark = () => pop.querySelectorAll('.fnd-r').forEach((r, i) => r.classList.toggle('on', i === act));
    const draw = () => {
      const q = norm(input.value), my = ++seq;
      if (!q) { close(); return; }
      const qt = q.split(' ');
      const best = (list, n) => list.map(e => { const m = matchScore(e, q, qt); return m ? [m * 10 + e.rel, e] : null; }).filter(Boolean)
        .sort((a, b) => b[0] - a[0]).slice(0, n).map(x => x[1]);
      const row = (e, teams) => e.isTeam
        ? `<div class="fnd-r tm-open" role="option" data-tm="${esc(e.team)}">${NFLE.ui.team(e.team, teams, esc(e.team))}<span class="fnd-v">${right(e, opts)}</span></div>`
        : `<div class="fnd-r" role="option" data-open-pid="${esc(e.pid)}">${NFLE.ui.player({ name: e.name, team: e.team, pos: e.pos, photo: e.photo, espn: e.espn, pid: e.pid,
            badges: e.hof ? `<span class="hof-b" title="Pro Football Hall of Fame, class of ${e.hof}">HOF</span>` : NFLE.injTag && !e.past ? NFLE.injTag(e.status || '', e.inactive, e.pid) : '' }, teams)}<span class="fnd-v">${right(e, opts)}</span></div>`;
      // current players first, then past ones once their list is in (a second paint, same keystroke)
      const paint = (cur, old, teams, done) => {
        if (my !== seq) return;  // a newer keystroke
        const keep = pop.querySelector('.fnd-r.on'), was = keep ? keep.dataset.openPid || keep.dataset.tm : null;
        pop.innerHTML = (cur.length ? cur.map(e => row(e, teams)).join('') : '')
          + (old.length ? `<div class="fnd-sec" role="presentation">Past players</div>${old.map(e => row(e, teams)).join('')}` : '')
          || (done ? '<div class="fnd-none muted">No player or team by that name</div>' : '<div class="fnd-none muted">Searching...</div>');
        const rows = [...pop.querySelectorAll('.fnd-r')], i = rows.findIndex(r => (r.dataset.openPid || r.dataset.tm) === was);
        act = i >= 0 ? i : 0;
        pop.hidden = false; input.setAttribute('aria-expanded', 'true'); mark();
      };
      index().then(({ list, teams }) => {
        paint(best(list, limit), [], teams, false);
        // past players once typing pauses: one small file per search, not one per keystroke
        clearTimeout(pastT);
        pastT = setTimeout(() => pastFor(q).then(({ old, now }) => { const cur = best(list.concat(now), limit);
          paint(cur, best(old, cur.length ? Math.max(3, limit - cur.length) : limit), teams, true); }), 150);
      });
    };
    input.addEventListener('input', draw);
    input.addEventListener('focus', () => { pairIndex(); if (input.value.trim()) draw(); });
    input.addEventListener('keydown', e => {
      const rows = pop.querySelectorAll('.fnd-r');
      if (e.key === 'Escape') { close(); return; }
      if (pop.hidden || !rows.length) return;
      if (e.key === 'ArrowDown' || e.key === 'ArrowUp') { e.preventDefault(); act = (act + (e.key === 'ArrowDown' ? 1 : rows.length - 1)) % rows.length; mark(); }
      else if (e.key === 'Enter') { e.preventDefault(); rows[act].click(); }
    });
    // a pick: the click rule opens the card; the list closes and the keyboard goes away
    pop.addEventListener('click', e => { if (e.target.closest('.fnd-r')) setTimeout(() => { close(); input.blur(); }); });
    pop.addEventListener('mousedown', e => e.preventDefault());  // keep focus in the box while picking
    document.addEventListener('pointerdown', e => { if (!pop.hidden && !host.contains(e.target)) close(); });
    return { close, refresh: draw };
  };
})();

// A clear X in every text box (owner 2026-10-21: "a little X to display inline on the right to clear the input easily
// rather than forcing user to backspace the whole thing"): drawn by ui.css in the box's right padding whenever it has
// text (its placeholder is hidden; a box without one gets a blank one), so no markup changes anywhere. A tap on it
// empties the box and fires the box's own input / change handlers (filters reset, the finder closes) without moving
// the caret or dropping the keyboard.
(() => {
  const SEL = 'input[type="search"], input[type="text"], input:not([type])';
  const ZONE = 32;  // px from the right edge: the X and its padding (ui.css)
  const box = t => (t && t.matches && t.matches(SEL) && !t.disabled && !t.readOnly && t.value ? t : null);
  const clearHit = e => { const el = box(e.target); if (!el) return null; const r = el.getBoundingClientRect();
    return e.clientX >= r.right - ZONE && e.clientX <= r.right ? el : null; };
  document.addEventListener('focusin', e => { if (e.target.matches && e.target.matches(SEL) && !e.target.hasAttribute('placeholder')) e.target.setAttribute('placeholder', ' '); });
  document.addEventListener('pointerdown', e => {
    const el = clearHit(e); if (!el) return;
    e.preventDefault();  // no caret jump, the keyboard stays as it was
    el.value = '';
    el.dispatchEvent(new Event('input', { bubbles: true }));
    el.dispatchEvent(new Event('change', { bubbles: true }));
  }, true);
  // a desktop pointer over the X is a pointer, not a text cursor
  document.addEventListener('mousemove', e => { if (e.target.matches && e.target.matches(SEL)) e.target.style.cursor = clearHit(e) ? 'pointer' : ''; });
})();
