// shell.js NFLE.ui.matchTile as of tag matchups-v1 (2026-10-18)
matchTile: (g, href) => {
      // the team's wordmark (owner 2026-10-17, as on All teams: tools/wordmarks_build.py), the typed nickname if it fails
      // the line in words (owner 2026-10-17): "JAX -2.5" -> "JAX by 2.5", "PK" -> "pick'em"
      const vegas = l => { const m = /^([A-Z]{2,3}) -(\d+(?:\.\d)?)$/.exec(l || '');
        return m ? `<b>${esc(m[1])} by ${+m[2]}</b>` : l === 'PK' ? "<b>pick'em</b>" : `<b>${esc(l)}</b>`; };
      // the team name in one scoreboard font (owner 2026-10-18, Barlow Condensed ExtraBold italic, self-hosted, OFL): the
      // official wordmarks are each team's own drawn lettering, so weight, spacing and height never matched; the images
      // stay on All teams (teamgrid.js), the per-mark sizing is in git history (b562159)
      const wordmark = s => `<span class="mt-tn">${esc(s.nick)}</span>`;
      const f = g.fc || {}, fin = g.final;
      const sides = [[g.away, fin && fin.away, fin && fin.home, f.p_away], [g.home, fin && fin.home, fin && fin.away, f.p_home]];
      // (the playoff-stakes line, matchups.js, likewise)
      // the whole tile opens the gamecast (owner 2026-10-18: "tapping anywhere on a matchup tile should bring to the
      // gamecast"): team names, logos and codes in it are plain text, not team links
      const T = (t, html) => html == null ? esc(t) : html;
      const verdict = !fin ? '' : !fin.winner ? '<span class="gf-pick toss">Tie</span>'
        : f.tossup ? `<span class="gf-pick toss">Tossup &middot; ${T(fin.winner)} won</span>`
          : fin.fav_won ? `<span class="gf-pick ok">Favorite won &middot; ${f.pct}%</span>`
            : `<span class="gf-pick miss">Upset &middot; a ${100 - f.pct}% chance</span>`;
      const main = sides.map(([s, sc, os, pct], i) => {
        const side = i ? 'home' : 'away';
        const cls = `${fin && sc < os ? ' lost' : ''}${fin && sc > os ? ' won' : ''}${!fin && !f.tossup && pct < 50 ? ' dog' : ''}`;
        return `${s.logo_url ? `<img class="mt-lg ${side}" src="${esc(F.logoSrc(s.logo_url, 112))}" alt="" loading="lazy">` : ''}
          <div class="mt-side ${side}${cls}"><span class="mt-num">${fin ? esc(sc) : `${esc(pct)}<small>%</small>`}</span>
            <span class="mt-nm">${T(s.team, `<b>${wordmark(s)}</b>`)} <small>${esc(s.record)}</small></span></div>
          ${i ? '' : `<span class="mt-at">${g.neutral ? 'vs' : '@'}${f.tossup && !fin ? '<small>Tossup</small>' : ''}</span>`}`;
      }).join('');
      // when (owner 2026-10-17): kickoff / Final / the live clock at the top middle; the footer keeps the rest
      const when = fin ? `<span class="mt-fin">${fin.ot ? 'Final/OT' : 'Final'}</span>` : `${esc(g.kickoff)}${g.neutral ? ` &middot; ${esc(g.site || 'neutral')}` : ''}`;
      const st = fin ? verdict
        // the Vegas line when there is one (owner 2026-10-17: then no "ours", the big win chances above are ours); before
        // a line is posted, our pick in its place
        : g.vegas_line ? `<span class="mt-odds">Vegas: ${vegas(g.vegas_line)}</span>`
          : f.model_fav || f.model_tossup ? `<span class="mt-odds" title="${esc(f.model_why || '')}">No Vegas line yet &middot; ours ${f.model_tossup ? 'tossup' : `<b>${T(f.model_fav)} ${esc(f.model_pct)}%</b>`}</span>` : '';
      return `<a class="mt ${fin ? 'is-final' : 'is-pre'}${f.tossup && !fin ? ' toss' : ''}" data-gid="${esc(g.id)}" href="${esc(href || (NFLE.gameHref ? NFLE.gameHref(g) : '#'))}" style="${esc(g.bt_style || '')}">
        <div class="mt-main"><div class="mt-when">${when}</div>${main}</div><div class="mt-st">${st}</div></a>`;
    },