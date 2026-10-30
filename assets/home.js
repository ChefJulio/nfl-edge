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
  const go = e => {
    if (e.target.closest('[data-open-pid], .tm-open, .hm-dg > summary')) return;  // the card opens (the page's click rule); a digest folds
    if (e.target.closest('.hm-news') && (e.type === 'click' || e.key === 'Enter')) NFLE.movesNotable = true;  // Moves opens on Notable
    const t = e.target.closest('.hm-t');
    if (t && (e.type === 'click' || e.key === 'Enter')) location.hash = t.dataset.href;
  };
  const draw = (sec, D) => {
    if (!sec.dataset.goes) { sec.dataset.goes = '1'; sec.addEventListener('click', go); sec.addEventListener('keydown', go); }
    const T = D.teams || {}, logo = (t, s = 20) => NFLE.fmt.logo(T, t, s), nick = t => (T[t] || {}).nick || t;
    // projections: the top projected player at each position
    const P = Object.entries(D.players || {}).map(([pid, p]) => Object.assign({ pid }, p));
    // (as Rankings: a player under 50% to play doesn't lead with his "if he plays" number)
    const plays = p => (p.play != null ? p.play : 1 - (p.inactive || 0)) >= 0.5;
    const top = ['QB', 'RB', 'WR', 'TE'].map(pos => P.filter(p => p.pos === pos && p.proj != null && plays(p)).sort((a, b) => b.proj - a.proj)[0]).filter(Boolean);
    const proj = top.map(p => `<li><span class="posb posb-${esc(p.pos)}">${esc(p.pos)}</span>${logo(p.team, 18)}<span class="hm-n"><button type="button" class="nm-link hm-nl" data-open-pid="${esc(p.pid)}">${esc(p.name)}</button></span><b class="hm-v">${f1(p.proj)}</b></li>`).join('');
    // power: the top four, net points per game vs an average team
    const pw = (D.power || []).slice().sort((a, b) => a.rank - b.rank).slice(0, 4)
      .map(t => `<li><span class="hm-rk">${t.rank}</span>${logo(t.team)}<span class="hm-n"><span class="tm-open hm-nl" data-tm="${esc(t.team)}">${esc(t.nick || nick(t.team))}</span></span><span class="hm-m">${esc(t.record || '')}</span><b class="hm-v">${signed(t.net)}</b></li>`).join('');
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
    // (owner 2026-10-29: "make the fantasy section preview the active team if there is one"): this week's matchup, each
    // side's best QB-TE lineup from our projections re-scored to the league's settings (as Rankings does), and his top
    // projected players with their tags
    const SC = D.score || {}, built = SC.built, keys = SC.keys || [];
    const sc = (c, w, pos) => (c || []).reduce((t, v, i) => t + (v || 0) * (w[keys[i]] || 0), 0) + (pos === 'TE' ? ((c || [])[5] || 0) * (w.te_bonus || 0) : 0);
    const lproj = p => { if (p.proj == null) return null; const w = mine && mine.w;
      if (!w || !built || !p.sc || !p.sc.pj) return p.proj;
      const base = sc(p.sc.pj, built, p.pos), now = sc(p.sc.pj, w, p.pos); return base > 0.3 ? p.proj * now / base : now; };
    const lineup = ids => {
      const lg = (mine && mine.lg) || {}, n = k => +lg[k] || 0;
      const pool = (ids || []).map(pid => D.players && D.players[pid] ? Object.assign({ pid, lp: lproj(D.players[pid]) }, D.players[pid]) : null)
        .filter(p => p && p.lp != null && plays(p)).sort((a, b) => b.lp - a.lp);
      const used = new Set(), take = (ok, k) => { const out = []; for (const p of pool) { if (out.length >= k) break; if (!used.has(p.pid) && ok(p)) { used.add(p.pid); out.push(p); } } return out; };
      const st = [...take(p => p.pos === 'QB', n('QB') || 1), ...take(p => p.pos === 'RB', n('RB') || 2), ...take(p => p.pos === 'WR', n('WR') || 2),
                  ...take(p => p.pos === 'TE', n('TE') || 1), ...take(p => ['RB', 'WR', 'TE'].includes(p.pos), n('flex')), ...take(p => ['QB', 'RB', 'WR', 'TE'].includes(p.pos), n('superflex'))];
      return { total: st.reduce((t, p) => t + p.lp, 0), st };
    };
    const tagOf = p => { const s = String(p.status || ''); return /^Out|^IR|Injured Reserve/i.test(s) ? 'O' : /^Doubt/i.test(s) ? 'D' : /^Quest/i.test(s) ? 'Q' : ''; };
    let fant = '<p class="hm-p">Connect your Sleeper or ESPN league: the best lineup each week, waiver adds by position and trade checks, under your league\'s scoring.</p>';
    if (mine && mine.league) {
      const me = lineup(mine.mine), op = mine.opp && mine.opp.length ? lineup(mine.opp) : null;
      const top = me.st.slice().sort((a, b) => b.lp - a.lp).slice(0, 4);
      const vs = op && op.st.length ? `<div class="hm-vs"><span><small>You</small><b>${f1(me.total)}</b></span><span class="hm-vsd muted">vs</span><span><small>${esc(mine.oppName || 'Opponent')}</small><b>${f1(op.total)}</b></span></div>` : '';
      fant = `<p class="hm-p hm-lg">${esc(mine.league)}</p>${vs}${top.length ? `<ul class="hm-l">${top.map(p => `<li><span class="posb posb-${esc(p.pos)}">${esc(p.pos)}</span>${logo(p.team, 18)}<span class="hm-n"><button type="button" class="nm-link hm-nl" data-open-pid="${esc(p.pid)}">${esc(p.name)}</button>${tagOf(p) ? ` <span class="hm-tag hm-tag-${tagOf(p)}">${tagOf(p)}</span>` : ''}</span><b class="hm-v">${f1(p.lp)}</b></li>`).join('')}</ul>` : ''}
        <p class="hm-f">Projected starters (QB-TE) in your league's scoring &middot; lineup, waivers and trades in Fantasy</p>`;
    }
    const wk = D.week ? `Week ${D.week}` : 'This week';
    // a tile opens its tab; a player or team named inside it opens that card instead (a link can't hold links)
    const tile = (href, label, body) => `<div class="hm-t" role="link" tabindex="0" data-href="#${href}"><div class="hm-k">${label}<span class="hm-go" aria-hidden="true">&rsaquo;</span></div>${body}</div>`;
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
        ${tile('league/lineup', mine && mine.league ? 'Your fantasy team' : 'Get fantasy advice', fant)}
        <div class="hm-news" hidden></div>
      </div></div>`;
    NFLE.notable().then(doc => drawNotable(sec.querySelector('.hm-news'), doc, logo));
  };
  // Notable moves (owner 2026-10-29): the last three weeks' trades, signings, releases, season-ending injuries and
  // suspensions of players our numbers care about (tools/notable_build.py), newest first; free agency's bursts (8+
  // within 3 days) fold into one dated card (owner: "we'll eval it in march")
  const DAYS = 21, MAX = 6, BURST = 8;  // 8+ in 3 days: free agency, not a trade deadline week
  const dayOf = d => new Date(d + 'T12:00:00');
  const short = d => dayOf(d).toLocaleDateString([], { month: 'short', day: 'numeric' });
  const drawNotable = (box, doc, logo) => {
    if (!box || !doc || !(doc.items || []).length) return;
    const F = NFLE.notableFmt, today = new Date();
    const items = doc.items.filter(i => (today - dayOf(i.date)) / 864e5 <= DAYS);
    if (!items.length) return;
    const row = it => {
      const p = it.players[0], more = it.players.length - 1, why = F.why(it, p);
      const route = it.kind === 'trade' || it.kind === 'signing' ? `${p.from ? logo(p.from, 16) : ''}<span class="hm-arrow" aria-hidden="true">&rsaquo;</span>${logo(p.to || it.team, 16)}` : logo(it.team || p.from, 16);
      return `<li class="hm-nv"><div class="hm-nv1"><span class="nv-k nv-${esc(it.kind)}">${esc(F.label(it.kind))}</span>
          <button type="button" class="nm-link hm-nl" data-open-pid="${esc(p.pid)}">${esc(p.name)}</button>${p.pos ? `<span class="posb posb-${esc(p.pos)}">${esc(p.pos)}</span>` : ''}
          ${more ? `<span class="hm-m" title="${esc(it.players.slice(1).map(x => x.name).join(', '))}">+${more}</span>` : ''}<span class="hm-route">${route}</span></div>
        <div class="hm-nv2">${[`<span>${esc(short(it.date))}</span>`, esc(F.detail(it, p)), esc(why.join(', '))].filter(Boolean).join(' &middot; ')}</div></li>`;
    };
    // bursts: a run of 5+ moves, each within 3 days of the run's newest one
    const blocks = [];
    for (let i = 0; i < items.length;) {
      let j = i;
      while (j + 1 < items.length && (dayOf(items[i].date) - dayOf(items[j + 1].date)) / 864e5 <= 3) j++;
      const run = items.slice(i, j + 1);
      if (run.length >= BURST) {
        const top = run.slice().sort((a, b) => (b.players[0].ovr || 0) - (a.players[0].ovr || 0)).slice(0, 3).map(x => x.players[0].name);
        const fa = run.filter(x => x.kind === 'signing').length > run.length / 2;
        blocks.push(`<li class="hm-dgw"><details class="hm-dg"><summary><span class="nv-k nv-signing">${fa ? 'Free agency' : 'Busy days'}</span>
          <b>${run.length} notable moves</b> <span class="muted">${esc(short(run[run.length - 1].date))}&ndash;${esc(short(run[0].date))} &middot; ${esc(top.join(', '))}</span></summary>
          <ul class="hm-l">${run.map(row).join('')}</ul></details></li>`);
      } else run.forEach(x => blocks.push(row(x)));
      i = j + 1;
    }
    box.innerHTML = `<div class="hm-t" role="link" tabindex="0" data-href="#players/moves"><div class="hm-k">Notable moves<span class="hm-go" aria-hidden="true">&rsaquo;</span></div>
      <ul class="hm-l">${blocks.slice(0, MAX).join('')}</ul>
      <p class="hm-f">Trades, signings, releases and season-ending injuries of players our numbers rate highly &middot; all of them in Moves</p></div>`;
    box.hidden = false;
  };
})();
