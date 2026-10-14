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
    { key: 'transactions', label: 'Transactions', subs: [['transactions', 'Transactions']] },
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
  nav.innerHTML = `<div class="wrap nav-par" role="tablist">${NAV.map(p => `<button type="button" role="tab" data-par="${p.key}">${p.label}</button>`).join('')}</div>
    <div class="wrap nav-sub" hidden></div>`;
  const subBar = nav.querySelector('.nav-sub');
  // Phones: the parent strip scrolls; its right edge fades (shell.css) until you reach the end.
  const par = nav.querySelector('.nav-par');
  const atEnd = () => par.classList.toggle('at-end', par.scrollLeft + par.clientWidth >= par.scrollWidth - 2);
  par.addEventListener('scroll', atEnd, { passive: true });
  window.addEventListener('resize', atEnd);
  requestAnimationFrame(atEnd);
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
    subBar.hidden = r.p.subs.length < 2;
    subBar.innerHTML = r.p.subs.length < 2 ? '' : r.p.subs.map(s => `<button type="button" class="chip${s === r.s ? ' on' : ''}" data-sub="${s[0]}">${s[1]}</button>`).join('');
    const id = sectionId(r.p, r.s);
    main.querySelectorAll(':scope > section').forEach(x => x.classList.toggle('on', x.id === id));
    const route = r.p.subs.length < 2 ? r.p.key : `${r.p.key}/${r.s[0]}`;
    try { localStorage.setItem('nfledge-tab', route); } catch (e) { /* private mode */ }
    if (push && location.hash.slice(1) !== route) { try { history.replaceState(null, '', '#' + route); } catch (e) { /* file:// */ } }
    document.dispatchEvent(new CustomEvent('nfle-route', { detail: { parent: r.p.key, sub: r.s[0], section: id } }));
  };
  nav.addEventListener('click', e => {
    const pb = e.target.closest('[data-par]'), sb = e.target.closest('[data-sub]');
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
  });
  window.addEventListener('hashchange', () => { const r = parse(location.hash); if (r) show(r, false); });
  let saved = null; try { saved = localStorage.getItem('nfledge-tab'); } catch (e) { /* ignore */ }
  show(parse(location.hash) || parse(saved) || parse('players'), !CARD.test(location.hash.slice(1)));
  window.NFLE_SHELL = { go: h => { const r = parse(h); if (r) show(r, true); } };
})();
