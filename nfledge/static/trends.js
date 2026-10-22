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
      ['40', 'gained 40+ yards', (P, j) => P.y[j] >= 40], ['fd', 'first downs', eq('fd', 1)], ['td', 'touchdowns', eq('td', 1)],
      ['neg', 'no gain or a loss', (P, j) => P.y[j] <= 0], ['to', 'turnovers', (P, j) => P.in[j] === 1 || P.fl[j] === 1]] },
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
    rnd: ['draft round', (P, j, G, D) => { const b = bioOf(P, j, D); return b ? b[2] : null; }, [], 'k'], season: ['season', (P, j, G, D) => D.season, [], 'kd'],
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
    rnd: k => (k >= 8 ? 'Undrafted' : k >= 7 ? 'Round 7+' : `Round ${k}`),
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
  const RNDL = x => (x >= 8 ? 'undrafted' : x >= 7 ? '7th+' : ordn(x));
  Object.assign(FILTERS, {
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
  const byAllowed = (k, fam) => k === 'college' || k === 'rnd' ? ['rush', 'pass', 'rec'].includes(fam) : FAM[fam].st ? ST_BY.has(k) : k !== 'kdist';
  // Two-way grids (owner 2026-10-14): a second grouping makes the answer a shaded rows x columns grid. Groupings with
  // dozens of values (players, teams, coaches) work as rows only; columns must fit a phone (capped, scrolls past that).
  const GRID_ROW_ONLY = new Set(['player', 'team', 'opp', 'coach', 'college']);
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
      const defaults = () => ({ fam: 'rush', met: 'ypc', who: 'L', wn: '', by: 'player', by2: '', st: 'reg', from: null, to: null, f: {}, fn: {}, min: null });
      const fromUrl = () => { try { const t = new URLSearchParams(location.search).get('t'); return t ? JSON.parse(decodeURIComponent(escape(atob(t)))) : null; } catch (e) { return null; } };
      const saved = () => { try { return JSON.parse(localStorage.getItem(LS) || 'null'); } catch (e) { return null; } };
      sec.innerHTML = `<div class="sec-head"><div><h2>Trends</h2><p>Ask the play-by-play anything: every run and pass since 1999, with charting (personnel, coverage, routes, pressure, play action...) where it exists. Tap a row to change it.</p></div></div>
        <div class="dt-card tr-card"><div class="tr-q"></div></div>
        <div class="tr-base muted"></div><div class="tr-cov"></div><div class="tr-trend"></div><div class="tr-tbl"></div>
        <p class="st-note muted">nflverse play-by-play (1999 on); NGS participation charting (2016-2025: formation, personnel, box, rushers, pressure, time to throw, routes, coverage) and FTN charting (2022 on, CC-BY-SA: motion, play action, RPOs, screens, blitzes, pocket, reads, drops, catchable / contested balls). A query only counts seasons where everything it uses was charted, and says which it left out. Rushing counts designed runs and QB scrambles; passing counts dropbacks (sacks included; yards per attempt and completion % use pass attempts). EPA = expected points added; CPOE = completion % over expected; pass rate over expected uses nflverse's xpass model, whose league average is not exactly zero, so read it against the league column. Rows under the minimum sample are hidden (the count is shown): small samples make loud, fake trends. Special teams (kickoffs, punts, field goals, extra points) read from the kicker's side, returns from the returner's; net punting = distance minus return yards, minus 20 for a touchback. Route names were re-charted in 2023, so outs, flats and swings are one group.</p>`;
      const qbox = sec.querySelector('.tr-q');

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

      // ---- the builder (owner 2026-10-22: "be more deliberate and elegant with how we're selecting filters ... a lot
      // easier to use and understand"): one labeled row per part of the question (Measure, Who, Only when, Seasons, Break
      // down, Minimum), each opening a sheet of grouped, searchable choices, and the question in plain English on top.
      // The query state Q, the links and run() are unchanged.
      const BY_GROUPS = [['People', ['player', 'team', 'opp', 'coach', 'college', 'rnd']], ['Time', ['season', 'week', 'qtr']],
        ['Situation', ['down', 'dist', 'zone', 'score']], ['Offense', ['align', 'pers', 'pa', 'mo']],
        ['Defense', ['box', 'rushers', 'dbs', 'mz', 'cov']], ['Passing', ['depth', 'loc', 'route', 'read', 'press']],
        ['Running', ['dir', 'gap']], ['Kicking', ['kdist']], ['Game', ['roof', 'surf']]];
      const cap = s => s.charAt(0).toUpperCase() + s.slice(1);
      // charting that starts after 1999: the first season with it, shown next to the choice ("2016+")
      const sinceTag = cols => {
        if (!cols || !cols.length) return '';
        const s = IX.seasons.find(y => covers(y, cols));
        return s && s > IX.seasons[0] ? `<span class="tq-since">${s}+</span>` : '';
      };
      // Who names the subject: the scope (Q.who) plus, for the league or one team, its unit (players, or the team as one:
      // owner 2026-10-22 "who: add teams themselves maybe?"). A team as itself is that team, a row per season.
      const UNITS = { player: 'Every player', team: 'Every team', opp: 'Every defense', coach: 'Every head coach' };
      const whoLabel = () => {
        const t = Q.who.slice(2);
        if (Q.who === 'L') return UNITS[Q.by] || 'Whole league';
        if (/^T:/.test(Q.who)) return Q.fam === 'team' ? `${t} offense` : Q.by === 'player' ? `${t} players` : `${t} as a team`;
        if (/^V:/.test(Q.who)) return Q.by === 'player' ? `Players against ${t}` : `${t} defense`;
        return Q.who[0] === 'C' ? `${Q.wn}'s offense` : Q.wn || 'Whole league';
      };
      const isR = (F, v) => F.range && typeof v === 'string' && v.startsWith('R:');
      const vals = k => (Array.isArray(Q.f[k]) ? Q.f[k] : k in Q.f ? [Q.f[k]] : []);
      const isNot = k => !!(Q.fn && Q.fn[k]);
      const setF = (k, list, neg) => {
        if (!list.length) { delete Q.f[k]; delete Q.fn[k]; return; }
        Q.f[k] = list.length === 1 ? list[0] : list;
        if (neg) Q.fn[k] = 1; else delete Q.fn[k];
      };
      const optLabel = k => {
        const F = FILTERS[k], one = v => (isR(F, v) ? F.range.say(...parseR(F, v)) : F.fmt ? F.fmt(v) : (F.opts.find(o => o[0] === v) || ['', ''])[1]);
        // "against GB or CHI", not "against GB or against CHI": shared leading words said once
        const ls = vals(k).map(one), w = ls.map(l => l.split(' '));
        let n = 0;
        while (ls.length > 1 && w.every(x => x.length > n + 1 && x[n] === w[0][n])) n++;
        return `${isNot(k) ? 'not ' : ''}${n ? `${w[0].slice(0, n).join(' ')} ${w.map(x => x.slice(n).join(' ')).join(' or ')}` : ls.join(' or ')}`;
      };
      const testOf = (k, v) => {
        const F = FILTERS[k];
        if (isR(F, v)) { const [lo, hi] = parseR(F, v), get = F.range.get; return (P, j, G, V, D) => { const x = get(P, j, G, V, D); return x != null && x >= lo && x <= hi; }; }
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
      const filterTest = k => {
        const ts = vals(k).map(v => testOf(k, v)).filter(Boolean);
        if (!ts.length) return null;
        const any = ts.length === 1 ? ts[0] : (P, j, G, V, D) => { for (let i = 0; i < ts.length; i++) if (ts[i](P, j, G, V, D)) return true; return false; };
        if (!isNot(k)) return any;
        const known = knownOf(FILTERS[k]);
        return (P, j, G, V, D) => known(P, j, G, V, D) && !any(P, j, G, V, D);
      };
      const ST_TXT = { reg: 'regular season', post: 'playoffs', both: 'regular season + playoffs' };
      const seasonsTxt = () => `${Q.from === Q.to ? Q.from : `${Q.from}–${Q.to}`} · ${cap(ST_TXT[Q.st])}`;
      const byTxt = () => (Q.by2 && BY[Q.by2] ? `${cap(BY[Q.by][0])}, then ${BY[Q.by2][0]} (grid)` : `One row per ${BY[Q.by][0]}`);
      const summary = () => {
        const [fam, m] = famMetric();
        const who = Q.who === 'L' && !UNITS[Q.by] ? 'The league' : whoLabel();
        const unit = (Q.who === 'L' && UNITS[Q.by]) || Q.by === 'player';  // the breakdown is already in the subject
        const when = Object.keys(Q.f).map(optLabel).filter(Boolean);
        const by = Q.by2 && BY[Q.by2] ? `, as a grid of ${BY[Q.by][0]} by ${BY[Q.by2][0]}` : unit ? '' : `, by ${BY[Q.by][0]}`;
        const yrs = Q.from === Q.to ? `${Q.from}` : `${Q.from}–${Q.to}`;
        return `<b>${esc(who)}</b> &middot; ${esc(fam.label.toLowerCase())} <b>${esc(m[0])}</b>${when.length ? ` when ${esc(when.join(', '))}` : ''} &middot; ${esc(yrs)} ${esc(ST_TXT[Q.st])}${esc(by)}`;
      };
      const render = () => {
        const fam = FAM[Q.fam], [, m] = famMetric();
        const chips = Object.keys(Q.f).map(k => `<span class="tq-chip${isNot(k) ? ' tq-not' : ''}"><button type="button" data-fx="${k}" title="${esc(FILTERS[k].label)}">${esc(optLabel(k))}</button><button type="button" class="tq-cx" data-x="${k}" aria-label="Remove ${esc(FILTERS[k].label)}">&times;</button></span>`).join('');
        const row = (pick, k, v) => `<button type="button" class="tq-row" data-pick="${pick}"><span class="tq-k">${k}</span><span class="tq-v">${v}</span><span class="tq-go" aria-hidden="true">&rsaquo;</span></button>`;
        qbox.innerHTML = `<p class="tq-sum">${summary()}</p>
          <div class="tq-rows">
            ${row('measure', 'Measure', `${esc(fam.label)} <span class="tq-dot">&middot;</span> <b>${esc(m[0])}</b>`)}
            ${row('who', 'Who', esc(whoLabel()))}
            <div class="tq-row tq-frow"><span class="tq-k">Only when</span><span class="tq-v tq-chips">${chips}<button type="button" class="tq-add" data-pick="add">+ Add</button></span></div>
            ${row('seasons', 'Seasons', esc(seasonsTxt()))}
            ${row('by', 'Break down', esc(byTxt()))}
            <div class="tq-row tq-mrow"><span class="tq-k">Minimum</span><span class="tq-v tr-min"><button type="button" class="tr-step" data-step="-1" aria-label="One fewer">&minus;</button><input type="range" min="0" max="${Math.max(maxN, Q.min ?? fam.min, fam.min * 2)}" step="1" value="${Q.min ?? fam.min}" aria-label="Minimum sample"><button type="button" class="tr-step" data-step="1" aria-label="One more">+</button> <b>${Q.min ?? fam.min}</b><span class="tr-w">${esc(fam.unit)}</span></span></div>
          </div>
          <div class="tq-acts"><button type="button" class="tq-act" data-pick="examples">Examples</button><button type="button" class="tq-act tr-share">Copy link</button><button type="button" class="tq-act tq-reset">Reset</button></div>`;
      };
      const setFam = k => {
        Q.fam = k; Q.met = FIRST[k]; Q.min = null;
        if (Q.fam === 'team' && Q.by === 'player') Q.by = 'team';
        if (Q.fam === 'team' && /^P:/.test(Q.who)) { Q.who = 'L'; Q.wn = ''; }
        Object.keys(Q.f).forEach(f => { if (!allowed(f, Q.fam)) delete Q.f[f]; });
        if (!byAllowed(Q.by, Q.fam)) Q.by = Q.fam === 'team' ? 'team' : 'player';
        if (Q.by2 && !byAllowed(Q.by2, Q.fam)) Q.by2 = '';
        maxN = 0;
      };
      const setWho = (v, name) => { Q.who = v; Q.wn = /^[PC]:/.test(v) ? name || '' : ''; if (/^P:/.test(Q.who) && Q.by === 'player') Q.by = 'season'; };
      // ---- the pickers (NFLE.sheet: a bottom sheet on phones, a centered panel on wide screens)
      const panel = () => { const el = document.createElement('div'); el.className = 'tq-sheet'; return el; };
      const done = () => { NFLE.sheetClose(); update(); };
      const pickMeasure = opener => {
        const el = panel();
        let fam = Q.fam;
        const draw = () => {
          el.innerHTML = `<div class="tq-seg" role="tablist">${Object.entries(FAM).map(([k, f]) => `<button type="button" data-fam="${k}" class="${k === fam ? 'on' : ''}">${esc(f.label)}</button>`).join('')}</div>
            <div class="tq-list">${Object.entries(FAM[fam].met).map(([k, mm]) => `<button type="button" class="tq-opt${fam === Q.fam && k === Q.met ? ' on' : ''}" data-met="${k}"><span>${esc(mm[0])}</span>${sinceTag(mm[3])}</button>`).join('')}</div>`;
        };
        draw();
        el.addEventListener('click', e => {
          const f = e.target.closest('[data-fam]'); if (f) { fam = f.dataset.fam; draw(); return; }
          const mt = e.target.closest('[data-met]'); if (!mt) return;
          if (fam !== Q.fam) setFam(fam);
          Q.met = mt.dataset.met; done();
        });
        NFLE.sheet('What to measure', el, opener);
      };
      // a team's players over the seasons in range, most plays first: role 'fam' (the measure's player), 'qb'
      // (dropbacks), 'any' (rushes + dropbacks + targets)
      const countPlayers = (t, role) => Promise.all(spanSeasons().map(s => loadSeason(s, false, FAM[Q.fam].st))).then(list => {
        const fam = FAM[Q.fam], cnt = new Map(), bump = (PL, a) => { if (a < 0) return; const [gid, nm] = PL[a], c = cnt.get(gid); if (c) c[1]++; else cnt.set(gid, [nm, 1]); };
        list.forEach(({ D, P, PL, n }) => {
          const ti = D.teams.indexOf(t), G = D.games, base = role !== 'fam' || !fam.st;
          if (ti < 0) return;
          const Pb = base ? D.cols : P, PLb = base ? D.players : PL, nb = base ? D.n : n;
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
      const teamOfPlayer = gid => Promise.all(spanSeasons().map(s => loadSeason(s, false, false))).then(list => {
        const c = {};
        list.forEach(({ D }) => {
          const k = D.players.findIndex(p => p[0] === gid), P = D.cols;
          if (k < 0) return;
          for (let j = 0; j < D.n; j++) if (P.ru[j] === k || P.pp[j] === k || P.re[j] === k) c[D.teams[P.o[j]]] = (c[D.teams[P.o[j]]] || 0) + 1;
        });
        return Object.keys(c).sort((a, b) => c[b] - c[a])[0] || null;
      });
      const pickWho = opener => {
        const el = panel(), teams = IX.teams, team = Q.fam === 'team', fam = FAM[Q.fam];
        const ok = k => BY[k] && byAllowed(k, Q.fam) && !(k === 'player' && team);
        // one team: as a unit (a row per season, or whatever it's broken down by) or its players
        // each grid keeps its own choice; it starts on the current one, else on the team as a unit
        const solo = { T: true, V: true };
        if (/^[TV]:/.test(Q.who)) solo[Q.who[0]] = team || Q.by !== 'player';
        const lit = (pre, t) => Q.who === `${pre}:${t}` && solo[pre] === (team || Q.by !== 'player');
        const tgrid = pre => `<div class="tq-teams">${teams.map(t => `<button type="button" data-who="${pre}:${t}" class="${lit(pre, t) ? 'on' : ''}">${esc(t)}</button>`).join('')}</div>`;
        const SEG = { T: ['As a team', 'Its players'], V: ['Their defense', 'Players facing them'] };
        const seg = pre => team ? '' : `<div class="tq-seg">${[1, 0].map((v, i) => `<button type="button" data-solo="${v}" data-pre="${pre}" class="${+solo[pre] === v ? 'on' : ''}">${SEG[pre][i]}</button>`).join('')}</div>`;
        const main = () => {
          el.innerHTML = `<div class="tq-list">${Object.entries(UNITS).filter(([k]) => ok(k)).map(([k, l]) => `<button type="button" class="tq-opt${Q.who === 'L' && Q.by === k ? ' on' : ''}" data-who="L" data-unit="${k}"><span>${l}</span><small>${{ player: 'a row per player', team: team ? 'a row per offense' : 'a row per team: its players combined', opp: 'a row per defense: what offenses did against it', coach: 'a row per head coach: the offenses they ran' }[k]}</small></button>`).join('')}</div>
            <h4 class="tq-h">${team ? 'A head coach' : 'A player or head coach'}</h4>
            <input class="dt-search tq-find" type="search" placeholder="Type a name" aria-label="Find a ${team ? 'head coach' : 'player or head coach'}" autocomplete="off">
            <div class="tq-list tq-found"></div>
            <h4 class="tq-h">One team${team ? "'s offense" : ''}</h4><div class="tq-solo">${seg('T')}${tgrid('T')}</div>
            <h4 class="tq-h">${team ? "One team's defense" : 'Against one team'}</h4><div class="tq-solo">${seg('V')}${tgrid('V')}</div>`;
          const inp = el.querySelector('.tq-find'), out = el.querySelector('.tq-found');
          const find = () => {
            const t = inp.value.trim().toLowerCase();
            out.innerHTML = t.length < 2 ? '' : [...findMap.values()].filter(o => o[0].toLowerCase().includes(t)).slice(0, 30)
              .map(o => `<button type="button" class="tq-opt" data-who="${esc(o[1])}" data-wn="${esc(o[2])}"><span>${esc(o[0])}</span></button>`).join('')
              || '<p class="muted tq-help">No one by that name in these seasons.</p>';
          };
          inp.addEventListener('input', find);
          fillFind().then(() => { if (inp.value) find(); });  // names load per season: search again once they're in
        };
        // a team's players (owner 2026-10-22: "vikings > aaron jones when playing the packers"): everyone with a play for
        // it in these seasons, most plays first; picking one is that player while playing for that team
        const roster = t => {
          el.innerHTML = '<p class="muted tq-help">Counting plays&hellip;</p>';
          countPlayers(t, 'fam').then(all => {
            const rows = all.slice(0, 60);
            el.innerHTML = `<button type="button" class="tq-act tq-back" data-back="1">&lsaquo; All teams</button>
              <h4 class="tq-h">${esc(t)} &middot; ${esc(fam.label.toLowerCase())}</h4>
              <div class="tq-list"><button type="button" class="tq-opt${Q.who === `T:${t}` && Q.by === 'player' ? ' on' : ''}" data-all="${esc(t)}"><span>Every ${esc(t)} player</span><small class="tq-r">a row each</small></button>
              ${rows.map(([gid, [nm, c]]) => `<button type="button" class="tq-opt${Q.who === `P:${gid}` && Q.f.tm === t ? ' on' : ''}" data-pid="${esc(gid)}" data-wn="${esc(nm)}" data-tm="${esc(t)}"><span>${esc(nm)}</span><small class="tq-r">${c} ${esc(fam.unit)}</small></button>`).join('')}</div>
              ${rows.length ? '' : '<p class="muted tq-help">No plays for this team in these seasons.</p>'}`;
            el.closest('.sheet') && (el.closest('.sheet').scrollTop = 0);
          });
        };
        main();
        el.addEventListener('click', e => {
          const sv = e.target.closest('[data-solo]');
          if (sv) {  // flip that grid's choice, and its highlighted team with it
            const pre = sv.dataset.pre, box = sv.closest('.tq-solo');
            solo[pre] = sv.dataset.solo === '1';
            box.querySelectorAll('[data-solo]').forEach(x => x.classList.toggle('on', x === sv));
            box.querySelectorAll('.tq-teams [data-who]').forEach(x => x.classList.toggle('on', lit(pre, x.dataset.who.slice(2))));
            return;
          }
          if (e.target.closest('[data-back]')) { main(); return; }
          const all = e.target.closest('[data-all]');
          if (all) { setWho(`T:${all.dataset.all}`); delete Q.f.tm; Q.by = 'player'; if (Q.by2 === Q.by) Q.by2 = ''; done(); return; }
          const pp = e.target.closest('[data-pid]');
          if (pp) { setWho(`P:${pp.dataset.pid}`, pp.dataset.wn); Q.f.tm = pp.dataset.tm; done(); return; }
          const b = e.target.closest('[data-who]'); if (!b) return;
          if (/^T:/.test(b.dataset.who) && !team && !solo.T) { roster(b.dataset.who.slice(2)); return; }
          setWho(b.dataset.who, b.dataset.wn);
          delete Q.f.tm;  // a new subject starts without the last one's team
          if (/^V:/.test(Q.who)) delete Q.f.vs;  // the scope already says who they played
          if (b.dataset.unit) Q.by = b.dataset.unit;
          else if (/^[TV]:/.test(Q.who)) Q.by = solo[Q.who[0]] ? (UNITS[Q.by] ? 'season' : Q.by) : 'player';
          if (Q.by2 === Q.by) Q.by2 = '';
          done();
        });
        NFLE.sheet('Who', el, opener);
      };
      // a player as a filter value (Thrown by, With / Without a teammate): search by name, or a team then its players;
      // opens on the team in question when there is one (Playing for, Who's team, or the chosen player's team)
      // Is / Is not (owner 2026-10-22: "do we have include and exclude with filters"): every filter but with / without
      // (each other's opposite); the sheet keeps its choice and commits it with the value
      const notSeg = (k, neg) => (FILTERS[k].noNot ? '' : `<div class="tq-seg tq-isnot" role="radiogroup" aria-label="Include or exclude">${[[0, 'Is'], [1, 'Is not']].map(([v, l]) => `<button type="button" data-not="${v}" class="${+neg === v ? 'on' : ''}">${l}</button>`).join('')}</div>`);
      const flipNot = (el, e) => { const b = e.target.closest('[data-not]'); if (!b) return null; el.querySelectorAll('[data-not]').forEach(x => x.classList.toggle('on', x === b)); return b.dataset.not === '1'; };
      const rmBtn = k => (k in Q.f ? '<button type="button" class="tq-act tq-rm" data-rm="1">Remove this filter</button>' : '');
      // multi-select sheets: tap to toggle, Apply commits ("any of these")
      const applyBar = n => `<div class="tq-applybar"><button type="button" class="tq-act tq-done" data-apply="1"${n ? '' : ' disabled'}>${n > 1 ? `Apply (any of ${n})` : 'Apply'}</button></div>`;
      const toggleSel = (el, sel, b) => {
        const v = b.dataset.fv;
        if (sel.has(v)) sel.delete(v); else sel.add(v);
        el.querySelectorAll('[data-fv]').forEach(x => x.classList.toggle('on', sel.has(x.dataset.fv)));
        const a = el.querySelector('.tq-applybar'); if (a) a.outerHTML = applyBar(sel.size);
      };
      const pickPerson = (k, opener) => {
        const F = FILTERS[k], el = panel(), role = F.param === 'qb' ? 'qb' : 'any';
        let neg = isNot(k);
        const set = (gid, nm) => { setF(k, [`${gid}|${nm}`], neg); done(); };
        const head = () => notSeg(k, neg);
        const main = () => {
          el.innerHTML = `${head()}<input class="dt-search tq-find" type="search" placeholder="Type a name" aria-label="Find a player" autocomplete="off">
            <div class="tq-list tq-found"></div><h4 class="tq-h">Or pick a team</h4>
            <div class="tq-teams">${IX.teams.map(t => `<button type="button" data-team="${t}">${esc(t)}</button>`).join('')}</div>${rmBtn(k)}`;
          const inp = el.querySelector('.tq-find'), out = el.querySelector('.tq-found');
          const find = () => {
            const t = inp.value.trim().toLowerCase();
            out.innerHTML = t.length < 2 ? '' : [...findMap.values()].filter(o => o[1][0] === 'P' && o[0].toLowerCase().includes(t)).slice(0, 30)
              .map(o => `<button type="button" class="tq-opt" data-pid="${esc(o[1].slice(2))}" data-wn="${esc(o[2])}"><span>${esc(o[0])}</span></button>`).join('')
              || '<p class="muted tq-help">No one by that name in these seasons.</p>';
          };
          inp.addEventListener('input', find);
          fillFind().then(() => { if (inp.value) find(); });
        };
        const team = t => {
          el.innerHTML = '<p class="muted tq-help">Counting plays&hellip;</p>';
          countPlayers(t, role).then(all => {
            const rows = all.slice(0, 60), unit = role === 'qb' ? 'dropbacks' : 'plays';
            el.innerHTML = `${head()}<button type="button" class="tq-act tq-back" data-back="1">&lsaquo; Search or another team</button>
              <h4 class="tq-h">${esc(t)} ${role === 'qb' ? 'passers' : 'players'}</h4>
              <div class="tq-list">${rows.map(([gid, [nm, c]]) => `<button type="button" class="tq-opt${vals(k).some(v => v.startsWith(gid + '|')) ? ' on' : ''}" data-pid="${esc(gid)}" data-wn="${esc(nm)}"><span>${esc(nm)}</span><small class="tq-r">${c} ${unit}</small></button>`).join('')}</div>
              ${rows.length ? '' : '<p class="muted tq-help">No plays for this team in these seasons.</p>'}${rmBtn(k)}`;
          });
        };
        el.addEventListener('click', e => {
          const n = flipNot(el, e); if (n != null) { neg = n; if (k in Q.f) { setF(k, vals(k), neg); update(); } return; }
          const pp = e.target.closest('[data-pid]'); if (pp) { set(pp.dataset.pid, pp.dataset.wn); return; }
          const tb = e.target.closest('[data-team]'); if (tb) { team(tb.dataset.team); return; }
          if (e.target.closest('[data-back]')) { main(); return; }
          if (e.target.closest('[data-rm]')) { setF(k, []); done(); }
        });
        const t0 = vals('tm')[0] || (/^T:/.test(Q.who) ? Q.who.slice(2) : null);
        if (t0) team(t0);
        else if (/^P:/.test(Q.who)) { el.innerHTML = '<p class="muted tq-help">Finding the team&hellip;</p>'; teamOfPlayer(Q.who.slice(2)).then(t => (t ? team(t) : main())); }
        else main();
        NFLE.sheet(F.label, el, opener);
      };
      const pickCollege = (k, opener) => {
        const el = panel(), sel = new Set(vals(k));
        let neg = isNot(k);
        el.innerHTML = '<p class="muted tq-help">Loading schools&hellip;</p>';
        loadBio().then(() => {
          const n = [new Map(), new Map()];
          BIO.p.forEach(([si, ci]) => { if (si >= 0) n[0].set(si, (n[0].get(si) || 0) + 1); if (ci >= 0) n[1].set(ci, (n[1].get(ci) || 0) + 1); });
          const top = (m, names) => [...m].sort((a, b) => b[1] - a[1]).map(([i, c]) => [names[i], c]);
          const schools = top(n[0], BIO.schools), confs = top(n[1], BIO.confs).filter(([c]) => c !== 'NO FOOTBALL').slice(0, 12);
          const row = (t, [nm, c]) => `<button type="button" class="tq-opt${sel.has(`${t}:${nm}`) ? ' on' : ''}" data-fv="${t}:${esc(nm)}"><span>${esc(nm)}</span><small class="tq-r">${c} players</small></button>`;
          el.innerHTML = `${notSeg(k, neg)}<input class="dt-search tq-find" type="search" placeholder="Search schools: Florida, Alabama&hellip;" aria-label="Search schools" autocomplete="off">
            <div class="tq-list tq-found"></div>
            <h4 class="tq-h">Conference <span class="muted">(today's)</span></h4><div class="tq-chipset">${confs.map(([c]) => `<button type="button" class="${sel.has(`c:${c}`) ? 'on' : ''}" data-fv="c:${esc(c)}">${esc(c.replace(/ Conference$/, ''))}</button>`).join('')}</div>
            <h4 class="tq-h">Most NFL players</h4><div class="tq-list">${schools.slice(0, 25).map(x => row('s', x)).join('')}</div>
            ${rmBtn(k)}${applyBar(sel.size)}`;
          const inp = el.querySelector('.tq-find'), out = el.querySelector('.tq-found');
          inp.addEventListener('input', () => {
            const t = inp.value.trim().toLowerCase();
            out.innerHTML = t.length < 2 ? '' : schools.filter(([nm]) => nm.toLowerCase().includes(t)).slice(0, 30).map(x => row('s', x)).join('')
              || '<p class="muted tq-help">No school by that name.</p>';
          });
        });
        el.addEventListener('click', e => {
          const n = flipNot(el, e); if (n != null) { neg = n; return; }
          const b = e.target.closest('[data-fv]'); if (b) { toggleSel(el, sel, b); return; }
          if (e.target.closest('[data-apply]')) { setF(k, [...sel], neg); done(); return; }
          if (e.target.closest('[data-rm]')) { setF(k, []); done(); }
        });
        NFLE.sheet('College', el, opener);
      };
      const pickRange = (k, opener) => {
        const F = FILTERS[k], r = F.range, el = panel(), step = r.step || 1, tick = r.tick || (x => `${x}`);
        let neg = isNot(k), moved = false;
        let [lo, hi] = isR(F, Q.f[k]) ? Q.f[k].slice(2).split('~').map(Number) : [r.min, r.max];
        const chips = [...F.opts.filter(o => !r.chips || r.chips.includes(o[0])).map(o => [o[1], o[0]]), ...(r.presets || []).map(([l, a, b]) => [l, `R:${a}~${b}`])];
        el.innerHTML = `${notSeg(k, neg)}<p class="tq-rv"></p>
          <div class="tq-range"><i class="tq-rtrack"><i class="tq-rfill"></i></i>
            <input type="range" class="tq-lo" min="${r.min}" max="${r.max}" step="${step}" value="${lo}" aria-label="From">
            <input type="range" class="tq-hi" min="${r.min}" max="${r.max}" step="${step}" value="${hi}" aria-label="To"></div>
          <div class="tq-rends"><span>${esc(tick(r.min))}${r.openLo ? ' or less' : ''}</span>${r.unit ? `<span class="muted">${esc(r.unit)}</span>` : ''}<span>${esc(tick(r.max))}${r.openHi ? '+' : ''}</span></div>
          <button type="button" class="tq-act tq-done" data-apply="1">Apply</button>
          ${chips.length ? `<h4 class="tq-h">Quick picks</h4><div class="tq-chipset">${chips.map(([l, v]) => `<button type="button" class="${Q.f[k] === v ? 'on' : ''}" data-fv="${esc(v)}">${esc(l)}</button>`).join('')}</div>` : ''}
          ${rmBtn(k)}`;
        const L = el.querySelector('.tq-lo'), H = el.querySelector('.tq-hi'), fill = el.querySelector('.tq-rfill'), out = el.querySelector('.tq-rv');
        const draw = () => {
          const pct = x => (100 * (x - r.min)) / (r.max - r.min);
          fill.style.left = `${pct(lo)}%`; fill.style.right = `${100 - pct(hi)}%`;
          const any = lo <= r.min && hi >= r.max;
          // a preset value (not a range) shows by name until a handle moves
          out.textContent = !moved && k in Q.f && !isR(F, Q.f[k]) ? cap(optLabel(k).replace(/^not /, '')) : any ? 'Any (drag the ends)' : cap(r.say(...parseR(F, `R:${lo}~${hi}`)));
          L.style.zIndex = lo >= r.max - step ? 3 : 2;  // a handle pushed to the far end stays grabbable
        };
        L.addEventListener('input', () => { lo = Math.min(+L.value, hi); L.value = lo; moved = true; draw(); });
        H.addEventListener('input', () => { hi = Math.max(+H.value, lo); H.value = hi; moved = true; draw(); });
        draw();
        el.addEventListener('click', e => {
          const n = flipNot(el, e); if (n != null) { neg = n; return; }
          if (e.target.closest('[data-apply]')) {
            if (!moved && k in Q.f) setF(k, vals(k), neg);  // only Is / Is not changed
            else if (lo <= r.min && hi >= r.max) setF(k, []);
            else setF(k, [`R:${lo}~${hi}`], neg);
            done(); return;
          }
          const b = e.target.closest('[data-fv]'); if (b) { setF(k, [b.dataset.fv], neg); done(); return; }
          if (e.target.closest('[data-rm]')) { setF(k, []); done(); }
        });
        NFLE.sheet(F.label, el, opener);
      };
      const pickFilter = (k, opener) => {
        if (FILTERS[k].range) { pickRange(k, opener); return; }
        if (FILTERS[k].param === 'college') { pickCollege(k, opener); return; }
        if (FILTERS[k].param) { pickPerson(k, opener); return; }
        const F = FILTERS[k], el = panel(), sel = new Set(vals(k));
        let neg = isNot(k);
        // team filters: conferences and divisions (Opponent) as chips, teams as a grid
        const pick = (cls, os) => `<div class="${cls}">${os.map(o => `<button type="button" class="${sel.has(o[0]) ? 'on' : ''}" data-fv="${esc(o[0])}">${esc(o[0])}</button>`).join('')}</div>`;
        const isTeam = o => IX.teams.includes(o[0]);
        el.innerHTML = `${notSeg(k, neg)}${k === 'vs' || k === 'tm' ? (k === 'vs' ? `<h4 class="tq-h">Conference</h4>${pick('tq-chipset', F.opts.filter(o => o[0].length === 3 && !isTeam(o)))}
            <h4 class="tq-h">Division</h4>${pick('tq-chipset', F.opts.filter(o => o[0].includes(' ')))}<h4 class="tq-h">Team</h4>` : '') + pick('tq-teams', F.opts.filter(isTeam))
          : `<div class="tq-list">${F.opts.map(o => `<button type="button" class="tq-opt${sel.has(o[0]) ? ' on' : ''}" data-fv="${esc(o[0])}"><span>${esc(cap(o[1]))}</span>${o[3] ? `<small>${esc(o[3])}</small>` : ''}</button>`).join('')}</div>`}
          ${rmBtn(k)}${applyBar(sel.size)}`;
        el.addEventListener('click', e => {
          const n = flipNot(el, e); if (n != null) { neg = n; return; }
          const b = e.target.closest('[data-fv]'); if (b) { toggleSel(el, sel, b); return; }
          if (e.target.closest('[data-apply]')) { setF(k, F.opts.map(o => o[0]).filter(v => sel.has(v)), neg); done(); return; }
          if (e.target.closest('[data-rm]')) { setF(k, []); done(); }
        });
        NFLE.sheet(F.label, el, opener);
      };
      const pickAdd = opener => {
        const el = panel(), groups = {};
        Object.entries(FILTERS).filter(([k]) => !(k in Q.f) && allowed(k, Q.fam) && !(k === 'vs' && /^V:/.test(Q.who)) && !(k === 'tm' && /^T:/.test(Q.who))).forEach(([k, f]) => { (groups[f.group] = groups[f.group] || []).push([k, f]); });
        const list = t => Object.entries(groups).map(([g, fs]) => {
          const hit = fs.filter(([, f]) => !t || f.label.toLowerCase().includes(t) || f.opts.some(o => o[1].toLowerCase().includes(t)));
          return hit.length ? `<h4 class="tq-h">${esc(g)}</h4><div class="tq-list">${hit.map(([k, f]) => `<button type="button" class="tq-opt" data-fk="${k}"><span>${esc(f.label)}</span><small>${f.hint ? esc(f.hint) : !f.opts.length && f.range ? `${esc((f.range.presets || []).map(x => x[0]).join(', '))} or any range` : `${esc(f.opts.slice(0, 3).map(o => o[1]).join(', '))}${f.opts.length > 3 ? '&hellip;' : ''}${f.range ? ', or a range' : ''}`}</small>${sinceTag(f.need)}<span class="tq-go">&rsaquo;</span></button>`).join('')}</div>` : '';
        }).join('') || '<p class="muted tq-help">No filter matches.</p>';
        el.innerHTML = `<input class="dt-search tq-find" type="search" placeholder="Search: blitz, red zone, 3rd down, cold&hellip;" aria-label="Search filters" autocomplete="off"><div class="tq-fl">${list('')}</div>`;
        const inp = el.querySelector('.tq-find');
        inp.addEventListener('input', () => { el.querySelector('.tq-fl').innerHTML = list(inp.value.trim().toLowerCase()); });
        el.addEventListener('click', e => { const b = e.target.closest('[data-fk]'); if (b) pickFilter(b.dataset.fk, opener); });
        NFLE.sheet('Only plays where…', el, opener);
      };
      const pickSeasons = opener => {
        const el = panel(), S = IX.seasons, first = S[0], last = S[S.length - 1];
        const charted = S.find(y => covers(y, ['pz'])) || first;
        // the newest season in the data is "this season" while it's the site's current one (owner 2026-10-22: "shouldn't
        // that read this season?"); every preset shows its years
        const CFG = window.NFLE_CFG || {}, now = CFG.current && CFG.season === last;
        const presets = (now ? [['This season', last, last], ['Last season', last - 1, last - 1]] : [['Last season', last, last]])
          .concat([['Last 3 seasons', last - 2, last], ['Last 5 seasons', last - 4, last], ['Charting era', charted, last], ['Every season', first, last]])
          .filter(([, a, b]) => b >= first).map(([l, a, b]) => [l, Math.max(first, a), b]);
        const yrs = (a, b) => (a === b ? `${a}` : `${a}–${b}`);
        const draw = () => {
          el.innerHTML = `<div class="tq-list">${presets.map(([l, a, b]) => `<button type="button" class="tq-opt${Q.from === a && Q.to === b ? ' on' : ''}" data-span="${a}-${b}"><span>${esc(l)}${l === 'Charting era' ? ' <i class="tq-note">personnel, coverage, routes&hellip;</i>' : ''}</span><small class="tq-r">${yrs(a, b)}</small></button>`).join('')}</div>
            <h4 class="tq-h">Custom range</h4>
            <div class="tq-span"><select class="dt-select" data-yr="from" aria-label="From">${S.map(y => opt(y, y, Q.from)).join('')}</select><span class="muted">to</span><select class="dt-select" data-yr="to" aria-label="To">${S.map(y => opt(y, y, Q.to)).join('')}</select></div>
            <h4 class="tq-h">Games</h4>
            <div class="tq-seg">${[['reg', 'Regular season'], ['post', 'Playoffs'], ['both', 'Both']].map(([k, l]) => `<button type="button" data-st="${k}" class="${Q.st === k ? 'on' : ''}">${l}</button>`).join('')}</div>
            <button type="button" class="tq-act tq-done" data-done="1">Done</button>`;
        };
        draw();
        el.addEventListener('click', e => {
          const p = e.target.closest('[data-span]');
          if (p) { const [a, b] = p.dataset.span.split('-').map(Number); Q.from = a; Q.to = b; done(); return; }
          const s = e.target.closest('[data-st]'); if (s) { Q.st = s.dataset.st; update(); draw(); return; }
          if (e.target.closest('[data-done]')) NFLE.sheetClose();
        });
        el.addEventListener('change', e => {
          const y = e.target.closest('[data-yr]'); if (!y) return;
          Q[y.dataset.yr] = +y.value;
          if (Q.to < Q.from) { if (y.dataset.yr === 'from') Q.to = Q.from; else Q.from = Q.to; }
          update(); draw();
        });
        NFLE.sheet('Seasons', el, opener);
      };
      const pickBy = opener => {
        const el = panel();
        const ok = k => BY[k] && byAllowed(k, Q.fam) && !(k === 'player' && (Q.fam === 'team' || /^P:/.test(Q.who)));
        const set = (cur, attr, filt) => BY_GROUPS.map(([g, ks]) => {
          const hit = ks.filter(filt);
          return hit.length ? `<h4 class="tq-h">${g}</h4><div class="tq-chipset">${hit.map(k => `<button type="button" data-${attr}="${k}" class="${cur === k ? 'on' : ''}">${esc(cap(BY[k][0]))}${sinceTag(BY[k][2])}</button>`).join('')}</div>` : '';
        }).join('');
        let grid = !!Q.by2;  // the second split (a grid) stays folded away until it's set or asked for
        const draw = () => {
          el.innerHTML = `<p class="tq-help muted">One row per&hellip;</p>${set(Q.by, 'by', ok)}
            <div class="tq-then">${grid ? `<h4 class="tq-h">Then by <span class="muted">(columns of a grid)</span></h4>
            <div class="tq-chipset"><button type="button" data-by2="" class="${!Q.by2 ? 'on' : ''}">No grid</button></div>
            ${set(Q.by2, 'by2', k => ok(k) && k !== Q.by && !GRID_ROW_ONLY.has(k))}` : '<button type="button" class="tq-act tq-grid" data-grid="1">+ Split again into a grid</button>'}</div>
            <button type="button" class="tq-act tq-done" data-done="1">Done</button>`;
        };
        draw();
        el.addEventListener('click', e => {
          const a = e.target.closest('[data-by]'); if (a) { Q.by = a.dataset.by; if (Q.by2 === Q.by) Q.by2 = ''; update(); draw(); return; }
          const b = e.target.closest('[data-by2]'); if (b) { Q.by2 = b.dataset.by2; update(); draw(); return; }
          if (e.target.closest('[data-grid]')) { grid = true; draw(); return; }
          if (e.target.closest('[data-done]')) NFLE.sheetClose();
        });
        NFLE.sheet('Break down', el, opener);
      };
      const pickExamples = opener => {
        const el = panel();
        el.innerHTML = `<div class="tq-list">${EXAMPLES.map((x, i) => `<button type="button" class="tq-opt" data-ex="${i}"><span>${esc(x[0])}</span></button>`).join('')}</div>`;
        el.addEventListener('click', e => {
          const b = e.target.closest('[data-ex]'); if (!b) return;
          Q = Object.assign(defaults(), { from: Q.from, to: Q.to }, JSON.parse(JSON.stringify(EXAMPLES[+b.dataset.ex][1])));
          done();
        });
        NFLE.sheet('Examples', el, opener);
      };
      const PICK = { measure: pickMeasure, who: pickWho, add: pickAdd, seasons: pickSeasons, by: pickBy, examples: pickExamples };
      const save = () => { try { localStorage.setItem(LS, JSON.stringify(Q)); } catch (e) { /* private mode */ } };

      // ---- loading: base file per season; charting file only when the query needs a charting column
      const stv = {};
      let collP = null;
      const loadBio = () => collP || (collP = NFLE.load('data/plays/bio.json').then(c => {
        BIO = { schools: c.schools, confs: c.confs, p: new Map(Object.entries(c.p)), fam: Q.fam };
      }));
      // game context: gsis ids per game side (the file holds the season's player idx, signed: + played, - out)
      const gfile = {};
      const loadG = (s, D) => gfile[s] || (gfile[s] = NFLE.load(`data/plays/${s}_g.json`).then(raw => {
        const ids = D.players.map(p => p[0]);
        D.gx = { x: raw.x, r: raw.r.map(sides => sides.map(list => new Map(list.map(v => [ids[Math.abs(v) - 1], v > 0])))) };
      }).catch(() => { D.gx = null; }));
      const loadSeason = (s, wantX, side, wantG) => loadSeason0(s, wantX, side).then(m => (wantG ? loadG(s, m.D).then(() => m) : m));
      const loadSeason0 = (s, wantX, side) => {
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
      const fillFind = () =>
        Promise.all(spanSeasons().map(s => loadSeason(s, false, FAM[Q.fam].st))).then(list => {
          const last = {}, coaches = new Set();
          list.forEach(({ D, PL }) => { PL.forEach(([g, n]) => { last[g] = [n, D.season]; }); (D.coaches || []).forEach(c => coaches.add(c)); });
          const opts = [];
          if (Q.fam !== 'team') Object.entries(last).forEach(([g, [n, s]]) => opts.push([`${n} (${s})`, `P:${g}`, n]));
          [...coaches].forEach(c => opts.push([`${c} (head coach)`, `C:${c}`, c]));
          opts.sort((a, b) => a[0].localeCompare(b[0]));
          findMap = new Map(opts.map(o => [o[0], o]));
        });
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
        const wantG = Object.keys(Q.f).some(k => FILTERS[k].g);
        const wantC = Object.keys(Q.f).some(k => FILTERS[k].bio) || ['college', 'rnd'].some(k => Q.by === k || Q.by2 === k);
        Promise.all([...seasons.map(s => loadSeason(s, wantX, FAM[Q.fam].st, wantG)), wantC ? loadBio() : null]).then(list => {
          list = list.slice(0, seasons.length);
          if (BIO) BIO.fam = Q.fam;
          if (me !== busy) return;
          if (wantG) {  // a season without its game file (not built yet) is left out, and said so
            const miss = list.filter(m => !m.D.gx).map(m => m.D.season);
            list = list.filter(m => m.D.gx);
            if (miss.length) covEl.insertAdjacentHTML('beforeend', `<p class="tr-covnote">Game details (scores, rest, who played) aren't available for ${esc(ranges(miss))} yet, so ${miss.length > 1 ? 'those seasons are' : 'that season is'} left out.</p>`);
          }
          const [fam, m] = famMetric();
          const tests = Object.keys(Q.f).map(filterTest).filter(Boolean);
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
              for (let k = 0; k < tests.length; k++) if (!tests[k](P, j, G, V, D)) { ok = false; break; }
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
      const update = () => { Object.keys(Q.fn).forEach(k => { if (!(k in Q.f)) delete Q.fn[k]; }); save(); render(); run(); };

      // ---- events (delegated: the builder redraws on every change)
      qbox.addEventListener('input', e => {
        if (!e.target.matches('.tr-min input')) return;
        Q.min = +e.target.value; qbox.querySelector('.tr-min b').textContent = Q.min; save();
        if (paint) paint();  // re-filter only: the counts don't depend on the minimum
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
        const fx = e.target.closest('[data-fx]');
        if (fx) { pickFilter(fx.dataset.fx, fx); return; }
        const pk = e.target.closest('[data-pick]');
        if (pk && PICK[pk.dataset.pick]) { PICK[pk.dataset.pick](pk); return; }
        if (e.target.closest('.tq-reset')) {
          const last = IX.seasons[IX.seasons.length - 1];
          Q = Object.assign(defaults(), { from: Math.max(IX.seasons[0], last - 2), to: last });
          update();
          return;
        }
        if (e.target.closest('.tr-share')) {
          const t = btoa(unescape(encodeURIComponent(JSON.stringify(Q))));
          const url = `${location.origin}${location.pathname}?t=${encodeURIComponent(t)}#players/trends`;
          const ok = () => { const b = e.target.closest('.tr-share'); b.textContent = 'Link copied'; setTimeout(() => { b.textContent = 'Copy link'; }, 1600); };
          if (navigator.share && matchMedia('(pointer: coarse)').matches) navigator.share({ url }).catch(() => {});
          else if (navigator.clipboard) navigator.clipboard.writeText(url).then(ok, () => prompt('Copy this link', url));
          else prompt('Copy this link', url);
        }
      });
      NFLE.load('data/plays/index.json').then(ix => {
        IX = ix;
        return NFLE.load(`data/plays/${ix.seasons[ix.seasons.length - 1]}.json`).then(d => {
          IX.teams = d.teams.slice().sort();
          const vsIn = ts => { const set = new Set(ts); return (P, j, G, V, D) => set.has(D.teams[P.d[j]]); };
          FILTERS.vs.opts = [
            ...['AFC', 'NFC'].map(c => [c, `against the ${c}`, vsIn(Object.keys(DIVS).filter(d => d.startsWith(c)).flatMap(d => DIVS[d]))]),
            ...Object.entries(DIVS).map(([d, ts]) => [d, `against the ${d}`, vsIn(ts)]),
            ...IX.teams.map(t => [t, `against ${t}`, (P, j, G, V, D) => D.teams[P.d[j]] === t])];
          FILTERS.tm.opts = IX.teams.map(t => [t, `playing for ${t}`, (P, j, G, V, D) => D.teams[P.o[j]] === t]);
        });
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
        Q.fn = Q.fn || {};
        if (OUT_MOVED[Q.f.out]) { Q.f.yds = OUT_MOVED[Q.f.out]; delete Q.f.out; }
        Object.keys(Q.f).forEach(k => { if (!FILTERS[k] || !allowed(k, Q.fam)) delete Q.f[k]; });
        update();
      }).catch(() => { sec.querySelector('.tr-base').textContent = 'Play data is not available on this page.'; });
    },
  };
})();
