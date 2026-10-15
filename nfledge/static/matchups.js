// Games > Matchups: one tile per game from the week JSON (DATA.games). Logos on the outside fading toward the
// middle, the two team colors blending across, @ in the center and one big number per side: the win chance before
// kickoff (Vegas, or ours before a line posts), the score once it starts. The whole tile opens the gamecast. Live
// games are repainted by gamecast.js (NFLE.paintTiles: called here once the tiles exist, then on every poll).
(() => {
  const NFLE = window.NFLE;
  // the tile itself is shared (NFLE.ui.matchTile, shell.js): player and team pages show the same one
  const tile = g => NFLE.ui.matchTile(g).replace('<a class="mt ', `<a id="g-${NFLE.esc(g.id)}" class="mt `);
  NFLE.areas.matchups = {
    mount(sec) {
      NFLE.week().then(D => {
        if (!D || !D.games || !NFLE.gameHref) return;  // no week data: keep whatever the page has
        sec.innerHTML = `<div class="sec-head"><div><h2>Matchups</h2></div></div>
          ${D.games.length ? `<div class="games">${D.games.map(tile).join('')}</div>` : '<p class="muted">No games this week.</p>'}`;
        NFLE.paintTiles();
      });
    },
  };
})();
