// (DI) gate (4), pre-registered 2026-10-25 (docs/INSIGHTS.md): the field goal check. On 480 states where kicking is
// the standard play (short kicks, not late, within 3), a made field goal is never worth more than 1 point LESS than the
// moment before it (that moment already holds a ~95%+ chance of making it). Each variant's model file from
// tools/di_eval.py (scratch/di/<variant>.json, fit through 2024). Pass: at most 1% of states (4) and fewer than current.
//   node tools/di_grid.mjs
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..');
const E = createRequire(import.meta.url)(join(ROOT, 'nfledge', 'static', 'calc_engine.js'));
const CLOCKS = [[1, '10:00'], [2, '8:00'], [3, '8:00'], [4, '10:00']];
const out = {};
for (const v of ['cur', 'a', 'b']) {
  const C = E.createCalc(JSON.parse(readFileSync(join(ROOT, 'scratch', 'di', `${v}.json`), 'utf8')));
  const bad = [];
  let n = 0, worst = 0;
  for (const [qtr, clock] of CLOCKS) for (const diff of [-3, 0, 3]) for (const line of [-7, -3, 0, 3, 7])
    for (const home of [1, 0]) for (const yl of [5, 10, 15, 20]) {
      const s = { diff, line, home, qtr, down: 4, togo: 8, yl, to: 3, oppTo: 3, rec2h: qtr <= 2 ? home : 0, sec: E.gameSec(qtr, clock) };
      const now = C.wp(s), made = C.fourth(s).fg.ifMade;
      n++;
      worst = Math.max(worst, now - made);
      if (made < now - 0.01) bad.push(`Q${qtr} ${clock} diff ${diff} line ${line} ${home ? 'home' : 'away'} at ${yl}: now ${(100 * now).toFixed(1)} made ${(100 * made).toFixed(1)}`);
    }
  out[v] = bad.length;
  console.log(`[di] (4) ${v}: ${bad.length} of ${n} states with a made field goal worth 1+ point less than the moment before; worst ${(100 * worst).toFixed(1)} points`);
  for (const b of bad.slice(0, 6)) console.log('   ', b);
}
for (const v of ['a', 'b']) console.log(`[di] (4) ${v}: ${out[v]} <= 4 and < current ${out.cur} -> ${out[v] <= 4 && out[v] < out.cur}`);
