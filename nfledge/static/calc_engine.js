// Model > Calc's engine (owner 2026-10-23: "a calculator where you input down, distance, score, team timeouts left and
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
  const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));
  const mean = a => a.reduce((t, v) => t + v, 0) / a.length;

  function createCalc(M) {
    const W = M.wp, I = M.inputs, F = W.features, FGC = M.wp_fg || null;  // (DH) make curve for the win model's fgp
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
    // (CN2, owner 2026-10-23, ATL tied at its own 45 with 0:08 and no timeouts: "the realistic likelihood you will get
    // into fg range from there and be able to kick without a timeout must be tiny") the last snap as football rules: a
    // field goal or a heave for a touchdown, whichever is better (a leader kneels), then the score decides and a tie
    // is overtime at 50%. On 493 real final snaps (2019-25) it beat the model, Brier 0.0880 vs 0.1014 (tied near
    // midfield: won 50%, this 51%, the model 66.5%). Heave touchdown rates: half-ending passes with 0:06 or less.
    const FINAL = d => (d > 0 ? 1 : d < 0 ? 0 : 0.5);
    const HEAVE = yl => (yl <= 20 ? 0.30 : yl <= 50 ? 0.03 : yl <= 60 ? 0.015 : 0.003);
    let fgPRef = null;  // set once fgP exists (defined below)
    const lastSnap = s => {
      if (s.diff > 0) return 1;
      let best = FINAL(s.diff);
      if (fgPRef && s.yl + 18 <= 70) { const p = fgPRef(s.yl, s); best = Math.max(best, p * FINAL(s.diff + 3) + (1 - p) * FINAL(s.diff)); }
      const h = HEAVE(s.yl);
      return Math.max(best, h * FINAL(s.diff + 7) + (1 - h) * FINAL(s.diff));
    };
    const SNAP_GAP = 10, LAST = 12, OOB = 0.136;  // a spike or snap needs ~10 s; 13.6% of late conversions end out of bounds
    // the clock can be run out: the team that has the ball and leads, the other side short of timeouts. Each down left
    // after this snap lets ~40 s run off; each defensive timeout takes one of those back. On 1st down this is nfl4th's
    // rule (0 timeouts: 2:00, 1: 1:20, 2: 0:40); (owner 2026-10-23: "does our engine know the difference between a team
    // winning with 1:59 left, defense has 3 timeouts vs 0?") it had ignored the down, so 3rd & 10 at 1:59 against no
    // timeouts read a sure win when only ~0:40 can be run off before a punt.
    const kneel = (sec, defTo, down = 1) => sec < 40 * Math.max(0, 4 - (down || 1) - defTo);
    // (DI, {#home-skew}: failed; the live file has neither shape, kept so tools/di_grid.mjs reproduces the result)
    // side 0: the same moment from the defense's side (a possession-symmetric model file, W.sym): its score,
    // timeouts, line, home and second-half receiver; the ball team's yards to the end zone, yards to go and fgp negated
    const featuresOf = (s, side = 1) => {
      const d = side ? s : { ...s, diff: -s.diff, to: s.oppTo, oppTo: s.to, line: -(s.line || 0), home: s.home ? 0 : 1, rec2h: s.rec2h ? 0 : 1 };
      const sg = side ? 1 : -1;
      const sec = clamp(d.sec, 0, 3600), half = sec > 1800 ? sec - 1800 : sec, line = d.line || 0;
      const x = new Array(F.length);
      x[idx.score_diff] = d.diff; x[idx.game_sec] = sec; x[idx.half_sec] = half; x[idx.second_half] = sec <= 1800 ? 1 : 0;
      x[idx.down] = d.down || 0; x[idx.ydstogo] = sg * d.togo; x[idx.yardline_100] = sg * clamp(d.yl, 1, 99);
      x[idx.own_to] = d.to; x[idx.opp_to] = d.oppTo; x[idx.exp_margin] = line;
      x[idx.spread_time] = line * Math.exp(-4 * (1 - sec / 3600));
      if (idx.home != null) x[idx.home] = d.home ? 1 : 0;  // (DI a) a model file may not carry it
      x[idx.receive_2h] = sec > 1800 ? (d.rec2h ? 1 : 0) : 0; x[idx.diff_time] = d.diff / Math.sqrt(sec + 1);
      // (DH, {#fg-input}) the field goal's make chance from the spot, by the season's curve (fit on the three seasons
      // before it); a kickoff (no down) has none, as in training
      if (idx.fgp != null) x[idx.fgp] = d.down && FGC ? sg * sig(FGC.a + FGC.b * (clamp(d.yl, 1, 99) + (FGC.snap || 17))) : NaN;
      if (idx.ball != null) x[idx.ball] = side;
      return x;
    };
    // (DI b) a symmetric file: the ball side's chance and 1 - the defense side's, averaged (the two teams sum to 1)
    const modelWp = s => W.sym ? (sig(raw(featuresOf(s, 1))) + 1 - sig(raw(featuresOf(s, 0)))) / 2 : sig(raw(featuresOf(s)));
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
      if (s.diff > 0 && s.sec <= 120 && kneel(s.sec, s.oppTo, s.down)) return 1;  // the leader kneels it out
      if (s.sec <= 6) return lastSnap(s);  // (CN2) the 4th quarter's last snap
      // (CK2, the owner's call 2026-10-23: "can we treat 1 and 2 point leads as the same thing?") late, a 1- and a
      // 2-point lead are one state (a field goal beats both): their average. Only late (owner: "the time left matters a
      // lot": with time for more scoring, 1 vs 2 decides 6 vs 7 and 8 vs 9 later). Real games, team with the ball
      // (2019-25): up 1 vs up 2 won 59.5% vs 72.8% with 10:00-15:00 left and 64.7 vs 78.1 with 6:00-10:00, but 67.9 vs
      // 63.2 with 3:00-6:00 and 94.4 vs 90.4 inside 3:00 ((CL), tools/poss_eval.py). So: in full inside 6:00, fading
      // to nothing at 8:00; above that the model's own pricing, which matches those games
      const a = Math.abs(s.diff), w = clamp((480 - s.sec) / 120, 0, 1);
      if (w > 0 && (a === 1 || a === 2) && !s.eq) {
        const g = Math.sign(s.diff), own = wp({ ...s, eq: 1 });
        return w * (wp({ ...s, diff: g, eq: 1 }) + wp({ ...s, diff: 2 * g, eq: 1 })) / 2 + (1 - w) * own;
      }
      return modelWp(s);
    };
    // the other team's side of the same moment
    const flip = s => ({ ...s, diff: -s.diff, to: s.oppTo, oppTo: s.to, line: -(s.line || 0), home: s.home ? 0 : 1, rec2h: s.rec2h ? 0 : 1 });
    // a new possession for the OTHER team: 1st & 10 at `yl` (its yards to the end zone), the clock run by `t`
    const theirBall = (s, yl, t, pts = 0) => {
      const o = later({ ...flip({ ...s, diff: s.diff + pts }), down: 1, togo: Math.min(10, yl), yl }, t);
      // (CN2) a change of possession stops the clock: with 0:12 or less left they get one snap
      if (!o.over && o.sec <= LAST && o.sec > 0) return 1 - lastSnap(o);
      return 1 - wp(o);
    };
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
    const fgP = (yl, s = {}) => {  // (lastSnap reads it through fgPRef)
      const f = I.fg, d = Math.round(fgDist(yl));
      if (d > f.from + f.rate.length - 1) return 0;
      const p = clamp(d < f.from ? f.rate[0] : f.rate[d - f.from], 1e-4, 1 - 1e-4), rw = f.roof_wind;
      // past 64 yd only strong kickers try, so the record flatters an average one: tapered to 0 at 70 (nfl4th's rule)
      const taper = clamp((70 - d) / 6, 0, 1);
      if (!rw) return p * taper;
      const o = roofOf(s).outdoors, ow = o * (s.wind != null && s.wind !== '' ? +s.wind : 8);
      return taper * sig(Math.log(p / (1 - p)) + rw.outdoors * (o - rw.mean_out) + rw.wind_out * (ow - rw.mean_ow));
    };
    fgPRef = fgP;
    const gainsAt = (togo, yl) => { const b = bucket(I.gains.buckets, togo); return b.bands.find(x => yl > x.lo && yl <= x.hi) || b.bands[b.bands.length - 1]; };

    // ---- 4th down: go / field goal / punt
    function fourth(s, opts = {}) {
      const pc = opts.conv != null ? opts.conv : convP(s);
      const g = gainsAt(s.togo, s.yl);
      const succ = g.succ_over.map(o => {
        const gain = s.togo + Math.max(0, o);
        if (gain >= s.yl) return afterTD(s);
        const n = later({ ...s, down: 1, yl: s.yl - gain, togo: Math.min(10, s.yl - gain) }, opts.convSec ?? PLAY);  // (CO2) convSec: the diagnostic's clock
        if (!n.over && n.sec <= LAST && n.sec > 0) {
          // (CN2) a timeout (or a spike, with time for one) buys one snap; else only if the play ended out of bounds
          if (n.to > 0 || n.sec >= SNAP_GAP) return lastSnap(n);
          return OOB * lastSnap(n) + (1 - OOB) * FINAL(n.diff);
        }
        return opts.convSec != null || n.over ? wp(n) : nextSnap(n);
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
    // (CO3, owner 2026-10-23: "time outs, 5 seconds would be accurate ... hurry up offense isn't letting 40 seconds
    // burn") after a converted 4th down the clock runs to the next snap at the offense's pace (runOff), not 5 s (the
    // real median was 37). Out of bounds (13.6%) stops it only in a half's late window (the 1st half's last 2:00, the
    // game's last 5:00) and only for a team not ahead (a leader stays in bounds); there a team not ahead with a
    // timeout takes the better of calling it and letting the clock run (and a defense behind, the better for it).
    const nextSnap = n => {
      const first = n.sec > 1800, half = first ? n.sec - 1800 : n.sec;
      const run = wp(later(n, runOff(n))), late = half <= (first ? 120 : 300);
      // (CO3 amended) a defense behind late stops that run with a timeout when it helps it
      if (late && n.diff > 0) return n.oppTo > 0 ? Math.min(run, wp({ ...n, oppTo: n.oppTo - 1 })) : run;
      if (!(late && n.diff <= 0)) return run;
      // (found 2026-10-23 comparing with nfl4th: IND down 1 at the SEA 38 with 0:22 and no timeouts read "if it works"
      // 10.6%, the clock running out the game) or it spikes the ball: a down for ~10 s
      const spike = wp(later({ ...n, down: n.down + 1 }, SNAP_GAP));
      const inb = Math.max(run, spike, n.to > 0 ? wp({ ...n, to: n.to - 1 }) : 0);
      return OOB * wp(n) + (1 - OOB) * inb;
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

    // ---- a penalty: the choosing team's chance after accepting vs declining. accept / decline: the next snap's state
    // under each, from the side of the team with the ball at the foul's snap, or (own: false, a turnover on downs) from
    // the other team's; chooser: 'offense' | 'defense' (of that snap). (PC) both valued the same way, by wp()
    function penalty(accept, decline, chooser = 'offense') {
      const offense = st => (st.own === false ? 1 - wp(st) : wp(st));
      const mine = st => (chooser === 'offense' ? offense(st) : 1 - offense(st));
      return { accept: { wp: mine(accept) }, decline: { wp: mine(decline) } };
    }

    // ---- grading a call made in a game (owner 2026-10-23: "identify questionable decisions made in games ... point out
    // the bad ones in hindsight"): every option's chance before the snap and what the chosen one gave up. kind 'fourth'
    // (choice go / fg / punt) or 'try' (xp / two). Verdicts: under TOSS fine (inside the model's noise), under
    // QUESTION debatable, else questionable. Judged before the snap, never by how the play turned out.
    // TOSS: (CJ) 20 bootstrap refits, 2025's 3,765 4th downs: under 1.25 points the recommendation flips in more than 1
    // refit in 5 (was 1.5 by judgment); past 3 points it flips in 4%, past 5 under 1%
    const TOSS = 0.0125, QUESTION = 0.03;
    const LABEL = { go: 'Go for it', fg: 'Field goal', punt: 'Punt', xp: 'Extra point', two: 'Go for two', accept: 'Accept', decline: 'Decline' };
    // kind 'penalty' (PC): s = { accept, decline, chooser } (penalty()'s arguments), choice accept / decline
    function grade(kind, s, choice, opts = {}) {
      let o;
      if (kind === 'try') { const t = tries(s); o = { xp: t.xp.wp, two: t.two.wp }; }
      else if (kind === 'penalty') { const p = penalty(s.accept, s.decline, s.chooser); o = { accept: p.accept.wp, decline: p.decline.wp }; }
      else { const f = fourth(s, opts); o = { go: f.go.wp }; if (f.fg) o.fg = f.fg.wp; if (f.punt) o.punt = f.punt.wp; o._p = { go: f.go.p, fg: f.fg && f.fg.p, goMade: f.go.ifMade, goMissed: f.go.ifMissed, fgMade: f.fg && f.fg.ifMade, fgMissed: f.fg && f.fg.ifMissed }; }
      const p = o._p; delete o._p;
      const ranked = Object.entries(o).sort((x, y) => y[1] - x[1]);
      const best = ranked[0], chosen = o[choice];
      if (chosen == null) return null;
      const cost = best[1] - chosen;
      // toss: the top two within TOSS, so no option is "best" (owner 2026-10-27: a neutral toss-up, no lean either way)
      const toss = ranked.length > 1 && best[1] - ranked[1][1] < TOSS;
      return { options: ranked.map(([k, v]) => ({ key: k, label: LABEL[k], wp: v })), best: best[0], toss, choice, cost, p,
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
