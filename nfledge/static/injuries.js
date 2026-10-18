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
        <div class="dt-card"><div class="dt-tools">
          <select class="dt-select in-team" aria-label="Team"><option value="">All teams</option></select>
          <div class="seg in-scope"><button type="button" data-v="fan">Fantasy</button><button type="button" data-v="all">All</button></div>
        </div><div class="seg in-tabs" role="tablist"></div><div class="skel-zone in-tbl"></div></div>
        <p class="st-note muted">Status, injury, estimated return and notes from ESPN's injury feed (updated daily). Play % is ours: the chance he plays this week, from the injury report, practice participation and his history (see the Model tab). Sorted by his projection if he plays; tap Grd to sort by the Edge grade.</p>`;
      const sub = sec.querySelector('.in-sub'), selT = sec.querySelector('.in-team');
      let scope = 'fan', tab = 'q', all = [], table = null;
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
      const base = () => all.filter(r => (scope === 'all' || r.pid) && (!selT.value || r.abbr === selT.value));
      const rows = () => base().filter(r => tabOf(r.status) === tab);
      const draw = () => {
        sec.querySelectorAll('.in-scope button').forEach(b => b.classList.toggle('on', b.dataset.v === scope));
        const b0 = base();
        sec.querySelector('.in-tabs').innerHTML = TABS.map(([k, l]) => `<button type="button" role="tab" data-t="${k}" class="${tab === k ? 'on' : ''}">${l} <span class="in-n">${b0.filter(r => tabOf(r.status) === k).length}</span></button>`).join('');
        if (!table) table = NFLE.Table(sec.querySelector('.in-tbl'), { howto: true, columns: cols, rows: rows(), sort: { key: 'proj', dir: 'desc' },
          cls: 'tiles', rowClass: () => 'teamrow', rowAttrs: r => `${NFLE.ui.tileStyle(TEAMS, r.abbr)}${r.pid ? ` data-open-pid="${esc(r.pid)}"` : ''}` });
        else table.update(rows());
      };
      // the page's week data (our availability) loads on its own (NFLE.week waits for it)
      Promise.all([NFLE.load('data/espn_injuries/latest.json'), NFLE.week()]).then(([d, wk]) => {
        TEAMS = (wk && wk.teams) || {};
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
        sub.textContent = `${all.length} players listed by ESPN, ${all.filter(r => r.pid).length} on our board · fetched ${ago(d.fetched)}`;
        [...new Set(all.map(r => r.abbr).filter(Boolean))].sort().forEach(a => selT.insertAdjacentHTML('beforeend', `<option>${esc(a)}</option>`));
        draw();
      }).catch(() => { sub.textContent = 'The injury list is not available right now.'; });
      selT.onchange = draw;
      sec.querySelector('.in-tabs').addEventListener('click', e => { const b = e.target.closest('[data-t]'); if (b) { tab = b.dataset.t; draw(); } });
      document.addEventListener('nfle-grades', () => { if (table) table.update(rows()); });  // grades arrive after the list
      sec.querySelector('.in-scope').addEventListener('click', e => { const b = e.target.closest('[data-v]'); if (b) { scope = b.dataset.v; draw(); } });
    },
  };
})();
