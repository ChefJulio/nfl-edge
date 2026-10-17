// Teams > All teams (owner 2026-10-17): every team as a tile, grouped by conference and division (East, North, South,
// West), each division ordered by record then our Power rank. Tap a tile for the team card. Uses the week data only
// (D.teams: name, logo, colors, division; D.power: record, rank).
(() => {
  const NFLE = window.NFLE, esc = NFLE.esc;
  const DIVS = ['East', 'North', 'South', 'West'];
  const winPct = rec => { const [w, l, t] = String(rec || '0-0').split('-').map(Number); const g = w + l + (t || 0); return g ? (w + 0.5 * (t || 0)) / g : 0; };
  const tile = (t, i, p) => `<button type="button" class="tg-tile tm-open" data-tm="${esc(t)}" style="--tc:${esc(i.color || '#555')};--tc2:${esc(i.color2 || i.color || '#555')}">
      <span class="tg-logo" style="background:${esc(i.logo_bg || '#333')}"><img src="${esc(NFLE.fmt.logoSrc(i.logo, 112))}" alt="" width="40" height="40" loading="lazy"></span>
      <span class="tg-nm">${esc(i.nick || t)}</span>
      <span class="tg-meta"><b>${esc(p.record || '0-0')}</b>${p.rank ? `<span class="tg-rk" title="Our Power rank">#${p.rank}</span>` : ''}</span></button>`;
  NFLE.areas.teamgrid = {
    mount(sec) {
      sec.classList.remove('soon');
      sec.innerHTML = '<div class="sec-head"><div><h2>All teams</h2><p>Every team by conference and division. Tap one for its page.</p></div></div><div class="tg-body skel-zone"></div>';
      NFLE.week().then(D => {
        const teams = (D && D.teams) || {}, power = Object.fromEntries(((D && D.power) || []).map(r => [r.team, r]));
        const conf = c => `<div class="tg-conf"><h3 class="tg-ch">${c}</h3>${DIVS.map(dv => {
          const ts = Object.keys(teams).filter(t => teams[t].division === `${c} ${dv}`)
            .sort((a, b) => winPct((power[b] || {}).record) - winPct((power[a] || {}).record) || ((power[a] || {}).rank || 99) - ((power[b] || {}).rank || 99));
          return ts.length ? `<div class="tg-div"><h4 class="tg-dh">${c} ${dv}</h4><div class="tg-grid">${ts.map(t => tile(t, teams[t], power[t] || {})).join('')}</div></div>` : '';
        }).join('')}</div>`;
        const body = sec.querySelector('.tg-body');
        body.classList.remove('skel-zone');
        body.innerHTML = Object.keys(teams).length ? `<div class="tg-confs">${conf('AFC')}${conf('NFC')}</div>` : '<p class="muted">Team data is not available on this page.</p>';
      });
    },
  };
})();
