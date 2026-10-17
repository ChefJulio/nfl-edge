// Model: how every number on the site is made. The text is MODEL.md with this build's live values, turned into HTML
// by the current week's build (data/model.json at the site root: html + toc + stale flag + the favorites track
// record), so every week's page - archived and lookahead too - shows the same, current description.
(() => {
  const NFLE = window.NFLE, esc = NFLE.esc;
  const track = t => !t ? '' : `<h2 id="track-record">How often favorites win</h2>
    <p>Market chances, ${esc(t.since)}&ndash;${esc(t.season)}. A well-calibrated forecast's favorites win about as often as their chance says; each season is scored with chances fit only on the seasons before it.</p>
    <table class="trk"><thead><tr><th>Favorite's chance</th><th class="num">Games</th><th class="num">Expected</th><th class="num">Won</th><th class="num">${esc(t.season)}</th></tr></thead>
    <tbody>${t.rows.map(r => `<tr${r.tossup ? ' class="toss"' : ''}><td>${esc(r.label)}</td><td class="num">${r.n}</td><td class="num">${Math.round(r.expected)}%</td><td class="num"><b>${Math.round(r.actual)}%</b></td><td class="num">${r.n_now ? `${Math.round(r.actual_now)}% <small>of ${r.n_now}</small>` : '&ndash;'}</td></tr>`).join('')}</tbody></table>`;
  // "How accurate is our chance to play?" (data/history/availability_track.json via the build; tools/avail_track.py)
  const avail = a => {
    if (!a) return '';
    const f3 = v => v.toFixed(3);
    const worst = Math.max(...a.versus.map(v => v.brier));
    const vs = a.versus.map(v => `<tr${v.ours ? ' class="av-ours"' : ''}><td>${esc(v.label)}</td><td class="num">${f3(v.brier)}</td>
      <td class="av-barc"><span class="av-bar" style="width:${Math.round(100 * v.brier / worst)}%"></span></td></tr>`).join('');
    // calibration: one dot per band, predicted (x) vs played (y); on the diagonal = said what happened
    const W = 300, H = 220, pad = 30, X = v => pad + (W - pad - 10) * v / 100, Y = v => H - pad - (H - pad - 10) * v / 100;
    const ticks = [0, 25, 50, 75, 100];
    const dots = (rows, cls) => rows.map(r => `<circle class="${cls}" cx="${X(r.predicted).toFixed(1)}" cy="${Y(r.played).toFixed(1)}" r="${cls === 'av-now' ? 4 : Math.max(4, Math.min(9, Math.sqrt(r.n) / 12)).toFixed(1)}"><title>${esc(r.band)}: we said ${r.predicted}%, ${r.played}% played (${r.n})</title></circle>`).join('');
    const svg = `<svg class="av-cal" viewBox="0 0 ${W} ${H}" role="img" aria-label="Calibration: our predicted chance to play vs how often those players played">
      ${ticks.map(v => `<line class="av-grid" x1="${X(0)}" x2="${X(100)}" y1="${Y(v)}" y2="${Y(v)}"/><text class="av-ax" x="${pad - 6}" y="${Y(v) + 3}" text-anchor="end">${v}</text>
        <text class="av-ax" x="${X(v)}" y="${H - pad + 14}" text-anchor="middle">${v}</text>`).join('')}
      <line class="av-diag" x1="${X(0)}" y1="${Y(0)}" x2="${X(100)}" y2="${Y(100)}"/>
      ${dots(a.calib, 'av-dot')}${a.now ? dots(a.now.calib, 'av-now') : ''}
      <text class="av-axl" x="${(X(0) + X(100)) / 2}" y="${H - 2}" text-anchor="middle">we said he'd play (%)</text>
      <text class="av-axl" transform="translate(9 ${(Y(0) + Y(100)) / 2}) rotate(-90)" text-anchor="middle">actually played (%)</text></svg>`;
    const cal = a.calib.map((r, i) => {
      const nw = a.now && a.now.calib.find(x => x.band === r.band);
      return `<tr><td>${esc(r.band)}</td><td class="num">${r.n.toLocaleString()}</td><td class="num">${r.predicted}%</td><td class="num"><b>${r.played}%</b></td>
        <td class="num muted">${nw ? `${nw.played}% <small>of ${nw.n}</small>` : '&ndash;'}</td></tr>`;
    }).join('');
    const st = a.stages.map(s => `<tr><td>${esc(s.label)}</td><td class="num">${f3(s.brier)}</td><td class="num">${s.wrong}%</td></tr>`).join('');
    let when = '';
    const spots = a.spots.map(s => {
      const gap = s.predicted - s.played, off = Math.abs(gap) >= 4;
      const head = s.when !== when ? `<tr class="av-when"><td colspan="5">${esc(s.when)}</td></tr>` : '';
      when = s.when;
      return `${head}<tr><td>${esc(s.label)}</td><td class="num">${s.n.toLocaleString()}</td><td class="num"><b>${s.played}%</b></td><td class="num">${s.predicted}%</td>
        <td class="num ${off ? 'av-off' : 'muted'}">${gap > 0 ? '+' : ''}${gap.toFixed(1)}</td></tr>`;
    }).join('');
    return `<h2 id="avail-record">How accurate is our chance to play?</h2>
      <p>Every number below was scored the way it would have worked live: each season (${esc(a.seasons)}) predicted by models trained only on the seasons before it, for quarterbacks, running backs, receivers and tight ends; players ruled Out are left out (that is 0% by rule). The error score is the average squared miss (a Brier score): lower is better, and 0 would mean never wrong.</p>
      <h3>Against the usual ways to read the injury report</h3>
      <table class="trk av-vs"><thead><tr><th>Final injury report, read as&hellip;</th><th class="num">Error</th><th></th></tr></thead><tbody>${vs}</tbody></table>
      <h3>When we say a chance, does it happen that often?</h3>
      <p>Each dot is a group of players we gave a similar chance to play; on the line means it happened exactly as often as we said. Bigger dots = more players. ${a.now ? `Hollow dots: this season so far (weeks ${esc(a.now.weeks)}, models trained only on earlier seasons).` : ''}</p>
      ${svg}
      <table class="trk"><thead><tr><th>We said</th><th class="num">Players</th><th class="num">Our average</th><th class="num">Played</th><th class="num">${a.now ? esc(a.now.season) : ''}</th></tr></thead><tbody>${cal}</tbody></table>
      <h3>Through the week</h3>
      <p>"Wrong call" = he did the opposite of what we leaned (we said more likely to play, he sat, or the reverse). Some of that can't be avoided: when 7 in 10 players in a spot play, 3 in 10 won't.</p>
      <table class="trk"><thead><tr><th>When</th><th class="num">Error</th><th class="num">Wrong call</th></tr></thead><tbody>${st}</tbody></table>
      <h3>Common situations</h3>
      <p>How often players in each spot actually played, next to what we predicted for them on average. Gaps of 4 points or more are marked.</p>
      <table class="trk av-spots"><thead><tr><th>Situation</th><th class="num">Players</th><th class="num">Played</th><th class="num">We said</th><th class="num">Gap</th></tr></thead><tbody>${spots}</tbody></table>`;
  };
  NFLE.areas.model = {
    mount(sec) {
      sec.innerHTML = `<div class="sec-head"><div><h2>The model</h2><p>How every number on this site is calculated. Blue values are filled in live from the latest build.</p></div></div>
        <div class="md-body skel-zone"></div>`;
      const body = sec.querySelector('.md-body');
      NFLE.load('data/model.json').then(m => {
        // m.html is our own build's rendering of MODEL.md (trusted, same origin): inserted as HTML on purpose
        body.innerHTML = `${m.stale ? '<div class="stale">This description may be out of date: the model code or configuration changed after it was last reviewed.</div>' : ''}
          <div class="seg md-areas" role="tablist"></div>
          <div class="doc-layout"><nav class="toc"></nav><article class="card card-pad doc">${m.html}</article></div>`;
        // One area at a time (owner 2026-10-16: explanations split by what we compute): each "## " section of MODEL.md
        // is an area; its track record goes inside it; the desktop side list shows the open area's subsections.
        const art = body.querySelector('article'), toc = body.querySelector('.toc'), bar = body.querySelector('.md-areas');
        const areas = [];
        let cur = null;
        [...art.childNodes].forEach(n => {
          if (n.nodeType === 1 && n.tagName === 'H2') {
            cur = document.createElement('div');
            cur.className = 'md-area';
            cur.dataset.title = n.textContent.trim();
            art.insertBefore(cur, n);
            areas.push(cur);
          }
          if (cur) cur.appendChild(n); else if (n.nodeType === 1 && n.tagName === 'H1') n.remove();
        });
        const place = (re, html) => { if (html) (areas.find(a => re.test(a.dataset.title)) || areas[areas.length - 1]).insertAdjacentHTML('beforeend', html); };
        place(/chance to play|inactive|availability/i, avail(m.avail));
        place(/^games|game lines/i, track(m.track));
        let saved = null;
        try { saved = sessionStorage.getItem('nfle-model-area'); } catch (e) { /* private mode */ }
        const show = title => {
          const a = areas.find(x => x.dataset.title === title) || areas[0];
          if (!a) return;
          areas.forEach(x => { x.hidden = x !== a; });
          bar.querySelectorAll('button').forEach(b => b.classList.toggle('on', b.dataset.t === a.dataset.title));
          a.querySelectorAll('h3').forEach((h, i) => { if (!h.id) h.id = `ma-${areas.indexOf(a)}-${i}`; });
          toc.innerHTML = [...a.querySelectorAll('h3')].map(h => `<a href="#${esc(h.id)}">${esc(h.textContent)}</a>`).join('');
          toc.parentElement.classList.toggle('no-toc', !toc.children.length);  // no subsections: no empty side column
          try { sessionStorage.setItem('nfle-model-area', a.dataset.title); } catch (e) { /* private mode */ }
        };
        bar.innerHTML = areas.map(a => `<button type="button" role="tab" data-t="${esc(a.dataset.title)}">${esc(a.dataset.title.replace(/^\d+\.\s*/, ''))}</button>`).join('');
        bar.addEventListener('click', e => { const b = e.target.closest('button[data-t]'); if (b) { show(b.dataset.t); window.scrollTo({ top: sec.offsetTop - 60 }); } });
        show(saved);
        // side-list links scroll within the page (the hash is the router's)
        toc.addEventListener('click', e => {
          const a = e.target.closest('a[href^="#"]'); if (!a) return;
          e.preventDefault();
          const t = document.getElementById(a.getAttribute('href').slice(1)); if (t) t.scrollIntoView({ behavior: 'smooth' });
        });
      }).catch(() => { body.innerHTML = '<p class="muted">Couldn\'t load the model description right now.</p>'; });
    },
  };
})();
