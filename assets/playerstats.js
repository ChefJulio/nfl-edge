// Players > Stats: raw regular-season stats for every player with a snap or a stat line that season
// (data/stats/players_<season>.json, tools/stats_build.py). Position groups get their own default columns; the last
// three columns are pickers over EVERY attribute we hold (saved in this browser). Fantasy points follow the site's
// scoring settings (NFLE.weights from gamecast.js). Rows open the player card.
(() => {
  const NFLE = window.NFLE, esc = NFLE.esc;
  const store = (k, v) => { try { if (v === undefined) return localStorage.getItem(k); localStorage.setItem(k, v); } catch (e) { return null; } return v; };
  const pageSeason = () => { const m = location.pathname.match(/(\d{4})\/week-\d+\.html$/); return m ? +m[1] : null; };
  const HALF = { pass_yd: 0.04, pass_td: 4, interception: -2, rush_yd: 0.1, rush_td: 6, reception: 0.5, rec_yd: 0.1, rec_td: 6, fumble_lost: -2, te_bonus: 0 };
  const GROUPS = {
    QB: ['QB'], RB: ['RB', 'FB', 'HB'], WR: ['WR'], TE: ['TE'], OL: ['T', 'G', 'C', 'OT', 'OG', 'OL', 'LS'],
    DL: ['DE', 'DT', 'NT', 'DL'], LB: ['LB', 'ILB', 'OLB', 'MLB'], DB: ['CB', 'S', 'FS', 'SS', 'DB', 'SAF'], K: ['K', 'PK'], P: ['P'],
  };
  const groupOf = pos => Object.keys(GROUPS).find(g => GROUPS[g].includes(pos)) || 'Other';
  const div = (a, b) => b ? a / b : null;
  // NFL passer rating (each part capped 0-2.375), for coverage allowed
  const passerRating = (c, a, y, t, i) => { if (!a) return null; const cl = v => Math.max(0, Math.min(2.375, v));
    return (cl((c / a - 0.3) * 5) + cl((y / a - 3) * 0.25) + cl(t / a * 20) + cl(2.375 - (i || 0) / a * 25)) / 6 * 100; };
  const fmt = {
    i: v => v == null ? '' : Math.round(v).toLocaleString(), y: v => v == null ? '' : String(Math.round(v)),  // y: years, no comma
    d1: v => v == null ? '' : v.toFixed(1), d2: v => v == null ? '' : v.toFixed(2),
    pct: v => v == null ? '' : `${(100 * v).toFixed(1)}%`, s: v => v == null ? '' : esc(v), epa: v => v == null ? '' : (v > 0 ? '+' : '') + v.toFixed(2),
    money: v => v == null ? '' : v >= 1 ? `$${v.toFixed(1)}M` : `$${Math.round(v * 1000)}K`,
  };
  // Every attribute we hold: [key, label, group, value(r, per), format, title, first-sort]. Counting stats (count: true)
  // divide by games in per-game mode.
  const A = [];
  const add = (key, label, group, fn, f = 'i', title = '', first = 'desc', count = false) => A.push({ key, label, group, fn, f, title, first, count });
  const raw = (key, label, group, f = 'i', title = '') => add(key, label, group, r => r[key], f, title, 'desc', true);
  // bio, draft, contract
  add('age', 'Age', 'Bio', r => r.age, 'd1', 'Age at the season opener', 'asc');
  add('ht', 'Height', 'Bio', r => r.ht, 'i', 'Inches'); add('wt', 'Weight', 'Bio', r => r.wt, 'i', 'Pounds');
  add('college', 'College', 'Bio', r => r.college, 's', '', 'asc'); add('exp', 'NFL yrs', 'Bio', r => r.exp, 'i', 'Seasons of experience that year');
  add('draft_y', 'Draft yr', 'Draft', r => r.draft_y, 'y', '', 'asc'); add('draft_r', 'Round', 'Draft', r => r.draft_r, 'i', '', 'asc');
  add('draft_o', 'Overall pick', 'Draft', r => r.draft_o, 'i', '', 'asc');
  add('draft', 'Draft', 'Draft', r => r.udfa ? 'UDFA' : r.draft_r ? `R${r.draft_r}:${r.draft_p}` : null, 's', 'Round:pick within the round', 'asc');
  add('apy', 'APY', 'Contract', r => r.apy, 'money', 'Average per year of the current deal (current season only)');
  add('deal_val', 'Deal total', 'Contract', r => r.deal_val, 'money'); add('deal_gtd', 'Guaranteed', 'Contract', r => r.deal_gtd, 'money');
  add('fa', 'Free agent', 'Contract', r => r.fa, 'i', 'Season he reaches free agency if not extended', 'asc');
  // usage
  add('games', 'G', 'Usage', r => r.games, 'i', 'Games played');
  raw('snaps_o', 'Off snaps', 'Usage'); add('snap_pct', 'Snap %', 'Usage', r => r.snap_pct || null, 'pct', 'Average share of offensive snaps');
  raw('snaps_d', 'Def snaps', 'Usage'); add('snap_pct_d', 'Def snap %', 'Usage', r => r.snap_pct_d || null, 'pct');
  raw('snaps_st', 'ST snaps', 'Usage');
  raw('targets', 'Tgt', 'Usage'); add('tgt_share', 'Tgt %', 'Usage', r => r.tgt_share || null, 'pct', 'Share of team targets');
  raw('carries', 'Car', 'Usage'); add('car_share', 'Car %', 'Usage', r => r.car_share || null, 'pct', 'Share of team carries');
  raw('car_i10', 'Car in 10', 'Usage', 'i', 'Carries inside the opponent 10'); raw('tgt_rz', 'RZ tgt', 'Usage', 'i', 'Targets inside the opponent 20');
  // passing
  add('cmp_att', 'Cmp/Att', 'Passing', r => r.attempts ? `${r.completions}/${r.attempts}` : null, 's', '', 'desc');
  raw('completions', 'Cmp', 'Passing'); raw('attempts', 'Att', 'Passing'); raw('passing_yards', 'Pass yds', 'Passing');
  raw('passing_tds', 'Pass TD', 'Passing'); raw('passing_interceptions', 'INT', 'Passing'); raw('sacks_suffered', 'Sacked', 'Passing');
  raw('passing_air_yards', 'Air yds', 'Passing'); raw('passing_first_downs', 'Pass 1D', 'Passing');
  // rushing / receiving
  raw('rushing_yards', 'Rush yds', 'Rushing'); raw('rushing_tds', 'Rush TD', 'Rushing'); raw('rushing_first_downs', 'Rush 1D', 'Rushing');
  raw('receptions', 'Rec', 'Receiving'); raw('receiving_yards', 'Rec yds', 'Receiving'); raw('receiving_tds', 'Rec TD', 'Receiving');
  raw('receiving_air_yards', 'Rec air yds', 'Receiving'); raw('receiving_yards_after_catch', 'YAC', 'Receiving'); raw('receiving_first_downs', 'Rec 1D', 'Receiving');
  raw('fumbles_lost_total', 'Fum lost', 'Rushing');
  // efficiency
  add('ypa', 'Y/A', 'Efficiency', r => div(r.passing_yards, r.attempts), 'd1', 'Passing yards per attempt');
  add('cmp_pct', 'Cmp%', 'Efficiency', r => div(r.completions, r.attempts), 'pct');
  add('ypc', 'YPC', 'Efficiency', r => div(r.rushing_yards, r.carries), 'd1', 'Rushing yards per carry');
  add('ypt', 'Y/Tgt', 'Efficiency', r => div(r.receiving_yards, r.targets), 'd1', 'Receiving yards per target');
  add('catch', 'Catch %', 'Efficiency', r => div(r.receptions, r.targets), 'pct');
  add('adot', 'aDOT', 'Efficiency', r => div(r.receiving_air_yards, r.targets), 'd1', 'Average depth of target');
  add('pass_epa', 'EPA/db', 'Efficiency', r => div(r.passing_epa, r.attempts + r.sacks_suffered), 'epa', 'Passing EPA per dropback');
  add('rush_epa', 'EPA/car', 'Efficiency', r => div(r.rushing_epa, r.carries), 'epa', 'Rushing EPA per carry');
  add('rec_epa', 'EPA/tgt', 'Efficiency', r => div(r.receiving_epa, r.targets), 'epa', 'Receiving EPA per target');
  // defense / kicking / punting / returns
  add('tackles', 'Tackles', 'Defense', r => (r.def_tackles_solo || 0) + (r.def_tackle_assists || 0) || null, 'i', 'Solo + assisted', 'desc', true);
  raw('def_tackles_for_loss', 'TFL', 'Defense'); raw('def_sacks', 'Sacks', 'Defense', 'd1'); raw('def_qb_hits', 'QB hits', 'Defense');
  raw('def_interceptions', 'Def INT', 'Defense'); raw('def_pass_defended', 'PD', 'Defense', 'i', 'Passes defended');
  raw('def_fumbles_forced', 'FF', 'Defense', 'i', 'Fumbles forced'); raw('def_tds', 'Def TD', 'Defense');
  raw('def_fum_rec', 'FR', 'Defense', 'i', 'Opponent fumbles recovered'); raw('def_safeties', 'Safeties', 'Defense');
  raw('def_blocks', 'Blocks', 'Defense', 'i', 'Blocked punts, field goals and extra points');
  // PFR advanced defense (2018 on): pass rush, coverage allowed, tackling
  raw('prs', 'Pressures', 'Pass rush', 'i', 'Sacks, QB hits and hurries (PFR, 2018 on)'); raw('hur', 'Hurries', 'Pass rush');
  raw('blz', 'Blitzes', 'Pass rush', 'i', 'Times he blitzed (defensive backs and linebackers)');
  raw('cov_tgt', 'Tgt allowed', 'Coverage', 'i', 'Passes thrown at the receiver he covered (PFR, 2018 on)');
  add('cov_cmp_pct', 'Cmp% allowed', 'Coverage', r => div(r.cov_cmp, r.cov_tgt), 'pct', 'Completion rate on throws into his coverage', 'asc');
  raw('cov_yds', 'Yds allowed', 'Coverage'); raw('cov_td', 'TD allowed', 'Coverage');
  add('cov_ypt', 'Yds/tgt allowed', 'Coverage', r => div(r.cov_yds, r.cov_tgt), 'd1', 'Yards allowed per target', 'asc');
  add('cov_rtg', 'Rating allowed', 'Coverage', r => passerRating(r.cov_cmp, r.cov_tgt, r.cov_yds, r.cov_td, r.cov_int), 'd1', 'Passer rating on throws into his coverage', 'asc');
  raw('mt', 'Missed tkl', 'Tackling', 'i', 'Missed tackles (PFR, 2018 on)');
  add('mt_pct', 'Missed %', 'Tackling', r => div(r.mt, (r.mt || 0) + (r.tk_comb || 0)), 'pct', 'Missed tackles / (tackles + missed)', 'asc');
  add('fg', 'FG', 'Kicking', r => r.fg_att ? `${r.fg_made}/${r.fg_att}` : null, 's'); raw('fg_made', 'FGM', 'Kicking');
  add('fg_pct', 'FG%', 'Kicking', r => div(r.fg_made, r.fg_att), 'pct'); add('fg_long', 'Long', 'Kicking', r => r.fg_att ? r.fg_long : null, 'i');
  add('pat', 'XP', 'Kicking', r => r.pat_att ? `${r.pat_made}/${r.pat_att}` : null, 's');
  raw('pt_att', 'Punts', 'Punting'); add('pt_avg', 'Avg', 'Punting', r => div(r.pt_yards, r.pt_att), 'd1', 'Yards per punt');
  raw('kickoff_return_yards', 'KR yds', 'Returns'); raw('punt_return_yards', 'PR yds', 'Returns');
  // fantasy (site scoring)
  add('fp', 'FPts', 'Fantasy', r => r._fp, 'd1', 'Fantasy points in your scoring', 'desc', true);
  add('fpg', 'FP/G', 'Fantasy', r => div(r._fp, r.games), 'd1', 'Fantasy points per game');
  add('fp_rank', 'Pos rank', 'Fantasy', r => r._rank, 'i', 'Fantasy-points finish at his position', 'asc');
  // careers (All years / a name search): the seasons he played, "2005-11", seasons count on hover
  const SPAN = { key: 'span', label: 'Seasons', first: 'asc', num: true, title: 'First and latest season (regular season)',
    value: r => r.first, html: r => r.first == null ? '' : `<span title="${r.nsea} season${r.nsea === 1 ? '' : 's'}">${r.first === r.season ? r.first : `${r.first}&ndash;${String(r.season).slice(2)}`}</span>` };
  const BY = Object.fromEntries(A.map(a => [a.key, a]));
  const DEFAULTS = {
    All: ['games', 'snaps_o', 'passing_yards', 'rushing_yards', 'receiving_yards', 'fp', 'fpg'],
    QB: ['games', 'cmp_att', 'passing_yards', 'passing_tds', 'passing_interceptions', 'ypa', 'sacks_suffered', 'rushing_yards', 'rushing_tds', 'fp', 'fpg'],
    RB: ['games', 'carries', 'rushing_yards', 'ypc', 'rushing_tds', 'car_share', 'targets', 'receptions', 'receiving_yards', 'receiving_tds', 'fp', 'fpg'],
    WR: ['games', 'targets', 'receptions', 'receiving_yards', 'ypt', 'receiving_tds', 'tgt_share', 'adot', 'fp', 'fpg'],
    TE: ['games', 'targets', 'receptions', 'receiving_yards', 'ypt', 'receiving_tds', 'tgt_share', 'snap_pct', 'fp', 'fpg'],
    OL: ['games', 'snaps_o', 'snap_pct', 'snaps_st'],
    DL: ['games', 'tackles', 'def_tackles_for_loss', 'def_sacks', 'prs', 'def_qb_hits', 'def_fumbles_forced', 'snap_pct_d', 'fp', 'fpg'],
    LB: ['games', 'tackles', 'def_tackles_for_loss', 'def_sacks', 'prs', 'def_interceptions', 'def_pass_defended', 'mt_pct', 'snap_pct_d', 'fp', 'fpg'],
    DB: ['games', 'tackles', 'def_interceptions', 'def_pass_defended', 'cov_tgt', 'cov_ypt', 'cov_rtg', 'mt_pct', 'snap_pct_d', 'fp', 'fpg'],
    K: ['games', 'fg', 'fg_pct', 'fg_long', 'pat'], P: ['games', 'pt_att', 'pt_avg'],
  };
  const SORT0 = { QB: 'fp', RB: 'fp', WR: 'fp', TE: 'fp', All: 'fp', OL: 'snaps_o', DL: 'fp', LB: 'fp', DB: 'fp', K: 'fg_made', P: 'pt_att' };
  const CUSTOM = 3;
  const pickHtml = (slot, key) => `<select class="ps-pick" data-slot="${slot}" aria-label="Custom column ${slot + 1}"><option value="">+ column</option>${
    [...new Set(A.map(a => a.group))].map(g => `<optgroup label="${esc(g)}">${A.filter(a => a.group === g).map(a => `<option value="${a.key}"${a.key === key ? ' selected' : ''}>${esc(a.label)}</option>`).join('')}</optgroup>`).join('')}</select>${
    key ? `<button type="button" class="ps-sort" data-slot="${slot}" aria-label="Sort by this column" title="Sort by this column">&#8597;</button>` : ''}`;

  NFLE.areas.playerstats = {
    mount(sec) {
      // team colors / logos for the tile rows (the week data's map); redraw once it is in
      let TEAMS = {};
      NFLE.week().then(D => { if (D && D.teams) { TEAMS = D.teams; if (table) { table = null; sec.querySelector('.ps-tbl').innerHTML = ''; draw(); } } });
      sec.classList.remove('soon');
      sec.innerHTML = `<div class="sec-head"><div><h2>Player stats</h2><p class="ps-sub">Loading&hellip;</p></div></div>
        <div class="dt-card"><div class="dt-tools">
          <select class="dt-select ps-season" aria-label="Season"></select>
          <div class="seg ps-type"><button type="button" data-t="reg">Regular season</button><button type="button" data-t="post">Playoffs</button></div>
          <select class="dt-select ps-pos" aria-label="Position">${['All', ...Object.keys(GROUPS)].map(g => `<option value="${g}">${g === 'All' ? 'All positions' : g}</option>`).join('')}</select>
          <div class="seg ps-per"><button type="button" data-v="tot">Totals</button><button type="button" data-v="pg">Per game</button></div>
          <input class="ps-q" type="search" placeholder="Find any player, any year" aria-label="Find a player">
        </div><p class="ps-searchnote" hidden></p><div class="skel-zone ps-tbl"></div></div>
        <p class="st-note muted">Raw stats, not adjusted for opponents (All years = regular-season careers). Fantasy points use your scoring settings (Rankings &rsaquo; Scoring &amp; league). The last three columns are yours: pick any stat, bio, draft or contract detail.</p>`;
      const sub = sec.querySelector('.ps-sub'), selS = sec.querySelector('.ps-season'), selP = sec.querySelector('.ps-pos'), q = sec.querySelector('.ps-q');
      let all = [], pos = store('nfledge-ps-pos') || 'QB', per = store('nfledge-ps-per') === 'pg', table = null;
      // careers (data/stats/players_career.json): the All years view, and every name search (owner 2026-10-18: "if i
      // type in marion barber his name should show up no matter what year or stats or position im filtering")
      let career = null, careerP = null, seasonRows = [], lastMode = '', seasonSub = '';
      const note = sec.querySelector('.ps-searchnote');
      const term = () => q.value.trim().toLowerCase();
      // a team code ("dal") still filters the picked season by team, as before
      const searching = () => career !== false && term().length >= 2 && !Object.keys(TEAMS).some(t => t.toLowerCase() === term());
      const view = () => searching() || selS.value === 'all' ? 'career' : 'season';
      const curPos = () => searching() ? 'All' : pos;
      const toRows = d => d.rows.map(v => { const r = Object.fromEntries(d.cols.map((c, i) => [c, v[i]])); r._g = groupOf(r.pos); return r; });
      // no careers file (an older build): searches filter the picked season, as before
      // search results in priority order (owner 2026-10-18: "active players first, then most prolific"): playing this
      // season, then career games (every position has them; fantasy points would bury linemen and defenders), then
      // career fantasy points. The Seasons column carries that order while searching; tapping a header re-sorts.
      const RELSPAN = Object.assign({}, SPAN, { first: 'desc', title: 'Search order: active players first, then most career games',
        value: r => (IX && r.season === IX.current ? 1e7 : 0) + (r.games || 0) * 1e3 + Math.min(999, Math.max(0, r._fp || 0) / 10) });
      const loadCareer = () => careerP || (careerP = NFLE.load('data/stats/players_career.json').then(d => { career = toRows(d); score(career); return career; })
        .catch(() => { career = false; if (table) draw(true); return null; }));
      let custom = (() => { try { return JSON.parse(store('nfledge-ps-custom') || 'null') || ['age', 'draft', 'apy']; } catch (e) { return ['age', 'draft', 'apy']; } })();
      if (!DEFAULTS[pos]) pos = 'QB';
      selP.value = pos;
      const col = (a, slot) => ({
        key: slot == null ? a.key : `c${slot}_${a ? a.key : ''}`, label: a ? a.label : '', title: a ? a.title : '', num: !a || a.f !== 's',
        first: a ? a.first : 'desc', headHtml: slot == null ? null : pickHtml(slot, a && a.key), cls: slot == null ? '' : 'ps-custom',
        value: r => { if (!a) return null; const v = a.fn(r); return per && a.count && typeof v === 'number' ? div(v, r.games) : v; },
        html: r => { if (!a) return ''; const v = a.fn(r); return fmt[per && a.count && a.f === 'i' ? 'd1' : a.f](per && a.count && typeof v === 'number' ? div(v, r.games) : v); },
      });
      const columns = () => [
        { key: 'name', label: 'Player', stick: true, first: 'asc', value: r => r.name,
          html: r => NFLE.ui.player({ name: r.name, pos: r.pos, grp: groupOf(r.pos), team: r.team, espn: r.espn }, TEAMS) },
        ...(view() === 'career' ? [searching() ? RELSPAN : SPAN] : []),
        ...DEFAULTS[curPos()].map(k => col(BY[k])),
        ...custom.map((k, i) => col(BY[k] || null, i)),
      ];
      const score = (all) => {
        const w = (NFLE.weights && NFLE.weights()) || HALF;
        all.forEach(r => {
          r._fp = (r.passing_yards || 0) * (w.pass_yd || 0) + (r.passing_tds || 0) * (w.pass_td || 0) + (r.passing_interceptions || 0) * (w.interception || 0)
            + (r.rushing_yards || 0) * (w.rush_yd || 0) + (r.rushing_tds || 0) * (w.rush_td || 0) + (r.receptions || 0) * (w.reception || 0)
            + (r.receiving_yards || 0) * (w.rec_yd || 0) + (r.receiving_tds || 0) * (w.rec_td || 0) + (r.fumbles_lost_total || 0) * (w.fumble_lost || 0)
            + (r.pos === 'TE' ? (r.receptions || 0) * (w.te_bonus || 0) : 0)
            // IDP (defenders; owner 2026-10-18): the scoring's idp_* weights
            + (r.def_tackles_solo || 0) * (w.idp_tkl_solo || 0) + (r.def_tackle_assists || 0) * (w.idp_tkl_ast || 0)
            + (r.def_tackles_for_loss || 0) * (w.idp_tkl_loss || 0) + (r.def_sacks || 0) * (w.idp_sack || 0) + (r.def_qb_hits || 0) * (w.idp_qb_hit || 0)
            + (r.def_interceptions || 0) * (w.idp_int || 0) + (r.def_pass_defended || 0) * (w.idp_pass_def || 0) + (r.def_fumbles_forced || 0) * (w.idp_ff || 0)
            + (r.def_fum_rec || 0) * (w.idp_fum_rec || 0) + (r.def_tds || 0) * (w.idp_def_td || 0) + (r.def_safeties || 0) * (w.idp_safe || 0)
            + (r.def_blocks || 0) * (w.idp_blk_kick || 0);
        });
        const byG = {};
        all.forEach(r => (byG[r._g] = byG[r._g] || []).push(r));
        Object.values(byG).forEach(g => g.sort((a, b) => b._fp - a._fp).forEach((r, i) => { r._rank = r._fp > 0 ? i + 1 : null; }));
      };
      // a name search: every player whose name has the words (any order), all positions, all years; else the filters
      const rows = () => {
        const t = term(), words = t.split(/\s+/).filter(Boolean);
        if (searching()) return (career || []).filter(r => { const n = (r.name || '').toLowerCase(); return words.every(x => n.includes(x)); });
        all = view() === 'career' && career ? career : seasonRows;
        return all.filter(r => (pos === 'All' || r._g === pos) && (!t || (r.name || '').toLowerCase().includes(t) || (r.team || '').toLowerCase() === t));
      };
      const draw = (resort) => {
        if (view() === 'career' && career === null) { sub.textContent = 'Loading every season\u2026'; loadCareer().then(() => draw(true)); return; }
        sec.querySelectorAll('.ps-per button').forEach(b => b.classList.toggle('on', (b.dataset.v === 'pg') === per));
        const srch = searching();
        note.hidden = !srch;
        if (srch) note.innerHTML = `Searching every season and position for <b>${esc(q.value.trim())}</b>, career totals. <button type="button" class="linkish ps-clear">Clear</button> to go back to ${esc(selS.value === 'all' ? 'all years' : selS.value)}, ${esc(pos === 'All' ? 'all positions' : pos)}.`;
        sec.querySelectorAll('.ps-season, .ps-pos, .ps-type').forEach(x => x.classList.toggle('ps-paused', srch));
        sub.textContent = view() === 'season' ? seasonSub : srch ? 'Every season and position' : `All years, ${IX ? IX.seasons[0] : ''}-${IX ? IX.current : ''} regular season: ${career.length.toLocaleString()} players`;
        const mode = `${view()}|${curPos()}|${srch}`, cols = columns(), rs = rows(), sk = { key: srch ? 'span' : SORT0[curPos()], dir: 'desc' };
        if (!table) table = NFLE.Table(sec.querySelector('.ps-tbl'), { howto: true, columns: cols, rows: rs, sort: sk, cls: 'tiles',
          rowClass: () => 'teamrow', rowAttrs: r => `${NFLE.ui.tileStyle(TEAMS, r.team)}${/^\d\d-\d{7}$/.test(r.pid) ? ` data-open-pid="${esc(r.pid)}"` : ''}` });
        else { table.setColumns(cols); table.update(rs); if (resort || mode !== lastMode) table.setSort(sk); }
        lastMode = mode;
      };
      sec.addEventListener('click', e => { if (e.target.closest('.ps-clear')) { q.value = ''; draw(true); } });
      // Custom-column sort buttons: the table ignores clicks on header controls, so they sort it themselves
      // (first tap = the stat's natural direction, the next flips it).
      sec.addEventListener('click', e => {
        const b = e.target.closest('.ps-sort'); if (!b || !table) return;
        const a = BY[custom[+b.dataset.slot]]; if (!a) return;
        const key = `c${b.dataset.slot}_${a.key}`, cur = table.getSort();
        table.setSort({ key, dir: cur && cur.key === key ? (cur.dir === 'asc' ? 'desc' : 'asc') : (a.first || 'desc') });
      });
      // One listener for every column picker: the table redraws its header on each sort and clones it for the phone
      // header strip, so handlers set on the pickers themselves were lost after the first sort.
      sec.addEventListener('change', e => {
        const s = e.target.closest('.ps-pick'); if (!s) return;
        custom[+s.dataset.slot] = s.value; store('nfledge-ps-custom', JSON.stringify(custom)); draw(false);
      });
      // Regular season / Playoffs (owner 2026-10-14): separate files, never mixed (players_<season>_post.json)
      let stype = 'reg', IX = null;
      const typeBtns = () => sec.querySelectorAll('.ps-type button').forEach(b => {
        const has = b.dataset.t === 'reg' || (selS.value !== 'all' && IX && (IX.post || []).includes(+selS.value));
        b.disabled = !has; b.title = has ? '' : 'No playoff games that season'; b.classList.toggle('on', b.dataset.t === stype);
      });
      const load = s => {
        if (s === 'all') { stype = 'reg'; typeBtns(); return loadCareer().then(() => draw(true)); }  // careers: regular season only
        s = +s;
        if (stype === 'post' && !(IX && (IX.post || []).includes(s))) stype = 'reg'; typeBtns();
        return NFLE.load(`data/stats/players_${s}${stype === 'post' ? '_post' : ''}.json`).then(d => {
        seasonRows = toRows(d);
        score(seasonRows);
        seasonSub = `${s} ${stype === 'post' ? 'playoffs' : 'regular season'}: ${seasonRows.length.toLocaleString()} players`;
        draw(true);
      }).catch(e => { console.error('[stats]', e); sub.textContent = 'No player stats for that season.'; }); };
      sec.querySelector('.ps-type').addEventListener('click', e => { const b = e.target.closest('[data-t]'); if (b && !b.disabled) { stype = b.dataset.t; load(selS.value); } });
      selP.onchange = () => { pos = selP.value; store('nfledge-ps-pos', pos); draw(true); };
      sec.querySelector('.ps-per').addEventListener('click', e => { const b = e.target.closest('[data-v]'); if (b) { per = b.dataset.v === 'pg'; store('nfledge-ps-per', per ? 'pg' : 'tot'); draw(false); } });
      // the first search letters fetch the careers; search on / off swaps the columns
      q.oninput = () => { if (table) draw(false); };
      // phones: bring the box to the top so the matches show between it and the keyboard
      q.addEventListener('focus', () => { if (innerWidth <= 640) setTimeout(() => scrollTo({ top: q.getBoundingClientRect().top + scrollY - 12, behavior: 'smooth' }), 250); });
      document.addEventListener('nfle-scoring', () => { score(seasonRows); if (career) score(career); if (table) draw(false); });
      NFLE.load('data/stats/index.json').then(ix => {
        IX = ix;
        const want = pageSeason() && ix.seasons.includes(pageSeason()) ? pageSeason() : ix.current;
        selS.innerHTML = (ix.career ? '<option value="all">All years</option>' : '') + [...ix.seasons].reverse().map(s => `<option value="${s}"${s === want ? ' selected' : ''}>${s}</option>`).join('');
        selS.onchange = () => load(selS.value);
        load(want);
      }).catch(() => { sub.textContent = 'Player stats are not available on this page.'; });
    },
  };
})();
