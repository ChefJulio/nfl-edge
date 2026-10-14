// Model: how every number on the site is made. The text is MODEL.md with this build's live values, turned into HTML
// by the current week's build (data/model.json at the site root: html + toc + stale flag + the favorites track
// record), so every week's page - archived and lookahead too - shows the same, current description.
(() => {
  const NFLE = window.NFLE, esc = NFLE.esc;
  const track = t => !t ? '' : `<h2 id="track-record">How often favorites win</h2>
    <p>Market chances, ${esc(t.since)}&ndash;${esc(t.season)}. A well-calibrated forecast's favorites win about as often as their chance says; each season is scored with chances fit only on the seasons before it.</p>
    <table class="trk"><thead><tr><th>Favorite's chance</th><th class="num">Games</th><th class="num">Expected</th><th class="num">Won</th><th class="num">${esc(t.season)}</th></tr></thead>
    <tbody>${t.rows.map(r => `<tr${r.tossup ? ' class="toss"' : ''}><td>${esc(r.label)}</td><td class="num">${r.n}</td><td class="num">${Math.round(r.expected)}%</td><td class="num"><b>${Math.round(r.actual)}%</b></td><td class="num">${r.n_now ? `${Math.round(r.actual_now)}% <small>of ${r.n_now}</small>` : '&ndash;'}</td></tr>`).join('')}</tbody></table>`;
  NFLE.areas.model = {
    mount(sec) {
      sec.innerHTML = `<div class="sec-head"><div><h2>The model</h2><p>How every number on this site is calculated. Blue values are filled in live from the latest build.</p></div></div>
        <div class="md-body"><p class="muted">Loading the model description&hellip;</p></div>`;
      const body = sec.querySelector('.md-body');
      NFLE.load('data/model.json').then(m => {
        // m.html is our own build's rendering of MODEL.md (trusted, same origin): inserted as HTML on purpose
        body.innerHTML = `${m.stale ? '<div class="stale">This description may be out of date: the model code or configuration changed after it was last reviewed.</div>' : ''}
          <div class="doc-layout"><nav class="toc">${m.toc.map(h => `<a href="#${esc(h.id)}">${esc(h.title)}</a>`).join('')}${m.track ? '<a href="#track-record">How often favorites win</a>' : ''}</nav>
          <article class="card card-pad doc">${m.html}${track(m.track)}</article></div>`;
        // table-of-contents links scroll within the page (the hash is the router's)
        body.querySelector('.toc').addEventListener('click', e => {
          const a = e.target.closest('a[href^="#"]'); if (!a) return;
          e.preventDefault();
          const t = document.getElementById(a.getAttribute('href').slice(1)); if (t) t.scrollIntoView({ behavior: 'smooth' });
        });
      }).catch(() => { body.innerHTML = '<p class="muted">Couldn\'t load the model description right now.</p>'; });
    },
  };
})();
