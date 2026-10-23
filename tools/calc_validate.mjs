// (CJ) grades every 2022-25 regulation 4th down with the browser engine (static/calc_engine.js) and that season's
// walk-forward model file (tools/calc_validate.py has the steps).
//   node tools/calc_validate.mjs            -> scratch/calc_val/graded_<season>.json
//   node tools/calc_validate.mjs --boot     -> scratch/calc_val/bootgraded_2025.json (2025's plays x every boot_<seed>.json refit)
import { readFileSync, writeFileSync, readdirSync, existsSync } from 'node:fs';
import { createRequire } from 'node:module';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..');
const E = createRequire(import.meta.url)(join(ROOT, 'nfledge', 'static', 'calc_engine.js'));
const DIR = join(ROOT, 'scratch', 'calc_val');
const read = f => JSON.parse(readFileSync(join(DIR, f), 'utf8'));
const stateOf = r => ({ diff: r.diff, sec: r.sec, down: 4, togo: r.togo, yl: r.yl, to: r.to, oppTo: r.oppTo, line: r.line || 0,
  total: r.total || 45, home: r.home, rec2h: r.rec2h, roof: r.roof, wind: r.wind });
const gradeAll = (C, rows) => rows.map(r => {
  const g = C.grade('fourth', stateOf(r), r.choice);
  if (!g) return null;
  const w = Object.fromEntries(g.options.map(o => [o.key, o.wp]));
  const second = g.options[1] ? g.options[1].wp : g.options[0].wp;
  return { ...r, f_chosen: w[r.choice], best: g.best, gap: g.options[0].wp - second, w_go: w.go ?? null, w_fg: w.fg ?? null, w_punt: w.punt ?? null,
           p_conv: g.p && g.p.go };
}).filter(Boolean);

if (process.argv.includes('--boot')) {
  const rows = read('rows_2025.json'), base = E.createCalc(read('through_2024.json'));
  const baseG = Object.fromEntries(gradeAll(base, rows).map(r => [`${r.game_id}:${r.play_id}`, r]));
  const out = [];
  for (const f of readdirSync(DIR).filter(f => /^boot_\d+\.json$/.test(f))) {
    const C = E.createCalc(read(f));
    for (const r of gradeAll(C, rows)) {
      const k = `${r.game_id}:${r.play_id}`, b = baseG[k];
      if (b) out.push({ key: k, seed: f, best: r.best, gap: r.gap, base_best: b.best, base_gap: b.gap });
    }
    console.log(`[val] graded 2025 with ${f}`);
  }
  writeFileSync(join(DIR, 'bootgraded_2025.json'), JSON.stringify(out));
} else {
  for (const s of [2022, 2023, 2024, 2025]) {
    const mf = `through_${s - 1}.json`;
    if (!existsSync(join(DIR, mf))) { console.log(`[val] ${s}: no ${mf}`); continue; }
    const C = E.createCalc(read(mf)), rows = read(`rows_${s}.json`);
    const g = gradeAll(C, rows);
    writeFileSync(join(DIR, `graded_${s}.json`), JSON.stringify(g));
    console.log(`[val] ${s}: graded ${g.length} of ${rows.length}`);
  }
}
