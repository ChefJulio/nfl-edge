// Model > Reference (owner 2026-10-18): league-wide rates from the play-by-play, descriptive only (not the model).
// data/reference.json (tools/reference_build.py) keeps counts per season, so any window is a sum: "Best fit" (every
// season, or since the rule change for tables a rule moved), all seasons, the last ten, the last three. Cells under
// 50 plays fade; every cell's tooltip has its count.
(() => {
  const NFLE = window.NFLE, esc = NFLE.esc;
  const KEY = 'nfledge-ref-window';
  const store = v => { try { if (v === undefined) return localStorage.getItem(KEY); localStorage.setItem(KEY, v); } catch (e) { return null; } return v; };
  const WINS = [['fit', 'Best fit'], ['all', 'All'], ['10', 'Last 10'], ['3', 'Last 3']];
  const DOWNS = ['1st', '2nd', '3rd', '4th'];
  const pc = (k, n) => n ? `${Math.round(100 * k / n)}%` : '';
  NFLE.areas.reference = {
    mount(sec) {
      sec.classList.remove('soon');
      sec.innerHTML = '<div class="sec-head"><div><h2>Reference</h2><p>How often things happen in the NFL, from every regular-season play since 2001. Descriptive history, not our model.</p></div></div><div class="rf-body skel-zone"></div>';
      NFLE.load('data/reference.json').then(R => draw(sec, R), () => { sec.querySelector('.rf-body').innerHTML = '<p class="muted">Reference tables are not available on this page.</p>'; });
    },
  };
  function draw(sec, R) {
    const M = R.meta, T = R.t, seasons = M.seasons, last = seasons[seasons.length - 1];
    let win = store() || 'fit';
    // the seasons a table sums in the chosen window
    const yrs = tbl => { const rule = M.rules[tbl]; const from = win === 'all' ? seasons[0] : win === '10' ? last - 9 : win === '3' ? last - 2 : rule ? rule[0] : seasons[0];
      return seasons.filter(s => s >= from); };
    const sum = (tbl, key) => { const out = []; yrs(tbl).forEach(s => { const c = (T[tbl][s] || {})[key]; if (c) c.forEach((v, i) => { out[i] = (out[i] || 0) + v; }); }); return out; };
    const span = tbl => { const y = yrs(tbl); return y.length > 1 ? `${y[0]}-${y[y.length - 1]}` : `${y[0]}`; };
    const heat = (v, lo = 0, hi = 1) => { const t = Math.max(0, Math.min(1, (v - lo) / (hi - lo || 1))); return `--h:${(t * 120).toFixed(0)};--a:${(0.12 + 0.3 * t).toFixed(2)}`; };
    const cell = (k, n, opts = {}) => {
      if (!n) return '<td class="rf-c rf-na"></td>';
      const v = k / n, thin = n < 50;
      return `<td class="rf-c${thin ? ' thin' : ''}" style="${heat(opts.inv ? 1 - v : v, opts.lo, opts.hi)}" title="${esc(`${opts.what || ''}${pc(k, n)} of ${n.toLocaleString()} ${opts.unit || 'plays'}${thin ? ' (few plays: read with care)' : ''}`)}">${opts.fmt ? opts.fmt(k, n) : pc(k, n)}</td>`;
    };
    const head = (title, tbl, note) => `<div class="rf-h"><h3>${title}</h3><span class="rf-span">${span(tbl)}</span></div>${note ? `<p class="rf-note">${note}</p>` : ''}`;
    const rule = tbl => M.rules[tbl] ? `<p class="rf-rule">${esc(M.rules[tbl][1])}${win === 'fit' ? '; shown since then' : ''}.</p>` : '';
    const grid = (rows, cols, rowLab, colLab, f) => `<div class="rf-scroll"><table class="rf-t"><thead><tr><th></th>${cols.map(c => `<th>${colLab(c)}</th>`).join('')}</tr></thead>
      <tbody>${rows.map(r => `<tr><th>${rowLab(r)}</th>${cols.map(c => f(r, c)).join('')}</tr>`).join('')}</tbody></table></div>`;
    const seg = (name, opts, cur) => `<div class="seg rf-seg" data-seg="${name}">${opts.map(([k, l]) => `<button type="button" data-v="${k}" class="${cur === k ? 'on' : ''}">${l}</button>`).join('')}</div>`;
    const S = { conv: 'ss', goal: 'td', turn: 'both', fourth: 'conv' };
    const render = () => {
      const D = ['1', '2', '3', '4'];
      // 1) conversion by down and distance
      const convI = S.conv === 'ss' ? 1 : 2;
      const conv = `<div class="gcs rf">${head('Converting by down and distance', 'conv', 'Share that earn a new set of downs (or score). Not goal to go. 4th down: only plays where the offense went for it.')}
        ${seg('conv', [['ss', 'Series converts'], ['now', 'On this play']], S.conv)}
        ${grid(M.dist, D, d => `& ${d}`, d => DOWNS[d - 1], (d, dn) => { const c = sum('conv', `${dn}|${d}`); return cell(c[convI] || 0, c[0] || 0, { what: `${DOWNS[dn - 1]} & ${d}: ` }); })}</div>`;
      // 2) goal to go
      const gi = S.goal === 'td' ? 1 : 2;
      const goal = `<div class="gcs rf">${head('Goal to go', 'goal', 'What the drive ended with, by the down and yards to the goal line.')}
        ${seg('goal', [['td', 'Touchdown'], ['fg', 'Field goal']], S.goal)}
        ${grid(['1', '2', '3', '4', '5', '6', '7', '8', '9', '10+'], D, y => `at ${y}`, d => `${DOWNS[d - 1]} & goal`, (y, dn) => { const c = sum('goal', `${dn}|${y}`); return cell(c[gi] || 0, c[0] || 0, { what: `${DOWNS[dn - 1]} & goal at the ${y}: ` }); })}</div>`;
      // 3) turnovers
      const turn = `<div class="gcs rf">${head('Turnovers by down and distance', 'turn', 'Share of plays that end in an interception or a lost fumble.')}
        ${seg('turn', [['both', 'Either'], ['int', 'Interception'], ['fum', 'Fumble lost']], S.turn)}
        ${grid(M.dist, D, d => `& ${d}`, d => DOWNS[d - 1], (d, dn) => { const c = sum('turn', `${dn}|${d}`); const k = S.turn === 'int' ? c[1] : S.turn === 'fum' ? c[2] : (c[1] || 0) + (c[2] || 0);
          return cell(k || 0, c[0] || 0, { inv: true, hi: 0.08, what: `${DOWNS[dn - 1]} & ${d}: `, fmt: (k_, n) => `${(100 * k_ / n).toFixed(1)}%` }); })}</div>`;
      // 4) fourth down
      const ZONES = [['own', 'Own side'], ['mid', 'Midfield'], ['fg', 'Opp 21-40'], ['rz', 'Red zone']];
      const fourth = `<div class="gcs rf">${head('4th down', 'fourth', 'How often teams go for it, and how often it works, by distance and field position.')}
        ${seg('fourth', [['conv', 'Converted (when going)'], ['went', 'Went for it']], S.fourth)}
        ${grid(['1', '2', '3-4', '5-7', '8+'], ZONES, d => `4th & ${d}`, z => z[1], (d, z) => { const c = sum('fourth', `${d}|${z[0]}`);
          return S.fourth === 'went' ? cell(c[1] || 0, c[0] || 0, { what: `went for it on 4th & ${d}: `, unit: '4th downs' }) : cell(c[2] || 0, c[1] || 0, { what: `converted 4th & ${d}: `, unit: 'attempts' }); })}</div>`;
      // 5) field goals, every yard
      const fgD = [...Array(42).keys()].map(i => String(i + 18)).concat(['60+']);
      const fgRows = fgD.map(d => { const c = sum('fg', d); return c[0] ? `<div class="rf-fg${c[0] < 50 ? ' thin' : ''}" title="${esc(`${d} yards: ${pc(c[1], c[0])} of ${c[0]} kicks`)}"><span>${d}</span><i style="width:${(100 * c[1] / c[0]).toFixed(0)}%"></i><b>${pc(c[1], c[0])}</b></div>` : ''; }).join('');
      const fg = `<div class="gcs rf">${head('Field goals by distance', 'fg', 'Make rate at every yard (the kick distance, snap to goalpost).')}<div class="rf-fgs">${fgRows}</div></div>`;
      // 6) kicks and tries
      const tile = (tbl, key, i, label, unit) => { const c = sum(tbl, key); return `<div class="rf-tile" title="${esc(`${c[0] || 0} ${unit}, ${span(tbl)}`)}"><div class="rf-k">${label}</div><div class="rf-v">${c[0] ? pc(c[i], c[0]) : '-'}</div><div class="rf-n">${(c[0] || 0).toLocaleString()} ${unit} · ${span(tbl)}</div></div>`; };
      const kicks = `<div class="gcs rf"><div class="rf-h"><h3>Kicks and tries</h3></div><div class="rf-tiles">
        ${tile('xp', 'all', 1, 'Extra point good', 'kicks')}${tile('two', 'pass', 1, 'Two-point pass', 'tries')}${tile('two', 'run', 1, 'Two-point run', 'tries')}
        ${tile('onside', 'all', 1, 'Onside kick recovered', 'kicks')}${tile('kick', 'all', 1, 'Kickoff touchback', 'kickoffs')}${tile('redzone', 'all', 1, 'Red zone drive: TD', 'drives')}${tile('redzone', 'all', 2, 'Red zone drive: FG', 'drives')}</div>
        ${['xp', 'onside', 'kick'].map(rule).join('')}</div>`;
      // 7) drives by starting spot
      const starts = ['1-10', '11-20', '21-30', '31-40', '41-50', '51-60', '61-70', '71-80', '81-90', '91-100'];
      const drive = `<div class="gcs rf">${head('Drives by starting spot', 'drive', 'What a drive ends with by where it starts (yards from its own goal line: 21-30 is its own 21 to 30).')}
        ${grid(starts, [['td', 'TD'], ['fg', 'FG'], ['any', 'Any score']], s => s.replace(/^(\d+)-(\d+)$/, (m, a, b) => +a > 50 ? `opp ${100 - b}-${100 - a + 1}` : `own ${a}-${b}`), c => c[1], (s, c) => { const x = sum('drive', s);
          return cell(c[0] === 'td' ? x[1] || 0 : c[0] === 'fg' ? x[2] || 0 : (x[1] || 0) + (x[2] || 0), x[0] || 0, { unit: 'drives', what: `from ${s}: ` }); })}</div>`;
      // 8) expected points
      const epRows = [...Array(20).keys()].map(i => `${i * 5 + 1}-${i * 5 + 5}`);
      const ep = `<div class="gcs rf">${head('Expected points, 1st & 10', 'ep', 'Average expected points (nflfastR\'s model) on 1st & 10, by yards to the end zone.')}
        ${grid(epRows, [['ep', 'Points']], y => `${y} to go`, c => c[1], y => { const x = sum('ep', y); const v = x[0] ? x[1] / x[0] : null;
          return v == null ? '<td class="rf-c rf-na"></td>' : `<td class="rf-c" style="${heat(v, -1, 6)}" title="${x[0].toLocaleString()} plays">${v.toFixed(2)}</td>`; })}</div>`;
      // 9) leads
      const lead = `<div class="gcs rf">${head('How often a lead holds', 'lead', 'Share of games the leading team won, by the size of its lead at that moment (ties count half).')}
        ${grid(M.lead, M.moments, l => `up ${l}`, m => m, (l, m) => { const x = sum('lead', `${m}|${l}`); return cell(x[1] || 0, x[0] || 0, { lo: 0.5, unit: 'games', what: `up ${l} at ${m}: ` }); })}</div>`;
      const body = sec.querySelector('.rf-body');
      body.classList.remove('skel-zone');
      body.innerHTML = `<div class="rf-top">${seg('win', WINS, win)}<span class="muted rf-wn">${win === 'fit' ? 'Every season, or since the rule change for tables a rule moved' : `Seasons: ${win === 'all' ? `${seasons[0]}-${last}` : win === '10' ? `${last - 9}-${last}` : `${last - 2}-${last}`}`}. Faded cells rest on fewer than 50 plays; tap any cell for its count.</span></div>
        ${conv}${goal}${fourth}${turn}${fg}${kicks}${drive}${lead}${ep}`;
      body.querySelectorAll('.rf-seg').forEach(g => g.onclick = e => { const b = e.target.closest('[data-v]'); if (!b) return;
        if (g.dataset.seg === 'win') { win = b.dataset.v; store(win); } else S[g.dataset.seg] = b.dataset.v; render(); });
    };
    render();
  }
})();
