// Players > Trends, the page: the UI over trends_engine.js (definitions, loading, counting; shared with
// tools/trends_cli.mjs). A play-level query builder over every run and pass play since 1999 (tools/trends_build.py:
// data/plays/<season>.json plays, _x charting, _g game context + who played, _on players on the field 2016-2025,
// bio.json college / draft / contracts / age). The query Q (fam, met, who, f filters + fn excluded, by / by2, seasons,
// min, gt / gn for game-by-game) is edited through labeled rows (Measure, Who, Only when, Seasons, Break down,
// Minimum), each a bottom-sheet picker; a plain-English summary sits on top. Filters: options (several = any of),
// Is / Is not, sliders (R:lo~hi) with linked boxes, players (gsis|Name). The answer: a leaderboard against the league
// in the same situation, a 2-D grid, or game logs / marks with streaks / best stretches; CSV export; share link (?t=,
// read once then dropped). Everything is counted in the browser from the season files. Audited against nflverse's
// season totals by tools/trends_audit.py (docs/trends_audit.md).
// Coverage: every filter / metric / grouping names the columns it needs; index.json lists, per season, the columns
// charted on >= 90% of the plays they apply to, and a query only counts seasons that have all it needs (and says
// which it left out), so a charting gap never reads as a zero.
(() => {
  const NFLE = window.NFLE, esc = NFLE.esc;
  const LS = 'nfledge-trends';
  const opt = (v, l, cur) => `<option value="${esc(v)}"${String(v) === String(cur) ? ' selected' : ''}>${esc(l)}</option>`;
  // the engine (trends_engine.js: definitions, loading, counting; shared with tools/trends_cli.mjs), loaded with this file
  let E = null;
  const engineReady = new Promise((ok, bad) => {
    if (NFLE.trendsEngine) { ok(); return; }
    const me = document.querySelector('script[src*="trends.js"]'), v = me && me.src.includes('?') ? me.src.slice(me.src.indexOf('?')) : '';
    const js = document.createElement('script');
    js.src = new URL(`assets/trends_engine.js${v}`, NFLE.root).href;
    js.onload = ok; js.onerror = () => bad(new Error('assets/trends_engine.js'));
    document.head.appendChild(js);
  }).then(() => { E = E || NFLE.trendsEngine(NFLE.load); });

  let TEAMS = {};  // the week data's teams map (tile colors, logos)
  NFLE.areas.trends = {
    mount(sec) {
      engineReady.then(() => this.mount2(sec), e => { sec.innerHTML = `<p class="muted">Couldn't load Trends (${esc(e.message)}).</p>`; });
    },
    mount2(sec) {
      const { FAM, FILTERS, BY, BYLABEL, EXAMPLES, FIRST, LOWER, GAMEBY, GRID_ROW_ONLY, GRID_MAX_ROWS, GRID_MAX_COLS, MARK, GMIN,
        blank, fmt, ranges, numKey, allowed, byAllowed, isR, parseR, UNITS, ST_TXT, cap } = E;
      NFLE.week().then(D => { if (D && D.teams) { TEAMS = D.teams; if (paint) paint(); } });
      sec.classList.remove('soon');
      let IX = null, Q = null, busy = 0, paint = null, maxN = 0, csvRows = null;  // csvRows: the shown table as [[cell...]]
      const defaults = E.defaults;
      const fromUrl = () => { try { const t = new URLSearchParams(location.search).get('t'); return t ? JSON.parse(decodeURIComponent(escape(atob(t)))) : null; } catch (e) { return null; } };
      const saved = () => { try { return JSON.parse(localStorage.getItem(LS) || 'null'); } catch (e) { return null; } };
      sec.innerHTML = `<div class="sec-head"><div><h2>Trends</h2><p>Ask the play-by-play anything: every run and pass since 1999, with charting (personnel, coverage, routes, pressure, play action...) where it exists. Tap a row to change it.</p></div></div>
        <div class="dt-card tr-card"><div class="tr-q"></div></div>
        <div class="tr-base muted"></div><div class="tr-cov"></div><div class="tr-trend"></div><div class="tr-tbl"></div>
        <p class="st-note muted">nflverse play-by-play (1999 on); NGS participation charting (2016-2025: formation, personnel, box, rushers, pressure, time to throw, routes, coverage) and FTN charting (2022 on, CC-BY-SA: motion, play action, RPOs, screens, blitzes, pocket, reads, drops, catchable / contested balls). A query only counts seasons where everything it uses was charted, and says which it left out. Rushing counts designed runs and QB scrambles; passing counts dropbacks (sacks included; yards per attempt and completion % use pass attempts). EPA = expected points added; CPOE = completion % over expected; pass rate over expected uses nflverse's xpass model, whose league average is not exactly zero, so read it against the league column. Rows under the minimum sample are hidden (the count is shown): small samples make loud, fake trends. Special teams (kickoffs, punts, field goals, extra points) read from the kicker's side, returns from the returner's; net punting = distance minus return yards, minus 20 for a touchback. Route names were re-charted in 2023, so outs, flats and swings are one group.</p>`;
      const qbox = sec.querySelector('.tr-q');

      // ---- what a query needs, and which seasons have it
      const famMetric = () => E.famMetric(Q);
      const covers = E.covers;
      const spanSeasons = () => E.spanSeasons(Q);

      // ---- the builder (owner 2026-10-22: "be more deliberate and elegant with how we're selecting filters ... a lot
      // easier to use and understand"): one labeled row per part of the question (Measure, Who, Only when, Seasons, Break
      // down, Minimum), each opening a sheet of grouped, searchable choices, and the question in plain English on top.
      // The query state Q, the links and run() are unchanged.
      const BY_GROUPS = [['People', ['player', 'team', 'opp', 'coach', 'pos', 'college', 'rnd', 'age', 'cyr']], ['Game by game', ['pgame', 'pmark', 'pspan']], ['Time', ['season', 'week', 'qtr']],
        ['Situation', ['down', 'dist', 'zone', 'score']], ['Offense', ['align', 'pers', 'pa', 'mo']],
        ['Defense', ['box', 'rushers', 'dbs', 'mz', 'cov']], ['Passing', ['depth', 'loc', 'route', 'read', 'press']],
        ['Running', ['dir', 'gap']], ['Kicking', ['kdist']], ['Game', ['roof', 'surf']]];
      // charting that starts after 1999: the first season with it, shown next to the choice ("2016+")
      const sinceTag = cols => {
        if (!cols || !cols.length) return '';
        const s = IX.seasons.find(y => covers(y, cols));
        return s && s > IX.seasons[0] ? `<span class="tq-since">${s}+</span>` : '';
      };
      // Who names the subject: the scope (Q.who) plus, for the league or one team, its unit (players, or the team as one:
      // owner 2026-10-22 "who: add teams themselves maybe?"). A team as itself is that team, a row per season.
      const whoLabel = () => E.whoLabel(Q);
      const vals = k => E.vals(Q, k);
      const isNot = k => E.isNot(Q, k);
      const setF = (k, list, neg) => E.setF(Q, k, list, neg);
      const optLabel = k => E.optLabel(Q, k);
      const seasonsTxt = () => E.seasonsTxt(Q);
      const defMin = () => E.defMin(Q);
      const gameTxt = () => E.gameTxt(Q);
      const byTxt = () => E.byTxt(Q);
      const summary = () => {
        const p = E.summaryParts(Q);
        return `<b>${esc(p.who)}</b> &middot; ${esc(p.fam)} <b>${esc(p.metric)}</b>${p.when.length ? ` when ${esc(p.when.join(', '))}` : ''} &middot; ${esc(p.years)} ${esc(p.st)}${esc(p.by)}`;
      };
      const render = () => {
        const fam = FAM[Q.fam], [, m] = famMetric();
        const chips = Object.keys(Q.f).map(k => `<span class="tq-chip${isNot(k) ? ' tq-not' : ''}"><button type="button" data-fx="${k}" title="${esc(FILTERS[k].label)}">${esc(optLabel(k))}</button><button type="button" class="tq-cx" data-x="${k}" aria-label="Remove ${esc(FILTERS[k].label)}">&times;</button></span>`).join('');
        const row = (pick, k, v) => `<button type="button" class="tq-row" data-pick="${pick}"><span class="tq-k">${k}</span><span class="tq-v">${v}</span><span class="tq-go" aria-hidden="true">&rsaquo;</span></button>`;
        qbox.innerHTML = `<p class="tq-sum">${summary()}</p>
          <div class="tq-rows">
            ${row('measure', 'Measure', `${esc(fam.label)} <span class="tq-dot">&middot;</span> <b>${esc(m[0])}</b>`)}
            ${row('who', 'Who', esc(whoLabel()))}
            <div class="tq-row tq-frow"><span class="tq-k">Only when</span><span class="tq-v tq-chips">${chips}<button type="button" class="tq-add" data-pick="add">+ Add</button></span></div>
            ${row('seasons', 'Seasons', esc(seasonsTxt()))}
            ${row('by', 'Break down', esc(byTxt()))}
            <div class="tq-row tq-mrow"><span class="tq-k">Minimum</span><span class="tq-v tr-min"><button type="button" class="tr-step" data-step="-1" aria-label="One fewer">&minus;</button><input class="tq-mrange" type="range" min="0" max="${Math.max(maxN, Q.min ?? defMin(), fam.min * 2)}" step="1" value="${Q.min ?? defMin()}" aria-label="Minimum sample"><button type="button" class="tr-step" data-step="1" aria-label="One more">+</button> <input class="tq-mnum" type="number" inputmode="numeric" min="0" step="1" value="${Q.min ?? defMin()}" aria-label="Minimum ${esc(fam.unit)}"><span class="tr-w">${esc(fam.unit)}</span></span></div>
          </div>
          <div class="tq-acts"><button type="button" class="tq-act" data-pick="examples">Examples</button><button type="button" class="tq-act tr-share">Copy link</button><button type="button" class="tq-act tq-csv" data-csv="1">Download CSV</button><button type="button" class="tq-act tq-reset">Reset</button></div>`;
      };
      const setFam = k => {
        Q.fam = k; Q.met = FIRST[k]; Q.min = null;
        if (Q.fam === 'team' && Q.by === 'player') Q.by = 'team';
        if (Q.fam === 'team' && /^P:/.test(Q.who)) { Q.who = 'L'; Q.wn = ''; }
        Object.keys(Q.f).forEach(f => { if (!allowed(f, Q.fam)) delete Q.f[f]; });
        if (!byAllowed(Q.by, Q.fam)) Q.by = Q.fam === 'team' ? 'team' : 'player';
        if (Q.by2 && !byAllowed(Q.by2, Q.fam)) Q.by2 = '';
        maxN = 0;
      };
      const setWho = (v, name) => { Q.who = v; Q.wn = /^[PC]:/.test(v) ? name || '' : ''; if (/^P:/.test(Q.who) && Q.by === 'player') Q.by = 'season'; };
      // ---- the pickers (NFLE.sheet: a bottom sheet on phones, a centered panel on wide screens)
      const panel = () => { const el = document.createElement('div'); el.className = 'tq-sheet'; return el; };
      const done = () => { NFLE.sheetClose(); update(); };
      const pickMeasure = opener => {
        const el = panel();
        let fam = Q.fam;
        const draw = () => {
          el.innerHTML = `<div class="tq-seg" role="tablist">${Object.entries(FAM).map(([k, f]) => `<button type="button" data-fam="${k}" class="${k === fam ? 'on' : ''}">${esc(f.label)}</button>`).join('')}</div>
            <div class="tq-list">${Object.entries(FAM[fam].met).map(([k, mm]) => `<button type="button" class="tq-opt${fam === Q.fam && k === Q.met ? ' on' : ''}" data-met="${k}"><span>${esc(mm[0])}</span>${sinceTag(mm[3])}</button>`).join('')}</div>`;
        };
        draw();
        el.addEventListener('click', e => {
          const f = e.target.closest('[data-fam]'); if (f) { fam = f.dataset.fam; draw(); return; }
          const mt = e.target.closest('[data-met]'); if (!mt) return;
          if (fam !== Q.fam) setFam(fam);
          Q.met = mt.dataset.met; done();
        });
        NFLE.sheet('What to measure', el, opener);
      };
      const countPlayers = (t, role) => E.countPlayers(Q, t, role);
      const teamOfPlayer = gid => E.teamOfPlayer(Q, gid);
      const pickWho = opener => {
        const el = panel(), teams = IX.teams, team = Q.fam === 'team', fam = FAM[Q.fam];
        const ok = k => BY[k] && byAllowed(k, Q.fam) && !(k === 'player' && team);
        // one team: as a unit (a row per season, or whatever it's broken down by) or its players
        // each grid keeps its own choice; it starts on the current one, else on the team as a unit
        const solo = { T: true, V: true };
        if (/^[TV]:/.test(Q.who)) solo[Q.who[0]] = team || Q.by !== 'player';
        const lit = (pre, t) => Q.who === `${pre}:${t}` && solo[pre] === (team || Q.by !== 'player');
        const tgrid = pre => `<div class="tq-teams">${teams.map(t => `<button type="button" data-who="${pre}:${t}" class="${lit(pre, t) ? 'on' : ''}">${esc(t)}</button>`).join('')}</div>`;
        const SEG = { T: ['As a team', 'Its players'], V: ['Their defense', 'Players facing them'] };
        const seg = pre => team ? '' : `<div class="tq-seg">${[1, 0].map((v, i) => `<button type="button" data-solo="${v}" data-pre="${pre}" class="${+solo[pre] === v ? 'on' : ''}">${SEG[pre][i]}</button>`).join('')}</div>`;
        // position (owner 2026-10-22: "can we sort by positions too? maybe as part of the who filter"): sets the Position
        // filter (Routes: the route runner's on-field position) and stays open, so a team can be picked next
        const pk = E.posKey(Q), POSO = (FILTERS[pk] && allowed(pk, Q.fam)) ? FILTERS[pk].opts.map(o => o[0]) : [];
        const posRow = () => (POSO.length ? `<h4 class="tq-h">Position</h4><div class="tq-chipset tq-posrow">${['', ...POSO].map(v => `<button type="button" data-pos="${v}" class="${(E.posSel(Q) || '') === v && !(v === '' && pk in Q.f) ? 'on' : ''}">${v || 'All'}</button>`).join('')}</div>` : '');
        const main = () => {
          el.innerHTML = `<div class="tq-list">${Object.entries(UNITS).filter(([k]) => ok(k)).map(([k, l]) => `<button type="button" class="tq-opt${Q.who === 'L' && Q.by === k ? ' on' : ''}" data-who="L" data-unit="${k}"><span>${l}</span><small>${{ player: 'a row per player', team: team ? 'a row per offense' : 'a row per team: its players combined', opp: 'a row per defense: what offenses did against it', coach: 'a row per head coach: the offenses they ran' }[k]}</small></button>`).join('')}</div>
            ${posRow()}
            <h4 class="tq-h">${team ? 'A head coach' : 'A player or head coach'}</h4>
            <input class="dt-search tq-find" type="search" placeholder="Type a name" aria-label="Find a ${team ? 'head coach' : 'player or head coach'}" autocomplete="off">
            <div class="tq-list tq-found"></div>
            <h4 class="tq-h">One team${team ? "'s offense" : ''}</h4><div class="tq-solo">${seg('T')}${tgrid('T')}</div>
            <h4 class="tq-h">${team ? "One team's defense" : 'Against one team'}</h4><div class="tq-solo">${seg('V')}${tgrid('V')}</div>`;
          const inp = el.querySelector('.tq-find'), out = el.querySelector('.tq-found');
          const find = () => {
            const t = inp.value.trim().toLowerCase();
            out.innerHTML = t.length < 2 ? '' : [...findMap.values()].filter(o => o[0].toLowerCase().includes(t)).slice(0, 30)
              .map(o => `<button type="button" class="tq-opt" data-who="${esc(o[1])}" data-wn="${esc(o[2])}"><span>${esc(o[0])}</span></button>`).join('')
              || '<p class="muted tq-help">No one by that name in these seasons.</p>';
          };
          inp.addEventListener('input', find);
          fillFind().then(() => { if (inp.value) find(); });  // names load per season: search again once they're in
        };
        // a team's players (owner 2026-10-22: "vikings > aaron jones when playing the packers"): everyone with a play for
        // it in these seasons, most plays first; picking one is that player while playing for that team
        const roster = t => {
          el.innerHTML = '<p class="muted tq-help">Counting plays&hellip;</p>';
          countPlayers(t, 'fam').then(all => {
            const rows = all.slice(0, 60);
            el.innerHTML = `<button type="button" class="tq-act tq-back" data-back="1">&lsaquo; All teams</button>
              <h4 class="tq-h">${esc(t)} &middot; ${esc(fam.label.toLowerCase())}</h4>
              <div class="tq-list"><button type="button" class="tq-opt${Q.who === `T:${t}` && Q.by === 'player' ? ' on' : ''}" data-all="${esc(t)}"><span>Every ${esc(t)} player</span><small class="tq-r">a row each</small></button>
              ${rows.map(([gid, [nm, c]]) => `<button type="button" class="tq-opt${Q.who === `P:${gid}` && Q.f.tm === t ? ' on' : ''}" data-pid="${esc(gid)}" data-wn="${esc(nm)}" data-tm="${esc(t)}"><span>${esc(nm)}</span><small class="tq-r">${c} ${esc(fam.unit)}</small></button>`).join('')}</div>
              ${rows.length ? '' : '<p class="muted tq-help">No plays for this team in these seasons.</p>'}`;
            el.closest('.sheet') && (el.closest('.sheet').scrollTop = 0);
          });
        };
        main();
        el.addEventListener('click', e => {
          const ps = e.target.closest('[data-pos]'); if (!ps) return;
          E.setF(Q, pk, ps.dataset.pos ? [ps.dataset.pos] : [], false);
          el.querySelectorAll('[data-pos]').forEach(x => x.classList.toggle('on', x === ps));
          update();
        });
        el.addEventListener('click', e => {
          const sv = e.target.closest('[data-solo]');
          if (sv) {  // flip that grid's choice, and its highlighted team with it
            const pre = sv.dataset.pre, box = sv.closest('.tq-solo');
            solo[pre] = sv.dataset.solo === '1';
            box.querySelectorAll('[data-solo]').forEach(x => x.classList.toggle('on', x === sv));
            box.querySelectorAll('.tq-teams [data-who]').forEach(x => x.classList.toggle('on', lit(pre, x.dataset.who.slice(2))));
            return;
          }
          if (e.target.closest('[data-back]')) { main(); return; }
          const all = e.target.closest('[data-all]');
          if (all) { setWho(`T:${all.dataset.all}`); delete Q.f.tm; Q.by = 'player'; if (Q.by2 === Q.by) Q.by2 = ''; done(); return; }
          const pp = e.target.closest('[data-pid]');
          if (pp) { setWho(`P:${pp.dataset.pid}`, pp.dataset.wn); Q.f.tm = pp.dataset.tm; done(); return; }
          const b = e.target.closest('[data-who]'); if (!b) return;
          if (/^T:/.test(b.dataset.who) && !team && !solo.T) { roster(b.dataset.who.slice(2)); return; }
          setWho(b.dataset.who, b.dataset.wn);
          delete Q.f.tm;  // a new subject starts without the last one's team
          if (/^V:/.test(Q.who)) delete Q.f.vs;  // the scope already says who they played
          if (b.dataset.unit) Q.by = b.dataset.unit;
          else if (/^[TV]:/.test(Q.who)) Q.by = solo[Q.who[0]] ? (UNITS[Q.by] ? 'season' : Q.by) : 'player';
          if (Q.by2 === Q.by) Q.by2 = '';
          done();
        });
        NFLE.sheet('Who', el, opener);
      };
      // a player as a filter value (Thrown by, With / Without a teammate): search by name, or a team then its players;
      // opens on the team in question when there is one (Playing for, Who's team, or the chosen player's team)
      // Is / Is not (owner 2026-10-22: "do we have include and exclude with filters"): every filter but with / without
      // (each other's opposite); the sheet keeps its choice and commits it with the value
      const notSeg = (k, neg) => (FILTERS[k].noNot ? '' : `<div class="tq-seg tq-isnot" role="radiogroup" aria-label="Include or exclude">${[[0, 'Is'], [1, 'Is not']].map(([v, l]) => `<button type="button" data-not="${v}" class="${+neg === v ? 'on' : ''}">${l}</button>`).join('')}</div>`);
      const flipNot = (el, e) => { const b = e.target.closest('[data-not]'); if (!b) return null; el.querySelectorAll('[data-not]').forEach(x => x.classList.toggle('on', x === b)); return b.dataset.not === '1'; };
      const rmBtn = k => (k in Q.f ? '<button type="button" class="tq-act tq-rm" data-rm="1">Remove this filter</button>' : '');
      // multi-select sheets: tap to toggle, Apply commits ("any of these")
      const applyBar = n => `<div class="tq-applybar"><button type="button" class="tq-act tq-done" data-apply="1"${n ? '' : ' disabled'}>${n > 1 ? `Apply (any of ${n})` : 'Apply'}</button></div>`;
      const toggleSel = (el, sel, b) => {
        const v = b.dataset.fv;
        if (sel.has(v)) sel.delete(v); else sel.add(v);
        el.querySelectorAll('[data-fv]').forEach(x => x.classList.toggle('on', sel.has(x.dataset.fv)));
        const a = el.querySelector('.tq-applybar'); if (a) a.outerHTML = applyBar(sel.size);
      };
      const pickPerson = (k, opener) => {
        const F = FILTERS[k], el = panel(), role = F.param === 'qb' ? 'qb' : 'any';
        let neg = isNot(k);
        const set = (gid, nm) => { setF(k, [`${gid}|${nm}`], neg); done(); };
        const head = () => notSeg(k, neg);
        const main = () => {
          el.innerHTML = `${head()}<input class="dt-search tq-find" type="search" placeholder="Type a name" aria-label="Find a player" autocomplete="off">
            <div class="tq-list tq-found"></div><h4 class="tq-h">Or pick a team</h4>
            <div class="tq-teams">${IX.teams.map(t => `<button type="button" data-team="${t}">${esc(t)}</button>`).join('')}</div>${rmBtn(k)}`;
          const inp = el.querySelector('.tq-find'), out = el.querySelector('.tq-found');
          const find = () => {
            const t = inp.value.trim().toLowerCase();
            out.innerHTML = t.length < 2 ? '' : [...findMap.values()].filter(o => o[1][0] === 'P' && o[0].toLowerCase().includes(t)).slice(0, 30)
              .map(o => `<button type="button" class="tq-opt" data-pid="${esc(o[1].slice(2))}" data-wn="${esc(o[2])}"><span>${esc(o[0])}</span></button>`).join('')
              || '<p class="muted tq-help">No one by that name in these seasons.</p>';
          };
          inp.addEventListener('input', find);
          fillFind().then(() => { if (inp.value) find(); });
        };
        const team = t => {
          el.innerHTML = '<p class="muted tq-help">Counting plays&hellip;</p>';
          countPlayers(t, role).then(all => {
            const rows = all.slice(0, 60), unit = role === 'qb' ? 'dropbacks' : 'plays';
            el.innerHTML = `${head()}<button type="button" class="tq-act tq-back" data-back="1">&lsaquo; Search or another team</button>
              <h4 class="tq-h">${esc(t)} ${role === 'qb' ? 'passers' : 'players'}</h4>
              <div class="tq-list">${rows.map(([gid, [nm, c]]) => `<button type="button" class="tq-opt${vals(k).some(v => v.startsWith(gid + '|')) ? ' on' : ''}" data-pid="${esc(gid)}" data-wn="${esc(nm)}"><span>${esc(nm)}</span><small class="tq-r">${c} ${unit}</small></button>`).join('')}</div>
              ${rows.length ? '' : '<p class="muted tq-help">No plays for this team in these seasons.</p>'}${rmBtn(k)}`;
          });
        };
        el.addEventListener('click', e => {
          const n = flipNot(el, e); if (n != null) { neg = n; if (k in Q.f) { setF(k, vals(k), neg); update(); } return; }
          const pp = e.target.closest('[data-pid]'); if (pp) { set(pp.dataset.pid, pp.dataset.wn); return; }
          const tb = e.target.closest('[data-team]'); if (tb) { team(tb.dataset.team); return; }
          if (e.target.closest('[data-back]')) { main(); return; }
          if (e.target.closest('[data-rm]')) { setF(k, []); done(); }
        });
        const t0 = vals('tm')[0] || (/^T:/.test(Q.who) ? Q.who.slice(2) : null);
        if (t0) team(t0);
        else if (/^P:/.test(Q.who)) { el.innerHTML = '<p class="muted tq-help">Finding the team&hellip;</p>'; teamOfPlayer(Q.who.slice(2)).then(t => (t ? team(t) : main())); }
        else main();
        NFLE.sheet(F.label, el, opener);
      };
      const pickCollege = (k, opener) => {
        const el = panel(), sel = new Set(vals(k));
        let neg = isNot(k);
        el.innerHTML = '<p class="muted tq-help">Loading schools&hellip;</p>';
        loadBio().then(() => {
          const n = [new Map(), new Map()];
          E.bio().p.forEach(([si, ci]) => { if (si >= 0) n[0].set(si, (n[0].get(si) || 0) + 1); if (ci >= 0) n[1].set(ci, (n[1].get(ci) || 0) + 1); });
          const top = (m, names) => [...m].sort((a, b) => b[1] - a[1]).map(([i, c]) => [names[i], c]);
          const schools = top(n[0], E.bio().schools), confs = top(n[1], E.bio().confs).filter(([c]) => c !== 'NO FOOTBALL').slice(0, 12);
          const row = (t, [nm, c]) => `<button type="button" class="tq-opt${sel.has(`${t}:${nm}`) ? ' on' : ''}" data-fv="${t}:${esc(nm)}"><span>${esc(nm)}</span><small class="tq-r">${c} players</small></button>`;
          el.innerHTML = `${notSeg(k, neg)}<input class="dt-search tq-find" type="search" placeholder="Search schools: Florida, Alabama&hellip;" aria-label="Search schools" autocomplete="off">
            <div class="tq-list tq-found"></div>
            <h4 class="tq-h">Conference <span class="muted">(today's)</span></h4><div class="tq-chipset">${confs.map(([c]) => `<button type="button" class="${sel.has(`c:${c}`) ? 'on' : ''}" data-fv="c:${esc(c)}">${esc(c.replace(/ Conference$/, ''))}</button>`).join('')}</div>
            <h4 class="tq-h">Most NFL players</h4><div class="tq-list">${schools.slice(0, 25).map(x => row('s', x)).join('')}</div>
            ${rmBtn(k)}${applyBar(sel.size)}`;
          const inp = el.querySelector('.tq-find'), out = el.querySelector('.tq-found');
          inp.addEventListener('input', () => {
            const t = inp.value.trim().toLowerCase();
            out.innerHTML = t.length < 2 ? '' : schools.filter(([nm]) => nm.toLowerCase().includes(t)).slice(0, 30).map(x => row('s', x)).join('')
              || '<p class="muted tq-help">No school by that name.</p>';
          });
        });
        el.addEventListener('click', e => {
          const n = flipNot(el, e); if (n != null) { neg = n; return; }
          const b = e.target.closest('[data-fv]'); if (b) { toggleSel(el, sel, b); return; }
          if (e.target.closest('[data-apply]')) { setF(k, [...sel], neg); done(); return; }
          if (e.target.closest('[data-rm]')) { setF(k, []); done(); }
        });
        NFLE.sheet('College', el, opener);
      };
      const pickRange = (k, opener) => {
        const F = FILTERS[k], r = F.range, el = panel(), step = r.step || 1, tick = r.tick || (x => `${x}`);
        let neg = isNot(k), moved = false;
        // the number boxes (owner 2026-10-22: "text input fields that are linked to the slider"): a time picker for clock
        // values; typing moves the handle, dragging rewrites the box
        const isTime = r.input === 'time';
        const box = isTime ? `type="time" step="${step * 60}"` : `type="number" inputmode="decimal" step="${step}" min="${r.min}" max="${r.max}"`;
        const toBox = v => (isTime ? `${String(Math.floor(v / 60)).padStart(2, '0')}:${String(v % 60).padStart(2, '0')}` : `${v}`);
        const fromBox = t => { if (isTime) { const [h, mm] = t.split(':').map(Number); return h * 60 + mm; } return parseFloat(t); };
        const snap = v => Math.min(r.max, Math.max(r.min, Math.round((v - r.min) / step) * step + r.min));
        let [lo, hi] = isR(F, Q.f[k]) ? Q.f[k].slice(2).split('~').map(Number) : [r.min, r.max];
        const chips = [...F.opts.filter(o => !r.chips || r.chips.includes(o[0])).map(o => [o[1], o[0]]), ...(r.presets || []).map(([l, a, b]) => [l, `R:${a}~${b}`])];
        el.innerHTML = `${notSeg(k, neg)}<p class="tq-rv"></p>
          <div class="tq-range"><i class="tq-rtrack"><i class="tq-rfill"></i></i>
            <input type="range" class="tq-lo" min="${r.min}" max="${r.max}" step="${step}" value="${lo}" aria-label="From">
            <input type="range" class="tq-hi" min="${r.min}" max="${r.max}" step="${step}" value="${hi}" aria-label="To"></div>
          <div class="tq-rends"><span>${esc(tick(r.min))}${r.openLo ? (isTime ? ' or earlier' : ' or less') : ''}</span>${r.unit ? `<span class="muted">${esc(r.unit)}</span>` : ''}<span>${esc(tick(r.max))}${r.openHi ? (isTime ? ' or later' : '+') : ''}</span></div>
          <div class="tq-rnums"><label>From <input class="tq-nlo" ${box}></label><label>To <input class="tq-nhi" ${box}></label></div>
          <button type="button" class="tq-act tq-done" data-apply="1">Apply</button>
          ${chips.length ? `<h4 class="tq-h">Quick picks</h4><div class="tq-chipset">${chips.map(([l, v]) => `<button type="button" class="${Q.f[k] === v ? 'on' : ''}" data-fv="${esc(v)}">${esc(l)}</button>`).join('')}</div>` : ''}
          ${rmBtn(k)}`;
        const L = el.querySelector('.tq-lo'), H = el.querySelector('.tq-hi'), fill = el.querySelector('.tq-rfill'), out = el.querySelector('.tq-rv');
        const NL = el.querySelector('.tq-nlo'), NH = el.querySelector('.tq-nhi');
        const draw = () => {
          const pct = x => (100 * (x - r.min)) / (r.max - r.min);
          fill.style.left = `${pct(lo)}%`; fill.style.right = `${100 - pct(hi)}%`;
          const any = lo <= r.min && hi >= r.max;
          // a preset value (not a range) shows by name until a handle moves
          out.textContent = !moved && k in Q.f && !isR(F, Q.f[k]) ? cap(optLabel(k).replace(/^not /, '')) : any ? 'Any (drag the ends)' : cap(r.say(...parseR(F, `R:${lo}~${hi}`)));
          L.style.zIndex = lo >= r.max - step ? 3 : 2;  // a handle pushed to the far end stays grabbable
          if (document.activeElement !== NL) NL.value = toBox(lo);
          if (document.activeElement !== NH) NH.value = toBox(hi);
        };
        L.addEventListener('input', () => { lo = Math.min(+L.value, hi); L.value = lo; moved = true; draw(); });
        H.addEventListener('input', () => { hi = Math.max(+H.value, lo); H.value = hi; moved = true; draw(); });
        // typing: move the handle as soon as the number makes sense; settle (order, bounds) when the box is left
        const typed = (box2, isLo, settle) => {
          const v = fromBox(box2.value);
          if (!isFinite(v)) { if (settle) draw(); return; }
          const x = snap(v);
          if (isLo) lo = settle ? Math.min(x, hi) : x; else hi = settle ? Math.max(x, lo) : x;
          if (lo > hi) { if (isLo) hi = lo; else lo = hi; }
          L.value = lo; H.value = hi; moved = true;
          if (settle) box2.value = toBox(isLo ? lo : hi);
          draw();
        };
        [[NL, true], [NH, false]].forEach(([b2, isLo]) => {
          b2.addEventListener('input', () => typed(b2, isLo, false));
          b2.addEventListener('change', () => typed(b2, isLo, true));
          b2.addEventListener('keydown', e => { if (e.key === 'Enter') { typed(b2, isLo, true); b2.blur(); } });
        });
        draw();
        el.addEventListener('click', e => {
          const n = flipNot(el, e); if (n != null) { neg = n; return; }
          if (e.target.closest('[data-apply]')) {
            if (!moved && k in Q.f) setF(k, vals(k), neg);  // only Is / Is not changed
            else if (lo <= r.min && hi >= r.max) setF(k, []);
            else setF(k, [`R:${lo}~${hi}`], neg);
            done(); return;
          }
          const b = e.target.closest('[data-fv]'); if (b) { setF(k, [b.dataset.fv], neg); done(); return; }
          if (e.target.closest('[data-rm]')) { setF(k, []); done(); }
        });
        NFLE.sheet(F.label, el, opener);
      };
      const pickFilter = (k, opener) => {
        if (FILTERS[k].range) { pickRange(k, opener); return; }
        if (FILTERS[k].param === 'college') { pickCollege(k, opener); return; }
        if (FILTERS[k].param) { pickPerson(k, opener); return; }
        const F = FILTERS[k], el = panel(), sel = new Set(vals(k));
        let neg = isNot(k);
        // team filters: conferences and divisions (Opponent) as chips, teams as a grid
        const pick = (cls, os) => `<div class="${cls}">${os.map(o => `<button type="button" class="${sel.has(o[0]) ? 'on' : ''}" data-fv="${esc(o[0])}">${esc(o[0])}</button>`).join('')}</div>`;
        const isTeam = o => IX.teams.includes(o[0]);
        el.innerHTML = `${notSeg(k, neg)}${k === 'vs' || k === 'tm' ? (k === 'vs' ? `<h4 class="tq-h">Conference</h4>${pick('tq-chipset', F.opts.filter(o => o[0].length === 3 && !isTeam(o)))}
            <h4 class="tq-h">Division</h4>${pick('tq-chipset', F.opts.filter(o => o[0].includes(' ')))}<h4 class="tq-h">Team</h4>` : '') + pick('tq-teams', F.opts.filter(isTeam))
          : `<div class="tq-list">${F.opts.map(o => `<button type="button" class="tq-opt${sel.has(o[0]) ? ' on' : ''}" data-fv="${esc(o[0])}"><span>${esc(cap(o[1]))}</span>${o[3] ? `<small>${esc(o[3])}</small>` : ''}</button>`).join('')}</div>`}
          ${rmBtn(k)}${applyBar(sel.size)}`;
        el.addEventListener('click', e => {
          const n = flipNot(el, e); if (n != null) { neg = n; return; }
          const b = e.target.closest('[data-fv]'); if (b) { toggleSel(el, sel, b); return; }
          if (e.target.closest('[data-apply]')) { setF(k, F.opts.map(o => o[0]).filter(v => sel.has(v)), neg); done(); return; }
          if (e.target.closest('[data-rm]')) { setF(k, []); done(); }
        });
        NFLE.sheet(F.label, el, opener);
      };
      const pickAdd = opener => {
        const el = panel(), groups = {};
        Object.entries(FILTERS).filter(([k]) => !(k in Q.f) && allowed(k, Q.fam) && !(k === 'vs' && /^V:/.test(Q.who)) && !(k === 'tm' && /^T:/.test(Q.who))).forEach(([k, f]) => { (groups[f.group] = groups[f.group] || []).push([k, f]); });
        const list = t => Object.entries(groups).map(([g, fs]) => {
          const hit = fs.filter(([, f]) => !t || f.label.toLowerCase().includes(t) || f.opts.some(o => o[1].toLowerCase().includes(t)));
          return hit.length ? `<h4 class="tq-h">${esc(g)}</h4><div class="tq-list">${hit.map(([k, f]) => `<button type="button" class="tq-opt" data-fk="${k}"><span>${esc(f.label)}</span><small>${f.hint ? esc(f.hint) : !f.opts.length && f.range ? `${esc((f.range.presets || []).map(x => x[0]).join(', '))} or any range` : `${esc(f.opts.slice(0, 3).map(o => o[1]).join(', '))}${f.opts.length > 3 ? '&hellip;' : ''}${f.range ? ', or a range' : ''}`}</small>${sinceTag(f.need)}<span class="tq-go">&rsaquo;</span></button>`).join('')}</div>` : '';
        }).join('') || '<p class="muted tq-help">No filter matches.</p>';
        el.innerHTML = `<input class="dt-search tq-find" type="search" placeholder="Search: blitz, red zone, 3rd down, cold&hellip;" aria-label="Search filters" autocomplete="off"><div class="tq-fl">${list('')}</div>`;
        const inp = el.querySelector('.tq-find');
        inp.addEventListener('input', () => { el.querySelector('.tq-fl').innerHTML = list(inp.value.trim().toLowerCase()); });
        el.addEventListener('click', e => { const b = e.target.closest('[data-fk]'); if (b) pickFilter(b.dataset.fk, opener); });
        NFLE.sheet('Only plays where…', el, opener);
      };
      const pickSeasons = opener => {
        const el = panel(), S = IX.seasons, first = S[0], last = S[S.length - 1];
        const charted = S.find(y => covers(y, ['pz'])) || first;
        // the newest season in the data is "this season" while it's the site's current one (owner 2026-10-22: "shouldn't
        // that read this season?"); every preset shows its years
        const CFG = window.NFLE_CFG || {}, now = CFG.current && CFG.season === last;
        const presets = (now ? [['This season', last, last], ['Last season', last - 1, last - 1]] : [['Last season', last, last]])
          .concat([['Last 3 seasons', last - 2, last], ['Last 5 seasons', last - 4, last], ['Charting era', charted, last], ['Every season', first, last]])
          .filter(([, a, b]) => b >= first).map(([l, a, b]) => [l, Math.max(first, a), b]);
        const yrs = (a, b) => (a === b ? `${a}` : `${a}–${b}`);
        const draw = () => {
          el.innerHTML = `<div class="tq-list">${presets.map(([l, a, b]) => `<button type="button" class="tq-opt${Q.from === a && Q.to === b ? ' on' : ''}" data-span="${a}-${b}"><span>${esc(l)}${l === 'Charting era' ? ' <i class="tq-note">personnel, coverage, routes&hellip;</i>' : ''}</span><small class="tq-r">${yrs(a, b)}</small></button>`).join('')}</div>
            <h4 class="tq-h">Custom range</h4>
            <div class="tq-span"><select class="dt-select" data-yr="from" aria-label="From">${S.map(y => opt(y, y, Q.from)).join('')}</select><span class="muted">to</span><select class="dt-select" data-yr="to" aria-label="To">${S.map(y => opt(y, y, Q.to)).join('')}</select></div>
            <h4 class="tq-h">Games</h4>
            <div class="tq-seg">${[['reg', 'Regular season'], ['post', 'Playoffs'], ['both', 'Both']].map(([k, l]) => `<button type="button" data-st="${k}" class="${Q.st === k ? 'on' : ''}">${l}</button>`).join('')}</div>
            <button type="button" class="tq-act tq-done" data-done="1">Done</button>`;
        };
        draw();
        el.addEventListener('click', e => {
          const p = e.target.closest('[data-span]');
          if (p) { const [a, b] = p.dataset.span.split('-').map(Number); Q.from = a; Q.to = b; done(); return; }
          const s = e.target.closest('[data-st]'); if (s) { Q.st = s.dataset.st; update(); draw(); return; }
          if (e.target.closest('[data-done]')) NFLE.sheetClose();
        });
        el.addEventListener('change', e => {
          const y = e.target.closest('[data-yr]'); if (!y) return;
          Q[y.dataset.yr] = +y.value;
          if (Q.to < Q.from) { if (y.dataset.yr === 'from') Q.to = Q.from; else Q.from = Q.to; }
          update(); draw();
        });
        NFLE.sheet('Seasons', el, opener);
      };
      const pickBy = opener => {
        const el = panel();
        const ok = k => BY[k] && byAllowed(k, Q.fam) && !(k === 'player' && (Q.fam === 'team' || /^P:/.test(Q.who)));
        const set = (cur, attr, filt, after = {}) => BY_GROUPS.map(([g, ks]) => {
          const hit = ks.filter(filt);
          return hit.length ? `<h4 class="tq-h">${g}</h4><div class="tq-chipset">${hit.map(k => `<button type="button" data-${attr}="${k}" class="${cur === k ? 'on' : ''}">${esc(cap(BY[k][0]))}${sinceTag(BY[k][2])}</button>`).join('')}</div>${after[g] || ''}` : '';
        }).join('');
        let grid = !!Q.by2;  // the second split (a grid) stays folded away until it's set or asked for
        const gameOpts = () => {
          const [, m] = famMetric();
          if (Q.by === 'pmark') return `<div class="tq-gp"><label>Mark <input type="number" inputmode="decimal" step="any" data-gt value="${Q.gt ?? ''}" placeholder="${MARK[Q.met] ? MARK[Q.met](Q.fam) : 'league avg'}"></label>
            <span class="muted">${esc(m[0].toLowerCase())} in a game${LOWER.has(Q.met) ? ' (or less)' : ' (or more)'}</span></div>`;
          if (Q.by === 'pspan') return `<div class="tq-gp"><label>Games in a row <input type="number" inputmode="numeric" min="2" max="20" step="1" data-gn value="${Q.gn}"></label>
            <span class="muted">best ${esc(m[0].toLowerCase())} over that many straight games with a matching play</span></div>`;
          return '';
        };
        const draw = () => {
          el.innerHTML = `<p class="tq-help muted">One row per&hellip;</p>${set(Q.by, 'by', ok, { 'Game by game': gameOpts() })}
            <div class="tq-then">${GAMEBY.has(Q.by) ? '' : grid ? `<h4 class="tq-h">Then by <span class="muted">(columns of a grid)</span></h4>
            <div class="tq-chipset"><button type="button" data-by2="" class="${!Q.by2 ? 'on' : ''}">No grid</button></div>
            ${set(Q.by2, 'by2', k => ok(k) && k !== Q.by && !GRID_ROW_ONLY.has(k))}` : '<button type="button" class="tq-act tq-grid" data-grid="1">+ Split again into a grid</button>'}</div>
            <button type="button" class="tq-act tq-done" data-done="1">Done</button>`;
        };
        draw();
        el.addEventListener('click', e => {
          const a = e.target.closest('[data-by]'); if (a) { Q.by = a.dataset.by; if (Q.by2 === Q.by || GAMEBY.has(Q.by)) Q.by2 = ''; update(); draw(); return; }
          const b = e.target.closest('[data-by2]'); if (b) { Q.by2 = b.dataset.by2; update(); draw(); return; }
          if (e.target.closest('[data-grid]')) { grid = true; draw(); return; }
          if (e.target.closest('[data-done]')) NFLE.sheetClose();
        });
        el.addEventListener('change', e => {
          if (e.target.matches('[data-gt]')) { Q.gt = e.target.value === '' ? null : +e.target.value; update(); }
          if (e.target.matches('[data-gn]')) { Q.gn = Math.max(2, Math.min(20, Math.round(+e.target.value || 4))); e.target.value = Q.gn; update(); }
        });
        NFLE.sheet('Break down', el, opener);
      };
      const pickExamples = opener => {
        const el = panel();
        el.innerHTML = `<div class="tq-list">${EXAMPLES.map((x, i) => `<button type="button" class="tq-opt" data-ex="${i}"><span>${esc(x[0])}</span></button>`).join('')}</div>`;
        el.addEventListener('click', e => {
          const b = e.target.closest('[data-ex]'); if (!b) return;
          Q = Object.assign(defaults(), { from: Q.from, to: Q.to }, JSON.parse(JSON.stringify(EXAMPLES[+b.dataset.ex][1])));
          done();
        });
        NFLE.sheet('Examples', el, opener);
      };
      const PICK = { measure: pickMeasure, who: pickWho, add: pickAdd, seasons: pickSeasons, by: pickBy, examples: pickExamples };
      const save = () => { try { localStorage.setItem(LS, JSON.stringify(Q)); } catch (e) { /* private mode */ } };

      // ---- loading (the engine's): the player / coach search list for the seasons in range
      const loadBio = E.loadBio;
      const fillFind = () => E.people(Q).then(opts => { findMap = new Map(opts.map(o => [o[0], o])); });
      let findMap = new Map();

      const run = () => {
        const me = ++busy, covEl = sec.querySelector('.tr-cov');
        if (Q.who === 'S') return;
        covEl.innerHTML = '';
        sec.querySelector('.tr-base').textContent = 'Counting plays…';
        E.compute(Q).then(r => {
          if (me !== busy) return;
          const { dropped, limiting, chartedIn } = r;
          covEl.innerHTML = dropped.length ? `<p class="tr-covnote">${esc(limiting.join(', ') || 'Charting')} ${limiting.length > 1 ? 'are' : 'is'} not charted for ${esc(ranges(dropped))}, so ${dropped.length > 1 ? 'those seasons are' : 'that season is'} left out${chartedIn.length ? ` (charted: ${esc(ranges(chartedIn))})` : ''}.</p>` : '';
          if (r.missG.length) covEl.insertAdjacentHTML('beforeend', `<p class="tr-covnote">Game details (scores, rest, who played) aren't available for ${esc(ranges(r.missG))} yet, so ${r.missG.length > 1 ? 'those seasons are' : 'that season is'} left out.</p>`);
          if (r.missOn.length) covEl.insertAdjacentHTML('beforeend', `<p class="tr-covnote">Who was on the field is only published for 2016-2025, so ${esc(ranges(r.missOn))} ${r.missOn.length > 1 ? 'are' : 'is'} left out.</p>`);
          if (r.empty) {
            sec.querySelector('.tr-base').textContent = ''; sec.querySelector('.tr-trend').innerHTML = '';
            sec.querySelector('.tr-tbl').innerHTML = r.empty === 'on' ? '<p class="muted">Pick seasons from 2016 to 2025 for on-field stats.</p>' : '';
            paint = null; csvRows = null; return;
          }
          const { fam, m, league, lg, den, unit, plays, groups, names, teamOf, by, by2, GMODE, wk, extras } = r, lab = BYLABEL[Q.by];
          if (GMODE) {
            sec.querySelector('.tr-base').innerHTML = `League, same situation: <b>${fmt(lg, m[2])}</b> ${esc(m[0])} on ${fmt(league.n)} ${esc(fam.unit)}`;
            sec.querySelector('.tr-trend').innerHTML = '';
            const tb = sec.querySelector('.tr-tbl'), isT = Q.fam === 'team';
            const nameOf = e => (isT ? e : names[e] || e);
            const gl = E.gameLabel, ord = E.gameOrd;
            const { rows: rows2, mark, low } = E.gameRows(r);
            const who = { key: 'who', label: isT ? 'Team' : 'Player', stick: true, first: 'asc', value: x => nameOf(x.ent),
              html: x => (isT ? NFLE.ui.team(x.ent, TEAMS) : NFLE.ui.player({ name: nameOf(x.ent), team: teamOf[x.ent] }, TEAMS)) };
            const rowAttrs = x => `${NFLE.ui.tileStyle(TEAMS, isT ? x.ent : teamOf[x.ent])}${!isT && /^\d\d-\d{7}$/.test(x.ent) ? ` data-open-pid="${esc(x.ent)}"` : ''}`;
            let cols2, csvHead, csvRow, sortKey, note = '';
            if (Q.by === 'pgame') {
              cols2 = [who, { key: 'game', label: 'Game', value: x => ord(x.g), html: x => esc(gl(x.g)) },
                { key: 'n', label: unit, num: true, value: x => x.n, html: x => fmt(x.n) },
                { key: 'v', label: m[0], num: true, cls: 'tr-main', value: x => (isFinite(x.v) ? x.v : null), html: x => `<b>${fmt(x.v, m[2])}</b>` }];
              csvHead = [isT ? 'Team' : 'Player', 'Team', 'Season', 'Week', 'Opponent', unit, m[0]];
              csvRow = x => [nameOf(x.ent), x.g.team, x.g.s, x.g.post ? `post ${x.g.w}` : x.g.w, `${x.g.home ? 'vs' : '@'} ${x.g.opp}`, x.n, +(+x.v).toFixed(m[2])];
              sortKey = 'v';
            } else if (Q.by === 'pmark') {
              cols2 = [who, { key: 'v', label: 'Games', num: true, cls: 'tr-main', value: x => x.v, html: x => `<b>${x.v}</b>` },
                { key: 'games', label: 'Of', num: true, value: x => x.games, html: x => fmt(x.games) },
                { key: 'pct', label: '%', num: true, value: x => x.pct, html: x => `${x.pct.toFixed(0)}%` },
                { key: 'streak', label: 'Longest streak', num: true, value: x => x.streak, html: x => fmt(x.streak) },
                { key: 'last', label: 'Most recent', value: x => (x.last ? ord(x.last) : 0), html: x => (x.last ? esc(gl(x.last)) : '') }];
              csvHead = [isT ? 'Team' : 'Player', 'Games reaching the mark', 'Games', '%', 'Longest streak', 'Most recent'];
              csvRow = x => [nameOf(x.ent), x.v, x.games, +x.pct.toFixed(1), x.streak, x.last ? gl(x.last) : ''];
              sortKey = 'v';
              note = `A game counts when its ${esc(m[0])} is ${fmt(mark, m[2])}${low ? ' or less' : ' or more'}. Games = games with a matching play; a streak is games in a row among those.`;
            } else {
              const N = Q.gn;
              cols2 = [who, { key: 'v', label: `${m[0]}, best ${N} games`, num: true, cls: 'tr-main', value: x => x.v, html: x => `<b>${fmt(x.v, m[2])}</b>` },
                { key: 'n', label: unit, num: true, value: x => x.n, html: x => fmt(x.n) },
                { key: 'span', label: 'Games', value: x => ord(x.from), html: x => `${esc(gl(x.from))} to ${esc(gl(x.to))}` }];
              csvHead = [isT ? 'Team' : 'Player', `${m[0]} (best ${N} games)`, unit, 'From', 'To'];
              csvRow = x => [nameOf(x.ent), +(+x.v).toFixed(m[2]), x.n, gl(x.from), gl(x.to)];
              sortKey = 'v';
              note = `The best ${N} games in a row, among games with a matching play.`;
            }
            if (!isT) { const h = csvHead, f = csvRow; csvHead = [...h, 'Player ID']; csvRow = x => [...f(x), x.ent]; }
            const CAP = 500;
            paint = () => {
              const min = Q.min ?? defMin();
              let keep = E.keepRows(r, rows2, min);
              const total = keep.length;
              keep = keep.slice(0, CAP);
              tb.innerHTML = '';
              if (!keep.length) { csvRows = null; tb.innerHTML = `<p class="muted">Nothing reaches it${min > 1 ? ` with at least ${min} ${esc(unit.toLowerCase())}` : ''}.</p>`; return; }
              NFLE.Table(tb, { columns: cols2, rows: keep, sort: { key: sortKey, dir: Q.by !== 'pmark' && low ? 'asc' : 'desc' }, cls: 'tiles', rowClass: () => 'teamrow', rowAttrs });
              tb.insertAdjacentHTML('beforeend', `<p class="tr-hid muted">${note}${total > CAP ? ` Showing the top ${CAP} of ${fmt(total)}.` : ''} Minimum: ${min} ${esc(unit.toLowerCase())}${Q.by === 'pgame' ? ' in the game' : Q.by === 'pspan' ? ' over the stretch' : ''}.</p>`);
              csvRows = [csvHead, ...keep.map(csvRow)];
            };
            maxN = rows2.reduce((mx, x) => Math.max(mx, x.n), 0);
            const sl = qbox.querySelector('.tq-mrange'); if (sl) sl.max = Math.max(maxN, Q.min ?? 0, 10);
            paint();
            return;
          }
          const rows = E.tableRows(r);
          maxN = rows.reduce((mx, r) => Math.max(mx, r.n), 0);
          const slider = qbox.querySelector('.tr-min input');
          if (slider) slider.max = Math.max(maxN, Q.min ?? fam.min, fam.min * 2);
          const whoTxt = wk === 'L' ? '' : ` &middot; this query: ${fmt(plays)} ${esc(fam.unit)}`;
          if (by2) {
            sec.querySelector('.tr-base').innerHTML = `League, same situation: <b>${fmt(lg, m[2])}</b> ${esc(m[0])} on ${fmt(league.n)} ${esc(fam.unit)}${whoTxt}`;
            sec.querySelector('.tr-trend').innerHTML = '';
            const lab2 = BYLABEL[Q.by2], tb = sec.querySelector('.tr-tbl');
            const rowLab = k => Q.by === 'player' ? names[k] || k : lab ? lab(numKey(k)) : String(k);
            const colLab = k => lab2 ? lab2(numKey(k)) : String(k);
            const cells = [...groups.values()].map(a => ({ r: a._k[0], c: a._k[1], a, n: den(a), v: m[1](a) }));
            const order = (keys, how, tot) => how === 'v' ? keys.sort((x, y) => tot.get(y) - tot.get(x))
              : keys.sort((x, y) => { const p = numKey(x), q = numKey(y), d = typeof p === 'number' && typeof q === 'number' ? p - q : String(p).localeCompare(String(q)); return how === 'kd' ? -d : d; });
            const totR = new Map(), totC = new Map(), allR = new Map();
            // each row's overall accumulator (the "All" column, and the order of player / team rows: best first)
            const merge = (t, a) => { Object.keys(a).forEach(k => { if (k !== '_k') t[k] = k === 'lg' ? Math.max(t[k] || 0, a[k]) : (t[k] || 0) + a[k]; }); return t; };
            cells.forEach(x => { totR.set(x.r, (totR.get(x.r) || 0) + x.n); totC.set(x.c, (totC.get(x.c) || 0) + x.n);
              allR.set(x.r, merge(allR.get(x.r) || blank(), x.a)); });
            const rowV = r => { const a = allR.get(r); const v = m[1](a); return den(a) >= (Q.min ?? fam.min) && isFinite(v) ? v : null; };
            const byMetric = keys => keys.sort((x, y) => { const p = rowV(x), q = rowV(y); if (p == null || q == null) return (p == null) - (q == null) || totR.get(y) - totR.get(x); return LOWER.has(Q.met) ? p - q : q - p; });
            const rowsK = by[3] === 'v' ? byMetric([...totR.keys()]) : order([...totR.keys()], by[3], totR), colsK = order([...totC.keys()], by2[3], totC);
            // too many: keep the biggest samples, then restore the grouping's own order
            const keep = (keys, tot, cap, how) => keys.length <= cap ? keys : order([...keys].sort((x, y) => tot.get(y) - tot.get(x)).slice(0, cap), how, tot);
            const R = rowsK.length <= GRID_MAX_ROWS ? rowsK : by[3] === 'v' ? byMetric([...rowsK].sort((x, y) => totR.get(y) - totR.get(x)).slice(0, GRID_MAX_ROWS)) : keep(rowsK, totR, GRID_MAX_ROWS, by[3]);
            const C = keep(colsK, totC, GRID_MAX_COLS, by2[3]);
            const at = new Map(cells.map(x => [`${x.r}||${x.c}`, x]));
            const lowGood = LOWER.has(Q.met), count = m[2] === 0;
            const draw = () => {
              const min = Q.min ?? fam.min, shown = cells.filter(x => x.n >= min && isFinite(x.v));
              const spread = count ? Math.max(1, ...shown.map(x => x.v)) : Math.max(1e-9, ...shown.map(x => Math.abs(x.v - lg)));
              const shade = x => {
                if (count) return `background: color-mix(in srgb, var(--accent) ${Math.round(8 + 52 * x.v / spread)}%, var(--panel2))`;
                const d = x.v - lg, good = lowGood ? d < 0 : d > 0, w = Math.round(8 + 52 * Math.min(1, Math.abs(d) / spread));
                return `background: color-mix(in srgb, ${good ? '#4fbf6f' : '#d9655b'} ${w}%, var(--panel2))`;
              };
              const hidden = cells.filter(x => x.n < min).length;
              const head = `<tr><th class="tr-gc0">${esc(by[0])} <span class="muted">/</span> ${esc(by2[0])}</th>${C.map(c => `<th>${['team', 'opp'].includes(Q.by2) ? NFLE.ui.tm(c, esc(colLab(c))) : esc(colLab(c))}</th>`).join('')}<th class="tr-gall">All</th></tr>`;
              const allCell = r => { const a = allR.get(r), n = den(a), v = m[1](a);
                return n >= min && isFinite(v) ? `<td class="tr-gall" style="${shade({ v, n })}"><b>${fmt(v, m[2])}</b><i>${fmt(n)}</i></td>` : '<td class="tr-ge tr-gall">&middot;</td>'; };
              const body = R.map(r => `<tr><th class="tr-gc0"${Q.by === 'player' && /^\d\d-\d{7}$/.test(r) ? ` data-open-pid="${esc(r)}"` : ''}>${['team', 'opp'].includes(Q.by) ? NFLE.ui.tm(r, esc(rowLab(r))) : esc(rowLab(r))}${Q.by === 'player' && teamOf[r] ? ` <span class="sub">${NFLE.ui.tm(teamOf[r])}</span>` : ''}</th>${C.map(c => {
                const x = at.get(`${r}||${c}`);
                if (!x || x.n < min || !isFinite(x.v)) return `<td class="tr-ge" title="${x ? `${fmt(x.n)} ${esc(unit.toLowerCase())}: under the minimum` : 'none'}">&middot;</td>`;
                return `<td style="${shade(x)}" title="${esc(rowLab(r))} / ${esc(colLab(c))}: ${fmt(x.v, m[2])} ${esc(m[0])} on ${fmt(x.n)} ${esc(unit.toLowerCase())}"><b>${fmt(x.v, m[2])}</b><i>${fmt(x.n)}</i></td>`;
              }).join('')}${allCell(r)}</tr>`).join('');
              const capped = (R.length < rowsK.length ? ` Showing the ${R.length} ${esc(by[0])} rows with the most ${esc(fam.unit)}.` : '') + (C.length < colsK.length ? ` Showing ${C.length} of ${colsK.length} columns.` : '');
              csvRows = [[`${by[0]} / ${by2[0]}`, ...C.map(colLab), 'All'], ...R.map(r => [rowLab(r), ...C.map(c => { const x = at.get(`${r}||${c}`); return x && x.n >= min && isFinite(x.v) ? +x.v.toFixed(m[2]) : ''; }),
                (() => { const a = allR.get(r), v = m[1](a); return den(a) >= min && isFinite(v) ? +v.toFixed(m[2]) : ''; })()])];
              tb.innerHTML = `<p class="tr-gnote muted">${count ? 'Darker = more.' : `Green = better than the league (${fmt(lg, m[2])}), red = worse.`} Small number = ${esc(unit.toLowerCase())}.${hidden ? ` ${hidden} cell${hidden === 1 ? '' : 's'} under ${min} hidden (&middot;).` : ''}${capped}</p>
                <div class="tr-gwrap"><table class="tr-grid"><thead>${head}</thead><tbody>${body}</tbody></table></div>`;
            };
            maxN = cells.reduce((mx, x) => Math.max(mx, x.n), 0);
            const slider = qbox.querySelector('.tr-min input');
            if (slider) slider.max = Math.max(maxN, Q.min ?? fam.min, fam.min * 2);
            paint = draw; draw();
            return;
          }
          sec.querySelector('.tr-base').innerHTML = `League, same situation: <b>${fmt(lg, m[2])}</b> ${esc(m[0])} on ${fmt(league.n)} ${esc(fam.unit)}${whoTxt}`;
          const trend = sec.querySelector('.tr-trend');
          if (Q.by === 'season' && rows.length > 1) {
            // the vertical range is the seasons' own (owner 2026-10-22: "are we setting the vertical range appropriately?":
            // a count's league line is the league TOTAL, thousands against a player's dozens, so it flattened the line).
            // A rate keeps the league line and includes it in the range; a count has none. Padding 8% each way; the
            // range's ends are labeled.
            const r = rows.filter(x => isFinite(x.v)).sort((x, y) => x.key - y.key), vs = r.map(x => x.v), isCount = m[2] === 0, W = 320, H = 96, L0 = 34;
            let lo = Math.min(...vs, ...(isCount ? [] : [lg])), hi = Math.max(...vs, ...(isCount ? [] : [lg]));
            const pad = (hi - lo) * 0.08 || Math.abs(hi) * 0.1 || 1;
            lo -= pad; hi += pad;
            if (isCount && lo < 0 && Math.min(...vs) >= 0) lo = 0;
            const X = i => L0 + i * (W - L0 - 12) / Math.max(1, r.length - 1), Y = v => H - 18 - (v - lo) / ((hi - lo) || 1) * (H - 28);
            const tick = v => fmt(v, isCount ? 0 : m[2]);
            trend.innerHTML = `<svg class="tr-svg" viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(m[0])} by season">
              <text x="${L0 - 6}" y="${Y(hi - pad) + 3}" class="tr-ax">${tick(hi - pad)}</text><text x="${L0 - 6}" y="${Y(lo + (isCount && lo === 0 ? 0 : pad)) + 3}" class="tr-ax">${tick(lo + (isCount && lo === 0 ? 0 : pad))}</text>
              ${isCount ? '' : `<line x1="${L0 - 2}" x2="${W - 6}" y1="${Y(lg)}" y2="${Y(lg)}" class="tr-lg"><title>League ${fmt(lg, m[2])}</title></line>`}
              <polyline points="${r.map((x, i) => `${X(i)},${Y(x.v)}`).join(' ')}" class="tr-pl"/>${r.map((x, i) => `<circle cx="${X(i)}" cy="${Y(x.v)}" r="3" class="tr-pt${+x.key === IX.current ? ' tr-pt-now' : ''}"><title>${x.key}: ${fmt(x.v, m[2])}${+x.key === IX.current ? ' (season so far)' : ''}</title></circle>
              <text x="${X(i)}" y="${H - 2}" class="tr-yr">${String(x.key).slice(2)}</text>`).join('')}</svg>`;
          } else trend.innerHTML = '';
          const isTeam = Q.by === 'team' || Q.by === 'opp';
          const cols = [
            { key: 'label', label: by[0][0].toUpperCase() + by[0].slice(1), stick: true, first: 'asc', value: r => by[3] === 'v' ? r.label : r.key,
              html: r => Q.by === 'player' ? NFLE.ui.player({ name: r.label, team: r.team }, TEAMS)
                : isTeam ? NFLE.ui.team(r.key, TEAMS) : `<b>${esc(r.label)}</b>` },
            { key: 'n', label: unit, num: true, value: r => r.n, html: r => fmt(r.n) },
            { key: 'v', label: m[0], num: true, cls: 'tr-main', value: r => isFinite(r.v) ? r.v : null, html: r => `<b>${fmt(r.v, m[2])}</b>` },
            // rates compare with the league rate; counts (0 decimals: yards, catches, TDs...) as a share of the league total
            m[2] === 0
              ? { key: 'dv', label: 'Share of league', num: true, value: r => lg > 0 ? r.v / lg : null,
                  html: r => lg > 0 ? `<span title="League total ${fmt(lg, m[2])}">${(100 * r.v / lg).toFixed(1)}%</span>` : '–' }
              : { key: 'dv', label: 'vs league', num: true, value: r => isFinite(r.v) ? r.v - lg : null,
                  html: r => { const d = r.v - lg; return isFinite(d) ? `<span title="League ${fmt(lg, m[2])}" class="${d > 0 ? 'tr-up' : d < 0 ? 'tr-dn' : ''}">${d > 0 ? '+' : ''}${fmt(d, m[2])}</span>` : '–'; } },
            ...extras.map(([k, mm]) => ({ key: `m_${k}`, label: mm[0], num: true,
              value: r => { const v = mm[1](r.a); return isFinite(v) ? v : null; }, html: r => fmt(mm[1](r.a), mm[2]) })),
          ];
          const tb = sec.querySelector('.tr-tbl');
          if (!rows.length) { tb.innerHTML = '<p class="muted">No plays match.</p>'; paint = null; csvRows = null; return; }
          const sort = by[3] === 'v' ? { key: 'v', dir: 'desc' } : { key: 'label', dir: by[3] === 'kd' ? 'desc' : 'asc' };
          // player / team rows are team-colored tiles like every other list (NFLE.ui); other groupings stay plain
          const tiled = Q.by === 'player' || isTeam, tm = r => Q.by === 'player' ? r.team : r.key;
          const o = { columns: cols, rows, sort, cls: tiled ? 'tiles' : '',
            rowClass: () => tiled ? `teamrow${isTeam ? ' tm-open' : ''}` : '',
            rowAttrs: r => `${tiled ? NFLE.ui.tileStyle(TEAMS, tm(r)) : ''}${Q.by === 'player' && /^\d\d-\d{7}$/.test(r.key) ? ` data-open-pid="${esc(r.key)}"` : ''}${isTeam ? ` data-tm="${esc(r.key)}"` : ''}` };
          paint = () => {
            const min = Q.min ?? fam.min, keep = rows.filter(r => r.n >= min), hid = rows.length - keep.length;
            tb.innerHTML = '';
            if (!keep.length) { csvRows = null; tb.innerHTML = `<p class="muted">All ${rows.length} rows have fewer than ${min} ${esc(unit.toLowerCase())}. Lower the minimum to see them.</p>`; return; }
            NFLE.Table(tb, Object.assign(o, { rows: keep }));
            const num = (v, d) => (v == null || !isFinite(v) ? '' : +(+v).toFixed(d));
            csvRows = [[cols[0].label, ...(Q.by === 'player' ? ['Team'] : []), unit, m[0], m[2] === 0 ? 'Share of league %' : 'vs league', ...extras.map(([, mm]) => mm[0]), ...(Q.by === 'player' ? ['Player ID'] : [])],
              ...keep.slice().sort(by[3] === 'v' ? (x, y) => (LOWER.has(Q.met) ? -1 : 1) * ((y.v || 0) - (x.v || 0)) : (x, y) => (by[3] === 'kd' ? -1 : 1) * (x.key > y.key ? 1 : x.key < y.key ? -1 : 0)).map(r => [r.label, ...(Q.by === 'player' ? [r.team || ''] : []), r.n, num(r.v, m[2]),
                m[2] === 0 ? (lg > 0 ? num((100 * r.v) / lg, 1) : '') : num(r.v - lg, m[2]), ...extras.map(([, mm]) => num(mm[1](r.a), mm[2])), ...(Q.by === 'player' ? [r.key] : [])])];
            if (hid) tb.insertAdjacentHTML('beforeend', `<p class="tr-hid muted">${hid} ${hid === 1 ? 'row' : 'rows'} under ${min} ${esc(unit.toLowerCase())} hidden.</p>`);
          };
          paint();
        }).catch(e => { sec.querySelector('.tr-base').textContent = `Couldn't load plays (${e.message}).`; });
      };
      const update = () => { Object.keys(Q.fn).forEach(k => { if (!(k in Q.f)) delete Q.fn[k]; }); save(); render(); run(); };

      // ---- events (delegated: the builder redraws on every change)
      // the minimum: slider, number box and -/+ all set it; re-filter only (the counts don't depend on it)
      const setMin = (v, from) => {
        Q.min = Math.max(0, Math.round(v));
        const R = qbox.querySelector('.tq-mrange'), N = qbox.querySelector('.tq-mnum');
        if (R) { if (Q.min > +R.max) R.max = Q.min; if (from !== R) R.value = Q.min; }
        if (N && from !== N) N.value = Q.min;
        save();
        if (paint) paint();
      };
      qbox.addEventListener('input', e => {
        if (e.target.matches('.tq-mrange')) setMin(+e.target.value, e.target);
        else if (e.target.matches('.tq-mnum') && e.target.value !== '' && isFinite(+e.target.value)) setMin(+e.target.value, e.target);
      });
      qbox.addEventListener('change', e => { if (e.target.matches('.tq-mnum')) setMin(+e.target.value || 0); });
      qbox.addEventListener('click', e => {
        const stp = e.target.closest('.tr-step');
        if (stp) {
          setMin((Q.min ?? defMin()) + +stp.dataset.step);
          return;
        }
        const x = e.target.closest('[data-x]');
        if (x) { delete Q.f[x.dataset.x]; update(); return; }
        const fx = e.target.closest('[data-fx]');
        if (fx) { pickFilter(fx.dataset.fx, fx); return; }
        const pk = e.target.closest('[data-pick]');
        if (pk && PICK[pk.dataset.pick]) { PICK[pk.dataset.pick](pk); return; }
        if (e.target.closest('.tq-reset')) {
          const last = IX.seasons[IX.seasons.length - 1];
          Q = Object.assign(defaults(), { from: Math.max(IX.seasons[0], last - 2), to: last });
          update();
          return;
        }
        if (e.target.closest('[data-csv]')) {
          if (!csvRows) { e.target.closest('[data-csv]').textContent = 'Nothing to export'; setTimeout(() => { const b = qbox.querySelector('[data-csv]'); if (b) b.textContent = 'Download CSV'; }, 1600); return; }
          const cell = v => { const t = String(v ?? ''); return /[",\n]/.test(t) ? `"${t.replace(/"/g, '""')}"` : t; };
          const title = qbox.querySelector('.tq-sum').textContent.replace(/\s+/g, ' ').trim();
          const text = [[title], ...csvRows].map(r => r.map(cell).join(',')).join('\r\n');
          const a = document.createElement('a');
          a.href = URL.createObjectURL(new Blob(['\ufeff' + text], { type: 'text/csv;charset=utf-8' }));
          a.download = `${title.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '').slice(0, 80) || 'trends'}.csv`;
          document.body.appendChild(a); a.click(); a.remove();
          setTimeout(() => URL.revokeObjectURL(a.href), 4000);
          return;
        }
        if (e.target.closest('.tr-share')) {
          const t = btoa(unescape(encodeURIComponent(JSON.stringify(Q))));
          const url = `${location.origin}${location.pathname}?t=${encodeURIComponent(t)}#players/trends`;
          const ok = () => { const b = e.target.closest('.tr-share'); b.textContent = 'Link copied'; setTimeout(() => { b.textContent = 'Copy link'; }, 1600); };
          if (navigator.share && matchMedia('(pointer: coarse)').matches) navigator.share({ url }).catch(() => {});
          else if (navigator.clipboard) navigator.clipboard.writeText(url).then(ok, () => prompt('Copy this link', url));
          else prompt('Copy this link', url);
        }
      });
      E.init().then(ix => {
        IX = ix;
        Q = E.normalize(Object.assign({}, saved() || {}, fromUrl() || {}));
        // a shared link seeds the query once; drop ?t= so later edits (saved locally) survive a reload
        if (location.search.includes('t=')) history.replaceState(null, '', location.pathname + location.hash);
        update();
      }).catch(() => { sec.querySelector('.tr-base').textContent = 'Play data is not available on this page.'; });
    },
  };
})();
