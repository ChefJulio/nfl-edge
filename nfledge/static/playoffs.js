// Teams > Playoffs: every postseason since 1920 as a bracket (data/playoffs/<season>.json, tools/playoffs_build.py),
// plus the current season's playoff odds (data/playoffs/odds.json, tools/playoff_odds.py) when available.
// Bracket layout per era: AFC rounds | Super Bowl | NFC rounds (mirrored) from 1970; two leagues side by side before;
// a single title game (plus labeled division tiebreakers) earlier; 1920-32 had no playoffs (champion by standings).
(() => {
  let TEAMS = {};  // the week data's teams map (tile colors, logos)
  const NFLE = window.NFLE, esc = NFLE.esc;
  const logoUrl = code => `https://a.espncdn.com/combiner/i?img=${encodeURIComponent(`/i/teamlogos/nfl/500/${code.toLowerCase()}.png`)}&w=60&h=60`;
  const ESPN_CODE = { LA: 'lar', WAS: 'wsh', LV: 'lv' };
  const badge = t => t.modern
    ? `<img class="po-logo tm-open" data-tm="${esc(t.site)}" src="${esc(logoUrl(ESPN_CODE[t.site] || t.site))}" alt="" width="20" height="20" loading="lazy">`
    : `<span class="po-txt" title="${esc(t.name)}">${esc(t.name.split(' ').map(w => w[0]).join('').slice(0, 3))}</span>`;
  const gameCard = g => {
    const homeWin = g.hs > g.as, row = (t, s, win) => `<div class="po-row${win ? ' win' : ''}">${badge(t)}${t.seed ? `<span class="po-seed">${t.seed}</span>` : ''}<span class="po-nm${t.modern ? ' tm-open' : ''}"${t.modern ? ` data-tm="${esc(t.site)}"` : ''}>${esc(t.name)}</span><b class="po-sc">${s}</b></div>`;
    const href = g.gid ? `${NFLE.root}game.html?g=${encodeURIComponent(g.gid)}` : '';
    return `<div class="po-game${href ? ' po-link' : ''}"${href ? ` data-href="${esc(href)}" title="Open the gamecast"` : ''}>
      ${row(g.away, g.as, !homeWin)}${row(g.home, g.hs, homeWin)}
      <div class="po-meta">${esc(new Date(g.date + 'T12:00:00').toLocaleDateString([], { month: 'short', day: 'numeric', year: 'numeric' }))}${g.neutral ? ' · neutral site' : ''}${g.league === 'AAFC' ? ' · AAFC' : g.league === 'AFL' ? ' · AFL' : ''}</div></div>`;
  };
  const roundCol = rd => `<div class="po-round"><div class="po-rl">${esc(rd.label)}</div><div class="po-games">${rd.games.map(gameCard).join('')}</div></div>`;
  const render = d => {
    if (d.era === 'standings') {
      return `<div class="po-none"><p>No playoffs in ${d.season}: the champion was decided by the standings.</p><p class="po-champ">Champion: <b>${esc(d.champion || '')}</b></p></div>`;
    }
    const groups = d.groups || [];
    const left = groups[0], right = groups[1], extra = groups.slice(2);
    const final = d.final ? `<div class="po-round po-final"><div class="po-rl">${esc(d.final.label)}</div><div class="po-games">${d.final.games.map(gameCard).join('')}</div></div>` : '';
    const side = (g, mirror) => g ? `<div class="po-side${mirror ? ' mirror' : ''}"><div class="po-st">${esc(g.title)}${g.title === 'AAFC' ? ' <span class="po-note">not counted in NFL records</span>' : ''}</div><div class="po-rounds">${(mirror ? [...g.rounds].reverse() : g.rounds).map(roundCol).join('')}</div></div>` : '';
    return `<div class="po-bracket">${side(left, false)}${final}${side(right, true)}</div>${extra.map(g => `<div class="po-bracket">${side(g, false)}</div>`).join('')}
      ${d.seeded ? '' : d.season < 1975 ? '<p class="st-note muted">No seeds before 1975: home field rotated by division, not by record.</p>' : ''}`;
  };
  NFLE.areas.playoffs = {
    mount(sec) {
      sec.classList.remove('soon');
      sec.innerHTML = `<div class="sec-head"><div><h2>Playoffs</h2><p class="po-sub">Loading&hellip;</p></div></div>
        <div class="dt-card"><div class="dt-tools"><select class="dt-select po-season" aria-label="Season"></select>
          <div class="seg po-view" hidden><button type="button" data-v="odds">Odds</button><button type="button" data-v="bracket">Bracket</button></div></div>
        <div class="skel-zone po-body"></div></div>
        <p class="st-note muted">Seasons are listed by the year they started (Super Bowl I = 1966 season). 1933-1998 results: FiveThirtyEight (MIT license); seeds 1975-1998: Wikipedia; 1999 on: nflverse, seeds from our tiebreaker code.</p>`;
      const sel = sec.querySelector('.po-season'), body = sec.querySelector('.po-body'), sub = sec.querySelector('.po-sub'), viewSeg = sec.querySelector('.po-view');
      let idx = null, view = 'odds';
      body.addEventListener('click', e => {
        if (e.target.closest('.tm-open')) return;
        const g = e.target.closest('.po-link'); if (g) location.href = g.dataset.href;
      });
      const load = s => {
        const isCur = s === idx.current;
        viewSeg.hidden = !isCur || !NFLE.areas.playoffOdds;
        if (isCur && NFLE.areas.playoffOdds && view === 'odds') {
          sec.querySelectorAll('.po-view button').forEach(b => b.classList.toggle('on', b.dataset.v === 'odds'));
          NFLE.areas.playoffOdds.render(body, sub);
          return;
        }
        sec.querySelectorAll('.po-view button').forEach(b => b.classList.toggle('on', b.dataset.v === 'bracket'));
        NFLE.load(`data/playoffs/${s}.json`).then(d => {
          sub.textContent = d.era === 'standings' ? `${s}: before the playoff era` : `${s} postseason`;
          body.innerHTML = render(d);
        }).catch(() => { sub.textContent = isCur ? `${s}: the playoffs haven't started` : 'No playoff data for that season.'; body.innerHTML = ''; });
      };
      viewSeg.addEventListener('click', e => { const b = e.target.closest('[data-v]'); if (b) { view = b.dataset.v; load(+sel.value); } });
      NFLE.load('data/playoffs/index.json').then(ix => {
        idx = ix;
        const seasons = [...new Set([...ix.seasons, ix.current])].sort((a, b) => b - a);
        const want = NFLE.areas.playoffOdds ? ix.current : ix.seasons[ix.seasons.length - 1];
        sel.innerHTML = seasons.map(s => `<option value="${s}"${s === want ? ' selected' : ''}>${s}${s === ix.current ? ' (this season)' : ''}</option>`).join('');
        sel.onchange = () => load(+sel.value);
        load(want);
      }).catch(() => { sub.textContent = 'Playoff data is not available on this page.'; });
    },
  };
})();
// Current-season playoff odds (data/playoffs/odds.json, tools/playoff_odds.py): the most likely seeding with each
// slot's chance, every team's chances by stage, and the walk-forward track record (2021-2025).
(() => {
  const NFLE = window.NFLE, esc = NFLE.esc;
  const pct = v => v == null ? '' : v >= 0.995 ? '>99%' : v > 0 && v < 0.005 ? '<1%' : `${Math.round(v * 100)}%`;
  const bar = v => `<span class="od-p" style="--v:${Math.round((v || 0) * 100)}">${pct(v)}</span>`;
  const logo = r => r.logo ? `<span class="st-logo" style="--tc:${esc(r.color || '#555')}"><img src="${esc(r.logo)}" alt="" width="20" height="20" loading="lazy"></span>` : '';
  let conf = '';
  NFLE.areas.playoffOdds = {
    render(body, sub) {
      body.innerHTML = '<p class="muted">Loading&hellip;</p>';
      Promise.all([NFLE.load('data/playoffs/odds.json'), NFLE.week()]).then(([d, wk]) => {
        TEAMS = (wk && wk.teams) || {};
        sub.textContent = `${d.season} playoff odds as of week ${d.as_of_week} · ${d.sims.toLocaleString()} simulated seasons`;
        const by = Object.fromEntries(d.teams.map(r => [r.team, r]));
        const seeding = ['AFC', 'NFC'].map(c => `<div class="od-conf"><div class="po-st">${c}</div>${(d.seeding[c] || []).map(s => {
          const r = by[s.team] || {};
          return `<div class="od-seed tm-open" data-tm="${esc(s.team)}" style="${NFLE.fmt.rowStyle(TEAMS, s.team)}"><b class="od-sn">${s.seed}</b>${logo(r)}<span class="od-nm">${esc(r.nick || s.team)}</span><span class="od-rec">${r.w}-${r.l}${r.t ? `-${r.t}` : ''}</span><span class="od-sp">${pct(s.p)}</span></div>`;
        }).join('')}</div>`).join('');
        const t = d.track;
        const track = t ? `<details class="howto od-track"><summary>Track record: how these odds did, 2021-2025</summary><div>
            <p>Odds re-run as of every week of every season (with that week's power ranks and the Vegas lines known then), then checked against what happened. Brier score: the average squared miss between the odds and what happened (0 would be perfect); "base rate" is the score from giving every team the league-wide average chance.</p>
            <table class="bx od-tt"><thead><tr><th></th><th class="num">Brier</th><th class="num">Base rate</th></tr></thead><tbody>
            ${[['playoffs', 'Make playoffs'], ['div', 'Win division'], ['bye', 'First-round bye'], ['title', 'Win Super Bowl']].map(([k, l]) => `<tr><td>${l}</td><td class="num">${t.brier[k].model.toFixed(3)}</td><td class="num">${t.brier[k].base_rate.toFixed(3)}</td></tr>`).join('')}
            </tbody></table>
            <p>Calibration (make playoffs): when we said X%, how often teams got in.</p>
            <table class="bx od-tt"><thead><tr><th>We said</th><th class="num">Teams</th><th class="num">Average</th><th class="num">Made it</th></tr></thead><tbody>
            ${t.calibration.map(c => `<tr><td>${esc(c.bin)}</td><td class="num">${c.n.toLocaleString()}</td><td class="num">${c.predicted}%</td><td class="num">${c.actual}%</td></tr>`).join('')}
            </tbody></table></div></details>` : '';
        body.innerHTML = `<div class="od-seeding">${seeding}</div>
          <p class="st-note muted od-note">Most likely seeding: the team most often in each seed, and how often. The NFL reseeds after the wild-card round, so this is not a fixed bracket.</p>
          <div class="dt-tools od-tools"><div class="seg od-cf"><button type="button" data-c="">All</button><button type="button" data-c="AFC">AFC</button><button type="button" data-c="NFC">NFC</button></div></div>
          <div class="od-tbl"></div>${track}`;
        const cols = [
          { key: 'team', label: 'Team', stick: true, first: 'asc', value: r => r.nick, html: r => NFLE.ui.team(r.team, TEAMS, esc(r.div)) },
          { key: 'rec', label: 'Record', value: r => r.w + 0.5 * r.t, html: r => `${r.w}-${r.l}${r.t ? `-${r.t}` : ''}` },
          { key: 'exp_w', label: 'Proj W', num: true, cls: 'key', title: 'Average wins at season end across the simulations', html: r => r.exp_w.toFixed(1) },
          ...[['p_playoffs', 'Playoffs'], ['p_div', 'Division', 'Win the division'], ['p_bye', 'Bye', 'The 1 seed: a first-round bye'],
              ['p_div_round', 'Div round', 'Reach the divisional round'], ['p_conf_game', 'Conf game', 'Reach the conference championship'],
              ['p_sb', 'Super Bowl', 'Reach the Super Bowl'], ['p_title', 'Win SB', 'Win the Super Bowl']]
            .map(([k, l, title]) => ({ key: k, label: l, num: true, title: title || '', html: r => bar(r[k]) })),
        ];
        const rows = () => d.teams.filter(r => !conf || r.conf === conf);
        const table = NFLE.Table(body.querySelector('.od-tbl'), { columns: cols, rows: rows(), sort: { key: 'p_playoffs', dir: 'desc' },
          cls: 'tiles', rowClass: () => 'teamrow tm-open', rowAttrs: r => `${NFLE.ui.tileStyle(TEAMS, r.team)} data-tm="${esc(r.team)}"` });
        const seg = body.querySelector('.od-cf');
        const mark = () => seg.querySelectorAll('button').forEach(b => b.classList.toggle('on', b.dataset.c === conf));
        seg.addEventListener('click', e => { const b = e.target.closest('[data-c]'); if (b) { conf = b.dataset.c; mark(); table.update(rows()); } });
        mark();
      }).catch(() => { body.innerHTML = '<p class="muted">Odds are not available yet.</p>'; });
    },
  };
})();
