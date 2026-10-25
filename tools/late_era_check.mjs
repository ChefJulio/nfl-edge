// (DF) late-game era check (tools/late_era_check.py): each 2022-25 late snap scored by the engine's wp() with a model
// fit on 2006-18 and with the walk-forward model fit through the season before.
import { readFileSync, writeFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..');
const E = createRequire(import.meta.url)(join(ROOT, 'nfledge', 'static', 'calc_engine.js'));
const DIR = join(ROOT, 'scratch', 'calc_val');
const read = f => JSON.parse(readFileSync(join(DIR, f), 'utf8'));
const old = E.createCalc(read('through_2018.json'));
const wf = {};
for (const s of [2022, 2023, 2024, 2025]) wf[s] = E.createCalc(read(`through_${s - 1}.json`));
const st = r => ({ diff: r.diff, sec: r.sec, down: r.down, togo: r.togo, yl: r.yl, to: r.to, oppTo: r.oppTo, line: r.line || 0,
  total: r.total || 45, home: r.home, rec2h: 0 });
const out = read('late_rows.json').map(r => ({ ...r, p_old: old.wp(st(r)), p_wf: wf[r.season].wp(st(r)) }));
writeFileSync(join(DIR, 'late_scored.json'), JSON.stringify(out));
console.log(`[df] scored ${out.length}`);
