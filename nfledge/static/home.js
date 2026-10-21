// Home (owner 2026-10-20): "a landing page with big tiles: I want to... see weekly projections / see team power
// rankings / track live games / get fantasy advice", then "make it look less AI and styled more inline with our site":
// the site's own pieces (section head, flat panels, muted tile labels, position badges, logos, tabular numbers), each
// tile previewing its tab with this week's real numbers. First visits land here; the logo comes back.
(() => {
  const NFLE = window.NFLE, esc = NFLE.esc;
  const f1 = v => (v == null || v !== v ? '–' : (Math.round(v * 10) / 10).toFixed(1));
  const signed = v => (v > 0 ? '+' : '') + f1(v);
  NFLE.areas.home = {
    mount(sec) {
      sec.innerHTML = '<div class="hm"><p class="muted">Loading&hellip;</p></div>';
      NFLE.week().then(D => draw(sec, D)).catch(() => { sec.innerHTML = '<div class="hm"><p class="muted">Couldn\'t load this week.</p></div>'; });
    },
  };
  const draw = (sec, D) => {
    const T = D.teams || {}, logo = (t, s = 20) => NFLE.fmt.logo(T, t, s), nick = t => (T[t] || {}).nick || t;
    // projections: the top projected player at each position
    const P = Object.entries(D.players || {}).map(([pid, p]) => Object.assign({ pid }, p));
    // (as Rankings: a player under 50% to play doesn't lead with his "if he plays" number)
    const plays = p => (p.play != null ? p.play : 1 - (p.inactive || 0)) >= 0.5;
    const top = ['QB', 'RB', 'WR', 'TE'].map(pos => P.filter(p => p.pos === pos && p.proj != null && plays(p)).sort((a, b) => b.proj - a.proj)[0]).filter(Boolean);
    const proj = top.map(p => `<li><span class="posb posb-${esc(p.pos)}">${esc(p.pos)}</span>${logo(p.team, 18)}<span class="hm-n">${esc(p.name)}</span><b class="hm-v">${f1(p.proj)}</b></li>`).join('');
    // power: the top four, net points per game vs an average team
    const pw = (D.power || []).slice().sort((a, b) => a.rank - b.rank).slice(0, 4)
      .map(t => `<li><span class="hm-rk">${t.rank}</span>${logo(t.team)}<span class="hm-n">${esc(t.nick || nick(t.team))}</span><span class="hm-m">${esc(t.record || '')}</span><b class="hm-v">${signed(t.net)}</b></li>`).join('');
    // games: the next ones to kick off (else the week's last finals)
    const G = (D.games || []).slice().sort((a, b) => `${a.gameday} ${a.gametime}`.localeCompare(`${b.gameday} ${b.gametime}`));
    const up = G.filter(g => !g.final), show = (up.length ? up : G.slice(-3)).slice(0, 4);
    const side = s => (s && (s.team || s)) || '';
    const games = show.map(g => { const a = side(g.away), h = side(g.home);
      const when = g.final ? 'Final' : String(g.kickoff || '').replace(/\s*ET$/, '').replace(/^(\w{3}) \w{3} \d+ · /, '$1 ');
      return `<li>${logo(a, 18)}<span class="hm-n hm-at">${esc(a)} <span class="muted">@</span> ${esc(h)}</span>${logo(h, 18)}<span class="hm-m hm-when">${esc(when)}</span></li>`; }).join('');
    // fantasy: your claimed team, else how to start
    let mine = null;
    try { mine = JSON.parse(localStorage.getItem('nfledge-mine') || 'null'); } catch (e) { /* private mode */ }
    const fant = mine && mine.league
      ? `<p class="hm-p">Your team in <b>${esc(mine.league)}</b>${mine.oppName ? ` vs ${esc(mine.oppName)}` : ''}: the best lineup, waiver adds by position and trade checks.</p>`
      : '<p class="hm-p">Connect your Sleeper or ESPN league: the best lineup each week, waiver adds by position and trade checks, under your league\'s scoring.</p>';
    const wk = D.week ? `Week ${D.week}` : 'This week';
    const tile = (href, label, body) => `<a class="hm-t" href="#${href}"><div class="hm-k">${label}<span class="hm-go" aria-hidden="true">&rsaquo;</span></div>${body}</a>`;
    sec.innerHTML = `<div class="hm">
      <div class="sec-head"><div><h2>I want to&hellip;</h2><p>${esc(wk)} on NFL Edge. Pick a place to start.</p></div></div>
      <details class="howto"><summary>What is this?</summary><div>
        <p>A free NFL prediction model. Every week it projects every player and team from play-by-play data and injury reports, ranks
        teams by how good they really are, tracks games live, and plugs into your Sleeper or ESPN league.</p>
        <p class="muted">No ads, no sign-up. The Model tab shows how it works, and what we tried that didn't.</p>
      </div></details>
      <div class="hm-grid">
        ${tile('players/rankings', 'See weekly projections', `<ul class="hm-l">${proj}</ul><p class="hm-f">Top projected at each position &middot; all players in Rankings</p>`)}
        ${tile('teams/power', 'See team power rankings', `<ul class="hm-l">${pw}</ul><p class="hm-f">Net points per game vs an average team</p>`)}
        ${tile('games', 'Track live games', `<ul class="hm-l">${games}</ul><p class="hm-f">Live scores, plays and win chances once games start</p>`)}
        ${tile('league/lineup', 'Get fantasy advice', fant)}
      </div></div>`;
  };
})();
