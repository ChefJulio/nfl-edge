// Players > Injuries: ESPN's current injury list (data/espn_injuries/latest.json, written daily by
// tools/espn_snapshot.py) next to our own chance he's inactive this week (the page's week data). Rows we project
// open the player page. Fantasy-relevant players (on our board) by default; "All" shows ESPN's whole list.
(() => {
  let TEAMS = {};  // the week data's teams map (tile colors, logos)
  const NFLE = window.NFLE, esc = NFLE.esc;
  const ORDER = { 'Out': 1, 'Injured Reserve': 2, 'Doubtful': 3, 'Questionable': 4, 'Day-To-Day': 5, 'Suspension': 6 };
  // tabs by status (owner 2026-10-18: "tabs for questionable and out, sorted by grades or projections")
  const TABS = [['q', 'Questionable', ['Questionable', 'Doubtful', 'Day-To-Day']], ['out', 'Out', ['Out']],
                ['ir', 'IR', ['Injured Reserve', 'Physically Unable to Perform', 'Suspension', 'Reserve/Suspended']]];
  const tabOf = st => (TABS.find(t => t[2].includes(st)) || ['other'])[0];
  const tone = s => /Out|Reserve|Suspension/.test(s) ? 'bad' : /Doubtful/.test(s) ? 'warn' : /Questionable|Day/.test(s) ? 'q' : '';
  const ago = iso => { const h = (Date.now() - new Date(iso)) / 3.6e6; return h < 1 ? 'just now' : h < 24 ? `${Math.round(h)}h ago` : `${Math.round(h / 24)}d ago`; };
  NFLE.areas.injuries = {
    mount(sec) {
      sec.classList.remove('soon');
      sec.innerHTML = `<div class="sec-head"><div><h2>Injuries</h2><p class="in-sub">Loading&hellip;</p></div></div>
        <div class="in-top"><input class="dt-search in-q" type="search" placeholder="Find a player" aria-label="Find a player" autocomplete="off">
          <div class="seg in-view"><button type="button" data-w="dash" class="on">This week</button><button type="button" data-w="full">Full list</button></div></div>
        <div class="in-dash"></div>
        <div class="dt-card in-full" hidden><div class="dt-tools">
          <select class="dt-select in-team" aria-label="Team"><option value="">All teams</option></select>
          <div class="seg in-scope"><button type="button" data-v="fan">Fantasy</button><button type="button" data-v="all">All</button></div>
        </div><div class="seg in-tabs" role="tablist"></div><div class="skel-zone in-tbl"></div><p class="in-more muted" hidden></p></div>
        <p class="st-note muted">Status, injury, estimated return and notes from ESPN's injury feed (updated daily). Play % is ours: the chance he plays this week, from the injury report, practice participation and his history (see the Model tab). Sorted by his projection if he plays; tap Grd to sort by the Edge grade.</p>`;
      const sub = sec.querySelector('.in-sub'), selT = sec.querySelector('.in-team');
      let scope = 'fan', tab = 'q', all = [], table = null, showSure = false, WK = null, view = 'dash';
      const q = sec.querySelector('.in-q');
      // listed but all but certain to play (our 99%+: full practice, cleared): hidden unless asked for (owner 2026-10-18)
      const sure = r => r.inactive != null && r.inactive < 0.015;  // shown as 99% or >99%
      const cols = [
        { key: 'name', label: 'Player', stick: true, first: 'asc', value: r => r.name,
          html: r => NFLE.ui.player({ name: r.name, pos: r.pos, team: r.abbr, espn: r.espn_id, subHtml: r.abbr ? NFLE.ui.tm(r.abbr) : NFLE.esc(r.team || '') }, TEAMS) },
        // Play% first after the name (owner 2026-10-18: "people going there want to see the % they play")
        { key: 'inactive', label: 'Play%', num: true, title: 'Our chance he plays this week', value: r => r.inactive == null ? null : 1 - r.inactive,
          html: r => r.inactive == null ? '<span class="muted">&ndash;</span>' : `<span class="in-pct" style="--p:${Math.round(100 * r.inactive)}">${NFLE.fmt.toPlay(r.inactive)}</span>` },
        { key: 'proj', label: 'Proj', num: true, first: 'desc', cls: 'projc', title: 'Our projected points if he plays this week (blank: not on our board, or no game)',
          value: r => r.proj, html: r => r.proj == null ? '<span class="muted">&ndash;</span>' : `<b>${r.proj.toFixed(1)}</b>` },
        { key: 'grd', label: 'Grd', num: true, first: 'desc', title: 'Edge grade (OVR): three seasons of fantasy output, a percentile within his position',
          value: r => { const g = r.pid && NFLE.gradeOf && NFLE.gradeOf(r.pid); return g ? g.v : null; },
          html: r => { const g = r.pid && NFLE.gradeOf && NFLE.gradeOf(r.pid); return g ? NFLE.gradeChip(g) : '<span class="muted">&ndash;</span>'; } },
        { key: 'status', label: 'Status', first: 'asc', value: r => ORDER[r.status] || 9, html: r => `<span class="in-st in-${tone(r.status)}">${esc(r.status)}</span>` },
        { key: 'injury', label: 'Injury', first: 'asc', value: r => r.type, html: r => esc([r.type, r.detail && r.detail !== r.type ? r.detail : '', r.side && r.side !== 'Not Specified' ? r.side : ''].filter(Boolean).join(' · ')) },
        { key: 'return_date', label: 'Est. return', first: 'asc', value: r => r.return_date, html: r => esc(r.return_date ? new Date(r.return_date + 'T12:00:00').toLocaleDateString([], { month: 'short', day: 'numeric' }) : '') },
        { key: 'updated', label: 'Updated', first: 'desc', value: r => r.updated, html: r => r.updated ? `<span title="${esc(new Date(r.updated).toLocaleString([], { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' }))}">${esc(ago(r.updated))}</span>` : '' },
        { key: 'comment', label: 'Latest', sort: false, cls: 'in-note', html: r => `<span title="${esc(r.comment || '')}">${esc(r.comment || '')}</span>` },
      ];
      const base = () => { const t = q.value.trim().toLowerCase();
        return all.filter(r => (scope === 'all' || r.pid) && (!selT.value || r.abbr === selT.value) && (!t || r.name.toLowerCase().includes(t))); };
      // This week (owner 2026-10-18: "a quick look at the guys actually dealing with injury ... the most practical
      // version"): players on our board this week with any chance of sitting, in three buckets by our chance he plays,
      // biggest projection first; the search box finds anyone. Our numbers, so it's as fresh as the last build.
      const BUCKETS = [['gt', 'Game-time calls', 'a real chance either way', p => p >= 0.15 && p < 0.85],
                       ['out', 'Expected out', 'plan around him', p => p < 0.15],
                       ['likely', 'Probably playing', 'listed, but expect him', p => p >= 0.85]];
      const kick = t => { const g = ((WK && WK.games) || []).find(x => x.away.team === t || x.home.team === t);
        // short: "Sun 1:00p" (the date is this week's anyway)
        const short = g && g.gameday ? (() => { const [h, m] = String(g.gametime || '13:00').split(':').map(Number);
          return `${new Date(g.gameday + 'T12:00:00').toLocaleDateString([], { weekday: 'short' })} ${((h + 11) % 12) + 1}:${String(m).padStart(2, '0')}${h < 12 ? 'a' : 'p'}`; })() : '';
        return g ? { txt: short, opp: g.home.team === t ? g.away.team : g.home.team, home: g.home.team === t, fin: !!g.final } : null; };
      const dashCols = [
        { key: 'name', label: 'Player', stick: true, sort: false, html: r => NFLE.ui.player({ name: r.name, pos: r.pos, team: r.team, photo: r.photo, espn: r.espn,
            subHtml: r.k ? `${r.k.home ? 'vs' : '@'} ${NFLE.ui.tm(r.k.opp)}` : NFLE.ui.tm(r.team), badges: NFLE.injTag ? NFLE.injTag(r.status) : '' }, TEAMS) },
        { key: 'play', label: 'Play%', num: true, sort: false, title: 'Our chance he plays this week',
          html: r => `<span class="in-pct" style="--p:${Math.round(100 * r.inactive)}">${NFLE.fmt.toPlay(r.inactive)}</span>` },
        { key: 'proj', label: 'Proj', num: true, sort: false, cls: 'projc', title: 'Projected points if he plays', html: r => `<b>${r.proj.toFixed(1)}</b>` },
        { key: 'when', label: 'Game', sort: false, cls: 'in-when', html: r => r.k ? `<span class="muted">${esc(r.k.fin ? 'final' : r.k.txt)}</span>` : '<span class="muted">bye</span>' },
      ];
      // on the injury report (a status before the practice letters) or a real chance of sitting; everyone carries a
      // ~1.5% baseline scratch risk, so that alone isn't an injury
      const listed = p => !!String(p.status || '').split('(')[0].trim() || (p.inactive || 0) >= 0.05;
      const drawDash = () => {
        const box = sec.querySelector('.in-dash');
        if (!WK) return;
        const t = q.value.trim().toLowerCase();
        const ps = Object.entries(WK.players || {}).map(([pid, p]) => ({ pid, name: p.name, pos: p.pos, team: p.team, photo: p.photo, espn: p.espn,
            status: p.status, inactive: p.inactive || 0, proj: +(p.proj || 0), k: kick(p.team) }))
          .filter(r => listed(r) && (!t || r.name.toLowerCase().includes(t) || r.team.toLowerCase() === t));
        box.innerHTML = '';
        BUCKETS.forEach(([k, label, note, inB]) => {
          const rs = ps.filter(r => inB(1 - r.inactive)).sort((a, b) => b.proj - a.proj);
          if (!rs.length) return;
          const open = k !== 'likely' || !!t;
          box.insertAdjacentHTML('beforeend', `<details class="in-b in-b-${k}"${open ? ' open' : ''}><summary><b>${label}</b> <span class="in-n">${rs.length}</span> <span class="muted">${note}</span></summary><div class="in-bt"></div></details>`);
          NFLE.Table(box.lastElementChild.querySelector('.in-bt'), { columns: dashCols, rows: rs, cls: 'tiles in-dt',
            rowClass: () => 'teamrow', rowAttrs: r => `${NFLE.ui.tileStyle(TEAMS, r.team)} data-open-pid="${esc(r.pid)}"` });
        });
        // a search for someone who isn't hurt says so (owner: find specific guys quickly)
        const healthy = t ? Object.values(WK.players || {}).filter(p => !listed(p) && p.name.toLowerCase().includes(t)).slice(0, 5) : [];
        if (healthy.length) box.insertAdjacentHTML('beforeend', `<p class="muted in-none">${healthy.map(p => `<b>${esc(p.name)}</b>`).join(', ')}: not on the injury list, expected to play.</p>`);
        if (!box.children.length) box.innerHTML = `<p class="muted in-none">${t ? 'No player on our board matches.' : 'Nobody on our board is in doubt this week.'}</p>`;
      };
      const setView = v => { view = v; sec.querySelectorAll('.in-view button').forEach(b => b.classList.toggle('on', b.dataset.w === v));
        sec.querySelector('.in-dash').hidden = v !== 'dash'; sec.querySelector('.in-full').hidden = v !== 'full'; if (v === 'dash') drawDash(); else draw(); };
      sec.querySelector('.in-view').addEventListener('click', e => { const b = e.target.closest('[data-w]'); if (b) setView(b.dataset.w); });
      q.addEventListener('input', () => { if (view === 'dash') drawDash(); else draw(); });
      const inTab = () => base().filter(r => tabOf(r.status) === tab);
      const rows = () => inTab().filter(r => showSure || !sure(r));
      const draw = () => {
        sec.querySelectorAll('.in-scope button').forEach(b => b.classList.toggle('on', b.dataset.v === scope));
        const b0 = base();
        sec.querySelector('.in-tabs').innerHTML = TABS.map(([k, l]) => `<button type="button" role="tab" data-t="${k}" class="${tab === k ? 'on' : ''}">${l} <span class="in-n">${b0.filter(r => tabOf(r.status) === k && (showSure || !sure(r))).length}</span></button>`).join('');
        if (!table) table = NFLE.Table(sec.querySelector('.in-tbl'), { howto: true, columns: cols, rows: rows(), sort: { key: 'proj', dir: 'desc' },
          cls: 'tiles', rowClass: () => 'teamrow', rowAttrs: r => `${NFLE.ui.tileStyle(TEAMS, r.abbr)}${r.pid ? ` data-open-pid="${esc(r.pid)}"` : ''}` });
        else table.update(rows());
        const n = inTab().filter(sure).length, more = sec.querySelector('.in-more');
        more.hidden = !n;
        more.innerHTML = showSure ? `Showing ${n} listed but expected to play (99%+). <button type="button" class="linkish">Hide them</button>`
          : `${n} more listed but expected to play (99%+). <button type="button" class="linkish">Show them</button>`;
      };
      // the page's week data (our availability) loads on its own (NFLE.week waits for it)
      Promise.all([NFLE.load('data/espn_injuries/latest.json'), NFLE.week()]).then(([d, wk]) => {
        TEAMS = (wk && wk.teams) || {}; WK = wk;
        const byEspn = {}, nameToAbbr = {};
        if (wk) {
          Object.entries(wk.players || {}).forEach(([pid, p]) => { if (p.espn) byEspn[String(p.espn)] = [pid, p]; });
          Object.entries(wk.teams || {}).forEach(([a, t]) => { nameToAbbr[t.name] = a; });
        }
        all = d.rows.map(r => {
          const hit = byEspn[String(r.espn_id)];
          return Object.assign({}, r, { abbr: nameToAbbr[r.team] || '', pid: hit ? hit[0] : null, pos: hit ? hit[1].pos : '', inactive: hit ? hit[1].inactive : null,
            proj: hit && hit[1].proj != null ? +hit[1].proj : null });
        });
        sub.textContent = `Who might sit this week, by our chance he plays · full ESPN list: ${all.length} players, fetched ${ago(d.fetched)}`;
        [...new Set(all.map(r => r.abbr).filter(Boolean))].sort().forEach(a => selT.insertAdjacentHTML('beforeend', `<option>${esc(a)}</option>`));
        drawDash();
      }).catch(() => { sub.textContent = 'The injury list is not available right now.'; });
      selT.onchange = draw;
      sec.querySelector('.in-more').addEventListener('click', e => { if (e.target.closest('button')) { showSure = !showSure; draw(); } });
      sec.querySelector('.in-tabs').addEventListener('click', e => { const b = e.target.closest('[data-t]'); if (b) { tab = b.dataset.t; draw(); } });
      document.addEventListener('nfle-grades', () => { if (table) table.update(rows()); });  // grades arrive after the list
      sec.querySelector('.in-scope').addEventListener('click', e => { const b = e.target.closest('[data-v]'); if (b) { scope = b.dataset.v; draw(); } });
    },
  };
})();
