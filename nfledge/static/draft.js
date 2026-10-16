// Teams > Draft: every pick of a draft (data/draft/<year>.json, tools/draft_build.py, 1980 on) with how the career
// turned out. Year picker, team / position / round filters, search; sortable. Drafted players we know open their page.
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
  const columns = teams => [
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
        </div><div class="dr-tbl"></div></div>
        <p class="st-note muted">Pro Football Reference via nflverse. Career numbers include this season so far; Approximate Value (AV) rates a season at any position on one scale.</p>`;
      const sub = sec.querySelector('.dr-sub'), selY = sec.querySelector('.dr-year'), selT = sec.querySelector('.dr-team'),
            selP = sec.querySelector('.dr-pos'), selR = sec.querySelector('.dr-round'), qi = sec.querySelector('.dr-q');
      let rows = [], table = null, teams = {};
      const filtered = () => {
        const q = qi.value.trim().toLowerCase();
        return rows.filter(r => (!selT.value || r.fr === selT.value) && (!selP.value || r.category === selP.value) && (!selR.value || r.round === +selR.value)
          && (!q || (r.pfr_player_name || '').toLowerCase().includes(q) || (r.college || '').toLowerCase().includes(q)));
      };
      const draw = () => {
        if (!table) table = NFLE.Table(sec.querySelector('.dr-tbl'), { columns: columns(teams), rows: filtered(), sort: { key: 'pick', dir: 'asc' },
          cls: 'tiles', rowClass: () => 'teamrow', rowAttrs: r => `${NFLE.ui.tileStyle(teams, r.fr)}${r.gsis_id ? ` data-open-pid="${esc(r.gsis_id)}"` : ''}` });
        else { table.setColumns(columns(teams)); table.update(filtered()); }
      };
      const fill = (sel, vals) => {
        const cur = sel.value; sel.length = 1;
        vals.forEach(v => sel.insertAdjacentHTML('beforeend', `<option value="${esc(v[0])}">${esc(v[1])}</option>`));
        sel.value = vals.some(v => String(v[0]) === cur) ? cur : '';
      };
      const load = y => NFLE.load(`data/draft/${y}.json`).then(d => {
        teams = Object.assign({}, d.teams || {}, WT);  // the week map has both trim colors
        rows = d.rows.map(v => Object.assign({ season: y }, Object.fromEntries(d.cols.map((c, i) => [c, v[i]]))));
        fill(selT, [...new Set(rows.map(r => r.fr))].sort().map(a => [a, (teams[a] && teams[a].nick) || a]));
        fill(selP, [...new Set(rows.map(r => r.category).filter(Boolean))].sort().map(c => [c, c]));
        fill(selR, [...new Set(rows.map(r => r.round))].sort((a, b) => a - b).map(r => [r, `Round ${r}`]));
        sub.textContent = `${y} NFL Draft: ${rows.length} picks`;
        draw();
      }).catch(() => { sub.textContent = 'No draft data for that year.'; });
      [selT, selP, selR].forEach(s => { s.onchange = () => table && table.update(filtered()); });
      qi.oninput = () => table && table.update(filtered());
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
