// (PC) grading accept / decline calls: the pre-registered gate (docs/INSIGHTS.md). Reads tools/pc_check.py's
// scratch/pc/ files and each season's walk-forward model (scratch/site/data/calc/wf/through_<season - 1>.json).
// (1) TRUST: the engine's win chance on every real snap, by down x zone, cells of 500+: trusted if |won - model| <= 2
//     points; a choice is graded only if both branch states sit in trusted cells.
// (2) SANITY: accepted defensive fouls with an automatic first down on an incomplete pass -> "accept" in 99%+.
// (3) SANITY: declined defensive offside on a play that gained a first down by 6+ yards -> "decline" in 99%+.
//   node tools/pc_check.mjs      (run by tools/pc_check.py)
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..');
const E = createRequire(import.meta.url)(join(ROOT, 'nfledge', 'static', 'calc_engine.js'));
const SEASONS = [2022, 2023, 2024, 2025];
const read = f => JSON.parse(readFileSync(join(ROOT, f), 'utf8'));
const zone = yl => (yl <= 30 ? 'opp 30-in' : yl <= 70 ? '31-70' : 'own 30-back');
const cellOf = st => `${st.down} | ${zone(st.yl)}`;
const NO_AFD = new Set(['Defensive Offside', 'Neutral Zone Infraction', 'Encroachment', 'Defensive Too Many Men on Field', 'Illegal Substitution', 'Defensive Delay of Game', 'Delay of Game']);

// (1) trust cells
const cells = {};
const calcs = {};
for (const s of SEASONS) {
  const C = E.createCalc(read(`scratch/site/data/calc/wf/through_${s - 1}.json`));
  calcs[s] = C;
  for (const [diff, sec, down, togo, yl, to, oppTo, line, home, rec2h, y] of read(`scratch/pc/snaps_${s}.json`)) {
    const st = { diff, sec, down, togo, yl, to, oppTo, line, home, rec2h };
    const c = cells[cellOf(st)] || (cells[cellOf(st)] = { n: 0, won: 0, p: 0 });
    c.n++; c.won += y; c.p += C.wp(st);
  }
}
const trusted = new Set();
console.log('(1) trust cells: down | zone   n   won   model   gap (points)');
for (const k of Object.keys(cells).sort()) {
  const c = cells[k], gap = 100 * (c.won - c.p) / c.n, ok = c.n >= 500 && Math.abs(gap) <= 2;
  if (ok) trusted.add(k);
  console.log(`  ${k.padEnd(16)} ${String(c.n).padStart(6)}  ${(c.won / c.n).toFixed(3)}  ${(c.p / c.n).toFixed(3)}  ${gap >= 0 ? '+' : ''}${gap.toFixed(2)}  ${ok ? 'trusted' : ''}`);
}

// grading
const graded = [], skipped = { trust: 0, ambiguous: 0 };
for (const s of SEASONS) {
  const C = calcs[s];
  for (const r of read(`scratch/pc/choices_${s}.json`)) {
    const states = [r.took, ...r.alt];
    if (!states.every(st => trusted.has(cellOf(st)))) { skipped.trust++; continue; }
    const gs = r.alt.map(alt => {
      const [accept, decline] = r.choice === 'accept' ? [r.took, alt] : [alt, r.took];
      return C.grade('penalty', { accept, decline, chooser: r.chooser }, r.choice);
    });
    if (new Set(gs.map(g => g.best)).size > 1) { skipped.ambiguous++; continue; }
    const g = gs.reduce((a, b) => (a.cost <= b.cost ? a : b));  // the smaller cost when two rebuilt states agree
    graded.push({ ...r, best: g.best, cost: g.cost, verdict: g.verdict, wpA: g.options.find(o => o.key === 'accept').wp, wpD: g.options.find(o => o.key === 'decline').wp });
  }
}
const total = graded.length + skipped.trust + skipped.ambiguous;
console.log(`\ngraded ${graded.length.toLocaleString()} of ${total.toLocaleString()} choices (left out: ${skipped.trust} a branch in an untrusted cell, ${skipped.ambiguous} spot rounding changes the answer)`);

// (2) and (3)
const s2 = graded.filter(r => r.choice === 'accept' && r.fouler === 'defense' && !NO_AFD.has(r.foul) && r.kind === 'incomplete');
const g2 = s2.filter(r => r.best === 'accept').length / s2.length;
const s3 = graded.filter(r => r.choice === 'decline' && r.foul === 'Defensive Offside' && r.took.down === 1 && r.took.own !== false && (r.yl - r.took.yl) - r.togo >= 6);
const g3 = s3.filter(r => r.best === 'decline').length / s3.length;
console.log(`(2) defense's automatic-first-down foul on an incomplete pass, accepted: model says accept ${(100 * g2).toFixed(1)}% of ${s2.length} -> ${g2 >= 0.99}`);
for (const r of s2.filter(r => r.best !== 'accept').slice(0, 5)) console.log(`     ${r.season} wk ${r.week} ${r.team}: accept ${(100 * r.wpA).toFixed(1)} decline ${(100 * r.wpD).toFixed(1)} | ${r.desc.slice(0, 140)}`);
console.log(`(3) declined defensive offside on a play that gained a first down by 6+: model says decline ${(100 * g3).toFixed(1)}% of ${s3.length} -> ${g3 >= 0.99}`);
for (const r of s3.filter(r => r.best !== 'decline').slice(0, 5)) console.log(`     ${r.season} wk ${r.week} ${r.team}: accept ${(100 * r.wpA).toFixed(1)} decline ${(100 * r.wpD).toFixed(1)} | ${r.desc.slice(0, 140)}`);

// reported either way
console.log('\nby season: graded / questionable (3+ points) / debatable');
for (const s of SEASONS) {
  const g = graded.filter(r => r.season === s);
  console.log(`  ${s}: ${g.length}  ${g.filter(r => r.verdict === 'questionable').length}  ${g.filter(r => r.verdict === 'debatable').length}`);
}
const dec = graded.filter(r => r.choice === 'decline'), acc = graded.filter(r => r.choice === 'accept');
console.log(`declines: ${dec.length}, questionable ${dec.filter(r => r.verdict === 'questionable').length}; accepts: ${acc.length}, questionable ${acc.filter(r => r.verdict === 'questionable').length}`);
console.log('\nthe 25 costliest calls (points of win chance given up):');
for (const r of [...graded].sort((a, b) => b.cost - a.cost).slice(0, 25)) {
  console.log(`  ${(100 * r.cost).toFixed(1).padStart(5)}  ${r.season} wk ${String(r.week).padStart(2)} ${r.team.padEnd(3)} ${r.choice.padEnd(7)} (best ${r.best}) Q${r.qtr} ${r.down}&${r.togo} at ${r.yl} diff ${r.diff >= 0 ? '+' : ''}${r.diff} | accept ${(100 * r.wpA).toFixed(1)} decline ${(100 * r.wpD).toFixed(1)}\n         ${r.desc.slice(0, 160)}`);
}
console.log(`\n[pc] GATE: (2) ${g2 >= 0.99}  (3) ${g3 >= 0.99}  (trust: ${trusted.size} of ${Object.keys(cells).length} cells) -> ${g2 >= 0.99 && g3 >= 0.99 && trusted.size ? 'PASS' : 'FAIL'}`);
