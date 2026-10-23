// (CO2) scores the real next snap after converted tries / missed field goals with the engine's wp(), beside the
// branch the engine assumed (tools/branch_eval.py has the steps).
import { readFileSync, writeFileSync, existsSync } from 'node:fs';
import { createRequire } from 'node:module';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..');
const E = createRequire(import.meta.url)(join(ROOT, 'nfledge', 'static', 'calc_engine.js'));
const DIR = join(ROOT, 'scratch', 'calc_val');
const read = f => JSON.parse(readFileSync(join(DIR, f), 'utf8'));
const RUN = +(process.argv.find(a => a.startsWith('--run=')) || '--run=39').slice(6);
const out = [];
for (const s of [2022, 2023, 2024, 2025]) {
  if (!existsSync(join(DIR, `next_${s}.json`))) continue;
  const C = E.createCalc(read(`through_${s - 1}.json`));
  for (const r of read(`next_${s}.json`)) {
    const st = { diff: r.diff, sec: r.sec, down: 1, togo: r.togo, yl: r.yl, to: r.to, oppTo: r.oppTo, line: r.line || 0,
      total: r.total || 45, home: r.home, rec2h: r.rec2h, roof: r.roof, wind: r.wind };
    const f_next = r.choice === 'go' ? C.wp(st) : 1 - C.wp(st);  // the trying team's side
    let f_run = null;
    if (r.choice === 'go') {
      const s0 = { diff: r.diff0, sec: r.sec0, down: 4, togo: r.togo0, yl: r.yl0, to: r.to, oppTo: r.oppTo, line: r.line || 0,
        total: r.total || 45, home: r.home, rec2h: r.rec2h, roof: r.roof, wind: r.wind };
      f_run = C.fourth(s0, { convSec: RUN }).go.ifMade;
    }
    out.push({ ...r, f_next, f_run });
  }
}
writeFileSync(join(DIR, 'nextgraded.json'), JSON.stringify(out));
console.log(`[co2] scored ${out.length} next snaps (clock run ${RUN} s)`);
