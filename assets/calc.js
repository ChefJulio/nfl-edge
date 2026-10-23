// Model > Calc (owner 2026-10-23: "a calculator where you input down, distance, score, team timeouts left and game
// clock, and you can use it and compare it with win probability to make decisions"): the situation in, every choice's
// chance to win out (static/calc_engine.js over data/calc/model.json; (CG) in docs/INSIGHTS.md). Also the gamecast's
// "What should they do?" sheet (NFLE.calcUI.sheet, prefilled from the live situation).
(() => {
  const NFLE = window.NFLE, esc = NFLE.esc;
  const ver = (document.currentScript && new URL(document.currentScript.src).search) || '';
  const KEY = 'nfle-calc';
  const TOSS = 0.0125;  // a gap under 1.25 points is inside the model's noise: a toss-up ((CJ): 20 bootstrap refits)
  const pc = v => `${(100 * v).toFixed(1)}%`;
  const pts = v => `${v >= 0 ? '+' : '−'}${(100 * Math.abs(v)).toFixed(1)}`;
  let ENG = null;
  const engine = () => ENG || (ENG = new Promise((ok, bad) => {
    if (NFLE.calcEngine) { ok(); return; }
    const s = document.createElement('script');
    s.src = new URL(`assets/calc_engine.js${ver}`, NFLE.root).href;
    s.onload = ok; s.onerror = () => bad(new Error('assets/calc_engine.js'));
    document.head.appendChild(s);
  }).then(() => NFLE.load('data/calc/model.json')).then(M => ({ E: NFLE.calcEngine, C: NFLE.calcEngine.createCalc(M), M })));

  const DEF = { mode: 'play', a: 'Offense', b: 'Defense', off: 17, def: 20, qtr: 4, clock: '4:00', down: 4, togo: 3, side: 'opp', yard: 38,
    to: 2, oppTo: 3, line: 0, total: 45, roof: 'outdoors', wind: '', home: 1, rec2h: 0, conv: '', fg: '', pen: { on: 'def', yds: 5, auto: 0, lod: 0, gain: 2 } };
  // the clock as typed: "2:00", or digits only (phones' number pad has no colon), read like a microwave: the last two
  // are seconds ("200" = 2:00, "45" = 0:45, "1500" = 15:00). null if it isn't a quarter's clock.
  const clockOf = v => {
    const t = String(v || '').trim(), m = t.match(/^(\d{1,2}):(\d{2})$/) || (/^\d{1,4}$/.test(t) ? [t, t.slice(0, -2) || '0', t.slice(-2).padStart(2, '0')] : null);
    if (!m) return null;
    const mm = +m[1], ss = +m[2];
    return ss < 60 && mm * 60 + ss <= 900 ? `${mm}:${String(ss).padStart(2, '0')}` : null;
  };
  const saved = () => { try { return JSON.parse(localStorage.getItem(KEY) || 'null'); } catch (e) { return null; } };
  const save = S => { try { localStorage.setItem(KEY, JSON.stringify(S)); } catch (e) { /* private mode */ } };

  // ---- the situation as the engine's state (from the side of the team in the first score row)
  const stateOf = (S, E) => {
    const yl = S.side === 'opp' ? +S.yard : 100 - +S.yard;
    const half = S.qtr <= 2 ? 1 : 2;
    return { diff: +S.off - +S.def, sec: E.gameSec(+S.qtr, S.clock), down: +S.down, togo: Math.min(+S.togo, yl), yl,
             to: +S.to, oppTo: +S.oppTo, line: +S.line || 0, total: +S.total || 45, roof: S.roof, wind: S.wind === '' ? null : +S.wind,
             home: +S.home, rec2h: half === 1 ? +S.rec2h : 0 };
  };

  // ---- controls
  const seg = (k, opts, v) => `<div class="seg cx-seg" data-k="${k}">${opts.map(([val, lab]) => `<button type="button" data-v="${esc(val)}" class="${String(val) === String(v) ? 'on' : ''}">${esc(lab)}</button>`).join('')}</div>`;
  const step = (k, v, lo, hi, lab = '') => `<div class="cx-step" data-k="${k}" data-lo="${lo}" data-hi="${hi}"><button type="button" data-d="-1" aria-label="Less">&minus;</button>`
    + `<input type="tel" inputmode="numeric" value="${esc(v)}" aria-label="${esc(lab || k)}"><button type="button" data-d="1" aria-label="More">+</button></div>`;
  const row = (lab, html, cls = '') => `<div class="cx-row ${cls}"><span class="cx-l">${lab}</span>${html}</div>`;

  function form(S) {
    // real teams when the gamecast filled it in (S.a / S.b), else the roles
    const names = S.a && S.a !== 'Offense' ? [`${S.a}${S.mode === 'ko' ? ' (kicking)' : S.mode === 'td' ? ' (scored)' : ' (ball)'}`, S.b]
      : S.mode === 'td' ? ['Scored', 'Other team'] : S.mode === 'ko' ? ['Kicking', 'Receiving'] : ['Offense', 'Defense'];
    const play = S.mode === 'play';
    return `<div class="cx-form">
      ${seg('mode', [['play', 'Snap'], ['td', 'After a TD'], ['ko', 'Kickoff']], S.mode)}
      <div class="cx-score">
        <label>${names[0]}${step('off', S.off, 0, 99, names[0] + ' points')}</label>
        <label>${names[1]}${step('def', S.def, 0, 99, names[1] + ' points')}</label>
      </div>
      ${row('Quarter', seg('qtr', [[1, '1st'], [2, '2nd'], [3, '3rd'], [4, '4th']], S.qtr))}
      ${row('Clock', `<input type="tel" class="cx-clock" data-k="clock" value="${esc(S.clock)}" inputmode="numeric" aria-label="Clock (m:ss, or digits: 200 = 2:00)" placeholder="m:ss">`)}
      ${play ? row('Down', seg('down', [[1, '1st'], [2, '2nd'], [3, '3rd'], [4, '4th']], S.down)) : ''}
      ${play ? row('To go', step('togo', S.togo, 1, 99, 'Yards to go')) : ''}
      ${play ? row('Ball on', `${seg('side', [['own', 'Own'], ['opp', 'Their']], S.side)}${step('yard', S.yard, 1, 50, 'Yard line')}`) : ''}
      ${row(`${names[0]} TOs`, seg('to', [[0, '0'], [1, '1'], [2, '2'], [3, '3']], S.to))}
      ${row(`${names[1]} TOs`, seg('oppTo', [[0, '0'], [1, '1'], [2, '2'], [3, '3']], S.oppTo))}
      <details class="cx-more"><summary>Teams and weather</summary>
        ${row(`${names[0]} favored by`, step('line', S.line, -30, 30, 'Vegas spread'))}
        ${row('Over / under', step('total', S.total, 25, 70, 'Total points line'))}
        ${row('Roof', seg('roof', [['outdoors', 'Open'], ['dome', 'Dome'], ['retractable', 'Closed']], S.roof))}
        ${S.roof === 'outdoors' ? row('Wind (mph)', step('wind', S.wind === '' ? 8 : S.wind, 0, 40, 'Wind mph')) : ''}
        ${row(`${names[0]} at home`, seg('home', [[1, 'Yes'], [0, 'No']], S.home))}
        ${S.qtr <= 2 ? row(`${names[0]} gets the 2nd-half kickoff`, seg('rec2h', [[1, 'Yes'], [0, 'No']], S.rec2h)) : ''}
      </details>
    </div>`;
  }

  // a decision: options [label, wp, note], best first marked; a toss-up when the top two are within TOSS
  function decision(title, opts, foot = '') {
    const o = opts.filter(x => x && x[1] != null).sort((a, b) => b[1] - a[1]);
    if (!o.length) return '';
    const best = o[0], gap = o[1] ? best[1] - o[1][1] : 1, toss = gap < TOSS;
    const head = toss ? `<b>Toss-up</b> <span class="muted">(${esc(best[0])} vs ${esc(o[1][0])}: ${pts(gap)} pts, inside the model's noise)</span>`
      : `<b>${esc(best[0])}</b> <span class="cx-gain">${pts(gap)} pts</span> <span class="muted">over ${esc(o[1] ? o[1][0].toLowerCase() : '')}</span>`;
    return `<div class="cx-dec"><h3>${esc(title)}</h3><p class="cx-pick">${head}</p>
      ${o.map((x, i) => `<div class="cx-opt${i === 0 && !toss ? ' best' : ''}"><span class="cx-on">${esc(x[0])}</span>
        <span class="cx-bar"><i style="width:${(100 * x[1]).toFixed(1)}%"></i></span><b>${pc(x[1])}</b>
        ${x[2] ? `<span class="cx-note">${x[2]}</span>` : ''}</div>`).join('')}${foot}</div>`;
  }

  // the state after accepting / declining a penalty (s: the offense's state before the snap)
  function penaltyStates(s, P, later) {
    const yds = +P.yds, gain = +P.gain;
    let acc;
    if (P.on === 'def') {  // half the distance to the goal at most
      const y = Math.min(yds, Math.floor(s.yl / 2) || 1), yl = s.yl - y, first = P.auto || y >= s.togo;
      acc = later({ ...s, yl, down: first ? 1 : s.down, togo: first ? Math.min(10, yl) : s.togo - y }, 5);
    } else {
      const y = Math.min(yds, Math.floor((100 - s.yl) / 2) || 1), yl = s.yl + y;
      acc = later({ ...s, yl, down: Math.min(4, s.down + (P.lod ? 1 : 0)), togo: s.togo + y }, 5);
    }
    // declined: the play stands
    const yl = s.yl - gain;
    let dec;
    if (gain >= s.yl) dec = { td: true };
    else if (gain >= s.togo) dec = later({ ...s, yl, down: 1, togo: Math.min(10, yl) }, 5);
    else if (s.down === 4) dec = { downs: true, yl: Math.min(99, Math.max(1, 100 - yl)) };
    else dec = later({ ...s, yl, down: s.down + 1, togo: s.togo - gain }, 5);
    return { acc, dec };
  }

  function results(S, eng) {
    const { E, C } = eng, s = stateOf(S, E), out = [];
    const now = `<div class="cx-now"><span>${S.mode === 'ko' ? 'Kicking team' : S.mode === 'td' ? 'Scoring team' : 'Offense'} win chance now</span><b>${pc(C.wp({ ...s, down: S.mode === 'play' ? s.down : 1, togo: S.mode === 'play' ? s.togo : 10, yl: S.mode === 'play' ? s.yl : 75 }))}</b></div>`;
    if (S.mode === 'play') {
      if (s.down === 4) {
        const opt = { conv: S.conv !== '' ? +S.conv / 100 : null, fg: S.fg !== '' ? +S.fg / 100 : null };
        const f = C.fourth(s, opt);
        out.push(decision('4th down', [
          ['Go for it', f.go.wp, `${pc(f.go.p)} to convert: ${pc(f.go.ifMade)} to win if it works, ${pc(f.go.ifMissed)} if it fails`],
          f.fg ? ['Field goal', f.fg.wp, `${f.fg.dist} yd, ${pc(f.fg.p)} to make: ${pc(f.fg.ifMade)} to win if good, ${pc(f.fg.ifMissed)} if missed${f.fg.rare ? ' (few kicks this long on record)' : ''}`] : null,
          f.punt ? ['Punt', f.punt.wp, `their ball near their ${Math.round(100 - f.punt.net)}`] : null,
        ], `<div class="cx-edit"><label>Convert %<input type="tel" data-k="conv" inputmode="decimal" placeholder="${(100 * f.go.p).toFixed(0)}" value="${esc(S.conv)}"></label>
          ${f.fg ? `<label>Field goal %<input type="tel" data-k="fg" inputmode="decimal" placeholder="${(100 * f.fg.p).toFixed(0)}" value="${esc(S.fg)}"></label>` : ''}
          <span class="muted">Your offense or kicker: change the rate.</span></div>`));
      }
      // timeouts: for the clock only, and only where the clock is worth something (owner 2026-10-23: "there's lots of
      // reasons to call timeouts beyond clock management": personnel, a delay of game, a challenge, icing a kicker)
      const half = s.sec > 1800 ? s.sec - 1800 : s.sec;
      if (half <= 300) {
        const why = '<p class="cx-foot">For the clock only. A timeout can be right for other reasons: the wrong personnel, a play clock about to run out, a challenge, icing a kicker. How much clock a snap takes here is measured from games in this situation.</p>';
        const ot = C.timeout(s, 'offense'), dt = C.timeout(s, 'defense');
        out.push(decision(`Timeout for the clock (${S.a && S.a !== 'Offense' ? S.a : 'offense'})`, ot.can ? [['Call it', ot.call.wp], [`Let ${Math.round(ot.run.seconds)} s run`, ot.run.wp]] : [['No timeouts left', null]], why));
        out.push(decision(`Timeout for the clock (${S.b && S.b !== 'Defense' ? S.b : 'defense'})`, dt.can ? [['Call it', dt.call.wp], [`Let ${Math.round(dt.run.seconds)} s run`, dt.run.wp]] : [['No timeouts left', null]]));
      } else out.push('<div class="cx-dec cx-quiet"><h3>Timeouts</h3><p class="cx-foot">More than 5:00 left in the half: a timeout is worth almost nothing for the clock here; teams call them for personnel, the play clock or a challenge. No verdict.</p></div>');
      // penalty
      const P = S.pen, st = penaltyStates(s, P, C.later);
      const chooser = P.on === 'def' ? 'offense' : 'defense', mine = v => (chooser === 'offense' ? v : 1 - v);
      const wpOf = x => (x.td ? null : x.downs ? 1 - C.wp(C.later({ ...C.flip(s), down: 1, togo: 10, yl: x.yl }, 5)) : C.wp(x));
      const tdWp = () => { const t = C.tries({ ...s, diff: s.diff + 6, sec: s.sec - 5 }); return Math.max(t.xp.wp, t.two.wp); };
      const acc = mine(wpOf(st.acc)), dec = st.dec.td ? mine(tdWp()) : mine(wpOf(st.dec));
      out.push(decision(`Penalty: ${chooser === 'offense' ? 'offense' : 'defense'} chooses`, [['Accept', acc], ['Decline', dec]],
        `<div class="cx-pen">${row('Flag on', seg('pen.on', [['def', 'Defense'], ['off', 'Offense']], P.on))}
          ${row('Yards', seg('pen.yds', [[5, '5'], [10, '10'], [15, '15']], P.yds))}
          ${P.on === 'def' ? row('Automatic 1st down', seg('pen.auto', [[1, 'Yes'], [0, 'No']], P.auto)) : row('Loss of down', seg('pen.lod', [[1, 'Yes'], [0, 'No']], P.lod))}
          ${row('If declined, the play gained', step('pen.gain', P.gain, -30, 99, 'Yards gained on the play'))}</div>`));
    } else if (S.mode === 'td') {
      const t = C.tries({ ...s, down: 1, togo: 10, yl: 75 });
      out.push(decision('The try', [['Kick the extra point', t.xp.wp, `${pc(t.xp.p)} good`], ['Go for two', t.two.wp, `${pc(t.two.p)} converted`]],
        '<p class="cx-foot">The score with the touchdown\'s six already counted.</p>'));
    } else {
      const o = C.onside({ ...s, down: 1, togo: 10, yl: 75 });
      out.push(decision('The kickoff', [['Kick it deep', o.kick.wp], ['Onside kick', o.onside.wp, `${pc(o.onside.p)} recovered (2024 kickoff rules on)`]]));
    }
    const m = eng.M, half = s.sec > 1800 ? s.sec - 1800 : s.sec;
    // a half's last 3:00: the general model misses the two-minute drill's tied-with-the-ball spots by ~10 points, and a
    // drive model built for it did no better ((CH), docs/INSIGHTS.md)
    const rough = half <= 180 ? '<p class="cx-rough">Last 3:00 of a half: rough. Our model (like the public ones) under-reads late tied games with the ball by about 10 points; a two-minute-drill model we built to fix it did no better.</p>' : '';
    return `${now}${rough}${out.join('')}<p class="cx-src muted">Our win probability model, trained on every regulation play ${m.seasons[0]}-${m.seasons[1]}; regulation only (overtime's rules changed in 2022 and 2025). Each choice: the chance of each outcome times the win chance after it. Not for betting.</p>`;
  }

  function mountInto(box, S0, opts = {}) {
    let S = { ...DEF, ...(S0 || {}), pen: { ...DEF.pen, ...((S0 || {}).pen || {}) } };
    box.innerHTML = '<div class="cx"><div class="cx-in"></div><div class="cx-out"><p class="muted">Loading the model&hellip;</p></div></div>';
    const inBox = box.querySelector('.cx-in'), outBox = box.querySelector('.cx-out');
    let eng = null;
    const set = (k, v) => { if (k.startsWith('pen.')) S.pen = { ...S.pen, [k.slice(4)]: v }; else S = { ...S, [k]: v }; };
    const draw = (redrawForm = true) => {
      if (redrawForm) inBox.innerHTML = form(S);
      if (eng) { try { outBox.innerHTML = results(S, eng); } catch (e) { outBox.innerHTML = `<p class="muted">Couldn't compute this (${esc(e.message)}).</p>`; } }
      if (!opts.noSave) save(S);
    };
    box.addEventListener('click', e => {
      const b = e.target.closest('.cx-seg button');
      if (b) { set(b.closest('.cx-seg').dataset.k, isNaN(+b.dataset.v) ? b.dataset.v : +b.dataset.v); draw(); return; }
      const d = e.target.closest('.cx-step button');
      if (d) { const w = d.closest('.cx-step'), i = w.querySelector('input'), v = Math.max(+w.dataset.lo, Math.min(+w.dataset.hi, (+i.value || 0) + +d.dataset.d));
        set(w.dataset.k, v); i.value = v; draw(false); }
    });
    box.addEventListener('input', e => {
      const i = e.target;
      if (i.closest('.cx-out')) return;  // fields in the results update on change (a redraw would drop the focus)
      if (i.matches('.cx-step input')) { const w = i.closest('.cx-step'); if (i.value !== '' && !isNaN(+i.value)) { set(w.dataset.k, Math.max(+w.dataset.lo, Math.min(+w.dataset.hi, +i.value))); draw(false); } }
      else if (i.dataset.k === 'clock') { const c = clockOf(i.value); if (c) { set('clock', c); draw(false); } }
      else if (i.dataset.k === 'conv' || i.dataset.k === 'fg') { set(i.dataset.k, i.value === '' || isNaN(+i.value) ? '' : Math.max(0, Math.min(100, +i.value))); draw(false); }
    });
    inBox.addEventListener('change', e => { if (e.target.dataset && e.target.dataset.k === 'clock') e.target.value = S.clock; });
    // fields in the results (rates, the penalty's yards): on change, then redraw the results
    outBox.addEventListener('change', e => {
      const i = e.target;
      if (i.matches('.cx-step input')) { const w = i.closest('.cx-step'); if (!isNaN(+i.value)) set(w.dataset.k, Math.max(+w.dataset.lo, Math.min(+w.dataset.hi, +i.value))); }
      else if (i.dataset.k === 'conv' || i.dataset.k === 'fg') set(i.dataset.k, i.value === '' || isNaN(+i.value) ? '' : Math.max(0, Math.min(100, +i.value)));
      draw(false);
    });
    draw();
    engine().then(e => { eng = e; draw(false); }, err => { outBox.innerHTML = `<p class="muted">The calculator's model isn't available (${esc(err.message)}).</p>`; });
  }

  // ---- Graded calls (owner 2026-10-23: "default it to sort by most controversial (worst compared to our model) and
  // group the tables by week and season"): every 4th down from 2022 on, graded at build time by tools/calc_grade.mjs
  // with this engine and a model fit only on earlier seasons (data/calc/graded_<season>.json)
  const QUESTION = 0.03;  // the engine's "questionable" line (3 points)
  const CALL = { go: 'Went for it', fg: 'Field goal', punt: 'Punted' }, OPT = { go: 'going for it', fg: 'a field goal', punt: 'a punt' };
  const OPTS = { go: 'Going for it', fg: 'A field goal', punt: 'A punt' };
  const OPTL = { go: 'Go for it', fg: 'Field goal', punt: 'Punt' };
  const clockAt = sec => { const q = sec > 2700 ? 1 : sec > 1800 ? 2 : sec > 900 ? 3 : 4, r = Math.round(sec - (4 - q) * 900);
    return { q, clock: `${Math.floor(r / 60)}:${String(r % 60).padStart(2, '0')}` }; };
  const scoreTxt = d => (d > 0 ? `up ${d}` : d < 0 ? `down ${-d}` : 'tied');
  const spotTxt = yl => (yl > 50 ? `own ${100 - yl}` : yl === 50 ? 'midfield' : `opp ${yl}`);
  const gradedState = r => { const { q, clock } = clockAt(r.s), off = r.sc ? r.sc[0] : Math.max(0, 20 + r.d);
    return { ...DEF, mode: 'play', a: r.t, b: r.o, off, def: off - r.d, qtr: q, clock, down: 4, togo: r.tg, side: r.yl > 50 ? 'own' : 'opp',
      yard: r.yl > 50 ? 100 - r.yl : r.yl, to: r.to, oppTo: r.ot, line: r.ln || 0, total: r.tt || 45, roof: r.rf || 'outdoors',
      wind: r.wd == null ? '' : r.wd, home: r.h, rec2h: r.r2 }; };

  function gradedRow(r, i) {
    const { q, clock } = clockAt(r.s), bad = r.x >= QUESTION, close = r.x < TOSS;
    const verdict = r.b === r.c ? '<span class="gc-ok">Right call</span>'
      : close ? `<span class="muted">Toss-up with ${OPT[r.b]}</span>`
      : `<span class="${bad ? 'gc-bad' : 'gc-meh'}">${OPTS[r.b]} was better by ${(100 * r.x).toFixed(1)} pts</span>`;
    const res = r.res > 0 ? '<b class="gc-w">W</b>' : r.res < 0 ? '<b class="gc-l">L</b>' : '<b>T</b>';
    const opts = Object.entries(r.op).filter(([, v]) => v != null).sort((a, b) => b[1] - a[1]);
    const br = [r.pc != null ? `Go: ${pc(r.pc)} to convert, then ${pc(r.gm)} to win; ${pc(r.gf)} if it fails` : '',
      r.pf != null && r.op.fg != null ? `Field goal: ${pc(r.pf)} to make, then ${pc(r.fm)}; ${pc(r.ff)} if missed` : ''].filter(Boolean).join('<br>');
    const happened = r.c === 'go' ? (r.cv ? 'converted' : 'failed') : r.c === 'fg' ? (r.cv ? 'good' : 'missed') : '';
    return `<details class="gc-row${bad && r.b !== r.c ? ' bad' : ''}"><summary>
        <span class="gc-who"><b>${esc(r.t)}</b> ${r.h ? 'vs' : '@'} ${esc(r.o)}</span><span class="gc-res">${res}</span>
        <span class="gc-sit">Q${q} ${clock} · ${scoreTxt(r.d)} · 4th &amp; ${r.tg}, ${spotTxt(r.yl)} · TOs ${r.to}-${r.ot}</span>
        <span class="gc-v">${esc(CALL[r.c])}${happened ? ` (${happened})` : ''} · ${verdict}</span></summary>
      <div class="gc-more">
        ${opts.map(([k, v]) => `<div class="cx-opt${k === r.b ? ' best' : ''}"><span class="cx-on">${esc(OPTL[k])}${k === r.c ? ' (their call)' : ''}</span>
          <span class="cx-bar"><i style="width:${(100 * v).toFixed(1)}%"></i></span><b>${pc(v)}</b></div>`).join('')}
        ${br ? `<p class="cx-foot">${br}</p>` : ''}
        <p class="gc-desc">${esc(r.ds || '')}</p>
        <button type="button" class="gc-btn gc-open" data-i="${i}">Open in the calculator</button>
      </div></details>`;
  }

  function mountGraded(box) {
    const st = { season: null, sort: 'worst', team: '', open: {} };
    let idx = null, data = null, rows = [];
    box.innerHTML = '<p class="muted">Loading graded calls&hellip;</p>';
    const draw = () => {
      if (!idx) return;
      const seasons = idx.seasons.map(x => x.season).sort((a, b) => b - a);
      const meta = idx.seasons.find(x => x.season === st.season) || {};
      const teams = data ? [...new Set(data.rows.map(r => r.t))].sort() : [];
      rows = data ? data.rows.filter(r => !st.team || r.t === st.team) : [];
      const byWeek = {};
      rows.forEach((r, i) => { (byWeek[r.w] = byWeek[r.w] || []).push(i); });
      const order = st.sort === 'worst' ? (a, b) => rows[b].x - rows[a].x || rows[a].s - rows[b].s
        : (a, b) => (rows[a].g < rows[b].g ? -1 : rows[a].g > rows[b].g ? 1 : rows[b].s - rows[a].s);
      const weeks = Object.keys(byWeek).map(Number).sort((a, b) => b - a);
      const SHOW = 5;
      const body = !data ? '<p class="muted">Loading&hellip;</p>' : !rows.length ? '<p class="muted">No 4th downs for this pick.</p>'
        : weeks.map(w => {
          const ix = byWeek[w].sort(order), nq = ix.filter(i => rows[i].x >= QUESTION && rows[i].b !== rows[i].c).length;
          const all = st.open[w] || st.team, shown = all ? ix : ix.slice(0, SHOW);
          return `<section class="gc-week"><h3>Week ${w} <span class="muted">${ix.length} fourth down${ix.length === 1 ? '' : 's'}${nq ? ` · <b class="gc-bad">${nq} questionable</b>` : ''}</span></h3>
            ${shown.map(i => gradedRow(rows[i], i)).join('')}
            ${!all && ix.length > SHOW ? `<button type="button" class="gc-btn gc-all" data-w="${w}">Show all ${ix.length}</button>` : ''}</section>`;
        }).join('');
      box.innerHTML = `<div class="gc-ctl">
          ${seg('season', seasons.map(s => [s, String(s)]), st.season)}
          ${seg('sort', [['worst', 'Most controversial'], ['game', 'Game order']], st.sort)}
          <select class="gc-team" aria-label="Team"><option value="">All teams</option>${teams.map(t => `<option${t === st.team ? ' selected' : ''}>${esc(t)}</option>`).join('')}</select>
        </div>
        <p class="cx-src muted">${meta.n ? `${meta.n.toLocaleString()} fourth downs, ${meta.flagged} questionable (${100 * QUESTION}+ pts of win chance worse than the best). ` : ''}Graded by a model trained only on seasons before ${st.season}. A right call can still lose.</p>
        ${body}`;
    };
    const loadSeason = s => {
      st.season = s; st.open = {}; data = null; draw();
      NFLE.load(`data/calc/graded_${s}.json`).then(d => { if (st.season === s) { data = d; draw(); } },
        () => { box.insertAdjacentHTML('beforeend', `<p class="muted">Couldn't load ${s}.</p>`); });
    };
    box.addEventListener('click', e => {
      const b = e.target.closest('.cx-seg button');
      if (b) { const k = b.closest('.cx-seg').dataset.k;
        if (k === 'season') loadSeason(+b.dataset.v); else { st.sort = b.dataset.v; draw(); }
        return; }
      const a = e.target.closest('.gc-all');
      if (a) { st.open[a.dataset.w] = 1; draw(); return; }
      const o = e.target.closest('.gc-open');
      if (o) { const r = rows[+o.dataset.i]; if (r) NFLE.calcUI.sheet(gradedState(r), `${r.t} ${r.h ? 'vs' : '@'} ${r.o}, week ${r.w}`); }
    });
    box.addEventListener('change', e => { if (e.target.matches('.gc-team')) { st.team = e.target.value; draw(); } });
    NFLE.load('data/calc/graded.json').then(j => {
      idx = j;
      const s = Math.max(...j.seasons.map(x => x.season));
      loadSeason(s);
    }, () => { box.innerHTML = '<p class="muted">The graded calls aren\'t available yet.</p>'; });
  }

  NFLE.calcUI = {
    engine,  // the engine + model, loaded once (the gamecast's Decisions pane grades with it)
    // a sheet over the gamecast, prefilled from a live situation
    sheet(S0, title = 'What should they do?') {
      const box = document.createElement('div');
      mountInto(box, S0, { noSave: true });
      if (NFLE.sheet) NFLE.sheet(title, box);
    },
  };
  NFLE.areas.calc = {
    mount(sec) {
      sec.classList.remove('soon');
      // two views (owner 2026-10-23): every real 4th down graded (the default) and the calculator
      sec.innerHTML = `<div class="sec-head"><div><h2>Calc</h2><p>Every 4th down graded by our win probability model, or set your own situation.</p></div></div>
        ${seg('view', [['graded', 'Graded calls'], ['calc', 'Calculator']], 'graded')}<div class="gc-host"></div><div class="cx-host" hidden></div>`;
      const g = sec.querySelector('.gc-host'), c = sec.querySelector('.cx-host'), tabs = sec.querySelector('.cx-seg[data-k="view"]');
      let calcOn = false;
      mountGraded(g);
      tabs.addEventListener('click', e => {
        const b = e.target.closest('button');
        if (!b) return;
        tabs.querySelectorAll('button').forEach(x => x.classList.toggle('on', x === b));
        const calc = b.dataset.v === 'calc';
        g.hidden = calc; c.hidden = !calc;
        if (calc && !calcOn) { calcOn = true; mountInto(c, saved()); }
      });
    },
  };
})();
