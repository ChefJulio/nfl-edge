// Games > Calc from the command line (static/calc_engine.js), for checks and for assistants.
//   node tools/calc_cli.mjs --check [--data=scratch/site]        the trees give the Python model's numbers
//   node tools/calc_cli.mjs '<state JSON>' [--data=...]          win probability and every decision for a state
//      state: {"diff":-3,"qtr":4,"clock":"2:00","down":4,"togo":2,"yl":40,"to":2,"oppTo":3,"line":0,"home":1}
//   node tools/calc_cli.mjs --demo                               a few classic spots
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..');
const E = createRequire(import.meta.url)(join(ROOT, 'nfledge', 'static', 'calc_engine.js'));
const args = process.argv.slice(2), opt = Object.fromEntries(args.filter(a => a.startsWith('--')).map(a => a.slice(2).split('=')));
const M = JSON.parse(readFileSync(join(ROOT, opt.data || 'scratch/site', 'data', 'calc', 'model.json'), 'utf8'));
const C = E.createCalc(M);
const pc = v => `${(100 * v).toFixed(1)}%`;

const state = o => ({ diff: 0, down: 1, togo: 10, yl: 75, to: 3, oppTo: 3, line: 0, home: 1, rec2h: 0, ...o, sec: o.sec != null ? o.sec : E.gameSec(o.qtr || 1, o.clock || '15:00') });
const show = (lab, o) => {
  const s = state(o), f = C.fourth(s), t = C.timeout(s, 'offense');
  const opts = Object.entries(f).map(([k, v]) => `${k} ${pc(v.wp)}${v.p != null ? ` (p ${pc(v.p)})` : ''}`).join(' | ');
  console.log(`${lab}\n  now ${pc(C.wp(s))}  4th: ${opts}\n  offense timeout: call ${pc(t.call.wp)} vs let ${t.run.seconds}s run ${pc(t.run.wp)}`);
};

if ('check' in opt) {
  const worst = E.selfCheck(M);
  console.log(`[calc] self-check on ${M.check.length} rows: worst difference ${worst.toExponential(2)}`);
  process.exit(worst < 1e-6 ? 0 : 1);
} else if ('demo' in opt) {
  show('4th & 1 at midfield, tied, 3rd quarter 8:00', { qtr: 3, clock: '8:00', down: 4, togo: 1, yl: 50 });
  show('4th & 4 at opp 35, down 4, 4th quarter 5:00', { diff: -4, qtr: 4, clock: '5:00', down: 4, togo: 4, yl: 35 });
  show('4th & 10 at own 30, up 7, 4th quarter 3:00', { diff: 7, qtr: 4, clock: '3:00', down: 4, togo: 10, yl: 70 });
  show('4th & goal at 2, down 3, 4th quarter 0:20', { diff: -3, qtr: 4, clock: '0:20', down: 4, togo: 2, yl: 2, to: 1 });
  const t = C.tries(state({ diff: -2, qtr: 4, clock: '1:30' }));
  console.log(`after a TD, down 2, 1:30 left: XP ${pc(t.xp.wp)} vs two ${pc(t.two.wp)}`);
  const o = C.onside(state({ diff: -8, qtr: 4, clock: '2:00', to: 3 }));
  console.log(`kicking off down 8, 2:00 left: onside ${pc(o.onside.wp)} vs kick ${pc(o.kick.wp)}`);
} else {
  const s = state(JSON.parse(args.find(a => !a.startsWith('--')) || '{}'));
  console.log(JSON.stringify({ wp: C.wp(s), fourth: C.fourth(s), timeout_offense: C.timeout(s, 'offense'), timeout_defense: C.timeout(s, 'defense') }, null, 1));
}
