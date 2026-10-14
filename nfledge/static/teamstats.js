// Teams > Stats: raw regular-season team stats from our own play-by-play (data/stats/teams_<season>.json, built by
// tools/stats_build.py). Offense or defense (what a defense allowed), totals or per game; rows open the team card.
(() => {
  const NFLE = window.NFLE, esc = NFLE.esc;
  const store = (k, v) => { try { if (v === undefined) return localStorage.getItem(k); localStorage.setItem(k, v); } catch (e) { return null; } return v; };
  const pageSeason = () => { const m = location.pathname.match(/(\d{4})\/week-\d+\.html$/); return m ? +m[1] : null; };
  const f0 = v => v == null ? '' : Math.round(v).toLocaleString();
  const f1 = v => v == null ? '' : v.toFixed(1);
  const pct = v => v == null ? '' : `${(100 * v).toFixed(1)}%`;
  const mmss = s => s == null ? '' : `${Math.floor(s / 60)}:${String(Math.round(s % 60)).padStart(2, '0')}`;
  const div = (a, b) => b ? a / b : null;

  // Column set for one side ('o' offense, 'd' defense). per = per-game mode: counting stats divided by games.
  const columns = (side, per) => {
    const k = n => `${side}_${n}`, cnt = (r, n) => per ? div(r[k(n)], r.g) : r[k(n)];
    const num = (key, label, fn, fmt, first = 'desc', title = '') => ({ key, label, num: true, first, title, value: fn, html: r => fmt(fn(r)) });  // one table: auto widths
    const lowGood = side === 'd' ? 'asc' : 'desc', highGood = side === 'd' ? 'desc' : 'asc';  // natural sort per side
    return [
      { key: 'team', label: 'Team', stick: true, first: 'asc', w: 170, value: r => r.nick,
        html: r => `<div class="who"><span class="st-logo" style="--tc:${esc(r.color || '#555')}"><img src="${esc(r.logo || '')}" alt="" width="20" height="20" loading="lazy"></span><div><b>${esc(r.nick)}</b><span class="sub">${esc(r.team)} &middot; ${r.w}-${r.l}${r.t ? `-${r.t}` : ''}</span></div></div>` },
      num('pts', side === 'o' ? 'Pts' : 'Pts allowed', r => per ? div(side === 'o' ? r.pf : r.pa, r.g) : (side === 'o' ? r.pf : r.pa), per ? f1 : f0, lowGood),
      num('yds', 'Yds', r => cnt(r, 'yds'), per ? f1 : f0, lowGood),
      num('ypp', 'Y/P', r => div(r[k('yds')], r[k('plays')]), f1, lowGood, 'Yards per play'),
      num('plays', 'Plays', r => cnt(r, 'plays'), per ? f1 : f0, 'desc'),
      num('pass_yds', 'Pass yds', r => cnt(r, 'pass_yds'), per ? f1 : f0, lowGood, 'Net passing yards (sack yards subtracted)'),
      num('cmp', 'Cmp%', r => div(r[k('cmp')], r[k('att')]), pct, lowGood, 'Completion rate'),
      num('pass_td', 'Pass TD', r => cnt(r, 'pass_td'), per ? f1 : f0, lowGood),
      num('int', 'INT', r => cnt(r, 'int'), per ? f1 : f0, highGood, side === 'd' ? 'Interceptions made' : 'Interceptions thrown'),
      num('sacks', 'Sacks', r => cnt(r, 'sacks'), per ? f1 : f0, highGood, side === 'd' ? 'Sacks made' : 'Sacks taken'),
      num('nya', 'NY/A', r => div(r[k('pass_yds')], r[k('att')] + r[k('sacks')]), f1, lowGood, 'Net yards per pass attempt (sacks included)'),
      num('rush_yds', 'Rush yds', r => cnt(r, 'rush_yds'), per ? f1 : f0, lowGood),
      num('ypc', 'YPC', r => div(r[k('rush_yds')], r[k('rush_att')]), f1, lowGood, 'Yards per carry'),
      num('rush_td', 'Rush TD', r => cnt(r, 'rush_td'), per ? f1 : f0, lowGood),
      num('to', side === 'd' ? 'Takeaways' : 'Giveaways', r => per ? div(side === 'd' ? r.takeaways : r.turnovers, r.g) : (side === 'd' ? r.takeaways : r.turnovers), per ? f1 : f0, side === 'd' ? 'desc' : 'asc', 'Interceptions + fumbles lost'),
      num('fd', '1st downs', r => cnt(r, 'first_downs'), per ? f1 : f0, lowGood),
      num('third', '3rd %', r => div(r[k('third_c')], r[k('third_att')]), pct, lowGood, '3rd-down conversion rate'),
      num('fourth', '4th %', r => div(r[k('fourth_c')], r[k('fourth_att')]), pct, lowGood, '4th-down conversion rate (attempts only)'),
      num('rz', 'RZ TD%', r => div(r[k('rz_td')], r[k('rz')]), pct, lowGood, 'Touchdowns per drive that reached the red zone (inside the 20)'),
      ...(side === 'o' ? [num('top', 'TOP', r => div(r.o_top, r.g), mmss, 'desc', 'Time of possession per game'),
                          num('pen', 'Penalties', r => per ? div(r.pen, r.g) : r.pen, per ? f1 : f0, 'asc', 'Flags against, all phases (declined included)'),
                          num('penyd', 'Pen yds', r => per ? div(r.pen_yds, r.g) : r.pen_yds, per ? f1 : f0, 'asc', 'Penalty yards against'),
                          num('pendr', 'Drawn', r => r.pen_drawn == null ? null : per ? div(r.pen_drawn, r.g) : r.pen_drawn, per ? f1 : f0, 'desc', "Opponents' flags (penalties drawn)")] : []),
      num('epa', 'EPA/play', r => div(r[k('epa')], r[k('plays')]), v => v == null ? '' : (v > 0 ? '+' : '') + v.toFixed(3), lowGood, 'Expected points added per play'),
      num('succ', 'Success', r => div(r[k('success')], r[k('plays')]), pct, lowGood, 'Share of plays with positive EPA'),
    ];
  };

  NFLE.areas.teamstats = {
    mount(sec) {
      sec.classList.remove('soon');
      sec.innerHTML = `<div class="sec-head"><div><h2>Team stats</h2><p class="ts-sub">Loading&hellip;</p></div></div>
        <div class="dt-card"><div class="dt-tools">
          <select class="dt-select ts-season" aria-label="Season"></select>
          <div class="seg ts-type"><button type="button" data-t="reg">Regular season</button><button type="button" data-t="post">Playoffs</button></div>
          <div class="seg ts-side"><button type="button" data-v="o">Offense</button><button type="button" data-v="d">Defense</button></div>
          <div class="seg ts-per"><button type="button" data-v="tot">Totals</button><button type="button" data-v="pg">Per game</button></div>
        </div><div class="ts-tbl"></div></div>
        <p class="st-note muted">Regular season, from play-by-play. Defense = what opponents did against them. Sorting starts with the best value.</p>`;
      const sel = sec.querySelector('.ts-season'), sub = sec.querySelector('.ts-sub');
      let side = store('nfledge-ts-side') === 'd' ? 'd' : 'o', per = store('nfledge-ts-per') === 'pg', rows = [], table = null, season = null;
      const draw = () => {
        sec.querySelectorAll('.ts-side button').forEach(b => b.classList.toggle('on', b.dataset.v === side));
        sec.querySelectorAll('.ts-per button').forEach(b => b.classList.toggle('on', (b.dataset.v === 'pg') === per));
        const cols = columns(side, per);
        if (!table) table = NFLE.Table(sec.querySelector('.ts-tbl'), { columns: cols, rows, sort: { key: 'pts', dir: side === 'd' ? 'asc' : 'desc' },
          rowClass: () => 'tm-open', rowAttrs: r => `data-tm="${esc(r.team)}"` });
        else { table.setColumns(cols); table.update(rows); }
      };
      // Regular season / Playoffs: separate files, never mixed (teams_<season>_post.json)
      let stype = 'reg', IX = null;
      const typeBtns = () => sec.querySelectorAll('.ts-type button').forEach(b => {
        const has = b.dataset.t === 'reg' || (IX && (IX.post || []).includes(+sel.value));
        b.disabled = !has; b.title = has ? '' : 'No playoff games that season'; b.classList.toggle('on', b.dataset.t === stype);
      });
      const load = s => { if (stype === 'post' && !(IX && (IX.post || []).includes(s))) stype = 'reg'; typeBtns();
        return NFLE.load(`data/stats/teams_${s}${stype === 'post' ? '_post' : ''}.json`).then(d => {
        season = s;
        rows = Object.entries(d.teams).map(([team, vals]) => Object.assign({ team }, d.info[team] || { nick: team }, Object.fromEntries(d.cols.map((c, i) => [c, vals[i]]))));
        sub.textContent = stype === 'post' ? `${s} playoffs: ${rows.length} teams` : `${s} regular season${rows.length && rows[0].g ? `, ${Math.max(...rows.map(r => r.g))} games` : ''}`;
        draw();
      }).catch(() => { sub.textContent = 'No team stats for that season.'; }); };
      sec.querySelector('.ts-type').addEventListener('click', e => { const b = e.target.closest('[data-t]'); if (b && !b.disabled) { stype = b.dataset.t; load(+sel.value); } });
      // switching sides re-sorts by points, best first (most scored / fewest allowed)
      sec.querySelector('.ts-side').addEventListener('click', e => { const b = e.target.closest('[data-v]'); if (b) { side = b.dataset.v; store('nfledge-ts-side', side); draw(); table.setSort({ key: 'pts', dir: side === 'd' ? 'asc' : 'desc' }); } });
      sec.querySelector('.ts-per').addEventListener('click', e => { const b = e.target.closest('[data-v]'); if (b) { per = b.dataset.v === 'pg'; store('nfledge-ts-per', per ? 'pg' : 'tot'); draw(); } });
      NFLE.load('data/stats/index.json').then(ix => {
        IX = ix;
        const want = pageSeason() && ix.seasons.includes(pageSeason()) ? pageSeason() : ix.current;
        sel.innerHTML = [...ix.seasons].reverse().map(s => `<option value="${s}"${s === want ? ' selected' : ''}>${s}</option>`).join('');
        sel.onchange = () => load(+sel.value);
        load(want);
      }).catch(() => { sub.textContent = 'Team stats are not available on this page.'; });
    },
  };
})();
