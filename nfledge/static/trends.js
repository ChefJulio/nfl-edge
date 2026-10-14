// Players > Trends: a play-level query builder over every run and pass play since 1999 (data/plays/<season>.json,
// tools/trends_build.py). The query reads as a sentence of tappable chips ("Rushing YPC for Ravens players, 4th
// quarter, 2022-2024, by player"); the answer is a leaderboard against the league in the same situation, with a
// minimum sample (small samples greyed, not hidden), a trend line when grouped by season, and a shareable link
// (?t=... in the URL). Everything is counted in the browser from the season files, loaded only when a query needs them.
(() => {
  const NFLE = window.NFLE, esc = NFLE.esc;
  const LS = 'nfledge-trends';
  // ---- stat families: which plays count, whose they are, what is summed, and the metrics built from the sums
  const FAM = {
    rush: { label: 'Rushing', unit: 'rushes', min: 20, play: (P, j) => P.ty[j] !== 1, actor: (P, j) => P.ru[j],
      add: (a, P, j) => { a.n++; a.y += P.y[j]; a.td += P.td[j]; a.e += P.e[j]; a.s += P.s[j]; a.fd += P.fd[j]; a.x += P.y[j] >= 10; a.fl += P.fl[j]; },
      met: { ypc: ['YPC', a => a.y / a.n, 2], yds: ['Yards', a => a.y, 0], att: ['Rushes', a => a.n, 0], td: ['TDs', a => a.td, 0],
             epa: ['EPA / rush', a => a.e / 100 / a.n, 3], sr: ['Success %', a => 100 * a.s / a.n, 1], fd: ['1st down %', a => 100 * a.fd / a.n, 1],
             x: ['10+ yd %', a => 100 * a.x / a.n, 1] } },
    pass: { label: 'Passing', unit: 'dropbacks', min: 50, play: (P, j) => P.ty[j] === 1, actor: (P, j) => P.pp[j],
      add: (a, P, j) => { a.n++; const sk = P.sk[j]; a.att += P.pa[j] && !sk; a.c += P.c[j]; a.y += sk ? 0 : P.y[j]; a.td += P.td[j] && P.c[j];
        a.int += P.in[j]; a.sk += sk; a.e += P.e[j]; a.s += P.s[j]; if (P.pa[j] && !sk && P.ay[j] > -99) { a.ay += P.ay[j]; a.ayn++; } },
      met: { ypa: ['Yds / att', a => a.y / a.att, 2], cmp: ['Comp %', a => 100 * a.c / a.att, 1], yds: ['Yards', a => a.y, 0], td: ['TDs', a => a.td, 0],
             int: ['INTs', a => a.int, 0], epa: ['EPA / dropback', a => a.e / 100 / a.n, 3], sr: ['Success %', a => 100 * a.s / a.n, 1],
             skr: ['Sack %', a => 100 * a.sk / a.n, 1], adot: ['Air yds / att', a => a.ay / a.ayn, 1], att: ['Attempts', a => a.att, 0] } },
    rec: { label: 'Receiving', unit: 'targets', min: 15, play: (P, j) => P.ty[j] === 1 && P.re[j] >= 0, actor: (P, j) => P.re[j],
      add: (a, P, j) => { a.n++; a.c += P.c[j]; a.y += P.c[j] ? P.y[j] : 0; a.td += P.td[j] && P.c[j]; a.e += P.e[j]; a.s += P.s[j];
        if (P.c[j] && P.yc[j] > -99) { a.yac += P.yc[j]; a.ycn++; } if (P.ay[j] > -99) { a.ay += P.ay[j]; a.ayn++; } },
      met: { ypt: ['Yds / target', a => a.y / a.n, 2], yds: ['Yards', a => a.y, 0], rec: ['Catches', a => a.c, 0], tgt: ['Targets', a => a.n, 0],
             cr: ['Catch %', a => 100 * a.c / a.n, 1], td: ['TDs', a => a.td, 0], yac: ['YAC / catch', a => a.yac / a.ycn, 1],
             adot: ['aDOT', a => a.ay / a.ayn, 1], epa: ['EPA / target', a => a.e / 100 / a.n, 3], sr: ['Success %', a => 100 * a.s / a.n, 1] } },
    team: { label: 'Team offense', unit: 'plays', min: 50, play: () => true, actor: (P, j) => P.o[j], teamActor: true,
      add: (a, P, j) => { a.n++; a.y += P.y[j]; a.e += P.e[j]; a.s += P.s[j]; a.db += P.ty[j] === 1; a.td += P.td[j]; a.fd += P.fd[j]; },
      met: { epa: ['EPA / play', a => a.e / 100 / a.n, 3], ypp: ['Yds / play', a => a.y / a.n, 2], sr: ['Success %', a => 100 * a.s / a.n, 1],
             pr: ['Pass rate %', a => 100 * a.db / a.n, 1], fd: ['1st down %', a => 100 * a.fd / a.n, 1], plays: ['Plays', a => a.n, 0], td: ['TDs', a => a.td, 0] } },
  };
  const FIRST = { rush: 'ypc', pass: 'epa', rec: 'ypt', team: 'epa' };
  // ---- situation filters: each a list of [value, label, test]
  const FILTERS = {
    qtr: ['Quarter', [['1', '1st quarter', (P, j) => P.q[j] === 1], ['2', '2nd quarter', (P, j) => P.q[j] === 2], ['3', '3rd quarter', (P, j) => P.q[j] === 3],
      ['4', '4th quarter', (P, j) => P.q[j] === 4], ['ot', 'overtime', (P, j) => P.q[j] >= 5], ['h2', '2nd half + OT', (P, j) => P.q[j] >= 3]]],
    down: ['Down', [['1', '1st down', (P, j) => P.dn[j] === 1], ['2', '2nd down', (P, j) => P.dn[j] === 2], ['3', '3rd down', (P, j) => P.dn[j] === 3],
      ['4', '4th down', (P, j) => P.dn[j] === 4], ['34', '3rd or 4th down', (P, j) => P.dn[j] >= 3]]],
    dist: ['Distance', [['s', 'short (1-3 to go)', (P, j) => P.tg[j] <= 3], ['m', 'medium (4-7 to go)', (P, j) => P.tg[j] >= 4 && P.tg[j] <= 7], ['l', 'long (8+ to go)', (P, j) => P.tg[j] >= 8]]],
    zone: ['Field zone', [['rz', 'red zone', (P, j) => P.yl[j] <= 20], ['gl', 'inside the 10', (P, j) => P.yl[j] <= 10], ['opp', "opponent's half", (P, j) => P.yl[j] <= 50], ['own', 'own half', (P, j) => P.yl[j] > 50]]],
    score: ['Score', [['l9', 'leading by 9+', (P, j) => P.sd[j] >= 9], ['l', 'leading by 1-8', (P, j) => P.sd[j] >= 1 && P.sd[j] <= 8], ['t', 'tied', (P, j) => P.sd[j] === 0],
      ['b', 'trailing by 1-8', (P, j) => P.sd[j] <= -1 && P.sd[j] >= -8], ['b9', 'trailing by 9+', (P, j) => P.sd[j] <= -9], ['one', 'one-score game', (P, j) => Math.abs(P.sd[j]) <= 8]]],
    time: ['Clock', [['2m', 'last 2 minutes of a half', (P, j) => P.hs[j] <= 12], ['5m', 'last 5 minutes of a half', (P, j) => P.hs[j] <= 30]]],
    site: ['Home / away', [['h', 'at home', (P, j, G) => G[P.g[j]][3] === P.o[j]], ['a', 'on the road', (P, j, G) => G[P.g[j]][3] !== P.o[j]]]],
    form: ['Formation', [['sg', 'shotgun', (P, j) => P.sg[j] === 1], ['uc', 'under center', (P, j) => P.sg[j] === 0], ['nh', 'no huddle', (P, j) => P.nh[j] === 1]]],
    dir: ['Run direction', [['l', 'runs left', (P, j) => P.rl[j] === 1], ['m', 'runs up the middle', (P, j) => P.rl[j] === 2], ['r', 'runs right', (P, j) => P.rl[j] === 3]]],
    depth: ['Pass depth', [['b', 'behind the line', (P, j) => P.ay[j] > -99 && P.ay[j] < 0], ['s', 'short (under 10 air yds)', (P, j) => P.ay[j] > -99 && P.ay[j] < 10],
      ['i', 'intermediate (10-19)', (P, j) => P.ay[j] >= 10 && P.ay[j] < 20], ['d', 'deep (20+)', (P, j) => P.ay[j] >= 20]]],
  };
  const BY = { player: 'player', team: 'team', season: 'season', opp: 'opponent', qtr: 'quarter', down: 'down' };
  const EXAMPLES = [
    ['4th-quarter rushing, one-score games', { fam: 'rush', met: 'ypc', who: 'L', by: 'player', f: { qtr: '4', score: 'one' } }],
    ['3rd-and-long passing', { fam: 'pass', met: 'epa', who: 'L', by: 'player', f: { down: '3', dist: 'l' } }],
    ['Red-zone targets', { fam: 'rec', met: 'tgt', who: 'L', by: 'player', f: { zone: 'rz' } }],
    ['Deep passing by team', { fam: 'pass', met: 'ypa', who: 'L', by: 'team', f: { depth: 'd' } }],
    ['Runs when leading by 9+', { fam: 'rush', met: 'sr', who: 'L', by: 'team', f: { score: 'l9' } }],
  ];
  const fmt = (v, d) => v == null || !isFinite(v) ? '–' : d ? v.toFixed(d) : Math.round(v).toLocaleString();
  const sel = (cls, opts, val, label) => `<select class="tr-chip ${cls}" aria-label="${esc(label)}">${opts.map(([v, l]) => `<option value="${esc(v)}"${String(v) === String(val) ? ' selected' : ''}>${esc(l)}</option>`).join('')}</select>`;

  NFLE.areas.trends = {
    mount(sec) {
      sec.classList.remove('soon');
      let IX = null, Q = null, table = null, busy = 0;
      const files = {};
      const defaults = () => ({ fam: 'rush', met: 'ypc', who: 'L', by: 'player', st: 'reg', from: null, to: null, f: {}, min: null });
      const fromUrl = () => { try { const t = new URLSearchParams(location.search).get('t'); return t ? JSON.parse(decodeURIComponent(escape(atob(t)))) : null; } catch (e) { return null; } };
      const saved = () => { try { return JSON.parse(localStorage.getItem(LS) || 'null'); } catch (e) { return null; } };
      sec.innerHTML = `<div class="sec-head"><div><h2>Trends</h2><p>Ask the play-by-play anything: every run and pass since 1999. Tap any word to change it.</p></div></div>
        <div class="dt-card tr-card"><div class="tr-q"></div><div class="tr-ex"></div></div>
        <div class="tr-base muted"></div><div class="tr-trend"></div><div class="tr-tbl"></div>
        <p class="st-note muted">nflverse play-by-play. Rushing counts designed runs and QB scrambles; passing counts dropbacks (sacks included; yards per attempt and completion % use pass attempts). EPA = expected points added. Rows under the minimum sample are greyed: small samples make loud, fake trends.</p>`;
      const qbox = sec.querySelector('.tr-q');
      sec.querySelector('.tr-ex').innerHTML = `<span class="muted">Try:</span> ${EXAMPLES.map((e, i) => `<button type="button" class="tr-exb" data-ex="${i}">${esc(e[0])}</button>`).join('')}`;

      // ---- the sentence
      const teamsOf = () => (IX && IX.teams) || [];
      const render = () => {
        const fam = FAM[Q.fam], seasons = IX.seasons;
        const whoOpts = [['L', 'the whole league'], ...teamsOf().map(t => [`T:${t}`, `${t} ${Q.fam === 'team' ? 'offense' : 'players'}`]), ...teamsOf().map(t => [`V:${t}`, `against ${t}`])];
        const famSel = sel('tr-fam', Object.entries(FAM).map(([k, f]) => [k, f.label]), Q.fam, 'Stat family');
        const metSel = sel('tr-met', Object.entries(fam.met).map(([k, m]) => [k, m[0]]), Q.met, 'Metric');
        const who = sel('tr-who', whoOpts, Q.who, 'Who');
        const yrs = seasons.map(s => [s, s]);
        const span = `${sel('tr-from', yrs, Q.from, 'From season')}<span class="tr-w">to</span>${sel('tr-to', yrs, Q.to, 'To season')}`;
        const st = sel('tr-st', [['reg', 'regular season'], ['post', 'playoffs'], ['both', 'regular season + playoffs']], Q.st, 'Season type');
        const by = sel('tr-by', Object.entries(BY).filter(([k]) => !(Q.fam === 'team' && k === 'player')).map(([k, l]) => [k, l]), Q.by, 'Group by');
        const chips = Object.entries(Q.f).map(([k, v]) => {
          const [name, opts] = FILTERS[k];
          return `<span class="tr-fchip">${sel(`tr-f`, opts.map(o => [o[0], o[1]]), v, name).replace('class="tr-chip tr-f"', `class="tr-chip tr-f" data-f="${k}"`)}<button type="button" class="tr-x" data-x="${k}" aria-label="Remove">&times;</button></span>`;
        }).join('');
        const free = Object.entries(FILTERS).filter(([k]) => !(k in Q.f) && !(k === 'dir' && Q.fam !== 'rush' && Q.fam !== 'team') && !(k === 'depth' && Q.fam === 'rush'));
        const add = free.length ? `<select class="tr-chip tr-add" aria-label="Add a filter"><option value="">+ filter</option>${free.map(([k, [n]]) => `<option value="${k}">${esc(n)}</option>`).join('')}</select>` : '';
        qbox.innerHTML = `<div class="tr-line">${famSel} ${metSel} <span class="tr-w">for</span> ${who}</div>
          <div class="tr-line">${chips} ${add}</div>
          <div class="tr-line">${span} <span class="tr-w">&middot;</span> ${st} <span class="tr-w">&middot; by</span> ${by}</div>
          <div class="tr-line tr-tools"><label class="tr-min"><span class="tr-w">min</span> <input type="range" min="0" max="${fam.min * 10}" step="${Math.max(1, Math.round(fam.min / 4))}" value="${Q.min ?? fam.min}"> <b>${Q.min ?? fam.min}</b> <span class="tr-w">${esc(fam.unit)}</span></label>
            <button type="button" class="tr-share">Copy link</button></div>`;
      };
      const save = () => { try { localStorage.setItem(LS, JSON.stringify(Q)); } catch (e) { /* private mode */ } };

      // ---- the query
      const load = () => {
        const want = IX.seasons.filter(s => s >= Q.from && s <= Q.to);
        return Promise.all(want.map(s => files[s] || (files[s] = NFLE.load(`data/plays/${s}.json`)))).then(docs => docs);
      };
      const run = () => {
        const me = ++busy;
        sec.querySelector('.tr-base').textContent = 'Counting plays…';
        load().then(docs => {
          if (me !== busy) return;
          const fam = FAM[Q.fam], m = fam.met[Q.met] || Object.values(fam.met)[0];
          const tests = Object.entries(Q.f).map(([k, v]) => (FILTERS[k][1].find(o => o[0] === v) || [])[2]).filter(Boolean);
          const [wk, wv] = Q.who === 'L' ? ['L', null] : Q.who.split(':');
          const groups = new Map(), league = {}, names = {}, teamOfPlayer = {};
          const blank = () => ({ n: 0, y: 0, td: 0, e: 0, s: 0, fd: 0, x: 0, fl: 0, att: 0, c: 0, int: 0, sk: 0, ay: 0, ayn: 0, yac: 0, ycn: 0, db: 0 });
          Object.assign(league, blank());
          let plays = 0;
          docs.forEach(D => {
            const P = D.cols, G = D.games, T = D.teams, n = D.n;
            const wt = wv != null ? T.indexOf(wv) : -2;
            D.players.forEach(([gid, nm]) => { names[gid] = nm; });
            for (let j = 0; j < n; j++) {
              const post = G[P.g[j]][2];
              if ((Q.st === 'reg' && post) || (Q.st === 'post' && !post)) continue;
              if (!fam.play(P, j)) continue;
              let ok = true;
              for (let k = 0; k < tests.length; k++) if (!tests[k](P, j, G)) { ok = false; break; }
              if (!ok) continue;
              const act = fam.actor(P, j);
              if (act < 0 && !fam.teamActor) continue;
              fam.add(league, P, j);
              if (wk === 'T' && P.o[j] !== wt) continue;
              if (wk === 'V' && P.d[j] !== wt) continue;
              plays++;
              let key, label;
              if (Q.by === 'player') { const gid = D.players[act][0]; key = gid; teamOfPlayer[gid] = T[P.o[j]]; }
              else if (Q.by === 'team') key = T[P.o[j]];
              else if (Q.by === 'opp') key = T[P.d[j]];
              else if (Q.by === 'season') key = D.season;
              else if (Q.by === 'qtr') key = P.q[j] >= 5 ? 'OT' : `Q${P.q[j]}`;
              else key = `${P.dn[j]}${['', 'st', 'nd', 'rd', 'th'][P.dn[j]] || ''} down`;
              let a = groups.get(key); if (!a) { a = blank(); groups.set(key, a); }
              fam.add(a, P, j);
            }
          });
          const lg = m[1](league), min = Q.min ?? fam.min;
          const rows = [...groups.entries()].map(([k, a]) => ({ key: k, a, n: a.n, v: m[1](a),
            label: Q.by === 'player' ? names[k] || k : String(k), team: Q.by === 'player' ? teamOfPlayer[k] : '' }));
          sec.querySelector('.tr-base').innerHTML = `League, same situation: <b>${fmt(lg, m[2])}</b> ${esc(m[0])} on ${fmt(league.n)} ${esc(fam.unit)}${wk !== 'L' ? ` &middot; this query: ${fmt(plays)} ${esc(fam.unit)}` : ''}`;
          // season trend line
          const trend = sec.querySelector('.tr-trend');
          if (Q.by === 'season' && rows.length > 1) {
            const r = rows.filter(x => isFinite(x.v)).sort((x, y) => x.key - y.key), vs = r.map(x => x.v), lo = Math.min(...vs, lg), hi = Math.max(...vs, lg), W = 320, H = 90;
            const X = i => 14 + i * (W - 28) / Math.max(1, r.length - 1), Y = v => H - 16 - (v - lo) / ((hi - lo) || 1) * (H - 30);
            trend.innerHTML = `<svg class="tr-svg" viewBox="0 0 ${W} ${H}" role="img"><line x1="10" x2="${W - 10}" y1="${Y(lg)}" y2="${Y(lg)}" class="tr-lg"/>
              <polyline points="${r.map((x, i) => `${X(i)},${Y(x.v)}`).join(' ')}" class="tr-pl"/>${r.map((x, i) => `<circle cx="${X(i)}" cy="${Y(x.v)}" r="3" class="tr-pt"><title>${x.key}: ${fmt(x.v, m[2])}</title></circle>
              <text x="${X(i)}" y="${H - 2}" class="tr-yr">${String(x.key).slice(2)}</text>`).join('')}</svg>`;
          } else trend.innerHTML = '';
          const cols = [
            { key: 'label', label: BY[Q.by][0].toUpperCase() + BY[Q.by].slice(1), stick: true, first: 'asc', value: r => r.label,
              html: r => Q.by === 'player' ? `<div class="who"><div><b>${esc(r.label)}</b><span class="sub">${esc(r.team || '')}</span></div></div>`
                : (Q.by === 'team' || Q.by === 'opp') ? `<span class="tm-open" data-tm="${esc(r.key)}"><b>${esc(r.label)}</b></span>` : `<b>${esc(r.label)}</b>` },
            { key: 'n', label: fam.unit[0].toUpperCase() + fam.unit.slice(1), num: true, value: r => r.n, html: r => fmt(r.n) },
            { key: 'v', label: m[0], num: true, cls: 'tr-main', value: r => isFinite(r.v) ? r.v : null, html: r => `<b>${fmt(r.v, m[2])}</b>` },
            { key: 'dv', label: 'vs league', num: true, value: r => isFinite(r.v) ? r.v - lg : null,
              html: r => { const d = r.v - lg; return isFinite(d) ? `<span class="${d > 0 ? 'tr-up' : d < 0 ? 'tr-dn' : ''}">${d > 0 ? '+' : ''}${fmt(d, m[2] || 0)}</span>` : '–'; } },
            ...Object.entries(fam.met).filter(([k]) => k !== Q.met).slice(0, 4).map(([k, mm]) => ({ key: `m_${k}`, label: mm[0], num: true,
              value: r => { const v = mm[1](r.a); return isFinite(v) ? v : null; }, html: r => fmt(mm[1](r.a), mm[2]) })),
          ];
          const tb = sec.querySelector('.tr-tbl');
          if (!rows.length) { tb.innerHTML = '<p class="muted">No plays match.</p>'; table = null; return; }
          const sortKey = Q.by === 'season' || Q.by === 'qtr' || Q.by === 'down' ? 'label' : 'v';
          const opt = { columns: cols, rows, sort: { key: sortKey, dir: sortKey === 'label' ? (Q.by === 'season' ? 'desc' : 'asc') : 'desc' },
            rowClass: r => r.n < min ? 'tr-low' : '', rowAttrs: r => Q.by === 'player' && /^\d\d-\d{7}$/.test(r.key) ? `data-open-pid="${esc(r.key)}"` : '' };
          tb.innerHTML = ''; table = NFLE.Table(tb, opt);
        }).catch(e => { sec.querySelector('.tr-base').textContent = `Couldn't load plays (${e.message}).`; });
      };
      const update = (re = true) => { save(); render(); if (re) run(); };

      // ---- events (delegated: the sentence redraws on every change)
      qbox.addEventListener('change', e => {
        const t = e.target;
        if (t.matches('.tr-fam')) { Q.fam = t.value; Q.met = FIRST[Q.fam]; Q.min = null; if (Q.fam === 'team' && Q.by === 'player') Q.by = 'team'; }
        else if (t.matches('.tr-met')) Q.met = t.value;
        else if (t.matches('.tr-who')) Q.who = t.value;
        else if (t.matches('.tr-from')) { Q.from = +t.value; if (Q.to < Q.from) Q.to = Q.from; }
        else if (t.matches('.tr-to')) { Q.to = +t.value; if (Q.from > Q.to) Q.from = Q.to; }
        else if (t.matches('.tr-st')) Q.st = t.value;
        else if (t.matches('.tr-by')) Q.by = t.value;
        else if (t.matches('.tr-f')) Q.f[t.dataset.f] = t.value;
        else if (t.matches('.tr-add') && t.value) Q.f[t.value] = FILTERS[t.value][1][0][0];
        else return;
        update();
      });
      qbox.addEventListener('input', e => {
        if (!e.target.matches('.tr-min input')) return;
        Q.min = +e.target.value; e.target.nextElementSibling.textContent = Q.min; save();
        if (table) { const min = Q.min; sec.querySelectorAll('.tr-tbl tbody tr').forEach(() => {}); run(); }
      });
      qbox.addEventListener('click', e => {
        const x = e.target.closest('[data-x]');
        if (x) { delete Q.f[x.dataset.x]; update(); return; }
        if (e.target.closest('.tr-share')) {
          const t = btoa(unescape(encodeURIComponent(JSON.stringify(Q))));
          const url = `${location.origin}${location.pathname}?t=${encodeURIComponent(t)}#players/trends`;
          const done = () => { const b = e.target.closest('.tr-share'); b.textContent = 'Link copied'; setTimeout(() => { b.textContent = 'Copy link'; }, 1600); };
          if (navigator.share && matchMedia('(pointer: coarse)').matches) navigator.share({ url }).catch(() => {});
          else if (navigator.clipboard) navigator.clipboard.writeText(url).then(done, () => prompt('Copy this link', url));
          else prompt('Copy this link', url);
        }
      });
      sec.querySelector('.tr-ex').addEventListener('click', e => {
        const b = e.target.closest('[data-ex]'); if (!b) return;
        const ex = EXAMPLES[+b.dataset.ex][1];
        Q = Object.assign(defaults(), { from: Q.from, to: Q.to }, JSON.parse(JSON.stringify(ex)));
        update();
      });
      NFLE.load('data/plays/index.json').then(ix => {
        IX = ix;
        return NFLE.load(`data/plays/${ix.seasons[ix.seasons.length - 1]}.json`).then(d => { IX.teams = d.teams.slice().sort(); });
      }).then(() => {
        const last = IX.seasons[IX.seasons.length - 1];
        Q = Object.assign(defaults(), saved() || {}, fromUrl() || {});
        if (!Q.to || !IX.seasons.includes(Q.to)) Q.to = last;
        if (!Q.from || !IX.seasons.includes(Q.from)) Q.from = Math.max(IX.seasons[0], Q.to - 2);
        if (!FAM[Q.fam]) Q.fam = 'rush';
        if (!FAM[Q.fam].met[Q.met]) Q.met = FIRST[Q.fam];
        update();
      }).catch(() => { sec.querySelector('.tr-base').textContent = 'Play data is not available on this page.'; });
    },
  };
})();
