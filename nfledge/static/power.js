// Teams > Power: the power rankings table from the week JSON (DATA.power; report.team_tables). Opponent-adjusted
// points per game vs an average team, unit by unit, with league-rank badges, the rank range from the bootstrap, the
// schedule played / left and this season's trend. Rows open the team page.
(() => {
  const NFLE = window.NFLE, esc = NFLE.esc, F = NFLE.fmt;
  // the season's weekly net ratings as a small line (the dot = this week)
  // weeks rated with a QB other than the usual starter (qb: 1s aligned with v) get a hollow ring
  const spark = (v, w = 84, h = 22, qb = []) => {
    v = (v || []).filter(x => x != null);
    if (v.length < 2) return '';
    const lo = Math.min(...v), span = (Math.max(...v) - lo) || 1, y = x => (h - 2 - (x - lo) / span * (h - 4)).toFixed(1);
    const pts = v.map((x, i) => `${(i * w / (v.length - 1)).toFixed(1)},${y(x)}`).join(' ');
    return `<svg class="spark" viewBox="0 0 ${w} ${h}" width="${w}" height="${h}" aria-hidden="true"><polyline points="${pts}" fill="none" stroke="currentColor" stroke-width="1.5"/>${qb.map((f, i) => f ? `<circle class="spark-qb" cx="${(i * w / (v.length - 1)).toFixed(1)}" cy="${y(v[i])}" r="3"/>` : '').join('')}<circle cx="${w}" cy="${y(v[v.length - 1])}" r="2.2" fill="currentColor"/></svg>`;
  };
  // Laid out to read at a glance (owner 2026-10-17): Net as a bar from zero with the rank range as a whisker, This
  // week folded into Net (shown only when this week's QB changes it), Offense / Defense as rank badges, the five units
  // as one heat strip, the schedule as two words. Every number is still in a tooltip.
  const badge = (rk, tip) => `<span class="rk-b ${F.rkc(rk)}" title="${esc(tip)}">${F.ord(rk)}</span>`;
  // Strength / Weakness (owner 2026-10-17, replacing a five-block heat strip: "hate the units column"): the team's
  // best and worst unit by league rank, in words; all five in its tap / hover tip
  const UNITS = [['pass_o', 'Pass O', 'per 100 dropbacks, incl. starting QB'], ['rush_o', 'Run O', 'per 100 designed runs'],
                 ['pass_d', 'Pass D', 'per 100 dropbacks faced'], ['rush_d', 'Run D', 'per 100 runs faced'], ['st', 'ST', '']];
  const sw = r => { const u = UNITS.map(([k, l]) => [l, r[`${k}_rk`], r[k]]).filter(x => x[1]).sort((a, b) => a[1] - b[1]);
    if (!u.length) return '';
    const best = u[0], worst = u[u.length - 1];
    const tip = UNITS.map(([k, l, per]) => `${l} ${F.sgn(r[k])} (${F.ord(r[`${k}_rk`])})`).join(' · ') + ' (pts/game vs average, league rank)';
    return `<span class="sw" title="${esc(tip)}"><span class="sw-b"><i>&#9650;</i>${esc(best[0])} <b>${F.ord(best[1])}</b></span><span class="sw-w"><i>&#9660;</i>${esc(worst[0])} <b>${F.ord(worst[1])}</b></span></span>`; };
  const word = rk => rk <= 8 ? 'hard' : rk >= 25 ? 'easy' : 'avg';
  const sched = r => r.sos_past_rk ? `<span class="sd" title="Opponents' strength vs average: played ${F.sgn(r.sos_past)} pts/game (${F.ord(r.sos_past_rk)} hardest), left ${F.sgn(r.sos_next)} (${F.ord(r.sos_next_rk)} hardest)">`
    + `<span><i>played</i> <b class="sd-${word(r.sos_past_rk)}">${word(r.sos_past_rk)}</b></span><span><i>left</i> <b class="sd-${word(r.sos_next_rk)}">${word(r.sos_next_rk)}</b></span></span>` : '';
  const columns = (teams, rows) => {
    // the bar's scale: every team's net and the ends of every rank range (a rank range maps to the nets at those ranks)
    const byRank = rows.map(r => r.net).sort((a, b) => b - a);
    const ends = r => { const [hi, lo] = String(r.range || '').split('-').map(Number); return hi && lo ? [byRank[lo - 1], byRank[hi - 1]] : [r.net, r.net]; };
    const all = rows.flatMap(r => [r.net, ...ends(r)]).filter(x => x != null);
    const lo = Math.min(0, ...all), hi = Math.max(0, ...all), X = v => `${((v - lo) / (hi - lo || 1) * 100).toFixed(1)}%`;
    const bar = r => { const [a, b] = ends(r), qb = r.net_now != null && Math.abs(r.net_now - r.net) >= 0.1;
      return `<div class="nb" title="Net ${F.sgn(r.net)} pts/game vs average. Whisker: 80% of simulations rank them ${esc(String(r.range).replace('-', ' to '))}">`
        + `<b>${F.sgn(r.net)}</b><span class="nb-t"><i class="nb-z" style="left:${X(0)}"></i>`
        + `<i class="nb-w" style="left:${X(a)};width:calc(${X(b)} - ${X(a)})"></i>`
        + `<i class="nb-b ${r.net >= 0 ? 'pos' : 'neg'}" style="left:${X(Math.min(0, r.net))};width:calc(${X(Math.max(0, r.net))} - ${X(Math.min(0, r.net))})"></i></span>`
        + `${qb ? `<span class="nb-qb" title="With this week's starting QB (${esc(r.qb_note || '')}): ${F.ord(r.rank_now)}">this week ${F.sgn(r.net_now)}</span>` : ''}</div>`; };
    return [
      { key: 'rank', label: '#', num: true, first: 'asc', cls: 'rk',
        html: r => `<span class="rkn">${r.rank}</span>${r.move > 0 ? `<span class="mv up">&#9650;${r.move}</span>` : r.move < 0 ? `<span class="mv dn">&#9660;${-r.move}</span>` : '<span class="mv">&ndash;</span>'}${r.qb_note ? `<span class="mv qbx" title="${esc(r.qb_note)}: this week's rating uses him">QB</span>` : ''}` },
      { key: 'nick', label: 'Team', stick: true, first: 'asc',
        html: r => `<div class="who tm-open" data-tm="${esc(r.team)}" title="Open the ${esc(r.nick)} team page">${F.logo(teams, r.team, 26)}<div><b><span class="nm-full">${esc(r.nick)}</span><span class="nm-short">${esc(r.team)}</span></b><span class="sub">${esc(r.team)} &middot; ${esc(r.record)}</span></div></div>` },
      { key: 'net', label: 'Net', num: true, cls: 'key nbc', title: 'Points per game vs an average team; the whisker is the rank range', html: bar },
      { key: 'off', label: 'Off', num: true, cls: 'odc', title: 'Offense rank (Pass O + Run O)', value: r => r.off,
        html: r => badge(r.off_rk, `Offense ${F.sgn(r.off)} pts/game: Pass O ${F.sgn(r.pass_o)} + Run O ${F.sgn(r.rush_o)}`) },
      { key: 'def', label: 'Def', num: true, cls: 'odc', title: 'Defense rank (Pass D + Run D)', value: r => r.def,
        html: r => badge(r.def_rk, `Defense ${F.sgn(r.def)} pts/game: Pass D ${F.sgn(r.pass_d)} + Run D ${F.sgn(r.rush_d)}`) },
      { key: 'sw', label: 'Strength / Weakness', sort: false, cls: 'swc', title: 'Best and worst of pass O, run O, pass D, run D and special teams, by league rank', html: sw },
      { key: 'sos_next', label: 'Schedule', first: 'desc', title: 'How hard the schedule has been and will be', html: sched },
      { key: 'trend', label: 'Trend', sort: false, cls: 'hide-sm',
        html: r => `<span${(r.qb_hist || []).some(Boolean) ? ' title="Hollow rings: weeks rated with a backup QB starting"' : ''}>${spark(r.net_hist, 84, 22, r.qb_hist || [])}</span>` },
    ];
  };
  NFLE.areas.power = {
    mount(sec) {
      NFLE.week().then(D => {
        if (!D || !D.power || !D.power.length || !('net_hist' in D.power[0])) return;  // older week file: keep the page's table
        const v = D.power_vol || {}, n = (x, d) => x ? Math.round(x) : d;
        sec.innerHTML = `<div class="sec-head"><div><h2>Power rankings</h2><p>How good each team is from here on, in points per game vs an average team.</p></div></div>
          <details class="howto"><summary>How to read</summary><div>
            <dl class="ht">
              <dt>Net</dt><dd>How good the team is from here on: opponent-adjusted points per game vs an average team (Offense + Defense + special teams). The bar runs from zero; its thin whisker is the rank range, where the team could rank given the uncertainty (10th to 90th percentile): short = settled, long = a few games could move it a lot. A quarterback who is out counts by his chance to be back in each remaining game.</dd>
              <dt>This week</dt><dd>Shown under Net only when this week's starting quarterback changes the rating (the QB tag by the rank); Matchups uses it.</dd>
              <dt>Off / Def</dt><dd>League ranks: green = top 8, red = bottom 8. Tap or hover for the points.</dd>
              <dt>Strength / Weakness</dt><dd>The best and worst of the team's five units (pass offense, run offense, pass defense, run defense, special teams) by league rank. Tap or hover it for all five, in points per game (per-play rating x a typical game's ${n(v.pass, 34)} dropbacks, ${n(v.rush, 25)} runs, ${n(v.st, 11)} special-teams plays).</dd>
              <dt>Schedule</dt><dd>How hard the opponents were (played) and will be (left), by their Power ratings: hard = top 8, easy = bottom 8.</dd>
              <dt>Arrows</dt><dd>Move since last week. Tap a team for its page; tap anything else for its numbers.</dd>
            </dl>
          </div></details>
          <div class="pw-tbl"></div>`;
        const teams = D.teams || {};
        NFLE.Table(sec.querySelector('.pw-tbl'), { columns: columns(teams, D.power), rows: D.power, sort: { key: 'rank', dir: 'asc' }, cls: 'tiles power',
          // only the team (logo and name) opens its page (owner 2026-10-17), so the rest of the row can show its tips on a tap
          rowClass: () => 'teamrow', rowAttrs: r => `style="${F.rowStyle(teams, r.team)}"` });
        sec.querySelector('.pw-tbl').setAttribute('data-taptip', '');
      });
    },
  };
})();
