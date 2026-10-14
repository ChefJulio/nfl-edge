// Teams > Standings: data/standings/<season>.json (tools/standings_build.py; tiebreakers in nfledge/standings.py).
// Two views: Divisions (eight tables) and Playoff picture (each conference in seed order). Rows open the team card.
(() => {
  const NFLE = window.NFLE, esc = NFLE.esc;
  const VIEW_KEY = 'nfledge-standings-view';
  const store = (k, v) => { try { if (v === undefined) return localStorage.getItem(k); localStorage.setItem(k, v); } catch (e) { return null; } return v; };
  const pageSeason = () => { const m = location.pathname.match(/(\d{4})\/week-\d+\.html$/); return m ? +m[1] : null; };
  const logo = (r, size = 22) => r.logo
    ? `<span class="st-logo" style="--tc:${esc(r.color || '#555')}"><img src="${esc(r.logo)}" alt="" width="${size}" height="${size}" loading="lazy"></span>` : '';
  const pct = v => v == null ? '' : v.toFixed(3).replace(/^0/, '');
  const sgn = v => v > 0 ? `+${v}` : `${v}`;
  const WHY = { 'head-to-head (sweep)': 'head-to-head sweep', 'division tiebreak': 'ahead of division rival' };

  const teamCell = (r, view) => {
    const why = view === 'conf' ? r.conf_why : r.div_why;
    const seed = r.seed ? `<span class="st-seed${r.seed <= (r.conf_rank && r.seed) ? '' : ''}" title="${r.seed <= 4 ? 'Division leader' : 'Wild card'}: seed ${r.seed}">${r.seed}</span>` : '';
    return `<div class="who">${logo(r)}<div><b>${esc(r.nick)}</b>${seed}
      <span class="sub">${esc(r.team)}${why ? ` &middot; <span class="st-why" title="Ahead of the clubs it's tied with on: ${esc(WHY[why] || why)}">${why === 'division tiebreak' ? '' : 'won tiebreak: '}${esc(WHY[why] || why)}</span>` : ''}</span></div></div>`;
  };
  const columns = (ties, view) => [
    ...(view === 'conf' ? [{ key: 'conf_rank', label: '#', num: true, first: 'asc' }] : []),
    { key: 'nick', label: 'Team', stick: true, first: 'asc', html: r => teamCell(r, view), value: r => view === 'conf' ? r.conf_rank : r.div_rank },
    { key: 'w', label: 'W', num: true }, { key: 'l', label: 'L', num: true, first: 'asc' },
    ...(ties ? [{ key: 't', label: 'T', num: true }] : []),
    { key: 'pct', label: 'Pct', num: true, html: r => pct(r.pct) },
    { key: 'pf', label: 'PF', num: true }, { key: 'pa', label: 'PA', num: true, first: 'asc' },
    { key: 'diff', label: 'Diff', num: true, html: r => `<span class="${r.diff > 0 ? 'st-pos' : r.diff < 0 ? 'st-neg' : ''}">${sgn(r.diff)}</span>` },
    { key: 'div_rec', label: 'Div', value: r => recPct(r.div_rec) }, { key: 'conf_rec', label: 'Conf', value: r => recPct(r.conf_rec) },
    { key: 'home', label: 'Home', value: r => recPct(r.home) }, { key: 'away', label: 'Away', value: r => recPct(r.away) },
    { key: 'streak', label: 'Strk', value: r => (r.streak[0] === 'W' ? 1 : -1) * (+r.streak.slice(1) || 0) },
    { key: 'last5', label: 'Last 5', sort: false, html: r => `<span class="st-l5">${[...r.last5].map(x => `<i class="${x === 'W' ? 'w' : x === 'L' ? 'l' : 't'}">${x}</i>`).join('')}</span>` },
  ];
  const recPct = s => { const [w, l, t = 0] = String(s || '').split('-').map(Number); const g = w + l + t; return g ? (w + t / 2) / g : null; };

  NFLE.areas.standings = {
    mount(sec) {
      sec.classList.remove('soon');
      sec.innerHTML = `<div class="sec-head"><div><h2>Standings</h2><p class="st-sub">Loading&hellip;</p></div></div>
        <div class="dt-card"><div class="dt-tools">
          <select class="st-season" aria-label="Season"></select>
          <div class="seg st-view"><button type="button" data-v="div">Divisions</button><button type="button" data-v="conf">Playoff picture</button></div>
        </div><div class="st-body"></div></div>
        <p class="st-note muted">Ties count as half a win. Tiebreakers follow the NFL's procedure (head-to-head, division record, common games, conference record, strength of victory and schedule, points rankings, net points); the deciding step is shown under the team. Net touchdowns and the coin toss (the last two steps, almost never reached) are not modeled.</p>`;
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
            body.insertAdjacentHTML('beforeend', `<h3 class="st-h">${conf}</h3><div class="st-tbl"></div>`);
            const rows = [...teams].sort((a, b) => a.conf_rank - b.conf_rank);
            NFLE.Table(body.lastElementChild, { columns: columns(ties, 'conf'), rows, sort: { key: 'conf_rank', dir: 'asc' },
              rowClass: r => `tm-open${r.conf_rank === doc.playoff_teams ? ' st-cut' : ''}`, rowAttrs: r => `data-tm="${esc(r.team)}"` });
          } else {
            const divs = [...new Set(teams.map(r => r.div))].sort();
            for (const d of divs) {
              body.insertAdjacentHTML('beforeend', `<h3 class="st-h">${esc(d)}</h3><div class="st-tbl"></div>`);
              const rows = teams.filter(r => r.div === d).sort((a, b) => a.div_rank - b.div_rank);
              NFLE.Table(body.lastElementChild, { columns: columns(ties, 'div'), rows, sort: { key: 'nick', dir: 'asc' },
                rowClass: () => 'tm-open', rowAttrs: r => `data-tm="${esc(r.team)}"` });
            }
          }
        }
      };
      const load = s => NFLE.load(`data/standings/${s}.json`).then(d => { doc = d; draw(); })
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
