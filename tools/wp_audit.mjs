// (CP) scores the audit's 2019-25 snaps with the engine's wp() and a model fit through 2018 (tools/wp_audit.py).
import { readFileSync, writeFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..');
const E = createRequire(import.meta.url)(join(ROOT, 'nfledge', 'static', 'calc_engine.js'));
const DIR = join(ROOT, 'scratch', 'calc_val');
const C = E.createCalc(JSON.parse(readFileSync(join(DIR, 'through_2018.json'), 'utf8')));
const rows = JSON.parse(readFileSync(join(DIR, 'audit_rows.json'), 'utf8'));
const out = rows.map(r => ({ game_id: r.game_id, season: r.season, won: r.won, diff: r.diff, sec: r.sec, to: r.to, oppTo: r.oppTo, tags: r.tags,
  wp: C.wp({ diff: r.diff, sec: r.sec, down: r.down, togo: r.togo, yl: r.yl, to: r.to, oppTo: r.oppTo, line: r.line || 0,
    total: r.total || 45, home: r.home, rec2h: r.rec2h }) }));
writeFileSync(join(DIR, 'audit_scored.json'), JSON.stringify(out));
console.log(`[cp] scored ${out.length} snaps`);
