// Games > Matchups: one tile per game from the week JSON (DATA.games). Logos on the outside fading toward the
// middle, the two team colors blending across, @ in the center and one big number per side: the win chance before
// kickoff (Vegas, or ours before a line posts), the score once it starts. The whole tile opens the gamecast. Live
// games are repainted by gamecast.js (NFLE.paintTiles: called here once the tiles exist, then on every poll).
(() => {
  const NFLE = window.NFLE, esc = NFLE.esc, F = NFLE.fmt;
  const tile = g => {
    const f = g.fc || {}, fin = g.final;
    const sides = [[g.away, fin && fin.away, fin && fin.home, f.p_away], [g.home, fin && fin.home, fin && fin.away, f.p_home]];
    const verdict = !fin ? '' : !fin.winner ? '<span class="gf-pick toss">Tie</span>'
      : f.tossup ? `<span class="gf-pick toss">Tossup &middot; ${esc(fin.winner)} won</span>`
        : fin.fav_won ? `<span class="gf-pick ok">Favorite won &middot; ${f.pct}%</span>`
          : `<span class="gf-pick miss">Upset &middot; a ${100 - f.pct}% chance</span>`;
    const main = sides.map(([s, sc, os, pct], i) => {
      const side = i ? 'home' : 'away';
      const cls = `${fin && sc < os ? ' lost' : ''}${!fin && !f.tossup && pct < 50 ? ' dog' : ''}`;
      return `${s.logo_url ? `<img class="mt-lg ${side}" src="${esc(F.logoSrc(s.logo_url, 112))}" alt="" loading="lazy">` : ''}
        <div class="mt-side ${side}${cls}"><span class="mt-num">${fin ? esc(sc) : `${esc(pct)}<small>%</small>`}</span>
          <span class="mt-nm"><b>${esc(s.nick)}</b> <small>${esc(s.record)}</small></span></div>
        ${i ? '' : `<span class="mt-at">${g.neutral ? 'vs' : '@'}${f.tossup && !fin ? '<small>Tossup</small>' : ''}</span>`}`;
    }).join('');
    const st = fin ? `<span class="mt-fin">Final</span>${verdict}`
      : `<span>${esc(g.kickoff)}${g.neutral ? ' &middot; neutral' : ''}</span>
         <span class="mt-odds">${g.vegas_line ? `<b>${esc(g.vegas_line)}</b>` : 'no line yet'} &middot; <span title="${esc(f.model_why || '')}">ours ${f.model_tossup ? 'tossup' : `${esc(f.model_fav)} ${esc(f.model_pct)}%`}</span></span>`;
    return `<a class="mt ${fin ? 'is-final' : 'is-pre'}${f.tossup && !fin ? ' toss' : ''}" id="g-${esc(g.id)}" data-gid="${esc(g.id)}" href="${esc(NFLE.gameHref(g))}" style="${esc(g.bt_style || '')}">
      <div class="mt-main">${main}</div><div class="mt-st">${st}</div></a>`;
  };
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
