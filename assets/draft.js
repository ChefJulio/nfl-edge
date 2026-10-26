// Teams > Draft: every pick of a draft (data/draft/<year>.json, tools/draft_build.py, 1980 on) with how the career
// turned out. Year picker, team / position / round filters, search; sortable. Drafted players we know open their page.
// Search (owner 2026-10-21: a search shouldn't stack on the filters, and a name shouldn't need its year): 2+ letters
// search every draft by player or school (data/draft/search.json, tools/draft_build.py), set the year / team /
// position / round pickers aside (dimmed) and list the matches with their year; the 12 latest drafts with a match load.
(() => {
  const NFLE = window.NFLE, esc = NFLE.esc;
  const pageSeason = () => { const m = location.pathname.match(/(\d{4})\/week-\d+\.html$/); return m ? +m[1] : null; };
  const n = v => v == null ? '' : Math.round(v).toLocaleString();
  const career = r => {  // the career line that fits the position
    const parts = [];
    if (r.pass_yards) parts.push(`${n(r.pass_yards)} pass yds, ${n(r.pass_tds)} TD`);
    if (r.rush_yards && (r.category === 'RB' || r.rush_yards >= 500)) parts.push(`${n(r.rush_yards)} rush yds, ${n(r.rush_tds)} TD`);
    if (r.rec_yards) parts.push(`${n(r.receptions)} rec, ${n(r.rec_yards)} yds, ${n(r.rec_tds)} TD`);
    if (r.side === 'D' && (r.def_solo_tackles || r.def_sacks || r.def_ints)) {
      parts.push([r.def_solo_tackles ? `${n(r.def_solo_tackles)} solo tkl` : '', r.def_sacks ? `${r.def_sacks} sacks` : '', r.def_ints ? `${n(r.def_ints)} INT` : ''].filter(Boolean).join(', '));
    }
    return parts.join(' · ');
  };
  const YEAR_COL = { key: 'season', label: 'Year', num: true, first: 'desc', title: 'Draft year' };
  const MAX_YEARS = 12;  // drafts loaded for one search (a school like Alabama matches nearly every year)
  const columns = (teams, searching) => [
    ...(searching ? [YEAR_COL] : []),
    { key: 'pick', label: 'Pick', num: true, first: 'asc', html: r => `<b>${r.pick}</b><span class="sub">R${r.round}:${r.in_rd}</span>` },
    { key: 'fr', label: 'Team', first: 'asc', value: r => r.team, html: r => {
        const t = teams[r.fr] || {};
        return `<span class="tm-open dr-tm" data-tm="${esc(r.fr)}">${NFLE.fmt.logo(teams, r.fr, 20)}<span>${esc(r.fr || r.team)}</span></span>`;
      } },
    { key: 'name', label: 'Player', stick: true, first: 'asc', value: r => r.pfr_player_name,
      html: r => NFLE.ui.player({ name: r.pfr_player_name, team: r.fr, pid: r.gsis_id, sub: `${r.position || ''} · ${r.college || ''}`,
        badges: r.hof ? ' <span class="dr-hof" title="Pro Football Hall of Fame">HOF</span>' : '' }, teams) },
    { key: 'age', label: 'Age', num: true, first: 'asc' },
    { key: 'yrs', label: 'Yrs', num: true, title: 'Seasons from his draft year to his last season', value: r => r.to ? r.to - r.season + 1 : null, html: r => r.to ? r.to - r.season + 1 : '' },
    { key: 'games', label: 'G', num: true, title: 'Career games' },
    { key: 'seasons_started', label: 'Starter', num: true, title: "Seasons as his team's primary starter" },
    { key: 'probowls', label: 'Pro Bowls', num: true }, { key: 'allpro', label: 'All-Pro', num: true, title: 'First-team All-Pro selections' },
    { key: 'w_av', label: 'Career AV', num: true, cls: 'key', title: 'Weighted career Approximate Value (Pro Football Reference): one number for a career at any position' },
    { key: 'dr_av', label: 'AV for team', num: true, title: 'Approximate Value produced for the team that drafted him' },
    { key: 'career', label: 'Career', sort: false, cls: 'dr-career', html: r => esc(career(r)) },
  ];
  NFLE.areas.draft = {
    mount(sec) {
      sec.classList.remove('soon');
      sec.innerHTML = `<div class="sec-head"><div><h2>Draft</h2><p class="dr-sub">Loading&hellip;</p></div></div>
        <div class="dt-card"><div class="dt-tools">
          <select class="dt-select dr-year" aria-label="Draft year"></select>
          <select class="dt-select dr-team" aria-label="Team"><option value="">All teams</option></select>
          <select class="dt-select dr-pos" aria-label="Position"><option value="">All positions</option></select>
          <select class="dt-select dr-round" aria-label="Round"><option value="">All rounds</option></select>
          <input class="dr-q" type="search" placeholder="Find a player or school" aria-label="Find a player or school">
        </div><div class="skel-zone dr-tbl"></div></div>
        <p class="st-note muted">Pro Football Reference via nflverse. Career numbers include this season so far; Approximate Value (AV) rates a season at any position on one scale.</p>`;
      const sub = sec.querySelector('.dr-sub'), selY = sec.querySelector('.dr-year'), selT = sec.querySelector('.dr-team'),
            selP = sec.querySelector('.dr-pos'), selR = sec.querySelector('.dr-round'), qi = sec.querySelector('.dr-q');
      let rows = [], table = null, teams = {}, hits = null, yearSub = '', seq = 0;
      const filtered = () => hits || rows.filter(r => (!selT.value || r.fr === selT.value) && (!selP.value || r.category === selP.value) && (!selR.value || r.round === +selR.value));
      const draw = (resort = false) => {
        if (!table) table = NFLE.Table(sec.querySelector('.dr-tbl'), { howto: true, columns: columns(teams, !!hits), rows: filtered(), sort: { key: 'pick', dir: 'asc' },
          cls: 'tiles', rowClass: () => 'teamrow', rowAttrs: r => `${NFLE.ui.tileStyle(teams, r.fr)}${r.gsis_id ? ` data-open-pid="${esc(r.gsis_id)}"` : ''}` });
        else { table.setColumns(columns(teams, !!hits)); table.update(filtered()); }
        if (resort) table.setSort(hits ? { key: 'season', dir: 'desc' } : { key: 'pick', dir: 'asc' });
      };
      // a year's rows (row order = the search index's), its clubs as they were that year (shell.js fmt.era)
      const rowsOf = (d, y) => {
        teams = Object.assign(teams, d.teams || {}, WT);  // the week map has both trim colors
        return d.rows.map((v, i) => { const r = Object.assign({ season: y, _i: i }, Object.fromEntries(d.cols.map((c, j) => [c, v[j]])));
          r.fr = NFLE.fmt.era(r.fr, y); return r; });
      };
      let SIX = null;
      const searchIx = () => SIX || (SIX = NFLE.load('data/draft/search.json').then(j => {
        const out = [];
        Object.entries(j.y || {}).forEach(([y, txt]) => String(txt).split('\n').forEach((ln, i) => {
          const k = ln.lastIndexOf('|');
          out.push({ y: +y, i, n: ln.slice(0, k).toLowerCase(), c: String(j.c[+ln.slice(k + 1)] || '').toLowerCase() });
        }));
        return out;
      }));
      const search = () => {
        const raw = qi.value.trim(), q = raw.toLowerCase(), my = ++seq, on = q.length >= 2;
        [selY, selT, selP, selR].forEach(x => { x.disabled = on; });
        if (!on) { const was = !!hits; hits = null; sub.textContent = yearSub; draw(was); return; }
        searchIx().then(ix => {
          const m = ix.filter(e => e.n.includes(q) || e.c.includes(q));
          const ys = [...new Set(m.map(e => e.y))].sort((a, b) => b - a), use = ys.slice(0, MAX_YEARS);
          return Promise.all(use.map(y => NFLE.load(`data/draft/${y}.json`).then(d => rowsOf(d, y)))).then(lists => {
            if (my !== seq) return;  // a newer keystroke
            const want = new Set(m.filter(e => use.includes(e.y)).map(e => `${e.y}:${e.i}`));
            const was = !!hits;
            hits = lists.flat().filter(r => want.has(`${r.season}:${r._i}`)).sort((a, b) => b.season - a.season || a.pick - b.pick);
            const n = hits.length, all = m.length;
            sub.textContent = !all ? `No pick matches "${raw}" in any draft` : ys.length > MAX_YEARS
              ? `"${raw}": ${n} picks in the ${MAX_YEARS} latest drafts with one (${all} picks in ${ys.length} drafts)`
              : `"${raw}": ${all} pick${all === 1 ? '' : 's'} in ${ys.length} draft${ys.length === 1 ? '' : 's'}`;
            draw(!was);
          });
        }).catch(() => { if (my === seq) sub.textContent = 'Search is not available right now.'; });
      };
      const fill = (sel, vals) => {
        const cur = sel.value; sel.length = 1;
        vals.forEach(v => sel.insertAdjacentHTML('beforeend', `<option value="${esc(v[0])}">${esc(v[1])}</option>`));
        sel.value = vals.some(v => String(v[0]) === cur) ? cur : '';
      };
      const load = y => NFLE.load(`data/draft/${y}.json`).then(d => {
        rows = rowsOf(d, y);
        fill(selT, NFLE.fmt.teamOpts(teams, rows.map(r => r.fr)));
        fill(selP, [...new Set(rows.map(r => r.category).filter(Boolean))].sort().map(c => [c, c]));
        fill(selR, [...new Set(rows.map(r => r.round))].sort((a, b) => a - b).map(r => [r, `Round ${r}`]));
        yearSub = `${y} NFL Draft: ${rows.length} picks`;
        if (!hits) { sub.textContent = yearSub; draw(); }
      }).catch(() => { sub.textContent = 'No draft data for that year.'; });
      [selT, selP, selR].forEach(s => { s.onchange = () => table && table.update(filtered()); });
      qi.oninput = search;
      let WT = {};
      Promise.all([NFLE.load('data/draft/index.json'), NFLE.week(), NFLE.ui.ready]).then(([ix, wk]) => {
        WT = (wk && wk.teams) || {};
        const ps = pageSeason(), want = ps && ix.years.includes(ps) ? ps : ix.years[ix.years.length - 1];
        selY.innerHTML = [...ix.years].reverse().map(y => `<option value="${y}"${y === want ? ' selected' : ''}>${y}</option>`).join('');
        selY.onchange = () => load(+selY.value);
        load(want);
      }).catch(() => { sub.textContent = 'Draft data is not available on this page.'; });
    },
  };
})();
