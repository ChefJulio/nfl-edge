// Teams > All teams (owner 2026-10-17): every team as a tile, grouped by conference and division (East, North, South,
// West), each division ordered by record then our Power rank. Tap a tile for the team card. Uses the week data only
// (D.teams: name, logo, colors, division; D.power: record, rank). The name is the team's wordmark (white, location line
// trimmed; tools/wordmarks_build.py), the typed nickname if it doesn't load.
(() => {
  const NFLE = window.NFLE, esc = NFLE.esc;
  const DIVS = ['East', 'North', 'South', 'West'];
  // the tile's color: the team's official primary (PRIMARY below), dark ones lifted (owner 2026-10-17: "packers green and bears grey ... look a little muted"): keep the hue,
  // raise lightness and saturation of dark primaries; bright ones are untouched
  const vivid = hex => {
    const m = /^#?([0-9a-f]{6})$/i.exec(hex || ''); if (!m) return hex;
    const n = parseInt(m[1], 16), r = (n >> 16) / 255, g = (n >> 8 & 255) / 255, b = (n & 255) / 255;
    const mx = Math.max(r, g, b), mn = Math.min(r, g, b), l = (mx + mn) / 2, d = mx - mn;
    let h = 0, s = d ? d / (1 - Math.abs(2 * l - 1)) : 0;
    if (d) h = mx === r ? ((g - b) / d) % 6 : mx === g ? (b - r) / d + 2 : (r - g) / d + 4;
    if (l >= 0.3) return hex;
    const L = 0.34, S = d < 0.04 ? s : Math.max(s, 0.5);  // near-grey colors (Raiders black) stay grey
    const c = (1 - Math.abs(2 * L - 1)) * S, x = c * (1 - Math.abs((h % 2 + 2) % 2 - 1)), o = L - c / 2;
    const [R, G, B] = h < 1 ? [c, x, 0] : h < 2 ? [x, c, 0] : h < 3 ? [0, c, x] : h < 4 ? [0, x, c] : h < 5 ? [x, 0, c] : [c, 0, x];
    return '#' + [R, G, B].map(v => Math.round((v + o) * 255).toString(16).padStart(2, '0')).join('');
  };
  // each team's official primary color (nflverse load_teams().team_color, 2026): the week data's "color" is greyed for
  // table rows and logo_bg is picked to frame the logo (the Bills' red circle), so neither is the team's main color
  const PRIMARY = {"ARI":"#97233F","ATL":"#A71930","BAL":"#241773","BUF":"#00338D","CAR":"#0085CA","CHI":"#0B162A","CIN":"#FB4F14","CLE":"#FF3C00","DAL":"#002244","DEN":"#002244","DET":"#0076B6","GB":"#203731","HOU":"#03202F","IND":"#002C5F","JAX":"#006778","KC":"#E31837","LA":"#003594","LAC":"#007BC7","LV":"#000000","MIA":"#008E97","MIN":"#4F2683","NE":"#002244","NO":"#D3BC8D","NYG":"#0B2265","NYJ":"#003F2D","PHI":"#004C54","PIT":"#000000","SEA":"#002244","SF":"#AA0000","TB":"#A71930","TEN":"#4495D2","WAS":"#5A1414"};
  const winPct = rec => { const [w, l, t] = String(rec || '0-0').split('-').map(Number); const g = w + l + (t || 0); return g ? (w + 0.5 * (t || 0)) / g : 0; };
  // the matchup tiles' look (owner 2026-10-17: "the logo blown up within the background"): the logo large, bleeding
  // off the right edge and fading toward the text; team-color gradient, darker under the text
  const tile = (t, i, p) => `<button type="button" class="tg-tile tm-open" data-tm="${esc(t)}" style="--tc:${esc(vivid(PRIMARY[t] || i.logo_bg || i.color) || '#555')};--tc2:${esc(i.color2 || i.color || '#555')}">
      <img class="tg-lg" src="${esc(NFLE.fmt.logoSrc(i.logo, 224))}" alt="" loading="lazy">
      <span class="tg-txt"><span class="tg-nm"><img class="tg-wm" src="${esc(NFLE.root || '')}assets/wordmarks/${esc(t)}.png" alt="${esc(i.nick || t)}"
        onerror="this.parentNode.textContent = this.alt"></span>
        <span class="tg-meta"><b>${esc(p.record || '0-0')}</b>${p.rank ? `<span class="tg-rk" title="Our Power rank">Power #${p.rank}</span>` : ''}</span></span></button>`;
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
