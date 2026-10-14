// Teams > Playoffs: every postseason since 1920 as a bracket (data/playoffs/<season>.json, tools/playoffs_build.py),
// plus the current season's playoff odds (data/playoffs/odds.json, tools/playoff_odds.py) when available.
// Bracket layout per era: AFC rounds | Super Bowl | NFC rounds (mirrored) from 1970; two leagues side by side before;
// a single title game (plus labeled division tiebreakers) earlier; 1920-32 had no playoffs (champion by standings).
(() => {
  const NFLE = window.NFLE, esc = NFLE.esc;
  const logoUrl = code => `https://a.espncdn.com/combiner/i?img=${encodeURIComponent(`/i/teamlogos/nfl/500/${code.toLowerCase()}.png`)}&w=60&h=60`;
  const ESPN_CODE = { LA: 'lar', WAS: 'wsh', LV: 'lv' };
  const badge = t => t.modern
    ? `<img class="po-logo" src="${esc(logoUrl(ESPN_CODE[t.site] || t.site))}" alt="" width="20" height="20" loading="lazy">`
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
        <div class="po-body"></div></div>
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
