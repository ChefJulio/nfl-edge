// League (owner 2026-10-15): your real fantasy league with NFL Edge's projections. Import, don't host: Sleeper's public
// API (no login, CORS open) by username or league id, and public ESPN leagues by league id (private ESPN leagues
// need login cookies a browser won't send cross-site; Yahoo needs OAuth: both need a server we don't have).
// Each platform is read into one shape (adapters below), then: your lineup vs the best one by our projections under
// YOUR league's scoring, this week's matchup with a win chance, and the best unrostered players. Player ids map to
// ours through data/fantasy_ids.json (tools/fantasy_ids_build.py). The connection is saved on this device only.
(() => {
  const NFLE = window.NFLE, esc = NFLE.esc;
  const LS = 'nfledge-league';
  const f1 = v => v == null || isNaN(v) ? '' : (Math.round(v * 10) / 10).toFixed(1);
  const pct = v => `${Math.round(100 * v)}%`;
  const UA = {};  // browsers set their own User-Agent; nothing to send
  const getJSON = url => fetch(url, UA).then(r => r.ok ? r.json() : Promise.reject(new Error(`${r.status}`)));

  // ---- scoring: platform settings -> our stat keys (pass_yd, pass_td, interception, rush_yd, rush_td, reception,
  // rec_yd, rec_td, fumble_lost, te_bonus). Bonuses (100-yard games, first downs, 2-pt tries) aren't projected.
  const SLEEPER_SCORE = { pass_yd: 'pass_yd', pass_td: 'pass_td', pass_int: 'interception', rush_yd: 'rush_yd', rush_td: 'rush_td',
                          rec: 'reception', rec_yd: 'rec_yd', rec_td: 'rec_td', fum_lost: 'fumble_lost', bonus_rec_te: 'te_bonus' };
  const ESPN_STAT = { 3: 'pass_yd', 4: 'pass_td', 20: 'interception', 24: 'rush_yd', 25: 'rush_td', 53: 'reception', 42: 'rec_yd',
                      43: 'rec_td', 72: 'fumble_lost' };
  const ESPN_SLOT = { 0: 'QB', 2: 'RB', 4: 'WR', 6: 'TE', 23: 'FLEX', 7: 'SUPER_FLEX', 16: 'DEF', 17: 'K' };
  const ESPN_POS = { 1: 'QB', 2: 'RB', 3: 'WR', 4: 'TE', 5: 'K', 16: 'DEF' };
  // Kickers (data/kdst.json, nfledge/kickers.py): expected made / missed per distance band + PATs, scored here with the
  // league's own kicking settings. Band order: 0_19, 20_29, 30_39, 40_49, 50_59, 60_ (made, then missed), xpm, xpmiss.
  const KB = ['0_19', '20_29', '30_39', '40_49', '50_59', '60_'];
  const KMID = { '0_19': 18, '20_29': 25, '30_39': 35, '40_49': 45, '50_59': 54, '60_': 61 };  // typical distance, for per-yard scoring
  const sleeperK = sc => {
    const g = k => +(sc[k] || 0), w = {};
    const band = { '0_19': '0_19', '20_29': '20_29', '30_39': '30_39', '40_49': '40_49' };
    KB.forEach(b => {
      const big = b === '50_59' ? (sc.fgm_50_59 != null ? g('fgm_50_59') : g('fgm_50p')) : b === '60_' ? (sc.fgm_60p != null ? g('fgm_60p') : g('fgm_50p')) : g(`fgm_${band[b]}`);
      const bigMiss = b === '50_59' || b === '60_' ? g('fgmiss_50p') : g(`fgmiss_${band[b]}`);
      w[`fgm_${b}`] = g('fgm') + big + g('fgm_yds') * KMID[b] + g('fgm_yds_over_30') * Math.max(0, KMID[b] - 30);
      w[`fgmiss_${b}`] = g('fgmiss') + bigMiss;
    });
    w.xpm = g('xpm'); w.xpmiss = g('xpmiss');
    return w;
  };
  // ESPN stat ids: 80 made <40, 77 made 40-49, 74 made 50+, 198 made 50-59, 201 made 60+, 85 missed FG, 86 PAT made, 88 PAT missed
  const espnK = items => {
    const pt = id => { const it = items.find(x => x.statId === id); return it ? (it.pointsOverrides && it.pointsOverrides['17'] != null ? it.pointsOverrides['17'] : it.points) : 0; };
    const w = {};
    KB.forEach(b => {
      const made = ['0_19', '20_29', '30_39'].includes(b) ? pt(80) : b === '40_49' ? pt(77)
        : b === '50_59' ? (items.some(x => x.statId === 198) ? pt(198) : pt(74)) : (items.some(x => x.statId === 201) ? pt(201) : pt(74));
      w[`fgm_${b}`] = made; w[`fgmiss_${b}`] = pt(85);
    });
    w.xpm = pt(86); w.xpmiss = pt(88);
    return w;
  };
  // D/ST (data/kdst.json, nfledge/defenses.py): expected stats + points / yards allowed as normal(mu, sd); a league's
  // tiers come from those distributions (integer outcomes, below 0 counted as 0), per-point / per-yard from the means.
  const { dstScore } = NFLE.kdst;  // shared with Rankings (shell.js)
  const sleeperD = sc => {
    const g = k => +(sc[k] || 0);
    const pa = [[0, 0, 'pts_allow_0'], [1, 6, 'pts_allow_1_6'], [7, 13, 'pts_allow_7_13'], [14, 20, 'pts_allow_14_20'], [21, 27, 'pts_allow_21_27'],
                [28, 34, 'pts_allow_28_34'], [35, Infinity, 'pts_allow_35p']];
    const ya = [[0, 99, 'yds_allow_0_100'], [100, 199, 'yds_allow_100_199'], [200, 299, 'yds_allow_200_299'], [300, 349, 'yds_allow_300_349'],
                [350, 399, 'yds_allow_350_399'], [400, 449, 'yds_allow_400_449'], [450, 499, 'yds_allow_450_499'], [500, 549, 'yds_allow_500_549'],
                [550, Infinity, 'yds_allow_550p']];
    return { sack: g('sack'), int: g('int'), fum_rec: g('fum_rec'), ff: g('ff'), def_td: g('def_td'), st_td: g('def_st_td') || g('st_td'),
             safe: g('safe'), blk: g('blk_kick'), pass_def: g('def_pass_def'), tkl_loss: g('tkl_loss'), forced_punts: g('def_forced_punts'),
             def_2pt: g('def_2pt'), pts_allow: g('pts_allow'), yds_allow: g('yds_allow'),
             pa_tiers: pa.filter(t => g(t[2])).map(([lo, hi, k]) => [lo, hi, g(k)]), ya_tiers: ya.filter(t => g(t[2])).map(([lo, hi, k]) => [lo, hi, g(k)]) };
  };
  // ESPN D/ST stat ids (values usually set as overrides for the D/ST slot, '16'): 99 sack, 95 INT, 96 fumble recovered,
  // 106 forced fumble, 97 blocked kick, 98 safety, 113 pass defended, 103 / 104 INT / fumble return TD, 101 / 102 / 93
  // kick / punt / blocked-kick return TD, 206 2-pt return, 120 per point allowed, 127 per yard allowed, tiers 89-92 / 121-125, 128-136
  const espnD = items => {
    const pt = id => { const it = items.find(x => x.statId === id); return it ? (it.pointsOverrides && it.pointsOverrides['16'] != null ? it.pointsOverrides['16'] : it.points) : 0; };
    const avg = ids => ids.reduce((a, i) => a + pt(i), 0) / ids.length;
    const pa = [[0, 0, 89], [1, 6, 90], [7, 13, 91], [14, 17, 92], [18, 21, 121], [22, 27, 122], [28, 34, 123], [35, 45, 124], [46, Infinity, 125]];
    const ya = [[0, 99, 128], [100, 199, 129], [200, 299, 130], [300, 349, 131], [350, 399, 132], [400, 449, 133], [450, 499, 134], [500, 549, 135], [550, Infinity, 136]];
    return { sack: pt(99), int: pt(95), fum_rec: pt(96), ff: pt(106), def_td: avg([103, 104]), st_td: avg([101, 102, 93]), safe: pt(98), blk: pt(97),
             pass_def: pt(113), tkl_loss: 0, forced_punts: 0, def_2pt: pt(206), pts_allow: pt(120), yds_allow: pt(127),
             pa_tiers: pa.filter(t => pt(t[2])).map(([lo, hi, i]) => [lo, hi, pt(i)]), ya_tiers: ya.filter(t => pt(t[2])).map(([lo, hi, i]) => [lo, hi, pt(i)]) };
  };
  // ESPN D/ST player ids are -16000 - ESPN team id
  const ESPN_TEAM = { 1: 'ATL', 2: 'BUF', 3: 'CHI', 4: 'CIN', 5: 'CLE', 6: 'DAL', 7: 'DEN', 8: 'DET', 9: 'GB', 10: 'TEN', 11: 'IND', 12: 'KC', 13: 'LV',
                      14: 'LA', 15: 'MIA', 16: 'MIN', 17: 'NE', 18: 'NO', 19: 'NYG', 20: 'NYJ', 21: 'PHI', 22: 'ARI', 23: 'PIT', 24: 'LAC', 25: 'SF',
                      26: 'SEA', 27: 'TB', 28: 'WAS', 29: 'CAR', 30: 'JAX', 33: 'BAL', 34: 'HOU' };
  const dstTeam = x => { const n = +x; if (n <= -16001 && n >= -16034) return ESPN_TEAM[-16000 - n] || null;
    if (/^[A-Z]{2,3}$/.test(x)) return ({ LAR: 'LA', WSH: 'WAS', JAC: 'JAX' })[x] || x; return null; };
  const SLEEPER_USED = new Set([...Object.keys(SLEEPER_SCORE), 'fgm', 'fgmiss', 'fgm_yds', 'fgm_yds_over_30', 'xpm', 'xpmiss',
    'fgm_0_19', 'fgm_20_29', 'fgm_30_39', 'fgm_40_49', 'fgm_50p', 'fgm_50_59', 'fgm_60p', 'fgmiss_0_19', 'fgmiss_20_29', 'fgmiss_30_39',
    'fgmiss_40_49', 'fgmiss_50p', 'sack', 'int', 'fum_rec', 'ff', 'def_td', 'def_st_td', 'st_td', 'safe', 'blk_kick', 'def_pass_def', 'tkl_loss',
    'def_forced_punts', 'def_2pt', 'pts_allow', 'yds_allow', 'pts_allow_0', 'pts_allow_1_6', 'pts_allow_7_13', 'pts_allow_14_20',
    'pts_allow_21_27', 'pts_allow_28_34', 'pts_allow_35p', 'yds_allow_0_100', 'yds_allow_100_199', 'yds_allow_200_299', 'yds_allow_300_349',
    'yds_allow_350_399', 'yds_allow_400_449', 'yds_allow_450_499', 'yds_allow_500_549', 'yds_allow_550p']);
  const ESPN_USED = new Set([3, 4, 20, 24, 25, 53, 42, 43, 72, 74, 77, 80, 85, 86, 88, 198, 201, 99, 95, 96, 106, 97, 98, 113, 103, 104, 101, 102, 93,
    206, 120, 127, 89, 90, 91, 92, 121, 122, 123, 124, 125, 128, 129, 130, 131, 132, 133, 134, 135, 136]);
  const NICE = { pass_2pt: '2-pt pass', rush_2pt: '2-pt rush', rec_2pt: '2-pt catch', def_3_and_out: '3-and-outs', def_4_and_stop: '4th-down stops',
                 fum: 'fumbles', fum_rec_td: 'fumble-return TDs (player)', st_ff: 'special-teams forced fumbles', st_fum_rec: 'special-teams fumble recoveries',
                 def_st_ff: 'D/ST special-teams forced fumbles', def_st_fum_rec: 'D/ST special-teams fumble recoveries', bonus_rec_te: 'TE catch bonus',
                 19: '2-pt pass', 26: '2-pt rush', 44: '2-pt catch', 63: 'fumble-recovery TDs (player)', 209: 'fumble recoveries (player)' };
  const ELIG = { QB: ['QB'], RB: ['RB'], WR: ['WR'], TE: ['TE'], FLEX: ['RB', 'WR', 'TE'], WRRB_FLEX: ['RB', 'WR'], REC_FLEX: ['WR', 'TE'],
                 SUPER_FLEX: ['QB', 'RB', 'WR', 'TE'], DEF: ['DEF'], K: ['K'] };

  // ---- adapters: -> { platform, id, name, season, week, slots, scoring, teams: [{ id, name, owner, ext: [ids], starters }],
  //                   matchup(teamId) -> { opp, points: { id: pts } } }
  const sleeper = {
    async leaguesFor(username, season) {
      const u = await getJSON(`https://api.sleeper.app/v1/user/${encodeURIComponent(username)}`);
      if (!u || !u.user_id) throw new Error('No Sleeper user by that name');
      const ls = await getJSON(`https://api.sleeper.app/v1/user/${u.user_id}/leagues/nfl/${season}`);
      return { user: u.user_id, leagues: (ls || []).map(l => ({ id: l.league_id, name: l.name })) };
    },
    async load(id) {
      const B = 'https://api.sleeper.app/v1';
      const [lg, users, rosters, state] = await Promise.all([getJSON(`${B}/league/${id}`), getJSON(`${B}/league/${id}/users`),
        getJSON(`${B}/league/${id}/rosters`), getJSON(`${B}/state/nfl`)]);
      const week = state.display_week || state.week;
      const mu = await getJSON(`${B}/league/${id}/matchups/${week}`).catch(() => []);
      const uName = Object.fromEntries((users || []).map(u => [u.user_id, (u.metadata && u.metadata.team_name) || u.display_name]));
      const scoring = {};
      Object.entries(SLEEPER_SCORE).forEach(([k, ours]) => { scoring[ours] = +((lg.scoring_settings || {})[k] || 0); });
      const byRoster = Object.fromEntries((mu || []).map(m => [m.roster_id, m]));
      const kw = sleeperK(lg.scoring_settings || {}), dw = sleeperD(lg.scoring_settings || {});
      const unmodeled = Object.entries(lg.scoring_settings || {}).filter(([k, v]) => +v && !SLEEPER_USED.has(k)).map(([k]) => NICE[k] || k.replace(/_/g, ' '));
      return {
        platform: 'sleeper', id, name: lg.name, season: lg.season, week, kw, dw, unmodeled,
        slots: (lg.roster_positions || []).filter(s => !['BN', 'IR', 'TAXI'].includes(s)),
        size: (lg.roster_positions || []).filter(s => !['IR', 'TAXI'].includes(s)).length,  // starters + bench
        scoring,
        teams: (rosters || []).map(r => { const st = r.settings || {};
          return { id: String(r.roster_id), owner: r.owner_id, name: uName[r.owner_id] || `Team ${r.roster_id}`,
                   ext: (r.players || []).map(String), starters: (r.starters || []).map(String),
                   ir: [...(r.reserve || []), ...(r.taxi || [])].map(String),  // not on the bench count
                   waiver: st.waiver_position || null, faab: lg.settings && lg.settings.waiver_type === 2 ? (lg.settings.waiver_budget || 0) - (st.waiver_budget_used || 0) : null,
                   record: { w: st.wins || 0, l: st.losses || 0, t: st.ties || 0, pf: (st.fpts || 0) + (st.fpts_decimal || 0) / 100 } }; }),
        matchup(teamId) {
          const me = byRoster[teamId];
          if (!me) return null;
          const opp = (mu || []).find(m => m.matchup_id === me.matchup_id && String(m.roster_id) !== String(teamId));
          return opp ? { opp: String(opp.roster_id), points: { [teamId]: me.points || 0, [opp.roster_id]: opp.points || 0 },
                         starters: { [teamId]: (me.starters || []).map(String), [opp.roster_id]: (opp.starters || []).map(String) } } : null;
        },
        defName: t => t,  // Sleeper team defenses are the team code ("MIN")
      };
    },
  };
  // ESPN public leagues (UNTESTED until a public league id is supplied: built from ESPN's documented-by-use v3 API)
  const espn = {
    async load(id, season) {
      const v = ['mTeam', 'mRoster', 'mSettings', 'mMatchupScore'].map(x => `view=${x}`).join('&');
      const d = await getJSON(`https://lm-api-reads.fantasy.espn.com/apis/v3/games/ffl/seasons/${season}/segments/0/leagues/${id}?${v}`)
        .catch(e => { throw new Error(String(e.message) === '401' ? 'That ESPN league is private (ESPN league settings: make it viewable to the public)' : e.message); });
      const st = d.settings || {}, week = d.scoringPeriodId;
      const slots = [];
      Object.entries((st.rosterSettings || {}).lineupSlotCounts || {}).forEach(([sid, n]) => { const s = ESPN_SLOT[sid]; if (s) for (let i = 0; i < n; i++) slots.push(s); });
      const scoring = { te_bonus: 0 };
      ((st.scoringSettings || {}).scoringItems || []).forEach(it => {
        const k = ESPN_STAT[it.statId]; if (!k) return;
        scoring[k] = it.points;
        if (k === 'reception' && it.pointsOverrides && it.pointsOverrides['6'] != null) scoring.te_bonus = it.pointsOverrides['6'] - it.points;  // TE premium
      });
      const items = (st.scoringSettings || {}).scoringItems || [];
      const kw = espnK(items), dw = espnD(items);
      const unmodeled = items.filter(it => !ESPN_USED.has(it.statId) && (it.points || Object.values(it.pointsOverrides || {}).some(Boolean)))
        .map(it => NICE[it.statId] || `ESPN stat ${it.statId}`);
      const names = {};
      const teams = (d.teams || []).map(t => {
        const entries = ((t.roster || {}).entries || []);
        entries.forEach(e => { const p = (e.playerPoolEntry || {}).player || {}; names[String(e.playerId)] = { name: p.fullName, pos: ESPN_POS[p.defaultPositionId] }; });
        // starters in the league's slot order (ESPN lists a roster in no particular order)
        const left = entries.filter(e => ![20, 21].includes(e.lineupSlotId));
        const starters = slots.map(sl => { const i = left.findIndex(e => ESPN_SLOT[e.lineupSlotId] === sl); return i < 0 ? '' : String(left.splice(i, 1)[0].playerId); });
        const ov = ((t.record || {}).overall) || {};
        return { id: String(t.id), owner: (t.owners || [])[0], name: t.name || `${t.location || ''} ${t.nickname || ''}`.trim(),
                 ext: entries.map(e => String(e.playerId)), starters, ir: entries.filter(e => e.lineupSlotId === 21).map(e => String(e.playerId)),
                 waiver: t.waiverRank || null, faab: (st.acquisitionSettings || {}).isUsingAcquisitionBudget ? ((st.acquisitionSettings || {}).acquisitionBudget || 0) - ((t.transactionCounter || {}).acquisitionBudgetSpent || 0) : null,
                 record: { w: ov.wins || 0, l: ov.losses || 0, t: ov.ties || 0, pf: ov.pointsFor || 0 } };
      });
      const games = (d.schedule || []).filter(g => g.matchupPeriodId === week || (g.home && g.home.pointsByScoringPeriod && g.home.pointsByScoringPeriod[week] != null));
      return {
        platform: 'espn', id, name: st.name, season, week, slots, scoring, kw, dw, unmodeled, teams, espnNames: names,
        size: Object.entries((st.rosterSettings || {}).lineupSlotCounts || {}).filter(([sid]) => +sid !== 21).reduce((t, [, n]) => t + n, 0),
        matchup(teamId) {
          const g = games.find(x => String((x.home || {}).teamId) === teamId || String((x.away || {}).teamId) === teamId);
          if (!g) return null;
          const home = String(g.home.teamId), away = String((g.away || {}).teamId), opp = home === teamId ? away : home;
          const pts = s => (s && (s.totalPointsLive ?? (s.pointsByScoringPeriod || {})[week] ?? s.totalPoints)) || 0;
          return { opp, points: { [home]: pts(g.home), [away]: pts(g.away) }, starters: null };
        },
        defName: x => (names[x] || {}).name || x,
      };
    },
  };

  // Always the CURRENT week (index.json), whatever page the tab is opened from: a real league is live now, and an
  // archived or lookahead page's week would project today's rosters with another week's numbers (owner 2026-10-15:
  // opened from 2025 wk 18, Mahomes et al. showed "no projection").
  NFLE.areas.league = { mount(sec) {
    const cur = NFLE.week().then(D => (D && !D.archive && !D.lookahead) ? D : NFLE.load('index.json'));
    Promise.all([cur, NFLE.load('data/fantasy_ids.json'), NFLE.load('data/kdst.json').catch(() => null)]).then(([D, IDS, KD]) => build(sec, D, IDS, KD));
  } };

  function build(sec, D, IDS, KD) {
    const KBY = {};  // kicker gsis -> { team, name, w: [[week, implied, line]] }
    if (KD && KD.k) Object.entries(KD.k).forEach(([team, o]) => { KBY[o.pid] = Object.assign({ team }, o); });
    const kScore = line => (KD ? KD.k_keys : []).reduce((t, key, i) => t + (line[i] || 0) * ((L.kw || {})[key] || 0), 0);
    const dWeek = (team, wk) => { const o = KD && KD.dst && KD.dst[team]; const e = o && o.w.find(z => z[0] === wk);
      return e ? { pts: dstScore(Object.fromEntries(KD.d_keys.map((k, i) => [k, e[3][i]])), L.dw || {}), opp: e[1], home: e[2] } : null; };
    const kWeek = (g, wk) => { const o = KBY[g]; const e = o && o.w.find(z => z[0] === wk); return e ? kScore(e[2]) : null; };
    const TEAMS = D.teams || {}, KEYS = D.score.keys;
    let saved = null;
    try { saved = JSON.parse(localStorage.getItem(LS) || 'null'); } catch (e) { /* none */ }
    let L = null, mine = null, ROS = null, view = 'lineup';
    const save = () => { try { localStorage.setItem(LS, JSON.stringify(saved)); } catch (e) { /* private mode */ } };
    const season = new Date().getMonth() < 2 ? new Date().getFullYear() - 1 : new Date().getFullYear();

    // ---- player lookup: platform id -> our player (projection row when we have one) --------------------------------
    const pts = (c, w, pos) => (c || []).reduce((t, v, i) => t + v * (w[KEYS[i]] || 0), 0) + (pos === 'TE' ? (c || [])[5] * (w.te_bonus || 0) : 0);
    const gsisOf = x => (IDS[L.platform] || {})[x];
    const player = x => {
      const g = gsisOf(x);
      if (g) return fromPid(g, x);
      // a team defense (projected), or an unmapped id
      const dt = dstTeam(x);
      if (dt) {
        const v = KD ? dWeek(dt, KD.from) : null;
        return { ext: x, name: `${(TEAMS[dt] || {}).nick || dt} D/ST`, pos: 'DEF', team: dt, proj: v ? v.pts : null, pa: v ? 1 : 0, exp: v ? v.pts : null, locked: started(dt),
                 sd: 5.5, inactive: 0, opp: v ? v.opp : '', home: v ? (v.home ? 'vs' : '@') : '', why: v ? '' : 'on bye' };
      }
      const e = L.espnNames && L.espnNames[x], dst = /^[A-Z]{2,3}$/.test(x);
      return { ext: x, name: e ? e.name : (dst ? `${(TEAMS[x] || {}).nick || x} D/ST` : `Player ${x}`), pos: e ? e.pos : (dst ? 'DEF' : ''),
               team: dst ? x : '', proj: null, exp: null };
    };
    // his game has kicked off this week: his lineup spot can't change (owner 2026-10-17: Sutton, locked after Thursday's
    // game, was suggested off the bench)
    const started = t => { const k = t && NFLE.fmt.kickoff(D.games, t); return k != null && Date.now() >= k; };
    const fromPid = (g, x) => {
      const p = D.players[g], nm = IDS.names[g];
      if (!p && KBY[g]) {  // a kicker: our kicking projection under this league's kicking settings
        const o = KBY[g], proj = kWeek(g, KD.from);
        return { ext: x, pid: g, name: o.name, pos: 'K', team: o.team, proj, pa: proj == null ? 0 : 1, exp: proj, sd: 4.3, inactive: 0, locked: started(o.team),
                 why: proj == null ? 'on bye' : '' };
      }
      if (!p) return { ext: x, pid: g, name: nm ? nm[0] : g, pos: nm ? nm[1] : '', team: nm ? nm[2] : '', proj: null, exp: null, why: 'no projection this week (bye, out, or not on our board)' };
      const proj = pts(p.sc.pj, L.scoring, p.pos), pa = 1 - (p.inactive || 0);
      // sd from his range (10th-90th percentile spans 2.56 sd), rescaled to this league's scoring
      const base = pts(p.sc.pj, D.score.built, p.pos), r = base > 0.3 ? proj / base : 1;
      const sd = ((p.q[4] - p.q[0]) * r) / 2.563;
      // two worlds for a teammate of an uncertain player, in this league's scoring: up to two such teammates, biggest
      // swing first (owner 2026-10-16: Coleman's projection assumes DJ Moore sits, not just Palmer)
      const conds = [p.cond, p.cond2].filter(Boolean).map(c => ({ name: c[0], pid: c[1], pSit: c[2], plays: c[3] * r, sits: c[4] * r }));
      return { ext: x, pid: g, name: p.name, pos: p.pos, team: p.team, photo: p.photo, espn: p.espn, status: p.status, opp: p.opp, home: p.home,
               proj, pa, exp: proj * pa, sd, inactive: p.inactive || 0, conds, locked: started(p.team) };
    };

    // "DJ Moore" -> "Moore", "Chris Rodriguez Jr." -> "Rodriguez" (suffixes skipped)
    const last = n => { const w = String(n || '').split(' ').filter(x => !/^(jr\.?|sr\.?|ii|iii|iv|v)$/i.test(x)); return w[w.length - 1] || n; };

    // the uncertain teammate's other world as a change to the shown projection (owner 2026-10-17: changes add up when
    // two teammates are uncertain, two totals don't); '' when it rounds to nothing
    const condTxt = c => { const d = c.pSit >= 0.5 ? c.plays - c.sits : c.sits - c.plays;
      return Math.abs(d) < 0.05 ? '' : `${NFLE.fmt.signed1(d)} if ${esc(last(c.name))} ${c.pSit >= 0.5 ? 'plays' : 'sits'}`; };
    // "Questionable (ESPN) (DL)" -> "Questionable per ESPN; practice: DNP, limited"
    const statusWords = st => {
      const m = String(st || '').match(/^(.*?)\s*\(([DLF]+)\)\s*$/), des = (m ? m[1] : String(st || '')).trim().replace(/\s*\(ESPN\)/, ' per ESPN');
      const days = m ? [...m[2]].map(c => ({ D: 'DNP', L: 'limited', F: 'full' })[c]).join(', ') : '';
      return [des, days && `practice: ${days}`].filter(Boolean).join('; ') || 'injury report';
    };
    // ---- best lineup: fixed slots first (scarcest eligibility), then flex / superflex, by expected points -----------
    // current: the lineup as set, aligned with slots. A player whose game has kicked off is locked: a starter keeps his
    // slot, a bench player can't come in. Slots fill scarcest first; rows come back in the league's slot order (owner
    // 2026-10-17: FLEX listed after D/ST was jarring).
    const optimize = (players, slots, current = []) => {
      const res = slots.map(() => null), used = new Set();
      current.forEach((p, i) => { if (p && p.locked && i < slots.length) { res[i] = p; used.add(p.ext); } });
      const pool = players.filter(p => p.exp != null && !p.locked && !used.has(p.ext)).sort((a, b) => b.exp - a.exp);
      const keep = current.filter(p => p && p.exp == null && ['DEF', 'K'].includes(p.pos));  // on bye / not projected: as you set them
      slots.map((s, i) => i).filter(i => !res[i]).sort((a, b) => (ELIG[slots[a]] || []).length - (ELIG[slots[b]] || []).length).forEach(i => {
        const el = ELIG[slots[i]] || [], pick = pool.find(p => !used.has(p.ext) && el.includes(p.pos))
          || keep.find(p => !used.has(p.ext) && el.includes(p.pos));
        if (pick) used.add(pick.ext);
        res[i] = pick || null;
      });
      return slots.map((s, i) => ({ slot: s, p: res[i] }));
    };
    const total = rows => rows.reduce((t, r) => t + (r.p && r.p.exp != null ? r.p.exp : 0), 0);
    // Win-chance spread, correlation-aware (INSIGHTS thread 6, {#h2h-corr}; owner 2026-10-16: "we lean towards being
    // correct"): each starter's variance (range + the chance he sits) plus, for every pair in one game, rho x s_i x s_j.
    // rho = correlation of standardized misses by position pair, teammates or opponents, fit on 2021-25 backtests
    // (tools/h2h_eval.py): a QB and his own receivers swing together, so a stack is less certain than independent sums.
    const RHO = { 'same:QB-WR': 0.244, 'same:QB-TE': 0.195, 'same:QB-RB': 0.028, 'same:RB-RB': -0.048, 'same:RB-TE': -0.034,
      'same:RB-WR': -0.022, 'same:TE-TE': -0.033, 'same:TE-WR': -0.019, 'same:WR-WR': -0.012, 'opp:QB-QB': 0.143, 'opp:QB-TE': 0.09,
      'opp:QB-WR': 0.051, 'opp:QB-RB': 0.013, 'opp:WR-WR': 0.035, 'opp:TE-WR': 0.028, 'opp:TE-TE': 0.017, 'opp:RB-RB': -0.014,
      'opp:RB-WR': 0.005, 'opp:RB-TE': 0.003 };
    const live = rows => rows.map(r => r.p).filter(p => p && p.exp != null);
    const sOf = p => Math.sqrt(p.pa * p.sd * p.sd + p.pa * (1 - p.pa) * p.proj * p.proj);
    const rhoOf = (p, q) => {
      if (!p.team || !q.team) return 0;
      const same = p.team === q.team;
      if (!same && p.opp !== q.team) return 0;  // not the same game
      return RHO[`${same ? 'same' : 'opp'}:${[p.pos, q.pos].sort().join('-')}`] || 0;
    };
    const covIn = ps => ps.reduce((t, p, i) => t + ps.slice(i + 1).reduce((u, q) => u + rhoOf(p, q) * sOf(p) * sOf(q), 0), 0);
    const covX = (as, bs) => as.reduce((t, p) => t + bs.reduce((u, q) => u + rhoOf(p, q) * sOf(p) * sOf(q), 0), 0);
    const varOf = ps => ps.reduce((t, p) => t + sOf(p) ** 2, 0) + 2 * covIn(ps);
    const spreadDiff = (a, b) => { const A = live(a), B = live(b); return Math.sqrt(Math.max(varOf(A) + varOf(B) - 2 * covX(A, B), 1e-6)); };
    const phi = z => 0.5 * (1 + Math.tanh(0.7978845608 * (z + 0.044715 * z * z * z)));

    // ---- views --------------------------------------------------------------------------------------------------
    // One row style for every table (owner 2026-10-17 audit): the slot (lineups only), the player with his chips wrapping
    // under the name inside the cell (a long chip used to push the numbers off a phone screen), the projection; the
    // chance to sit is a chip ("35% out"), and the position chip shows only where the slot doesn't already say it
    // (FLEX, bench) or there is no slot (waivers sit under a position heading, so none there either).
    const badgesOf = p => {
      const out = p.proj != null && p.inactive >= 0.05 && p.inactive < 0.99 ?  // ruled out: the O chip says it
        `<span class="lg-out${p.inactive >= 0.5 ? ' hi' : ''}" title="Chance he sits">${pct(p.inactive)} out</span>` : '';
      const conds = (p.conds || []).map(c => condTxt(c) && `<span class="lg-cond" title="${esc(`${f1(c.sits)} if ${c.name} sits, ${f1(c.plays)} if he plays`)}">${condTxt(c)}</span>`).join('');
      const lock = p.locked ? '<span class="lg-lock" title="His game has kicked off: his spot is set">locked</span>' : '';
      const inner = lock + NFLE.injTag(p.status || '') + out + conds;
      return inner ? `<div class="badges lg-badges">${inner}</div>` : '';
    };
    const row = (slot, p, extra = '', o = {}) => {
      const slotTd = o.noSlot ? '' : `<td class="lg-slot">${esc(slot)}</td>`;
      if (!p) return `<tr>${slotTd}<td colspan="2" class="muted">empty</td>${extra}</tr>`;
      const pos = o.noSlot || slot === p.pos ? '' : p.pos;
      return `<tr class="teamrow" style="${NFLE.fmt.rowStyle(TEAMS, p.team)}"${p.pid ? ` data-open-pid="${esc(p.pid)}"` : ''}>${slotTd}
        <td class="lg-who">${NFLE.ui.player({ name: p.name, pos, team: p.team, photo: p.photo, espn: p.espn, pid: p.pid,
          subHtml: p.opp ? `${esc(p.home)} ${NFLE.ui.tm(p.opp)}` : p.why ? esc(p.why) : NFLE.ui.tm(p.team), badges: badgesOf(p) }, TEAMS)}</td>
        <td class="num"><b>${p.proj != null ? f1(p.proj) : '—'}</b></td>${extra}</tr>`;
    };
    const table = (body, head = '<th>Slot</th><th>Player</th><th class="num">Proj</th>') =>
      `<div class="lg-scroll"><table class="bx tiles lg-tbl"><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table></div>`;

    // Waiver claim window (owner 2026-10-17): order resets to inverse standings Tuesday ~2am Central, claims made during
    // Tuesday process Wednesday ~2am; after that unclaimed players are free agents, first come first served, so the
    // order only matters inside that window (a player dropped later is on waivers for 24 hours: rare enough to skip).
    const claimWindow = () => {
      const p = Object.fromEntries(new Intl.DateTimeFormat('en-US', { timeZone: 'America/Chicago', weekday: 'short', hour: 'numeric', hourCycle: 'h23' })
        .formatToParts(new Date()).map(x => [x.type, x.value]));
      const h = +p.hour;
      return (p.weekday === 'Tue' && h >= 2) || (p.weekday === 'Wed' && h < 2);
    };
    // The waiver wire as information, not orders (owner 2026-10-17: close calls are the manager's judgment, e.g. a
    // backup's upside the projections can't see): the free agents who'd improve your team most, and your players
    // whose own rest-of-season projection free agents at their position beat. No add-drop pairs.
    const movesCard = () => {
      if (!ROS) { NFLE.load('data/ros.json').then(j => { ROS = j; if (view === 'lineup') draw(); }, () => {}); return '<div class="lg-mv lg-moves"><div class="muted">Checking the waiver wire…</div></div>'; }
      const { moves } = movesFor(), weeks = rosWeeks();
      const best = moves.filter(m => m.ros >= 1).slice(0, 3);
      const fa = freeAgents();
      const own = mine.ext.filter(x => !(mine.ir || []).includes(x)).map(x => ({ x, p: player(x), ros: weeks.reduce((t, k) => t + ((weekOf(x, k) || {}).exp || 0), 0) }));
      const below = own.map(o => ({ ...o, beat: fa.filter(f => f.pos === o.p.pos && f.ros > o.ros) }))
        .filter(o => o.beat.length && o.p.pos).sort((a, b) => b.beat.length - a.beat.length || a.ros - b.ros).slice(0, 4);
      const wv = mine.faab != null ? `$${mine.faab} FAAB left` : mine.waiver && claimWindow() ? `claims process Wed ~2am CT · you're #${mine.waiver} of ${L.teams.length}` : '';
      return `<div class="lg-mv lg-moves"><div class="lg-mv-h">Waiver wire${wv ? ` <span class="muted lg-wv">${wv}</span>` : ''}</div>
          <div class="lg-mv-sub">Best available for you</div>
          ${best.length ? best.map(m => `<div class="lg-mv-row"><span class="lg-mv-k good">+${Math.round(m.ros)}</span><div><b>${esc(m.add.name)}</b> <span class="muted">${esc(m.add.pos)} · ROS ${Math.round(m.add.ros)} · ${NFLE.fmt.signed1(m.wk)} this week</span></div></div>`).join('')
            : '<div class="muted">No free agent improves your team over the rest of the season by our projections.</div>'}
          ${below.length ? `<div class="lg-mv-sub">Below the waiver wire</div>${below.map(o => `<div class="lg-mv-row"><span class="lg-mv-k bad">${esc(o.p.pos)}</span><div><b>${esc(o.p.name)}</b> <span class="muted">ROS ${Math.round(o.ros)} · ${o.beat.length} free agent${o.beat.length === 1 ? '' : 's'} project more (best: ${esc(o.beat.sort((a, b) => b.ros - a.ros)[0].name)} ${Math.round(o.beat[0].ros)})</span></div></div>`).join('')}` : ''}
          <div class="muted lg-mv-f">+X = how much he'd add to your team: your best lineup each remaining week through ${ROS.through}, summed, making room with whoever costs least (one QB, TE, K and D/ST is enough; ${DEPTH_MIN} RBs and WRs stay). ROS = his own expected points. Upside the projections can't see is your call.</div></div>`;
    };
    const lineupView = () => {
      const ps = mine.ext.map(player), cur = new Set(mine.starters);
      const curStart = mine.starters.map(x => ps.find(p => p.ext === x));
      const best = optimize(ps, L.slots, curStart), bestSet = new Set(best.filter(r => r.p).map(r => r.p.ext));
      const curRows = L.slots.map((s, i) => ({ slot: s, p: ps.find(p => p.ext === mine.starters[i]) || null }));
      const gain = total(best) - total(curRows);
      // replaced starters include ones with no projection (bye, IR, out): they score 0 where they sit
      const benchIn = best.filter(r => r.p && !cur.has(r.p.ext)).map(r => r.p),
        benchOut = curRows.filter(r => r.p && !['DEF', 'K'].includes(r.p.pos) && !bestSet.has(r.p.ext)).map(r => r.p);
      // An uncertain starter (15-85% to sit) isn't a bench call midweek: lineups can change until each game kicks off,
      // so he's a "wait for the final report" with what he's worth if he plays vs the best fill-in.
      // Only when he'd start if he plays: a player who projects below the weakest fill-in even when active is simply
      // benched (Palmer 4.4 vs Coleman 7.6, 2026-10-16), not a game-time call.
      const minFill = benchIn.length ? Math.min(...benchIn.map(q => q.proj ?? 0)) : 0;
      const unsure = benchOut.filter(p => p.exp != null && p.inactive >= 0.15 && p.inactive <= 0.85 && p.proj > minFill);
      const sure = benchOut.filter(p => !unsure.includes(p));
      const fill = benchIn.slice().sort((a, b) => b.exp - a.exp);
      // Readable moves (owner 2026-10-16): who comes in, who goes out and why, then one card per game-time call with
      // its two outcomes on their own lines.
      const why = p => p.exp == null ? 'not projected (bye, IR or out)'
        : p.inactive >= 0.15 ? `${pct(p.inactive)} to sit · ${f1(p.proj)} if he plays · ${esc(statusWords(p.status))}`
        : `projects ${f1(p.exp)}`;
      const ifLines = p => (p.conds || []).map(condTxt).filter(Boolean);
      const nm = p => `<b>${esc(p.name)}</b>`;
      const sureCard = sure.length ? `<div class="lg-mv">
          <div class="lg-mv-row"><span class="lg-mv-k good">Start</span><div>${fill.slice(0, sure.length).map(p =>
            `<div>${nm(p)} <span class="muted">${f1(p.exp)}${ifLines(p).length ? ` · ${ifLines(p).join(' · ')}` : ''}</span></div>`).join('')}</div></div>
          <div class="lg-mv-row"><span class="lg-mv-k bad">Bench</span><div>${sure.map(p => `<div>${nm(p)} <span class="muted">${why(p)}</span></div>`).join('')}</div></div>
        </div>` : '';
      const gtCards = unsure.map(p => {
        // his backup on YOUR roster (a teammate whose projection depends on him), in the "he sits" world
        const cuffOf = q => (q.conds || []).find(c => c.pid === p.pid);
        // only someone who comes off the bench for him (not a player already starting either way)
        const cuff = ps.filter(q => cuffOf(q) && (!bestSet.has(q.ext) || benchIn.includes(q))).sort((a, b) => cuffOf(b).sits - cuffOf(a).sits)[0];
        const other = fill.length ? fill[fill.length - 1] : null;
        const cc = cuff && cuffOf(cuff);
        const useCuff = cuff && (!other || cc.sits >= other.proj);  // the better of his backup (in that world) and the next man up
        const out = useCuff ? `start ${nm(cuff)} <b>${f1(cc.sits)}</b> <span class="muted">(${f1(cc.plays)} if ${esc(last(p.name))} plays)</span>`
          : other ? `start ${nm(other)} <b>${f1(other.proj)}</b>${cuff ? ` <span class="muted">(your ${esc(cuff.name)} only rises to ${f1(cc.sits)})</span>` : ''}` : 'pick up a fill-in';
        return `<div class="lg-mv gt">
            <div class="lg-mv-h">${nm(p)} <span class="lg-mv-tag">game-time call</span></div>
            <div class="muted lg-mv-s">${pct(p.inactive)} to sit · ${esc(statusWords(p.status))}</div>
            <div class="lg-mv-row"><span class="lg-mv-k good">Plays</span><div>start him <b>${f1(p.proj)}</b></div></div>
            <div class="lg-mv-row"><span class="lg-mv-k bad">Out</span><div>${out}</div></div>
          </div>`;
      }).join('');
      const swaps = !benchIn.length ? '<div class="lg-swaps good">Your lineup is already the best one by our projections.</div>'
        : `<div class="lg-swaps">${sureCard}${gtCards}
          <div class="muted lg-mv-f">Best lineup: <b class="good">+${f1(gain)}</b> expected points.${unsure.length ? ' Inactives are posted 90 minutes before each kickoff.' : ''}</div></div>`;
      const unproj = curRows.filter(r => r.p && r.p.exp == null && r.slot !== 'DEF' && r.slot !== 'K').map(r => r.p);
      const bench = ps.filter(p => !bestSet.has(p.ext) && p.exp != null).sort((a, b) => b.exp - a.exp);
      return `${swaps}${movesCard()}${unproj.length ? `<p class="muted lg-note">Starting with no projection: ${unproj.map(p => `${esc(p.name)} (${esc(p.why || 'not projected')})`).join(', ')}.</p>` : ''}
        <h3 class="lg-h">Best lineup <span class="muted">${f1(total(best))} expected</span></h3>
        ${table(best.map(r => row(r.slot, r.p)).join(''))}
        <h3 class="lg-h">Bench</h3>${table(bench.map(p => row('BN', p)).join('') || '<tr><td colspan="3" class="muted">No projected bench players.</td></tr>')}
        <p class="muted lg-note">Expected points = our projection under your league's scoring x his chance to play. Kickers and team defenses are projected under your league's own kicking and D/ST settings (3-and-outs and 4th-down stops aren't modeled). Scoring bonuses (100-yard games, 2-point tries) aren't modeled.</p>`;
    };

    const matchupView = () => {
      const m = L.matchup(mine.id);
      if (!m) return '<p class="muted">No matchup this week (bye or playoffs over).</p>';
      const opp = L.teams.find(t => t.id === m.opp);
      const lineupOf = t => {
        const ps = t.ext.map(player);
        const st = (m.starters && m.starters[t.id]) || t.starters;
        return L.slots.map((s, i) => ({ slot: s, p: ps.find(p => p.ext === st[i]) || null }));
      };
      const a = lineupOf(mine), b = lineupOf(opp), ea = total(a), eb = total(b), sd = spreadDiff(a, b) || 1;
      const pw = phi((ea - eb) / sd);
      const side = (t, rows, e, live) => `<div class="lg-side"><div class="lg-tn">${esc(t.name)}</div><div class="lg-big">${f1(e)}</div>
        <div class="muted">projected${live ? ` · ${f1(live)} so far` : ''}</div>${table(rows.map(r => row(r.slot, r.p)).join(''))}</div>`;
      return `<div class="lg-wp"><b>${pct(pw)}</b> to win <span class="muted">(projected ${f1(ea)} - ${f1(eb)}, both teams' current lineups)</span>
          <div class="lg-bar"><span style="width:${(100 * pw).toFixed(1)}%"></span></div></div>
        <div class="lg-vs">${side(mine, a, ea, m.points[mine.id])}${side(opp, b, eb, m.points[opp.id])}</div>
        <p class="muted lg-note">Win chance: each starter's projection and range under your scoring and his chance to sit, for both lineups, counting how players in the same game rise and fall together (a QB and his receivers most). Live points are the platform's.</p>`;
    };

    const WHEAD = '<th>Player</th><th class="num">This wk</th><th class="num">ROS</th>';
    const waiversView = () => {
      if (!ROS) return '<p class="muted">Loading rest-of-season projections…</p>';
      const { moves } = movesFor(), gain = Object.fromEntries(moves.map(m => [m.add.key, m]));
      const forYou = p => { const m = gain[p.key];
        return `<td class="num lg-gain ${m && m.ros > 0.5 ? 'good' : 'muted'}"${m ? ` title="${esc(`${m.ros >= 0 ? '+' : ''}${Math.round(m.ros)} to your team rest of season, ${NFLE.fmt.signed1(m.wk)} this week`)}"` : ''}>${m ? `${m.ros >= 0.5 ? '+' : ''}${Math.round(m.ros)}` : ''}</td>`; };
      const fa = freeAgents();
      const pick = pos => fa.filter(p => p.pos === pos).sort((a, b) => b.ros - a.ros).slice(0, MOVE_POOL)
        .sort((a, b) => ((gain[b.key] || {}).ros ?? -1e9) - ((gain[a.key] || {}).ros ?? -1e9) || b.ros - a.ros).slice(0, 6);
      const sect = (pos, label = pos) => { const list = pick(pos);
        return list.length ? `<h3 class="lg-h">${label}</h3>${table(list.map(p => row(pos, p, `<td class="num">${Math.round(p.ros)}</td>${forYou(p)}`, { noSlot: true })).join(''),
          (pos === 'DEF' ? WHEAD.replace('Player', 'Team') : WHEAD) + '<th class="num">For you</th>')}` : ''; };
      return `<p class="muted lg-note">Unrostered in your league. ROS = his expected points through week ${ROS.through} under your scoring; For you = what adding him does to your team's best lineups through week ${ROS.through}, with the best drop. Each position's best ${MOVE_POOL} by ROS, most useful to you first.</p>
        ${['QB', 'RB', 'WR', 'TE'].map(p => sect(p)).join('')}${L.slots.includes('K') ? sect('K') : ''}${L.slots.includes('DEF') ? sect('DEF', 'D/ST') : ''}`;
    };

    // ---- rest-of-season value of a set of players: their best lineup each remaining week through 17, summed (ros.json:
    // each week's projected line x his chance to play, so byes, injuries and returns count). Keys are platform ids, or
    // 'g:<gsis>' / 'd:<team>' for free agents. Shared by the Teams view and Moves.
    let WKC = new Map(), WKL = null;  // week value cache, per loaded league (its scoring)
    const weekOf = (key, k) => {
      if (WKL !== L) { WKC = new Map(); WKL = L; }
      const ck = `${key}|${k}`;
      if (WKC.has(ck)) return WKC.get(ck);
      const g = key.startsWith('g:') ? key.slice(2) : key.startsWith('d:') ? null : gsisOf(key);
      const dt = key.startsWith('d:') ? key.slice(2) : (!g && dstTeam(key));
      let v = null;
      if (dt) { const d = dWeek(dt, k); v = d ? { ext: key, pos: 'DEF', exp: d.pts } : null; }
      else if (g && !ROS.players[g] && KBY[g]) { const e = kWeek(g, k); v = e == null ? null : { ext: key, pos: 'K', exp: e }; }
      else if (g && ROS.players[g]) {
        const r = ROS.players[g], e = r.w.find(z => z[0] === k);
        v = !e || (k === ROS.from && r.k && Date.now() >= Date.parse(r.k)) ? null : { ext: key, pos: r.pos, exp: e[1] * pts(e[5], L.scoring, r.pos) };
      }
      WKC.set(ck, v);
      return v;
    };
    const rosWeeks = () => { const w = []; for (let k = ROS.from; k <= ROS.through; k++) w.push(k); return w; };
    const valueOf = (keys, weeks) => weeks.reduce((t, k) => t + total(optimize(keys.map(x => weekOf(x, k)).filter(Boolean), L.slots)), 0);
    // Free agents with rest-of-season points (expected, under this league's scoring), best first per position
    const freeAgents = () => {
      const rostered = new Set(L.teams.flatMap(t => t.ext.map(gsisOf).filter(Boolean)));
      const ros = g => rosWeeks().reduce((t, k) => t + ((weekOf(`g:${g}`, k) || {}).exp || 0), 0);
      const out = Object.entries(D.players).filter(([pid, p]) => !rostered.has(pid) && ['QB', 'RB', 'WR', 'TE'].includes(p.pos))
        .map(([pid]) => Object.assign(fromPid(pid, pid), { key: `g:${pid}`, ros: ros(pid) }));
      if (L.slots.includes('K')) Object.entries(KBY).filter(([g]) => !rostered.has(g))
        .forEach(([g]) => out.push(Object.assign(fromPid(g, g), { key: `g:${g}`, ros: ros(g) })));
      const rosteredD = new Set(L.teams.flatMap(t => t.ext.map(dstTeam).filter(Boolean)));
      if (L.slots.includes('DEF') && KD && KD.dst) Object.keys(KD.dst).filter(t => !rosteredD.has(t)).forEach(t => {
        const r = player(L.platform === 'espn' ? String(-16000 - +(Object.entries(ESPN_TEAM).find(([, c]) => c === t) || [0])[0]) : t);
        out.push(Object.assign(r, { key: `d:${t}`, ros: rosWeeks().reduce((a, k) => a + ((weekOf(`d:${t}`, k) || {}).exp || 0), 0) }));
      });
      return out;
    };
    // Moves (owner 2026-10-17: "pick this guy up off waivers and drop this guy"): for each of the best free agents at
    // each position, your team's rest-of-season value (best lineup every remaining week, summed) with him added and each
    // non-IR player dropped (or none, with an open bench spot); the best drop per add, ranked by the gain. This week's
    // gain alongside, from the same weekly values.
    const MOVE_POOL = 8;  // free agents tried per position (the best by their own rest-of-season points)
    // Roster rules (owner 2026-10-17). Hold-one positions (one starting slot, streamable from waivers when he has a bye:
    // QB unless 2-QB / superflex, TE, K, D/ST): a move there must be an upgrade that drops the same position, never a
    // second copy. RB / WR: never drop below DEPTH_MIN.
    // STOPGAP: these rules stand in for depth the values don't see. Rest-of-season values assume every healthy player
    // stays healthy and play the best lineup by expected points, so a backup's insurance (he plays when a starter is
    // hurt) and the waiver wire's own depth (a D/ST for a bye can be picked up that week) are worth ~0 to them.
    // Remaining work (docs/INSIGHTS.md sec. 9, "Fantasy: depth-aware values"): fitted weekly injury rates by position,
    // lineup value as an expectation over who's available, and a waiver replacement level; then drop these rules.
    const DEPTH_MIN = 3;
    const POSK = new Map();
    const posOf = k => { if (!POSK.has(k)) POSK.set(k, k.startsWith('d:') ? 'DEF' : k.startsWith('g:') ? fromPid(k.slice(2), k.slice(2)).pos : player(k).pos); return POSK.get(k); };
    const holdOne = pos => ['TE', 'K', 'DEF'].includes(pos)
      || (pos === 'QB' && !L.slots.includes('SUPER_FLEX') && L.slots.filter(x => x === 'QB').length < 2);
    const allowed = (base, a, d) => {
      const n = pos => base.filter(x => posOf(x) === pos).length;
      if (holdOne(a.pos) && n(a.pos) >= 1 && (d == null || posOf(d) !== a.pos)) return false;
      const dp = d == null ? null : posOf(d);
      if (['RB', 'WR'].includes(dp) && n(dp) - 1 + (a.pos === dp ? 1 : 0) < DEPTH_MIN) return false;
      return true;
    };
    const movesFor = (roster = null) => {
      const weeks = rosWeeks(), now = [weeks[0]];
      const base = roster || mine.ext.filter(x => !(mine.ir || []).includes(x));
      const baseRos = valueOf(base, weeks), baseWk = valueOf(base, now);
      const open = L.size ? base.length < L.size : false;
      const fa = freeAgents();
      const pool = ['QB', 'RB', 'WR', 'TE', 'K', 'DEF'].flatMap(pos => fa.filter(p => p.pos === pos).sort((a, b) => b.ros - a.ros).slice(0, MOVE_POOL));
      const drops = open ? [null, ...base] : base;
      const moves = pool.map(a => {
        let best = null;
        drops.forEach(d => {
          if (!allowed(base, a, d)) return;
          const keys = [...base.filter(x => x !== d), a.key];
          const ros = valueOf(keys, weeks) - baseRos;
          if (!best || ros > best.ros) best = { add: a, drop: d, ros, wk: valueOf(keys, now) - baseWk };
        });
        return best;
      }).filter(Boolean);
      return { moves: moves.sort((x, y) => y.ros - x.ros), open, base };
    };

    // ---- league rankings: every team's best lineup this week and for each remaining week through 17 (ros.json:
    // each week's projected stat line x his chance to play, so byes, injuries and returns all count), summed
    const teamsView = () => {
      if (!ROS) return '<p class="muted">Loading rest-of-season projections…</p>';
      const weeks = rosWeeks();
      const rows = L.teams.map(t => { const ps = t.ext.map(player);
        return { t, wk: total(optimize(ps, L.slots, (t.starters || []).map(x => ps.find(p => p.ext === x) || null))), ros: valueOf(t.ext, weeks) }; });
      rows.sort((a, b) => b.ros - a.ros);
      const avg = rows.reduce((s_, r) => s_ + r.ros, 0) / rows.length;
      const wkRank = rows.slice().sort((a, b) => b.wk - a.wk).map(r => r.t.id);
      const body = rows.map((r, i) => {
        const rc = r.t.record || {};
        return `<tr class="${r.t.id === mine.id ? 'lg-me' : ''}"><td class="num"><b>${i + 1}</b></td><td><b>${esc(r.t.name)}</b>${r.t.id === mine.id ? ' <span class="lg-you">you</span>' : ''}</td>
          <td class="num"><b>${Math.round(r.ros)}</b></td><td class="num lg-avg ${r.ros >= avg ? 'good' : 'bad'}">${r.ros >= avg ? '+' : ''}${Math.round(r.ros - avg)}</td>
          <td class="num">${f1(r.wk)} <span class="muted">(${wkRank.indexOf(r.t.id) + 1})</span></td>
          <td class="num">${rc.w ?? ''}-${rc.l ?? ''}${rc.t ? `-${rc.t}` : ''}</td><td class="num muted lg-pf">${rc.pf ? Math.round(rc.pf) : ''}</td></tr>`;
      }).join('');
      return `<p class="muted lg-note">Ranked by rest-of-season strength: each team's best lineup by our projections for every remaining week through ${ROS.through}, summed (byes, injuries and players coming back included). This week's number in parentheses is its rank. Kickers and team defenses included.</p>
        <div class="lg-scroll"><table class="bx lg-tbl lg-rank"><thead><tr><th class="num">#</th><th>Team</th><th class="num">ROS</th><th class="num lg-avg">vs avg</th><th class="num">This wk</th><th class="num">Record</th><th class="num lg-pf">PF</th></tr></thead><tbody>${body}</tbody></table></div>`;
    };

    const draw = () => {
      if (!L) return connectView();
      const box = sec.querySelector('.lg-body');
      box.innerHTML = view === 'lineup' ? lineupView() : view === 'matchup' ? matchupView() : view === 'teams' ? teamsView() : waiversView();
      if (NFLE.ui && NFLE.ui.ready) NFLE.ui.ready.then(() => {});
    };

    const header = () => {
      sec.innerHTML = `<div class="sec-head"><div><h2>${esc(L.name)}</h2><p>${L.platform === 'sleeper' ? 'Sleeper' : 'ESPN'} · week ${esc(String(L.week))} · ${L.teams.length} teams · our projections under your league's scoring.</p>${(L.unmodeled || []).length ? `<details class="lg-unmod"><summary>${new Set(L.unmodeled).size} scoring rules not modeled</summary><p class="muted">Your league also scores ${esc([...new Set(L.unmodeled)].join(', '))}: not in our projections yet.</p></details>` : ''}</div></div>
        <div class="lg-top"><label>Your team <select class="lg-team">${L.teams.map(t => `<option value="${esc(t.id)}"${mine && t.id === mine.id ? ' selected' : ''}>${esc(t.name)}</option>`).join('')}</select></label>
          <button type="button" class="lg-change">Change league</button></div>
        <div class="seg lg-seg">${[['lineup', 'Lineup'], ['matchup', 'Matchup'], ['teams', 'Teams'], ['waivers', 'Waivers']].map(([k, l]) => `<button type="button" data-v="${k}" class="${view === k ? 'on' : ''}">${l}</button>`).join('')}</div>
        <div class="lg-body"></div>`;
      sec.querySelector('.lg-team').onchange = e => { mine = L.teams.find(t => t.id === e.target.value); saved.team = mine.id; save(); draw(); };
      sec.querySelector('.lg-change').onclick = () => { saved = null; save(); L = null; connectView(); };
      sec.querySelector('.lg-seg').onclick = e => { const b = e.target.closest('[data-v]'); if (!b) return; view = b.dataset.v;
        sec.querySelectorAll('.lg-seg button').forEach(x => x.classList.toggle('on', x === b));
        if ((view === 'waivers' || view === 'teams') && !ROS) NFLE.load('data/ros.json').then(j => { ROS = j; draw(); }, () => draw()); else draw(); };
    };

    const open = async s => {
      sec.innerHTML = '<p class="muted">Loading your league…</p>';
      try {
        L = s.platform === 'espn' ? await espn.load(s.league, season) : await sleeper.load(s.league);
        mine = L.teams.find(t => t.id === s.team) || L.teams.find(t => s.user && t.owner === s.user) || L.teams[0];
        saved = Object.assign({}, s, { team: mine.id }); save();
        header(); draw();
      } catch (e) {
        saved = null; save(); connectView(`Couldn't load that league: ${e.message}`);
      }
    };

    function connectView(err = '') {
      sec.innerHTML = `<div class="sec-head"><div><h2>My League</h2><p>Bring your fantasy league here: your lineup, matchup and waiver pickups with our projections under your league's own scoring.</p></div></div>
        ${err ? `<p class="lg-err">${esc(err)}</p>` : ''}
        <div class="card lg-connect">
          <div class="seg lg-plat"><button type="button" data-p="sleeper" class="on">Sleeper</button><button type="button" data-p="espn">ESPN</button></div>
          <p class="muted lg-hint">Sleeper: your username, or a league id.</p>
          <div class="lg-form"><input type="text" class="lg-in" placeholder="Sleeper username or league id" autocomplete="off"><button type="button" class="sbtn lg-go">Connect</button></div>
          <div class="lg-pick"></div>
          <p class="muted lg-note">Saved on this device only. ESPN: public leagues only (league settings: "make league viewable to public"); the id is the leagueId= number in your league's web address. Yahoo isn't supported (it needs a login server).</p>
        </div>`;
      let plat = 'sleeper';
      const inp = sec.querySelector('.lg-in'), pick = sec.querySelector('.lg-pick');
      sec.querySelector('.lg-plat').onclick = e => { const b = e.target.closest('[data-p]'); if (!b) return; plat = b.dataset.p;
        sec.querySelectorAll('.lg-plat button').forEach(x => x.classList.toggle('on', x === b));
        inp.placeholder = plat === 'espn' ? 'ESPN league id' : 'Sleeper username or league id';
        sec.querySelector('.lg-hint').textContent = plat === 'espn' ? 'ESPN: your public league\'s id.' : 'Sleeper: your username, or a league id.'; };
      const go = async () => {
        const v = inp.value.trim(); if (!v) return;
        if (plat === 'espn') return open({ platform: 'espn', league: v.replace(/\D/g, '') });
        if (/^\d{10,}$/.test(v)) return open({ platform: 'sleeper', league: v });
        pick.innerHTML = '<p class="muted">Finding your leagues…</p>';
        try {
          const r = await sleeper.leaguesFor(v, season);
          if (!r.leagues.length) { pick.innerHTML = `<p class="lg-err">No ${season} Sleeper leagues for ${esc(v)}.</p>`; return; }
          pick.innerHTML = r.leagues.map(l => `<button type="button" class="sbtn lg-lg" data-id="${esc(l.id)}">${esc(l.name)}</button>`).join('');
          pick.onclick = e => { const b = e.target.closest('[data-id]'); if (b) open({ platform: 'sleeper', league: b.dataset.id, user: r.user }); };
        } catch (e) { pick.innerHTML = `<p class="lg-err">${esc(e.message)}</p>`; }
      };
      sec.querySelector('.lg-go').onclick = go;
      inp.onkeydown = e => { if (e.key === 'Enter') go(); };
    }

    if (saved && saved.league) open(saved); else connectView();
  }
})();
