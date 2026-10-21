// Teams > Standings: data/standings/<season>.json (tools/standings_build.py; tiebreakers in nfledge/standings.py).
// Two views: Divisions (eight tables) and Playoff picture (each conference in seed order). Rows open the team card.
(() => {
  let TEAMS = {};  // the week data's teams map (tile colors, logos), filled at mount
  const NFLE = window.NFLE, esc = NFLE.esc;
  const VIEW_KEY = 'nfledge-standings-view';
  const store = (k, v) => { try { if (v === undefined) return localStorage.getItem(k); localStorage.setItem(k, v); } catch (e) { return null; } return v; };
  const pageSeason = () => { const m = location.pathname.match(/(\d{4})\/week-\d+\.html$/); return m ? +m[1] : null; };
  const logo = (r, size = 22) => r.logo
    ? `<span class="st-logo" style="--tc:${esc(r.color || '#555')}"><img src="${esc(r.logo)}" alt="" width="${size}" height="${size}" loading="lazy"></span>` : '';
  const pct = v => v == null ? '' : v.toFixed(3).replace(/^0/, '');
  const sgn = v => v > 0 ? `+${v}` : `${v}`;
  // the deciding tiebreak step: full name (tooltip) and a short tag, so the pinned team column stays narrow on phones
  const WHY = { 'head-to-head (sweep)': 'head-to-head sweep', 'division tiebreak': 'ahead of division rival' };
  const TB = { 'head-to-head': 'H2H', 'head-to-head (sweep)': 'H2H sweep', 'division record': 'div rec', 'common games': 'common',
               'conference record': 'conf rec', 'strength of victory': 'SOV', 'strength of schedule': 'SOS',
               'conference points rank': 'conf pts', 'league points rank': 'NFL pts', 'net points': 'net pts', 'division tiebreak': 'div TB' };

  const teamCell = (r, view) => {
    const why = view === 'conf' ? r.conf_why : r.div_why;
    const seed = r.seed ? `<span class="st-seed${r.seed <= (r.conf_rank && r.seed) ? '' : ''}" title="${r.seed <= 4 ? 'Division leader' : 'Wild card'}: seed ${r.seed}">${r.seed}</span>` : '';
    return NFLE.ui.team(r.team, TEAMS, `${esc(r.team)}${why ? ` &middot; <span class="st-why" title="Ahead of the clubs it's tied with on: ${esc(WHY[why] || why)}">${why === 'division tiebreak' ? '' : 'TB: '}${esc(TB[why] || why)}</span>` : ''}`, seed);
  };
  const columns = (ties, view) => [
    ...(view === 'conf' ? [{ w: 44, key: 'conf_rank', label: '#', num: true, first: 'asc' }] : []),
    { w: 176, key: 'nick', label: 'Team', stick: true, first: 'asc', html: r => teamCell(r, view), value: r => view === 'conf' ? r.conf_rank : r.div_rank },
    { w: 46, key: 'w', label: 'W', num: true, cls: 'key' }, { w: 46, key: 'l', label: 'L', num: true, first: 'asc', cls: 'key' },
    ...(ties ? [{ w: 42, key: 't', label: 'T', num: true }] : []),
    { w: 64, key: 'pct', label: 'Pct', num: true, html: r => pct(r.pct) },
    { w: 58, key: 'pf', label: 'PF', num: true }, { w: 58, key: 'pa', label: 'PA', num: true, first: 'asc' },
    { w: 64, key: 'diff', label: 'Diff', num: true, cls: 'key', html: r => `<span class="${r.diff > 0 ? 'st-pos' : r.diff < 0 ? 'st-neg' : ''}">${sgn(r.diff)}</span>` },
    { w: 64, key: 'div_rec', label: 'Div', cls: 'ctr', value: r => recPct(r.div_rec) }, { w: 68, key: 'conf_rec', label: 'Conf', cls: 'ctr', value: r => recPct(r.conf_rec) },
    { w: 64, key: 'home', label: 'Home', cls: 'ctr', value: r => recPct(r.home) }, { w: 64, key: 'away', label: 'Away', cls: 'ctr', value: r => recPct(r.away) },
    { w: 58, key: 'streak', label: 'Strk', cls: 'ctr', value: r => (r.streak[0] === 'W' ? 1 : -1) * (+r.streak.slice(1) || 0) },
    { w: 116, key: 'last5', label: 'Last 5', sort: false, html: r => `<span class="st-l5">${[...r.last5].map(x => `<i class="${x === 'W' ? 'w' : x === 'L' ? 'l' : 't'}">${x}</i>`).join('')}</span>` },
  ];
  const recPct = s => { const [w, l, t = 0] = String(s || '').split('-').map(Number); const g = w + l + t; return g ? (w + t / 2) / g : null; };

  NFLE.areas.standings = {
    mount(sec) {
      sec.classList.remove('soon');
      NFLE.week().then(D => { if (D && D.teams) { TEAMS = D.teams; draw(); } });
      sec.innerHTML = `<div class="sec-head"><div><h2>Standings</h2><p class="st-sub">Loading&hellip;</p></div></div>
        <div class="dt-card"><div class="dt-tools">
          <select class="dt-select st-season" aria-label="Season"></select>
          <div class="seg st-view"><button type="button" data-v="div">Divisions</button><button type="button" data-v="conf">Playoff picture</button></div>
        </div><div class="skel-zone st-body"></div></div>
        <p class="st-note muted">Ties count as half a win. Tiebreakers follow the NFL's procedure (head-to-head, division record, common games, conference record, strength of victory and schedule, points rankings, net points); the deciding step is shown under the team (TB = won a tiebreak on: H2H = head-to-head, div / conf rec = division / conference record, common = common games, SOV / SOS = strength of victory / schedule, pts = points rankings; div TB = ahead of a division rival on the division tiebreak). Net touchdowns and the coin toss (the last two steps, almost never reached) are not modeled.</p>`;
      const sel = sec.querySelector('.st-season'), body = sec.querySelector('.st-body'), sub = sec.querySelector('.st-sub');
      let view = store(VIEW_KEY) === 'conf' ? 'conf' : 'div', doc = null;
      const draw = () => {
        sec.querySelectorAll('.st-view button').forEach(b => b.classList.toggle('on', b.dataset.v === view));
        if (!doc) return;
        const ties = doc.teams.some(r => r.t > 0);
        sub.textContent = doc.complete ? `${doc.season} final regular-season standings` : doc.through_week ? `${doc.season} through week ${doc.through_week}` : `${doc.season}: no games played yet`;
        body.innerHTML = '';
        for (const conf of ['AFC', 'NFC']) {
          const teams = doc.teams.filter(r => r.conf === conf);
          if (view === 'conf') {
            body.insertAdjacentHTML('beforeend', `<h3 class="st-h">${NFLE.ui.conf(conf, 20)}</h3><div class="st-tbl"></div>`);
            const rows = [...teams].sort((a, b) => a.conf_rank - b.conf_rank);
            NFLE.Table(body.lastElementChild, { columns: columns(ties, 'conf'), rows, sort: { key: 'conf_rank', dir: 'asc' },
              cls: 'tiles', rowClass: r => `teamrow tm-open${r.conf_rank === doc.playoff_teams ? ' st-cut' : ''}`, rowAttrs: r => `${NFLE.ui.tileStyle(TEAMS, r.team)} data-tm="${esc(r.team)}"` });
          } else {
            const divs = [...new Set(teams.map(r => r.div))].sort();
            for (const d of divs) {
              body.insertAdjacentHTML('beforeend', `<h3 class="st-h">${NFLE.ui.conf(d, 18)}</h3><div class="st-tbl"></div>`);
              const rows = teams.filter(r => r.div === d).sort((a, b) => a.div_rank - b.div_rank);
              NFLE.Table(body.lastElementChild, { columns: columns(ties, 'div'), rows, sort: { key: 'nick', dir: 'asc' },
                cls: 'tiles', rowClass: () => 'teamrow tm-open', rowAttrs: r => `${NFLE.ui.tileStyle(TEAMS, r.team)} data-tm="${esc(r.team)}"` });
            }
          }
        }
      };
      // the clubs as they were that season (OAK / SD / STL before their moves; shell.js fmt.era), once per file
      const eraDoc = d => { if (d && !d._era) { (d.teams || []).forEach(r => { const t = NFLE.fmt.era(r.team, d.season);
        if (t !== r.team) { const o = NFLE.fmt.teamOf(TEAMS, t); Object.assign(r, { team: t, logo: o.logo || r.logo, color: o.color || r.color, nick: o.nick || r.nick }); } }); d._era = 1; } return d; };
      const load = s => NFLE.load(`data/standings/${s}.json`).then(d => { doc = eraDoc(d); draw(); })
        .catch(() => { body.innerHTML = '<p class="muted st-pad">No standings for that season.</p>'; });
      sec.querySelector('.st-view').addEventListener('click', e => {
        const b = e.target.closest('[data-v]'); if (!b) return; view = b.dataset.v; store(VIEW_KEY, view); draw();
      });
      NFLE.load('data/standings/index.json').then(ix => {
        const want = pageSeason() && ix.seasons.includes(pageSeason()) ? pageSeason() : ix.current;
        sel.innerHTML = [...ix.seasons].reverse().map(s => `<option value="${s}"${s === want ? ' selected' : ''}>${s}</option>`).join('');
        sel.onchange = () => load(+sel.value);
        load(want);
      }).catch(() => { sub.textContent = 'Standings are not available on this page.'; });
      draw();
    },
  };
})();
