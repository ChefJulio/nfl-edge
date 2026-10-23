// Injury-status agreement check (owner 2026-10-22 audit: "make sure the different areas where we display and compare
// injury/health stuff" agree). Reads a built site's week data the way the pages do (nfledge/static/health.js, the one
// browser reading) and checks that every place a player's status shows tells the same story:
//   - the badge (tag), the card's status pill and the Injuries page's "listed" agree with each other;
//   - his practice letters line up with his team's filed report days (the week's chronology, nfledge/chronology.py);
//   - the chronology itself is sane (states, final vs filed);
//   - ros.json's injury-only chance this week matches the week data, and "back" never names a week he's under even.
// Usage: node tools/health_check.mjs [--site=scratch/site]     (exit 1 on any disagreement)
import { readFileSync, existsSync } from 'node:fs';
import { createRequire } from 'node:module';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..');
const H = createRequire(import.meta.url)(join(ROOT, 'nfledge', 'static', 'health.js'));
const opt = Object.fromEntries(process.argv.slice(2).filter(a => a.startsWith('--')).map(a => a.slice(2).split('=')));
const site = join(ROOT, opt.site || 'scratch/site');
const D = JSON.parse(readFileSync(join(site, 'index.json'), 'utf8'));
const bad = [], note = (pid, P, msg) => bad.push(`${(P && P.name) || pid} (${(P && P.team) || '?'}): ${msg}`);

if (!D.chrono) note('-', null, 'week data has no "chrono" (built before 2026-10-22?)');
const STATES = new Set(['upcoming', 'due', 'overdue', 'filed', 'unfiled']);
for (const [t, c] of Object.entries(D.chrono || {})) {
  const st = c.days.map(x => x[1]);
  if (st.some(s => !STATES.has(s))) note(t, null, `unknown day state in ${st}`);
  if (st.includes('unfiled') && (st.includes('due') || st.includes('overdue'))) note(t, null, `kicked off yet still due / overdue: ${st}`);
  const nf = st.filter(s => s === 'filed').length;
  if (!c.final && c.stage !== Math.min(nf, 2)) note(t, null, `stage ${c.stage} with ${nf} filed days`);
}

let n = 0;
for (const [pid, P] of Object.entries(D.players || {})) {
  n++;
  const t = H.tag(P, pid, D.tags), gd = H.gameday(P), pill = H.pill(P, t, D.week);
  // the badge and the roster-wide map say the same thing
  if (D.tags && P.tag != null && (D.tags[pid] || '') !== (P.tag || '')) note(pid, P, `tag ${P.tag || '-'} vs the tags map ${D.tags[pid] || '-'}`);
  // the pill names the tag (or the game-day ruling), nothing else
  const want = gd === 'INA' ? 'Inactive' : t === 'IR' ? 'Injured reserve' : t === 'SSPD' ? 'Suspended' : t === 'O' ? 'Out'
    : t === 'D' ? 'Doubtful' : t === 'Q' ? 'Questionable' : t === 'PUP' || t === 'NFI' ? t : gd === 'ACT' ? 'Active' : null;
  if ((pill && pill[1]) !== want) note(pid, P, `pill ${pill && pill[1]} but tag ${t || '-'} / game day ${gd || '-'}`);
  // a tag means he's listed (the Injuries page shows every tagged player)
  if (t && !H.listed(P)) note(pid, P, `tag ${t} but not listed`);
  // what spoke vs the words
  if (P.src === '' && P.status && !/ESPN/.test(P.status) && !gd) note(pid, P, `nothing spoke but status "${P.status}"`);
  if (P.src && P.src !== 'tuesday' && !P.status) note(pid, P, `src ${P.src} with an empty status`);
  // his letters line up with his team's filed days (InjuryModel.availability shows one letter per filed day)
  const ch = D.chrono && D.chrono[P.team], d = H.days(P);
  if (ch && P.src === 'report' && d) {
    const filed = ch.days.filter(x => x[1] === 'filed').length;
    if (d.length !== filed && !/\?/.test(d)) note(pid, P, `practice letters ${d} vs ${filed} filed days (${ch.days.map(x => x.join(':')).join(' ')})`);
  }
  if (P.gd && !['INA', 'ACT'].includes(P.gd)) note(pid, P, `game day ${P.gd}`);
  if (P.gd === 'INA' && P.inactive != null && P.inactive < 0.999) note(pid, P, `inactive on game day but ${Math.round(100 * (1 - P.inactive))}% to play`);
}

const rosF = join(site, 'data', 'ros.json');
if (existsSync(rosF)) {
  const R = JSON.parse(readFileSync(rosF, 'utf8'));
  for (const [pid, r] of Object.entries(R.players)) {
    const P = D.players[pid], z = r.w.find(x => x[0] === R.from);
    if (P && z && z[6] != null && P.inactive != null && Math.abs(z[6] - (1 - P.inactive)) > 0.002) note(pid, P, `ros.json injury chance ${z[6]} vs the week's ${(1 - P.inactive).toFixed(3)}`);
    const w = H.back(r);
    if (w) { const e = r.w.find(x => x[0] === w); if (H.rosChance(e) < H.AVAIL.EVEN) note(pid, P || r, `back week ${w} at ${H.rosChance(e)}`); }
  }
} else console.log('(no data/ros.json: skipped the rest-of-season checks)');

console.log(`week ${D.season} ${D.week}: ${n} players, ${Object.keys(D.chrono || {}).length} teams in the chronology`);
bad.slice(0, 60).forEach(b => console.log('  ' + b));
console.log(bad.length ? `${bad.length} disagreement(s)` : 'all agree');
process.exit(bad.length ? 1 : 0);
