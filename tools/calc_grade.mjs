// Model > Calc > Graded calls (owner 2026-10-23: "default it to sort by most controversial ... group the tables by week
// and season"): every 4th down of each season from data/calc/plays_<season>.json, graded with the browser engine
// (static/calc_engine.js) and a model fit only on the seasons before it (data/calc/wf/through_<year>.json, both from
// tools/calc_build.py). Writes data/calc/graded_<season>.json and data/calc/graded.json (the index). Run in the full
// build and the UI-only path, so the grades follow the engine.
//   node tools/calc_grade.mjs --site=site
import { readFileSync, writeFileSync, readdirSync, existsSync } from 'node:fs';
import { createRequire } from 'node:module';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..');
const site = (process.argv.find(a => a.startsWith('--site=')) || '--site=site').slice(7);
const DIR = join(ROOT, site, 'data', 'calc');
const E = createRequire(import.meta.url)(join(ROOT, 'nfledge', 'static', 'calc_engine.js'));
const read = f => JSON.parse(readFileSync(join(DIR, f), 'utf8'));
const r3 = v => (v == null ? null : Math.round(v * 1000) / 1000);

const seasons = existsSync(DIR) ? readdirSync(DIR).map(f => (f.match(/^plays_(\d{4})\.json$/) || [])[1]).filter(Boolean).map(Number).sort() : [];
const index = { built: new Date().toISOString().slice(0, 10), seasons: [] };
for (const s of seasons) {
  const mf = join('wf', `through_${s - 1}.json`);
  if (!existsSync(join(DIR, mf))) { console.log(`[grade] ${s}: no ${mf}`); continue; }
  const M = read(mf), C = E.createCalc(M);
  const out = [];
  for (const r of read(`plays_${s}.json`)) {
    const st = { diff: r.diff, sec: r.sec, down: 4, togo: r.togo, yl: r.yl, to: r.to, oppTo: r.oppTo, line: r.line || 0,
      total: r.total || 45, home: r.home, rec2h: r.rec2h, roof: r.roof, wind: r.wind };
    const g = C.grade('fourth', st, r.choice);
    if (!g) continue;
    const w = Object.fromEntries(g.options.map(o => [o.key, r3(o.wp)]));
    const p = g.p || {};
    out.push({ g: r.game_id, w: r.week, t: r.team, o: r.opp, h: r.home, q: r.qtr, s: r.sec, d: r.diff, tg: r.togo, yl: r.yl,
      to: r.to, ot: r.oppTo, ln: r.line, tt: r.total, rf: r.roof, wd: r.wind, r2: r.rec2h,
      c: r.choice, b: g.best, x: r3(Math.max(0, (w[g.best] ?? 0) - (w[r.choice] ?? 0))), op: w,
      pc: r3(p.go), gm: r3(p.goMade), gf: r3(p.goMissed), pf: r3(p.fg), fm: r3(p.fgMade), ff: r3(p.fgMissed),
      cv: r.choice === 'go' ? r.conv : r.choice === 'fg' ? r.fgm : null, res: r.result, ds: r.desc, sc: [r.pts, r.opp_pts] });
  }
  writeFileSync(join(DIR, `graded_${s}.json`), JSON.stringify({ season: s, through: s - 1, seasons: M.seasons, rows: out }));
  index.seasons.push({ season: s, n: out.length, weeks: Math.max(0, ...out.map(o => o.w)), flagged: out.filter(o => o.x >= C.QUESTION).length });
  console.log(`[grade] ${s}: ${out.length} 4th downs graded (model through ${s - 1})`);
}
if (index.seasons.length) writeFileSync(join(DIR, 'graded.json'), JSON.stringify(index));
