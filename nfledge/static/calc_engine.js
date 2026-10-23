// Games > Calc's engine (owner 2026-10-23: "a calculator where you input down, distance, score, team timeouts left and
// game clock ... to make decisions, like whether to take a time out, whether to go for it on fourth down / punt / fg
// attempt, whether to onside kick, and whether to accept or decline a penalty"; (CG) in docs/INSIGHTS.md). Pure: the
// model file (data/calc/model.json: win probability trees from nfledge/winprob.py, decision inputs from
// nfledge/calc_inputs.py) in, numbers out; no DOM. UMD: NFLE.calcEngine in the browser, module.exports in Node
// (tools/calc_cli.mjs). Every decision is the same sum: each outcome's chance x the win probability after it.
//
// A state is from the side of the team with the ball: { diff (its score minus the other's), sec (game seconds left),
// down (1-4), togo, yl (yards to the end zone), to / oppTo (timeouts), line (its Vegas expected margin, + = favored),
// home (1 / 0), rec2h (1 = it receives the second-half kickoff) }.
(function (root, factory) {
  const E = factory();
  if (typeof module === 'object' && module.exports) module.exports = E;
  else { root.NFLE = root.NFLE || {}; root.NFLE.calcEngine = E; }
})(typeof self !== 'undefined' ? self : this, () => {
  const sig = z => 1 / (1 + Math.exp(-z));
  const KEYS = [['k_up12', 1, 2], ['k_up3', 3, 3], ['k_up46', 4, 6], ['k_up7', 7, 7], ['k_up8', 8, 8],
                ['k_dn12', -2, -1], ['k_dn3', -3, -3], ['k_dn46', -6, -4], ['k_dn7', -7, -7], ['k_dn8', -8, -8]];  // nfledge/winprob.py KEYS
  const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));
  const mean = a => a.reduce((t, v) => t + v, 0) / a.length;

  function createCalc(M) {
    const W = M.wp, I = M.inputs, F = W.features;
    const idx = Object.fromEntries(F.map((f, i) => [f, i]));
    // ---- tree models (win probability, conversion), exactly as sklearn evaluates them: left when x <= threshold
    const trees = (T, x) => {
      let z = T.baseline;
      for (const t of T.trees) {
        let j = 0;
        while (t[j][0] >= 0) { const n = t[j], v = x[n[0]]; j = Number.isNaN(v) ? (n[5] ? n[2] : n[3]) : (v <= n[1] ? n[2] : n[3]); }
        z += t[j][4];
      }
      return z;
    };
    const raw = x => trees(W, x);
    // the clock can be run out: the team that has the ball and leads, the other side short of timeouts (nfl4th's rule)
    const kneel = (sec, defTo) => (defTo === 0 && sec < 120) || (defTo === 1 && sec < 80) || (defTo === 2 && sec < 40);
    const featuresOf = s => {
      const sec = clamp(s.sec, 0, 3600), half = sec > 1800 ? sec - 1800 : sec, line = s.line || 0;
      const x = new Array(F.length);
      x[idx.score_diff] = s.diff; x[idx.game_sec] = sec; x[idx.half_sec] = half; x[idx.second_half] = sec <= 1800 ? 1 : 0;
      x[idx.down] = s.down || 0; x[idx.ydstogo] = s.togo; x[idx.yardline_100] = clamp(s.yl, 1, 99);
      x[idx.own_to] = s.to; x[idx.opp_to] = s.oppTo; x[idx.exp_margin] = line;
      x[idx.spread_time] = line * Math.exp(-4 * (1 - sec / 3600)); x[idx.home] = s.home ? 1 : 0;
      x[idx.receive_2h] = sec > 1800 ? (s.rec2h ? 1 : 0) : 0; x[idx.diff_time] = s.diff / Math.sqrt(sec + 1);
      // (CK) the score's football meaning: up 1-2 (a field goal beats it), 3 (ties), 4-6, 7, 8, and the same trailing
      for (const [k, lo, hi] of KEYS) if (idx[k] != null) x[idx[k]] = s.diff >= lo && s.diff <= hi ? 1 : 0;
      return x;
    };
    // (CJ, 2026-10-23, found by comparing with nfl4th) the half can end: a play that takes the rest of a half ends it
    // (later() marks the state "over"), so a non-scoring conversion with 0:03 left before halftime is worth the
    // halftime score, not a new set of downs; and a leader with the ball who can kneel it out has won, whatever led
    // there (it had only been applied after a failed 4th down, so punting while trailing late read too kindly)
    const later = (s, t) => {
      const end = s.sec > 1800 ? 1800 : 0, sec = s.sec - t;
      return sec <= end ? { ...s, sec: end, over: true } : { ...s, sec };
    };
    const wp = s => {
      if (s.over && s.sec >= 1800) {
        // halftime: the second-half kickoff, to whoever receives it (rec2h: the team with the ball here)
        const k = { ...s, over: false, sec: 1800, down: 1, togo: 10, yl: I.kickoff.rec[5] };
        return s.rec2h ? wp(k) : 1 - wp({ ...flip(k), sec: 1800, down: 1, togo: 10, yl: I.kickoff.rec[5] });
      }
      if (s.sec <= 0) return s.diff > 0 ? 1 : s.diff < 0 ? 0 : 0.5;  // time's up (overtime: a coin flip here)
      if (s.diff > 0 && s.sec <= 120 && kneel(s.sec, s.oppTo)) return 1;  // the leader kneels it out
      return sig(raw(featuresOf(s)));
    };
    // the other team's side of the same moment
    const flip = s => ({ ...s, diff: -s.diff, to: s.oppTo, oppTo: s.to, line: -(s.line || 0), home: s.home ? 0 : 1, rec2h: s.rec2h ? 0 : 1 });
    // a new possession for the OTHER team: 1st & 10 at `yl` (its yards to the end zone), the clock run by `t`
    const theirBall = (s, yl, t, pts = 0) => { const o = flip({ ...s, diff: s.diff + pts }); return 1 - wp(later({ ...o, down: 1, togo: Math.min(10, yl), yl }, t)); };
    const PLAY = I.clock.play_len;  // a snap's own length
    // after we score: they receive the kickoff (its measured landing spots: the 2025 rules)
    const afterScore = (s, pts, t = PLAY) => mean(I.kickoff.rec.map(yl => theirBall(s, yl, t + 5, pts)));
    const afterTD = (s, t = PLAY) => I.tries.xp * afterScore(s, 7, t) + (1 - I.tries.xp) * afterScore(s, 6, t);
    const bucket = (arr, v) => arr.find(b => v >= b.lo && v <= b.hi) || arr[arr.length - 1];

    // ---- inputs (the page can override the two that matter most: opts.conv, opts.fg). s.total: the over/under;
    // s.roof: 'outdoors' | 'dome' | 'retractable'; s.wind: mph (outdoors)
    const roofOf = s => ({ outdoors: (s.roof || 'outdoors') === 'outdoors' ? 1 : 0, dome: s.roof === 'dome' ? 1 : 0, retractable: s.roof === 'retractable' ? 1 : 0 });
    // P(a 4th-down try converts) for an average team in this spot: trees on 3rd and 4th downs with team strength (the
    // spread, total, team total) and roof, asked at down 3 (2026-10-23: 4th-down tries are chosen, teams go when they
    // expect to make it: from their own 20-45, 4th & 10 converted 36% of 61 tries, 3rd & 10 31.5% of 1,287; at down 4
    // the trees said 42%). A team that knows better types its own rate.
    const convP = s => {
      const C = M.conv, r = roofOf(s), total = s.total || 45, line = s.line || 0;
      const v = { down: 3, ydstogo: s.togo, yardline_100: s.yl, spread: line, total, team_total: (total + line) / 2, ...r };
      return sig(trees(C, C.features.map(f => v[f])));
    };
    const fgDist = yl => yl + I.fg.offset;
    // make rate: the recent table, shifted for roof and wind (outdoors; unknown wind = a typical 8 mph)
    const fgP = (yl, s = {}) => {
      const f = I.fg, d = Math.round(fgDist(yl));
      if (d > f.from + f.rate.length - 1) return 0;
      const p = clamp(d < f.from ? f.rate[0] : f.rate[d - f.from], 1e-4, 1 - 1e-4), rw = f.roof_wind;
      // past 64 yd only strong kickers try, so the record flatters an average one: tapered to 0 at 70 (nfl4th's rule)
      const taper = clamp((70 - d) / 6, 0, 1);
      if (!rw) return p * taper;
      const o = roofOf(s).outdoors, ow = o * (s.wind != null && s.wind !== '' ? +s.wind : 8);
      return taper * sig(Math.log(p / (1 - p)) + rw.outdoors * (o - rw.mean_out) + rw.wind_out * (ow - rw.mean_ow));
    };
    const gainsAt = (togo, yl) => { const b = bucket(I.gains.buckets, togo); return b.bands.find(x => yl > x.lo && yl <= x.hi) || b.bands[b.bands.length - 1]; };

    // ---- 4th down: go / field goal / punt
    function fourth(s, opts = {}) {
      const pc = opts.conv != null ? opts.conv : convP(s);
      const g = gainsAt(s.togo, s.yl);
      const succ = g.succ_over.map(o => {
        const gain = s.togo + Math.max(0, o);
        if (gain >= s.yl) return afterTD(s);
        return wp(later({ ...s, down: 1, yl: s.yl - gain, togo: Math.min(10, s.yl - gain) }, PLAY));
      });
      // failed: their ball at the spot
      const fail = g.fail.map(f => theirBall(s, clamp(100 - (s.yl - Math.min(f, s.togo - 1)), 1, 99), PLAY));
      const go = pc * mean(succ) + (1 - pc) * mean(fail);
      const out = { go: { wp: go, p: pc, ifMade: mean(succ), ifMissed: mean(fail) } };
      const pf = opts.fg != null ? opts.fg : fgP(s.yl, s);
      if (fgDist(s.yl) <= 70) {
        // a miss: their ball at the spot of the kick (7 yards behind the line), at least their own 20
        const spot = s.yl + 7, missYl = spot <= 20 ? 80 : 100 - spot;
        const made = afterScore(s, 3), missed = theirBall(s, missYl, PLAY);
        out.fg = { wp: pf * made + (1 - pf) * missed, p: pf, dist: fgDist(s.yl), ifMade: made, ifMissed: missed, rare: fgDist(s.yl) >= 60 };
      }
      if (s.yl >= 30) {
        // every punt: blocked (their ball about where it was kicked), muffed and lost (ours where they'd have had it),
        // returned for a touchdown (they score), else their spot
        const b = bucket(I.punts.bands, clamp(s.yl, I.punts.bands[0].lo, 99)), mid = b.rec[5];
        const clean = mean(b.rec.map(r => theirBall(s, r, PLAY + 3)));
        const blocked = theirBall(s, clamp(100 - s.yl - 7, 1, 99), PLAY);
        const muffed = wp(later({ ...s, down: 1, togo: Math.min(10, 100 - mid), yl: clamp(100 - mid, 1, 99) }, PLAY + 3));
        const retTd = 1 - afterTD(flip(s), PLAY + 3);
        const pClean = 1 - b.p_block - b.p_muff - b.p_ret_td;
        out.punt = { wp: pClean * clean + b.p_block * blocked + b.p_muff * muffed + b.p_ret_td * retTd, net: mean(b.rec),
                     p_block: b.p_block, p_muff: b.p_muff, p_ret_td: b.p_ret_td };
      }
      return out;
    }

    // ---- after a touchdown (the score already counts the six): kick the extra point or go for two
    function tries(s) {
      const k = { ...s };
      const xp = I.tries.xp * afterScore(k, 1, 0) + (1 - I.tries.xp) * afterScore(k, 0, 0);
      const two = I.tries.two * afterScore(k, 2, 0) + (1 - I.tries.two) * afterScore(k, 0, 0);
      return { xp: { wp: xp, p: I.tries.xp }, two: { wp: two, p: I.tries.two } };
    }

    // ---- kicking off after a score (s: the kicking team's side; its down / distance / field position unused)
    function onside(s, opts = {}) {
      const p = opts.onside != null ? opts.onside : I.onside.p;
      const kept = wp(later({ ...s, down: 1, togo: 10, yl: I.onside.kept_yl }, PLAY));
      const lost = theirBall(s, I.onside.lost_yl, PLAY);
      const normal = mean(I.kickoff.rec.map(yl => theirBall(s, yl, PLAY)));
      return { onside: { wp: p * kept + (1 - p) * lost, p, ifKept: kept, ifLost: lost }, kick: { wp: normal } };
    }

    // ---- a timeout with the clock running (s: the team with the ball; who: 'offense' | 'defense' calls it). Calling
    // it keeps the time a running clock would lose before the next snap and costs one timeout. That time is the
    // offense's pace there, measured (I.clock.pace: 2026-10-23, 39 s between snaps normally, ~21 when hurrying at a
    // half's end, 44 for a 4th-quarter leader in the last two minutes) minus the play's own length; the clock stops at
    // the two-minute warning anyway.
    const runOff = s => {
      const first = s.sec > 1800, half = first ? s.sec - 1800 : s.sec;
      const band = half <= 120 ? 'two' : half <= 300 ? 'five' : 'normal';
      const pace = I.clock.pace[`${first ? 2 : 4}:${band}:${s.diff > 0 ? 'lead' : 'trail'}`] || I.clock.normal;
      const lose = Math.max(0, pace - I.clock.play_len);
      return half > 120 && half - lose < 120 ? half - 120 : Math.min(lose, half);
    };
    function timeout(s, who = 'offense') {
      const off = who === 'offense';
      const callS = off ? { ...s, to: s.to - 1 } : { ...s, oppTo: s.oppTo - 1 };
      const runS = later(s, runOff(s));
      // averaged over clocks 0-12 s around each (the trees step between nearby seconds, about the size of a timeout's
      // effect; a constrained-time model that smoothed it underfit the last seconds: nfledge/winprob.py)
      const smooth = st => mean([0, 3, 6, 9, 12].map(k => wp({ ...st, sec: Math.max(1, st.sec - k + 6) })));
      const mine = st => (off ? smooth(st) : 1 - smooth(st));
      return { call: { wp: mine(callS) }, run: { wp: mine(runS), seconds: runOff(s) }, can: off ? s.to > 0 : s.oppTo > 0 };
    }

    // ---- a penalty: the choosing team's chance after accepting vs declining. accept / decline: states from the side of
    // the team with the ball then; chooser: 'offense' | 'defense'
    function penalty(accept, decline, chooser = 'offense') {
      const mine = st => (chooser === 'offense' ? wp(st) : 1 - wp(st));
      return { accept: { wp: mine(accept) }, decline: { wp: mine(decline) } };
    }

    // ---- grading a call made in a game (owner 2026-10-23: "identify questionable decisions made in games ... point out
    // the bad ones in hindsight"): every option's chance before the snap and what the chosen one gave up. kind 'fourth'
    // (choice go / fg / punt) or 'try' (xp / two). Verdicts: under TOSS fine (inside the model's noise), under
    // QUESTION debatable, else questionable. Judged before the snap, never by how the play turned out.
    // TOSS: (CJ) 20 bootstrap refits, 2025's 3,765 4th downs: under 1.25 points the recommendation flips in more than 1
    // refit in 5 (was 1.5 by judgment); past 3 points it flips in 4%, past 5 under 1%
    const TOSS = 0.0125, QUESTION = 0.03;
    const LABEL = { go: 'Go for it', fg: 'Field goal', punt: 'Punt', xp: 'Extra point', two: 'Go for two' };
    function grade(kind, s, choice, opts = {}) {
      let o;
      if (kind === 'try') { const t = tries(s); o = { xp: t.xp.wp, two: t.two.wp }; }
      else { const f = fourth(s, opts); o = { go: f.go.wp }; if (f.fg) o.fg = f.fg.wp; if (f.punt) o.punt = f.punt.wp; o._p = { go: f.go.p, fg: f.fg && f.fg.p }; }
      const p = o._p; delete o._p;
      const ranked = Object.entries(o).sort((x, y) => y[1] - x[1]);
      const best = ranked[0], chosen = o[choice];
      if (chosen == null) return null;
      const cost = best[1] - chosen;
      return { options: ranked.map(([k, v]) => ({ key: k, label: LABEL[k], wp: v })), best: best[0], choice, cost, p,
               verdict: cost < TOSS ? 'fine' : cost < QUESTION ? 'debatable' : 'questionable' };
    }

    return { wp, later, fourth, tries, onside, timeout, penalty, grade, TOSS, QUESTION, convP, fgP, fgDist, featuresOf, raw, convRaw: x => trees(M.conv, x), flip, kneel, inputs: I, meta: { built: M.built, seasons: M.seasons } };
  }

  // the self-check: the trees give the model's own numbers (tools/calc_cli.mjs --check)
  function selfCheck(M) {
    const c = createCalc(M);
    const wpWorst = (M.check || []).reduce((worst, r) => Math.max(worst, Math.abs(sig(c.raw(r.x)) - r.p)), 0);
    return (M.conv_check || []).reduce((worst, r) => Math.max(worst, Math.abs(sig(c.convRaw(r.x)) - r.p)), wpWorst);
  }

  // seconds left in the game from quarter (1-4) and the quarter clock "m:ss"
  const gameSec = (qtr, clock) => { const [m, ss] = String(clock || '15:00').split(':').map(Number); return (4 - qtr) * 900 + (m || 0) * 60 + (ss || 0); };

  return { createCalc, selfCheck, gameSec };
});
