// Players > Rankings, rendered in the browser from the week JSON (DATA.players + DATA.rk; report.week_data). Same
// look and behavior as the server-rendered table it replaces: the scoring & league panel re-scores every projection
// from its stat line (pj = projected stats, ss = season, wk = weekly, ac = actual, all in score.keys order), tiers
// and roster slots follow the league, FLEX = RB / WR / TE together (top 150) with the experts' flex rank, Last 5
// bars, pinned name column. Live scores (gamecast.js) paint the Actual cells (tr.main[data-espn] td.actc).
(() => {
  const NFLE = window.NFLE, esc = NFLE.esc;
  const LS_KEY = 'nfledge-scoring';
  const POS = ['QB', 'RB', 'WR', 'TE', 'FLEX'];
  const FLEX_DEPTH = 150;  // a 14-team 2RB/2WR/1TE/1FLEX league starts 84 flex-eligible players; 150 adds waiver depth
  const f0 = v => v == null ? '' : String(Math.round(v));
  const f1 = v => v == null || isNaN(v) ? '' : (Math.round(v * 10) / 10).toFixed(1);
  const sgn = v => v == null ? '' : Math.abs(v) < 0.05 ? '0.0' : `${v > 0 ? '+' : ''}${f1(v)}`;
  const nameParts = n => { const i = String(n).indexOf(' '); return i < 0 ? [n, '', ''] : [n[0], n.slice(1, i), n.slice(i + 1)]; };
  const logoSrc = (url, size) => !url ? '' : !/a\.espncdn\.com\/i\/teamlogos\//.test(url) ? url
    : `https://a.espncdn.com/combiner/i?img=${encodeURIComponent(new URL(url).pathname)}&w=${size * 3}&h=${size * 3}`;

  NFLE.areas.rankings = {
    mount(sec) {
      const week = () => new Promise(ok => { const t0 = Date.now(); const f = () => { const d = NFLE.weekData && NFLE.weekData(); if (d || Date.now() - t0 > 15000) ok(d || null); else setTimeout(f, 100); }; f(); });
      week().then(D => { if (D && D.rk) build(sec, D); });
    },
  };

  function build(sec, D) {
    const SC = D.score, RK = D.rk, TEAMS = D.teams || {};
    const nweek = (D.week || 1) - 1;
    const logo = (t, size) => { const i = TEAMS[t] || {}; return i.logo ? `<span class="logo" style="background:${esc(i.logo_bg || '#333')}"><img src="${esc(logoSrc(i.logo, size))}" alt="${esc(t)}" width="${size}" height="${size}" loading="lazy"></span>` : ''; };
    const rowStyle = t => { const i = TEAMS[t] || {}; return `--tc:${i.color || '#666'};--tc2:${i.color2 || '#999'};--tfg:#ffffff`; };
    const defaults = () => ({ preset: 'Half PPR', w: { ...SC.presets['Half PPR'] }, lg: { teams: SC.league.teams, ...SC.league.starters, flex: SC.league.flex, superflex: 0 } });
    let state = defaults();
    try { const s = JSON.parse(localStorage.getItem(LS_KEY) || 'null'); if (s && s.w && s.lg) state = s; } catch (e) { /* default */ }
    const pts = (c, w, pos) => (c || []).reduce((t, v, i) => t + v * (w[SC.keys[i]] || 0), 0) + (pos === 'TE' ? (c || [])[5] * (w.te_bonus || 0) : 0);
    const all = Object.entries(D.players).map(([pid, p]) => Object.assign({ pid }, p));
    let pos = 'QB', tables = {}, q = '';

    // -- markup -----------------------------------------------------------------------------------------------
    sec.innerHTML = `<div class="sec-head"><div><h2>Weekly rankings</h2><p><span id="scoreSub">Half-PPR</span> projections if active, with realistic ranges. Tap a player for his page.</p></div></div>
      <details class="howto"><summary>How to read</summary><div>
        <b>Projection</b> assumes the player is active (NFL availability is yes/no, so injured players show an Inactive% instead of a discount). Tap a player for his range of outcomes.
        <b>#</b> is our rank; the number in parentheses is the FantasyPros expert consensus rank ("lw" = last week's, until Friday).
        <b>Last 5</b>: his last five games this season; green = beat our projection for that game, red = missed it, the white tick is the projection.
        <b>Range</b>: floor to ceiling; 8 times in 10 his score lands inside it.
        <b>Matchup</b>: points the opponent adds to (+) or takes from (-) the projection, vs an average opponent: its Vegas total, the team's play volume and the defense ratings together. Green helps, red hurts; the deeper the color, the bigger the matchup.
        <b>Volume</b>: projected dropbacks / carries / targets; an arrow means his recent usage share has moved up or down from his longer-run share.
        <b>Team pts</b>: points his team is expected to score (Vegas implied total). <b>TD</b>: chance of at least one touchdown (QBs: projected passing TDs).
        <b>vs ECR</b>: how many spots higher (+) or lower (-) we rank him than the expert consensus. Hover a player's name for our one-line take. A yellow edge marks a projection boosted by a teammate's absence.
      </div></details>
      <div class="card">
        <div class="toolbar">
          <div class="seg posbar">${POS.map(p => `<button type="button" data-pos="${p}" class="pos-${p}">${p}</button>`).join('')}</div>
          <input type="search" id="psearch" placeholder="Find a player" aria-label="Find a player">
          <button type="button" class="sbtn" id="scoreBtn" aria-expanded="false" aria-controls="scorePanel">Scoring &amp; league <span id="scoreSum"></span></button>
        </div>
        <div class="spanel" id="scorePanel" hidden>
          <div class="sp-row"><span class="sp-h">Preset</span><div class="sp-presets" id="spPresets"></div></div>
          <div class="sp-grid">
            <div class="sp-col"><div class="sp-h">Points per stat</div>
              ${[['pass_yd', 'Passing yards per point', 1, 1], ['pass_td', 'Passing TD', 0.5], ['interception', 'Interception', 0.5], ['rush_yd', 'Rushing yards per point', 1, 1],
                 ['rush_td', 'Rushing TD', 0.5], ['reception', 'Reception', 0.25], ['rec_yd', 'Receiving yards per point', 1, 1], ['rec_td', 'Receiving TD', 0.5],
                 ['fumble_lost', 'Fumble lost', 0.5], ['te_bonus', 'TE reception bonus', 0.25]]
                .map(([k, l, st, inv]) => `<label>${l} <input type="number" step="${st}"${inv ? ' min="1" data-inv="1"' : ''} data-k="${k}"></label>`).join('')}
            </div>
            <div class="sp-col"><div class="sp-h">League (sets the tiers)</div>
              ${[['teams', 'Teams', 4, 32], ['QB', 'QB', 0, 3], ['RB', 'RB', 0, 4], ['WR', 'WR', 0, 5], ['TE', 'TE', 0, 3], ['flex', 'Flex (RB/WR/TE)', 0, 4], ['superflex', 'Superflex (any)', 0, 2]]
                .map(([k, l, a, b]) => `<label>${l} <input type="number" step="1" min="${a}" max="${b}" data-l="${k}"></label>`).join('')}
              <button type="button" class="sp-reset" id="spReset">Reset to Half PPR, 10 teams</button>
            </div>
          </div>
          <p class="sp-note">Projections are stat lines, so any scoring re-scores them exactly. Blended-in expert ranks and the floor/ceiling ranges are scaled by the same ratio (an approximation). Saved on this device.</p>
        </div>
        ${POS.map(p => `<div class="posview" data-pos="${p}" hidden><div class="rk-tbl"></div><div class="byes-box"></div></div>`).join('')}
      </div>`;

    // -- derived values under the current scoring + league ---------------------------------------------------------
    const derive = () => {
      const { w, lg } = state;
      all.forEach(r => {
        const base = pts(r.sc.pj, SC.built, r.pos), now = pts(r.sc.pj, w, r.pos);
        const ratio = base > 0.3 ? now / base : 1;
        r._proj = base > 0.3 ? r.proj * ratio : now;
        r._q = r.q.map(v => v * ratio);  // p10, p25, p50, p75, p90
        r._ratio = ratio;
        r._fpg = r.sc.g ? pts(r.sc.ss, w, r.pos) / r.sc.g : r.fpg;
        r._act = r.sc.ac ? pts(r.sc.ac, w, r.pos) : r.act;
      });
      const rank = {};
      ['QB', 'RB', 'WR', 'TE'].forEach(p => all.filter(r => r.pos === p).sort((a, b) => b._proj - a._proj).forEach((r, i) => { r._rank = i + 1; rank[r.pid] = i + 1; }));
      const slot = {};
      all.forEach(r => { slot[r.pid] = r._rank <= lg.teams * (lg[r.pos] || 0) ? 'start' : 'bench'; });
      const fill = (ps, n) => all.filter(r => ps.includes(r.pos) && slot[r.pid] === 'bench').sort((a, b) => b._proj - a._proj).slice(0, n).forEach(r => { slot[r.pid] = 'flex'; });
      fill(['RB', 'WR', 'TE'], lg.teams * (lg.flex || 0));
      fill(['QB', 'RB', 'WR', 'TE'], lg.teams * (lg.superflex || 0));
      all.forEach(r => { r._slot = slot[r.pid]; r._tier = `${r.pos}${Math.floor((r._rank - 1) / lg.teams) + 1}`; });
      all.filter(r => ['RB', 'WR', 'TE'].includes(r.pos)).sort((a, b) => b._proj - a._proj).forEach((r, i) => { r._frank = i + 1; });
    };

    // -- cells (same markup and classes as the server template) ----------------------------------------------------
    const l5 = r => {
      const weeks = []; for (let k = Math.max(1, D.week - 5); k < D.week; k++) weeks.push(k);
      if (!weeks.length) return '<span class="l5-none">week 1</span>';
      const byes = new Set(r.byes || []), pend = new Set(r.pend || []), pjw = r.pjw || {};
      const played = Object.fromEntries((r.sc.wk || []).map(x => [x[0], pts(x.slice(1), state.w, r.pos)]));
      const games = weeks.map(k => ({ wk: k, v: played[k], pj: pjw[k] != null ? pjw[k] * r._ratio : null }));
      const W = 96, H = 34, slot = W / 5, bw = slot - 5;
      const top = Math.max(10, ...games.map(g => Math.max(g.v ?? 0, g.v != null ? g.pj || 0 : 0))) * 1.08;
      const y = v => (H - 9) - (H - 11) * Math.max(v, 0) / top;
      return `<svg class="l5s" viewBox="0 0 ${W} ${H}" width="${W}" height="${H}">${games.map((g, i) => {
        const x = i * slot + 2, mid = x + bw / 2;
        let body;
        if (g.v == null) {
          body = byes.has(g.wk) ? `<text x="${mid.toFixed(1)}" y="${H - 13}" class="bye">BYE</text>`
            : pend.has(g.wk) ? `<text x="${mid.toFixed(1)}" y="${H - 13}" class="bye">...<title>Week ${g.wk}: stats not published yet</title></text>`
            : `<line x1="${(x + 3).toFixed(1)}" x2="${(x + bw - 3).toFixed(1)}" y1="${H - 11}" y2="${H - 11}" class="dnp"><title>Week ${g.wk}: did not play</title></line>`;
        } else {
          const cls = g.pj == null ? 'b-none' : g.v >= g.pj ? 'b-hit' : 'b-miss', yt = y(g.v);
          body = `<rect x="${x.toFixed(1)}" y="${yt.toFixed(1)}" width="${bw.toFixed(1)}" height="${Math.max(1.5, H - 9 - yt).toFixed(1)}" rx="2" class="${cls}"><title>Week ${g.wk}: ${f1(g.v)} pts${g.pj != null ? ` · projected ${f1(g.pj)}` : ''}</title></rect>`
            + (g.pj != null ? `<line x1="${(x - 1).toFixed(1)}" x2="${(x + bw + 1).toFixed(1)}" y1="${y(g.pj).toFixed(1)}" y2="${y(g.pj).toFixed(1)}" class="pj"/>` : '');
        }
        return body + `<text x="${mid.toFixed(1)}" y="${H - 0.5}" class="wl">${g.wk}</text>`;
      }).join('')}</svg>`;
    };
    const ecrOf = (r, flex) => flex ? r.ecr_flex : r.ecr;
    const staleOf = (r, flex) => flex ? r.ecr_flex_stale : r.ecr_stale;
    const rankOf = (r, flex) => flex ? r._frank : r._rank;
    const columns = flex => {
      const range = r => `Floor ${f1(r._q[0])} · middle ${f1(r._q[1])}-${f1(r._q[3])} · ceiling ${f1(r._q[4])}`;
      const cols = [
        { key: 'rank', label: '#', num: true, first: 'asc', cls: 'rk', title: "Our rank at the position; in parentheses the FantasyPros expert consensus rank (published Fridays; 'lw' = last week's until then)",
          value: r => rankOf(r, flex), html: r => { const e = ecrOf(r, flex), st = staleOf(r, flex);
            return `<b class="rkn">${rankOf(r, flex)}</b>${e != null ? `<span class="ecr${st ? ' stale' : ''}" title="${st ? 'Last week' : 'Expert consensus'} ${flex ? 'flex ' : ''}rank (FantasyPros${flex ? ' superflex list without QBs' : ''})">(${f0(e)}${st ? '<sup>lw</sup>' : ''})</span>` : ''}`; } },
        { key: 'name', label: 'Player', stick: true, first: 'asc', value: r => r.name, html: r => {
            const [ini, rest, last] = nameParts(r.name);
            const badges = (r.status || r.boost >= 1 || r.low_sample) ? `<div class="badges">${r.status ? `<span class="flag ${r.inactive >= 0.5 ? 'f-out' : 'f-q'}" title="Injury report; practice Wed/Thu/Fri: D = did not practice, L = limited, F = full">${esc(r.status)}</span>` : ''}${r.boost >= 1 ? `<span class="flag f-up" title="Raised by volume vacated by: ${esc(r.boost_from)}">+${f1(r.boost)} inj</span>` : ''}${r.low_sample ? '<span class="flag" title="Few career opportunities: efficiency leans on the position x draft-round prior">low data</span>' : ''}</div>` : '';
            return `<div class="who" title="${esc(r.takeaway)}"><span class="pic${r.photo ? '' : ' nopic'}"><span class="pic-img">${r.photo ? `<img src="${esc(r.photo)}" alt="" width="34" height="34" loading="lazy" onerror="this.closest('.pic').classList.add('nopic')">` : ''}</span><span class="pic-tm">${logo(r.team, 11)}</span></span><div class="nmw"><b class="nm">${flex ? `<span class="posb posb-${esc(r.pos)}">${esc(r.pos)}</span>` : ''}<span class="fn">${esc(ini)}</span>${rest ? `<span class="fn-rest">${esc(rest)}</span><span class="fn-dot">.</span>` : ''}${last ? ` ${esc(last)}` : ''}</b>${badges}</div></div>`; } },
        { key: 'proj', label: 'Proj', num: true, cls: 'projc', title: 'Projected fantasy points under your scoring (tap a player for the full range of outcomes)', value: r => r._proj,
          html: r => `<b class="pv" title="${esc(range(r))}">${f1(r._proj)}</b>` },
        { key: 'range', label: 'Range', num: true, cls: 'rngc', title: 'Floor to ceiling: 8 times in 10 his score lands in this range (10th to 90th percentile of how past projections like this turned out)',
          value: r => r._q[4] - r._q[0], html: r => `<span title="${esc(range(r))}">${Math.round(r._q[0])}&ndash;${Math.round(r._q[4])}</span>` },
        ...(RK.show_act ? [{ key: 'act', label: 'Actual', num: true, cls: 'actc', title: 'What he scored: live during his game (pulsing dot), final once it ends. Green = above his likely range (75th pct), red = below it (25th pct), colored only when final',
          value: r => r._act, html: r => r._act == null ? '' : `<span class="act-v ${r._act > r._q[3] ? 'act-hi' : r._act < r._q[1] ? 'act-lo' : ''}">${f1(r._act)}</span>` }] : []),
        { key: 'fpg', label: 'FP/G', num: true, cls: 'fpgc', title: 'Season fantasy points per game', value: r => r._fpg, html: r => f1(r._fpg) },
        { key: 'tier', label: 'Tier', first: 'asc', cls: 'tierc', value: r => r._rank, html: r => `<span class="tier t-${r._slot}" title="${{ start: 'Starter', flex: 'Flex range', bench: 'Bench depth' }[r._slot]} in a ${state.lg.teams}-team league">${r._tier}</span>` },
        { key: 'l5', label: 'Last 5', sort: false, cls: 'l5', title: 'His last 5 games this season: bar = points scored, green = beat our projection for that game, red = missed it; the tick is our projection', html: l5 },
        { key: 'mu', label: 'Matchup', first: 'desc', cls: 'mu', title: 'Opponent, and the points facing them adds (+) or takes away (-) vs an average opponent: Vegas total, play volume and defense ratings together. Green helps, red hurts; deeper = bigger.',
          value: r => r.mu, html: r => `<span class="opp tm-open" data-tm="${esc(r.opp)}"><span class="vs">${esc(r.home)}</span>${logo(r.opp, 18)}<b>${esc(r.opp)}</b></span><span class="muv" style="color:${esc(r.mu_c || '')}" title="Facing ${esc(r.opp)} instead of an average opponent: ${sgn(r.mu)} pts">${sgn(r.mu)}</span>` },
        { key: 'inactive', label: 'Inactive', cls: 'ctr', title: 'Chance he is inactive: injury (practice pattern + game status) or healthy scratch', value: r => r.inactive,
          html: r => `<span title="${esc(r.inactive_why)}" class="${r.inactive >= 0.5 ? 'pill pill-bad' : r.inactive >= 0.15 ? 'pill pill-warn' : r.inactive >= 0.05 ? 'pill pill-soft' : 'quiet'}">${r.inactive < 0.005 ? '&lt;1%' : `${Math.round(100 * r.inactive)}%`}</span>` },
        { key: 'vol', label: 'Volume', first: 'desc', cls: 'volc', title: 'Projected volume; arrow = his recent usage share has moved up or down from his longer-run share (a role change)',
          value: r => r.vol && r.vol.v, html: r => r.vol ? `<span title="${esc(r.vol.d)}">${esc(r.vol.t)}${r.vol.a === 'up' ? '<i class="va va-up">&#9650;</i>' : r.vol.a === 'down' ? '<i class="va va-down">&#9660;</i>' : ''}</span>` : '' },
        { key: 'imp', label: 'Team pts', num: true, cls: 'impc', title: "Points his team is expected to score this game (Vegas implied total; our model's before lines post): more points, more scoring chances", value: r => r.imp, html: r => f1(r.imp) },
        { key: 'td', label: pos === 'QB' ? 'Pass TD' : 'TD', num: true, cls: 'tdc', title: pos === 'QB' ? 'Projected passing touchdowns (hover for his rushing TD chance)' : 'Chance he scores at least one touchdown',
          value: r => r.td && r.td.v, html: r => r.td ? `<span title="${esc(r.td.d)}">${esc(r.td.t)}</span>` : '' },
        { key: 'vs', label: 'vs ECR', num: true, cls: 'vsc', title: 'Where we rank him vs the FantasyPros expert consensus: +6 = six spots higher than the experts (we like him more), -4 = lower',
          value: r => { const e = ecrOf(r, flex); return e == null ? null : Math.round(e - rankOf(r, flex)); },
          html: r => { const e = ecrOf(r, flex); if (e == null) return ''; const v = Math.round(e - rankOf(r, flex)); return `<span class="vs-n ${v >= 3 ? 'pos' : v <= -3 ? 'neg' : ''}${staleOf(r, flex) ? ' stale' : ''}">${v > 0 ? '+' : ''}${v}</span>`; } },
      ];
      return cols;
    };
    const rowsFor = p => {
      const t = q.trim().toLowerCase();
      const base = p === 'FLEX' ? all.filter(r => ['RB', 'WR', 'TE'].includes(r.pos)).sort((a, b) => b._proj - a._proj).slice(0, FLEX_DEPTH) : all.filter(r => r.pos === p);
      return t ? base.filter(r => r.name.toLowerCase().includes(t)) : base;
    };
    const rowAttrs = r => `style="${rowStyle(r.team)}" data-pid="${esc(r.pid)}" data-espn="${esc(r.espn || '')}" data-team="${esc(r.team)}" data-name="${esc(r.name.toLowerCase())}" data-pos="${esc(r.pos)}"`;
    const rowClass = r => `main teamrow${r.boost >= 1 ? ' boosted' : ''}${r.inactive >= 0.5 ? ' out' : ''}`;
    const byesHtml = p => {
      const list = (RK.byes || {})[p] || [];
      return list.length ? `<div class="byes"><span>On bye</span>${list.map(b => `<span class="bye"><span class="tm-open" data-tm="${esc(b.team)}">${logo(b.team, 16)}</span><button type="button" class="nm-link" data-open-pid="${esc(b.pid)}">${esc(b.name)}</button> <span class="muted">${f1(b.sc && b.sc.g ? pts(b.sc.ss, state.w, p) / b.sc.g : b.fpg)} FP/G</span></span>`).join('')}</div>` : '';
    };
    const draw = (resort = true) => {
      derive();
      POS.forEach(p => {
        const view = sec.querySelector(`.posview[data-pos="${p}"]`);
        if (view.hidden && tables[p] === undefined) return;  // built on first show
        const rows = rowsFor(p);
        if (!tables[p]) tables[p] = NFLE.Table(view.querySelector('.rk-tbl'), { columns: columns(p === 'FLEX'), rows, cls: 'sortable ranks tiles', sort: { key: 'proj', dir: 'desc' }, rowAttrs, rowClass });
        else { tables[p].setColumns(columns(p === 'FLEX')); tables[p].update(rows); if (resort) tables[p].setSort({ key: 'proj', dir: 'desc' }); }
        view.querySelector('.byes-box').innerHTML = byesHtml(p);
      });
      const name = state.preset || 'Custom';
      const sn = document.getElementById('scoreName'); if (sn) sn.textContent = name;
      sec.querySelector('#scoreSub').textContent = name === 'Custom' ? 'Custom-scoring' : name;
      sec.querySelector('#scoreSum').textContent = `· ${name}, ${state.lg.teams} teams`;
      document.dispatchEvent(new Event('nfle-scoring'));  // open player page / live points re-score too
    };
    const showPos = p => {
      pos = p;
      sec.querySelectorAll('.posbar button').forEach(b => b.classList.toggle('on', b.dataset.pos === p));
      sec.querySelectorAll('.posview').forEach(v => { v.hidden = v.dataset.pos !== p; });
      if (!tables[p]) { tables[p] = null; draw(false); } else tables[p].layout();
    };
    sec.querySelector('.posbar').addEventListener('click', e => { const b = e.target.closest('[data-pos]'); if (b) showPos(b.dataset.pos); });
    sec.querySelector('#psearch').oninput = e => { q = e.target.value; POS.forEach(p => tables[p] && tables[p].update(rowsFor(p))); };
    window.nfleWeights = () => state.w;
    window.nfleApplyScoring = () => draw();

    // -- scoring & league panel --------------------------------------------------------------------------------
    const btn = sec.querySelector('#scoreBtn'), panel = sec.querySelector('#scorePanel'), presetBox = sec.querySelector('#spPresets');
    const sameW = (a, b) => Object.keys(b).every(k => Math.abs((a[k] || 0) - (b[k] || 0)) < 1e-9);
    const sync = () => {
      panel.querySelectorAll('input[data-k]').forEach(i => { const v = state.w[i.dataset.k]; i.value = i.dataset.inv ? (v ? Math.round(1 / v) : '') : v; });
      panel.querySelectorAll('input[data-l]').forEach(i => { i.value = state.lg[i.dataset.l] ?? 0; });
      presetBox.querySelectorAll('button').forEach(b => b.classList.toggle('on', b.textContent === state.preset));
    };
    const save = () => { try { localStorage.setItem(LS_KEY, JSON.stringify(state)); } catch (e) { /* private mode */ } };
    const changed = () => { state.preset = Object.keys(SC.presets).find(n => sameW(state.w, SC.presets[n])) || 'Custom'; sync(); draw(); save(); };
    Object.keys(SC.presets).forEach(n => {
      const b = document.createElement('button'); b.type = 'button'; b.textContent = n;
      b.onclick = () => { state.w = { ...SC.presets[n] }; changed(); };
      presetBox.appendChild(b);
    });
    panel.querySelectorAll('input[data-k]').forEach(i => i.onchange = () => { const v = parseFloat(i.value); if (isNaN(v)) return; state.w[i.dataset.k] = i.dataset.inv ? (v > 0 ? 1 / v : 0) : v; changed(); });
    panel.querySelectorAll('input[data-l]').forEach(i => i.onchange = () => { const v = parseInt(i.value, 10); if (isNaN(v) || v < 0) return; state.lg[i.dataset.l] = i.dataset.l === 'teams' ? Math.max(4, v) : v; changed(); });
    sec.querySelector('#spReset').onclick = () => { state = defaults(); changed(); };
    btn.onclick = () => { panel.hidden = !panel.hidden; btn.setAttribute('aria-expanded', String(!panel.hidden)); };
    sync();
    showPos('QB');
  }
})();
