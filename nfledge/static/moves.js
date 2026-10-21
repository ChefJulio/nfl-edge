// Players > Moves: every roster move ESPN logs (data/transactions/<season>.json, tools/transactions_build.py, 2002 on),
// one row per player per move, newest first. Season / team / move type / position / date range filters and a search;
// players we know open their page. The full move text rides along, so nothing the parser missed is lost.
(() => {
  const NFLE = window.NFLE, esc = NFLE.esc;
  const pageSeason = () => { const m = location.pathname.match(/(\d{4})\/week-\d+\.html$/); return m ? +m[1] : null; };
  const LABEL = { signed: 'Signed', re_signed: 'Re-signed', extended: 'Extended', tendered: 'Tendered', option: 'Option',
    released: 'Released', waived: 'Waived', ps_signed: 'PS signed', ps_released: 'PS released', ps_elevated: 'Elevated', promoted: 'Promoted',
    ir: 'IR', pup: 'PUP', nfi: 'NFI', designated: 'Return window', activated: 'Activated', reserve: 'Reserve list',
    traded: 'Traded', claimed: 'Claimed', acquired: 'Acquired', retired: 'Retired', suspended: 'Suspended',
    reinstated: 'Reinstated', free_agent: 'Free agent', staff: 'Staff', other: 'Other' };
  // filter groups; the tone colors the chip (adds green, losses red, injury lists amber)
  const GROUPS = [
    ['add', 'Signings', ['signed', 're_signed', 'extended', 'tendered', 'option']],
    ['cut', 'Releases', ['released', 'waived']],
    ['ps', 'Practice squad', ['ps_signed', 'ps_released', 'ps_elevated', 'promoted']],
    ['inj', 'Injury lists', ['ir', 'pup', 'nfi', 'designated', 'activated', 'reserve']],
    ['trade', 'Trades & claims', ['traded', 'claimed', 'acquired']],
    ['misc', 'Other', ['retired', 'free_agent', 'suspended', 'reinstated', 'staff', 'other']],
  ];
  const GROUP = Object.fromEntries(GROUPS.flatMap(g => g[2].map(t => [t, g[0]])));
  const STEP = 250;  // rows drawn at a time (a season runs to ~5,000)
  const day = d => d ? new Date(d + 'T12:00:00').toLocaleDateString([], { month: 'short', day: 'numeric' }) : '';
  const columns = teams => [
    { key: 'date', label: 'Date', first: 'desc', html: r => `<span class="mv-date">${esc(day(r.date))}</span>` },
    { key: 'team', label: 'Team', first: 'asc', html: r => {
        const t = NFLE.fmt.teamOf(teams, r.team);
        return `<span class="tm-open mv-tm" data-tm="${esc(r.team)}">${t.logo ? `<span class="st-logo" style="--tc:${esc(t.color || '#555')}"><img src="${esc(t.logo)}" alt="" width="18" height="18" loading="lazy"></span>` : ''}<span>${esc(r.team || '')}</span></span>`;
      } },
    { key: 'type', label: 'Move', first: 'asc', value: r => LABEL[r.type] || r.type,
      html: r => `<span class="mv-chip mv-${GROUP[r.type] || 'misc'}">${esc(LABEL[r.type] || r.type)}</span>` },
    // phones fold the note under the name (the Details column is hidden there; the table fits without side-scroll)
    { key: 'name', label: 'Player', first: 'asc', value: r => r.name || '~', cls: 'mv-who',
      html: r => `${r.name ? NFLE.ui.player({ name: r.name, pos: r.pos, team: r.team, pid: r.pid }, teams) : ''}<span class="mv-note">${esc(r.text)}</span>` },
    { key: 'text', label: 'Details', sort: false, cls: 'mv-text', html: r => esc(r.text) },
  ];
  NFLE.areas.moves = {
    mount(sec) {
      sec.classList.remove('soon');
      sec.innerHTML = `<div class="sec-head"><div><h2>Moves</h2><p class="mv-sub">Loading&hellip;</p></div></div>
        <div class="dt-card"><div class="dt-tools mv-tools closed">
          <select class="dt-select mv-season" aria-label="Season"></select>
          <input class="mv-q" type="search" placeholder="Find a player or note" aria-label="Find a player or note">
          <button type="button" class="mv-ftog" aria-expanded="false">Filters</button>
          <select class="dt-select mv-team" aria-label="Team"><option value="">All teams</option></select>
          <select class="dt-select mv-group" aria-label="Move type"><option value="">All moves</option>${GROUPS.map(g => `<option value="${g[0]}">${esc(g[1])}</option>`).join('')}</select>
          <select class="dt-select mv-pos" aria-label="Position"><option value="">All positions</option></select>
          <label class="mv-dl">From <input type="date" class="mv-from"></label><label class="mv-dl">To <input type="date" class="mv-to"></label>
        </div><div class="skel-zone mv-tbl"></div><div class="mv-more-wrap"><button type="button" class="mv-more" hidden></button></div></div>
        <p class="st-note muted">From ESPN's transactions log (updated daily; thin before 2003). Each note is split into one row per player; tap a linked name for his page. The full note is kept in Details.</p>`;
      const $ = s => sec.querySelector(s);
      const sub = $('.mv-sub'), selS = $('.mv-season'), selT = $('.mv-team'), selG = $('.mv-group'), selP = $('.mv-pos'),
            from = $('.mv-from'), to = $('.mv-to'), qi = $('.mv-q'), more = $('.mv-more');
      let rows = [], table = null, teams = {}, shown = STEP, season = null;
      const filtered = () => {
        const q = qi.value.trim().toLowerCase();
        return rows.filter(r => (!selT.value || r.team === selT.value) && (!selG.value || GROUP[r.type] === selG.value)
          && (!selP.value || r.pos === selP.value) && (!from.value || r.date >= from.value) && (!to.value || r.date <= to.value)
          && (!q || r.name.toLowerCase().includes(q) || r.text.toLowerCase().includes(q)));
      };
      const draw = (reset = true) => {
        if (reset) shown = STEP;
        const all = filtered(), cur = table && table.getSort();
        // the data is newest first: draw it in pages; any other sort needs the whole filtered season in the table
        const page = cur && !(cur.key === 'date' && cur.dir === 'desc') ? all : all.slice(0, shown);
        if (!table) table = NFLE.Table($('.mv-tbl'), { columns: columns(teams), rows: page, sort: { key: 'date', dir: 'desc' },
          cls: 'tiles', rowClass: () => 'teamrow', rowAttrs: r => `${NFLE.ui.tileStyle(teams, r.team)}${r.pid ? ` data-open-pid="${esc(r.pid)}"` : ''}`, onSort: () => draw(false) });
        else table.update(page);
        more.hidden = page.length >= all.length;
        more.textContent = `Show more (${(all.length - page.length).toLocaleString()} left)`;
        sub.textContent = `${season}: ${all.length.toLocaleString()} moves${all.length < rows.length ? ` of ${rows.length.toLocaleString()}` : ''}`;
      };
      const fill = (sel, vals) => {
        const cur = sel.value; sel.length = 1;
        vals.forEach(v => sel.insertAdjacentHTML('beforeend', `<option value="${esc(v[0])}">${esc(v[1])}</option>`));
        sel.value = vals.some(v => String(v[0]) === cur) ? cur : '';
      };
      const load = y => NFLE.load(`data/transactions/${y}.json`).then(d => {
        season = y;
        rows = d.rows.map(v => Object.fromEntries(d.cols.map((c, i) => [c, v[i]])));
        rows.forEach(r => { if (r.team) r.team = NFLE.fmt.era(r.team, season); });  // the club as it was (shell.js fmt.era)
        fill(selT, [...new Set(rows.map(r => r.team).filter(Boolean))].sort().map(a => [a, NFLE.fmt.teamOf(teams, a).nick || a]));
        fill(selP, [...new Set(rows.map(r => r.pos).filter(Boolean))].sort().map(p => [p, p]));
        from.value = to.value = '';
        nset();
        draw();
      }).catch(() => { sub.textContent = 'No moves logged for that season.'; });
      [selT, selG, selP, from, to].forEach(s => { s.onchange = () => draw(); });
      qi.oninput = () => draw();
      // phones: the less-used filters sit behind a toggle (the count on it says how many are set)
      const tools = $('.mv-tools'), ftog = $('.mv-ftog');
      ftog.onclick = () => { const open = tools.classList.toggle('closed') === false; ftog.setAttribute('aria-expanded', open); };
      const nset = () => { const n = [selT, selG, selP, from, to].filter(x => x.value).length; ftog.textContent = n ? `Filters (${n})` : 'Filters'; };
      [selT, selG, selP, from, to].forEach(x => x.addEventListener('change', nset));
      more.onclick = () => { shown += STEP * 4; draw(false); };
      Promise.all([NFLE.load('data/transactions/index.json'), NFLE.week(), NFLE.ui.ready]).then(([ix, wk]) => {
        teams = Object.assign({}, ix.teams || {}, (wk && wk.teams) || {});  // the week map has both trim colors
        const ps = pageSeason(), want = ps && ix.seasons.includes(ps) ? ps : ix.seasons[ix.seasons.length - 1];
        selS.innerHTML = [...ix.seasons].reverse().map(y => `<option value="${y}"${y === want ? ' selected' : ''}>${y}</option>`).join('');
        selS.onchange = () => load(+selS.value);
        load(want);
      }).catch(() => { sub.textContent = 'Moves are not available on this page.'; });
    },
  };
})();
