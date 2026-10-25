// (DG) late correction test (tools/late_corr_eval.py): each 2006-25 late snap scored by the engine wp() with the model
// fit on 2006-18.
import { readFileSync, writeFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..');
const E = createRequire(import.meta.url)(join(ROOT, 'nfledge', 'static', 'calc_engine.js'));
const DIR = join(ROOT, 'scratch', 'calc_val');
const read = f => JSON.parse(readFileSync(join(DIR, f), 'utf8'));
const old = E.createCalc(read('through_2018.json'));
const st = r => ({ diff: r.diff, sec: r.sec, down: r.down, togo: r.togo, yl: r.yl, to: r.to, oppTo: r.oppTo, line: r.line || 0,
  total: r.total || 45, home: r.home, rec2h: 0 });
const out = read('latecorr_rows.json').map(r => ({ ...r, p: old.wp(st(r)) }));
writeFileSync(join(DIR, 'latecorr_scored.json'), JSON.stringify(out));
console.log(`[dg] scored ${out.length}`);
