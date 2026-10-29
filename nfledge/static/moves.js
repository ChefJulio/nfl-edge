// Players > Moves: every roster move ESPN logs (data/transactions/<season>.json, tools/transactions_build.py, 2002 on),
// one row per player per move (a trade: one row for the whole trade, what each side got), newest first; this season opens on Notable. Season / team / move type / position / date range filters and a search;
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
  // One row per trade (owner 2026-10-29: Buckner's trade was four rows, "SF gets: / IND gets: style?"): each team logs
  // its side, sometimes twice, so trade rows that name the same player within a week, or share a note, are one trade,
  // and what each side received is read from the notes ("Acquired X from Y for Z": this team gets X, Y gets Z;
  // "Traded X to Y for Z": Y gets X, this team gets Z).
  const ORD = { first: '1st', second: '2nd', third: '3rd', fourth: '4th', fifth: '5th', sixth: '6th', seventh: '7th' };
  // a club as ESPN's notes name it ("Houston", "the N.Y. Jets", "San Francisco 49ers") -> its code
  const CITY = [['ARI', /Arizona|Cardinals/], ['ATL', /Atlanta|Falcons/], ['BAL', /Baltimore|Ravens/], ['BUF', /Buffalo|Bills/],
    ['CAR', /Carolina|Panthers/], ['CHI', /Chicago|Bears/], ['CIN', /Cincinnati|Bengals/], ['CLE', /Cleveland|Browns/],
    ['DAL', /Dallas|Cowboys/], ['DEN', /Denver|Broncos/], ['DET', /Detroit|Lions/], ['GB', /Green Bay|Packers/],
    ['HOU', /Houston|Texans/], ['IND', /Indianapolis|Colts/], ['JAX', /Jacksonville|Jaguars/], ['KC', /Kansas City|Chiefs/],
    ['LV', /Las Vegas|Raiders/], ['LAC', /Chargers/], ['LA', /Rams|Los Angeles/], ['MIA', /Miami|Dolphins/],
    ['MIN', /Minnesota|Vikings/], ['NE', /New England|Patriots/], ['NO', /New Orleans|Saints/], ['NYG', /Giants/],
    ['NYJ', /Jets/], ['PHI', /Philadelphia|Eagles/], ['PIT', /Pittsburgh|Steelers/], ['SF', /San Francisco|49ers/],
    ['SEA', /Seattle|Seahawks/], ['TB', /Tampa Bay|Buccaneers/], ['TEN', /Tennessee|Titans/], ['WAS', /Washington|Commanders/]];
  const clubOf = name => (CITY.find(([, rx]) => rx.test(name || '')) || [])[0] || null;
  const tidy = x => x.trim().replace(/^(?:a|an|the)\s+/i, '').replace(/\b(first|second|third|fourth|fifth|sixth|seventh)(?=-| round)/gi, m => ORD[m.toLowerCase()]).replace(/(\d(?:st|nd|rd|th)) round/g, '$1-round')
    .replace(/\s*draft (?:pick|choice)s?\b/i, ' pick').replace(/\s+pick(s?)\b/i, ' pick$1').replace(/\.$/, '').trim();
  const items = s => (s || '').replace(/\s+(?:and|plus)\s+(?=(?:a|an|the|\d{4}|[A-Z]{1,4}\s)\b)/g, ', ').split(/,\s*/).map(tidy).filter(Boolean);
  // a note -> [what the logging team got, what the other side got, the other side's name as written]
  const sides = text => {
    const t = text.replace(/\s+/g, ' ').trim();
    let m = t.match(/^(?:Acquired|Received)\s+(.+?)\s+from\s+(?:the\s+)?(.+?)\s+(?:in exchange for|for)\s+(.+)$/i);
    if (m) return [items(m[1]), items(m[3]), m[2]];
    m = t.match(/^(?:Traded|Trade)\s+(.+?)\s+to\s+(?:the\s+)?(.+?)\s+(?:in exchange for|for)\s+(.+)$/i);
    if (m) return [items(m[3]), items(m[1]), m[2]];
    m = t.match(/^(?:Traded|Trade)\s+(.+?)\s+to\s+(?:the\s+)?(.+?)$/i);
    if (m) return [[], items(m[1]), m[2]];
    return null;
  };
  const isTrade = r => r.type === 'traded' || r.type === 'acquired';
  const groupTrades = rows => {
    const tr = rows.filter(isTrade), parent = tr.map((_, i) => i);
    const find = i => { while (parent[i] !== i) i = parent[i] = parent[parent[i]]; return i; };
    const join = (a, b) => { parent[find(b)] = find(a); };
    const byText = {};
    tr.forEach((r, i) => { const k = r.text; if (k in byText) join(byText[k], i); else byText[k] = i; });
    // the same player within a week: by id, else by name (Joey Porter Jr.: an Oct 1 note without an id, finalized Oct 7)
    const nm = r => (r.name || '').toLowerCase().replace(/[^a-z]/g, '');
    tr.forEach((a, i) => tr.forEach((b, j) => { if (j > i && ((a.pid && a.pid === b.pid) || (nm(a) && nm(a) === nm(b))) && Math.abs(new Date(a.date) - new Date(b.date)) <= 7 * 864e5) join(i, j); }));
    const groups = {};
    tr.forEach((r, i) => (groups[find(i)] = groups[find(i)] || []).push(r));
    const out = Object.values(groups).map(g => {
      const teams = [...new Set(g.map(r => r.team).filter(Boolean))];
      const players = [], seen = new Set();
      g.forEach(r => { const k = r.pid || r.name; if (r.name && !seen.has(k)) { seen.add(k); players.push(r); } });
      // what each side got: the logging team's view of each note (the longest note per team), the other side by name
      const gets = {};
      teams.forEach(t => {
        const note = g.filter(r => r.team === t).map(r => r.text).sort((a, b) => b.length - a.length)[0];
        const s = note && sides(note);
        if (!s) return;
        if (s[0].length) gets[t] = gets[t] || s[0];
        const other = teams.find(x => x !== t) || clubOf(s[2]);
        const key = other || s[2];
        if (key && key !== t && !teams.includes(key)) teams.push(key);  // the side that didn't log it
        if (s[1].length && !(key in gets)) gets[key] = s[1];
      });
      const first = g.map(r => r.date).sort()[0], lead = players[0] || g[0];
      // the side that got the headline player first ("SF gets Buckner", then what IND got)
      const has = xs => xs.some(x => lead.name && x.includes(lead.name));
      const order = Object.entries(gets).sort((a, b) => has(b[1]) - has(a[1]));
      if (order.length) teams.sort((a, b) => order.findIndex(o => o[0] === a) - order.findIndex(o => o[0] === b));
      return { grp: true, date: first, team: teams[0], teams, type: 'traded', pid: lead.pid, name: lead.name, pos: lead.pos, players,
               gets: order, text: [...new Set(g.map(r => r.text))].join(' / ') };
    });
    return [...rows.filter(r => !isTrade(r)), ...out].sort((a, b) => (a.date < b.date ? 1 : a.date > b.date ? -1 : 0));
  };
  const tmLogo = (teams, abbr) => { const t = NFLE.fmt.teamOf(teams, abbr);
    return t.logo ? `<span class="st-logo" style="--tc:${esc(t.color || '#555')}"><img src="${esc(t.logo)}" alt="" width="18" height="18" loading="lazy"></span>` : ''; };
  const getsHtml = r => r.gets.length ? `<span class="mv-gets">${r.gets.map(([t, xs]) => `<span><b>${esc(t)} gets</b> ${esc(xs.join(', '))}</span>`).join('')}</span>`
    : `<span class="mv-note">${esc(r.text)}</span>`;
  const day = d => d ? new Date(d + 'T12:00:00').toLocaleDateString([], { month: 'short', day: 'numeric' }) : '';
  const columns = teams => [
    { key: 'date', label: 'Date', first: 'desc', html: r => `<span class="mv-date">${esc(day(r.date))}</span>` },
    { key: 'team', label: 'Team', first: 'asc', html: r => r.grp && r.teams.length > 1
        ? `<span class="mv-tm mv-tm2">${r.teams.map(t => `<span class="tm-open" data-tm="${esc(t)}">${tmLogo(teams, t)}</span>`).join('<span class="mv-swap" aria-hidden="true">&#8644;</span>')}</span>`
        : `<span class="tm-open mv-tm" data-tm="${esc(r.team)}">${tmLogo(teams, r.team)}<span>${esc(r.team || '')}</span></span>` },
    { key: 'type', label: 'Move', first: 'asc', value: r => r.grp ? 'Trade' : LABEL[r.type] || r.type,
      html: r => `<span class="mv-chip mv-${GROUP[r.type] || 'misc'}">${esc(r.grp ? 'Trade' : LABEL[r.type] || r.type)}</span>` },
    // phones fold the note under the name (the Details column is hidden there; the table fits without side-scroll); a
    // trade shows its players and what each side got
    { key: 'name', label: 'Player', first: 'asc', value: r => r.name || '~', cls: 'mv-who',
      html: r => r.grp ? `${r.players.map(p => NFLE.ui.player({ name: p.name, pos: p.pos, team: p.team, pid: p.pid }, teams)).join('')}${getsHtml(r)}`
        : `${r.name ? NFLE.ui.player({ name: r.name, pos: r.pos, team: r.team, pid: r.pid }, teams) : ''}<span class="mv-note">${esc(r.text)}</span>` },
    { key: 'text', label: 'Details', sort: false, cls: 'mv-text', html: r => r.grp ? r.text.split(' / ').map(esc).join('<br>') : esc(r.text) },
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
          <select class="dt-select mv-group" aria-label="Move type"><option value="">All moves</option><option value="notable">Notable</option>${GROUPS.map(g => `<option value="${g[0]}">${esc(g[1])}</option>`).join('')}</select>
          <select class="dt-select mv-pos" aria-label="Position"><option value="">All positions</option></select>
          <label class="mv-dl">From <input type="date" class="mv-from"></label><label class="mv-dl">To <input type="date" class="mv-to"></label>
        </div><div class="skel-zone mv-tbl"></div><div class="mv-more-wrap"><button type="button" class="mv-more" hidden></button></div></div>
        <p class="st-note muted">From ESPN's transactions log (updated daily; thin before 2003). Each note is split into one row per player; tap a linked name for his page. The full note is kept in Details.</p>`;
      const $ = s => sec.querySelector(s);
      const sub = $('.mv-sub'), selS = $('.mv-season'), selT = $('.mv-team'), selG = $('.mv-group'), selP = $('.mv-pos'),
            from = $('.mv-from'), to = $('.mv-to'), qi = $('.mv-q'), more = $('.mv-more');
      let rows = [], table = null, teams = {}, shown = STEP, season = null;
      // Notable (owner 2026-10-29; data/notable.json, tools/notable_build.py): this league year's moves of players our
      // numbers rate highly. A row is notable when the feed lists his move of that kind within 3 days of it.
      const NG = { trade: 'trade', release: 'cut', signing: 'add', extension: 'add', susp: 'misc', season: 'inj' };
      let notable = null;
      const isNotable1 = r => !!(notable && r.pid && (notable[r.pid] || []).some(m => m.g === GROUP[r.type] && Math.abs(new Date(r.date) - new Date(m.d)) <= 3 * 864e5));
      const isNotable = r => r.grp ? r.players.some(x => isNotable1(Object.assign({}, x, { type: 'traded', date: r.date }))) : isNotable1(r);
      NFLE.notable().then(doc => {
        notable = {};
        ((doc && doc.items) || []).forEach(it => it.players.forEach(p => (notable[p.pid] = notable[p.pid] || []).push({ d: it.date, g: NG[it.kind] })));
        if (selG.value === 'notable') draw();
        else if (rows.length && !userG && notableDefault()) { selG.value = 'notable'; nset(); draw(); }
      });
      // Notable is where this season opens (owner 2026-10-29: "make notable the default on moves"); other seasons have
      // no notable list and open on all moves; a filter picked by hand stays
      let userG = false, notableLY = null;
      NFLE.notable().then(d => { notableLY = d && (d.items || []).length ? d.league_year : null; });
      const notableDefault = () => notableLY != null && +season === +notableLY;
      // a search (owner 2026-10-21: it shouldn't stack on the filters) looks through the whole season: team, type,
      // position and dates are set aside (dimmed) while there's text; the season stays its scope
      const filtered = () => {
        const q = qi.value.trim().toLowerCase();
        [selT, selG, selP, from, to].forEach(x => { x.disabled = !!q; });
        if (q) return rows.filter(r => (r.grp ? r.players.some(x => (x.name || '').toLowerCase().includes(q)) : (r.name || '').toLowerCase().includes(q)) || (r.text || '').toLowerCase().includes(q));
        return rows.filter(r => (!selT.value || (r.grp ? r.teams.includes(selT.value) : r.team === selT.value)) && (!selG.value || (selG.value === 'notable' ? isNotable(r) : GROUP[r.type] === selG.value))
          && (!selP.value || (r.grp ? r.players.some(x => x.pos === selP.value) : r.pos === selP.value)) && (!from.value || r.date >= from.value) && (!to.value || r.date <= to.value));
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
        sub.textContent = `${season}: ${all.length.toLocaleString()} ${selG.value === 'notable' ? 'notable ' : ''}moves${all.length < rows.length ? ` of ${rows.length.toLocaleString()}` : ''}`;
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
        rows = groupTrades(rows);
        if (!userG) selG.value = notableDefault() ? 'notable' : '';
        fill(selT, NFLE.fmt.teamOpts(teams, rows.flatMap(r => r.grp ? r.teams : [r.team])));
        fill(selP, [...new Set(rows.map(r => r.pos).filter(Boolean))].sort().map(p => [p, p]));
        from.value = to.value = '';
        nset();
        draw();
        wantNotable();
      }).catch(() => { sub.textContent = 'No moves logged for that season.'; });
      [selT, selG, selP, from, to].forEach(s => { s.onchange = () => draw(); });
      selG.addEventListener('change', () => { userG = true; });
      qi.oninput = () => draw();
      // phones: the less-used filters sit behind a toggle (the count on it says how many are set)
      const tools = $('.mv-tools'), ftog = $('.mv-ftog');
      ftog.onclick = () => { const open = tools.classList.toggle('closed') === false; ftog.setAttribute('aria-expanded', open); };
      const nset = () => { const n = [selT, selG, selP, from, to].filter(x => x.value).length; ftog.textContent = n ? `Filters (${n})` : 'Filters'; };
      [selT, selG, selP, from, to].forEach(x => x.addEventListener('change', nset));
      more.onclick = () => { shown += STEP * 4; draw(false); };
      // Home's Notable moves tile opens this tab on its filter (this season)
      const wantNotable = () => {
        if (!NFLE.movesNotable || !rows.length) return;
        NFLE.movesNotable = false;
        qi.value = ''; selT.value = selP.value = from.value = to.value = ''; selG.value = 'notable';
        nset(); draw();
      };
      addEventListener('hashchange', () => setTimeout(wantNotable, 0));
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
