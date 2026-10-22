#!/usr/bin/env node
// Trends from the command line, for scripts and LLMs (owner 2026-10-22: "making the tool usable for llms"). Runs the
// page's own engine (nfledge/static/trends_engine.js) over the same data files, so an answer here is what the page shows.
//
//   node tools/trends_cli.mjs '<query JSON>' [--data=<site dir or URL>] [--limit=50] [--csv]
//   node tools/trends_cli.mjs --schema [--data=...]        measures, filters (values / ranges), breakdowns, seasons
//   node tools/trends_cli.mjs --find="Aaron Jones" [--from=2024 --to=2025]   player / coach ids
//
// The query is the page's Q (see --schema "query"): {"fam":"rush","met":"ypc","who":"P:Aaron Jones","f":{"vs":"GB"},
// "from":2024,"to":2025}. Conveniences: "who":"P:<name>" and player filter values ("qb", "with", "wo", "onw", "onx")
// given as a name are resolved to ids (an ambiguous name is an error listing the candidates). Output: JSON with the
// question in words, the league line, notes on seasons left out, the rows, and a link that opens the query on the site.
// --data defaults to the live site; a built local site (python tools/trends_build.py --site=DIR) is faster.
import { createRequire } from 'node:module';
import { readFileSync } from 'node:fs';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

const require = createRequire(import.meta.url);
const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..');
const createEngine = require(join(ROOT, 'nfledge', 'static', 'trends_engine.js'));
const SITE = 'https://chefjulio.github.io/nfl-edge/';

const args = process.argv.slice(2);
const opt = Object.fromEntries(args.filter(a => a.startsWith('--')).map(a => { const [k, ...v] = a.slice(2).split('='); return [k, v.length ? v.join('=') : true]; }));
const pos = args.filter(a => !a.startsWith('--'));
const data = opt.data || SITE;
const load = /^https?:/.test(data)
  ? p => fetch(new URL(p, data.endsWith('/') ? data : `${data}/`)).then(r => { if (!r.ok) throw new Error(`${p}: HTTP ${r.status}`); return r.json(); })
  : p => Promise.resolve().then(() => JSON.parse(readFileSync(join(data, p), 'utf8')));
const E = createEngine(load);
const out = x => process.stdout.write(`${typeof x === 'string' ? x : JSON.stringify(x, null, 1)}\n`);
const fail = msg => { process.stderr.write(`${msg}\n`); process.exit(1); };

// a name -> [label, value, name] candidates among the seasons in range (exact name first), for --find
const findPeople = (Q, name) => E.people(Q).then(list => {
  const t = name.toLowerCase().trim(), exact = list.filter(o => o[2].toLowerCase() === t);
  return exact.length ? exact : list.filter(o => o[2].toLowerCase().includes(t));
});
const resolve = async Q => {
  const { problems } = await E.resolveNames(Q);
  if (problems.length) fail(problems.map(p => (p.candidates.length ? `"${p.name}" matches several players: ${p.candidates.map(c => `${c.label} = ${c.who}`).join('; ')}` : `no player "${p.name}" in ${Q.from}-${Q.to}`)).join('\n'));
  return Q;
};
const link = Q => `${SITE}?q=${encodeURIComponent(JSON.stringify(Q))}#players/trends`;
const csv = rows => {
  if (!rows.length) return '';
  const head = Object.keys(rows[0]), cell = v => { const s = v == null ? '' : String(v); return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s; };
  return [head, ...rows.map(r => head.map(h => r[h]))].map(r => r.map(cell).join(',')).join('\n');
};

try {
  await E.init();
  if (opt.schema) { out(E.schema()); process.exit(0); }
  if (opt.find) {
    const Q = E.normalize({ from: opt.from ? +opt.from : undefined, to: opt.to ? +opt.to : undefined });
    out((await findPeople(Q, String(opt.find))).slice(0, 25).map(o => ({ label: o[0], who: o[1], name: o[2] })));
    process.exit(0);
  }
  if (!pos.length) fail('usage: node tools/trends_cli.mjs \'<query JSON>\' | --schema | --find=<name>  (see the header of this file)');
  let q;
  try { q = JSON.parse(pos[0]); } catch (e) { fail(`query is not JSON: ${e.message}`); }
  const Q = await resolve(E.normalize(q));
  const a = await E.answer(Q, { limit: opt.limit ? +opt.limit : 50 });
  a.link = link(a.query);
  out(opt.csv ? csv(a.rows) : a);
} catch (e) { fail(`error: ${e.message}`); }
