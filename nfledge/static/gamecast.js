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
  const f1 = v => (v == null || isNaN(v)) ? '' : (Math.round(v * 10) / 10).toFixed(1);
  const f0 = v => (v == null || isNaN(v)) ? '' : String(Math.round(v));
  const pc = v => `${Math.round(v * 100)}%`;
  const ord = n => n ? `${n}${(n % 100 >= 11 && n % 100 <= 13) ? 'th' : ({ 1: 'st', 2: 'nd', 3: 'rd' }[n % 10] || 'th')}` : '';
  const el = (html) => { const t = document.createElement('template'); t.innerHTML = html.trim(); return t.content.firstChild; };
  // Plain GETs only: a cache-mode option makes Chromium add Cache-Control / Pragma request headers, which turns the
  // request into a CORS preflight that ESPN's feed does not answer (WebKit is fine either way). ESPN's own
  // max-age is 1-9 s, so the browser cache never holds live data for long.
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
  const logo = (url, bg, size = 22, alt = '') => url
    ? `<span class="nl" style="background:${esc(bg || '#333')};width:${size + 6}px;height:${size + 6}px"><img src="${esc(url)}" alt="${esc(alt)}" width="${size}" height="${size}" loading="lazy"></span>` : '';

  // ------------------------------------------------------------------------------------------------------- ESPN
  const weekEvents = async (season, week) => {
    const d = await getJSON(`${ESPN.sb}?seasontype=2&week=${week}&dates=${season}`);
    return d.events || [];
  };
  const evKey = ev => ev.competitions[0].competitors.map(t => ourCode(t.team.abbreviation)).sort().join('-');
  const gKey = (a, h) => [a, h].sort().join('-');
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
  const newsHtml = items => !items.length ? '<p class="pc-sub">No news in the last 60 days.</p>'
    : `<ol class="nw">${items.slice(0, 6).map(a => {
        const story = String(a.story || a.description || '').replace(/<[^>]+>/g, '').trim();
        const long = story.length > 260;
        return `<li class="nw-i${Date.now() - new Date(a.published).getTime() < 86400000 ? ' fresh' : ''}">
          <div class="nw-t">${esc(ago(a.published))}${a.type ? ` · ${esc(a.type === 'Rotowire' ? 'RotoWire' : a.type)}` : ''}</div>
          <div class="nw-h">${esc(a.headline || '')}</div>
          ${story ? `<div class="nw-s${long ? ' clip' : ''}">${esc(story)}</div>${long ? '<button type="button" class="nw-more">More</button>' : ''}` : ''}</li>`;
      }).join('')}</ol><div class="nw-src">Player news by RotoWire, via ESPN's public feed.</div>`;
  const loadNews = async (espn, box) => {
    const hit = NEWS[espn];
    if (hit && Date.now() - hit.t < 300000) { box.innerHTML = newsHtml(hit.items); wireNews(box); return; }
    box.innerHTML = '<p class="pc-sub">Loading news&hellip;</p>';
    try {
      const d = await getJSON(`https://site.web.api.espn.com/apis/fantasy/v2/games/ffl/news/players?days=60&playerId=${encodeURIComponent(espn)}`);
      const items = (d.feed || []).filter(a => a.headline).sort((a, b) => new Date(b.published) - new Date(a.published));
      NEWS[espn] = { t: Date.now(), items };
      if (box.isConnected) { box.innerHTML = newsHtml(items); wireNews(box); }
    } catch (e) { if (box.isConnected) box.innerHTML = '<p class="pc-sub">News unavailable right now.</p>'; }
  };
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
  const logCols = (pos, rushy) => {
    const c = (g, i) => g.c[i], x = (g, i) => g.x[i];
    const ypc = g => x(g, 2) ? (c(g, 3) / x(g, 2)).toFixed(1) : '';
    if (pos === 'QB') return [['Passing', [['C/A', g => `${x(g, 0)}/${x(g, 1)}`], ['Yd', g => f0(c(g, 0))], ['TD', g => c(g, 1)], ['Int', g => c(g, 2)]]],
                              ['Rushing', [['Att', g => x(g, 2)], ['Yd', g => f0(c(g, 3))], ['TD', g => c(g, 4)]]]];
    const rec = ['Receiving', [['Tgt', g => x(g, 3)], ['Rec', g => c(g, 5)], ['Yd', g => f0(c(g, 6))], ['TD', g => c(g, 7)]]];
    const rush = ['Rushing', [['Att', g => x(g, 2)], ['Yd', g => f0(c(g, 3))], ['YPC', ypc], ['TD', g => c(g, 4)]]];
    return pos === 'RB' ? [rush, rec] : rushy ? [rec, ['Rushing', [['Att', g => x(g, 2)], ['Yd', g => f0(c(g, 3))], ['TD', g => c(g, 4)]]]] : [rec];
  };
  const logHtml = (L, p) => {
    const w = weights(), built = (DATA && DATA.score && DATA.score.built) || HALF, pos = L.pos || (p && p.pos);
    const all = L.seasons.flatMap(s => s.g);
    const rushy = pos !== 'QB' && pos !== 'RB' && all.reduce((t, g) => t + g.x[2], 0) >= 8;
    const groups = logCols(pos, rushy), stat = groups.flatMap(gr => gr[1]);
    const lg = league(), need = (lg.teams || 10) * Math.max(1, lg[pos] || 1);
    const rkClass = r => r <= need ? 'rk-good' : r <= 2 * need ? 'rk-mid' : 'rk-bad';
    const projOf = g => g.pjl ? g.pj * (pts(g.pjl, w, pos) / Math.max(0.1, pts(g.pjl, built, pos))) : null;
    const opp = g => `<td class="lg-opp tm-opp ${mrClass(g.mr)}"${g.mr ? ` title="Our pregame matchup rank: ${ord(g.mr)} of 32 vs ${esc(pos)}s (1st = toughest)"` : ''}><button type="button" class="tm-open" data-tm="${esc(g.o)}">${g.h === 0 ? '@' : ''}${esc(g.o)}</button></td>`;
    const head = `<tr class="lg-gh"><th colspan="6"></th>${groups.map(([n, cols]) => `<th colspan="${cols.length}" class="lg-grp">${n}</th>`).join('')}</tr>
      <tr class="lg-ch"><th>Wk</th><th>Opp</th><th class="num">Pts</th><th class="num">Proj</th><th class="num">Rank</th><th class="num">Snap</th>${stat.map(([n]) => `<th class="num">${n}</th>`).join('')}</tr>`;
    const blank = `<td class="num">–</td>`.repeat(stat.length);
    const body = L.seasons.map(S => {
      const isCur = S.s === L.cur, rows = S.g.map(g => ({ w: g.w, g }));
      if (isCur) (L.up || []).forEach(u => rows.push({ w: u.w, u }));
      rows.sort((a, b) => a.w - b.w);
      const fps = S.g.map(g => pts(g.c, w, pos)), fpg = fps.length ? fps.reduce((a, b) => a + b, 0) / fps.length : 0;
      const team = S.g.length ? S.g[S.g.length - 1].t : '';
      const trs = rows.map(r => {
        if (r.u && r.u.bye) return `<tr class="lg-bye"><td>${r.w}</td><td colspan="${5 + stat.length}">Bye</td></tr>`;
        if (r.u) {
          const pj = projOf(r.u);
          return `<tr class="lg-up"${tileAttrs(r.u)}><td>${r.w}</td>${opp(r.u)}<td class="num">–</td><td class="num">${pj != null ? f1(pj) : '–'}</td><td class="num">–</td><td class="num">–</td>${blank}</tr>`;
        }
        const g = r.g, v = pts(g.c, w, pos), pj = projOf(g);
        return `<tr${tileAttrs(g)}><td>${g.w}</td>${opp(g)}<td class="num lg-fp">${f1(v)}</td>
          <td class="num ${pj == null ? 'muted' : v >= pj ? 'lg-over' : 'lg-under'}">${pj != null ? f1(pj) : '–'}</td>
          <td class="num"><span class="lg-rk ${rkClass(g.rk)}">${g.rk}</span></td><td class="num">${g.sn != null ? g.sn : '–'}</td>
          ${stat.map(([, fn]) => `<td class="num">${fn(g)}</td>`).join('')}</tr>`;
      }).join('');
      return `<tbody><tr class="lg-season"><td colspan="${6 + stat.length}"><b>${S.s}</b> ${esc(team)} · ${S.g.length} game${S.g.length === 1 ? '' : 's'}${S.g.length ? ` · ${f1(fpg)} FP/G` : ''}</td></tr>${head}${trs}</tbody>`;
    }).join('');
    const legend = `<div class="lg-leg"><span>Opponent color = our pregame matchup rank (2021 on):</span><span class="mr-easy">easy</span><span class="mr-ok">fair</span><span class="mr-tough">tough</span><span class="mr-hard">hardest</span>
      <span>· Rank = his ${esc(pos)} finish that week (green = starter in your league size) · Proj = our projection then (green = beat it) · Tap a game (2021 on) to open its matchup</span></div>`;
    return `${legend}<div class="lg-scroll"><table class="lg">${body}</table></div>`;
  };
  // Log rows we have a week page for (2021 on) open that game's matchup tile: in place when it's this page's week,
  // else on that week's page. g.gid / g.f (week file) come from tools/player_logs.py.
  const tileAttrs = g => g.gid && g.f ? ` data-gid="${esc(g.gid)}" data-f="${esc(g.f)}" title="Open the matchup"` : '';
  const wireLogRows = box => box && box.addEventListener('click', e => {
    if (e.target.closest('button, a, select, input')) return;
    const tr = e.target.closest('tr[data-gid]'); if (!tr) return;
    const gid = tr.dataset.gid, f = tr.dataset.f;
    if (CFG.page !== 'game' && DATA && f === DATA.__rel) { closePlayer(); goToTile(gid); }
    else location.href = `${siteRoot()}${f.replace(/\.json$/, '.html')}#g-${gid}`;
  });
  const LOGP = {};  // pid -> in-flight fetch, so a re-render while loading doesn't refetch
  const ensureLog = pid => LOGS[pid] ? Promise.resolve(LOGS[pid]) : (LOGP[pid] || (LOGP[pid] =
    getJSON(`${siteRoot()}data/players/${encodeURIComponent(pid)}.json`).then(L => (LOGS[pid] = L)).catch(() => (LOGS[pid] = { missing: 1, seasons: [] }))));

  // ----------------------------------------------------------------------------------------------- player card
  let cardPid = null, cardTab = 'ov';  // the open tab survives live refreshes; a new player starts on Week
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
  const weekBars = (p, d) => {
    const nweek = (d.week || 1) - 1; if (nweek < 1) return '';
    const w = weights(), byW = Object.fromEntries((p.sc.wk || []).map(r => [r[0], pts(r.slice(1), w, p.pos)]));
    const W = 300, H = 70, top = Math.max(10, ...Object.values(byW)), bw = W / nweek;
    let out = '';
    for (let k = 1; k <= nweek; k++) {
      const v = byW[k], x0 = (k - 1) * bw + 2;
      out += v === undefined
        ? `<line x1="${x0 + 3}" y1="${H - 16}" x2="${x0 + bw - 7}" y2="${H - 16}" class="wb-miss"><title>Week ${k}: did not play</title></line>`
        : `<rect x="${x0}" y="${H - 14 - Math.max(1, (H - 28) * Math.max(v, 0) / top)}" width="${bw - 5}" height="${Math.max(1, (H - 28) * Math.max(v, 0) / top)}" rx="2" class="wb"><title>Week ${k}: ${f1(v)} pts</title></rect>
           <text x="${x0 + (bw - 5) / 2}" y="${H - 16 - Math.max(1, (H - 28) * Math.max(v, 0) / top) - 3}" class="wb-v">${f0(v)}</text>`;
      out += `<text x="${x0 + (bw - 5) / 2}" y="${H - 2}" class="wb-l">${k}</text>`;
    }
    return `<svg class="pc-wk" viewBox="0 0 ${W} ${H}" width="100%" height="${H}">${out}</svg>`;
  };
  // Expected line: the week page's own row graphic (TD donuts) when the card shows this page's week, else text.
  const expectedLine = (pid, p, d) => {
    const td = d === DATA && document.querySelector(`tr.main[data-pid="${CSS.escape(pid)}"] td.line`);
    if (td) return td.innerHTML;
    const l = p.proj_line || {}, tdp = x => x ? `${Math.round((1 - Math.exp(-x)) * 100)}%` : '';
    const s = (v, u, d = 0) => v ? `<span class="st"><b>${d ? f1(v) : f0(v)}</b><small>${u}</small></span>` : '';
    const tds = (l.pass_td ? `${s(l.pass_td, 'pass TD', 1)}` : '') + (l.rush_td >= 0.1 ? `<span class="st"><b>${tdp(l.rush_td)}</b><small>rush TD</small></span>` : '')
      + (l.rec_td >= 0.1 ? `<span class="st"><b>${tdp(l.rec_td)}</b><small>rec TD</small></span>` : '');
    return p.pos === 'QB' ? s(l.pass_yd, 'pass yd') + s(l.int, 'INT', 1) + s(l.rush_yd, 'rush yd') + tds
      : p.pos === 'RB' ? s(l.car, 'car', 1) + s(l.rush_yd, 'rush yd') + s(l.rec, 'rec', 1) + s(l.rec_yd, 'rec yd') + tds
        : s(l.tgt, 'tgt', 1) + s(l.rec, 'rec', 1) + s(l.rec_yd, 'yd') + tds;
  };
  // Season totals and usage, rebuilt from numbers (sc.ss = season stat line in scoring-key order, ext = volume).
  const seasonText = p => {
    const ss = p.sc.ss, e = p.ext || {}, K = KEYS(), v = k => ss ? ss[K.indexOf(k)] || 0 : 0;
    if (!ss || !e.games) return '<span class="muted">No games this season yet.</span>';
    const s = (x, u) => `<span class="st"><b>${f0(x)}</b><small>${u}</small></span>`;
    const parts = [s(e.games, 'games')];
    if (p.pos === 'QB') parts.push(s(e.completions, `/${f0(e.attempts)} cmp`), s(v('pass_yd'), 'pass yd'), s(v('pass_td'), 'pass TD'), s(v('interception'), 'INT'), s(v('rush_yd'), 'rush yd'));
    else {
      if (e.carries) parts.push(s(e.carries, 'car'), s(v('rush_yd'), 'rush yd'), s(v('rush_td'), 'rush TD'));
      if (e.targets) parts.push(s(e.targets, 'tgt'), s(v('reception'), 'rec'), s(v('rec_yd'), 'rec yd'), s(v('rec_td'), 'rec TD'));
    }
    const use = [e.snap != null ? `${Math.round(e.snap * 100)}% of snaps` : '', p.pos !== 'QB' && e.tgt_share ? `${Math.round(e.tgt_share * 100)}% target share` : '',
                 e.carry_share ? `${Math.round(e.carry_share * 100)}% of carries` : ''].filter(Boolean).join(' · ');
    return `${parts.join('')}${use ? `<div class="pc-sub">${use}</div>` : ''}`;
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
  const wkWait = d => d === undefined ? '<div class="pc-box"><p class="pc-sub">Loading that week&hellip;</p></div>'
    : '<div class="pc-box"><p class="pc-sub">We have no page for that week.</p></div>';

  const gameHref = (g, d = DATA) => `${siteRoot()}game.html?d=${encodeURIComponent(d.__rel || CFG.data)}&g=${encodeURIComponent(g.id)}`;
  // The player's weekly section for the selected week (projection, matchup, availability, season to date).
  const playerWeek = (pid, p, d) => {
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
    const pl = p.proj_line || {};
    const vol = [pl.att ? `${f1(pl.att)} pass att` : '', pl.car ? `${f1(pl.car)} carries` : '', pl.tgt ? `${f1(pl.tgt)} targets` : '', pl.rec ? `${f1(pl.rec)} catches` : ''].filter(Boolean).join(' · ');
    const nweek = (d.week || 1) - 1;
    const fpg = p.sc.g ? pts(p.sc.ss, w, p.pos) / p.sc.g : null;
    const last = [...(p.sc.wk || [])].sort((a, b) => a[0] - b[0]).slice(-3).map(r => pts(r.slice(1), w, p.pos));
    const l3 = last.length ? last.reduce((a, b) => a + b, 0) / last.length : null;
    const flags = [p.status ? `<span class="flag ${p.inactive >= 0.5 ? 'f-out' : 'f-q'}">${esc(p.status)}</span>` : '',
                   p.boost >= 1 ? `<span class="flag f-up" title="Raised by volume vacated by ${esc(p.boost_from)}">+${f1(p.boost)} from injuries</span>` : '',
                   p.low_sample ? '<span class="flag">low data</span>' : ''].join('');
    const html = `
      <div class="pc-wkmeta"><span class="tier t-${esc(p.slot)}">${esc(p.tier)}</span> <span class="muted">${esc(p.pos)}${p.rank} in ${esc(wkLabel(d).toLowerCase())}</span>
        ${opp ? `<span class="muted">· <button type="button" class="tm-open pc-tlink" data-tm="${esc(p.team)}">${esc(p.team)}</button> ${esc(p.home)} <button type="button" class="tm-open pc-tlink" data-tm="${esc(opp.team)}">${esc(opp.team)}</button></span>` : ''}
        ${flags ? `<span class="pc-flags">${flags}</span>` : ''}</div>
      ${now}
      <div class="pc-grid">
        <div class="pc-box"><div class="pc-k">Projection${p.inactive >= 0.05 ? ' (if active)' : ''}</div><div class="pc-big">${f1(s.proj)} <small>pts</small></div>
          ${rangeSvg(s.q, s.proj)}<div class="pc-sub">Floor ${f1(s.q[0])} · middle ${f1(s.q[1])}–${f1(s.q[3])} · ceiling ${f1(s.q[4])} · confidence ${esc(p.conf)}</div></div>
        <div class="pc-box"><div class="pc-k">Expected line</div><div class="line">${expectedLine(pid, p, d)}</div>${vol ? `<div class="pc-sub">${esc(vol)}</div>` : ''}</div>
        <div class="pc-box"><div class="pc-k">Matchup</div>
          <div class="pc-mu">${g ? `<a class="pc-tile" href="${tileHref(g, d)}" data-goto="${esc(g.id)}" title="Open the matchup tile">` : ''}${opp ? logo(opp.logo_url, opp.logo_bg, 20, opp.team) : ''}<b>${esc(p.home)} ${esc(p.opp)} &rsaquo;</b>${g ? '</a>' : ''}
            <span style="color:${esc(p.dvp_color)}">${esc(p.dvp)} vs ${esc(p.pos)}s</span> <span class="muted">grade ${esc(p.grade)}</span></div>
          <div class="pc-sub">This defense ${p.mpts >= 0 ? 'adds' : 'takes away'} ${f1(Math.abs(p.mpts))} pts vs an average one.</div></div>
        <div class="pc-box"><div class="pc-k">Availability</div><div class="pc-big sm">${p.inactive < 0.005 ? '<1' : Math.round(p.inactive * 100)}% <small>inactive</small></div>
          <div class="pc-sub">${esc(p.inactive_why)}</div></div>
      </div>
      <div class="pc-box"><div class="pc-k">${esc(d.season)} season before week ${esc(d.week)}</div><div class="line">${seasonText(p)}</div>
        <div class="pc-sub">${fpg != null ? `${f1(fpg)} FP/G` : ''}${l3 != null ? ` · last 3: ${f1(l3)}` : ''}${p.sched ? ` · ${esc(p.sched)}` : ''}</div>
        ${nweek >= 1 ? `<div class="pc-k" style="margin-top:10px">Points by week</div>${weekBars(p, d)}` : ''}</div>
      <p class="pc-take">${esc(p.takeaway)}</p>
      ${g ? `<div class="pc-links"><a href="${gameHref(g, d)}">${st && st.state === 'in' ? '<span class="live-dot"></span>' : ''}Gamecast: ${esc(g.away.team)} @ ${esc(g.home.team)} &rsaquo;</a>
        <a href="${tileHref(g, d)}" data-goto="${esc(g.id)}">Matchup tile &rsaquo;</a></div>` : ''}`;
    return html;
  };
  // A player we didn't list that week: say so, and show what he did from the career log when he played.
  const playerOff = (L, d) => {
    const S = L && (L.seasons || []).find(x => +x.s === +d.season), g = S && S.g.find(x => x.w === +d.week);
    const pos = L && L.pos;
    const played = g ? `<div class="pc-now"><div class="pc-k">Final</div><div class="pc-big">${f1(pts(g.c, weights(), pos))} <small>pts</small></div>
      <div class="pc-sub">${g.h === 0 ? '@' : 'vs'} ${esc(g.o)} · ${ord(g.rk)} among ${esc(pos)}s${g.gid && g.f ? ` · <a href="${siteRoot()}${esc(g.f.replace(/\.json$/, '.html'))}#g-${esc(g.gid)}" data-goto="${esc(g.gid)}">Matchup tile &rsaquo;</a>` : ''}</div></div>` : '';
    return `${played}<div class="pc-box"><p class="pc-sub">Not on our ${esc(wkLabel(d).toLowerCase())} board: a bye, ruled out, not on a roster yet, or projected too low to list.</p></div>`;
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
    if (cardTab === 'news' && !news) cardTab = 'ov';
    const week = d === undefined || d === null ? wkWait(d) : p ? playerWeek(pid, p, d) : playerOff(L, d);
    body.innerHTML = `
      <div class="pc-head" style="--tc:${esc(info.color || '#666')}">
        ${team ? tLogo(team, 34) : ''}
        <div class="pc-id"><h3 id="pcName">${esc(name)}</h3>
          <div class="pc-meta">${pos ? `<span class="posb posb-${esc(pos)}">${esc(pos)}</span>` : ''} ${team ? `<button type="button" class="tm-open pc-tlink" data-tm="${esc(team)}">${esc(info.name || team)}</button>` : '<span class="muted">Free agent</span>'}</div></div>
      </div>
      <div class="seg pc-tabs" role="tablist">${[['ov', 'Week'], ['log', 'Game log'], ...(news ? [['news', 'News']] : [])]
        .map(([k, l]) => `<button type="button" role="tab" data-pt="${k}" class="${cardTab === k ? 'on' : ''}">${l}</button>`).join('')}</div>
      <div class="pc-tab" data-pt="ov"${cardTab === 'ov' ? '' : ' hidden'}>${pickerHtml()}${week}</div>
      <div class="pc-tab" data-pt="log"${cardTab === 'log' ? '' : ' hidden'}><div class="pc-box pc-logbox"><div class="pc-k">Every career game</div><div class="pc-log">${
        !LOGS[pid] ? '<p class="pc-sub">Loading game log&hellip;</p>' : !L ? '<p class="pc-sub">Game log unavailable.</p>'
          : L.seasons.length || (L.up || []).length ? logHtml(L, p || row) : '<p class="pc-sub">No NFL games yet.</p>'}</div></div></div>
      ${news ? `<div class="pc-tab" data-pt="news"${cardTab === 'news' ? '' : ' hidden'}><div class="pc-box pc-newsbox"><div class="pc-k">Recent news</div><div class="pc-news"></div></div></div>` : ''}`;
    const nb = body.querySelector('.pc-news'); if (nb) loadNews(espn, nb);
    wireLogRows(body.querySelector('.pc-log'));
    body.querySelectorAll('.pc-tabs [data-pt]').forEach(b => b.onclick = () => {
      cardTab = b.dataset.pt;
      body.querySelectorAll('.pc-tabs [data-pt]').forEach(x => x.classList.toggle('on', x === b));
      body.querySelectorAll('.pc-tab').forEach(t => { t.hidden = t.dataset.pt !== cardTab; });
    });
    wirePicker(body);
    wireGoto(body);
  };
  // Matchup links in cards jump to that game's tile: in place for this page's week, else on that week's page.
  const tileHref = (g, d = DATA) => CFG.page !== 'game' && d === DATA ? `#g-${g.id}`
    : `${siteRoot()}${(d.__rel || 'index.json').replace(/\.json$/, '.html')}#g-${g.id}`;
  const goToTile = gid => {
    const tab = document.querySelector('nav.tabs button[data-tab="games"]'); if (tab) tab.click();
    const card = document.getElementById('g-' + gid);
    if (card) setTimeout(() => {
      card.scrollIntoView({ behavior: 'smooth', block: 'start' });
      card.classList.add('flash'); setTimeout(() => card.classList.remove('flash'), 1600);
      // Arriving from another page: logos still loading above shift the layout, so re-align once they're in.
      if (document.readyState !== 'complete') addEventListener('load', () => card.scrollIntoView({ block: 'start' }), { once: true });
    }, 60);
  };
  const wireGoto = body => body.querySelectorAll('[data-goto]').forEach(a => a.onclick = ev => {
    if (!(a.getAttribute('href') || '').startsWith('#')) return;  // a real link to another week page's tile
    ev.preventDefault(); closePlayer(); goToTile(a.dataset.goto);
  });
  // ------------------------------------------------------------------------------------------------- team card
  // Same overlay and look as the player card. Week tab from the picked week's data (Power, matchup, players);
  // season stats and the career game log from data/teams/<TEAM>.json (tools/player_logs.py).
  let cardTeam = null, teamTab = 'ov', teamOpp = '';
  const TLOGS = {};
  const rkChip = (r, title = '') => r ? `<span class="rk-b ${r <= 8 ? 'rk1' : r <= 16 ? 'rk2' : r <= 24 ? 'rk3' : 'rk4'}"${title ? ` title="${esc(title)}"` : ''}>${ord(r)}</span>` : '';
  const sgn = v => v == null || isNaN(v) ? '' : `${v >= 0 ? '+' : ''}${(+v).toFixed(1)}`;
  const tInfo = t => (DATA && DATA.teams && DATA.teams[t]) || {};
  const tLogo = (t, size = 20) => { const i = tInfo(t); return logo(i.logo, i.logo_bg, size, t); };
  const gcHref = (gid, f) => `${siteRoot()}game.html?g=${encodeURIComponent(gid)}${f ? `&d=${encodeURIComponent(f)}` : ''}`;
  const rankTrend = hist => {
    const wk = Object.keys(hist || {}).map(Number).sort((a, b) => a - b);
    if (wk.length < 2) return '';
    const W = 300, H = 80, X = w => 14 + (W - 28) * (w - wk[0]) / Math.max(1, wk[wk.length - 1] - wk[0]), Y = r => 8 + (H - 26) * (r - 1) / 31;
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
      h2h = `<div class="tm-h2h">${tLogo(teamOpp, 18)} <b>${esc(abbr)} vs ${esc(teamOpp)} since 1999: ${w}-${l}${t ? `-${t}` : ''}</b> <span class="muted">(${gs.length} games)</span></div>`;
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
      if (!rows.length) return '';
      rows.sort((a, b) => a.w - b.w);
      const rk = S.rk || {}, av = S.avg || {};
      const trs = rows.map(r => {
        if (r.bye) return `<tr class="lg-bye"><td>${r.w}</td><td colspan="15">Bye</td></tr>`;
        if (r.u) {
          const u = r.u;
          return `<tr class="lg-up"${tileAttrs(u)}><td>${u.w}</td>${oppCell(u.o, u.h, u.opr)}<td class="muted">upcoming</td><td class="num">${u.ln != null ? sgn(-u.ln).replace('+0.0', 'PK') : '–'}</td>
            <td class="num">${pct(u.vc, u.mc)}</td><td class="num">–</td><td class="num">–</td><td colspan="8"></td><td><a class="tm-gc" href="${gcHref(u.gid, u.f)}" title="Gamecast">&rsaquo;</a></td></tr>`;
        }
        const g = r.g, s = g.s || [], os = g.os || [];
        const res = `<span class="tm-res ${g.r === 'W' ? 'w' : g.r === 'L' ? 'l' : ''}">${g.r}</span> ${g.ps}-${g.pa}${g.ot ? ' <small>OT</small>' : ''}`;
        const line = g.ln != null ? `${g.ln > 0 ? '-' : g.ln < 0 ? '+' : ''}${g.ln === 0 ? 'PK' : Math.abs(g.ln).toFixed(1)}${g.ats ? ` <small class="ats-${g.ats}">${g.ats === 'W' ? 'cov' : g.ats === 'L' ? 'no' : 'push'}</small>` : ''}` : '–';
        return `<tr${tileAttrs(g)}><td>${g.w}</td>${oppCell(g.o, g.h, g.opr)}<td class="tm-rc">${res}</td><td class="num">${line}</td><td class="num">${pct(g.vc, g.mc)}</td>
          <td class="num">${g.pr ? `<span class="lg-rk ${g.pr <= 8 ? 'rk-good' : g.pr <= 20 ? 'rk-mid' : 'rk-bad'}">${g.pr}</span>` : '–'}</td><td class="num muted">${g.elo || ''}</td>
          <td class="num">${f0(s[0])}</td><td class="num">${f0(s[1])}</td><td class="num">${f0(s[2])}</td><td class="num">${s[3] != null ? s[3].toFixed(1) : ''}</td><td class="num">${s[4] ?? ''}</td>
          <td class="num">${f0(os[0])}</td><td class="num">${os[3] != null ? os[3].toFixed(1) : ''}</td><td class="num">${os[4] ?? ''}</td>
          <td><a class="tm-gc" href="${gcHref(g.gid, g.f)}" title="Gamecast">&rsaquo;</a></td></tr>`;
      }).join('');
      const sumBits = [S.rec, av.pf != null ? `${f1(av.pf)} PF/G${rk.pf ? ` (${ord(rk.pf)})` : ''}` : '', av.pa != null ? `${f1(av.pa)} PA/G${rk.pa ? ` (${ord(rk.pa)})` : ''}` : ''].filter(Boolean).join(' · ');
      return `<tbody><tr class="lg-season"><td colspan="16"><b>${S.s}</b> ${esc(sumBits)}</td></tr>${head}${trs}</tbody>`;
    }).join('');
    const legend = `<div class="lg-leg"><span>Opponent color = their power rank that week (2021 on):</span><span class="mr-hard">top 8</span><span class="mr-tough">9-16</span><span class="mr-ok">17-24</span><span class="mr-easy">25-32</span>
      <span>· Odds = pregame win chance, Vegas / our model · Line = Vegas spread for ${esc(abbr)} (cov = covered) · › = gamecast · Tap a game (2021 on) to open its matchup</span></div>`;
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
  const renderTeam = abbr => {
    const body = document.querySelector('#pcOv .pc-body');
    const d = cardData(), L = TLOGS[abbr], info = tInfo(abbr);
    cardNeeds();
    // Header, season box and game log are current; the Week tab (matchup, Power, players) follows the picker.
    const wk = d ? teamWeek(abbr, d) : { html: wkWait(d), players: '' };
    body.innerHTML = `
      <div class="pc-head" style="--tc:${esc(info.color || '#666')}">${tLogo(abbr, 34)}
        <div class="pc-id"><h3 id="pcName">${esc(info.name || abbr)}</h3>
          <div class="pc-meta"><b>${esc((L && (L.seasons.find(s => s.s === L.cur) || {}).rec) || '')}</b>${info.division ? ` <span class="muted">${esc(info.division)}</span>` : ''}</div></div></div>
      <div class="seg pc-tabs" role="tablist">${[['ov', 'Week'], ['log', 'Game log'], ['pl', 'Players']].map(([k, l]) => `<button type="button" data-tt="${k}" class="${teamTab === k ? 'on' : ''}">${l}</button>`).join('')}</div>
      <div class="pc-tab" data-tt="ov"${teamTab === 'ov' ? '' : ' hidden'}>${pickerHtml()}${wk.html}<div class="tm-season">${L ? teamSeasonBox(L) : ''}</div></div>
      <div class="pc-tab" data-tt="log"${teamTab === 'log' ? '' : ' hidden'}><div class="pc-box pc-logbox"><div class="pc-k">Every game since 1999</div><div class="tm-log">${L ? teamLogHtml(L, abbr) : '<p class="pc-sub">Loading game log&hellip;</p>'}</div></div></div>
      <div class="pc-tab" data-tt="pl"${teamTab === 'pl' ? '' : ' hidden'}>${pickerHtml()}${d ? `<div class="pc-box"><div class="pc-k">Fantasy players · ${esc(wkLabel(d).toLowerCase())}</div>
        ${wk.players ? `<table class="bx tm-pl"><thead><tr><th>Player</th><th class="num">Proj</th><th>Tier</th><th class="num">FP/G</th></tr></thead><tbody>${wk.players}</tbody></table>` : '<p class="pc-sub">No fantasy-relevant players listed that week.</p>'}</div>` : wkWait(d)}</div>`;
    body.querySelectorAll('[data-tt]').forEach(b => b.onclick = () => {
      teamTab = b.dataset.tt;
      body.querySelectorAll('.pc-tabs [data-tt]').forEach(x => x.classList.toggle('on', x === b));
      body.querySelectorAll('.pc-tab').forEach(t => { t.hidden = t.dataset.tt !== teamTab; });
    });
    wireTeamLog(body, abbr);
    wireLogRows(body.querySelector('.tm-log'));
    wirePicker(body);
    wireGoto(body);
    if (!L) loadTeamLog(abbr);
  };
  // The team's Week tab for one week's data: result / live score, matchup and odds, Power box; plus its player rows.
  const teamWeek = (abbr, d) => {
    const pw = (d.power || []).find(x => x.team === abbr), g = teamGame(abbr, d);
    const opp = g && (g.away.team === abbr ? g.home : g.away), home = g && g.home.team === abbr;
    const st = d === DATA && g ? LIVE.byGame[g.id] : null;
    let now = '';
    if (st && st.state !== 'pre') {
      const me = st.home.team === abbr ? st.home : st.away, them = st.home.team === abbr ? st.away : st.home, live = st.state === 'in';
      now = `<div class="pc-now${live ? ' is-live' : ''}"><div class="pc-k">${live ? `<span class="live-dot"></span>Live · ${esc(st.short || '')}` : 'Final'}</div>
        <div class="pc-big">${esc(abbr)} ${me.score} <small>–</small> ${them.score} ${esc(them.team)}</div><div class="pc-sub"><a href="${gameHref(g, d)}">${live ? 'Open live gamecast' : 'Game recap'} &rsaquo;</a></div></div>`;
    } else if (g && g.final) {
      const ps = home ? g.final.home : g.final.away, pa = home ? g.final.away : g.final.home;
      now = `<div class="pc-now"><div class="pc-k">Final</div><div class="pc-big">${esc(abbr)} ${ps} <small>–</small> ${pa} ${esc(opp.team)}</div><div class="pc-sub"><a href="${gameHref(g, d)}">Game recap &rsaquo;</a></div></div>`;
    }
    const fc = g && g.fc;
    const myPct = (fav, pct) => fav === abbr ? pct : 100 - pct;
    const week = g ? `<div class="pc-box"><div class="pc-k">${esc(wkLabel(d))}</div>
        <div class="pc-mu"><a class="pc-tile" href="${tileHref(g, d)}" data-goto="${esc(g.id)}" title="Open the matchup tile">${tLogo(opp.team, 22)}<b>${home ? 'vs' : '@'} ${esc(opp.nick || opp.team)} &rsaquo;</b></a> <span class="muted">${esc(g.kickoff || '')}</span></div>
        ${fc ? `<div class="tm-odds"><div><div class="pc-k">${fc.src === 'Vegas' ? 'Vegas odds' : 'Our model (no line yet)'}</div><b>${fc.tossup ? 'Tossup' : `${myPct(fc.fav, fc.pct)}%`}</b>${fc.tossup ? ` <small class="muted">${esc(abbr)} ${myPct(fc.fav, fc.pct)}%</small>` : ''}</div>
          ${fc.src === 'Vegas' ? `<div><div class="pc-k">Our model</div><b>${fc.model_tossup ? 'Tossup' : `${myPct(fc.model_fav, fc.model_pct)}%`}</b></div>` : ''}
          ${g.vegas_line ? `<div><div class="pc-k">Line</div><b>${esc(g.vegas_line)}</b></div>` : ''}</div>` : ''}
        <div class="pc-links" style="margin-top:8px"><a href="${gameHref(g, d)}">Gamecast &rsaquo;</a><a href="${tileHref(g, d)}" data-goto="${esc(g.id)}">Matchup tile &rsaquo;</a></div></div>`
      : `<div class="pc-box"><div class="pc-k">${esc(wkLabel(d))}</div><b>Bye</b></div>`;
    const unit = (label, v, rk, pp, total) => `<div class="tm-u${total ? ' tm-tot' : ''}"><span class="tm-ul">${label}</span><span class="tm-uv">${sgn(v)}</span>${rkChip(rk)}
      <span class="tm-ub"><span style="${v >= 0 ? `left:50%;width:${Math.min(50, Math.abs(v) * 10)}%` : `right:50%;width:${Math.min(50, Math.abs(v) * 10)}%`}" class="${v >= 0 ? 'pos' : 'neg'}"></span></span>
      ${pp != null ? `<span class="tm-pp muted" title="EPA per 100 plays">${sgn(pp)}</span>` : '<span></span>'}</div>`;
    const power = pw ? `<div class="pc-box"><div class="pc-k">Power ranking</div>
        <div class="tm-pw"><div><div class="pc-big">${ord(pw.rank)}</div><div class="pc-sub">rank range ${esc(pw.range)}${pw.move ? ` · ${pw.move > 0 ? '▲' : '▼'}${Math.abs(pw.move)} from the week before` : ''}</div></div>
          <div><div class="pc-big sm">${sgn(pw.net)} <small>pts/g vs avg</small></div></div></div>
        <div class="tm-units">${unit('Offense', pw.off, pw.off_rk, null, true)}${unit('Pass O', pw.pass_o, pw.pass_o_rk, pw.pass_o_pp)}${unit('Run O', pw.rush_o, pw.rush_o_rk, pw.rush_o_pp)}
          ${unit('Defense', pw.def, pw.def_rk, null, true)}${unit('Pass D', pw.pass_d, pw.pass_d_rk, pw.pass_d_pp)}${unit('Run D', pw.rush_d, pw.rush_d_rk, pw.rush_d_pp)}
          ${unit('Special teams', pw.st, pw.st_rk, null, true)}</div>
        <div class="pc-sub">Points per game vs an average team (opponent-adjusted). Schedule so far ${ord(pw.sos_past_rk)} hardest · rest of season ${ord(pw.sos_next_rk)} hardest.</div>
        ${rankTrend(pw.rank_hist) ? `<div class="pc-k" style="margin-top:10px">Power rank by week</div>${rankTrend(pw.rank_hist)}` : ''}</div>` : '';
    const players = Object.entries(d.players).filter(([, p]) => p.team === abbr).sort((a, b) => b[1].proj - a[1].proj);
    const plRows = players.map(([pid, p]) => { const s = scaled(p, d);
      return `<tr><td><button type="button" class="bx-n" data-open-pid="${esc(pid)}">${esc(p.name)}</button> <span class="posb posb-${esc(p.pos)}">${esc(p.pos)}</span>${p.status ? ` <span class="flag ${p.inactive >= 0.5 ? 'f-out' : 'f-q'}">${esc(p.status)}</span>` : ''}</td>
        <td class="num"><b>${f1(s.proj)}</b></td><td><span class="tier t-${esc(p.slot)}">${esc(p.tier)}</span></td><td class="num muted">${p.fpg != null ? f1(p.fpg) : ''}</td></tr>`; }).join('');
    return { html: `${now}<div class="pc-grid tm-grid">${week}${power}</div>`, players: plRows };
  };
  const wireTeamLog = (body, abbr) => {
    const sel = body.querySelector('[data-topp]');
    if (sel) sel.onchange = () => { teamOpp = sel.value; body.querySelector('.tm-log').innerHTML = teamLogHtml(TLOGS[abbr], abbr); wireTeamLog(body, abbr); };
  };
  const loadTeamLog = async abbr => {
    try { TLOGS[abbr] = await getJSON(`${siteRoot()}data/teams/${encodeURIComponent(abbr)}.json`); }
    catch (e) { const b = document.querySelector('#pcOv .tm-log'); if (b) b.innerHTML = '<p class="pc-sub">Game log unavailable.</p>'; return; }
    if (cardTeam === abbr) renderTeam(abbr);
  };
  const openTeam = abbr => {
    if (!DATA) return;
    const ov = ensureOverlay();
    if (!location.hash.startsWith('#player/') && !location.hash.startsWith('#team/')) prevHash = location.hash;
    if (abbr !== cardTeam) { teamTab = 'ov'; teamOpp = ''; }
    if (ov.hidden) cardWk = pageKey();  // a fresh card starts on the page's week; card-to-card keeps the picked one
    cardPid = null; cardTeam = abbr;
    renderTeam(abbr);
    ov.hidden = false;
    document.documentElement.classList.add('pc-open');
    try { history.replaceState(null, '', location.pathname + location.search + '#team/' + abbr); } catch (e) { /* ignore */ }
    ov.querySelector('.pc').scrollTop = 0; ov.scrollTop = 0;
  };

  const openPlayer = pid => {
    if (!DATA) return;
    const ov = ensureOverlay();
    if (!location.hash.startsWith('#player/') && !location.hash.startsWith('#team/')) prevHash = location.hash;
    if (pid !== cardPid) cardTab = 'ov';
    if (ov.hidden) cardWk = pageKey();
    cardPid = pid; cardTeam = null;
    renderCard(pid);
    ov.hidden = false;
    document.documentElement.classList.add('pc-open');
    try { history.replaceState(null, '', location.pathname + location.search + '#player/' + pid); } catch (e) { /* ignore */ }
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
  const paintTiles = () => {
    document.querySelectorAll('article.game[data-gid]').forEach(art => {
      const st = LIVE.byGame[art.dataset.gid], box = art.querySelector('.gc-live');
      if (!box) return;
      const g = DATA.games.find(x => x.id === art.dataset.gid);
      // Header scoreboard: live / just-finished scores in the same slots the build fills for finals.
      if (st && st.state !== 'pre' && !(st.state === 'post' && g && g.final)) {
        const sides = { away: art.querySelector('.g-team.away'), home: art.querySelector('.g-team.home') };
        ['away', 'home'].forEach(k => {
          const sc = sides[k] && sides[k].querySelector('.g-sc');
          if (sc) { sc.textContent = st[k].score; sc.hidden = false; }
          if (sides[k]) sides[k].classList.toggle('lost', st.state === 'post' && st[k].score < st[k === 'away' ? 'home' : 'away'].score);
        });
        const at = art.querySelector('.g-at');
        if (at) at.innerHTML = st.state === 'in' ? `<span class="live-dot"></span><small>${esc(st.short || '')}</small>` : '<span class="g-fin">FINAL</span>';
      }
      // Pregame: nothing. Final: the tile already shows our final line, unless the game ended after this build.
      if (!st || st.state === 'pre' || (st.state === 'post' && g && g.final)) { box.hidden = true; return; }
      const sum = LIVE.sums[st.id];
      const live = st.state === 'in';
      const sit = live ? (st.sit || (sum && sitFromPlays(sum))) : null;
      const sp = sit ? spot(sit, st) : null;
      const lastText = (sit && sit.lastPlay && sit.lastPlay.text) || '';
      const href = g ? gameHref(g) : '#';
      box.innerHTML = `
        ${sp ?`<div class="gl-sit"><b>${esc(sp.offense.team)} ball</b>${sp.text ? ` · ${esc(sp.text)}` : ''}${sp.red ? ' · <span class="gl-red">red zone</span>' : ''}</div>${fieldSvg(sp, st)}` : ''}
        ${lastText ? `<div class="gl-last">${linkNames(esc(lastText), [st.away.team, st.home.team])}</div>` : ''}
        <a class="gl-open" href="${href}">${live ? 'Open live gamecast' : 'Game recap'} &rsaquo;</a>`;
      box.hidden = false;
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
    pollWeek();
    document.addEventListener('visibilitychange', () => {
      if (document.hidden) clearTimeout(LIVE.timer); else pollWeek();
    });
  };

  // ------------------------------------------------------------------------------------------------- game page
  const GP = { sum: null, info: null, g: null, timer: null, view: 'drive', filter: 'all', q: '', sort: 'new', replay: null };
  const parseGid = gid => { const m = String(gid || '').match(/^(\d{4})_(\d{2})_([A-Z]{2,3})_([A-Z]{2,3})$/); return m ? { season: +m[1], week: +m[2], away: m[3], home: m[4] } : null; };
  const wpSeries = (sum) => {
    const plays = allPlays(sum).flatMap(d => d.plays || []);
    const byId = Object.fromEntries(plays.map(p => [String(p.id), p]));
    return (sum.winprobability || []).map(w => ({ w, p: byId[String(w.playId)] })).filter(x => x.p)
      .map(x => ({ t: elapsed(x.p), home: x.w.homeWinPercentage, play: x.p }));
  };
  const wpChart = (ser, info, upto) => {
    const pts_ = upto != null ? ser.filter(s => s.t <= upto) : ser;
    if (pts_.length < 2) return '<p class="muted">ESPN has no live win probability for this game yet.</p>';
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
  const tugRow = (x, label) => {
    const side = x.side, v = `+${(x.pts || 0).toFixed(1)}`;
    const chip = r => r ? `<span class="rk-b ${r <= 8 ? 'rk1' : r <= 16 ? 'rk2' : r <= 24 ? 'rk3' : 'rk4'}">${ord(r)}</span>` : '<span></span>';
    return `<div class="gt-row" title="${esc(x.title)}"><span class="gt-l">${esc(label || x.label)}</span>${chip(x.away_rk)}
      <span class="gt-v">${side === 'away' ? v : side === 'even' ? '<i>even</i>' : ''}</span>
      <span class="tug"><span class="tug-o" style="width:${x.split.toFixed(1)}%"></span><span class="tug-mid"></span></span>
      <span class="gt-v r">${side === 'home' ? v : side === 'even' ? '<i>even</i>' : ''}</span>${chip(x.home_rk)}</div>`;
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
    return `<div class="ts-head"><b>${esc(info.away.team)}</b><b>${esc(info.home.team)}</b></div>${rows}`;
  };
  const boxScore = (sum, info) => {
    const lines = boxLines(sum), map = byEspn(), w = weights();
    const nameCell = o => {
      const pid = map[o.id];
      return pid ? `<button type="button" class="bx-n" data-pid="${esc(pid)}">${esc(o.short)}</button>` : `<span class="bx-n plain">${esc(o.short)}</span>`;
    };
    const fp = o => { const pid = map[o.id], p = pid && DATA.players[pid]; return pts(o.line, w, p ? p.pos : ''); };
    return [info.away, info.home].map(side => {
      const mine = Object.values(lines).filter(o => o.team === side.team);
      const proj = o => { const pid = map[o.id], p = pid && DATA && DATA.players[pid]; return p ? p : null; };
      const fan = mine.filter(o => proj(o) || fp(o) !== 0).sort((x, y) => fp(y) - fp(x));
      const fanRows = fan.map(o => {
        const p = proj(o), s = p ? scaled(p) : null, v = fp(o);
        const d = s ? v - s.proj : null;
        return `<tr><td class="bx-who">${nameCell(o)}${p ? ` <span class="posb posb-${esc(p.pos)}">${esc(p.pos)}</span>` : ''}
          <div class="bx-line">${esc(statLineText(o))}</div></td><td class="num"><b>${f1(v)}</b></td>
          <td class="num muted">${s ? f1(s.proj) : ''}</td><td class="num ${d == null ? '' : d >= 0 ? 'good' : 'bad'}">${d == null ? '' : (d >= 0 ? '+' : '') + f1(d)}</td></tr>`;
      }).join('');
      const pass = mine.filter(o => o.att).map(o => { const p = proj(o), pl = p && p.proj_line;
        return `<tr><td>${nameCell(o)}</td><td class="num">${o.comp}/${o.att}</td><td class="num">${f0(o.line[0])}${pl && pl.pass_yd ? ` <small class="muted">/ ${f0(pl.pass_yd)}</small>` : ''}</td><td class="num">${o.line[1]}</td><td class="num">${o.line[2]}</td></tr>`; }).join('');
      const rush = mine.filter(o => o.car).sort((x, y) => y.line[3] - x.line[3]).map(o => { const p = proj(o), pl = p && p.proj_line;
        return `<tr><td>${nameCell(o)}</td><td class="num">${o.car}${pl && pl.car ? ` <small class="muted">/ ${f1(pl.car)}</small>` : ''}</td><td class="num">${f0(o.line[3])}${pl && pl.rush_yd ? ` <small class="muted">/ ${f0(pl.rush_yd)}</small>` : ''}</td><td class="num">${o.line[4]}</td></tr>`; }).join('');
      const rec = mine.filter(o => o.tgt || o.line[5]).sort((x, y) => y.tgt - x.tgt || y.line[6] - x.line[6]).map(o => { const p = proj(o), pl = p && p.proj_line;
        return `<tr><td>${nameCell(o)}</td><td class="num"><b>${o.tgt}</b>${pl && pl.tgt ? ` <small class="muted">/ ${f1(pl.tgt)}</small>` : ''}</td><td class="num">${o.line[5]}</td><td class="num">${f0(o.line[6])}${pl && pl.rec_yd ? ` <small class="muted">/ ${f0(pl.rec_yd)}</small>` : ''}</td><td class="num">${o.line[7]}</td></tr>`; }).join('');
      const tbl = (title, head, body) => body ? `<div class="bx-t"><div class="bx-h">${title}</div><table class="bx"><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table></div>` : '';
      return `<div class="bx-team" style="--tc:${esc(side.color)}"><div class="bx-th tm-open" data-tm="${esc(side.team)}">${logo(side.logo, '#111', 20, side.team)}<b>${esc(side.team)}</b></div>
        ${tbl('Fantasy points <small>(your scoring) vs our projection</small>', '<th>Player</th><th class="num">Pts</th><th class="num">Proj</th><th class="num">+/-</th>', fanRows)}
        ${tbl('Passing <small>yards / projected</small>', '<th>Player</th><th class="num">C/Att</th><th class="num">Yds</th><th class="num">TD</th><th class="num">Int</th>', pass)}
        ${tbl('Rushing <small>/ projected</small>', '<th>Player</th><th class="num">Car</th><th class="num">Yds</th><th class="num">TD</th>', rush)}
        ${tbl('Receiving <small>targets / projected</small>', '<th>Player</th><th class="num">Tgt</th><th class="num">Rec</th><th class="num">Yds</th><th class="num">TD</th>', rec)}</div>`;
    }).join('');
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
  const gameLog = (sum, info, ser, upto) => {
    const drives = allPlays(sum);
    const wpAfter = {}; ser.forEach((s, i) => { wpAfter[s.play.id] = { now: s.home, prev: i ? ser[i - 1].home : s.home }; });
    const teamOf = id => String(id) === String(info.home.id) ? info.home : String(id) === String(info.away.id) ? info.away : null;
    const q = GP.q.trim().toLowerCase();
    const keep = p => (upto == null || elapsed(p) <= upto) && (GP.filter === 'all' || (GP.filter === 'score' && p.scoringPlay)
      || (GP.filter === 'to' && p.isTurnover) || (GP.filter === 'pen' && p.isPenalty)) && (!q || String(p.text).toLowerCase().includes(q));
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
      const swing = Math.abs(d) >= 0.01 ? `<span class="pl-wp" title="Change in ESPN's live win probability on this play">${esc(d > 0 ? info.home.team : info.away.team)} +${Math.round(Math.abs(d) * 100)}%</span>` : '';
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
        <div class="pl-side">${p.scoringPlay ? `<b class="pl-sc">${esc(info.away.team)} ${p.awayScore}–${p.homeScore} ${esc(info.home.team)}</b>` : ''}${swing}</div></li>`;
    };
    const order = GP.sort !== 'old';  // newest first unless asked otherwise
    const swingOf = p => { const w = wpAfter[p.id]; return w ? Math.abs(w.now - w.prev) : 0; };
    let html = '';
    if (GP.sort === 'impact') {
      // Biggest swings in ESPN's live win probability, one flat list (impact order doesn't fit inside drives).
      const pl = drives.flatMap(d => d.plays || []).filter(keep).filter(p => wpAfter[p.id]).sort((a, b) => swingOf(b) - swingOf(a)).slice(0, 40);
      html = pl.length ? `<p class="gcs-note">The ${pl.length} plays that moved ESPN's win probability the most.</p><ol class="pls">${pl.map(playRow).join('')}</ol>`
        : '<p class="muted">No win-probability data for these plays yet.</p>';
    } else if (GP.view === 'every') {
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
  const renderGame = () => {
    const root = document.getElementById('gc'), { sum, info, g } = GP;
    const rp = GP.replay;
    const ser = sum ? wpSeries(sum) : [];
    const upto = rp ? rp.t : null;
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
    const fc = g && g.fc;
    const side = (s, isHome) => `<div class="sb-t tm-open${isHome ? ' home' : ''}" data-tm="${esc(s.team)}" style="--tc:${esc(s.color)}">${logo(s.logo, '#111', 40, s.team)}
      <div class="sb-id"><div class="sb-n"><span class="sb-full">${esc((g && (isHome ? g.home.nick : g.away.nick)) || s.team)}</span><span class="sb-ab">${esc(s.team)}</span></div><div class="sb-r">${esc(s.record || '')}</div></div>
      <div class="sb-s">${isHome ? hs : as}</div>${sp && sp.offense.team === s.team ? '<i class="sb-ball" title="Has the ball"></i>' : ''}</div>`;
    root.innerHTML = `
      <section class="sb">${side(info.away, false)}<div class="sb-mid">${info.state === 'in' && !rp ? '<span class="live-dot"></span>' : ''}<b>${esc(status)}</b>
        ${info.state === 'pre' ? `<div class="muted">${esc(new Date(info.date).toLocaleString([], { weekday: 'short', hour: 'numeric', minute: '2-digit' }))}</div>` : ''}</div>${side(info.home, true)}</section>
      ${sp ? `<section class="sit"><div class="sit-dd"><b>${esc(sp.offense.team)} ball</b>${sp.text ? ` · ${esc(sp.text)}` : ''}${sp.red ? ' · <span class="gl-red">red zone</span>' : ''}</div>
        ${fieldSvg(sp, info)}${sit.lastPlay && sit.lastPlay.text ? `<div class="sit-last"><span class="muted">Last play:</span> ${linkNames(esc(sit.lastPlay.text), [info.away.team, info.home.team])}</div>` : ''}</section>` : ''}
      ${GP.canReplay ? `<section class="rp">${rp ? `<button type="button" data-rp="first">&laquo;</button><button type="button" data-rp="prev">&lsaquo;</button>
        <button type="button" data-rp="play">${rp.timer ? 'Pause' : 'Play'}</button><button type="button" data-rp="next">&rsaquo;</button><button type="button" data-rp="last">&raquo;</button>
        <input type="range" min="0" max="${rp.plays.length - 1}" value="${rp.i}" aria-label="Replay position"><span class="muted">Play ${rp.i + 1} of ${rp.plays.length}</span>
        <button type="button" data-rp="off">Exit replay</button>` : '<button type="button" data-rp="on">Replay this game play by play</button>'}</section>` : ''}
      <nav class="gc-jump"><a href="#gcWp">Win %</a><a href="#gcLog">Plays</a><a href="#gcBox">Box score</a><a href="#gcTeam">Team stats</a>${g ? '<a href="#gcPre">Pregame</a>' : ''}</nav>
      <div class="gc-grid">
        <div class="gc-col">
          <section class="gcs" id="gcWp"><h3>Live win probability <span class="src">ESPN</span></h3>
            <p class="gcs-note">ESPN's in-game model, updated every play. Not NFL Edge's forecast: our pregame chances are in the Pregame box.</p>
            ${wpNow != null ? `<div class="wp-now-t"><span style="color:${esc(info.away.color)}">${esc(info.away.team)} ${pc(1 - wpNow)}</span><span style="color:${esc(info.home.color)}">${esc(info.home.team)} ${pc(wpNow)}</span></div>` : ''}
            <div class="wp-wrap">${sum ? wpChart(ser, info, upto) : ''}<div class="wp-tip" hidden></div></div>
            <div class="wp-leg"><span><i class="wp-m wp-score"></i>score</span><span><i class="wp-m wp-to"></i>turnover</span><span class="muted">Above the line: ${esc(info.home.team)} favored · below: ${esc(info.away.team)}</span></div></section>
          <section class="gcs" id="gcLog"><h3>Game log</h3>
            <div class="lg-bar"><div class="seg">${[['drive', 'By drive'], ['every', 'Every play']].map(([k, l]) => `<button type="button" data-view="${k}" class="${GP.view === k ? 'on' : ''}">${l}</button>`).join('')}</div>
              <div class="seg">${[['all', 'All'], ['score', 'Scoring'], ['to', 'Turnovers'], ['pen', 'Penalties']].map(([k, l]) => `<button type="button" data-filter="${k}" class="${GP.filter === k ? 'on' : ''}">${l}</button>`).join('')}</div>
              <input type="search" id="lgQ" placeholder="Player or text" value="${esc(GP.q)}" aria-label="Filter plays">
              <div class="seg">${[['new', 'Newest'], ['old', 'Oldest'], ['impact', 'Biggest swings']].map(([k, l]) => `<button type="button" data-sort="${k}" class="${GP.sort === k ? 'on' : ''}">${l}</button>`).join('')}</div></div>
            <div id="lgBody">${sum ? gameLog(sum, info, ser, upto) : '<p class="muted">Plays appear once the game starts.</p>'}</div></section>
        </div>
        <div class="gc-col">
          <section class="gcs" id="gcBox"><h3>Box score</h3>${rp ? '<p class="gcs-note">Box score shows the final totals during a replay.</p>' : ''}
            ${sum && sum.boxscore && sum.boxscore.players ? boxScore(sum, info) : '<p class="muted">The box score fills in once the game starts.</p>'}</section>
          <section class="gcs" id="gcTeam"><h3>Team stats</h3>${sum ? teamStats(sum, info) || '<p class="muted">Not available yet.</p>' : ''}</section>
          ${g ? `<section class="gcs" id="gcPre"><h3>Pregame <span class="src us">NFL Edge, before kickoff</span></h3>
            <div class="pre-odds"><div><div class="pc-k">Vegas odds</div><b>${fc && fc.src === 'Vegas' ? (fc.tossup ? 'Tossup' : `${esc(fc.nick)} ${fc.pct}%`) : '—'}</b>
              <div class="muted">${esc(g.vegas_line || 'No line')}${g.vegas_total ? ` · O/U ${f1(g.vegas_total)}` : ''}</div></div>
              <div><div class="pc-k">Our model</div><b>${fc ? (fc.model_tossup ? 'Tossup' : `${esc(fc.model_nick)} ${fc.model_pct}%`) : '—'}</b><div class="muted">${esc(fc ? fc.model_why || '' : '')}</div></div></div>
            <div class="pc-k" style="margin-top:12px">Who wins each battle · EPA per 100 plays</div>
            <div class="gt-teams"><b>${esc(info.away.team)}</b><b>${esc(info.home.team)}</b></div>
            <div class="gt" style="--ac:${esc(g.colors[g.away.team])};--hc:${esc(g.colors[g.home.team])}">
              ${g.battles.map(b => tugRow(b.head, `${b.head.left} vs ${b.head.right}`)).join('')}${g.extras.map(x => tugRow(x)).join('')}</div></section>` : ''}
        </div>
      </div>`;
    wireGame();
  };
  const wireGame = () => {
    const root = document.getElementById('gc');
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
        tip.hidden = false; tip.style.left = `${Math.min(Math.max(x * 100, 18), 82)}%`;
      };
      svg.addEventListener('mousemove', move); svg.addEventListener('touchstart', move, { passive: true });
      svg.addEventListener('touchmove', move, { passive: true });
      svg.addEventListener('mouseleave', () => { tip.hidden = true; hair.style.display = 'none'; });
    }
    // replay controls
    root.querySelectorAll('[data-rp]').forEach(b => b.onclick = () => replayCmd(b.dataset.rp));
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
      GP.sort = 'new'; renderGame(); return;
    }
    const rp = GP.replay; if (!rp) return;
    if (cmd === 'off') { clearInterval(rp.timer); GP.replay = null; renderGame(); return; }
    if (cmd === 'first') replayTo(0);
    if (cmd === 'last') replayTo(rp.plays.length - 1);
    if (cmd === 'prev') replayTo(rp.i - 1);
    if (cmd === 'next') replayTo(rp.i + 1);
    if (cmd === 'play') {
      if (rp.timer) { clearInterval(rp.timer); rp.timer = null; renderGame(); }
      else { rp.timer = setInterval(() => { if (rp.i >= rp.plays.length - 1) { clearInterval(rp.timer); rp.timer = null; } replayTo(rp.i + 1); }, 900); renderGame(); }
    }
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
      if (GP.info.realState !== 'pre') GP.sum = await getJSON(ESPN.sum + ev.id);
      // Player cards opened from this page show the live / final line too.
      if (GP.sum) Object.assign(LIVE.lines, boxLines(GP.sum));
      if (GP.g) LIVE.byGame[GP.g.id] = GP.info;
      GP.canReplay = GP.info.realState === 'post' && GP.sum && allPlays(GP.sum).length > 0;
      if (!GP.replay) renderGame();
    } catch (e) {
      if (!GP.info) document.getElementById('gc').innerHTML = `<p class="gc-loading">Live data unavailable right now (${esc(e.message)}). Try again in a minute.</p>`;
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
    else if (location.hash.startsWith('#g-')) goToTile(location.hash.slice(3));  // deep link to a matchup tile
    document.addEventListener('nfle-scoring', () => { paintRows(); if (cardPid) renderCard(cardPid); else if (cardTeam) renderTeam(cardTeam); });
    if (CFG.current || SIM) startLive();
  };
  // One click rule for the whole site: the innermost clickable thing wins - a player name or player row opens his
  // card, a team name / logo / tile header opens the team card (so a team inside a player row opens the team).
  document.addEventListener('click', e => {
    if (e.target.closest('a[href], input, select, .pc-tabs, .seg')) return;
    for (let n = e.target; n && n !== document; n = n.parentElement) {
      if (n.dataset && n.dataset.openPid) { openPlayer(n.dataset.openPid); return; }
      if (n.classList && n.classList.contains('tm-open') && n.dataset.tm) { openTeam(n.dataset.tm); return; }
      if (n.matches && n.matches('tr.main[data-pid]')) { openPlayer(n.dataset.pid); return; }
    }
  });
  window.NFLE = { openPlayer, closePlayer, openTeam };
  if (CFG.page === 'game') initGame(); else initWeek();
})();
