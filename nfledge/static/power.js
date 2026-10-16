// Teams > Power: the power rankings table from the week JSON (DATA.power; report.team_tables). Opponent-adjusted
// points per game vs an average team, unit by unit, with league-rank badges, the rank range from the bootstrap, the
// schedule played / left and this season's trend. Rows open the team page.
(() => {
  const NFLE = window.NFLE, esc = NFLE.esc, F = NFLE.fmt;
  // the season's weekly net ratings as a small line (the dot = this week)
  const spark = (v, w = 84, h = 22) => {
    v = (v || []).filter(x => x != null);
    if (v.length < 2) return '';
    const lo = Math.min(...v), span = (Math.max(...v) - lo) || 1, y = x => (h - 2 - (x - lo) / span * (h - 4)).toFixed(1);
    const pts = v.map((x, i) => `${(i * w / (v.length - 1)).toFixed(1)},${y(x)}`).join(' ');
    return `<svg class="spark" viewBox="0 0 ${w} ${h}" width="${w}" height="${h}" aria-hidden="true"><polyline points="${pts}" fill="none" stroke="currentColor" stroke-width="1.5"/><circle cx="${w}" cy="${y(v[v.length - 1])}" r="2.2" fill="currentColor"/></svg>`;
  };
  const mc = (v, rk, cls = 'mv2', sm = '') => `<div class="mc"><span class="${cls}">${F.sgn(v)}</span><span class="rk-b${sm} ${F.rkc(rk)}">${F.ord(rk)}</span></div>`;
  const sched = (v, rk, o, d) => rk ? `<div class="mc" title="Opposing defenses ${F.sgn(o)} + opposing offenses ${F.sgn(d)} pts/game vs average"><span class="mv2">${F.sgn(v)}</span><span class="rk-b ${F.rkc(33 - rk)}" title="1st = hardest (red), 32nd = easiest (green)">${F.ord(rk)}</span></div><span class="sub">${rk <= 8 ? 'hard' : rk >= 25 ? 'easy' : 'average'}</span>` : '';
  const columns = teams => [
    { key: 'rank', label: '#', num: true, first: 'asc', cls: 'rk',
      html: r => `<span class="rkn">${r.rank}</span>${r.move > 0 ? `<span class="mv up">&#9650;${r.move}</span>` : r.move < 0 ? `<span class="mv dn">&#9660;${-r.move}</span>` : '<span class="mv">&ndash;</span>'}` },
    { key: 'nick', label: 'Team', stick: true, first: 'asc',
      html: r => `<div class="who">${F.logo(teams, r.team, 26)}<div><b><span class="nm-full">${esc(r.nick)}</span><span class="nm-short">${esc(r.team)}</span></b><span class="sub">${esc(r.team)} &middot; ${esc(r.record)}</span></div></div>` },
    { key: 'net', label: 'Net', num: true,
      html: r => `<div class="netc"><b>${F.sgn(r.net)}</b><span class="sub" title="80% of simulations rank this team between ${esc(String(r.range).replace('-', ' and '))} (ratings resampled within their uncertainty). Narrow = settled; wide = a few more games could move them a lot.">rank range ${esc(r.range)}</span></div>` },
    { key: 'off', label: 'Offense', title: 'Pass O + Run O', html: r => `<span title="Pass O ${F.sgn(r.pass_o)} + Run O ${F.sgn(r.rush_o)}">${mc(r.off, r.off_rk)}</span>` },
    { key: 'def', label: 'Defense', title: 'Pass D + Run D', html: r => `<span title="Pass D ${F.sgn(r.pass_d)} + Run D ${F.sgn(r.rush_d)}">${mc(r.def, r.def_rk)}</span>` },
    ...[['pass_o', 'Pass O', 'per 100 dropbacks, incl. starting QB'], ['rush_o', 'Run O', 'per 100 designed runs'],
        ['pass_d', 'Pass D', 'per 100 dropbacks faced'], ['rush_d', 'Run D', 'per 100 runs faced'], ['st', 'ST', '']].map(([k, label, nm]) => ({
      key: k, label, cls: 'minor',
      html: r => `<span${r[`${k}_pp`] != null ? ` title="${F.sgn(r[`${k}_pp`])} ${nm}"` : ''}>${mc(r[k], r[`${k}_rk`], 'mv3', ' sm')}</span>` })),
    { key: 'sos_past', label: 'Schedule played', html: r => sched(r.sos_past, r.sos_past_rk, r.sos_past_o, r.sos_past_d) },
    { key: 'sos_next', label: 'Schedule left', html: r => sched(r.sos_next, r.sos_next_rk, r.sos_next_o, r.sos_next_d) },
    { key: 'trend', label: 'Trend', sort: false, cls: 'hide-sm', html: r => spark(r.net_hist) },
  ];
  NFLE.areas.power = {
    mount(sec) {
      NFLE.week().then(D => {
        if (!D || !D.power || !D.power.length || !('net_hist' in D.power[0])) return;  // older week file: keep the page's table
        const v = D.power_vol || {}, n = (x, d) => x ? Math.round(x) : d;
        sec.innerHTML = `<div class="sec-head"><div><h2>Power rankings</h2><p>Opponent-adjusted points per game vs an average team. Everything adds up: Offense = Pass O + Run O, Defense = Pass D + Run D, Net = Offense + Defense + ST.</p></div></div>
          <details class="howto"><summary>How to read</summary><div>
            <dl class="ht">
              <dt>Every number</dt><dd>Points per game vs an average opponent. Higher is better everywhere, defense included, and the columns add up.</dd>
              <dt>Units</dt><dd>Per-play rating × a typical game's plays (about ${n(v.pass, 34)} dropbacks, ${n(v.rush, 25)} runs, ${n(v.st, 11)} special-teams plays). Hover a unit for its per-play rating. Pass O includes the current starting QB.</dd>
              <dt>Rank range</dt><dd>Where the team could rank given the uncertainty (10th–90th percentile). Narrow = settled; wide = a few games could move it a lot.</dd>
              <dt>Badges</dt><dd>League ranks: green = top 8, red = bottom 8.</dd>
              <dt>Schedule</dt><dd>Points per game opponents took away (played) or will (left). Positive = tougher than average; 1st = hardest.</dd>
              <dt>Arrows</dt><dd>Move since last week.</dd>
            </dl>
          </div></details>
          <div class="pw-tbl"></div>`;
        const teams = D.teams || {};
        NFLE.Table(sec.querySelector('.pw-tbl'), { columns: columns(teams), rows: D.power, sort: { key: 'rank', dir: 'asc' }, cls: 'tiles power',
          rowClass: () => 'teamrow tm-open', rowAttrs: r => `style="${F.rowStyle(teams, r.team)}" data-tm="${esc(r.team)}" title="Open the ${esc(r.nick)} team page"` });
      });
    },
  };
})();
