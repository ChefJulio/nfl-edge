// Players > Trends engine: the definitions (measures, filters, breakdowns), the data loading and the counting behind
// the Trends page, with nothing about the page in it, so the page (static/trends.js) and the command line
// (tools/trends_cli.mjs: answers for scripts and LLMs) count the same way. createEngine(load): load(path) resolves a
// parsed JSON file under the site root (data/plays/..., built by tools/trends_build.py). Browser: NFLE.trendsEngine;
// Node: module.exports. Audited against nflverse's season totals by tools/trends_audit.py (docs/trends_audit.md).
(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory;
  else (root.NFLE = root.NFLE || {}).trendsEngine = factory;
})(typeof self !== 'undefined' ? self : globalThis, function createEngine(load) {
  'use strict';
  // columns that live in <season>_x.json (participation + FTN charting): loaded only when a query needs one
  const XCOLS = new Set(['fm', 'op', 'db', 'bx', 'pr', 'tt', 'pz', 'mz', 'cv', 'rt', 'mo', 'px', 'sc', 'rp', 'tr', 'oo', 'iw', 'ta', 'cb', 'ct', 'dr', 'cr', 'bl', 'bf', 'rd']);
  const CNAME = { ay: 'air yards', yc: 'YAC', pl: 'pass location', rl: 'run direction', gp: 'run gap', cp: 'completion probability', xp: 'expected pass rate',
    xy: 'expected YAC', wp: 'win probability', wa: 'WPA', fm: 'QB alignment', op: 'personnel', db: 'defensive personnel', bx: 'box count', pr: 'pass rushers',
    tt: 'time to throw', pz: 'pressure', mz: 'man / zone', cv: 'coverage shell', rt: 'routes', mo: 'motion', px: 'play action', sc: 'screens', rp: 'RPOs',
    tr: 'trick plays', oo: 'pocket', iw: 'INT-worthy throws', ta: 'throwaways', cb: 'catchable balls', ct: 'contested balls', dr: 'drops',
    cr: 'created receptions', bl: 'blitzers', bf: 'backfield', rd: 'reads' };
  const FLAGS = ['tl', 'qh', 'pz', 'iw', 'ta', 'oo', 'px', 'mo', 'dr', 'cb', 'ct', 'cr', 'sg', 'nh', 'sc', 'rp'];
  // ---- metrics: [label, value from the sums, decimals, columns needed]
  // yards and touchdowns are the credited ones where the season file has them (v6: yru / yre / ypa, tdr / tdv / tdq /
  // tdo; official-stat rules), else the play's (older files)
  const rate = c => a => 100 * a[c + 'n'] / a[c + 'd'];
  const FAM = {
    rush: { label: 'Rushing', unit: 'rushes', min: 20, play: (P, j) => P.ty[j] !== 1, actor: (P, j) => P.ru[j],
      add: (a, P, j) => { const y = P.yru ? P.yru[j] : P.y[j]; a.y += y; a.td += P.tdr ? P.tdr[j] : P.td[j]; a.fd += P.fd[j]; a.x += y >= 10; a.fl += P.fl[j]; },
      lat: (P, j) => (P.lu ? P.lu[j] : -1), latAdd: (a, P, j) => { a.y += P.luy[j]; a.td += P.ltd[j]; },
      met: { ypc: ['YPC', a => a.y / a.n, 2], yds: ['Yards', a => a.y, 0], att: ['Rushes', a => a.n, 0], td: ['TDs', a => a.td, 0],
             epa: ['EPA / rush', a => a.e / 100 / a.n, 3], sr: ['Success %', a => 100 * a.s / a.n, 1], fd: ['1st down %', a => 100 * a.fd / a.n, 1],
             x: ['10+ yd %', a => 100 * a.x / a.n, 1], stuff: ['Stuffed %', rate('tl'), 1], fl: ['Fumbles lost', a => a.fl, 0],
             wpa: ['WPA', a => a.wa / 1000, 2, ['wa']] } },
    pass: { label: 'Passing', unit: 'dropbacks', min: 50, play: (P, j) => P.ty[j] === 1, actor: (P, j) => P.pp[j],
      add: (a, P, j) => { const sk = P.sk[j], att = P.pa[j] && !sk; a.att += att; a.c += P.c[j]; a.y += sk ? 0 : P.ypa ? P.ypa[j] : P.y[j]; a.td += P.tdq ? P.tdq[j] : P.td[j] && P.c[j];
        a.int += P.in[j]; a.sk += sk; if (att && P.ay[j] > -99) { a.ay += P.ay[j]; a.ayn++; } if (att && P.cp[j] > -999) { a.cp += P.cp[j]; a.cpn++; }
        if (P.tt && P.tt[j] >= 0) { a.tt += P.tt[j]; a.ttn++; } },
      met: { ypa: ['Yds / att', a => a.y / a.att, 2], cmp: ['Comp %', a => 100 * a.c / a.att, 1], yds: ['Yards', a => a.y, 0], td: ['TDs', a => a.td, 0],
             int: ['INTs', a => a.int, 0], epa: ['EPA / dropback', a => a.e / 100 / a.n, 3], sr: ['Success %', a => 100 * a.s / a.n, 1],
             skr: ['Sack %', a => 100 * a.sk / a.n, 1], att: ['Attempts', a => a.att, 0], adot: ['Air yds / att', a => a.ay / a.ayn, 1, ['ay']],
             cpoe: ['CPOE', a => a.cp / 10 / a.cpn, 1, ['cp']], pz: ['Pressure %', rate('pz'), 1, ['pz']], tt: ['Time to throw', a => a.tt / 10 / a.ttn, 2, ['tt']],
             qh: ['QB hit %', rate('qh'), 1], iw: ['INT-worthy %', rate('iw'), 1, ['iw']], ta: ['Throwaway %', rate('ta'), 1, ['ta']],
             oo: ['Out of pocket %', rate('oo'), 1, ['oo']], px: ['Play action %', rate('px'), 1, ['px']], wpa: ['WPA', a => a.wa / 1000, 2, ['wa']] } },
    rec: { label: 'Receiving', unit: 'targets', min: 15, play: (P, j) => P.ty[j] === 1 && P.re[j] >= 0, actor: (P, j) => P.re[j],
      lat: (P, j) => (P.lv ? P.lv[j] : -1), latAdd: (a, P, j) => { a.y += P.lvy[j]; a.td += P.ltd[j]; },
      add: (a, P, j) => { const c = P.c[j]; a.c += c; a.y += c ? (P.yre ? P.yre[j] : P.y[j]) : 0; a.td += P.tdv ? P.tdv[j] : P.td[j] && c;
        if (c && P.yc[j] > -99) { a.yac += P.yc[j]; a.ycn++; if (P.xy[j] > -999) { a.yo += P.yc[j] - P.xy[j] / 10; a.yon++; } }
        if (P.ay[j] > -99) { a.ay += P.ay[j]; a.ayn++; } if (P.cp[j] > -999) { a.cp += P.cp[j]; a.cpn++; }
        if (P.ct && P.ct[j] === 1) { a.ctt++; a.ctc += c; } },
      met: { ypt: ['Yds / target', a => a.y / a.n, 2], yds: ['Yards', a => a.y, 0], rec: ['Catches', a => a.c, 0], tgt: ['Targets', a => a.n, 0],
             cr: ['Catch %', a => 100 * a.c / a.n, 1], td: ['TDs', a => a.td, 0], yac: ['YAC / catch', a => a.yac / a.ycn, 1, ['yc']],
             adot: ['aDOT', a => a.ay / a.ayn, 1, ['ay']], epa: ['EPA / target', a => a.e / 100 / a.n, 3], sr: ['Success %', a => 100 * a.s / a.n, 1],
             croe: ['Catch % over exp.', a => a.cp / 10 / a.cpn, 1, ['cp']], yacoe: ['YAC over exp.', a => a.yo / a.yon, 2, ['xy']],
             drop: ['Drop %', rate('dr'), 1, ['dr']], cb: ['Catchable %', rate('cb'), 1, ['cb']], ctr: ['Contested %', rate('ct'), 1, ['ct']],
             ctc: ['Contested catch %', a => 100 * a.ctc / a.ctt, 1, ['ct'], ['Contested targets', a => a.ctt]], crt: ['Created catch %', rate('cr'), 1, ['cr']],
             wpa: ['WPA', a => a.wa / 1000, 2, ['wa']] } },
    // owner 2026-10-22 ("snap-level with/without and per-route stats"): needs <season>_on.json (participation, 2016-2025).
    // A route = a dropback (incl. sacks, scrambles) with the player on the field as a WR / TE / RB / FB: blocking snaps
    // can't be told apart, so TE and RB routes run high. multi: actors() gives every route runner; PL is the on-field list.
    route: { label: 'Routes', unit: 'routes', min: 50, on: true, multi: true, play: (P, j) => P.ty[j] !== 0, actor: (P, j) => P.re[j],
      actors: (P, j, D) => (D.on.rr[j] || []),
      add: (a, P, j, act, D) => { if (act == null) return; const t = P.re[j] >= 0 && D.players[P.re[j]][0] === D.on.pl[act][0];
        if (t) { a.tg = (a.tg || 0) + 1; const c = P.c[j]; a.c += c; a.y += c ? (P.yre ? P.yre[j] : P.y[j]) : 0; a.td += P.tdv ? P.tdv[j] : P.td[j] && c; } },
      met: { yprr: ['Yds / route', a => a.y / a.n, 2], tprr: ['Targets / route %', a => (100 * (a.tg || 0)) / a.n, 1], rr: ['Routes', a => a.n, 0],
             tgt: ['Targets', a => a.tg || 0, 0], yds: ['Yards', a => a.y, 0], rec: ['Catches', a => a.c, 0], td: ['TDs', a => a.td, 0] } },
    team: { label: 'Team offense', unit: 'plays', min: 50, play: () => true, actor: (P, j) => P.o[j], teamActor: true,
      add: (a, P, j) => { const db = P.ty[j] !== 0; a.y += P.y[j]; a.db += db; a.td += P.tdo ? P.tdo[j] : P.td[j]; a.fd += P.fd[j];
        if (P.xp[j] >= 0) { a.xo += db - P.xp[j] / 100; a.xon++; } },
      met: { epa: ['EPA / play', a => a.e / 100 / a.n, 3], ypp: ['Yds / play', a => a.y / a.n, 2], sr: ['Success %', a => 100 * a.s / a.n, 1],
             pr: ['Dropback %', a => 100 * a.db / a.n, 1], proe: ['Pass rate over exp.', a => 100 * a.xo / a.xon, 1, ['xp']],
             fd: ['1st down %', a => 100 * a.fd / a.n, 1], plays: ['Plays', a => a.n, 0], td: ['TDs', a => a.td, 0], sg: ['Shotgun %', rate('sg'), 1],
             nh: ['No-huddle %', rate('nh'), 1], px: ['Play action %', rate('px'), 1, ['px']], mo: ['Motion %', rate('mo'), 1, ['mo']],
             wpa: ['WPA', a => a.wa / 1000, 2, ['wa']] } },
  };
  // Special teams (<season>_st.json): every column from the kicking team's side; return families read the same plays
  // from the receiving team's side (side 'r': the view flips team, score, win probability and EPA; loadSeason).
  const retMet = { avg: ['Yds / return', a => a.ry / a.n, 1], yds: ['Return yards', a => a.ry, 0], ret: ['Returns', a => a.n, 0],
    td: ['TDs', a => a.td, 0], long: ['Long', a => a.lg, 0], x40: ['40+ yd returns', a => a.x40, 0], fl: ['Fumbles lost', a => a.fl, 0],
    epa: ['EPA / return', a => a.e / 100 / a.n, 3] };
  const retAdd = (a, P, j) => { const y = P.ry[j]; a.ry += y; a.td += P.td[j]; a.x40 += y >= 40; a.fl += P.fl[j]; if (y > a.lg) a.lg = y; };
  Object.assign(FAM, {
    fg: { label: 'Field goals', unit: 'attempts', min: 5, st: 'k', play: (P, j) => P.t[j] === 2, actor: (P, j) => P.kp[j],
      add: (a, P, j) => { const d = P.kd[j], mk = P.mk[j]; a.mk += mk; a.kd += d; a.f50 += d >= 50; a.m50 += d >= 50 && mk; if (mk && d > a.lg) a.lg = d; },
      met: { pct: ['FG %', a => 100 * a.mk / a.n, 1], made: ['Made', a => a.mk, 0], att: ['Attempts', a => a.n, 0], long: ['Long', a => a.lg, 0],
             avgd: ['Avg distance', a => a.kd / a.n, 1], m50: ['Made 50+', a => a.m50, 0], p50: ['50+ %', a => 100 * a.m50 / a.f50, 1, null, ['50+ attempts', a => a.f50]],
             epa: ['EPA / kick', a => a.e / 100 / a.n, 3] } },
    xp: { label: 'Extra points', unit: 'attempts', min: 10, st: 'k', play: (P, j) => P.t[j] === 3, actor: (P, j) => P.kp[j],
      add: (a, P, j) => { a.mk += P.mk[j]; },
      met: { pct: ['XP %', a => 100 * a.mk / a.n, 1], made: ['Made', a => a.mk, 0], att: ['Attempts', a => a.n, 0], miss: ['Missed', a => a.n - a.mk, 0] } },
    punt: { label: 'Punting', unit: 'punts', min: 10, st: 'k', play: (P, j) => P.t[j] === 1, actor: (P, j) => P.kp[j],
      add: (a, P, j) => { const d = Math.max(0, P.kd[j]); a.kd += d; a.net += d - P.ry[j] - 20 * P.tb[j]; a.i20 += P.i20[j]; a.tb += P.tb[j];
        a.fc += P.fc[j]; a.rt += P.rt[j]; a.ry += P.ry[j]; a.bk += P.bk[j]; if (d > a.lg) a.lg = d; },
      met: { net: ['Net avg', a => a.net / a.n, 1], gross: ['Gross avg', a => a.kd / a.n, 1], i20: ['Inside 20 %', a => 100 * a.i20 / a.n, 1],
             tbr: ['Touchback %', a => 100 * a.tb / a.n, 1], fcr: ['Fair catch %', a => 100 * a.fc / a.n, 1], rya: ['Return yds allowed / punt', a => a.ry / a.n, 1],
             punts: ['Punts', a => a.n, 0], long: ['Long', a => a.lg, 0], bk: ['Blocked', a => a.bk, 0], epa: ['EPA / punt', a => a.e / 100 / a.n, 3] } },
    ko: { label: 'Kickoffs', unit: 'kickoffs', min: 10, st: 'k', play: (P, j) => P.t[j] === 0, actor: (P, j) => P.kp[j],
      add: (a, P, j) => { a.kd += Math.max(0, P.kd[j]); a.tb += P.tb[j]; a.rt += P.rt[j]; a.ry += P.rt[j] ? P.ry[j] : 0; },
      met: { tbr: ['Touchback %', a => 100 * a.tb / a.n, 1], avgd: ['Avg distance', a => a.kd / a.n, 1], retr: ['Returned %', a => 100 * a.rt / a.n, 1],
             rya: ['Return yds allowed / return', a => a.ry / a.rt, 1], kicks: ['Kickoffs', a => a.n, 0], epa: ['EPA / kickoff', a => a.e / 100 / a.n, 3] } },
    kr: { label: 'Kick returns', unit: 'returns', min: 8, st: 'r', play: (P, j) => P.t[j] === 0 && P.rt[j] === 1, actor: (P, j) => P.rp[j], add: retAdd, met: retMet },
    pr: { label: 'Punt returns', unit: 'returns', min: 8, st: 'r', play: (P, j) => P.t[j] === 1 && P.rt[j] === 1, actor: (P, j) => P.rp[j], add: retAdd, met: retMet },
  });
  const FIRST = { rush: 'ypc', pass: 'epa', rec: 'ypt', route: 'yprr', team: 'epa', fg: 'pct', xp: 'pct', punt: 'net', ko: 'tbr', kr: 'avg', pr: 'avg' };
  const COUNT = { att: 1, tgt: 1, plays: 1, punts: 1, kicks: 1, ret: 1, rr: 1 };  // metrics equal to the sample column: not repeated as extras
  const blank = () => { const a = { n: 0, y: 0, td: 0, e: 0, s: 0, fd: 0, x: 0, fl: 0, att: 0, c: 0, int: 0, sk: 0, ay: 0, ayn: 0, yac: 0, ycn: 0, db: 0,
    cp: 0, cpn: 0, tt: 0, ttn: 0, yo: 0, yon: 0, xo: 0, xon: 0, ctt: 0, ctc: 0, wa: 0, mk: 0, kd: 0, lg: 0, f50: 0, m50: 0, net: 0, i20: 0,
    tb: 0, fc: 0, rt: 0, ry: 0, x40: 0, bk: 0 }; FLAGS.forEach(c => { a[c + 'n'] = 0; a[c + 'd'] = 0; }); return a; };
  const common = (a, P, j) => {
    if (!P.s) { a.n++; a.e += P.e[j]; return; }  // special teams: no success / WPA / charting columns
    a.n++; a.e += P.e[j]; a.s += P.s[j]; a.wa += P.wa[j];
    for (let k = 0; k < FLAGS.length; k++) { const col = P[FLAGS[k]]; if (col) { const v = col[j]; if (v >= 0) { a[FLAGS[k] + 'd']++; a[FLAGS[k] + 'n'] += v === 1; } } }
  };

  // ---- filters: { label, group, need, only (families), opts: [value, label, test(P, j, G, V)] }; V = the season's vocabularies
  const vt = (c, label) => (P, j, G, V) => !!V[c] && V[c][P[c][j] - 1] === label;
  const eq = (c, v) => (P, j) => P[c][j] === v;
  const gm = (P, j, G) => G[P.g[j]];
  const offFav = (P, j, G) => { const g = gm(P, j, G); return g[9] === -999 ? null : (g[3] === P.o[j] ? g[9] : -g[9]); };
  const PASSY = ['pass', 'rec', 'team'], RUNNY = ['rush', 'team'];
  // game context (<season>_g.json, attached as D.gx by loadSeason): x row [home pts, away pts, home rest, away rest,
  // weekday, kickoff min ET, neutral]; r[game] = [home Map, away Map] gsis -> played (true) / on the roster, out (false)
  let BIO = null;  // bio.json: { schools, confs, p: Map gsis -> [school, conf, draft round, pick, contracts], fam: the query's family }
  // ranges (owner 2026-10-22: "can we use sliders for filters when natural?"): a filter with .range takes "R:lo~hi"
  // (an end at an open min / max means no bound) besides its preset options, so saved presets keep their meaning;
  // range.chips limits which presets show as quick picks (the rest still read from saved queries)
  const span = (lo, hi, f = x => x, more = '+', less = ' or less') => (lo === -Infinity && hi === Infinity ? 'any'
    : lo === -Infinity ? `${f(hi)}${less}` : hi === Infinity ? `${f(lo)}${more}` : lo === hi ? `${f(lo)}` : `${f(lo)}-${f(hi)}`);
  const sg = x => (x > 0 ? `+${x}` : `${x}`);
  const ordn = x => `${x}${['th', 'st', 'nd', 'rd'][x % 100 > 10 && x % 100 < 14 ? 0 : x % 10] || 'th'}`;
  const parseR = (F, v) => { const [a, b] = v.slice(2).split('~').map(Number), r = F.range; return [r.openLo && a <= r.min ? -Infinity : a, r.openHi && b >= r.max ? Infinity : b]; };
  // the measured player's bio row, and the contract running in a season (the latest signed that still covers it)
  const bioOf = (P, j, D) => { if (!BIO) return null; const a = FAM[BIO.fam].actor(P, j); return a >= 0 ? BIO.p.get(D.players[a][0]) || null : null; };
  const deal = (b, season) => { if (!b) return null; let d = null; for (const c of b[4]) if (c[0] <= season && season < c[0] + c[1]) d = c; return d; };
  // opponent strength (owner 2026-10-22): per season, each defense's rank by EPA allowed per play (regular season; run =
  // designed runs, pass = dropbacks incl. scrambles), who reached the playoffs, and (with the game file) each team's
  // regular-season win % (to date in the current season). RUNFAM: the query's family, for which defense rank applies.
  let RUNFAM = 'rush';
  const seasonCtx = D => {
    if (D.ctx) return D.ctx;
    const P = D.cols, G = D.games, nT = D.teams.length, z = () => new Float64Array(nT);
    const eR = z(), nR = z(), eP = z(), nP = z(), post = new Uint8Array(nT), pair = [];
    for (let j = 0; j < D.n; j++) {
      const g = P.g[j], d = P.d[j];
      if (!pair[g]) pair[g] = [P.o[j], d];
      if (G[g][2]) { post[P.o[j]] = 1; post[d] = 1; continue; }
      if (P.ty[j] === 0) { eR[d] += P.e[j]; nR[d]++; } else { eP[d] += P.e[j]; nP[d]++; }
    }
    const rank = (e, n) => { const r = new Int16Array(nT).fill(-1); [...Array(nT).keys()].filter(t => n[t] > 0).sort((a, b) => e[a] / n[a] - e[b] / n[b]).forEach((t, i) => { r[t] = i + 1; }); return r; };
    return (D.ctx = { run: rank(eR, nR), pass: rank(eP, nP), all: rank(eR.map((x, i) => x + eP[i]), nR.map((x, i) => x + nP[i])), post, pair });
  };
  const winPct = D => {
    if (D.wpct) return D.wpct;
    if (!D.gx) return null;
    const c = seasonCtx(D), nT = D.teams.length, w = new Float64Array(nT), g = new Float64Array(nT);
    D.games.forEach((G0, gi) => {
      const x = D.gx.x[gi], pr = c.pair[gi];
      if (G0[2] || x[0] < 0 || !pr) return;
      const h = G0[3], a = pr[0] === h ? pr[1] : pr[0], r = x[0] > x[1] ? 1 : x[0] < x[1] ? 0 : 0.5;
      w[h] += r; w[a] += 1 - r; g[h]++; g[a]++;
    });
    return (D.wpct = Array.from(w, (v, i) => (g[i] ? (100 * v) / g[i] : null)));
  };
  const defRank = (P, j, D) => { const c = seasonCtx(D), side = RUNFAM === 'rush' ? c.run : RUNFAM === 'pass' || RUNFAM === 'rec' ? c.pass : c.all, r = side[P.d[j]]; return r > 0 ? r : null; };
  // career (bio birth date YYYYMMDD, rookie season): age on Sept. 1 of the season, and his season count from the rookie year
  const ageOf = (b, s) => (!b || !(b[5] > 0) ? null : s - Math.floor(b[5] / 10000) - (b[5] % 10000 > 901 ? 1 : 0));
  const yearOf = (b, s) => (!b || !(b[6] > 0) || s < b[6] ? null : s - b[6] + 1);
  const home = (P, j, G) => P.o[j] === G[P.g[j]][3];
  const gx = (P, j, D, k) => (D.gx ? D.gx.x[P.g[j]][k] : -1);
  const margin = (P, j, G, D) => { if (!D.gx) return null; const x = D.gx.x[P.g[j]]; if (x[0] < 0) return null; return home(P, j, G) ? x[0] - x[1] : x[1] - x[0]; };
  // a team's days of rest (opp: its opponent's); week 1 has no previous game
  const rest = (P, j, G, D, opp) => { if (!D.gx || G[P.g[j]][1] === 1) return -1; const x = D.gx.x[P.g[j]]; return home(P, j, G) !== !!opp ? x[2] : x[3]; };
  const mate = (P, j, G, D, id) => (D.gx ? D.gx.r[P.g[j]][home(P, j, G) ? 0 : 1].get(id) : undefined);
  // today's divisions (fixed since 2002; earlier seasons are grouped by them too)
  const DIVS = { 'AFC East': ['BUF', 'MIA', 'NE', 'NYJ'], 'AFC North': ['BAL', 'CIN', 'CLE', 'PIT'], 'AFC South': ['HOU', 'IND', 'JAX', 'TEN'],
    'AFC West': ['DEN', 'KC', 'LAC', 'LV'], 'NFC East': ['DAL', 'NYG', 'PHI', 'WAS'], 'NFC North': ['CHI', 'DET', 'GB', 'MIN'],
    'NFC South': ['ATL', 'CAR', 'NO', 'TB'], 'NFC West': ['ARI', 'LA', 'SEA', 'SF'] };
  const FILTERS = {
    qtr: { label: 'Quarter', group: 'Situation', opts: [['1', '1st quarter', eq('q', 1)], ['2', '2nd quarter', eq('q', 2)], ['3', '3rd quarter', eq('q', 3)],
      ['4', '4th quarter', eq('q', 4)], ['ot', 'overtime', (P, j) => P.q[j] >= 5], ['h2', '2nd half + OT', (P, j) => P.q[j] >= 3]] },
    down: { label: 'Down', group: 'Situation', opts: [['1', '1st down', eq('dn', 1)], ['2', '2nd down', eq('dn', 2)], ['3', '3rd down', eq('dn', 3)],
      ['4', '4th down', eq('dn', 4)], ['34', '3rd or 4th down', (P, j) => P.dn[j] >= 3]] },
    dist: { label: 'Distance', group: 'Situation', opts: [...Array.from({ length: 14 }, (_, i) => [String(i + 1), `${i + 1} to go`, (P, j) => P.tg[j] === i + 1]),
      ['15', '15+ to go', (P, j) => P.tg[j] >= 15], ['s', 'short (1-3 to go)', (P, j) => P.tg[j] <= 3], ['m', 'medium (4-7 to go)', (P, j) => P.tg[j] >= 4 && P.tg[j] <= 7],
      ['l', 'long (8+ to go)', (P, j) => P.tg[j] >= 8]] },
    zone: { label: 'Field zone', group: 'Situation', opts: [['rz', 'red zone', (P, j) => P.yl[j] <= 20], ['gl', 'inside the 10', (P, j) => P.yl[j] <= 10],
      ['gtg', 'goal to go', (P, j) => P.yl[j] <= P.tg[j]], ['opp', "opponent's half", (P, j) => P.yl[j] <= 50], ['own', 'own half', (P, j) => P.yl[j] > 50],
      ['deep', 'backed up (own 10)', (P, j) => P.yl[j] >= 90]] },
    score: { label: 'Score', group: 'Situation', opts: [['l9', 'leading by 9+', (P, j) => P.sd[j] >= 9], ['l', 'leading by 1-8', (P, j) => P.sd[j] >= 1 && P.sd[j] <= 8],
      ['t', 'tied', eq('sd', 0)], ['b', 'trailing by 1-8', (P, j) => P.sd[j] <= -1 && P.sd[j] >= -8], ['b9', 'trailing by 9+', (P, j) => P.sd[j] <= -9],
      ['one', 'one-score game', (P, j) => Math.abs(P.sd[j]) <= 8]] },
    time: { label: 'Clock', group: 'Situation', opts: [['2m', 'last 2 minutes of a half', (P, j) => P.hs[j] <= 12], ['5m', 'last 5 minutes of a half', (P, j) => P.hs[j] <= 30]] },
    wp: { label: 'Win probability', group: 'Situation', need: ['wp'], known: (P, j) => P.wp[j] >= 0, opts: [['ng', 'no garbage time (10-90%)', (P, j) => P.wp[j] >= 10 && P.wp[j] <= 90],
      ['close', 'competitive (25-75%)', (P, j) => P.wp[j] >= 25 && P.wp[j] <= 75], ['ahead', 'game in hand (90%+)', (P, j) => P.wp[j] > 90],
      ['behind', 'long shot (under 10%)', (P, j) => P.wp[j] >= 0 && P.wp[j] < 10]] },
    // owner 2026-10-22 ("i can pick vikings, what if i want only when playing packers"): the options are the teams,
    // filled in once the team list loads; the data keeps today's codes in every season (shell.js franchise)
    // owner 2026-10-22 ("good ideas, all 5" + "20+ yard plays isn't a filter we can use already?"): situation type, play
    // result, schedule, game result, thrown by, with / without a teammate. g: needs <season>_g.json (game context and
    // who played); param: the value is a player ("gsis|Name"), picked in pickPerson
    sit: { label: 'Situation type', group: 'Situation', opts: [
      ['neu', 'neutral situations', (P, j) => P.dn[j] <= 2 && P.q[j] <= 4 && P.hs[j] > 12 && P.wp[j] >= 20 && P.wp[j] <= 80,
        '1st-2nd down, 20-80% win chance, not the last 2 minutes of a half'],
      ['early', 'early downs (1st-2nd)', (P, j) => P.dn[j] === 1 || P.dn[j] === 2],
      ['pd', 'passing downs', (P, j) => (P.dn[j] === 2 && P.tg[j] >= 8) || (P.dn[j] >= 3 && P.tg[j] >= 5), '2nd & 8+, 3rd or 4th & 5+']] },
    xpc: { label: 'Expected play call', group: 'Situation', need: ['xp'], known: (P, j) => P.xp[j] >= 0, opts: [
      ['p', 'pass expected', (P, j) => P.xp[j] >= 70, "nflverse's model gives a pass 70%+"],
      ['r', 'run expected', (P, j) => P.xp[j] >= 0 && P.xp[j] <= 30, 'a pass 30% or less'],
      ['m', 'toss-up play call', (P, j) => P.xp[j] > 30 && P.xp[j] < 70, 'a pass 30-70%']] },
    out: { label: 'Play result', group: 'Result', opts: [['10', 'gained 10+ yards', (P, j) => P.y[j] >= 10], ['20', 'gained 20+ yards', (P, j) => P.y[j] >= 20],
      ['40', 'gained 40+ yards', (P, j) => P.y[j] >= 40], ['fd', 'first downs', eq('fd', 1)], ['td', 'touchdowns (by the offense)', (P, j) => (P.tdo ? P.tdo[j] : P.td[j]) === 1],
      ['neg', 'no gain or a loss', (P, j) => P.y[j] <= 0], ['to', 'turnovers', (P, j) => P.in[j] === 1 || P.fl[j] === 1],
      // owner 2026-10-22 ("plays that resulted in ..."): the outcomes the play file already carries
      ['succ', 'successful plays', eq('s', 1), "positive EPA (the analysts' success rate)"], ['fail', 'unsuccessful plays', eq('s', 0)],
      ['inc', 'incomplete passes', (P, j) => P.ty[j] === 1 && P.pa[j] === 1 && !P.sk[j] && !P.c[j] && !P.in[j]],
      ['sack', 'sacks', eq('sk', 1)], ['int', 'interceptions', eq('in', 1)], ['fum', 'fumbles lost', eq('fl', 1)]] },
    res: { label: 'Game result', group: 'Game', g: true, known: (P, j, G, V, D) => margin(P, j, G, D) != null, opts: [['w', 'in wins', (P, j, G, V, D) => margin(P, j, G, D) > 0],
      ['l', 'in losses', (P, j, G, V, D) => { const m = margin(P, j, G, D); return m != null && m < 0; }],
      ['one', 'one-score games (8 or less)', (P, j, G, V, D) => { const m = margin(P, j, G, D); return m != null && Math.abs(m) <= 8; }],
      ['bw', 'won by 17+', (P, j, G, V, D) => margin(P, j, G, D) >= 17], ['bl', 'lost by 17+', (P, j, G, V, D) => { const m = margin(P, j, G, D); return m != null && m <= -17; }]] },
    sched: { label: 'Schedule', group: 'Game', g: true, known: (P, j, G, V, D) => !!D.gx && gx(P, j, D, 5) >= 0, opts: [
      ['bye', 'off a bye', (P, j, G, V, D) => rest(P, j, G, D, 0) >= 13], ['obye', 'opponent off a bye', (P, j, G, V, D) => rest(P, j, G, D, 1) >= 13],
      ['short', 'short week (5 days or less)', (P, j, G, V, D) => { const r = rest(P, j, G, D, 0); return r >= 0 && r <= 5; }],
      ['xr', 'extra rest (8-12 days)', (P, j, G, V, D) => { const r = rest(P, j, G, D, 0); return r >= 8 && r <= 12; }],
      ['prime', 'primetime (7 p.m. ET or later)', (P, j, G, V, D) => gx(P, j, D, 5) >= 1140],
      ['thu', 'Thursday games', (P, j, G, V, D) => gx(P, j, D, 4) === 4], ['snf', 'Sunday night', (P, j, G, V, D) => gx(P, j, D, 4) === 0 && gx(P, j, D, 5) >= 1140],
      ['mon', 'Monday games', (P, j, G, V, D) => gx(P, j, D, 4) === 1],
      ['sun1', 'Sunday early (1 p.m. ET)', (P, j, G, V, D) => gx(P, j, D, 4) === 0 && gx(P, j, D, 5) >= 0 && gx(P, j, D, 5) < 900],
      ['sun4', 'Sunday late afternoon', (P, j, G, V, D) => gx(P, j, D, 4) === 0 && gx(P, j, D, 5) >= 900 && gx(P, j, D, 5) < 1140],
      ['intl', 'neutral site / international', (P, j, G, V, D) => gx(P, j, D, 6) === 1 && !G[P.g[j]][2]]] },
    qb: { label: 'Thrown by', group: 'Pass', only: PASSY, param: 'qb', hint: 'one quarterback', opts: [], known: (P, j) => P.pp[j] >= 0,
      fmt: v => `thrown by ${v.split('|')[1] || 'a QB'}`, test: v => { const id = v.split('|')[0]; return (P, j, G, V, D) => { const k = P.pp[j]; return k >= 0 && D.players[k][0] === id; }; } },
    with: { label: 'With a teammate', group: 'Teammates', g: true, param: 'mate', opts: [], noNot: true, hint: 'only games the teammate played',
      fmt: v => `with ${v.split('|')[1] || 'teammate'}`, test: v => { const id = v.split('|')[0]; return (P, j, G, V, D) => mate(P, j, G, D, id) === true; } },
    wo: { label: 'Without a teammate', group: 'Teammates', g: true, param: 'mate', opts: [], noNot: true, hint: "only games the teammate was on the roster but didn't play",
      fmt: v => `without ${v.split('|')[1] || 'teammate'}`, test: v => { const id = v.split('|')[0]; return (P, j, G, V, D) => mate(P, j, G, D, id) === false; } },
    // owner 2026-10-22 ("how bout college, plays that went to u of florida"): the measured player's school or its
    // conference (today's conference: nflverse lists the school's current one)
    col: { label: 'College', group: 'Player',  only: ['rush', 'pass', 'rec'], param: 'college', bio: true, opts: [], known: (P, j, G, V, D) => { const b = bioOf(P, j, D); return !!b && b[0] >= 0; }, hint: 'a school or conference',
      fmt: v => `from ${v.slice(2)}`, test: v => {
        const k = v[0] === 'c' ? 1 : 0, idx = (k ? BIO.confs : BIO.schools).indexOf(v.slice(2)), actor = FAM[BIO.fam].actor;
        return (P, j, G, V, D) => { const a = actor(P, j); if (a < 0) return false; const c = BIO.p.get(D.players[a][0]); return !!c && c[k] === idx; };
      } },
    vs: { label: 'Opponent', group: 'Game', hint: 'a team, division or conference', opts: [] },
    tm: { label: 'Playing for', group: 'Game', hint: 'only plays for one team (for players who moved)', opts: [] },
    site: { label: 'Home / away', group: 'Game', opts: [['h', 'at home', (P, j, G) => gm(P, j, G)[3] === P.o[j]], ['a', 'on the road', (P, j, G) => gm(P, j, G)[3] !== P.o[j]]] },
    week: { label: 'Weeks', group: 'Game', opts: [['e', 'weeks 1-4', (P, j, G) => gm(P, j, G)[1] <= 4 && !gm(P, j, G)[2]],
      ['m', 'weeks 5-9', (P, j, G) => { const w = gm(P, j, G)[1]; return w >= 5 && w <= 9 && !gm(P, j, G)[2]; }],
      ['l', 'weeks 10-14', (P, j, G) => { const w = gm(P, j, G)[1]; return w >= 10 && w <= 14 && !gm(P, j, G)[2]; }],
      ['d', 'week 15 on', (P, j, G) => gm(P, j, G)[1] >= 15 && !gm(P, j, G)[2]]] },
    roof: { label: 'Roof', group: 'Game', opts: [['in', 'indoors', (P, j, G) => gm(P, j, G)[4] === 1], ['out', 'outdoors', (P, j, G) => gm(P, j, G)[4] === 0]] },
    surf: { label: 'Surface', group: 'Game', opts: [['g', 'on grass', (P, j, G) => gm(P, j, G)[5] === 0], ['t', 'on turf', (P, j, G) => gm(P, j, G)[5] === 1]] },
    wx: { label: 'Weather', group: 'Game', opts: [['c40', 'cold (40 F or below)', (P, j, G) => { const g = gm(P, j, G); return !g[4] && g[6] > -999 && g[6] <= 40; }],
      ['c32', 'freezing (32 F or below)', (P, j, G) => { const g = gm(P, j, G); return !g[4] && g[6] > -999 && g[6] <= 32; }],
      ['w15', 'windy (15+ mph)', (P, j, G) => { const g = gm(P, j, G); return !g[4] && g[7] >= 15; }],
      ['hot', 'hot (80 F or above)', (P, j, G) => { const g = gm(P, j, G); return !g[4] && g[6] >= 80; }]] },
    div: { label: 'Division', group: 'Game', opts: [['d', 'division games', (P, j, G) => gm(P, j, G)[8] === 1], ['n', 'non-division games', (P, j, G) => gm(P, j, G)[8] === 0]] },
    line: { label: 'Point spread', group: 'Game', opts: [['f7', 'favored by 7+', (P, j, G) => offFav(P, j, G) >= 70], ['f', 'favored', (P, j, G) => offFav(P, j, G) > 0],
      ['u', 'underdog', (P, j, G) => { const f = offFav(P, j, G); return f != null && f < 0; }], ['u7', 'underdog by 7+', (P, j, G) => { const f = offFav(P, j, G); return f != null && f <= -70; }]] },
    total: { label: 'Over / under', group: 'Game', opts: [['hi', 'total 48+', (P, j, G) => gm(P, j, G)[10] >= 480],
      ['lo', 'total 40 or less', (P, j, G) => { const t = gm(P, j, G)[10]; return t > 0 && t <= 400; }]] },
    form: { label: 'Shotgun / huddle', group: 'Offense', opts: [['sg', 'shotgun', eq('sg', 1)], ['uc', 'not shotgun', eq('sg', 0)], ['nh', 'no huddle', eq('nh', 1)]] },
    align: { label: 'QB alignment', group: 'Offense', need: ['fm'], opts: ['Shotgun', 'Under center', 'Pistol', 'Wildcat'].map(l => [l, l.toLowerCase(), vt('fm', l)]) },
    pers: { label: 'Personnel', group: 'Offense', need: ['op'], opts: [...['10', '11', '12', '13', '20', '21', '22'].map(c => [c, `${c} personnel`, vt('op', c)]),
      ['e', 'no running back', (P, j, G, V) => !!V.op && (V.op[P.op[j] - 1] || 'x')[0] === '0']] },
    bf: { label: 'Backfield', group: 'Offense', need: ['bf'], opts: [['0', 'empty backfield', eq('bf', 0)], ['1', 'one back', eq('bf', 1)], ['2', 'two+ backs', (P, j) => P.bf[j] >= 2]] },
    mo: { label: 'Motion', group: 'Offense', need: ['mo'], opts: [['y', 'motion at the snap', eq('mo', 1)], ['n', 'no motion', eq('mo', 0)]] },
    pa: { label: 'Play action', group: 'Offense', need: ['px'], only: PASSY, opts: [['y', 'play action', eq('px', 1)], ['n', 'no play action', eq('px', 0)]] },
    rpo: { label: 'RPO', group: 'Offense', need: ['rp'], opts: [['y', 'RPOs', eq('rp', 1)], ['n', 'not an RPO', eq('rp', 0)]] },
    scr: { label: 'Screen', group: 'Offense', need: ['sc'], only: PASSY, opts: [['y', 'screens', eq('sc', 1)], ['n', 'no screens', eq('sc', 0)]] },
    trick: { label: 'Trick play', group: 'Offense', need: ['tr'], opts: [['y', 'trick plays', eq('tr', 1)], ['n', 'no trick plays', eq('tr', 0)]] },
    dir: { label: 'Run direction', group: 'Run', only: RUNNY, opts: [['l', 'runs left', eq('rl', 1)], ['m', 'runs up the middle', eq('rl', 2)], ['r', 'runs right', eq('rl', 3)],
      ['o', 'runs outside (left or right)', (P, j) => P.rl[j] === 1 || P.rl[j] === 3]] },
    rtype: { label: 'Run type', group: 'Run', only: ['rush'], opts: [['d', 'designed runs', eq('ty', 0)], ['s', 'QB scrambles', eq('ty', 2)]] },
    gap: { label: 'Run gap', group: 'Run', need: ['gp'], only: RUNNY, opts: [['end', 'around end', eq('gp', 1)], ['tackle', 'off tackle', eq('gp', 2)], ['guard', 'off guard', eq('gp', 3)]] },
    depth: { label: 'Pass depth', group: 'Pass', need: ['ay'], only: PASSY, opts: [['b', 'behind the line', (P, j) => P.ay[j] > -99 && P.ay[j] < 0],
      ['s', 'short (under 10 air yds)', (P, j) => P.ay[j] > -99 && P.ay[j] < 10], ['i', 'intermediate (10-19)', (P, j) => P.ay[j] >= 10 && P.ay[j] < 20],
      ['d', 'deep (20+)', (P, j) => P.ay[j] >= 20]] },
    loc: { label: 'Pass location', group: 'Pass', need: ['pl'], only: PASSY, opts: [['l', 'throws left', eq('pl', 1)], ['m', 'throws over the middle', eq('pl', 2)],
      ['r', 'throws right', eq('pl', 3)], ['o', 'throws outside (left or right)', (P, j) => P.pl[j] === 1 || P.pl[j] === 3]] },
    route: { label: 'Route', group: 'Pass', need: ['rt'], only: PASSY, opts: ['Go', 'Post', 'Corner', 'Slant', 'In / dig', 'Hitch / curl', 'Cross / drag',
      'Out / flat / swing', 'Angle', 'Wheel', 'Screen'].map(l => [l, `${l.toLowerCase()} routes`, vt('rt', l)]) },
    press: { label: 'Pressure', group: 'Pass', need: ['pz'], only: PASSY, opts: [['y', 'under pressure', eq('pz', 1)], ['n', 'clean pocket', eq('pz', 0)]] },
    ttt: { label: 'Time to throw', group: 'Pass', need: ['tt'], only: PASSY, opts: [['q', 'quick (under 2.5 s)', (P, j) => P.tt[j] >= 0 && P.tt[j] < 25],
      ['m', '2.5-3.4 s', (P, j) => P.tt[j] >= 25 && P.tt[j] < 35], ['l', 'held it (3.5 s+)', (P, j) => P.tt[j] >= 35]] },
    pocket: { label: 'Pocket', group: 'Pass', need: ['oo'], only: PASSY, opts: [['in', 'in the pocket', eq('oo', 0)], ['out', 'out of the pocket', eq('oo', 1)]] },
    read: { label: 'Read', group: 'Pass', need: ['rd'], only: PASSY, opts: ['1st read', '2nd read', '3rd+ read', 'Checkdown', 'Designed', 'Scramble drill']
      .map(l => [l, l.toLowerCase() + (l.endsWith('read') ? ' throws' : ''), vt('rd', l)]) },
    hit: { label: 'QB hit', group: 'Pass', only: PASSY, opts: [['y', 'QB hit', eq('qh', 1)], ['n', 'QB not hit', eq('qh', 0)]] },
    catchable: { label: 'Catchable', group: 'Pass', need: ['cb'], only: PASSY, opts: [['y', 'catchable balls', eq('cb', 1)], ['n', 'uncatchable balls', eq('cb', 0)]] },
    contested: { label: 'Contested', group: 'Pass', need: ['ct'], only: PASSY, opts: [['y', 'contested balls', eq('ct', 1)], ['n', 'uncontested balls', eq('ct', 0)]] },
    fgd: { label: 'Kick distance', group: 'Special teams', stOnly: true, only: ['fg'], opts: [['29', 'under 30 yds', (P, j) => P.kd[j] < 30],
      ['30', '30-39 yds', (P, j) => P.kd[j] >= 30 && P.kd[j] < 40], ['40', '40-49 yds', (P, j) => P.kd[j] >= 40 && P.kd[j] < 50],
      ['50', '50+ yds', (P, j) => P.kd[j] >= 50], ['55', '55+ yds', (P, j) => P.kd[j] >= 55], ['60', '60+ yds', (P, j) => P.kd[j] >= 60]] },
    pz: { label: 'Punting from', group: 'Special teams', stOnly: true, only: ['punt', 'pr'], opts: [['deep', 'own 20 or deeper', (P, j) => P.yl[j] >= 80],
      ['own', 'own 21-40', (P, j) => P.yl[j] >= 60 && P.yl[j] < 80], ['mid', 'own 41 to opp 41', (P, j) => P.yl[j] > 40 && P.yl[j] < 60],
      ['opp', 'opponent 40 or closer', (P, j) => P.yl[j] <= 40]] },
    box: { label: 'Box', group: 'Defense', need: ['bx'], opts: [['l', '6 or fewer in the box', (P, j) => P.bx[j] >= 1 && P.bx[j] <= 6], ['7', '7 in the box', eq('bx', 7)],
      ['s', '8+ in the box', (P, j) => P.bx[j] >= 8]] },
    rushers: { label: 'Pass rushers', group: 'Defense', need: ['pr'], only: PASSY, opts: [['3', '3 or fewer rushers', (P, j) => P.pr[j] >= 1 && P.pr[j] <= 3],
      ['4', '4 rushers', eq('pr', 4)], ['5', '5+ rushers', (P, j) => P.pr[j] >= 5]] },
    blitz: { label: 'Blitz', group: 'Defense', need: ['bl'], only: PASSY, opts: [['y', 'blitzed', (P, j) => P.bl[j] >= 1], ['n', 'not blitzed', eq('bl', 0)]] },
    dbs: { label: 'Defensive personnel', group: 'Defense', need: ['db'], opts: [['4', 'base (4 DBs or fewer)', (P, j) => P.db[j] >= 0 && P.db[j] <= 4],
      ['5', 'nickel (5 DBs)', eq('db', 5)], ['6', 'dime (6+ DBs)', (P, j) => P.db[j] >= 6]] },
    mz: { label: 'Man / zone', group: 'Defense', need: ['mz'], only: PASSY, opts: [['m', 'vs man coverage', eq('mz', 1)], ['z', 'vs zone coverage', eq('mz', 2)]] },
    cov: { label: 'Coverage', group: 'Defense', need: ['cv'], only: PASSY, opts: ['Cover 0', 'Cover 1', 'Cover 2', '2-man', 'Cover 3', 'Cover 4', 'Cover 6', 'Cover 9', 'Combo']
      .map(l => [l, `vs ${l}`, vt('cv', l)]) },
  };
  // ---- group by: [label, key(P, j, G, D, V), need, sort ('v' metric, 'k' key asc, 'kd' key desc)]
  const vk = c => (P, j, G, D, V) => (V[c] && V[c][P[c][j] - 1]) || null;
  const code = (c, names) => (P, j) => names[P[c][j]] || null;
  const offCoach = (P, j, G, D) => { const g = G[P.g[j]], i = g[3] === P.o[j] ? g[11] : g[12]; return i >= 0 ? D.coaches[i] : null; };
  const BY = {
    player: ['player', null, [], 'v'], team: ['team', (P, j, G, D) => D.teams[P.o[j]], [], 'v'], opp: ['opponent', (P, j, G, D) => D.teams[P.d[j]], [], 'v'],
    coach: ['head coach', offCoach, [], 'v'],
    college: ['college', (P, j, G, D) => { const a = FAM[BIO.fam].actor(P, j), c = a >= 0 ? BIO.p.get(D.players[a][0]) : null; return c && c[0] >= 0 ? BIO.schools[c[0]] : null; }, [], 'v'],
    rnd: ['draft round', (P, j, G, D) => { const b = bioOf(P, j, D); return b ? b[2] : null; }, [], 'k'],
    // game by game (owner 2026-10-22, "game logs, streaks, spans"): built from player-game totals in run(), not a key function
    pgame: ['game (game log)', null, [], 'v'], pmark: ['games reaching a mark', null, [], 'v'], pspan: ['best stretch of games', null, [], 'v'],
    age: ['age', (P, j, G, D) => ageOf(bioOf(P, j, D), D.season), [], 'k'], cyr: ['career year', (P, j, G, D) => yearOf(bioOf(P, j, D), D.season), [], 'k'], season: ['season', (P, j, G, D) => D.season, [], 'kd'],
    // playoff weeks on the 2021+ numbering (wild card = 19), so each round groups and labels the same in every season:
    // before 2021 the regular season had 17 weeks and the wild card was week 18
    week: ['week', (P, j, G, D) => { const g = G[P.g[j]]; return g[2] ? 100 + g[1] + (+D.season < 2021 ? 1 : 0) : g[1]; }, [], 'kd'],  // newest first, like season (owner 2026-10-18)
    qtr: ['quarter', (P, j) => P.q[j] >= 5 ? 5 : P.q[j], [], 'k'], down: ['down', (P, j) => P.dn[j] || null, [], 'k'],
    dist: ['yards to go', (P, j) => Math.min(P.tg[j], 15), [], 'k'], zone: ['field position', (P, j) => Math.floor((100 - P.yl[j]) / 10), [], 'k'],
    score: ['score margin', (P, j) => Math.max(-3, Math.min(3, Math.sign(P.sd[j]) * Math.ceil(Math.abs(P.sd[j]) / 8))), [], 'k'],
    align: ['QB alignment', vk('fm'), ['fm'], 'v'], pers: ['personnel', vk('op'), ['op'], 'k'], box: ['box count', (P, j) => P.bx[j] >= 1 ? P.bx[j] : null, ['bx'], 'k'],
    rushers: ['pass rushers', (P, j) => P.pr[j] >= 1 ? P.pr[j] : null, ['pr'], 'k'], dbs: ['defensive backs', (P, j) => P.db[j] >= 0 ? P.db[j] : null, ['db'], 'k'],
    mz: ['man / zone', code('mz', ['', 'Man', 'Zone']), ['mz'], 'v'], cov: ['coverage', vk('cv'), ['cv'], 'k'], route: ['route', vk('rt'), ['rt'], 'v'],
    read: ['read', vk('rd'), ['rd'], 'k'], pa: ['play action', code('px', ['No play action', 'Play action']), ['px'], 'v'],
    mo: ['motion', code('mo', ['No motion', 'Motion']), ['mo'], 'v'], press: ['pressure', code('pz', ['Clean', 'Pressured']), ['pz'], 'v'],
    depth: ['pass depth', (P, j) => P.ay[j] <= -99 ? null : P.ay[j] < 0 ? 0 : P.ay[j] < 10 ? 1 : P.ay[j] < 20 ? 2 : 3, ['ay'], 'k'],
    loc: ['pass location', code('pl', [null, 'Left', 'Middle', 'Right']), ['pl'], 'v'], dir: ['run direction', (P, j) => P.rl[j] || null, ['rl'], 'k'],
    gap: ['run gap', (P, j) => P.rl[j] === 2 ? 4 : P.gp[j] || null, ['gp'], 'k'],  // outside -> inside: end, tackle, guard, middle
    kdist: ['kick distance', (P, j) => P.kd[j] >= 0 ? Math.min(6, Math.floor(P.kd[j] / 10)) : null, [], 'k'],
    roof: ['roof', (P, j, G) => G[P.g[j]][4] ? 'Indoors' : 'Outdoors', [], 'v'], surf: ['surface', (P, j, G) => [null, 'Grass', 'Turf'][G[P.g[j]][5] + 1] || null, [], 'v'],
  };
  const BYLABEL = {
    week: k => k > 100 ? ['', 'Wild Card', 'Divisional', 'Conference', 'Super Bowl'][Math.min(4, k - 118)] || `Playoffs wk ${k - 100}` : `Week ${k}`,
    rnd: k => (k >= 8 ? 'Undrafted' : k >= 7 ? 'Round 7+' : `Round ${k}`), age: k => `Age ${k}`, cyr: k => (k === 1 ? 'Rookie year' : `Year ${k}`),
    qtr: k => k === 5 ? 'OT' : `Q${k}`, down: k => `${k}${['', 'st', 'nd', 'rd', 'th'][k]} down`, dist: k => k >= 15 ? '15+ to go' : `${k} to go`,
    zone: k => k < 5 ? `Own ${k * 10}-${k * 10 + 9}` : `Opp ${100 - k * 10}-${91 - k * 10}`.replace('Opp 0-', 'Opp 1-'),
    score: k => ['Down 17+', 'Down 9-16', 'Down 1-8', 'Tied', 'Up 1-8', 'Up 9-16', 'Up 17+'][k + 3], box: k => `${k} in the box`,
    rushers: k => `${k} rushers`, dir: k => [null, 'Left', 'Middle', 'Right'][k], gap: k => [null, 'End', 'Tackle', 'Guard', 'Middle'][k], kdist: k => k >= 6 ? '60+ yds' : k < 2 ? 'under 20 yds' : `${k * 10}-${k * 10 + 9} yds`, dbs: k => `${k} DBs`, pers: k => `${k} personnel`, depth: k => ['Behind the line', 'Short (0-9)', 'Intermediate (10-19)', 'Deep (20+)'][k],
  };
  const EXAMPLES = [
    ['4th-quarter rushing, one-score games', { fam: 'rush', met: 'ypc', who: 'L', by: 'player', f: { qtr: '4', score: 'one' } }],
    ['Passing vs the blitz', { fam: 'pass', met: 'epa', who: 'L', by: 'player', f: { blitz: 'y' } }],
    ['Red-zone targets', { fam: 'rec', met: 'tgt', who: 'L', by: 'player', f: { zone: 'rz' } }],
    ['Which coverage hurts most?', { fam: 'pass', met: 'epa', who: 'L', by: 'cov', f: {} }],
    ['Runs vs a stacked box', { fam: 'rush', met: 'ypc', who: 'L', by: 'player', f: { box: 's' } }],
    ['Pass rate over expected', { fam: 'team', met: 'proe', who: 'L', by: 'team', f: { wp: 'ng' } }],
    ['Cold-weather passing by season', { fam: 'pass', met: 'ypa', who: 'L', by: 'season', f: { wx: 'c32' } }],
    ['Field goals from 50+', { fam: 'fg', met: 'pct', who: 'L', by: 'player', f: { fgd: '50' } }],
    ['Where runs work: direction x gap', { fam: 'rush', met: 'ypc', who: 'L', by: 'dir', by2: 'gap', f: {} }],
    ['Success by down and distance', { fam: 'team', met: 'sr', who: 'L', by: 'down', by2: 'dist', f: {} }],
    ['Each team by quarter', { fam: 'team', met: 'epa', who: 'L', by: 'team', by2: 'qtr', f: {} }],
    ['Best kick returners', { fam: 'kr', met: 'avg', who: 'L', by: 'player', f: {} }],
  ];
  const fmt = (v, d) => v == null || !isFinite(v) ? '–' : d ? v.toFixed(d) : Math.round(v).toLocaleString();
  const ranges = ys => { const out = []; ys.forEach(y => { const r = out[out.length - 1]; if (r && r[1] === y - 1) r[1] = y; else out.push([y, y]); });
    return out.map(([a, b]) => a === b ? `${a}` : `${a}-${b}`).join(', '); };
  // special teams take the game / situation filters (and their own); offense filters don't apply to kicks
  const RANGES = {
    dist: { get: (P, j) => P.tg[j], min: 1, max: 20, openHi: true, chips: ['s', 'm', 'l', '15'], say: (lo, hi) => `${span(lo, hi)} to go` },
    zone: { get: (P, j) => P.yl[j], min: 1, max: 99, unit: 'yards from the end zone',
      say: (lo, hi) => (lo <= 1 ? (hi <= 50 ? `inside the opponent's ${hi}` : `within ${hi} yds of the end zone`) : hi >= 99 ? `${lo}+ yds from the end zone` : `${lo}-${hi} yds from the end zone`) },
    score: { get: (P, j) => P.sd[j], min: -21, max: 21, openLo: true, openHi: true, unit: 'offense\'s score margin', tick: sg,
      say: (lo, hi) => (lo === 0 && hi === 0 ? 'tied' : lo >= 1 ? `leading by ${span(lo, hi)}` : hi <= -1 ? `trailing by ${span(-hi, -lo)}` : `score margin ${span(lo, hi, sg, ' or more', ' or less')}`) },
    time: { get: (P, j) => P.hs[j] / 6, min: 0, max: 30, unit: 'minutes left in the half', say: (lo, hi) => (lo <= 0 ? `last ${hi} min of a half` : `${lo}-${hi} min left in a half`) },
    wp: { get: (P, j) => (P.wp[j] < 0 ? null : P.wp[j]), min: 0, max: 100, unit: 'offense\'s win chance (%)', say: (lo, hi) => `${lo}-${hi}% win chance` },
    week: { get: (P, j, G) => (G[P.g[j]][2] ? null : G[P.g[j]][1]), min: 1, max: 18, say: (lo, hi) => (lo === hi ? `week ${lo}` : `weeks ${lo}-${hi}`) },
    line: { get: (P, j, G) => { const f = offFav(P, j, G); return f == null ? null : f / 10; }, min: -20, max: 20, step: 0.5, openLo: true, openHi: true, unit: 'points favored (- = underdog)', tick: sg,
      say: (lo, hi) => (lo > 0 ? `favored by ${span(lo, hi)}` : hi < 0 ? `underdog by ${span(-hi, -lo)}` : `spread ${span(lo, hi, sg, ' or more', ' or less')}`) },
    total: { get: (P, j, G) => (gm(P, j, G)[10] > 0 ? gm(P, j, G)[10] / 10 : null), min: 30, max: 60, step: 0.5, openLo: true, openHi: true, say: (lo, hi) => `over / under ${span(lo, hi)}` },
    depth: { get: (P, j) => (P.ay[j] <= -99 ? null : P.ay[j]), min: -10, max: 40, openLo: true, openHi: true, unit: 'air yards', say: (lo, hi) => `${span(lo, hi)} air yds` },
    ttt: { get: (P, j) => (P.tt[j] < 0 ? null : P.tt[j] / 10), min: 1, max: 5, step: 0.1, openLo: true, openHi: true, unit: 'seconds to throw', tick: x => x.toFixed(1),
      say: (lo, hi) => `${span(lo, hi, x => x.toFixed(1))} s to throw` },
    fgd: { get: (P, j) => (P.kd[j] < 0 ? null : P.kd[j]), min: 18, max: 65, openLo: true, openHi: true, say: (lo, hi) => `${span(lo, hi)} yd kicks` },
  };
  Object.entries(RANGES).forEach(([k, r]) => { FILTERS[k].range = r; });
  const clock = m => { const h = Math.floor(m / 60), mm = String(m % 60).padStart(2, '0'); return `${((h + 11) % 12) + 1}:${mm} ${h < 12 ? 'a.m.' : 'p.m.'}`; };
  const outdoor = (P, j, G, c) => { const g = gm(P, j, G); return g[4] || g[c] <= -999 ? null : g[c]; };
  const RNDL = x => (x >= 8 ? 'undrafted' : x >= 7 ? '7th+' : ordn(x));
  // on the field for that play (participation): with = he was out there; off = he played in the game for this offense
  // but sat this play out
  const onField = (P, j, D, id) => { if (!D.on) return undefined; const r = D.on.p[j]; if (!r) return undefined; const i = D.on.ix.get(id); return i != null && r.includes(i); };
  Object.assign(FILTERS, {
    onw: { label: 'On the field with', group: 'Teammates', on: true, param: 'mate', noNot: true, opts: [], hint: 'plays a teammate was on the field (2016-2025)',
      fmt: v => `with ${v.split('|')[1] || 'teammate'} on the field`, test: v => { const id = v.split('|')[0]; return (P, j, G, V, D) => onField(P, j, D, id) === true; } },
    onx: { label: 'Off the field', group: 'Teammates', on: true, g: true, param: 'mate', noNot: true, opts: [], hint: "plays a teammate who played that game sat out (2016-2025)",
      fmt: v => `${v.split('|')[1] || 'teammate'} off the field`, test: v => { const id = v.split('|')[0]; return (P, j, G, V, D) => mate(P, j, G, D, id) === true && onField(P, j, D, id) === false; } },
    rpos: { label: 'Position', group: 'Player', only: ['route'], actorLevel: true, hint: 'the route runner: WR, TE or RB',
      opts: [['WR', 'wide receivers'], ['TE', 'tight ends'], ['RB', 'running backs (incl. FB)']] },
    owp: { label: "Opponent's record", group: 'Game', g: true, opts: [], range: { get: (P, j, G, V, D) => { const w = winPct(D); return w ? w[P.d[j]] : null; },
      min: 0, max: 100, unit: "opponent's regular-season win % (to date this season)", tick: x => `${x}%`,
      presets: [['winning teams', 51, 100], ['.600 or better', 60, 100], ['losing teams', 0, 49]],
      say: (lo, hi) => (hi >= 100 ? `vs teams winning ${lo}%+` : lo <= 0 ? `vs teams winning ${hi}% or less` : `vs teams winning ${lo}-${hi}%`) } },
    opo: { label: 'Opponent made the playoffs', group: 'Game', hint: 'that season (none yet for the current one)',
      opts: [['y', 'vs playoff teams', (P, j, G, V, D) => seasonCtx(D).post[P.d[j]] === 1], ['n', 'vs non-playoff teams', (P, j, G, V, D) => seasonCtx(D).post[P.d[j]] === 0]] },
    odr: { label: 'Opponent defense rank', group: 'Game', opts: [], hint: 'by EPA allowed that season: run D for rushing, pass D for passing',
      range: { get: (P, j, G, V, D) => defRank(P, j, D), min: 1, max: 32, unit: '1 = best defense that season', tick: ordn,
        presets: [['top 5', 1, 5], ['top 10', 1, 10], ['bottom 10', 23, 32]],
        say: (lo, hi) => (lo <= 1 ? `vs top-${hi} defenses` : hi >= 32 ? `vs defenses ranked ${ordn(lo)} or worse` : `vs defenses ranked ${ordn(lo)}-${ordn(hi)}`) } },
    age: { label: 'Age', group: 'Player', bio: true, only: ['rush', 'pass', 'rec'], opts: [], range: { get: (P, j, G, V, D) => ageOf(bioOf(P, j, D), D.season),
      min: 20, max: 40, openLo: true, openHi: true, unit: 'age on Sept. 1 of the season', presets: [['25 or younger', 20, 25], ['26-29', 26, 29], ['30+', 30, 40]],
      say: (lo, hi) => `age ${span(lo, hi)}` } },
    cyr: { label: 'Career year', group: 'Player', bio: true, only: ['rush', 'pass', 'rec'], opts: [], range: { get: (P, j, G, V, D) => yearOf(bioOf(P, j, D), D.season),
      min: 1, max: 15, openHi: true, unit: 'season number, rookie year = 1', presets: [['rookies', 1, 1], ['2nd year', 2, 2], ['3rd-5th year', 3, 5], ['10th year+', 10, 15]],
      say: (lo, hi) => (lo === hi ? (lo === 1 ? 'rookies' : `${ordn(lo)}-year players`) : `career years ${span(lo, hi)}`) } },
    // owner 2026-10-22 ("exact temperature and kickoff time"): outdoor games only for weather (domes have none)
    temp: { label: 'Temperature', group: 'Game', opts: [], range: { get: (P, j, G) => outdoor(P, j, G, 6), min: 0, max: 100, openLo: true, openHi: true,
      unit: 'degrees F at kickoff (outdoor games)', tick: x => `${x} F`, presets: [['freezing (32 or below)', 0, 32], ['cold (40 or below)', 0, 40], ['hot (80+)', 80, 100]],
      say: (lo, hi) => `${span(lo, hi, x => `${x} F`)} outdoors` } },
    wind: { label: 'Wind', group: 'Game', opts: [], range: { get: (P, j, G) => outdoor(P, j, G, 7), min: 0, max: 30, openHi: true,
      unit: 'mph at kickoff (outdoor games)', tick: x => `${x} mph`, presets: [['calm (under 5)', 0, 4], ['windy (15+)', 15, 30], ['very windy (20+)', 20, 30]],
      say: (lo, hi) => `wind ${span(lo, hi, x => `${x} mph`)}` } },
    kick: { label: 'Kickoff time', group: 'Game', g: true, opts: [], range: { get: (P, j, G, V, D) => { const m = gx(P, j, D, 5); return m >= 0 ? m : null; },
      min: 540, max: 1260, step: 5, openLo: true, openHi: true, input: 'time', unit: 'Eastern time', tick: clock,
      presets: [['morning (overseas)', 540, 690], ['1 p.m. window', 780, 840], ['late afternoon', 900, 1020], ['night (7 p.m. or later)', 1140, 1260]],
      say: (lo, hi) => `kickoff ${span(lo, hi, clock, ' or later', ' or earlier')} ET` } },
    yds: { label: 'Yards gained', group: 'Result', opts: [], range: { get: (P, j) => P.y[j], min: -10, max: 50, openLo: true, openHi: true,
      presets: [['10+ yards', 10, 50], ['20+', 20, 50], ['40+', 40, 50], ['no gain or a loss', -10, 0]],
      say: (lo, hi) => (lo >= 1 ? `gained ${span(lo, hi)} yards` : hi === 0 && lo === -Infinity ? 'no gain or a loss' : `${span(lo, hi)} yards`) } },
    rnd: { label: 'Draft round', group: 'Player', bio: true, only: ['rush', 'pass', 'rec'], opts: [],
      range: { get: (P, j, G, V, D) => { const b = bioOf(P, j, D); return b ? b[2] : null; }, min: 1, max: 8, tick: RNDL,
        presets: [['1st round', 1, 1], ['day 2 (rounds 2-3)', 2, 3], ['day 3 (rounds 4-7)', 4, 7], ['undrafted', 8, 8]],
        say: (lo, hi) => (lo === hi ? (hi >= 8 ? 'undrafted' : `${RNDL(lo)}-round picks`) : hi >= 8 ? `${RNDL(lo)} round or later, or undrafted` : `drafted in rounds ${lo}-${RNDL(hi)}`) } },
    pick: { label: 'Draft pick', group: 'Player', bio: true, only: ['rush', 'pass', 'rec'], opts: [],
      range: { get: (P, j, G, V, D) => { const b = bioOf(P, j, D); return b && b[3] > 0 ? b[3] : null; }, min: 1, max: 260, openHi: true, unit: 'overall pick (drafted players)',
        presets: [['top 10', 1, 10], ['1st round (1-32)', 1, 32], ['2nd round (33-64)', 33, 64], ['100th or later', 100, 260]],
        say: (lo, hi) => (lo === hi ? `pick ${lo}` : `picks ${span(lo, hi)}`) } },
    aav: { label: 'Contract (AAV)', group: 'Player', bio: true, only: ['rush', 'pass', 'rec'], opts: [], hint: 'average per year of the contract running that season',
      range: { get: (P, j, G, V, D) => { const d = deal(bioOf(P, j, D), D.season); return d ? d[2] / 100 : null; }, min: 0, max: 50, step: 0.5, openHi: true,
        unit: '$ million per year (OverTheCap)', tick: x => `$${x}M`, presets: [['under $2M', 0, 2], ['$10M+', 10, 50], ['$20M+', 20, 50], ['$30M+', 30, 50]],
        say: (lo, hi) => (lo <= 0 ? `AAV under $${hi}M` : `AAV ${span(lo, hi, x => `$${x}M`)}`) } },
    cap: { label: 'Contract (% of cap)', group: 'Player', bio: true, only: ['rush', 'pass', 'rec'], opts: [], hint: 'AAV as a share of the cap when signed (compares eras)',
      range: { get: (P, j, G, V, D) => { const d = deal(bioOf(P, j, D), D.season); return d && d[3] >= 0 ? d[3] / 10 : null; }, min: 0, max: 20, step: 0.5, openHi: true,
        unit: '% of the salary cap', tick: x => `${x}%`, presets: [['under 1%', 0, 1], ['5%+', 5, 20], ['10%+', 10, 20]],
        say: (lo, hi) => `contract ${span(lo, hi, x => `${x}%`)} of the cap` } },
  });
  // the 10+ / 20+ / 40+ / no-gain options moved from Play result to Yards gained (saved queries are moved on load)
  FILTERS.out.opts = FILTERS.out.opts.filter(o => !['10', '20', '40', 'neg'].includes(o[0]));
  const OUT_MOVED = { 10: 'R:10~50', 20: 'R:20~50', 40: 'R:40~50', neg: 'R:-10~0' };
  const ST_FILTERS = new Set(['fgd', 'week', 'vs', 'tm', 'res', 'sched', 'with', 'wo', 'qtr', 'score', 'time', 'wp', 'site', 'week', 'roof', 'surf', 'wx', 'div', 'line', 'total']);
  const ST_BY = new Set(['player', 'team', 'opp', 'coach', 'season', 'week', 'qtr', 'score', 'roof', 'surf', 'kdist']);
  const allowed = (k, fam) => {
    const F = FILTERS[k], only = !F.only || F.only.includes(fam);
    return FAM[fam].st ? (ST_FILTERS.has(k) || (F.stOnly && only)) : !F.stOnly && only;
  };
  const byAllowed = (k, fam) => GAMEBY.has(k) ? !FAM[fam].st : ['college', 'rnd', 'age', 'cyr'].includes(k) ? ['rush', 'pass', 'rec'].includes(fam) : FAM[fam].st ? ST_BY.has(k) : k !== 'kdist';
  // Two-way grids (owner 2026-10-14): a second grouping makes the answer a shaded rows x columns grid. Groupings with
  // dozens of values (players, teams, coaches) work as rows only; columns must fit a phone (capped, scrolls past that).
  const GRID_ROW_ONLY = new Set(['player', 'team', 'opp', 'coach', 'college', 'pgame', 'pmark', 'pspan']);
  const GAMEBY = new Set(['pgame', 'pmark', 'pspan']);
  // a game row's minimum sample, and a mark's starting value for counting stats (rates start at the league average)
  const GMIN = { rush: 5, pass: 10, rec: 2, route: 10, team: 20 };
  const MARK = { yds: f => (f === 'pass' ? 300 : 100), td: f => (f === 'pass' ? 2 : 1), rec: () => 8, tgt: () => 10, att: () => 20, rr: () => 30 };
  const mergeAcc = (t, a) => { Object.keys(a).forEach(k => { if (k !== '_k') t[k] = k === 'lg' ? Math.max(t[k] || 0, a[k]) : (t[k] || 0) + a[k]; }); return t; };
  const GRID_MAX_ROWS = 40, GRID_MAX_COLS = 24;
  // metrics where a lower number is the good one (the grid shades those the other way)
  const LOWER = new Set(['skr', 'int', 'stuff', 'fl', 'drop', 'iw', 'ta', 'pz', 'qh', 'rya', 'bk', 'miss']);
  const numKey = x => (x !== '' && x != null && !isNaN(x) ? +x : x);

  // ---- the query (Q): { fam, met, who ('L' | 'T:team' | 'V:team' | 'P:gsis' | 'C:coach'), wn (that player's / coach's
  // name), f: { filter: value | [values] }, fn: { filter: 1 = excluded }, by, by2, st ('reg' | 'post' | 'both'),
  // from, to, min, gt (game mark), gn (stretch length) }. Filter values: an option key, "R:lo~hi" for a range,
  // "gsis|Name" for a player, "s:School" / "c:Conference" for a college.
  let IX = null;  // index.json (+ teams), set by init()
  const defaults = () => ({ fam: 'rush', met: 'ypc', who: 'L', wn: '', by: 'player', by2: '', st: 'reg', from: null, to: null, f: {}, fn: {}, min: null, gt: null, gn: 4 });
  const famMetric = Q => { const fam = FAM[Q.fam]; return [fam, fam.met[Q.met] || Object.values(fam.met)[0]]; };
  const needs = Q => {
    const [, m] = famMetric(Q), s = new Set(m[3] || []);
    Object.keys(Q.f).forEach(k => (FILTERS[k].need || []).forEach(c => s.add(c)));
    (BY[Q.by][2] || []).forEach(c => s.add(c));
    if (Q.by2 && BY[Q.by2]) (BY[Q.by2][2] || []).forEach(c => s.add(c));
    return [...s];
  };
  const tracked = () => new Set(IX.tracked || Object.keys(CNAME));
  const covers = (s, cols) => { const have = IX.cov[s] || [], tr = tracked(); return cols.every(c => !tr.has(c) || have.includes(c)); };
  const spanSeasons = Q => IX.seasons.filter(s => s >= Q.from && s <= Q.to);
  const cap = s => s.charAt(0).toUpperCase() + s.slice(1);
  // Who names the subject: the scope (Q.who) plus, for the league or one team, its unit (players, or the team as one:
  // owner 2026-10-22 "who: add teams themselves maybe?"). A team as itself is that team, a row per season.
  const UNITS = { player: 'Every player', team: 'Every team', opp: 'Every defense', coach: 'Every head coach' };
  const whoLabel = Q => {
    const t = Q.who.slice(2);
    if (Q.who === 'L') return UNITS[Q.by] || 'Whole league';
    if (/^T:/.test(Q.who)) return Q.fam === 'team' ? `${t} offense` : Q.by === 'player' ? `${t} players` : `${t} as a team`;
    if (/^V:/.test(Q.who)) return Q.by === 'player' ? `Players against ${t}` : `${t} defense`;
    return Q.who[0] === 'C' ? `${Q.wn}'s offense` : Q.wn || 'Whole league';
  };
  const isR = (F, v) => F.range && typeof v === 'string' && v.startsWith('R:');
  const vals = (Q, k) => (Array.isArray(Q.f[k]) ? Q.f[k] : k in Q.f ? [Q.f[k]] : []);
  const isNot = (Q, k) => !!(Q.fn && Q.fn[k]);
  const setF = (Q, k, list, neg) => {
    if (!list.length) { delete Q.f[k]; delete Q.fn[k]; return; }
    Q.f[k] = list.length === 1 ? list[0] : list;
    if (neg) Q.fn[k] = 1; else delete Q.fn[k];
  };
  const optLabel = (Q, k) => {
    const F = FILTERS[k], one = v => (isR(F, v) ? F.range.say(...parseR(F, v)) : F.fmt ? F.fmt(v) : (F.opts.find(o => o[0] === v) || ['', ''])[1]);
    // "against GB or CHI", not "against GB or against CHI": shared leading words said once
    const ls = vals(Q, k).map(one), w = ls.map(l => l.split(' '));
    let n = 0;
    while (ls.length > 1 && w.every(x => x.length > n + 1 && x[n] === w[0][n])) n++;
    return `${isNot(Q, k) ? 'not ' : ''}${n ? `${w[0].slice(0, n).join(' ')} ${w.map(x => x.slice(n).join(' ')).join(' or ')}` : ls.join(' or ')}`;
  };
  const testOf = (k, v) => {
    const F = FILTERS[k];
    if (isR(F, v)) { const [lo, hi] = parseR(F, v), get = F.range.get; return (P, j, G, V, D) => { const x = get(P, j, G, V, D); return x != null && x >= lo && x <= hi; }; }
    if (F.actorLevel) return null;
    return F.test ? F.test(v) : (F.opts.find(o => o[0] === v) || [])[2];
  };
  // "is not" keeps only plays where the filter's value is known: a play with no charting (or no contract on record)
  // is neither play action nor not play action
  const MISS = { ay: -99, yc: -99, cp: -999, xy: -999, fm: 0, op: 0, rt: 0, cv: 0, mz: 0, rd: 0, pl: 0, rl: 0, gp: 0 };
  const knownOf = F => {
    const need = F.need || [], get = F.range ? F.range.get : null, own = F.known;
    return (P, j, G, V, D) => (!get || get(P, j, G, V, D) != null) && (!own || own(P, j, G, V, D))
      && need.every(c => P[c] && P[c][j] !== (c in MISS ? MISS[c] : -1));
  };
  const filterTest = (Q, k) => {
    const ts = vals(Q, k).map(v => testOf(k, v)).filter(Boolean);
    if (!ts.length) return null;
    const any = ts.length === 1 ? ts[0] : (P, j, G, V, D) => { for (let i = 0; i < ts.length; i++) if (ts[i](P, j, G, V, D)) return true; return false; };
    if (!isNot(Q, k)) return any;
    const known = knownOf(FILTERS[k]);
    return (P, j, G, V, D) => known(P, j, G, V, D) && !any(P, j, G, V, D);
  };
  const ST_TXT = { reg: 'regular season', post: 'playoffs', both: 'regular season + playoffs' };
  const seasonsTxt = Q => `${Q.from === Q.to ? Q.from : `${Q.from}–${Q.to}`} · ${cap(ST_TXT[Q.st])}`;
  // the minimum sample by default: per game in a game log, else the measure's own
  const defMin = Q => (Q.by === 'pgame' ? GMIN[Q.fam] || 1 : FAM[Q.fam].min);
  const markTxt = Q => { const [, m] = famMetric(Q), mk = Q.gt != null ? Q.gt : MARK[Q.met] ? MARK[Q.met](Q.fam) : null;
    return mk == null ? `${m[0]} above the league average` : `${fmt(mk, m[2])}${LOWER.has(Q.met) ? ' or less' : '+'} ${m[0].toLowerCase()}`; };
  const gameTxt = Q => (Q.by === 'pgame' ? 'Each game (game log)' : Q.by === 'pmark' ? `Games with ${markTxt(Q)}` : `Best ${Q.gn}-game stretch`);
  const byTxt = Q => GAMEBY.has(Q.by) ? gameTxt(Q) : (Q.by2 && BY[Q.by2] ? `${cap(BY[Q.by][0])}, then ${BY[Q.by2][0]} (grid)` : `One row per ${BY[Q.by][0]}`);
  // the question in words, as parts (the page bolds who / metric) and as one line
  const summaryParts = Q => {
    const [fam, m] = famMetric(Q);
    const who = Q.who === 'L' && !UNITS[Q.by] ? 'The league' : whoLabel(Q);
    const unit = (Q.who === 'L' && UNITS[Q.by]) || Q.by === 'player';  // the breakdown is already in the subject
    const when = Object.keys(Q.f).map(k => optLabel(Q, k)).filter(Boolean);
    const by = GAMEBY.has(Q.by) ? `, ${gameTxt(Q).toLowerCase()}` : Q.by2 && BY[Q.by2] ? `, as a grid of ${BY[Q.by][0]} by ${BY[Q.by2][0]}` : unit ? '' : `, by ${BY[Q.by][0]}`;
    return { who, fam: fam.label.toLowerCase(), metric: m[0], when, years: Q.from === Q.to ? `${Q.from}` : `${Q.from}–${Q.to}`, st: ST_TXT[Q.st], by };
  };
  const describe = Q => { const s = summaryParts(Q); return `${s.who} · ${s.fam} ${s.metric}${s.when.length ? ` when ${s.when.join(', ')}` : ''} · ${s.years} ${s.st}${s.by}`; };
  // a query from a saved / shared / hand-written one: defaults filled, unknown keys dropped, seasons in range
  const OK_ST = new Set(['reg', 'post', 'both']);
  const normalize = q => {
    const Q = Object.assign(defaults(), q || {});
    Q.f = Object.assign({}, Q.f || {}); Q.fn = Object.assign({}, Q.fn || {});
    const last = IX.seasons[IX.seasons.length - 1];
    if (!Q.to || !IX.seasons.includes(+Q.to)) Q.to = last;
    if (!Q.from || !IX.seasons.includes(+Q.from)) Q.from = Math.max(IX.seasons[0], Q.to - 2);
    Q.from = +Q.from; Q.to = +Q.to;
    if (Q.from > Q.to) [Q.from, Q.to] = [Q.to, Q.from];
    if (!OK_ST.has(Q.st)) Q.st = 'reg';
    if (!FAM[Q.fam]) Q.fam = 'rush';
    if (!FAM[Q.fam].met[Q.met]) Q.met = FIRST[Q.fam];
    if (!BY[Q.by] || !byAllowed(Q.by, Q.fam)) Q.by = 'player';
    if (Q.by2 && (!BY[Q.by2] || !byAllowed(Q.by2, Q.fam) || Q.by2 === Q.by || GRID_ROW_ONLY.has(Q.by2) || GAMEBY.has(Q.by))) Q.by2 = '';
    if (Q.who === 'S' || typeof Q.who !== 'string') Q.who = 'L';
    if (OUT_MOVED[Q.f.out]) { Q.f.yds = OUT_MOVED[Q.f.out]; delete Q.f.out; }
    Object.keys(Q.f).forEach(k => { if (!FILTERS[k] || !allowed(k, Q.fam)) delete Q.f[k]; });
    Object.keys(Q.fn).forEach(k => { if (!(k in Q.f)) delete Q.fn[k]; });
    return Q;
  };

  // ---- loading: base file per season; charting file only when the query needs a charting column; game context,
  // on-field and bio files only when a filter / measure / breakdown uses them. load(path) -> Promise of parsed JSON,
  // paths relative to the site root (the page: NFLE.load; tools/trends_cli.mjs: files or the live site).
  const base = {}, extra = {}, merged = {}, stv = {}, gfile = {}, onfile = {};
  let bioP = null;
  const loadBio = () => bioP || (bioP = load('data/plays/bio.json').then(c => {
    BIO = { schools: c.schools, confs: c.confs, p: new Map(Object.entries(c.p)), fam: 'rush' };
  }));
  const bio = () => BIO;
  // game context: gsis ids per game side (the file holds the season's player idx, signed: + played, - out)
  const loadG = (s, D) => gfile[s] || (gfile[s] = load(`data/plays/${s}_g.json`).then(raw => {
    const ids = D.players.map(p => p[0]);
    D.gx = { x: raw.x, r: raw.r.map(sides => sides.map(list => new Map(list.map(v => [ids[Math.abs(v) - 1], v > 0])))) };
  }).catch(() => { D.gx = null; }));
  const loadOn = (s, D) => onfile[s] || (onfile[s] = load(`data/plays/${s}_on.json`).then(raw => {
    const runs = raw.pl.map(x => x[2] !== 'QB');
    D.on = { pl: raw.pl, p: raw.p, ix: new Map(raw.pl.map((x, i) => [x[0], i])), rr: raw.p.map(r => (r ? r.filter(i => runs[i]) : null)) };
  }).catch(() => { D.on = null; }));
  const loadSeason0 = (s, wantX, side) => {
    const b = base[s] || (base[s] = load(`data/plays/${s}.json`));
    if (side) {
      const st = stv[s] || (stv[s] = load(`data/plays/${s}_st.json`));
      return Promise.all([b, st]).then(([D, S]) => {
        const key = `${s}st${side}`;
        if (!merged[key]) {
          const c = S.cols, r = side === 'r';
          // the kicking team's columns, or the same plays from the receiving team's side
          const P = Object.assign({}, c, r ? { o: c.r, d: c.k, sd: c.sd.map(x => -x), wp: c.wp.map(x => x < 0 ? -1 : 100 - x), e: c.e.map(x => -x) } : { o: c.k, d: c.r });
          merged[key] = { D, P, V: {}, PL: S.players, n: S.n };
        }
        return merged[key];
      });
    }
    const x = wantX ? (extra[s] || (extra[s] = load(`data/plays/${s}_x.json`).catch(() => ({ cols: {}, vocab: {} })))) : Promise.resolve(null);
    return Promise.all([b, x]).then(([D, X]) => {
      const key = `${s}${X ? 'x' : ''}`;
      if (!merged[key]) merged[key] = { D, P: X ? Object.assign({}, D.cols, X.cols) : D.cols, V: X ? X.vocab || {} : {}, PL: D.players, n: D.n };
      return merged[key];
    });
  };
  const loadSeason = (s, wantX, side, wantG, wantOn) => loadSeason0(s, wantX, side)
    .then(m => Promise.all([wantG ? loadG(s, m.D) : null, wantOn ? loadOn(s, m.D) : null]).then(() => m));
  // the index, the latest season's teams, and the team options of the Opponent / Playing for filters
  const init = () => load('data/plays/index.json').then(ix => {
    IX = ix;
    return load(`data/plays/${ix.seasons[ix.seasons.length - 1]}.json`).then(d => {
      IX.teams = d.teams.slice().sort();
      const vsIn = ts => { const set = new Set(ts); return (P, j, G, V, D) => set.has(D.teams[P.d[j]]); };
      FILTERS.vs.opts = [
        ...['AFC', 'NFC'].map(c => [c, `against the ${c}`, vsIn(Object.keys(DIVS).filter(d => d.startsWith(c)).flatMap(d => DIVS[d]))]),
        ...Object.entries(DIVS).map(([d, ts]) => [d, `against the ${d}`, vsIn(ts)]),
        ...IX.teams.map(t => [t, `against ${t}`, (P, j, G, V, D) => D.teams[P.d[j]] === t])];
      FILTERS.tm.opts = IX.teams.map(t => [t, `playing for ${t}`, (P, j, G, V, D) => D.teams[P.o[j]] === t]);
      return IX;
    });
  });
  // player / coach search: names from the seasons in range (players carry their last season in range):
  // [[label, who value, name]] sorted
  const people = Q => Promise.all(spanSeasons(Q).map(s => loadSeason(s, false, FAM[Q.fam].st))).then(list => {
    const last = {}, coaches = new Set();
    list.forEach(({ D, PL }) => { PL.forEach(([g, n]) => { last[g] = [n, D.season]; }); (D.coaches || []).forEach(c => coaches.add(c)); });
    const opts = [];
    if (Q.fam !== 'team') Object.entries(last).forEach(([g, [n, s]]) => opts.push([`${n} (${s})`, `P:${g}`, n]));
    [...coaches].forEach(c => opts.push([`${c} (head coach)`, `C:${c}`, c]));
    return opts.sort((a, b) => a[0].localeCompare(b[0]));
  });
  // a team's players over the seasons in range, most plays first: role 'fam' (the measure's player), 'qb'
  // (dropbacks), 'any' (rushes + dropbacks + targets)
  const countPlayers = (Q, t, role) => Promise.all(spanSeasons(Q).map(s => loadSeason(s, false, FAM[Q.fam].st))).then(list => {
    const fam = FAM[Q.fam], cnt = new Map(), bump = (PL, a) => { if (a < 0) return; const [gid, nm] = PL[a], c = cnt.get(gid); if (c) c[1]++; else cnt.set(gid, [nm, 1]); };
    list.forEach(({ D, P, PL, n }) => {
      const ti = D.teams.indexOf(t), G = D.games, base2 = role !== 'fam' || !fam.st;
      if (ti < 0) return;
      const Pb = base2 ? D.cols : P, PLb = base2 ? D.players : PL, nb = base2 ? D.n : n;
      for (let j = 0; j < nb; j++) {
        if (Pb.o[j] !== ti) continue;
        const post = G[Pb.g[j]][2];
        if ((Q.st === 'reg' && post) || (Q.st === 'post' && !post)) continue;
        if (role === 'fam') { if (fam.play(Pb, j)) bump(PLb, fam.actor(Pb, j)); }
        else if (role === 'qb') { if (Pb.ty[j] === 1) bump(PLb, Pb.pp[j]); }
        else { bump(PLb, Pb.ru[j]); bump(PLb, Pb.pp[j]); bump(PLb, Pb.re[j]); }
      }
    });
    return [...cnt].sort((a, b) => b[1][1] - a[1][1]);
  });
  // the team a player had the most plays for in range (to open a teammate list on his team)
  const teamOfPlayer = (Q, gid) => Promise.all(spanSeasons(Q).map(s => loadSeason(s, false, false))).then(list => {
    const c = {};
    list.forEach(({ D }) => {
      const k = D.players.findIndex(p => p[0] === gid), P = D.cols;
      if (k < 0) return;
      for (let j = 0; j < D.n; j++) if (P.ru[j] === k || P.pp[j] === k || P.re[j] === k) c[D.teams[P.o[j]]] = (c[D.teams[P.o[j]]] || 0) + 1;
    });
    return Object.keys(c).sort((a, b) => c[b] - c[a])[0] || null;
  });

  // ---- counting: every play of the seasons in range through the query. Resolves to the sums (league, groups) and what
  // the page / CLI need to lay them out; nothing about the page in it.
  const compute = Q => {
    const all = spanSeasons(Q), need = needs(Q);
    const seasons = all.filter(s => covers(s, need)), dropped = all.filter(s => !seasons.includes(s));
    const wantX = need.some(c => XCOLS.has(c));
    const res = { Q, seasons, dropped, limiting: need.filter(c => dropped.some(s => !covers(s, [c]))).map(c => CNAME[c] || c),
      chartedIn: need.length ? IX.seasons.filter(s => covers(s, need)) : [], missG: [], missOn: [], empty: null };
    if (!seasons.length) return Promise.resolve(Object.assign(res, { empty: 'seasons' }));
    const wantG = Object.keys(Q.f).some(k => FILTERS[k].g);
    const wantOn = !!FAM[Q.fam].on || Object.keys(Q.f).some(k => FILTERS[k].on);
    const wantC = Object.keys(Q.f).some(k => FILTERS[k].bio) || ['college', 'rnd', 'age', 'cyr'].some(k => Q.by === k || Q.by2 === k);
    return Promise.all([...seasons.map(s => loadSeason(s, wantX, FAM[Q.fam].st, wantG, wantOn)), wantC ? loadBio() : null]).then(list => {
      list = list.slice(0, seasons.length);
      if (BIO) BIO.fam = Q.fam;
      RUNFAM = Q.fam;
      if (wantG) {  // a season without its game file (not built yet) is left out, and said so
        res.missG = list.filter(m => !m.D.gx).map(m => m.D.season);
        list = list.filter(m => m.D.gx);
      }
      if (wantOn) {  // on-field data: NFL participation, 2016-2025 (not published for the current season)
        res.missOn = list.filter(m => !m.D.on).map(m => m.D.season);
        list = list.filter(m => m.D.on);
        if (!list.length) return Object.assign(res, { empty: 'on' });
      }
      if (FAM[Q.fam].multi) list = list.map(m => Object.assign({}, m, { PL: m.D.on.pl }));
      const [fam, m] = famMetric(Q);
      const tests = Object.keys(Q.f).map(k => filterTest(Q, k)).filter(Boolean);
      const [wk, ...rest] = Q.who === 'L' ? ['L'] : Q.who.split(':'), wv = rest.join(':');
      // the route runner's position (an actor-level filter): FB counts as RB
      const posSet = fam.multi && Q.f.rpos ? new Set(vals(Q, 'rpos')) : null, POSG = { FB: 'RB' };
      const GMODE = GAMEBY.has(Q.by), gmeta = new Map();
      const by = BY[Q.by], by2 = !GMODE && Q.by2 && BY[Q.by2] ? BY[Q.by2] : null, groups = new Map(), league = blank(), names = {}, teamOf = {};
      let plays = 0;
      list.forEach(({ D, P, V, PL, n }) => {
        const G = D.games, T = D.teams;
        const wt = wk === 'T' || wk === 'V' ? T.indexOf(wv) : -2;
        const wp = wk === 'P' ? PL.findIndex(p => p[0] === wv) : -2;
        if (wk === 'P' && wp < 0) return;
        PL.forEach(([gid, nm]) => { names[gid] = nm; });
        for (let j = 0; j < n; j++) {
          const post = G[P.g[j]][2];
          if ((Q.st === 'reg' && post) || (Q.st === 'post' && !post)) continue;
          if (!fam.play(P, j)) continue;
          let ok = true;
          for (let k = 0; k < tests.length; k++) if (!tests[k](P, j, G, V, D)) { ok = false; break; }
          if (!ok) continue;
          // actors: the play's player(s), plus whoever took a lateral (credited yards / TD only, no carry or target)
          const acts = fam.multi ? fam.actors(P, j, D).map(x => [x, 0]) : [[fam.actor(P, j), 0]];
          if (fam.lat) { const L = fam.lat(P, j); if (L >= 0) acts.push([L, 1]); }
          for (let q = 0; q < acts.length; q++) {
            const [act, lat] = acts[q];
            if (act < 0 && !fam.teamActor) continue;
            if (posSet && !posSet.has(POSG[PL[act][2]] || PL[act][2])) continue;
            if (lat) fam.latAdd(league, P, j); else { common(league, P, j); fam.add(league, P, j, act, D); }
            if (wk === 'T' && P.o[j] !== wt) continue;
            if (wk === 'V' && P.d[j] !== wt) continue;
            if (wk === 'P' && act !== wp) continue;
            if (wk === 'C' && offCoach(P, j, G, D) !== wv) continue;
            let key;
            if (GMODE) {  // one group per player (team, for team offense) per game
              const ent = Q.fam === 'team' ? T[P.o[j]] : PL[act][0], g = G[P.g[j]];
              key = `${ent}|${D.season}|${P.g[j]}`;
              if (!gmeta.has(key)) gmeta.set(key, { ent, s: +D.season, w: g[1], post: g[2], opp: T[P.d[j]], home: P.o[j] === g[3], team: T[P.o[j]] });
              if (Q.fam !== 'team') teamOf[ent] = T[P.o[j]];
            } else if (Q.by === 'player') { key = PL[act][0]; teamOf[key] = T[P.o[j]]; } else key = by[1](P, j, G, D, V);
            if (key == null) continue;
            let k2 = null;
            if (by2) { k2 = by2[1](P, j, G, D, V); if (k2 == null) continue; }
            if (!lat) plays++;
            const gk = by2 ? `${key}||${k2}` : key;
            let a = groups.get(gk); if (!a) { a = blank(); a._k = [key, k2]; groups.set(gk, a); }
            if (lat) fam.latAdd(a, P, j); else { common(a, P, j); fam.add(a, P, j, act, D); }
          }
        }
      });
      const den = m[4] ? m[4][1] : (a => a.n), unit = m[4] ? m[4][0] : fam.unit[0].toUpperCase() + fam.unit.slice(1);
      // extra columns: other metrics of the family whose data every counted season has
      const extras = Object.entries(fam.met).filter(([k, mm]) => k !== Q.met && !COUNT[k] && seasons.every(s => covers(s, mm[3] || []))
        && (mm[3] || []).every(c => !XCOLS.has(c) || wantX)).slice(0, 5);
      return Object.assign(res, { fam, m, league, lg: m[1](league), den, unit, plays, groups, names, teamOf, gmeta, by, by2, GMODE, wk, extras });
    });
  };
  // the leaderboard rows ({ key, a, n, v, label, team })
  const tableRows = r => { const lab = BYLABEL[r.Q.by];
    return [...r.groups.entries()].map(([k, a]) => ({ key: k, a, n: r.den(a), v: r.m[1](a),
      label: r.Q.by === 'player' ? r.names[k] || k : lab ? lab(k) : String(k), team: r.Q.by === 'player' ? r.teamOf[k] : '' })); };
  // game by game: game logs, games reaching a mark (count, streak, most recent), best N-game stretches
  const gameLabel = g => `${g.s} ${g.post ? 'playoffs' : `wk ${g.w}`} ${g.home ? 'vs' : '@'} ${g.opp}`;
  const gameOrd = g => g.s * 100 + (g.post ? 50 : 0) + g.w;
  const gameRows = r => {
    const { Q, m, den, lg } = r, low = LOWER.has(Q.met), better = (x, y) => (low ? x < y : x > y);
    const items = [...r.groups.entries()].map(([k, a]) => ({ a, n: den(a), v: m[1](a), g: r.gmeta.get(k) }));
    const byEnt = new Map();
    items.forEach(x => { if (!byEnt.has(x.g.ent)) byEnt.set(x.g.ent, []); byEnt.get(x.g.ent).push(x); });
    byEnt.forEach(l => l.sort((x, y) => gameOrd(x.g) - gameOrd(y.g)));
    const mark = Q.gt != null ? Q.gt : MARK[Q.met] ? MARK[Q.met](Q.fam) : +lg.toFixed(m[2]);
    const hits = v => isFinite(v) && (low ? v <= mark : v >= mark);
    let rows;
    if (Q.by === 'pgame') rows = items.map(x => ({ ent: x.g.ent, g: x.g, n: x.n, v: x.v, a: x.a }));
    else if (Q.by === 'pmark') {
      rows = [...byEnt.entries()].map(([ent, l]) => {
        let run2 = 0, best = 0, last = null, n = 0, reach = 0;
        l.forEach(x => { n += x.n; if (hits(x.v)) { reach++; run2++; best = Math.max(best, run2); last = x.g; } else run2 = 0; });
        return { ent, n, v: reach, games: l.length, pct: (100 * reach) / l.length, streak: best, last };
      }).filter(x => x.v > 0);
    } else {
      const N = Q.gn;
      rows = [];
      byEnt.forEach((l, ent) => {
        let best = null;
        for (let i = 0; i + N <= l.length; i++) {
          const t = blank(); for (let q = i; q < i + N; q++) mergeAcc(t, l[q].a);
          const v = m[1](t);
          if (isFinite(v) && (!best || better(v, best.v))) best = { v, n: den(t), from: l[i].g, to: l[i + N - 1].g };
        }
        if (best) rows.push({ ent, ...best });
      });
    }
    return { rows, mark, low };
  };
  // the minimum, the sort (best first; a key's own order for season / week / down...) and the label of a row
  const keepRows = (r, rows, min) => {
    const { Q } = r, low = LOWER.has(Q.met), by = r.by;
    const out = rows.filter(x => x.n >= min);
    if (r.GMODE) return out.sort((x, y) => (Q.by === 'pmark' ? y.v - x.v || y.pct - x.pct : low ? x.v - y.v : y.v - x.v));
    return out.sort(by[3] === 'v' ? (x, y) => (low ? -1 : 1) * ((y.v || 0) - (x.v || 0)) : (x, y) => (by[3] === 'kd' ? -1 : 1) * (x.key > y.key ? 1 : x.key < y.key ? -1 : 0));
  };
  // one call for the CLI / an LLM: the question, the league line, notes on left-out seasons, and the rows (plain values)
  const num = (v, d) => (v == null || !isFinite(v) ? null : +(+v).toFixed(d));
  const answer = (q, { limit = 50 } = {}) => {
    const Q = normalize(q);
    return compute(Q).then(r => {
      const out = { question: describe(Q), query: Q, notes: [] };
      if (r.dropped.length) out.notes.push(`${r.limiting.join(', ') || 'Charting'} not charted for ${ranges(r.dropped)}: left out`);
      if (r.missG.length) out.notes.push(`game details not available for ${ranges(r.missG)}: left out`);
      if (r.missOn.length) out.notes.push(`on-field data (2016-2025 only) missing for ${ranges(r.missOn)}: left out`);
      if (r.empty) { out.rows = []; out.notes.push(r.empty === 'on' ? 'no seasons with on-field data in range' : 'no seasons have the data this query needs'); return out; }
      const { m, lg, unit, den, Q: q2 } = r, min = q2.min ?? defMin(q2);
      out.league = { metric: m[0], value: num(lg, m[2]), sample: r.league.n, unit: r.fam.unit };
      out.min = min;
      if (r.GMODE) {
        const g = gameRows(r), rows = keepRows(r, g.rows, min), isT = q2.fam === 'team';
        if (q2.by === 'pmark') out.mark = g.mark;
        out.total = rows.length;
        out.rows = rows.slice(0, limit).map(x => Object.assign({ [isT ? 'team' : 'player']: isT ? x.ent : r.names[x.ent] || x.ent }, isT ? {} : { id: x.ent, team: r.teamOf[x.ent] },
          q2.by === 'pgame' ? { game: gameLabel(x.g), [unit.toLowerCase()]: x.n, [m[0]]: num(x.v, m[2]) }
            : q2.by === 'pmark' ? { games_reaching: x.v, games: x.games, pct: num(x.pct, 1), longest_streak: x.streak, most_recent: x.last ? gameLabel(x.last) : null }
              : { [`${m[0]} (best ${q2.gn} games)`]: num(x.v, m[2]), [unit.toLowerCase()]: x.n, from: gameLabel(x.from), to: gameLabel(x.to) }));
        return out;
      }
      if (r.by2) {  // a grid: cells as rows of (row, column, value, sample)
        const lab = BYLABEL[q2.by], lab2 = BYLABEL[q2.by2];
        const cells = [...r.groups.values()].map(a => ({ [r.by[0]]: q2.by === 'player' ? r.names[a._k[0]] || a._k[0] : lab ? lab(numKey(a._k[0])) : String(a._k[0]),
          [r.by2[0]]: lab2 ? lab2(numKey(a._k[1])) : String(a._k[1]), [m[0]]: num(m[1](a), m[2]), [unit.toLowerCase()]: den(a) })).filter(x => x[unit.toLowerCase()] >= min);
        out.total = cells.length;
        out.rows = cells.sort((x, y) => y[unit.toLowerCase()] - x[unit.toLowerCase()]).slice(0, limit);
        return out;
      }
      const rows = keepRows(r, tableRows(r), min);
      out.total = rows.length;
      out.rows = rows.slice(0, limit).map(x => Object.assign({ [r.by[0]]: x.label }, q2.by === 'player' ? { id: x.key, team: x.team } : {},
        { [unit.toLowerCase()]: x.n }, COUNT[q2.met] ? {} : { [m[0]]: num(x.v, m[2]) }, { [m[2] === 0 ? 'share of league %' : 'vs league']: m[2] === 0 ? (lg > 0 ? num((100 * x.v) / lg, 1) : null) : num(x.v - lg, m[2]) },
        Object.fromEntries(r.extras.map(([, mm]) => [mm[0], num(mm[1](x.a), mm[2])]))));
      return out;
    });
  };
  // the catalog an LLM reads to write a query: measures, filters (values / ranges / players), breakdowns, seasons
  const schema = () => ({
    seasons: ranges(IX.seasons), teams: IX.teams,
    // a charted column, the seasons with it (a query only counts seasons that have every column it needs, and says so)
    charted: Object.fromEntries([...tracked()].map(c => [CNAME[c] || c, ranges(IX.seasons.filter(y => (IX.cov[y] || []).includes(c)))]).filter(x => x[1])),
    query: { fam: 'measure family', met: 'metric key', who: "'L' (league) | 'T:<team>' (a team's players / the team) | 'V:<team>' (against a team) | 'P:<gsis id>' | 'C:<coach name>'; with P / C set wn to the name",
      f: '{ filter: value or [values] (any of) }', fn: '{ filter: 1 } to exclude', by: 'breakdown', by2: 'optional second breakdown (a grid)', st: "'reg' | 'post' | 'both'",
      from: 'first season', to: 'last season', min: "minimum sample per row (default: the family's)", gt: 'mark for by=pmark', gn: 'stretch length for by=pspan',
      values: "option key; 'R:lo~hi' for a range (an end at the range's open min / max = no bound); 'gsis|Name' for a player filter; 's:School' or 'c:Conference' for college" },
    families: Object.fromEntries(Object.entries(FAM).map(([k, f]) => [k, { label: f.label, unit: f.unit, min: f.min, default_metric: FIRST[k],
      metrics: Object.fromEntries(Object.entries(f.met).map(([mk, mm]) => [mk, { label: mm[0], decimals: mm[2], needs: mm[3] || [], lower_is_better: LOWER.has(mk) }])) }])),
    filters: Object.fromEntries(Object.entries(FILTERS).map(([k, F]) => [k, Object.assign({ label: F.label, group: F.group },
      F.only ? { families: F.only } : {}, F.stOnly ? { special_teams_only: true } : {}, F.need ? { needs: F.need } : {}, F.hint ? { hint: F.hint } : {},
      F.opts && F.opts.length ? { options: F.opts.map(o => [o[0], o[1]]) } : {},
      F.range ? { range: { min: F.range.min, max: F.range.max, step: F.range.step || 1, open_low: !!F.range.openLo, open_high: !!F.range.openHi, unit: F.range.unit || '',
        presets: (F.range.presets || []).map(([l, a, b]) => [`R:${a}~${b}`, l]) } } : {},
      F.param ? { value: F.param === 'college' ? "'s:School' or 'c:Conference'" : "'gsis|Name' of a player" } : {}, F.noNot ? { no_exclude: true } : {})])),
    breakdowns: Object.fromEntries(Object.entries(BY).map(([k, b]) => [k, Object.assign({ label: b[0] }, b[2] && b[2].length ? { needs: b[2] } : {},
      GRID_ROW_ONLY.has(k) ? { rows_only: true } : {}, GAMEBY.has(k) ? { game_by_game: true } : {})])),
  });

  return {
    // definitions the page renders from
    FAM, FILTERS, BY, BYLABEL, EXAMPLES, FIRST, COUNT, LOWER, GAMEBY, GRID_ROW_ONLY, GRID_MAX_ROWS, GRID_MAX_COLS, MARK, GMIN, XCOLS, CNAME,
    blank, fmt, ranges, numKey, mergeAcc, allowed, byAllowed, parseR, isR, ordn, span,
    // the query
    defaults, normalize, famMetric, needs, covers, spanSeasons, vals, isNot, setF, optLabel, whoLabel, seasonsTxt, byTxt, gameTxt, markTxt,
    defMin, summaryParts, describe, UNITS, ST_TXT, cap,
    // data and counting
    init, ix: () => IX, bio, loadBio, people, countPlayers, teamOfPlayer, compute, tableRows, gameRows, gameLabel, gameOrd, keepRows, answer, schema,
  };
});
