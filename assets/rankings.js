// Players > Rankings, rendered in the browser from the week JSON (DATA.players + DATA.rk; report.week_data). Same
// look and behavior as the server-rendered table it replaces: the scoring & league panel re-scores every projection
// from its stat line (pj = projected stats, ss = season, wk = weekly, ac = actual, all in score.keys order), tiers
// and roster slots follow the league, FLEX = RB / WR / TE together (top 150) with the experts' flex rank, Last 5
// bars, pinned name column. Live scores (gamecast.js) paint the Actual cells (tr.main[data-espn] td.actc).
// Rest of season (owner 2026-10-15): a second mode on the same tab, from data/ros.json (tools/ros_build.py): each
// remaining week's expected stat line through week 17 x his chance to play, summed under the viewer's scoring (exact:
// points are linear in the stats); this week's game drops out once it kicks off.
(() => {
  const NFLE = window.NFLE, esc = NFLE.esc;
  const LS_KEY = 'nfledge-scoring';
  const POS = ['QB', 'RB', 'WR', 'TE', 'FLEX', 'K', 'DST'];
  const OUT_LINE = 0.9;
  // Two worlds in one cell (owner 2026-10-20, Lamar Jackson / Tyler Huntley): when a player is 20-80% to play, he and
  // the teammate whose role hangs on him show both projections: the likelier world as the number (it sorts), the other
  // dimmed beneath. 20-80%: the other world is at least a 1-in-5 chance (the Q tag's 32-88% would add it for an 85%
  // starter's backup, an outcome that rarely happens).
  const TWO_LO = 0.2, TWO_HI = 0.8;  // inactive chance at which a player projects 0 (owner 2026-10-16: under 10% to play)
  const KDP = ['K', 'DST'];  // kickers / team defenses: data/kdst.json, standard ESPN scoring (owner 2026-10-15)
  const POS_LABEL = { DST: 'D/ST' };
  const FLEX_DEPTH = 150;  // a 14-team 2RB/2WR/1TE/1FLEX league starts 84 flex-eligible players; 150 adds waiver depth
  const f0 = v => v == null ? '' : String(Math.round(v));
  const f1 = v => v == null || isNaN(v) ? '' : (Math.round(v * 10) / 10).toFixed(1);
  const sgn = v => v == null ? '' : Math.abs(v) < 0.05 ? '0.0' : `${v > 0 ? '+' : ''}${f1(v)}`;

  NFLE.areas.rankings = {
    mount(sec) {
      NFLE.week().then(D => { if (D && D.rk) build(sec, D); });
    },
  };

  function build(sec, D) {
    const SC = D.score, RK = D.rk, TEAMS = D.teams || {};
    const nweek = (D.week || 1) - 1;
    const logo = (t, size) => NFLE.fmt.logo(TEAMS, t, size), rowStyle = t => NFLE.fmt.rowStyle(TEAMS, t);
    // IDP (defenders) ride in the same weights; presets set the offense only (owner 2026-10-18)
    const IDP = SC.idp || {};
    const defaults = () => ({ preset: 'Half PPR', w: { ...SC.presets['Half PPR'], ...IDP }, lg: { teams: SC.league.teams, ...SC.league.starters, flex: SC.league.flex, superflex: 0 } });
    // the active claimed fantasy team (league.js shareMine) sets the scoring by default (owner 2026-10-20); picking a
    // preset or editing a value is the viewer's own choice (src 'own') and sticks until they pick their league again
    const mine = () => { try { const m = JSON.parse(localStorage.getItem('nfledge-mine') || 'null'); return m && m.w && m.league ? m : null; } catch (e) { return null; } };
    const fromTeam = m => ({ src: 'team', preset: m.league, w: { ...IDP, ...m.w },
                             lg: m.lg && m.lg.teams ? { ...m.lg } : { teams: SC.league.teams, ...SC.league.starters, flex: SC.league.flex, superflex: 0 } });
    const start = () => { const m = mine(); return m ? fromTeam(m) : defaults(); };
    let state = null;
    try { const s = JSON.parse(localStorage.getItem(LS_KEY) || 'null'); if (s && s.w && s.lg && s.src === 'own') state = s; } catch (e) { /* default */ }
    state = state || start();
    state.w = { ...IDP, ...state.w };  // saved before IDP existed: its defaults
    const pts = (c, w, pos) => (c || []).reduce((t, v, i) => t + v * (w[SC.keys[i]] || 0), 0) + (pos === 'TE' ? (c || [])[5] * (w.te_bonus || 0) : 0);
    const all = Object.entries(D.players).map(([pid, p]) => Object.assign({ pid }, p));
    let pos = 'QB', tables = {}, q = '', mode = 'week', ROS = null, rosAll = [];
    const rosTables = {};
    try { if (localStorage.getItem('nfledge-rk-mode') === 'ros') mode = 'ros'; } catch (e) { /* default */ }
    const rosOk = !D.archive;  // a past week's page: 'rest of season from now' means nothing there, weekly only
    if (!rosOk) mode = 'week';

    // -- markup -----------------------------------------------------------------------------------------------
    sec.innerHTML = `<div class="seg rk-mode" role="tablist"><button type="button" role="tab" data-mode="week">Weekly</button><button type="button" role="tab" data-mode="ros">Rest of season</button></div>
      <div class="sec-head rk-h-week"><div><h2>Weekly rankings</h2><p><span id="scoreSub">Half PPR</span> projections if active, with realistic ranges. Tap a player for his page.</p></div></div>
      <div class="sec-head rk-h-ros" hidden><div><h2>Rest-of-season rankings</h2><p><span class="rosSub">Half PPR</span> points expected from now through week 17, each game weighted by his chance to play. Tap a player for his page.</p></div></div>
      <details class="howto rk-h-ros" hidden><summary>How to read</summary><div>
        <dl class="ht">
          <dt>ROS pts</dt><dd>Points we expect from him from now through week 17, in your scoring. Each game is projected against its real opponent, then scaled by his chance to play.</dd>
          <dt>Pts/G</dt><dd>Those points per game he's expected to play.</dd>
          <dt>Exp G</dt><dd>Games he's expected to play (byes and expected absences don't count).</dd>
          <dt>Sched</dt><dd>Points his remaining opponents add (+) or take away (−) in total.</dd>
          <dt>Weeks</dt><dd>Each week's expected points. B = bye, dash = expected to sit, faded = under 50% to play.</dd>
        </dl>
        <p class="ht-note">Later weeks are less certain: they use today's roles and ratings. This week's game counts until kickoff.</p>
      </div></details>
      <details class="howto rk-h-week"><summary>How to read</summary><div>
        <dl class="ht">
          <dt>#</dt><dd>Our rank at the position.</dd>
          <dt>Pts</dt><dd>Points if he plays (hover for his floor-to-ceiling range). Injured players show their chance to play instead of a discount, since playing is yes/no. Once his game starts: his actual points, with the projection under it.</dd>
          <dt>Matchup</dt><dd>Points this opponent adds (+) or takes away (−) vs an average one. Green helps, red hurts; deeper = bigger. A wind, rain or snow mark = weather worth knowing at kickoff.</dd>
          <dt>Grd</dt><dd>His Edge grade: three seasons of fantasy output, ranked within his position (50 to 99).</dd>
          <dt>Last 5</dt><dd>His last five games. Green beat our projection, red missed it; the white tick is the projection.</dd>
          <dt>Snap%</dt><dd>His share of his offense's snaps this season.</dd>
          <dt>TD</dt><dd>Chance of at least one touchdown (QBs: projected passing TDs).</dd>
        </dl>
        <p class="ht-note">Tap a player for his page. A green "+ inj" tag = projection raised by a teammate's absence.</p>
      </div></details>
      <div class="card">
        <div class="toolbar">
          <div class="seg posbar">${POS.map(p => `<button type="button" data-pos="${p}" class="pos-${p}">${POS_LABEL[p] || p}</button>`).join('')}</div>
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
            <div class="sp-col"><div class="sp-h">Defenders (IDP)</div>
              ${[['idp_tkl_solo', 'Solo tackle'], ['idp_tkl_ast', 'Assisted tackle'], ['idp_tkl_loss', 'Tackle for loss'], ['idp_sack', 'Sack'],
                 ['idp_qb_hit', 'QB hit'], ['idp_int', 'Interception'], ['idp_pass_def', 'Pass defended'], ['idp_ff', 'Forced fumble'],
                 ['idp_fum_rec', 'Fumble recovery'], ['idp_def_td', 'Defensive TD'], ['idp_safe', 'Safety'], ['idp_blk_kick', 'Blocked kick']]
                .map(([k, l]) => `<label>${l} <input type="number" step="0.5" data-k="${k}"></label>`).join('')}
            </div>
            <div class="sp-col"><div class="sp-h">League (sets the tiers)</div>
              ${[['teams', 'Teams', 4, 32], ['QB', 'QB', 0, 3], ['RB', 'RB', 0, 4], ['WR', 'WR', 0, 5], ['TE', 'TE', 0, 3], ['flex', 'Flex (RB/WR/TE)', 0, 4], ['superflex', 'Superflex (any)', 0, 2]]
                .map(([k, l, a, b]) => `<label>${l} <input type="number" step="1" min="${a}" max="${b}" data-l="${k}"></label>`).join('')}
              <button type="button" class="sp-reset" id="spReset">Reset to Half PPR, 10 teams</button>
            </div>
          </div>
          <p class="sp-note">Projections are stat lines, so any scoring re-scores them exactly. Blended-in expert ranks and the floor/ceiling ranges are scaled by the same ratio (an approximation). Saved on this device.</p>
        </div>
        ${POS.map(p => `<div class="posview" data-pos="${p}" hidden><div class="rk-tbl"></div><div class="byes-box"></div><div class="ros-tbl" hidden></div></div>`).join('')}
        <p class="muted ros-note" hidden></p>
      </div>`;

    // -- derived values under the current scoring + league ---------------------------------------------------------
    // game grades for final scores (owner 2026-10-17: white while live, "the grade coloring once the game is over"):
    // this season's pool of qualified games as percentiles (tools/player_logs.py), the game log's Grd scale
    let GPOOL = null;
    NFLE.load('data/grades/game_pool.json').then(j => { GPOOL = j; if (mode === 'week') draw(false); }).catch(() => {});
    const gamePct = (pos, v) => { const q = GPOOL && GPOOL.q[pos]; if (!q || v == null) return null;
      let i = 0; while (i < 100 && q[i + 1] <= v) i++;
      return i >= 100 ? 99 : Math.min(99, Math.round(i + (q[i + 1] > q[i] ? (v - q[i]) / (q[i + 1] - q[i]) : 0))); };
    const GAME_OF = Object.fromEntries((D.games || []).flatMap(g => [[g.away.team, g.id], [g.home.team, g.id]]));
    const derive = () => {
      const { w, lg } = state;
      all.forEach(r => {
        const base = pts(r.sc.pj, SC.built, r.pos), now = pts(r.sc.pj, w, r.pos);
        const ratio = base > 0.3 ? now / base : 1;
        r._proj = base > 0.3 ? r.proj * ratio : now;
        // Near-certain outs (owner 2026-10-16: under 10% to play) project 0 and sink below the active players; the
        // line if he does play stays beside it. 10-50% keep their if-active line (owner's call).
        r._ifact = r._proj;
        r._likelyOut = (r.play != null ? 1 - r.play : r.inactive) >= OUT_LINE;  // (AY3) out or a near-certain healthy scratch
        if (r._likelyOut) r._proj = 0;
        const pl = 1 - (r.inactive || 0), lastNm = n => String(n || '').split(' ').slice(1).join(' ') || n;
        r._two = null;
        if (!r._likelyOut && pl >= TWO_LO && pl <= TWO_HI) {  // his own two worlds: plays / sits (0)
          r._two = pl >= 0.5 ? { alt: 0, txt: 'if he sits' } : { alt: r._proj, txt: 'if he plays', dim: true };
          if (pl < 0.5) r._proj = 0;
        } else if (r.cond && 1 - r.cond[2] >= TWO_LO && 1 - r.cond[2] <= TWO_HI) {  // a teammate's: the other world
          const [nm, , pSit, plays, sits] = r.cond;
          r._two = pSit >= 0.5 ? { alt: plays * ratio, txt: `if ${lastNm(nm)} plays` } : { alt: sits * ratio, txt: `if ${lastNm(nm)} sits` };
        }
        r._q = r.q.map(v => v * ratio);  // p10, p25, p50, p75, p90
        r._ratio = ratio;
        r._fpg = r.sc.g ? pts(r.sc.ss, w, r.pos) / r.sc.g : r.fpg;
        r._act = r.sc.ac ? pts(r.sc.ac, w, r.pos) : r.act;
        // live (gamecast.js polls ESPN and shares NFLE.live): his box-score line and whether his game is on / over
        const lv = NFLE.live, st = lv && GAME_OF[r.team] && lv.byGame[GAME_OF[r.team]], ln = lv && r.espn && lv.lines[r.espn];
        if (ln && ln.line) r._act = pts(ln.line, w, r.pos);
        // the same output in the site's scoring, for the game grade (the Grd pool is built in it)
        r._actSite = ln && ln.line ? pts(ln.line, SC.built, r.pos) : r.sc.ac ? pts(r.sc.ac, SC.built, r.pos) : null;
        r._live = !!(st && st.state === 'in');
        if (r._act == null && st && st.state !== 'pre') r._act = 0;  // kicked off, no stats yet
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
    const nameCell = (r, flex) => {
      // his chance to play rides on the injury badge when it's in doubt (owner 2026-10-17: the Play% column read >99%
      // for nearly everyone)
      const pct = r.inactive >= 0.05 ? `<span class="flag fl-play ${r.inactive >= 0.5 ? 'fl-bad' : r.inactive >= 0.15 ? 'fl-warn' : ''}" title="${esc(r.inactive_why || '')}">${NFLE.fmt.toPlay(r.inactive)}</span>` : '';
      // (AY3) healthy-scratch risk is its own chip, never the injury one: "Scratch 30%" (chance he's inactive without an injury)
      const scr = (r.scratch || 0) >= 0.1 ? `<span class="flag fl-scr${r.scratch >= 0.5 ? ' fl-bad' : ''}" title="${esc(r.play_why || 'Healthy-scratch risk')}">Scratch ${Math.round(100 * r.scratch)}%</span>` : '';
      // no "+X inj" flag or highlight in the list (owner 2026-10-20): the teammate-injury boost is in the projection;
      // its detail is on the player's page
      const badges = (r.status || r.low_sample || pct || scr) ? `<div class="badges">${NFLE.injTag(r.status, r.inactive)}${pct}${scr}${r.low_sample ? '<span class="flag" title="Few career opportunities: efficiency leans on the position x draft-round prior">low data</span>' : ''}</div>` : '';
      // first name on top, last name below, badges to the right (owner 2026-10-17); scrolled sideways the pinned
      // column narrows and each line truncates (rankings.css)
      const [first, lastN] = NFLE.fmt.split(r.name);
      // his rank rides on the photo's corner once the # column scrolls away (owner 2026-10-17; rankings.css)
      const rk = r._rrank != null ? (flex ? r._rfrank : r._rrank) : (flex ? r._frank : r._rank);
      return `<div class="who" title="${esc(r.takeaway || '')}"><span class="pic${r.photo ? '' : ' nopic'}"${NFLE.fmt.picStyle(TEAMS, r.team)}>${rk != null ? `<span class="pic-rk" aria-hidden="true">${rk}</span>` : ''}<span class="pic-img">${r.photo ? `<img src="${esc(r.photo)}" alt="" width="34" height="34" loading="lazy" onerror="this.closest('.pic').classList.add('nopic')">` : ''}</span><span class="pic-tm">${logo(r.team, 11)}</span></span><div class="nmw nm2w"><span class="nm2"><span class="l1">${flex ? `<span class="posb posb-${esc(r.pos)}">${esc(r.pos)}</span> ` : ''}${esc(first)}</span><b class="nm l2">${esc(lastN)}</b></span>${badges ? badges.replace('<div class="badges">', '<div class="badges nm-b">') : ''}</div></div>`;
    };
    // The projection shown is the likelier world for an uncertain teammate (owner 2026-10-15: availability is binary).
    // The "+0.5 if X plays" line under it is gone from the table (owner 2026-10-20): that detail is on the player's page.
    const rankOf = (r, flex) => flex ? r._frank : r._rank;
    // weather that matters (owner 2026-10-17): a small mark beside the opponent only for wind 15+ mph, a 50%+ chance
    // of rain or any snow at kickoff (live week, outdoor games; data.forecast_conditions); the forecast in its tooltip
    const WX = Object.fromEntries((D.games || []).flatMap(g => g.wx ? [[g.away.team, g.wx], [g.home.team, g.wx]] : []));
    const ICON = {
      wind: '<path d="M3 8h9a3 3 0 1 0-3-3M3 12h13a3 3 0 1 1-3 3M3 16h6"/>',
      rain: '<path d="M7 14a4 4 0 0 1 .5-8A5 5 0 0 1 17 7a3.5 3.5 0 0 1 0 7z"/><path d="M8 17l-1 3M12 17l-1 3M16 17l-1 3"/>',
      // six arms, each with a chevron branch near its tip (owner: a plain asterisk read as a footnote mark)
      snow: '<path d="M12 3v18M4.2 7.5l15.6 9M4.2 16.5l15.6-9"/><path d="M9.5 7L12 4.5 14.5 7M9.5 17l2.5 2.5 2.5-2.5'
        + 'M15.08 7.34l3.42.91-.92 3.42M8.92 16.66l-3.42-.91.92-3.42M8.92 7.34l-3.42.91.92 3.42M15.08 16.66l3.42-.91-.92-3.42"/>',
    };
    const wxMark = t => { const w = WX[t]; if (!w) return '';
      const k = w.snow > 0 ? 'snow' : w.pop >= 50 ? 'rain' : w.wind >= 15 ? 'wind' : null;
      if (!k) return '';
      const tip = [w.wind != null ? `wind ${Math.round(w.wind)} mph` : '', w.pop != null ? `${w.pop}% chance of rain` : '', w.snow > 0 ? `${w.snow} cm snow` : ''].filter(Boolean).join(' · ');
      return `<span class="wx wx-${k}" title="Kickoff forecast: ${esc(tip)}"><svg viewBox="0 0 24 24" width="14" height="14" aria-hidden="true">${ICON[k]}</svg></span>`; };
    const columns = (flex, tp = pos) => {  // tp: this table's position (the TD column's label follows it)
      const range = r => `Floor ${f1(r._q[0])} · middle ${f1(r._q[1])}-${f1(r._q[3])} · ceiling ${f1(r._q[4])}`;
      const cols = [
        // the rank carries the tier as its color (owner 2026-10-17: the Tier column only repeated it)
        { key: 'rank', label: '#', num: true, first: 'asc', cls: 'rk', title: 'Our rank at the position. Color = tier in your league: green starter, amber flex range, gray bench',
          value: r => rankOf(r, flex), html: r => `<b class="rkn rk-${r._slot}" title="${{ start: 'Starter', flex: 'Flex range', bench: 'Bench depth' }[r._slot]} in a ${state.lg.teams}-team league (${esc(r._tier)})">${rankOf(r, flex)}</b>` },
        { key: 'name', label: 'Player', stick: true, first: 'asc', value: r => r.name, html: r => nameCell(r, flex) },
        // once his game starts (owner 2026-10-17): what he's scored, the projection dimmed beneath; the sort stays by
        // projection. Live: the dot; final: green above his likely range (p75), red below it (p25)
        // "Pts" (owner 2026-10-17: the column holds projections AND actual scores); each actual is labeled live / final
        { key: 'proj', label: 'Pts', num: true, cls: 'projc', title: 'Fantasy points under your scoring: our projection, until his game starts; then his actual points, marked live or final, with the projection beneath (tap a player for the full range of outcomes)',
          value: r => r._proj,
          html: r => r._act != null
            ? (() => { const g = r._live ? null : gamePct(r.pos, r._actSite);
              // against his own likely range (owner 2026-10-18): white inside p25-p75, green above, red below; live, only
              // green once he's already past it (falling short mid-game isn't a miss yet)
              const lo = r._q[1], hi = r._q[3], tone = r._act > hi ? ' gr-hi' : !r._live && r._act < lo ? ' gr-lo' : '';
              return `<span class="pv-stack"><b class="pv act-v${tone}" title="${r._live ? 'Live' : 'Final'}: ${f1(r._act)} pts · projected ${f1(r._proj)}${r._likelyOut ? ` (ruled out; ${f1(r._ifact)} if he had played)` : ''}${g != null ? ` · game grade ${50 + Math.round(g * 49 / 99)}` : ''}"><span class="pv-tag">${r._live ? '<span class="live-dot"></span>live' : 'final'}</span>${f1(r._act)}</b><span class="pv-was">proj <b>${f1(r._proj)}</b></span></span>`; })()
            : r._likelyOut
              ? `<b class="pv" title="Under 10% to play: projected 0">0.0</b><span class="ifact" title="${esc(range(r))}">if he plays ${f1(r._ifact)}</span>`
              : r._two
              ? `<b class="pv${r._two.dim ? ' pv-dim' : ''}" title="${esc(range(r))}">${f1(r._proj)}</b><span class="ifact">${f1(r._two.alt)} ${esc(r._two.txt)}</span>`
              : `<b class="pv" title="${esc(range(r))}">${f1(r._proj)}</b>` },
        // Matchup right after Proj (owner 2026-10-17: the two numbers a start / sit call hinges on); his team's implied
        // points (the Team pts column) folded into its tooltip
        { key: 'mu', label: 'Matchup', first: 'desc', cls: 'mu', title: 'Opponent, and the points facing them adds (+) or takes away (-) vs an average opponent: Vegas total, play volume and defense ratings together. Green helps, red hurts; deeper = bigger.',
          value: r => r.mu, html: r => `<span class="opp tm-open" data-tm="${esc(r.opp)}"><span class="vs">${esc(r.home)}</span>${logo(r.opp, 18)}<b>${esc(r.opp)}</b></span>${wxMark(r.team)}<span class="muv" style="color:${esc(r.mu_c || '')}" title="Facing ${esc(r.opp)} instead of an average opponent: ${sgn(r.mu)} pts${r.imp != null ? ` · his team is expected to score ${f1(r.imp)}` : ''}">${sgn(r.mu)}</span>` },
        // Grd (owner 2026-10-17, replacing Range: the floor-to-ceiling range stays in the Pts tooltip and the card): the
        // Edge grade, the team cards' number (gamecast.js NFLE.gradeOf)
        { key: 'grd', label: 'Grd', num: true, cls: 'grdc', first: 'desc', title: "Edge grade (OVR): three seasons of fantasy output, a percentile within his position (rookies and second-year players: this season's when higher)",
          value: r => { const g = NFLE.gradeOf && NFLE.gradeOf(r.pid); return g ? g.v : -1; },
          html: r => { const g = NFLE.gradeOf && NFLE.gradeOf(r.pid); return g ? NFLE.gradeChip(g) : '<span class="muted">&ndash;</span>'; } },
        // season FP/G folded into its tooltip (owner 2026-10-17: the FP/G column repeated it)
        { key: 'l5', label: 'Last 5', sort: false, cls: 'l5', title: 'His last 5 games this season: bar = points scored, green = beat our projection for that game, red = missed it; the tick is our projection',
          html: r => `<span title="${r._fpg != null ? `Season: ${f1(r._fpg)} FP/G` : ''}">${l5(r)}</span>` },

        // Snap% (owner 2026-10-17, replacing Volume): his share of the offense's snaps this season, the plainest read on role
        { key: 'snap', label: 'Snap%', num: true, cls: 'snapc', first: 'desc', title: "His share of his offense's snaps this season",
          value: r => r.ext && r.ext.snap != null ? r.ext.snap : -1, html: r => r.ext && r.ext.snap != null ? `${Math.round(r.ext.snap * 100)}%` : '' },
        { key: 'td', label: tp === 'QB' ? 'Pass TD' : 'TD', num: true, cls: 'tdc', title: tp === 'QB' ? 'Projected passing touchdowns (hover for his rushing TD chance)' : 'Chance he scores at least one touchdown',
          value: r => r.td && r.td.v, html: r => r.td ? `<span title="${esc(r.td.d)}">${esc(r.td.t)}</span>` : '' },
      ];
      return cols;
    };
    // -- kickers and team defenses --------------------------------------------------------------------------------
    // Each team's kicker / D/ST line per week (this week through 17), scored with standard ESPN rules; the scoring panel
    // applies to QB / RB / WR / TE only.
    let KD = null, KDA = { K: [], DST: [] };
    const KS = NFLE.kdst;
    const loadKD = () => KD ? Promise.resolve(KD) : Promise.all([NFLE.load('data/kdst.json'), NFLE.ui.ready]).then(([j]) => {
      if (!j) throw new Error('no kdst');
      KD = j;
      KDA.K = Object.entries(j.k || {}).map(([team, o]) => ({ pid: o.pid, name: o.name, team, pos: 'K',
        photo: NFLE.ui.headshot(NFLE.ui.ids && NFLE.ui.ids[o.pid]),
        by: Object.fromEntries(o.w.map(([wk, imp, line]) => [wk, { v: KS.kScore(j.k_keys, line, KS.STD_K), imp,
          fga: line.slice(0, 12).reduce((a, b) => a + b, 0), xp: line[12] }])) }));
      KDA.DST = Object.entries(j.dst || {}).map(([team, o]) => ({ pid: `DST-${team}`, name: (TEAMS[team] || {}).nick || team, team, pos: 'DST',
        by: Object.fromEntries(o.w.map(([wk, opp, home, line]) => { const ln = Object.fromEntries(j.d_keys.map((k, i) => [k, line[i]]));
          return [wk, { v: KS.dstScore(ln, KS.STD_D), opp, home: home ? 'vs' : '@', pa: ln.pa_mu, sack: ln.sack, take: ln.int + ln.fum_rec }]; })) }));
      return j;
    });
    // kickoff (ms) of a team's game this week: gameday + gametime are Eastern (EDT from mid-March to early November)
    const kickoff = t => NFLE.fmt.kickoff(D.games, t);
    const oppOf = t => { const g = (D.games || []).find(x => x.away.team === t || x.home.team === t);
      return g ? { opp: g.home.team === t ? g.away.team : g.home.team, home: g.home.team === t ? 'vs' : '@' } : null; };
    const kdRows = (p, m = mode) => {
      const t = q.trim().toLowerCase(), wk = D.week;
      let rows = KDA[p].map(r0 => {
        const e = r0.by[wk], r = Object.assign({}, r0);
        if (m === 'ros') {  // this week's game drops out once it kicks off (as for players)
          const ko = kickoff(r.team), started = ko != null && Date.now() >= ko;
          const ws = Object.entries(r.by).filter(([w]) => +w >= (KD ? KD.from : wk) && !(started && +w === D.week));
          const tot = ws.reduce((a, [, x]) => a + x.v, 0);
          return Object.assign(r, { _v: tot, _games: ws.length, _ppg: ws.length ? tot / ws.length : 0 });
        }
        return e ? Object.assign(r, { _v: e.v, _e: e, _o: oppOf(r.team) }) : null;
      }).filter(Boolean).sort((a, b) => b._v - a._v);
      rows.forEach((r, i) => { r._rank = i + 1; r._tier = `${POS_LABEL[p] || p}${Math.floor(i / state.lg.teams) + 1}`; r._slot = i < state.lg.teams ? 'start' : 'bench'; });
      return t ? rows.filter(r => r.name.toLowerCase().includes(t) || r.team.toLowerCase() === t) : rows;
    };
    const kdWho = r => r.pos === 'DST' ? NFLE.ui.team(r.team, TEAMS, esc(r.team))
      : NFLE.ui.player({ name: r.name, team: r.team, photo: r.photo, sub: r.team }, TEAMS);
    const kdOpp = (opp, home) => opp ? `<span class="opp tm-open" data-tm="${esc(opp)}"><span class="vs">${esc(home)}</span>${logo(opp, 18)}<b>${esc(opp)}</b></span>` : '';
    const kdColumns = p => {
      const head = [
        { key: 'rank', label: '#', num: true, first: 'asc', cls: 'rk', value: r => r._rank, html: r => `<b class="rkn">${r._rank}</b>` },
        { key: 'name', label: p === 'K' ? 'Kicker' : 'Defense', stick: true, first: 'asc', value: r => r.name, html: kdWho }];
      if (mode === 'ros') return [...head,
        { key: 'proj', label: 'ROS pts', num: true, cls: 'projc', title: 'Expected points from this week through week 17, standard ESPN scoring', value: r => r._v, html: r => `<b class="pv">${f0(r._v)}</b>` },
        { key: 'ppg', label: 'Pts/G', num: true, value: r => r._ppg, html: r => f1(r._ppg) },
        { key: 'games', label: 'Games', num: true, title: 'Games left through week 17 (byes excluded)', value: r => r._games, html: r => String(r._games) },
        { key: 'tier', label: 'Tier', first: 'asc', cls: 'tierc', value: r => r._rank, html: r => `<span class="tier t-${r._slot}">${r._tier}</span>` }];
      return [...head,
        { key: 'proj', label: 'Proj', num: true, cls: 'projc', title: 'Projected points, standard ESPN scoring', value: r => r._v, html: r => `<b class="pv">${f1(r._v)}</b>` },
        { key: 'mu', label: 'Matchup', first: 'asc', cls: 'mu', value: r => p === 'DST' ? r._e.opp : (r._o || {}).opp,
          html: r => p === 'DST' ? kdOpp(r._e.opp, r._e.home) : (r._o ? kdOpp(r._o.opp, r._o.home) : '') },
        ...(p === 'K' ? [
          { key: 'imp', label: 'Team pts', num: true, title: "Points his team is expected to score (Vegas implied total; our model's before lines post)", value: r => r._e.imp, html: r => f1(r._e.imp) },
          { key: 'fga', label: 'FG att', num: true, title: 'Expected field-goal attempts', value: r => r._e.fga, html: r => f1(r._e.fga) },
          { key: 'xp', label: 'XP', num: true, title: 'Expected extra points made', value: r => r._e.xp, html: r => f1(r._e.xp) }]
        : [
          { key: 'pa', label: 'Opp pts', num: true, first: 'asc', title: 'Points the opponent is expected to score', value: r => r._e.pa, html: r => f1(r._e.pa) },
          { key: 'sack', label: 'Sacks', num: true, title: 'Expected sacks', value: r => r._e.sack, html: r => f1(r._e.sack) },
          { key: 'take', label: 'Takeaways', num: true, title: 'Expected interceptions + fumble recoveries', value: r => r._e.take, html: r => f1(r._e.take) }]),
        { key: 'tier', label: 'Tier', first: 'asc', cls: 'tierc', value: r => r._rank, html: r => `<span class="tier t-${r._slot}" title="${r._slot === 'start' ? 'Starter' : 'Bench'} in a ${state.lg.teams}-team league">${r._tier}</span>` }];
    };
    const kdAttrs = r => r.pos === 'DST' ? `style="${rowStyle(r.team)}" data-open-pid="${esc(r.pid)}" data-team="${esc(r.team)}"`
      : `style="${rowStyle(r.team)}" data-pid="${esc(r.pid)}" data-open-pid="${esc(r.pid)}" data-team="${esc(r.team)}"`;
    const kdNote = p => `<p class="muted kd-note">${p === 'K' ? 'Kickers' : 'Team defenses'}: standard ESPN scoring (${p === 'K' ? 'field goals 3 / 4 / 5 by distance, misses −1, extra points 1' : 'sacks 1, takeaways 2, touchdowns 6, points-allowed tiers'}); the scoring panel applies to QB / RB / WR / TE.${KD && D.week < KD.from ? ' Kicker and defense projections cover the current week through week 17.' : ''}</p>`;
    const kdDraw = p => {
      const view = sec.querySelector(`.posview[data-pos="${p}"]`);
      if (!KD) { loadKD().then(() => kdDraw(p)).catch(() => { view.querySelector('.byes-box').innerHTML = '<p class="muted">Kicker and defense projections are not available right now.</p>'; }); return; }
      const box = view.querySelector(mode === 'ros' ? '.ros-tbl' : '.rk-tbl'), store = mode === 'ros' ? rosTables : tables;
      const opts = { columns: kdColumns(p), rows: kdRows(p), cls: 'sortable ranks tiles', sort: { key: 'proj', dir: 'desc' },
                     rowAttrs: kdAttrs, rowClass: r => `main teamrow${r.pos === 'DST' ? ' tm-open' : ''}` };
      if (!store[p]) store[p] = NFLE.Table(box, opts);
      else { store[p].setColumns(opts.columns); store[p].update(opts.rows); }
      view.querySelector('.byes-box').innerHTML = kdNote(p);
    };
    const rowsFor = p => {
      const t = q.trim().toLowerCase();
      const base = p === 'FLEX' ? all.filter(r => ['RB', 'WR', 'TE'].includes(r.pos)).sort((a, b) => b._proj - a._proj).slice(0, FLEX_DEPTH) : all.filter(r => r.pos === p);
      return t ? base.filter(r => r.name.toLowerCase().includes(t)) : base;
    };
    const rowAttrs = r => `style="${rowStyle(r.team)}" data-pid="${esc(r.pid)}" data-espn="${esc(r.espn || '')}" data-team="${esc(r.team)}" data-name="${esc(r.name.toLowerCase())}" data-pos="${esc(r.pos)}"`;
    const rowClass = r => `main teamrow${r.inactive >= 0.5 ? ' out' : ''}`;
    const byesHtml = p => {
      const list = (RK.byes || {})[p] || [];
      return list.length ? `<div class="byes"><span>On bye</span>${list.map(b => `<span class="bye"><span class="tm-open" data-tm="${esc(b.team)}">${logo(b.team, 16)}</span><button type="button" class="nm-link" data-open-pid="${esc(b.pid)}">${esc(b.name)}</button> <span class="muted">${f1(b.sc && b.sc.g ? pts(b.sc.ss, state.w, p) / b.sc.g : b.fpg)} FP/G</span></span>`).join('')}</div>` : '';
    };
    // -- rest of season ----------------------------------------------------------------------------------------
    const rosDerive = () => {
      if (!ROS) return;
      const { w, lg } = state, now = Date.now();
      rosAll.forEach(r => {
        let tot = 0, games = 0, sched = 0;
        const by = {};
        r.wk.forEach(([wk, pa, mu, opp, home, line]) => {
          if (wk === ROS.from && r.k && now >= Date.parse(r.k)) return;  // this week's game has kicked off
          const v = pts(line, w, r.pos);
          by[wk] = { v: v * pa, pa, opp, home };
          tot += v * pa; games += pa; sched += mu * pa;
        });
        Object.assign(r, { _tot: tot, _games: games, _ppg: games > 0.05 ? tot / games : 0, _sched: sched, _by: by });
        r._fpg = r.g ? pts(r.ss, w, r.pos) / r.g : null;  // season so far (ros.json carries it: bye-week players too)
      });
      ['QB', 'RB', 'WR', 'TE'].forEach(p => rosAll.filter(r => r.pos === p).sort((a, b) => b._tot - a._tot).forEach((r, i) => { r._rrank = i + 1; }));
      const slot = {};
      rosAll.forEach(r => { slot[r.pid] = r._rrank <= lg.teams * (lg[r.pos] || 0) ? 'start' : 'bench'; });
      const fill = (ps, n) => rosAll.filter(r => ps.includes(r.pos) && slot[r.pid] === 'bench').sort((a, b) => b._tot - a._tot).slice(0, n).forEach(r => { slot[r.pid] = 'flex'; });
      fill(['RB', 'WR', 'TE'], lg.teams * (lg.flex || 0));
      fill(['QB', 'RB', 'WR', 'TE'], lg.teams * (lg.superflex || 0));
      rosAll.forEach(r => { r._rslot = slot[r.pid]; r._rtier = `${r.pos}${Math.floor((r._rrank - 1) / lg.teams) + 1}`; });
      rosAll.filter(r => ['RB', 'WR', 'TE'].includes(r.pos)).sort((a, b) => b._tot - a._tot).forEach((r, i) => { r._rfrank = i + 1; });
    };
    const strip = r => {
      const wks = []; for (let k = ROS.from; k <= ROS.through; k++) wks.push(k);
      const byes = new Set((ROS.byes || {})[r.team] || []);
      const slot = 9, W = wks.length * slot, H = 30, bw = slot - 2;
      const top = Math.max(8, ...wks.map(k => (r._by[k] || {}).v || 0)) * 1.08;
      return `<svg class="ros-s" viewBox="0 0 ${W} ${H}" width="${W}" height="${H}">${wks.map((k, i) => {
        const x = i * slot + 1, mid = x + bw / 2, e = r._by[k];
        let body;
        if (e) {
          const h = Math.max(1.5, (H - 9) * e.v / top);
          body = `<rect x="${x}" y="${(H - 8 - h).toFixed(1)}" width="${bw}" height="${h.toFixed(1)}" rx="1.5" class="${e.pa < 0.5 ? 'rs-doubt' : 'rs-b'}"><title>Week ${k} ${esc(e.home)} ${esc(e.opp)}: ${f1(e.v)} expected pts${e.pa < 0.995 ? ` (${Math.round(100 * e.pa)}% to play)` : ''}</title></rect>`;
        } else if (byes.has(k)) body = `<text x="${mid}" y="${H - 11}" class="rs-bye">B<title>Week ${k}: bye</title></text>`;
        else if (k === ROS.from && r.k && Date.now() >= Date.parse(r.k)) body = `<text x="${mid}" y="${H - 11}" class="rs-bye">&#10003;<title>Week ${k}: game already started</title></text>`;
        else body = `<line x1="${x + 1}" x2="${x + bw - 1}" y1="${H - 9}" y2="${H - 9}" class="rs-sit"><title>Week ${k}: expected to sit</title></line>`;
        return body + (i % 2 === 0 ? `<text x="${mid}" y="${H - 0.5}" class="rs-wl">${k}</text>` : '');
      }).join('')}</svg>`;
    };
    const rosColumns = flex => [
      { key: 'rank', label: '#', num: true, first: 'asc', cls: 'rk', title: 'Our rest-of-season rank at the position', value: r => flex ? r._rfrank : r._rrank, html: r => `<b class="rkn">${flex ? r._rfrank : r._rrank}</b>` },
      { key: 'name', label: 'Player', stick: true, first: 'asc', value: r => r.name, html: r => nameCell(r, flex) },
      { key: 'tot', label: 'ROS pts', num: true, cls: 'projc', title: 'Expected fantasy points from now through week 17 under your scoring, each game weighted by his chance to play', value: r => r._tot, html: r => `<b class="pv">${f0(r._tot)}</b>` },
      { key: 'ppg', label: 'Pts/G', num: true, title: 'Expected points per game he plays', value: r => r._ppg, html: r => f1(r._ppg) },
      // expected games (owner 2026-10-17 read "11.0" as a count): whole numbers plain, so a decimal flags injury risk
      { key: 'games', label: 'Exp G', num: true, title: 'Expected games: his games left through week 17 (byes excluded), each counted by his chance to play it. 11 games with one at 70% = 10.7. A decimal means some injury risk.', value: r => r._games,
        html: r => Math.abs(r._games - Math.round(r._games)) < 0.05 ? String(Math.round(r._games)) : f1(r._games) },
      { key: 'sched', label: 'Sched', num: true, first: 'desc', title: 'Points his remaining opponents add (+) or take away (-) in total, vs average opponents', value: r => r._sched,
        html: r => `<span class="ros-sched ${r._sched >= 1.5 ? 'pos' : r._sched <= -1.5 ? 'neg' : 'muted'}">${sgn(r._sched)}</span>` },
      { key: 'weeks', label: 'Weeks', sort: false, cls: 'l5', title: 'Expected points each remaining week; B = bye, dash = expected to sit, faded = under 50% to play', html: strip },
      { key: 'tier', label: 'Tier', first: 'asc', cls: 'tierc', value: r => r._rrank, html: r => `<span class="tier t-${r._rslot}" title="${{ start: 'Starter', flex: 'Flex range', bench: 'Bench depth' }[r._rslot]} in a ${state.lg.teams}-team league, rest of season">${r._rtier}</span>` },
      { key: 'fpg', label: 'FP/G', num: true, cls: 'fpgc', title: 'Season fantasy points per game so far', value: r => r._fpg, html: r => f1(r._fpg) },
    ];
    const rosRows = p => {
      const t = q.trim().toLowerCase();
      const base = p === 'FLEX' ? rosAll.filter(r => ['RB', 'WR', 'TE'].includes(r.pos)).sort((a, b) => b._tot - a._tot).slice(0, FLEX_DEPTH) : rosAll.filter(r => r.pos === p);
      return t ? base.filter(r => r.name.toLowerCase().includes(t)) : base;
    };
    const rosDraw = (resort = true) => {
      if (KDP.includes(pos)) { kdDraw(pos); return; }
      if (!ROS) return;
      rosDerive();
      const box = sec.querySelector(`.posview[data-pos="${pos}"] .ros-tbl`);
      const opts = { columns: rosColumns(pos === 'FLEX'), rows: rosRows(pos), cls: 'sortable ranks tiles ros', sort: { key: 'tot', dir: 'desc' }, rowAttrs,
                     rowClass: r => `main teamrow${(D.players[r.pid] || {}).inactive >= 0.5 ? ' out' : ''}` };
      if (!rosTables[pos]) rosTables[pos] = NFLE.Table(box, opts);
      else { rosTables[pos].setColumns(opts.columns); rosTables[pos].update(opts.rows); if (resort) rosTables[pos].setSort({ key: 'tot', dir: 'desc' }); }
    };
    const loadRos = () => ROS ? Promise.resolve() : NFLE.load('data/ros.json').then(j => {
      if (!j || !j.players) throw new Error('no ros data');
      ROS = j;
      rosAll = Object.entries(j.players).map(([pid, x]) => {
        const live = D.players[pid] || {};
        return { pid, name: x.name, pos: x.pos, team: x.team, espn: x.espn, photo: x.photo || live.photo, k: x.k, wk: x.w,
                 ss: x.ss, g: x.g, status: live.status || '', takeaway: live.takeaway || '' };
      });
      sec.querySelector('.ros-note').textContent = `Weeks ${j.from}-${j.through}${(j.missing || []).length ? ` (weeks ${j.missing.join(', ')} not built yet, counted as 0)` : ''} · built ${j.built || ''}.`;
    });
    const setMode = m => {
      mode = m;
      if (rosOk) { try { localStorage.setItem('nfledge-rk-mode', m); } catch (e) { /* private mode */ } }
      sec.querySelectorAll('.rk-mode button').forEach(b => b.classList.toggle('on', b.dataset.mode === m));
      sec.querySelectorAll('.rk-h-week').forEach(e => { e.hidden = m !== 'week'; });
      sec.querySelectorAll('.rk-h-ros').forEach(e => { e.hidden = m !== 'ros'; });
      sec.querySelector('.ros-note').hidden = m !== 'ros';
      sec.querySelectorAll('.posview').forEach(v => {
        v.querySelector('.rk-tbl').hidden = m !== 'week'; v.querySelector('.byes-box').hidden = m !== 'week'; v.querySelector('.ros-tbl').hidden = m !== 'ros';
      });
      if (m === 'ros') loadRos().then(() => rosDraw()).catch(() => { const n = sec.querySelector('.ros-note'); n.hidden = false; n.textContent = 'Rest-of-season projections are not available right now.'; });
      else if (tables[pos]) tables[pos].layout();
    };
    if (!rosOk) sec.querySelector('.rk-mode').hidden = true;
    sec.querySelector('.rk-mode').addEventListener('click', e => { const b = e.target.closest('[data-mode]'); if (b && b.dataset.mode !== mode) setMode(b.dataset.mode); });

    const draw = (resort = true) => {
      derive();
      if (mode === 'ros') rosDraw(resort);
      POS.forEach(p => {
        const view = sec.querySelector(`.posview[data-pos="${p}"]`);
        if (view.hidden && tables[p] === undefined) return;  // built on first show
        if (KDP.includes(p)) { if (mode === 'week') kdDraw(p); return; }
        const rows = rowsFor(p);
        if (!tables[p]) {
          tables[p] = NFLE.Table(view.querySelector('.rk-tbl'), { columns: columns(p === 'FLEX', p), rows, cls: 'sortable ranks tiles', sort: { key: 'proj', dir: 'desc' }, rowAttrs, rowClass });
          // the landing animation (pages/week.html adds html.land-anim) plays on this first draw only, not on sorts
          setTimeout(() => document.documentElement.classList.remove('land-anim'), 1200);
        }
        else { tables[p].setColumns(columns(p === 'FLEX', p)); tables[p].update(rows); if (resort) tables[p].setSort({ key: 'proj', dir: 'desc' }); }
        view.querySelector('.byes-box').innerHTML = byesHtml(p);
      });
      const name = state.preset || 'Custom';
      const sn = document.getElementById('scoreName'); if (sn) sn.textContent = name;
      const sub = name === 'Custom' ? 'Custom-scoring' : state.src === 'team' ? `${name}-scoring` : name;
      sec.querySelector('#scoreSub').textContent = sub;
      sec.querySelector('.rosSub').textContent = sub;
      sec.querySelector('#scoreSum').textContent = `· ${name}, ${state.lg.teams} teams`;
      document.dispatchEvent(new Event('nfle-scoring'));  // open player page / live points re-score too
    };
    // live scores (gamecast.js, every ~minute on game days): redraw in place, no re-sort
    document.addEventListener('nfle-live', () => { if (mode === 'week') draw(false); });
    document.addEventListener('nfle-grades', () => { if (mode === 'week') draw(false); });
    const showPos = p => {
      pos = p;
      sec.querySelectorAll('.posbar button').forEach(b => b.classList.toggle('on', b.dataset.pos === p));
      sec.querySelectorAll('.posview').forEach(v => { v.hidden = v.dataset.pos !== p; });
      if (!tables[p]) { tables[p] = null; draw(false); } else tables[p].layout();
      if (mode === 'ros') rosDraw(!rosTables[p]);
    };
    sec.querySelector('.posbar').addEventListener('click', e => { const b = e.target.closest('[data-pos]'); if (b) showPos(b.dataset.pos); });
    sec.querySelector('#psearch').oninput = e => { q = e.target.value; POS.forEach(p => tables[p] && tables[p].update(KDP.includes(p) ? kdRows(p, 'week') : rowsFor(p))); if (mode === 'ros') rosDraw(false); };
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
    const changed = () => { state.src = 'own'; state.preset = Object.keys(SC.presets).find(n => sameW(state.w, SC.presets[n])) || 'Custom'; sync(); draw(); save(); };
    const useTeam = m => { state = fromTeam(m); sync(); draw(); save(); };
    const teamBtn = document.createElement('button'); teamBtn.type = 'button'; teamBtn.className = 'sp-team';
    teamBtn.onclick = () => { const m = mine(); if (m) useTeam(m); };
    presetBox.appendChild(teamBtn);
    const paintTeam = () => { const m = mine(); teamBtn.hidden = !m; teamBtn.textContent = m ? m.league : ''; };
    paintTeam();
    Object.keys(SC.presets).forEach(n => {
      const b = document.createElement('button'); b.type = 'button'; b.textContent = n;
      b.onclick = () => { state.w = { ...state.w, ...SC.presets[n] }; changed(); };  // the IDP weights stay
      presetBox.appendChild(b);
    });
    // switching or removing the active team: follow it unless the viewer picked their own scoring
    document.addEventListener('nfle-mine', () => {
      paintTeam();
      if (state.src === 'own') return;
      const m = mine();
      if (m) useTeam(m); else { state = defaults(); sync(); draw(); save(); }
    });
    panel.querySelectorAll('input[data-k]').forEach(i => i.onchange = () => { const v = parseFloat(i.value); if (isNaN(v)) return; state.w[i.dataset.k] = i.dataset.inv ? (v > 0 ? 1 / v : 0) : v; changed(); });
    panel.querySelectorAll('input[data-l]').forEach(i => i.onchange = () => { const v = parseInt(i.value, 10); if (isNaN(v) || v < 0) return; state.lg[i.dataset.l] = i.dataset.l === 'teams' ? Math.max(4, v) : v; changed(); });
    sec.querySelector('#spReset').onclick = () => { state = defaults(); changed(); };  // an explicit choice too
    btn.onclick = () => { panel.hidden = !panel.hidden; btn.setAttribute('aria-expanded', String(!panel.hidden)); };
    sync();
    showPos('QB');
    setMode(mode);
  }
})();
