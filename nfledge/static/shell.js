// NFL Edge app shell: navigation (parent tabs + sub-tab chips) and hash routing.
// Routes: #players/rankings, #teams/power, #games ... Old one-level hashes (#players, #games, #power, #roles,
// #model) map onto the new routes; #player/<id>, #team/<abbr> and #g-<game> stay with gamecast.js (cards).
// Server-rendered tabs keep their <section id="tab-..."> until their migration phase; tabs that don't exist yet get
// a placeholder section. Loaded on every week page (current, lookahead, archived) from assets/, so nav changes
// reach archived weeks without a rebuild.
// NFLE.load(path): lazy JSON loader with an in-memory cache, paths relative to the site root (the folder holding
// assets/), so it works from index.html and from archived <season>/week-NN.html pages alike.
(() => {
  const NFLE = window.NFLE = window.NFLE || {};
  const root = new URL('..', document.currentScript ? document.currentScript.src : location.href);
  const cache = new Map();
  NFLE.root = root.href;
  NFLE.load = path => {
    if (!cache.has(path)) {
      cache.set(path, fetch(new URL(path, root), { cache: 'no-cache' })
        .then(r => r.ok ? r.json() : Promise.reject(new Error(`${r.status} ${path}`)))
        .catch(e => { cache.delete(path); throw e; }));
    }
    return cache.get(path);
  };
})();
(() => {
  // Four parents (owner, 2026-10-14): Players (incl. transactions = player news) and Teams (incl. playoffs, draft).
  const NAV = [
    { key: 'players', label: 'Players', subs: [['rankings', 'Rankings', 'tab-players'], ['stats', 'Stats'], ['roles', 'Roles', 'tab-roles'], ['injuries', 'Injuries'], ['moves', 'Moves']] },
    { key: 'teams', label: 'Teams', subs: [['power', 'Power', 'tab-power'], ['standings', 'Standings'], ['playoffs', 'Playoffs'], ['stats', 'Stats'], ['draft', 'Draft']] },
    { key: 'games', label: 'Games', subs: [['matchups', 'Matchups', 'tab-games']] },
    { key: 'model', label: 'Model', subs: [['model', 'Model', 'tab-model']] },
  ];
  // Client-rendered tabs: section id -> area module (assets/<area>.js + .css), loaded the first time the tab opens.
  // A module registers NFLE.areas[<area>] = { mount(section) } and renders into its section.
  const AREAS = { 'tab-teams-standings': 'standings', 'tab-teams-stats': 'teamstats', 'tab-players-stats': 'playerstats',
                  'tab-players-injuries': 'injuries', 'tab-players': 'rankings', 'tab-teams-draft': 'draft',
                  'tab-teams-playoffs': 'playoffs' };
  const ver = (document.currentScript && new URL(document.currentScript.src).search) || '';
  const loaded = {};
  const NFLE = window.NFLE = window.NFLE || {};
  NFLE.areas = NFLE.areas || {};
  const mountArea = id => {
    const area = AREAS[id], sec = document.getElementById(id);
    if (!area || !sec || sec.dataset.mounted) return;
    sec.dataset.mounted = '1';
    const go = () => { try { NFLE.areas[area].mount(sec); } catch (e) { sec.insertAdjacentHTML('beforeend', `<p class="muted">Couldn't load this tab (${String(e.message || e)}).</p>`); } };
    if (loaded[area]) { loaded[area].then(go); return; }
    const css = document.createElement('link'); css.rel = 'stylesheet'; css.href = new URL(`assets/${area}.css${ver}`, NFLE.root).href;
    document.head.appendChild(css);
    loaded[area] = new Promise((ok, bad) => {
      const js = document.createElement('script'); js.src = new URL(`assets/${area}.js${ver}`, NFLE.root).href;
      js.onload = ok; js.onerror = () => bad(new Error(`assets/${area}.js`)); document.head.appendChild(js);
    });
    loaded[area].then(go, e => sec.insertAdjacentHTML('beforeend', `<p class="muted">Couldn't load this tab (${e.message}).</p>`));
  };
  const OLD = { players: 'players/rankings', roles: 'players/roles', power: 'teams/power', games: 'games', model: 'model',
               playoffs: 'teams/playoffs', draft: 'teams/draft', transactions: 'players/moves' };
  const CARD = /^g-/;  // old matchup-tile links: gamecast.js turns them into gamecast links
  const PAGE = /^(player|team)\/(.+)$/;  // player / team pages (rendered by gamecast.js into #pcOv in the page section)
  const nav = document.querySelector('nav.tabs');
  const main = document.querySelector('main .wrap');
  if (!nav || !main) return;
  const parent = k => NAV.find(p => p.key === k) || NAV[0];
  const sectionId = (p, s) => s[2] || `tab-${p.key}-${s[0]}`;
  // The player / team page: a section holding the card renderer's container (#pcOv, found by gamecast.js) under a
  // breadcrumb trail back to where you came from.
  main.insertAdjacentHTML('beforeend', `<section id="tab-page"><nav class="crumbs" aria-label="Breadcrumb"></nav>
    <div class="pc-ov pc-page" id="pcOv"><div class="pc"><div class="pc-body"></div></div></div></section>`);
  NFLE.pageMode = true;
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
  // Phones: a bottom tab bar (owner's choice, 2026-10-14). Five slots: the four busiest parents + More (a sheet with
  // the rest); the sub-tab chips stay in the top bar. The top strip (parent tabs in the top bar, short labels) is
  // kept for a possible future setting: set NAV_MODE = 'top'. Desktop always uses the top strip.
  const NAV_MODE = 'bottom';
  const ICON = {
    players: '<circle cx="12" cy="8" r="3.6"/><path d="M5 20c.8-3.6 3.6-5.6 7-5.6s6.2 2 7 5.6"/>',
    teams: '<path d="M12 3l7 3v5c0 4.4-3 8-7 10-4-2-7-5.6-7-10V6z"/>',
    games: '<rect x="3.5" y="5" width="17" height="15" rx="2.5"/><path d="M3.5 10h17M8 3v4M16 3v4"/>',
    model: '<path d="M4 19V5M4 19h16M8 15l3-4 3 2 5-6"/>',
    more: '<circle cx="5.5" cy="12" r="1.4"/><circle cx="12" cy="12" r="1.4"/><circle cx="18.5" cy="12" r="1.4"/>',
  };
  const svg = k => `<svg viewBox="0 0 24 24" width="22" height="22" aria-hidden="true">${ICON[k]}</svg>`;
  const navMode = NAV_MODE;
  const BOTTOM = NAV.map(p => p.key);  // all four parents fit: no More sheet
  let bot = null;
  if (navMode === 'bottom') {
    document.documentElement.classList.add('nav-bottom');
    bot = document.createElement('div');
    bot.className = 'botbar';
    const extra = NAV.filter(p => !BOTTOM.includes(p.key));  // parents beyond the bar go in a More sheet (none today)
    bot.innerHTML = `<nav class="bb-row">${BOTTOM.map(k => `<button type="button" data-par="${k}">${svg(k)}<span>${parent(k).label}</span></button>`).join('')}
      ${extra.length ? `<button type="button" data-more>${svg('more')}<span>More</span></button>` : ''}</nav>
      ${extra.length ? `<div class="bb-sheet" hidden>${extra.map(p => `<button type="button" data-par="${p.key}">${p.label}</button>`).join('')}</div>` : ''}`;
    document.body.appendChild(bot);
    // Phones: the sub-tab chips ride in the bottom bar too (all navigation in thumb reach; owner, 2026-10-14) and the
    // top bar is hidden. Wider screens keep everything in the top bar. --bbh = the bar's height, for page padding.
    const phone = matchMedia('(max-width: 640px)');
    const place = () => {
      if (phone.matches) bot.insertBefore(subBar, bot.firstChild); else nav.appendChild(subBar);
      document.documentElement.style.setProperty('--bbh', `${phone.matches ? bot.offsetHeight : 0}px`);
    };
    phone.addEventListener('change', place);
    NFLE.placeBar = place;
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
  let lastRoute = null;  // the list route a page was opened from (breadcrumb), with its scroll position
  const scrolls = {};
  let onPage = false;
  const showPage = (kind, id) => {
    const from = lastRoute || { p: NAV[0], s: NAV[0].subs[0] };
    main.querySelectorAll(':scope > section').forEach(x => x.classList.toggle('on', x.id === 'tab-page'));
    nav.querySelectorAll('[data-par]').forEach(b => b.classList.toggle('on', b.dataset.par === from.p.key));
    if (bot) bot.querySelectorAll('.bb-row [data-par]').forEach(b => b.classList.toggle('on', b.dataset.par === from.p.key));
    subBar.hidden = true; subBar.innerHTML = '';
    if (NFLE.placeBar) NFLE.placeBar();
    const crumbs = document.querySelector('#tab-page .crumbs');
    const fromHash = from.p.subs.length < 2 ? from.p.key : `${from.p.key}/${from.s[0]}`;
    crumbs.innerHTML = `<button type="button" class="cr-back" aria-label="Back">&lsaquo;</button>
      <a href="#${fromHash}">${from.p.label}</a>${from.p.subs.length > 1 ? `<span>&rsaquo;</span><a href="#${fromHash}">${from.s[1]}</a>` : ''}
      <span>&rsaquo;</span><b class="cr-here">${kind === 'team' ? id : '&hellip;'}</b>`;
    crumbs.querySelector('.cr-back').onclick = () => { if (history.length > 1 && lastRoute) history.back(); else location.hash = fromHash; };
    window.scrollTo({ top: 0 });
    const fresh = !onPage;  // opened from a list (not page-to-page): the card starts on this page's week
    const render = () => {
      const fn = kind === 'player' ? NFLE.showPlayer : NFLE.showTeam;
      NFLE.freshPage = fresh;
      if (fn) fn(decodeURIComponent(id));
      NFLE.freshPage = false;
      // the name for the last crumb, once the card has rendered it
      setTimeout(() => { const h = document.getElementById('pcName'); const here = crumbs.querySelector('.cr-here'); if (h && here) here.textContent = h.textContent.replace(/^#\d+\s*/, ''); }, 60);
    };
    render();
    onPage = true;
    document.dispatchEvent(new CustomEvent('nfle-route', { detail: { parent: from.p.key, sub: 'page', section: 'tab-page' } }));
  };
  const show = (r, push) => {
    if (lastRoute && lastRoute !== r) scrolls[sectionId(lastRoute.p, lastRoute.s)] = window.scrollY;
    nav.querySelectorAll('[data-par]').forEach(b => b.classList.toggle('on', b.dataset.par === r.p.key));
    if (bot) {
      bot.querySelectorAll('.bb-row [data-par]').forEach(b => b.classList.toggle('on', b.dataset.par === r.p.key));
      const more = bot.querySelector('[data-more]'), sheet = bot.querySelector('.bb-sheet');
      if (more) more.classList.toggle('on', !BOTTOM.includes(r.p.key));
      if (sheet) { sheet.querySelectorAll('[data-par]').forEach(b => b.classList.toggle('on', b.dataset.par === r.p.key)); sheet.hidden = true; }
    }
    subBar.hidden = r.p.subs.length < 2;
    subBar.innerHTML = r.p.subs.length < 2 ? '' : r.p.subs.map(s => `<button type="button" class="chip${s === r.s ? ' on' : ''}" data-sub="${s[0]}">${s[1]}</button>`).join('');
    const id = sectionId(r.p, r.s);
    main.querySelectorAll(':scope > section').forEach(x => x.classList.toggle('on', x.id === id));
    const route = r.p.subs.length < 2 ? r.p.key : `${r.p.key}/${r.s[0]}`;
    try { localStorage.setItem('nfledge-tab', route); } catch (e) { /* private mode */ }
    if (push && location.hash.slice(1) !== route) { try { history.replaceState(null, '', '#' + route); } catch (e) { /* file:// */ } }
    if (NFLE.placeBar) NFLE.placeBar();  // the chip row comes and goes with the parent: re-measure the bar
    lastRoute = r; onPage = false;
    mountArea(id);
    if (scrolls[id] != null) requestAnimationFrame(() => window.scrollTo({ top: scrolls[id] }));  // back from a page
    document.dispatchEvent(new CustomEvent('nfle-route', { detail: { parent: r.p.key, sub: r.s[0], section: id } }));
  };
  const onNav = e => {
    const pb = e.target.closest('[data-par]'), sb = e.target.closest('[data-sub]');
    if (bot && e.target.closest('[data-more]')) { const sh = bot.querySelector('.bb-sheet'); sh.hidden = !sh.hidden; return; }
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
    document.addEventListener('click', e => { const sh = bot.querySelector('.bb-sheet'); if (sh && !bot.contains(e.target)) sh.hidden = true; });
  }
  const route = (h, push) => {
    const m = (h || '').replace(/^#/, '').match(PAGE);
    if (m) { if (lastRoute) scrolls[sectionId(lastRoute.p, lastRoute.s)] = window.scrollY; showPage(m[1], m[2]); return true; }
    const r = parse(h); if (r) { show(r, push); return true; }
    return false;
  };
  window.addEventListener('hashchange', () => route(location.hash, false));
  let saved = null; try { saved = localStorage.getItem('nfledge-tab'); } catch (e) { /* ignore */ }
  // A page link opened directly: its breadcrumb points at the tab you last used.
  if (PAGE.test(location.hash.slice(1))) { lastRoute = parse(saved) || parse('players'); route(location.hash, false); }
  else show(parse(location.hash) || parse(saved) || parse('players'), !CARD.test(location.hash.slice(1)));
  window.NFLE_SHELL = { go: h => { const r = parse(h); if (r) show(r, true); } };
})();
