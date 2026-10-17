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
  NFLE.fmt = {
    signed1: v => `${v >= 0 ? '+' : '-'}${Math.abs(v).toFixed(1)}`,  // a change in points: +0.9 / -0.7
    // Availability is shown one way everywhere (owner 2026-10-17): his chance to PLAY, "62%"; never the chance to sit
    toPlay: inactive => { const p = 1 - (inactive || 0); return p > 0.995 ? '&gt;99%' : p < 0.005 ? '&lt;1%' : `${Math.round(p * 100)}%`; },
    // kickoff (ms) of a team's game in a week's games: gameday + gametime are Eastern (EDT mid-March to early November)
    kickoff: (games, t) => { const g = (games || []).find(x => x.away.team === t || x.home.team === t);
      if (!g || !g.gameday || !g.gametime) return null; const m = +g.gameday.slice(5, 7), d = +g.gameday.slice(8, 10);
      const edt = (m > 3 && m < 11) || (m === 3 && d >= 9) || (m === 11 && d < 3); return Date.parse(`${g.gameday}T${g.gametime}:00${edt ? '-04:00' : '-05:00'}`); },
    f1, logoSrc,
    sgn: v => v == null || isNaN(v) ? '' : Math.abs(v) < 0.05 ? '0.0' : `${v > 0 ? '+' : ''}${f1(v)}`,
    pct: v => v == null || isNaN(v) ? '' : `${Math.round(v * 100)}%`,
    ord: n => !n ? '' : `${n}${n % 100 >= 10 && n % 100 <= 20 ? 'th' : ({ 1: 'st', 2: 'nd', 3: 'rd' }[n % 10] || 'th')}`,
    rkc: n => n <= 8 ? 'rk1' : n <= 16 ? 'rk2' : n <= 24 ? 'rk3' : 'rk4',  // league-rank badge color (top 8 green ... bottom 8 red)
    posb: p => ['QB', 'RB', 'WR', 'TE', 'K', 'DST'].includes(p) ? `<span class="posb posb-${esc(p)}">${esc(p)}</span>` : esc(p),
    short: n => { const i = String(n).indexOf(' '); return i < 0 ? String(n) : String(n).slice(i + 1); },  // 'Josh Allen' -> 'Allen'
    // [first, last] for two-line names (owner 2026-10-17): 'Amon-Ra St. Brown' -> ['Amon-Ra', 'St. Brown'],
    // 'Marvin Harrison Jr.' -> ['Marvin', 'Harrison Jr.']; one word -> ['', word]
    split: n => { const s = String(n || '').trim(), i = s.indexOf(' '); return i < 0 ? ['', s] : [s.slice(0, i), s.slice(i + 1)]; },
    // team logo on its picked background, and a row's team trim (--tc / --tc2), from the week data's teams map
    logo: (teams, t, size = 18) => { const i = (teams || {})[t] || {}; return i.logo ? `<span class="logo" style="background:${esc(i.logo_bg || '#333')}"><img src="${esc(logoSrc(i.logo, size))}" alt="${esc(t)}" width="${size}" height="${size}" loading="lazy"></span>` : ''; },
    rowStyle: (teams, t) => { const i = (teams || {})[t] || {}; return `--tc:${i.color || '#666'};--tc2:${i.color2 || '#999'};--tfg:#ffffff`; },
    // a player photo circle in his team's colors: primary fill, secondary ring (owner 2026-10-16)
    picStyle: (teams, t) => { const i = (teams || {})[t] || {}; return i.color ? ` style="--pc1:${i.color};--pc2:${i.color2 || i.color}"` : ''; },
  };
  // One look everywhere (owner 2026-10-14): every list of players or teams is a row of team-colored tiles (table cls
  // 'tiles', row class 'teamrow', row style from tileStyle) with the same name cell, and every matchup is the Games
  // tab's tile. Teams map = the week data's (NFLE.week() -> D.teams: logo, logo_bg, color, color2, nick).
  const F = NFLE.fmt;
  NFLE.ui = {
    headshot: espn => espn ? `https://a.espncdn.com/i/headshots/nfl/players/full/${encodeURIComponent(espn)}.png` : '',
    ids: {},  // gsis -> ESPN id (data/espn_ids.json, tools/stats_build.py): a headshot for any list with a player id
    tileStyle: (teams, t) => `style="${F.rowStyle(teams, t)}"`,
    // A team name or logo that opens the team page (owner 2026-10-16: every one on the site, except the small logo on
    // a player's photo). html: what to show (default: the abbreviation).
    tm: (t, html, cls = '') => t ? `<span class="tm-open${cls ? ` ${cls}` : ''}" data-tm="${esc(t)}">${html == null ? esc(t) : html}</span>` : (html || ''),
    // p: { name, team, pos, grp (badge color group), photo | espn | pid, sub (default: team, linked) | subHtml, badges }
    player: (p, teams) => {
      const photo = p.photo || NFLE.ui.headshot(p.espn || (p.pid && NFLE.ui.ids[p.pid]));
      const pic = photo
        ? `<span class="pic"${F.picStyle(teams, p.team)}><span class="pic-img"><img src="${esc(photo)}" alt="" width="34" height="34" loading="lazy" onerror="this.closest('.pic').classList.add('nopic')"></span><span class="pic-tm">${F.logo(teams, p.team, 11)}</span></span>`
        : NFLE.ui.tm(p.team, F.logo(teams, p.team, 26));
      const pos = p.pos ? `<span class="posb posb-${esc(p.grp || p.pos)}">${esc(p.pos)}</span> ` : '';
      const sub = p.subHtml != null ? p.subHtml : p.sub != null ? esc(p.sub) : NFLE.ui.tm(p.team);
      // two lines (owner 2026-10-17): first name with the small details (position, team) on top, last name below,
      // badges to the right; narrower than "full name / details", and each line truncates when the table scrolls
      const [first, last] = F.split(p.name);
      return `<div class="who">${pic}<div class="nmw nm2w"><span class="nm2"><span class="l1">${first ? `<span class="fnm">${esc(first)}</span> ` : ''}${pos}<span class="sub">${sub}</span></span><b class="nm l2">${esc(last)}</b></span>${p.badges ? `<span class="nm-b">${p.badges}</span>` : ''}</div></div>`;
    },
    // a team: logo, nickname, sub line (default "KC")
    team: (t, teams, sub, extra = '') => {
      const i = (teams || {})[t] || {};
      return `<div class="who">${F.logo(teams, t, 26)}<div><b>${esc(i.nick || t)}</b>${extra}<span class="sub">${sub == null ? esc(t) : sub}</span></div></div>`;
    },
    // the Games tab's matchup tile: logos outside, team colors blending, win chance (score once it starts); live
    // games are repainted by gamecast.js (NFLE.paintTiles finds tiles by data-gid wherever they are)
    matchTile: (g, href) => {
      // the team's wordmark (owner 2026-10-17, as on All teams: tools/wordmarks_build.py), the typed nickname if it fails
      // the line in words (owner 2026-10-17): "JAX -2.5" -> "JAX by 2.5", "PK" -> "pick'em"
      const vegas = l => { const m = /^([A-Z]{2,3}) -(\d+(?:\.\d)?)$/.exec(l || '');
        return m ? `<b>${esc(m[1])} by ${+m[2]}</b>` : l === 'PK' ? "<b>pick'em</b>" : `<b>${esc(l)}</b>`; };
      const wordmark = s => `<img class="mt-wm" src="${esc(NFLE.root || '')}assets/wordmarks/${esc(s.team)}.png" alt="${esc(s.nick)}" onerror="this.replaceWith(this.alt)">`;
      const f = g.fc || {}, fin = g.final;
      const sides = [[g.away, fin && fin.away, fin && fin.home, f.p_away], [g.home, fin && fin.home, fin && fin.away, f.p_home]];
      const T = NFLE.ui.tm;
      const verdict = !fin ? '' : !fin.winner ? '<span class="gf-pick toss">Tie</span>'
        : f.tossup ? `<span class="gf-pick toss">Tossup &middot; ${T(fin.winner)} won</span>`
          : fin.fav_won ? `<span class="gf-pick ok">Favorite won &middot; ${f.pct}%</span>`
            : `<span class="gf-pick miss">Upset &middot; a ${100 - f.pct}% chance</span>`;
      const main = sides.map(([s, sc, os, pct], i) => {
        const side = i ? 'home' : 'away';
        const cls = `${fin && sc < os ? ' lost' : ''}${fin && sc > os ? ' won' : ''}${!fin && !f.tossup && pct < 50 ? ' dog' : ''}`;
        // the logo's visible edge (outside the score / name, which sit above it) and the name open the team page
        return `${s.logo_url ? `<img class="mt-lg ${side} tm-open" data-tm="${esc(s.team)}" src="${esc(F.logoSrc(s.logo_url, 112))}" alt="" loading="lazy">` : ''}
          <div class="mt-side ${side}${cls}"><span class="mt-num">${fin ? esc(sc) : `${esc(pct)}<small>%</small>`}</span>
            <span class="mt-nm">${T(s.team, `<b>${wordmark(s)}</b>`)} <small>${esc(s.record)}</small></span></div>
          ${i ? '' : `<span class="mt-at">${g.neutral ? 'vs' : '@'}${f.tossup && !fin ? '<small>Tossup</small>' : ''}</span>`}`;
      }).join('');
      // when (owner 2026-10-17): kickoff / Final / the live clock at the top middle; the footer keeps the rest
      const when = fin ? '<span class="mt-fin">Final</span>' : `${esc(g.kickoff)}${g.neutral ? ' &middot; neutral' : ''}`;
      const st = fin ? verdict
        // the Vegas line when there is one (owner 2026-10-17: then no "ours", the big win chances above are ours); before
        // a line is posted, our pick in its place
        : g.vegas_line ? `<span class="mt-odds">Vegas: ${vegas(g.vegas_line)}</span>`
          : f.model_fav || f.model_tossup ? `<span class="mt-odds" title="${esc(f.model_why || '')}">No Vegas line yet &middot; ours ${f.model_tossup ? 'tossup' : `<b>${T(f.model_fav)} ${esc(f.model_pct)}%</b>`}</span>` : '';
      return `<a class="mt ${fin ? 'is-final' : 'is-pre'}${f.tossup && !fin ? ' toss' : ''}" data-gid="${esc(g.id)}" href="${esc(href || (NFLE.gameHref ? NFLE.gameHref(g) : '#'))}" style="${esc(g.bt_style || '')}">
        <div class="mt-main"><div class="mt-when">${when}</div>${main}</div><div class="mt-st">${st}</div></a>`;
    },
  };
  // lists that show players by id wait for this (with NFLE.week()) before drawing, so their rows come up with faces.
  // Fetched on first use, not on every page load: 77 KB the landing Rankings page doesn't need (its players carry
  // their ESPN ids), and it competed with index.json for the first paint (Lighthouse 2026-10-16).
  let idsP = null;
  Object.defineProperty(NFLE.ui, 'ready', { get: () => idsP || (idsP = NFLE.load('data/espn_ids.json').then(m => { NFLE.ui.ids = m || {}; }).catch(() => {})) });
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
    b.onclick = () => location.reload();
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
  NFLE.week().then(D => {
    if (!D || !D.head) return;
    const h = D.head, live = !(CFG.archive || CFG.lookahead), pending = live && !h.injury_report;
    const sc = h.scoring === 'half' ? 'Half PPR' : h.scoring === 'ppr' ? 'PPR' : String(h.scoring || '').replace(/^./, c => c.toUpperCase());
    hw.querySelector('.hpop').innerHTML = [
      // two different weeks (owner 2026-10-17 read them as one): what the projections are built on, and how far
      // this week's own games have got (a live week's projections use only earlier weeks, as before kickoff)
      `<span>Projections use games through <b>week ${esc(h.data_week)}</b>${CFG.lookahead ? ' (all games played so far)' : ''}</span>`,
      h.n_final ? `<span>Week ${esc(D.week)} so far: <b>${h.n_final} of ${h.n_games}</b> games final</span>` : '',
      `<span>Scoring <b id="scoreName">${esc(sc)}</b></span>`,
      pending ? '<span class="alert">Injury report pending: last week\'s statuses (and early ESPN injury news) are used</span>' : live ? '<span>Injury report <b>in</b></span>' : '',
      `<span>Updated ${esc(D.generated || '')}</span>`].join('');
    hb.classList.toggle('warn', pending);
    hw.hidden = false;
  });
  hb.addEventListener('click', e => { e.stopPropagation(); const on = hw.classList.toggle('open'); hb.setAttribute('aria-expanded', on); });
  document.addEventListener('click', e => { if (!hw.contains(e.target)) { hw.classList.remove('open'); hb.setAttribute('aria-expanded', 'false'); } });
})();
(() => {
  // Four parents (owner, 2026-10-14): Players (incl. transactions = player news) and Teams (incl. playoffs, draft).
  const NAV = [
    { key: 'players', label: 'Players', subs: [['rankings', 'Rankings', 'tab-players'], ['stats', 'Stats'], ['roles', 'Roles', 'tab-roles'], ['injuries', 'Injuries'], ['moves', 'Moves'], ['trends', 'Trends']] },
    { key: 'teams', label: 'Teams', subs: [['all', 'All teams'], ['power', 'Power', 'tab-power'], ['standings', 'Standings'], ['playoffs', 'Playoffs'], ['stats', 'Stats'], ['draft', 'Draft']] },
    { key: 'games', label: 'Games', subs: [['matchups', 'Matchups', 'tab-games']] },
    // your own fantasy league (Sleeper / public ESPN import; owner 2026-10-15)
    { key: 'league', label: 'Fantasy', subs: [['league', 'My League', 'tab-league']] },  // tab named Fantasy (owner 2026-10-16)
    { key: 'model', label: 'Model', subs: [['model', 'Model', 'tab-model']] },
  ];
  // Client-rendered tabs: section id -> area module (assets/<area>.js + .css), loaded the first time the tab opens.
  // A module registers NFLE.areas[<area>] = { mount(section) } and renders into its section.
  const AREAS = { 'tab-teams-all': 'teamgrid', 'tab-teams-standings': 'standings', 'tab-teams-stats': 'teamstats', 'tab-players-stats': 'playerstats',
                  'tab-players-injuries': 'injuries', 'tab-players': 'rankings', 'tab-teams-draft': 'draft',
                  'tab-teams-playoffs': 'playoffs', 'tab-players-moves': 'moves', 'tab-power': 'power',
                  'tab-games': 'matchups', 'tab-roles': 'roles', 'tab-model': 'model',
                  'tab-players-trends': 'trends', 'tab-league': 'league' };
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
               playoffs: 'teams/playoffs', draft: 'teams/draft', transactions: 'players/moves' };
  const CARD = /^g-/;  // old matchup-tile links: gamecast.js turns them into gamecast links
  const PAGE = /^(player|team)\/(.+)$/;  // player / team cards (rendered by gamecast.js into #pcOv)
  const nav = document.querySelector('nav.tabs');
  const main = document.querySelector('main .wrap');
  // Pages without the tab bar (game.html) still run the cards (owner 2026-10-17: a player tapped in the gamecast opened
  // over the Players tab of another page): the card opens over the page itself and closing returns to it.
  const listless = !nav || !main;
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
  if (!listless) nav.innerHTML = `<div class="wrap nav-par" role="tablist">${NAV.map(p => `<button type="button" role="tab" data-par="${p.key}">${p.short
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
  const navMode = NAV_MODE;
  const BOTTOM = NAV.map(p => p.key);  // all five parents fit: no More sheet
  let bot = null;
  if (navMode === 'bottom' && !listless) {
    document.documentElement.classList.add('nav-bottom');
    // the page's first-paint copy (pages/week.html) when there is one; older archived pages have none
    bot = document.querySelector('body > .botbar') || document.createElement('div');
    bot.className = 'botbar';
    bot.removeAttribute('aria-hidden');
    const extra = NAV.filter(p => !BOTTOM.includes(p.key));  // parents beyond the bar go in a More sheet (none today)
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
  const showUnder = d => { const s = snaps[d - 1]; under.replaceChildren(); under.hidden = !s; cardOv.classList.toggle('pc-stacked', !!s);
    if (s) { under.appendChild(s.el); s.el.querySelector('.pc').scrollTop = s.top; } };
  const hideCard = () => { cardOv.hidden = true; document.documentElement.classList.remove('pc-open'); onPage = false; depth = 0;
    snaps.length = 0; showUnder(0); settle(); };
  const settle = () => { cardWrap.style.transition = 'none'; cardWrap.style.transform = ''; };
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
  }, { passive: false });
  cardBox.addEventListener('touchend', () => {
    if (dmode !== 'drag') { dmode = null; return; }
    dmode = null;
    const dy = dlast - dy0;
    cardWrap.style.transition = 'transform .22s var(--ease)';
    if (dy > 0.25 * cardWrap.offsetHeight || dv > 0.6) {
      cardWrap.style.transform = 'translateY(100%)';
      setTimeout(closeCard, 210);  // it stays off screen until the card below renders or the overlay hides (settle)
    } else cardWrap.style.transform = '';
  });
  // a card opened on a card slides up over it (the first one animates from CSS as the overlay appears)
  const playIn = () => { cardWrap.style.animation = 'none'; void cardWrap.offsetWidth; cardWrap.style.animation = ''; };
  cardOv.addEventListener('click', e => { if (e.target === cardOv || e.target.closest('.pc-x')) closeCard(); });
  document.addEventListener('keydown', e => { if (e.key === 'Escape' && !cardOv.hidden && !document.querySelector('.sheet-ov, .zoom-ov')) closeCard(); });
  const showPage = (kind, id) => {
    // a direct link has no list behind it: a team card opens over Teams, a player card over Players
    if (!lastRoute && !listless) { const home = kind === 'team' ? 'teams' : 'players'; show(parse(home), false); deep = true; }
    const fresh = !onPage;  // opened from a list (not card-to-card): the card starts on this page's week
    const fn = kind === 'player' ? NFLE.showPlayer : NFLE.showTeam;
    // depth of this card: its history entry's (Back / Forward), else one deeper than the open card
    const st = history.state && history.state.nfleCard, was = cardOv.hidden ? 0 : depth, d = st || was + 1;
    let top = 0;
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
    main.querySelectorAll(':scope > section').forEach(x => x.classList.toggle('on', x.id === id));
    const route = r.p.subs.length < 2 ? r.p.key : `${r.p.key}/${r.s[0]}`;
    try { localStorage.setItem('nfledge-tab', route); } catch (e) { /* private mode */ }
    if (push && location.hash.slice(1) !== route) { try { history.replaceState(null, '', '#' + route); } catch (e) { /* file:// */ } }
    if (NFLE.placeBar) NFLE.placeBar();  // the chip row comes and goes with the parent: re-measure the bar
    lastRoute = r; onPage = false;
    mountArea(id);
    if (scrolls[id] != null) requestAnimationFrame(() => window.scrollTo({ top: scrolls[id] }));  // back from a page
    document.dispatchEvent(new CustomEvent('nfle-route', { detail: { parent: r.p.key, sub: r.s[0], section: id } }));
  };
  const onNav = e => {
    const pb = e.target.closest('[data-par]'), sb = e.target.closest('[data-sub]');
    if (bot && e.target.closest('[data-more]')) { const sh = bot.querySelector('.bb-sheet'); sh.hidden = !sh.hidden; return; }
    if (pb) {  // a parent tab reopens the sub-tab you last used there
      const p = parent(pb.dataset.par);
      let last = null; try { last = localStorage.getItem(`nfledge-sub-${p.key}`); } catch (e) { /* ignore */ }
      show({ p, s: p.subs.find(x => x[0] === last) || p.subs[0] }, true);
      window.scrollTo({ top: 0 });
    } else if (sb) {
      const p = parent(nav.querySelector('[data-par].on').dataset.par);
      const s = p.subs.find(x => x[0] === sb.dataset.sub);
      try { localStorage.setItem(`nfledge-sub-${p.key}`, s[0]); } catch (e) { /* ignore */ }
      show({ p, s }, true);
    }
  };
  if (!listless) nav.addEventListener('click', onNav);
  if (bot) {
    bot.addEventListener('click', onNav);
    document.addEventListener('click', e => { const sh = bot.querySelector('.bb-sheet'); if (sh && !bot.contains(e.target)) sh.hidden = true; });
  }
  const route = (h, push) => {
    const m = (h || '').replace(/^#/, '').match(PAGE);
    if (m) { showPage(m[1], m[2]); return true; }
    if (listless) { hideCard(); deep = false; return true; }  // the card's entry left: the page itself
    const r = parse(h);
    if (r) { const back = !cardOv.hidden && lastRoute && r.p === lastRoute.p && r.s === lastRoute.s;
      hideCard(); deep = false;
      if (!back) show(r, push);  // closing a card over the same list leaves it as it was (scroll included)
      return true; }
    return false;
  };
  window.addEventListener('hashchange', () => route(location.hash, false));
  let saved = null; try { saved = localStorage.getItem('nfledge-tab'); } catch (e) { /* ignore */ }
  // A card link opened directly: over the tab you last used in that section (Teams for a team, Players for a player)
  if (listless) {
    if (PAGE.test(location.hash.slice(1))) { deep = true; route(location.hash, false); }
  } else if (PAGE.test(location.hash.slice(1))) {
    const sec = location.hash.slice(1).startsWith('team/') ? 'teams' : 'players';
    show((saved && saved.startsWith(sec) ? parse(saved) : null) || parse(sec), false);
    deep = true;
    route(location.hash, false);
  }
  else show(parse(location.hash) || parse(saved) || parse('players'), !CARD.test(location.hash.slice(1)));
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
// Kicker and D/ST scoring from data/kdst.json lines (tools/kdst_build.py): shared by Rankings and the Fantasy tab.
// STD = standard ESPN scoring, the rules both models were tested on (nfledge/kickers.py STANDARD, defenses.py ESPN_STD).
(() => {
  const NFLE = window.NFLE = window.NFLE || {};
  const DSTAT = ['sack', 'int', 'fum_rec', 'ff', 'def_td', 'st_td', 'safe', 'blk', 'pass_def', 'tkl_loss', 'forced_punts', 'def_2pt'];
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
