// Players > Trends: a play-level query builder over every run and pass play since 1999 (data/plays/<season>.json +
// <season>_x.json charting, tools/trends_build.py). The query reads as a sentence of tappable chips ("Rushing YPC for
// BAL players, 4th quarter, 2022-2024, by player"); the answer is a leaderboard against the league in the same
// situation, with a minimum sample (smaller samples hidden), a trend line when grouped by season, and a
// shareable link (?t=..., read once then dropped). Everything is counted in the browser from the season files.
// Coverage: every filter / metric / grouping names the columns it needs; index.json lists, per season, the columns
// charted on >= 90% of the plays they apply to, and a query only counts seasons that have all it needs (and says
// which it left out), so a charting gap never reads as a zero.
(() => {
  const NFLE = window.NFLE, esc = NFLE.esc;
  const LS = 'nfledge-trends';
  // columns that live in <season>_x.json (participation + FTN charting): loaded only when a query needs one
  const XCOLS = new Set(['fm', 'op', 'db', 'bx', 'pr', 'tt', 'pz', 'mz', 'cv', 'rt', 'mo', 'px', 'sc', 'rp', 'tr', 'oo', 'iw', 'ta', 'cb', 'ct', 'dr', 'cr', 'bl', 'bf', 'rd']);
  const CNAME = { ay: 'air yards', yc: 'YAC', pl: 'pass location', rl: 'run direction', gp: 'run gap', cp: 'completion probability', xp: 'expected pass rate',
    xy: 'expected YAC', wp: 'win probability', wa: 'WPA', fm: 'QB alignment', op: 'personnel', db: 'defensive personnel', bx: 'box count', pr: 'pass rushers',
    tt: 'time to throw', pz: 'pressure', mz: 'man / zone', cv: 'coverage shell', rt: 'routes', mo: 'motion', px: 'play action', sc: 'screens', rp: 'RPOs',
    tr: 'trick plays', oo: 'pocket', iw: 'INT-worthy throws', ta: 'throwaways', cb: 'catchable balls', ct: 'contested balls', dr: 'drops',
    cr: 'created receptions', bl: 'blitzers', bf: 'backfield', rd: 'reads' };
  const FLAGS = ['tl', 'qh', 'pz', 'iw', 'ta', 'oo', 'px', 'mo', 'dr', 'cb', 'ct', 'cr', 'sg', 'nh', 'sc', 'rp'];
  // ---- metrics: [label, value from the sums, decimals, columns needed]
  const rate = c => a => 100 * a[c + 'n'] / a[c + 'd'];
  const FAM = {
    rush: { label: 'Rushing', unit: 'rushes', min: 20, play: (P, j) => P.ty[j] !== 1, actor: (P, j) => P.ru[j],
      add: (a, P, j) => { a.y += P.y[j]; a.td += P.td[j]; a.fd += P.fd[j]; a.x += P.y[j] >= 10; a.fl += P.fl[j]; },
      met: { ypc: ['YPC', a => a.y / a.n, 2], yds: ['Yards', a => a.y, 0], att: ['Rushes', a => a.n, 0], td: ['TDs', a => a.td, 0],
             epa: ['EPA / rush', a => a.e / 100 / a.n, 3], sr: ['Success %', a => 100 * a.s / a.n, 1], fd: ['1st down %', a => 100 * a.fd / a.n, 1],
             x: ['10+ yd %', a => 100 * a.x / a.n, 1], stuff: ['Stuffed %', rate('tl'), 1], fl: ['Fumbles lost', a => a.fl, 0],
             wpa: ['WPA', a => a.wa / 1000, 2, ['wa']] } },
    pass: { label: 'Passing', unit: 'dropbacks', min: 50, play: (P, j) => P.ty[j] === 1, actor: (P, j) => P.pp[j],
      add: (a, P, j) => { const sk = P.sk[j], att = P.pa[j] && !sk; a.att += att; a.c += P.c[j]; a.y += sk ? 0 : P.y[j]; a.td += P.td[j] && P.c[j];
        a.int += P.in[j]; a.sk += sk; if (att && P.ay[j] > -99) { a.ay += P.ay[j]; a.ayn++; } if (att && P.cp[j] > -999) { a.cp += P.cp[j]; a.cpn++; }
        if (P.tt && P.tt[j] >= 0) { a.tt += P.tt[j]; a.ttn++; } },
      met: { ypa: ['Yds / att', a => a.y / a.att, 2], cmp: ['Comp %', a => 100 * a.c / a.att, 1], yds: ['Yards', a => a.y, 0], td: ['TDs', a => a.td, 0],
             int: ['INTs', a => a.int, 0], epa: ['EPA / dropback', a => a.e / 100 / a.n, 3], sr: ['Success %', a => 100 * a.s / a.n, 1],
             skr: ['Sack %', a => 100 * a.sk / a.n, 1], att: ['Attempts', a => a.att, 0], adot: ['Air yds / att', a => a.ay / a.ayn, 1, ['ay']],
             cpoe: ['CPOE', a => a.cp / 10 / a.cpn, 1, ['cp']], pz: ['Pressure %', rate('pz'), 1, ['pz']], tt: ['Time to throw', a => a.tt / 10 / a.ttn, 2, ['tt']],
             qh: ['QB hit %', rate('qh'), 1], iw: ['INT-worthy %', rate('iw'), 1, ['iw']], ta: ['Throwaway %', rate('ta'), 1, ['ta']],
             oo: ['Out of pocket %', rate('oo'), 1, ['oo']], px: ['Play action %', rate('px'), 1, ['px']], wpa: ['WPA', a => a.wa / 1000, 2, ['wa']] } },
    rec: { label: 'Receiving', unit: 'targets', min: 15, play: (P, j) => P.ty[j] === 1 && P.re[j] >= 0, actor: (P, j) => P.re[j],
      add: (a, P, j) => { const c = P.c[j]; a.c += c; a.y += c ? P.y[j] : 0; a.td += P.td[j] && c;
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
    team: { label: 'Team offense', unit: 'plays', min: 50, play: () => true, actor: (P, j) => P.o[j], teamActor: true,
      add: (a, P, j) => { const db = P.ty[j] !== 0; a.y += P.y[j]; a.db += db; a.td += P.td[j]; a.fd += P.fd[j];
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
  const FIRST = { rush: 'ypc', pass: 'epa', rec: 'ypt', team: 'epa', fg: 'pct', xp: 'pct', punt: 'net', ko: 'tbr', kr: 'avg', pr: 'avg' };
  const COUNT = { att: 1, tgt: 1, plays: 1, punts: 1, kicks: 1, ret: 1 };  // metrics equal to the sample column: not repeated as extras
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
    wp: { label: 'Win probability', group: 'Situation', need: ['wp'], opts: [['ng', 'no garbage time (10-90%)', (P, j) => P.wp[j] >= 10 && P.wp[j] <= 90],
      ['close', 'competitive (25-75%)', (P, j) => P.wp[j] >= 25 && P.wp[j] <= 75], ['ahead', 'game in hand (90%+)', (P, j) => P.wp[j] > 90],
      ['behind', 'long shot (under 10%)', (P, j) => P.wp[j] >= 0 && P.wp[j] < 10]] },
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
    coach: ['head coach', offCoach, [], 'v'], season: ['season', (P, j, G, D) => D.season, [], 'kd'],
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
  const opt = (v, l, cur) => `<option value="${esc(v)}"${String(v) === String(cur) ? ' selected' : ''}>${esc(l)}</option>`;
  const sel = (cls, opts, val, label, extra = '') => `<select class="tr-chip ${cls}" aria-label="${esc(label)}"${extra}>${opts.map(([v, l]) => opt(v, l, val)).join('')}</select>`;
  const ranges = ys => { const out = []; ys.forEach(y => { const r = out[out.length - 1]; if (r && r[1] === y - 1) r[1] = y; else out.push([y, y]); });
    return out.map(([a, b]) => a === b ? `${a}` : `${a}-${b}`).join(', '); };
  // special teams take the game / situation filters (and their own); offense filters don't apply to kicks
  const ST_FILTERS = new Set(['qtr', 'score', 'time', 'wp', 'site', 'week', 'roof', 'surf', 'wx', 'div', 'line', 'total']);
  const ST_BY = new Set(['player', 'team', 'opp', 'coach', 'season', 'week', 'qtr', 'score', 'roof', 'surf', 'kdist']);
  const allowed = (k, fam) => {
    const F = FILTERS[k], only = !F.only || F.only.includes(fam);
    return FAM[fam].st ? (ST_FILTERS.has(k) || (F.stOnly && only)) : !F.stOnly && only;
  };
  const byAllowed = (k, fam) => FAM[fam].st ? ST_BY.has(k) : k !== 'kdist';
  // Two-way grids (owner 2026-10-14): a second grouping makes the answer a shaded rows x columns grid. Groupings with
  // dozens of values (players, teams, coaches) work as rows only; columns must fit a phone (capped, scrolls past that).
  const GRID_ROW_ONLY = new Set(['player', 'team', 'opp', 'coach']);
  const GRID_MAX_ROWS = 40, GRID_MAX_COLS = 24;
  // metrics where a lower number is the good one (the grid shades those the other way)
  const LOWER = new Set(['skr', 'int', 'stuff', 'fl', 'drop', 'iw', 'ta', 'pz', 'qh', 'rya', 'bk', 'miss']);
  const numKey = x => (x !== '' && x != null && !isNaN(x) ? +x : x);

  let TEAMS = {};  // the week data's teams map (tile colors, logos)
  NFLE.areas.trends = {
    mount(sec) {
      NFLE.week().then(D => { if (D && D.teams) { TEAMS = D.teams; if (paint) paint(); } });
      sec.classList.remove('soon');
      let IX = null, Q = null, busy = 0, paint = null, maxN = 0;
      const base = {}, extra = {}, merged = {};
      const defaults = () => ({ fam: 'rush', met: 'ypc', who: 'L', wn: '', by: 'player', by2: '', st: 'reg', from: null, to: null, f: {}, min: null });
      const fromUrl = () => { try { const t = new URLSearchParams(location.search).get('t'); return t ? JSON.parse(decodeURIComponent(escape(atob(t)))) : null; } catch (e) { return null; } };
      const saved = () => { try { return JSON.parse(localStorage.getItem(LS) || 'null'); } catch (e) { return null; } };
      sec.innerHTML = `<div class="sec-head"><div><h2>Trends</h2><p>Ask the play-by-play anything: every run and pass since 1999, with charting (personnel, coverage, routes, pressure, play action...) where it exists. Tap any word to change it.</p></div></div>
        <div class="dt-card tr-card"><div class="tr-q"></div><div class="tr-ex"></div></div>
        <div class="tr-base muted"></div><div class="tr-cov"></div><div class="tr-trend"></div><div class="tr-tbl"></div>
        <datalist id="tr-dl"></datalist>
        <p class="st-note muted">nflverse play-by-play (1999 on); NGS participation charting (2016-2025: formation, personnel, box, rushers, pressure, time to throw, routes, coverage) and FTN charting (2022 on, CC-BY-SA: motion, play action, RPOs, screens, blitzes, pocket, reads, drops, catchable / contested balls). A query only counts seasons where everything it uses was charted, and says which it left out. Rushing counts designed runs and QB scrambles; passing counts dropbacks (sacks included; yards per attempt and completion % use pass attempts). EPA = expected points added; CPOE = completion % over expected; pass rate over expected uses nflverse's xpass model, whose league average is not exactly zero, so read it against the league column. Rows under the minimum sample are hidden (the count is shown): small samples make loud, fake trends. Special teams (kickoffs, punts, field goals, extra points) read from the kicker's side, returns from the returner's; net punting = distance minus return yards, minus 20 for a touchback. Route names were re-charted in 2023, so outs, flats and swings are one group.</p>`;
      const qbox = sec.querySelector('.tr-q');
      sec.querySelector('.tr-ex').innerHTML = `<span class="muted">Try:</span> ${EXAMPLES.map((e, i) => `<button type="button" class="tr-exb" data-ex="${i}">${esc(e[0])}</button>`).join('')}`;

      // ---- what a query needs, and which seasons have it
      const famMetric = () => { const fam = FAM[Q.fam]; return [fam, fam.met[Q.met] || Object.values(fam.met)[0]]; };
      const needs = () => {
        const [, m] = famMetric(), s = new Set(m[3] || []);
        Object.keys(Q.f).forEach(k => (FILTERS[k].need || []).forEach(c => s.add(c)));
        (BY[Q.by][2] || []).forEach(c => s.add(c));
        if (Q.by2 && BY[Q.by2]) (BY[Q.by2][2] || []).forEach(c => s.add(c));
        return [...s];
      };
      const tracked = () => new Set(IX.tracked || Object.keys(CNAME));
      const covers = (s, cols) => { const have = IX.cov[s] || [], tr = tracked(); return cols.every(c => !tr.has(c) || have.includes(c)); };
      const spanSeasons = () => IX.seasons.filter(s => s >= Q.from && s <= Q.to);

      // ---- the sentence
      const render = () => {
        const fam = FAM[Q.fam], teams = IX.teams;
        const whoOpts = [['L', 'the whole league'], ...teams.map(t => [`T:${t}`, `${t} ${Q.fam === 'team' ? 'offense' : 'players'}`]), ...teams.map(t => [`V:${t}`, `against ${t}`])];
        if (/^[PC]:/.test(Q.who)) whoOpts.unshift([Q.who, Q.who[0] === 'C' ? `${Q.wn}'s offense` : Q.wn]);
        whoOpts.push(['S', Q.fam === 'team' ? 'find a head coach...' : 'find a player or coach...']);
        const metSel = sel('tr-met', Object.entries(fam.met).map(([k, m]) => [k, m[0]]), Q.met, 'Metric');
        const who = Q.who === 'S' ? `<input class="tr-chip tr-find" list="tr-dl" placeholder="type a name" aria-label="Find a player or coach" autocomplete="off">`
          : sel('tr-who', whoOpts, Q.who, 'Who');
        const yrs = IX.seasons.map(s => [s, s]);
        const span = `${sel('tr-from', yrs, Q.from, 'From season')}<span class="tr-w">to</span>${sel('tr-to', yrs, Q.to, 'To season')}`;
        const st = sel('tr-st', [['reg', 'regular season'], ['post', 'playoffs'], ['both', 'regular season + playoffs']], Q.st, 'Season type');
        const by2 = sel(`tr-by2${Q.by2 ? '' : ' tr-off'}`, [['', 'nothing else'], ...Object.entries(BY).filter(([k]) => k !== Q.by && !GRID_ROW_ONLY.has(k) && byAllowed(k, Q.fam)).map(([k, b]) => [k, b[0]])], Q.by2 || '', 'Then by (grid)');
        const by = sel('tr-by', Object.entries(BY).filter(([k]) => byAllowed(k, Q.fam) && !(k === 'player' && (Q.fam === 'team' || /^P:/.test(Q.who)))).map(([k, b]) => [k, b[0]]), Q.by, 'Group by');
        const chips = Object.entries(Q.f).map(([k, v]) => `<span class="tr-fchip">${sel('tr-f', FILTERS[k].opts.map(o => [o[0], o[1]]), v, FILTERS[k].label, ` data-f="${k}"`)}<button type="button" class="tr-x" data-x="${k}" aria-label="Remove">&times;</button></span>`).join('');
        const groups = {};
        Object.entries(FILTERS).filter(([k]) => !(k in Q.f) && allowed(k, Q.fam)).forEach(([k, f]) => { (groups[f.group] = groups[f.group] || []).push([k, f.label]); });
        const add = `<select class="tr-chip tr-add" aria-label="Add a filter"><option value="">+ filter</option>${Object.entries(groups).map(([g, fs]) => `<optgroup label="${esc(g)}">${fs.map(([k, l]) => opt(k, l)).join('')}</optgroup>`).join('')}</select>`;
        qbox.innerHTML = `<div class="tr-line">${sel('tr-fam', Object.entries(FAM).map(([k, f]) => [k, f.label]), Q.fam, 'Stat family')} ${metSel} <span class="tr-w">for</span> ${who}</div>
          <div class="tr-line">${chips} ${add}</div>
          <div class="tr-line">${span} <span class="tr-w">&middot;</span> ${st} <span class="tr-w">&middot; by</span> ${by} <span class="tr-w">and</span> ${by2}</div>
          <div class="tr-line tr-tools"><div class="tr-min"><span class="tr-w">min</span><button type="button" class="tr-step" data-step="-1" aria-label="One fewer">&minus;</button><input type="range" min="0" max="${Math.max(maxN, Q.min ?? fam.min, fam.min * 2)}" step="1" value="${Q.min ?? fam.min}" aria-label="Minimum sample"><button type="button" class="tr-step" data-step="1" aria-label="One more">+</button> <b>${Q.min ?? fam.min}</b> <span class="tr-w">${esc(fam.unit)}</span></div>
            <button type="button" class="tr-share">Copy link</button></div>`;
        const f = qbox.querySelector('.tr-find'); if (f) { fillFind(); f.focus(); }
      };
      const save = () => { try { localStorage.setItem(LS, JSON.stringify(Q)); } catch (e) { /* private mode */ } };

      // ---- loading: base file per season; charting file only when the query needs a charting column
      const stv = {};
      const loadSeason = (s, wantX, side) => {
        const b = base[s] || (base[s] = NFLE.load(`data/plays/${s}.json`));
        if (side) {
          const st = stv[s] || (stv[s] = NFLE.load(`data/plays/${s}_st.json`));
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
        const x = wantX ? (extra[s] || (extra[s] = NFLE.load(`data/plays/${s}_x.json`).catch(() => ({ cols: {}, vocab: {} })))) : Promise.resolve(null);
        return Promise.all([b, x]).then(([D, X]) => {
          const key = `${s}${X ? 'x' : ''}`;
          if (!merged[key]) merged[key] = { D, P: X ? Object.assign({}, D.cols, X.cols) : D.cols, V: X ? X.vocab || {} : {}, PL: D.players, n: D.n };
          return merged[key];
        });
      };
      // player / coach search: names from the seasons in range (players carry their last season in range)
      const fillFind = () => {
        Promise.all(spanSeasons().map(s => loadSeason(s, false, FAM[Q.fam].st))).then(list => {
          const last = {}, coaches = new Set();
          list.forEach(({ D, PL }) => { PL.forEach(([g, n]) => { last[g] = [n, D.season]; }); (D.coaches || []).forEach(c => coaches.add(c)); });
          const opts = [];
          if (Q.fam !== 'team') Object.entries(last).forEach(([g, [n, s]]) => opts.push([`${n} (${s})`, `P:${g}`, n]));
          [...coaches].forEach(c => opts.push([`${c} (head coach)`, `C:${c}`, c]));
          opts.sort((a, b) => a[0].localeCompare(b[0]));
          findMap = new Map(opts.map(o => [o[0], o]));
          sec.querySelector('#tr-dl').innerHTML = opts.map(o => `<option value="${esc(o[0])}"></option>`).join('');
        });
      };
      let findMap = new Map();

      const run = () => {
        const me = ++busy, all = spanSeasons(), need = needs();
        const seasons = all.filter(s => covers(s, need)), dropped = all.filter(s => !seasons.includes(s));
        const wantX = need.some(c => XCOLS.has(c));
        const covEl = sec.querySelector('.tr-cov');
        const limiting = need.filter(c => dropped.some(s => !covers(s, [c]))).map(c => CNAME[c] || c);
        const chartedIn = need.length ? IX.seasons.filter(s => covers(s, need)) : [];
        covEl.innerHTML = dropped.length ? `<p class="tr-covnote">${esc(limiting.join(', ') || 'Charting')} ${limiting.length > 1 ? 'are' : 'is'} not charted for ${esc(ranges(dropped))}, so ${dropped.length > 1 ? 'those seasons are' : 'that season is'} left out${chartedIn.length ? ` (charted: ${esc(ranges(chartedIn))})` : ''}.</p>` : '';
        if (Q.who === 'S') return;
        if (!seasons.length) { sec.querySelector('.tr-base').textContent = ''; sec.querySelector('.tr-trend').innerHTML = ''; sec.querySelector('.tr-tbl').innerHTML = ''; paint = null; return; }
        sec.querySelector('.tr-base').textContent = 'Counting plays…';
        Promise.all(seasons.map(s => loadSeason(s, wantX, FAM[Q.fam].st))).then(list => {
          if (me !== busy) return;
          const [fam, m] = famMetric();
          const tests = Object.entries(Q.f).map(([k, v]) => (FILTERS[k].opts.find(o => o[0] === v) || [])[2]).filter(Boolean);
          const [wk, ...rest] = Q.who === 'L' ? ['L'] : Q.who.split(':'), wv = rest.join(':');
          const by = BY[Q.by], by2 = Q.by2 && BY[Q.by2] ? BY[Q.by2] : null, groups = new Map(), league = blank(), names = {}, teamOf = {};
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
              for (let k = 0; k < tests.length; k++) if (!tests[k](P, j, G, V)) { ok = false; break; }
              if (!ok) continue;
              const act = fam.actor(P, j);
              if (act < 0 && !fam.teamActor) continue;
              common(league, P, j); fam.add(league, P, j);
              if (wk === 'T' && P.o[j] !== wt) continue;
              if (wk === 'V' && P.d[j] !== wt) continue;
              if (wk === 'P' && act !== wp) continue;
              if (wk === 'C' && offCoach(P, j, G, D) !== wv) continue;
              let key;
              if (Q.by === 'player') { key = PL[act][0]; teamOf[key] = T[P.o[j]]; } else key = by[1](P, j, G, D, V);
              if (key == null) continue;
              let k2 = null;
              if (by2) { k2 = by2[1](P, j, G, D, V); if (k2 == null) continue; }
              plays++;
              const gk = by2 ? `${key}||${k2}` : key;
              let a = groups.get(gk); if (!a) { a = blank(); a._k = [key, k2]; groups.set(gk, a); }
              common(a, P, j); fam.add(a, P, j);
            }
          });
          const lg = m[1](league), lab = BYLABEL[Q.by];
          const den = m[4] ? m[4][1] : (a => a.n), unit = m[4] ? m[4][0] : fam.unit[0].toUpperCase() + fam.unit.slice(1);
          const rows = [...groups.entries()].map(([k, a]) => ({ key: k, a, n: den(a), v: m[1](a),
            label: Q.by === 'player' ? names[k] || k : lab ? lab(k) : String(k), team: Q.by === 'player' ? teamOf[k] : '' }));
          maxN = rows.reduce((mx, r) => Math.max(mx, r.n), 0);
          const slider = qbox.querySelector('.tr-min input');
          if (slider) slider.max = Math.max(maxN, Q.min ?? fam.min, fam.min * 2);
          const whoTxt = wk === 'L' ? '' : ` &middot; this query: ${fmt(plays)} ${esc(fam.unit)}`;
          if (by2) {
            sec.querySelector('.tr-base').innerHTML = `League, same situation: <b>${fmt(lg, m[2])}</b> ${esc(m[0])} on ${fmt(league.n)} ${esc(fam.unit)}${whoTxt}`;
            sec.querySelector('.tr-trend').innerHTML = '';
            const lab2 = BYLABEL[Q.by2], tb = sec.querySelector('.tr-tbl');
            const rowLab = k => Q.by === 'player' ? names[k] || k : lab ? lab(numKey(k)) : String(k);
            const colLab = k => lab2 ? lab2(numKey(k)) : String(k);
            const cells = [...groups.values()].map(a => ({ r: a._k[0], c: a._k[1], a, n: den(a), v: m[1](a) }));
            const order = (keys, how, tot) => how === 'v' ? keys.sort((x, y) => tot.get(y) - tot.get(x))
              : keys.sort((x, y) => { const p = numKey(x), q = numKey(y), d = typeof p === 'number' && typeof q === 'number' ? p - q : String(p).localeCompare(String(q)); return how === 'kd' ? -d : d; });
            const totR = new Map(), totC = new Map(), allR = new Map();
            // each row's overall accumulator (the "All" column, and the order of player / team rows: best first)
            const merge = (t, a) => { Object.keys(a).forEach(k => { if (k !== '_k') t[k] = k === 'lg' ? Math.max(t[k] || 0, a[k]) : (t[k] || 0) + a[k]; }); return t; };
            cells.forEach(x => { totR.set(x.r, (totR.get(x.r) || 0) + x.n); totC.set(x.c, (totC.get(x.c) || 0) + x.n);
              allR.set(x.r, merge(allR.get(x.r) || blank(), x.a)); });
            const rowV = r => { const a = allR.get(r); const v = m[1](a); return den(a) >= (Q.min ?? fam.min) && isFinite(v) ? v : null; };
            const byMetric = keys => keys.sort((x, y) => { const p = rowV(x), q = rowV(y); if (p == null || q == null) return (p == null) - (q == null) || totR.get(y) - totR.get(x); return LOWER.has(Q.met) ? p - q : q - p; });
            const rowsK = by[3] === 'v' ? byMetric([...totR.keys()]) : order([...totR.keys()], by[3], totR), colsK = order([...totC.keys()], by2[3], totC);
            // too many: keep the biggest samples, then restore the grouping's own order
            const keep = (keys, tot, cap, how) => keys.length <= cap ? keys : order([...keys].sort((x, y) => tot.get(y) - tot.get(x)).slice(0, cap), how, tot);
            const R = rowsK.length <= GRID_MAX_ROWS ? rowsK : by[3] === 'v' ? byMetric([...rowsK].sort((x, y) => totR.get(y) - totR.get(x)).slice(0, GRID_MAX_ROWS)) : keep(rowsK, totR, GRID_MAX_ROWS, by[3]);
            const C = keep(colsK, totC, GRID_MAX_COLS, by2[3]);
            const at = new Map(cells.map(x => [`${x.r}||${x.c}`, x]));
            const lowGood = LOWER.has(Q.met), count = m[2] === 0;
            const draw = () => {
              const min = Q.min ?? fam.min, shown = cells.filter(x => x.n >= min && isFinite(x.v));
              const spread = count ? Math.max(1, ...shown.map(x => x.v)) : Math.max(1e-9, ...shown.map(x => Math.abs(x.v - lg)));
              const shade = x => {
                if (count) return `background: color-mix(in srgb, var(--accent) ${Math.round(8 + 52 * x.v / spread)}%, var(--panel2))`;
                const d = x.v - lg, good = lowGood ? d < 0 : d > 0, w = Math.round(8 + 52 * Math.min(1, Math.abs(d) / spread));
                return `background: color-mix(in srgb, ${good ? '#4fbf6f' : '#d9655b'} ${w}%, var(--panel2))`;
              };
              const hidden = cells.filter(x => x.n < min).length;
              const head = `<tr><th class="tr-gc0">${esc(by[0])} <span class="muted">/</span> ${esc(by2[0])}</th>${C.map(c => `<th>${['team', 'opp'].includes(Q.by2) ? NFLE.ui.tm(c, esc(colLab(c))) : esc(colLab(c))}</th>`).join('')}<th class="tr-gall">All</th></tr>`;
              const allCell = r => { const a = allR.get(r), n = den(a), v = m[1](a);
                return n >= min && isFinite(v) ? `<td class="tr-gall" style="${shade({ v, n })}"><b>${fmt(v, m[2])}</b><i>${fmt(n)}</i></td>` : '<td class="tr-ge tr-gall">&middot;</td>'; };
              const body = R.map(r => `<tr><th class="tr-gc0"${Q.by === 'player' && /^\d\d-\d{7}$/.test(r) ? ` data-open-pid="${esc(r)}"` : ''}>${['team', 'opp'].includes(Q.by) ? NFLE.ui.tm(r, esc(rowLab(r))) : esc(rowLab(r))}${Q.by === 'player' && teamOf[r] ? ` <span class="sub">${NFLE.ui.tm(teamOf[r])}</span>` : ''}</th>${C.map(c => {
                const x = at.get(`${r}||${c}`);
                if (!x || x.n < min || !isFinite(x.v)) return `<td class="tr-ge" title="${x ? `${fmt(x.n)} ${esc(unit.toLowerCase())}: under the minimum` : 'none'}">&middot;</td>`;
                return `<td style="${shade(x)}" title="${esc(rowLab(r))} / ${esc(colLab(c))}: ${fmt(x.v, m[2])} ${esc(m[0])} on ${fmt(x.n)} ${esc(unit.toLowerCase())}"><b>${fmt(x.v, m[2])}</b><i>${fmt(x.n)}</i></td>`;
              }).join('')}${allCell(r)}</tr>`).join('');
              const capped = (R.length < rowsK.length ? ` Showing the ${R.length} ${esc(by[0])} rows with the most ${esc(fam.unit)}.` : '') + (C.length < colsK.length ? ` Showing ${C.length} of ${colsK.length} columns.` : '');
              tb.innerHTML = `<p class="tr-gnote muted">${count ? 'Darker = more.' : `Green = better than the league (${fmt(lg, m[2])}), red = worse.`} Small number = ${esc(unit.toLowerCase())}.${hidden ? ` ${hidden} cell${hidden === 1 ? '' : 's'} under ${min} hidden (&middot;).` : ''}${capped}</p>
                <div class="tr-gwrap"><table class="tr-grid"><thead>${head}</thead><tbody>${body}</tbody></table></div>`;
            };
            maxN = cells.reduce((mx, x) => Math.max(mx, x.n), 0);
            const slider = qbox.querySelector('.tr-min input');
            if (slider) slider.max = Math.max(maxN, Q.min ?? fam.min, fam.min * 2);
            paint = draw; draw();
            return;
          }
          sec.querySelector('.tr-base').innerHTML = `League, same situation: <b>${fmt(lg, m[2])}</b> ${esc(m[0])} on ${fmt(league.n)} ${esc(fam.unit)}${whoTxt}`;
          const trend = sec.querySelector('.tr-trend');
          if (Q.by === 'season' && rows.length > 1) {
            const r = rows.filter(x => isFinite(x.v)).sort((x, y) => x.key - y.key), vs = r.map(x => x.v), lo = Math.min(...vs, lg), hi = Math.max(...vs, lg), W = 320, H = 90;
            const X = i => 14 + i * (W - 28) / Math.max(1, r.length - 1), Y = v => H - 16 - (v - lo) / ((hi - lo) || 1) * (H - 30);
            trend.innerHTML = `<svg class="tr-svg" viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(m[0])} by season"><line x1="10" x2="${W - 10}" y1="${Y(lg)}" y2="${Y(lg)}" class="tr-lg"/>
              <polyline points="${r.map((x, i) => `${X(i)},${Y(x.v)}`).join(' ')}" class="tr-pl"/>${r.map((x, i) => `<circle cx="${X(i)}" cy="${Y(x.v)}" r="3" class="tr-pt"><title>${x.key}: ${fmt(x.v, m[2])}</title></circle>
              <text x="${X(i)}" y="${H - 2}" class="tr-yr">${String(x.key).slice(2)}</text>`).join('')}</svg>`;
          } else trend.innerHTML = '';
          // extra columns: other metrics of the family whose data every counted season has
          const extras = Object.entries(fam.met).filter(([k, mm]) => k !== Q.met && !COUNT[k] && seasons.every(s => covers(s, mm[3] || []))
            && (mm[3] || []).every(c => !XCOLS.has(c) || wantX)).slice(0, 5);
          const isTeam = Q.by === 'team' || Q.by === 'opp';
          const cols = [
            { key: 'label', label: by[0][0].toUpperCase() + by[0].slice(1), stick: true, first: 'asc', value: r => by[3] === 'v' ? r.label : r.key,
              html: r => Q.by === 'player' ? NFLE.ui.player({ name: r.label, team: r.team }, TEAMS)
                : isTeam ? NFLE.ui.team(r.key, TEAMS) : `<b>${esc(r.label)}</b>` },
            { key: 'n', label: unit, num: true, value: r => r.n, html: r => fmt(r.n) },
            { key: 'v', label: m[0], num: true, cls: 'tr-main', value: r => isFinite(r.v) ? r.v : null, html: r => `<b>${fmt(r.v, m[2])}</b>` },
            // rates compare with the league rate; counts (0 decimals: yards, catches, TDs...) as a share of the league total
            m[2] === 0
              ? { key: 'dv', label: 'Share of league', num: true, value: r => lg > 0 ? r.v / lg : null,
                  html: r => lg > 0 ? `<span title="League total ${fmt(lg, m[2])}">${(100 * r.v / lg).toFixed(1)}%</span>` : '–' }
              : { key: 'dv', label: 'vs league', num: true, value: r => isFinite(r.v) ? r.v - lg : null,
                  html: r => { const d = r.v - lg; return isFinite(d) ? `<span title="League ${fmt(lg, m[2])}" class="${d > 0 ? 'tr-up' : d < 0 ? 'tr-dn' : ''}">${d > 0 ? '+' : ''}${fmt(d, m[2])}</span>` : '–'; } },
            ...extras.map(([k, mm]) => ({ key: `m_${k}`, label: mm[0], num: true,
              value: r => { const v = mm[1](r.a); return isFinite(v) ? v : null; }, html: r => fmt(mm[1](r.a), mm[2]) })),
          ];
          const tb = sec.querySelector('.tr-tbl');
          if (!rows.length) { tb.innerHTML = '<p class="muted">No plays match.</p>'; paint = null; return; }
          const sort = by[3] === 'v' ? { key: 'v', dir: 'desc' } : { key: 'label', dir: by[3] === 'kd' ? 'desc' : 'asc' };
          // player / team rows are team-colored tiles like every other list (NFLE.ui); other groupings stay plain
          const tiled = Q.by === 'player' || isTeam, tm = r => Q.by === 'player' ? r.team : r.key;
          const o = { columns: cols, rows, sort, cls: tiled ? 'tiles' : '',
            rowClass: () => tiled ? `teamrow${isTeam ? ' tm-open' : ''}` : '',
            rowAttrs: r => `${tiled ? NFLE.ui.tileStyle(TEAMS, tm(r)) : ''}${Q.by === 'player' && /^\d\d-\d{7}$/.test(r.key) ? ` data-open-pid="${esc(r.key)}"` : ''}${isTeam ? ` data-tm="${esc(r.key)}"` : ''}` };
          paint = () => {
            const min = Q.min ?? fam.min, keep = rows.filter(r => r.n >= min), hid = rows.length - keep.length;
            tb.innerHTML = '';
            if (!keep.length) { tb.innerHTML = `<p class="muted">All ${rows.length} rows have fewer than ${min} ${esc(unit.toLowerCase())}. Lower the minimum to see them.</p>`; return; }
            NFLE.Table(tb, Object.assign(o, { rows: keep }));
            if (hid) tb.insertAdjacentHTML('beforeend', `<p class="tr-hid muted">${hid} ${hid === 1 ? 'row' : 'rows'} under ${min} ${esc(unit.toLowerCase())} hidden.</p>`);
          };
          paint();
        }).catch(e => { sec.querySelector('.tr-base').textContent = `Couldn't load plays (${e.message}).`; });
      };
      const update = () => { save(); render(); run(); };

      // ---- events (delegated: the sentence redraws on every change)
      qbox.addEventListener('change', e => {
        const t = e.target;
        if (t.matches('.tr-fam')) {
          Q.fam = t.value; Q.met = FIRST[Q.fam]; Q.min = null;
          if (Q.fam === 'team' && Q.by === 'player') Q.by = 'team';
          if (Q.fam === 'team' && /^P:/.test(Q.who)) { Q.who = 'L'; Q.wn = ''; }
          Object.keys(Q.f).forEach(k => { if (!allowed(k, Q.fam)) delete Q.f[k]; });
          if (!byAllowed(Q.by, Q.fam)) Q.by = Q.fam === 'team' ? 'team' : 'player';
          if (Q.by2 && !byAllowed(Q.by2, Q.fam)) Q.by2 = '';
          maxN = 0;
        } else if (t.matches('.tr-met')) Q.met = t.value;
        else if (t.matches('.tr-who')) { Q.who = t.value; if (!/^[PC]:/.test(Q.who)) Q.wn = ''; if (/^P:/.test(Q.who) && Q.by === 'player') Q.by = 'season'; }
        else if (t.matches('.tr-find')) {
          const hit = findMap.get(t.value); if (!hit) return;
          Q.who = hit[1]; Q.wn = hit[2]; if (/^P:/.test(Q.who) && Q.by === 'player') Q.by = 'season';
        } else if (t.matches('.tr-from')) { Q.from = +t.value; if (Q.to < Q.from) Q.to = Q.from; }
        else if (t.matches('.tr-to')) { Q.to = +t.value; if (Q.from > Q.to) Q.from = Q.to; }
        else if (t.matches('.tr-st')) Q.st = t.value;
        else if (t.matches('.tr-by')) { Q.by = t.value; if (Q.by2 === Q.by) Q.by2 = ''; }
        else if (t.matches('.tr-by2')) Q.by2 = t.value;
        else if (t.matches('.tr-f')) Q.f[t.dataset.f] = t.value;
        else if (t.matches('.tr-add') && t.value) Q.f[t.value] = FILTERS[t.value].opts[0][0];
        else return;
        update();
      });
      qbox.addEventListener('input', e => {
        if (e.target.matches('.tr-find')) { if (findMap.has(e.target.value)) e.target.dispatchEvent(new Event('change', { bubbles: true })); return; }
        if (!e.target.matches('.tr-min input')) return;
        Q.min = +e.target.value; qbox.querySelector('.tr-min b').textContent = Q.min; save();
        if (paint) paint();  // re-filter only: the counts don't depend on the minimum
      });
      qbox.addEventListener('focusout', e => {
        // leaving the search box without picking a name goes back to the previous choice
        if (e.target.matches('.tr-find') && Q.who === 'S') setTimeout(() => { if (Q.who === 'S' && !qbox.contains(document.activeElement)) { Q.who = 'L'; update(); } }, 200);
      });
      qbox.addEventListener('click', e => {
        const stp = e.target.closest('.tr-step');
        if (stp) {
          const inp = qbox.querySelector('.tr-min input'), cur = Q.min ?? FAM[Q.fam].min;
          Q.min = Math.max(0, Math.min(+inp.max, cur + +stp.dataset.step));
          inp.value = Q.min; qbox.querySelector('.tr-min b').textContent = Q.min; save();
          if (paint) paint();
          return;
        }
        const x = e.target.closest('[data-x]');
        if (x) { delete Q.f[x.dataset.x]; update(); return; }
        if (e.target.closest('.tr-share')) {
          const t = btoa(unescape(encodeURIComponent(JSON.stringify(Q))));
          const url = `${location.origin}${location.pathname}?t=${encodeURIComponent(t)}#players/trends`;
          const done = () => { const b = e.target.closest('.tr-share'); b.textContent = 'Link copied'; setTimeout(() => { b.textContent = 'Copy link'; }, 1600); };
          if (navigator.share && matchMedia('(pointer: coarse)').matches) navigator.share({ url }).catch(() => {});
          else if (navigator.clipboard) navigator.clipboard.writeText(url).then(done, () => prompt('Copy this link', url));
          else prompt('Copy this link', url);
        }
      });
      sec.querySelector('.tr-ex').addEventListener('click', e => {
        const b = e.target.closest('[data-ex]'); if (!b) return;
        Q = Object.assign(defaults(), { from: Q.from, to: Q.to }, JSON.parse(JSON.stringify(EXAMPLES[+b.dataset.ex][1])));
        update();
      });
      NFLE.load('data/plays/index.json').then(ix => {
        IX = ix;
        return NFLE.load(`data/plays/${ix.seasons[ix.seasons.length - 1]}.json`).then(d => { IX.teams = d.teams.slice().sort(); });
      }).then(() => {
        const last = IX.seasons[IX.seasons.length - 1];
        Q = Object.assign(defaults(), saved() || {}, fromUrl() || {});
        // a shared link seeds the query once; drop ?t= so later edits (saved locally) survive a reload
        if (location.search.includes('t=')) history.replaceState(null, '', location.pathname + location.hash);
        if (!Q.to || !IX.seasons.includes(Q.to)) Q.to = last;
        if (!Q.from || !IX.seasons.includes(Q.from)) Q.from = Math.max(IX.seasons[0], Q.to - 2);
        if (!FAM[Q.fam]) Q.fam = 'rush';
        if (!FAM[Q.fam].met[Q.met]) Q.met = FIRST[Q.fam];
        if (!BY[Q.by] || !byAllowed(Q.by, Q.fam)) Q.by = 'player';
        if (Q.who === 'S') Q.who = 'L';
        Object.keys(Q.f).forEach(k => { if (!FILTERS[k] || !allowed(k, Q.fam)) delete Q.f[k]; });
        update();
      }).catch(() => { sec.querySelector('.tr-base').textContent = 'Play data is not available on this page.'; });
    },
  };
})();
