// Home (owner 2026-10-20): "a landing page with big tiles: I want to... see weekly projections / see team power
// rankings / track live games / get fantasy advice". First visits land here; the logo comes back. Each tile is a link
// to its tab on this week's page.
(() => {
  const NFLE = window.NFLE, esc = NFLE.esc;
  NFLE.areas.home = {
    mount(sec) {
      const CFG = window.NFLE_CFG || {};
      let mine = null;
      try { mine = JSON.parse(localStorage.getItem('nfledge-mine') || 'null'); } catch (e) { /* private mode */ }
      const wk = CFG.week ? `Week ${CFG.week}` : 'This week\'s';
      const tiles = [
        ['players/rankings', 'players', 'See weekly projections', `${wk} rankings at every position, with ranges and matchups`],
        ['teams/power', 'teams', 'See team power rankings', 'How good every team is from here on, and why'],
        ['games', 'games', 'Track live games', 'Scores, plays, box scores and win chances as they happen'],
        ['league/lineup', 'league', 'Get fantasy advice', mine && mine.league ? `Lineup, waivers and trades for your team in ${mine.league}`
          : 'Connect your Sleeper or ESPN league: lineup, waivers and trades'],
      ];
      sec.innerHTML = `<div class="home"><h2 class="home-h">I want to&hellip;</h2><div class="home-grid">${tiles.map(([h, k, t, sub]) =>
        `<a class="home-tile ht-${k}" href="#${h}">${NFLE.navIcon ? NFLE.navIcon(k) : ''}<b>${esc(t)}</b><span>${esc(sub)}</span><i class="home-go" aria-hidden="true">&rsaquo;</i></a>`).join('')}</div></div>`;
    },
  };
})();
