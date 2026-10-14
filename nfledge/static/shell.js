// NFL Edge app shell: navigation (parent tabs + sub-tab chips) and hash routing.
// Routes: #players/rankings, #teams/power, #games ... Old one-level hashes (#players, #games, #power, #roles,
// #model) map onto the new routes; #player/<id>, #team/<abbr> and #g-<game> stay with gamecast.js (cards).
// Server-rendered tabs keep their <section id="tab-..."> until their migration phase; tabs that don't exist yet get
// a placeholder section. Loaded on every week page (current, lookahead, archived) from assets/, so nav changes
// reach archived weeks without a rebuild.
(() => {
  const NAV = [
    { key: 'players', label: 'Players', subs: [['rankings', 'Rankings', 'tab-players'], ['stats', 'Stats'], ['roles', 'Role changes', 'tab-roles'], ['injuries', 'Injuries']] },
    { key: 'teams', label: 'Teams', subs: [['power', 'Power', 'tab-power'], ['stats', 'Stats'], ['standings', 'Standings']] },
    { key: 'games', label: 'Games', subs: [['matchups', 'Matchups', 'tab-games']] },
    { key: 'playoffs', label: 'Playoffs', subs: [['playoffs', 'Playoffs']] },
    { key: 'draft', label: 'Draft', subs: [['draft', 'Draft']] },
    { key: 'transactions', label: 'Transactions', short: 'Moves', subs: [['transactions', 'Transactions']] },
    { key: 'model', label: 'Model', subs: [['model', 'Model', 'tab-model']] },
  ];
  const OLD = { players: 'players/rankings', roles: 'players/roles', power: 'teams/power', games: 'games', model: 'model' };
  const CARD = /^(player|team)\/|^g-/;  // card / old tile deep links: gamecast.js owns these
  const nav = document.querySelector('nav.tabs');
  const main = document.querySelector('main .wrap');
  if (!nav || !main) return;
  const parent = k => NAV.find(p => p.key === k) || NAV[0];
  const sectionId = (p, s) => s[2] || `tab-${p.key}-${s[0]}`;
  // Placeholder sections for tabs not built yet (one per sub-tab), so routing is uniform.
  NAV.forEach(p => p.subs.forEach(s => {
    if (!document.getElementById(sectionId(p, s))) {
      main.insertAdjacentHTML('beforeend', `<section id="${sectionId(p, s)}" class="soon"><div class="sec-head"><div><h2>${s[1] === p.label ? p.label : `${p.label} &middot; ${s[1]}`}</h2><p>Coming soon.</p></div></div></section>`);
    }
  }));
  // Phones show the short label where one exists, so all seven parent tabs fit on one line (owner's pick).
  nav.innerHTML = `<div class="wrap nav-par" role="tablist">${NAV.map(p => `<button type="button" role="tab" data-par="${p.key}">${p.short
      ? `<span class="lbl-long">${p.label}</span><span class="lbl-short">${p.short}</span>` : p.label}</button>`).join('')}</div>
    <div class="wrap nav-sub" hidden></div>`;
  // Optional bottom tab bar on phones (owner trying it out): ?nav=bottom turns it on, ?nav=top off; remembered.
  // Five slots: the four busiest parents + More (a sheet with the rest). Sub-tab chips stay in the top bar.
  const ICON = {
    players: '<circle cx="12" cy="8" r="3.6"/><path d="M5 20c.8-3.6 3.6-5.6 7-5.6s6.2 2 7 5.6"/>',
    teams: '<path d="M12 3l7 3v5c0 4.4-3 8-7 10-4-2-7-5.6-7-10V6z"/>',
    games: '<rect x="3.5" y="5" width="17" height="15" rx="2.5"/><path d="M3.5 10h17M8 3v4M16 3v4"/>',
    playoffs: '<path d="M8 4h8v5a4 4 0 01-8 0zM8 6H5a3 3 0 003 4M16 6h3a3 3 0 01-3 4M12 13v4M8.5 20h7"/>',
    more: '<circle cx="5.5" cy="12" r="1.4"/><circle cx="12" cy="12" r="1.4"/><circle cx="18.5" cy="12" r="1.4"/>',
  };
  const svg = k => `<svg viewBox="0 0 24 24" width="22" height="22" aria-hidden="true">${ICON[k]}</svg>`;
  const qp = new URLSearchParams(location.search).get('nav');
  try { if (qp === 'bottom' || qp === 'top') localStorage.setItem('nfledge-nav', qp); } catch (e) { /* ignore */ }
  let navMode = qp || ''; try { navMode = navMode || localStorage.getItem('nfledge-nav') || 'top'; } catch (e) { navMode = 'top'; }
  const BOTTOM = ['players', 'teams', 'games', 'playoffs'];
  let bot = null;
  if (navMode === 'bottom') {
    document.documentElement.classList.add('nav-bottom');
    bot = document.createElement('div');
    bot.className = 'botbar';
    bot.innerHTML = `<nav class="bb-row">${BOTTOM.map(k => `<button type="button" data-par="${k}">${svg(k)}<span>${parent(k).label}</span></button>`).join('')}
      <button type="button" data-more>${svg('more')}<span>More</span></button></nav>
      <div class="bb-sheet" hidden>${NAV.filter(p => !BOTTOM.includes(p.key)).map(p => `<button type="button" data-par="${p.key}">${p.label}</button>`).join('')}</div>`;
    document.body.appendChild(bot);
  }
  const subBar = nav.querySelector('.nav-sub');
  const parse = h => {
    h = (h || '').replace(/^#/, '');
    if (!h || CARD.test(h)) return null;
    if (OLD[h]) h = OLD[h];
    const [pk, sk] = h.split('/');
    const p = parent(pk);
    const s = p.subs.find(x => x[0] === sk) || p.subs[0];
    return { p, s };
  };
  const show = (r, push) => {
    nav.querySelectorAll('[data-par]').forEach(b => b.classList.toggle('on', b.dataset.par === r.p.key));
    if (bot) {
      bot.querySelectorAll('.bb-row [data-par]').forEach(b => b.classList.toggle('on', b.dataset.par === r.p.key));
      bot.querySelector('[data-more]').classList.toggle('on', !BOTTOM.includes(r.p.key));
      bot.querySelectorAll('.bb-sheet [data-par]').forEach(b => b.classList.toggle('on', b.dataset.par === r.p.key));
      bot.querySelector('.bb-sheet').hidden = true;
    }
    subBar.hidden = r.p.subs.length < 2;
    subBar.innerHTML = r.p.subs.length < 2 ? '' : r.p.subs.map(s => `<button type="button" class="chip${s === r.s ? ' on' : ''}" data-sub="${s[0]}">${s[1]}</button>`).join('');
    const id = sectionId(r.p, r.s);
    main.querySelectorAll(':scope > section').forEach(x => x.classList.toggle('on', x.id === id));
    const route = r.p.subs.length < 2 ? r.p.key : `${r.p.key}/${r.s[0]}`;
    try { localStorage.setItem('nfledge-tab', route); } catch (e) { /* private mode */ }
    if (push && location.hash.slice(1) !== route) { try { history.replaceState(null, '', '#' + route); } catch (e) { /* file:// */ } }
    document.dispatchEvent(new CustomEvent('nfle-route', { detail: { parent: r.p.key, sub: r.s[0], section: id } }));
  };
  const onNav = e => {
    const pb = e.target.closest('[data-par]'), sb = e.target.closest('[data-sub]');
    if (e.target.closest('[data-more]')) { const sh = bot.querySelector('.bb-sheet'); sh.hidden = !sh.hidden; return; }
    if (pb) {  // a parent tab reopens the sub-tab you last used there
      const p = parent(pb.dataset.par);
      let last = null; try { last = localStorage.getItem(`nfledge-sub-${p.key}`); } catch (e) { /* ignore */ }
      show({ p, s: p.subs.find(x => x[0] === last) || p.subs[0] }, true);
      window.scrollTo({ top: 0 });
    } else if (sb) {
      const p = parent(nav.querySelector('[data-par].on').dataset.par);
      const s = p.subs.find(x => x[0] === sb.dataset.sub);
      try { localStorage.setItem(`nfledge-sub-${p.key}`, s[0]); } catch (e) { /* ignore */ }
      show({ p, s }, true);
    }
  };
  nav.addEventListener('click', onNav);
  if (bot) {
    bot.addEventListener('click', onNav);
    document.addEventListener('click', e => { if (!bot.contains(e.target)) bot.querySelector('.bb-sheet').hidden = true; });
  }
  window.addEventListener('hashchange', () => { const r = parse(location.hash); if (r) show(r, false); });
  let saved = null; try { saved = localStorage.getItem('nfledge-tab'); } catch (e) { /* ignore */ }
  show(parse(location.hash) || parse(saved) || parse('players'), !CARD.test(location.hash.slice(1)));
  window.NFLE_SHELL = { go: h => { const r = parse(h); if (r) show(r, true); } };
})();
