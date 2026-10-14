// Players > Roles: snap and opportunity spikes from the week JSON (DATA.roles; report.role_changes): each player's
// latest game against his previous three. Alerts, not model inputs. Rows open the player page.
(() => {
  const NFLE = window.NFLE, esc = NFLE.esc, F = NFLE.fmt;
  const arrow = (a, b) => `<span class="arrow"><span class="from">${F.pct(a)}</span><i>&rarr;</i><b>${F.pct(b)}</b></span>`;
  NFLE.areas.roles = {
    mount(sec) {
      NFLE.week().then(D => {
        if (!D || !D.roles) return;  // older week file: keep the page's table
        const teams = D.teams || {}, last = D.week - 1;
        sec.innerHTML = `<div class="sec-head"><div><h2>Role changes</h2><p>Snap and opportunity spikes in week ${last} compared with each player's previous three games.</p></div></div>
          <details class="howto"><summary>How to read</summary><div>
            Compares each player's latest game with his previous three. Opportunity share = (carries + targets) / team plays. These are alerts, not model inputs: check the reason (injury ahead of him, demotion, game script) before chasing.
          </div></details>
          ${D.roles.length ? '<div class="ro-tbl"></div>' : '<p class="muted">No role changes yet this season.</p>'}`;
        if (!D.roles.length) return;
        NFLE.Table(sec.querySelector('.ro-tbl'), {
          columns: [
            { key: 'name', label: 'Player', stick: true, first: 'asc',
              html: r => `<div class="who">${F.logo(teams, r.team, 18)}<div><b><span class="nm-full">${esc(r.name)}</span><span class="nm-short">${esc(F.short(r.name))}</span></b><span class="sub">${F.posb(r.pos)} <span class="tm-open" data-tm="${esc(r.team)}">${esc(r.team)}</span>${r.week !== last ? ` &middot; wk ${r.week}` : ''}</span></div></div>` },
            { key: 'snap', label: 'Snap share', title: 'Sorts by the size of the jump', value: r => (r.snap_now || 0) - (r.snap_prev || 0), html: r => arrow(r.snap_prev, r.snap_now) },
            { key: 'opp', label: 'Opportunity share', title: 'Sorts by the size of the jump', value: r => (r.opp_now || 0) - (r.opp_prev || 0), html: r => arrow(r.opp_prev, r.opp_now) },
            { key: 'touches', label: 'Touches', num: true },
            { key: 'takeaway', label: 'Takeaway', sort: false, cls: 'take' },
          ],
          rows: D.roles, sort: null, cls: 'tiles',
          rowClass: () => 'teamrow pl-row', rowAttrs: r => `style="${F.rowStyle(teams, r.team)}" data-open-pid="${esc(r.pid)}"`,
        });
      });
    },
  };
})();
