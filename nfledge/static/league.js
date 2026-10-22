// League (owner 2026-10-15): your real fantasy league with NFL Edge's projections. Import, don't host: Sleeper's public
// API (no login, CORS open) by username or league id, and public ESPN leagues by league id (private ESPN leagues
// need login cookies a browser won't send cross-site; Yahoo needs OAuth: both need a server we don't have).
// Each platform is read into one shape (adapters below), then: your lineup vs the best one by our projections under
// YOUR league's scoring, this week's matchup with a win chance, and the best unrostered players. Player ids map to
// ours through data/fantasy_ids.json (tools/fantasy_ids_build.py). The connection is saved on this device only.
(() => {
  const NFLE = window.NFLE, esc = NFLE.esc;
  const LS = 'nfledge-league';
  const LT = 'nfledge-teams';  // every claimed team (switcher)
  const f1 = v => v == null || isNaN(v) ? '' : (Math.round(v * 10) / 10).toFixed(1);
  const pct = v => `${Math.round(100 * v)}%`;
  const UA = {};  // browsers set their own User-Agent; nothing to send
  const getJSON = url => fetch(url, UA).then(r => r.ok ? r.json() : Promise.reject(new Error(`${r.status}`)));

  // ---- scoring: platform settings -> our stat keys (pass_yd, pass_td, interception, rush_yd, rush_td, reception,
  // rec_yd, rec_td, fumble_lost, te_bonus). Bonuses (100-yard games, first downs, 2-pt tries) aren't projected.
  const SLEEPER_SCORE = { pass_yd: 'pass_yd', pass_td: 'pass_td', pass_int: 'interception', rush_yd: 'rush_yd', rush_td: 'rush_td',
                          rec: 'reception', rec_yd: 'rec_yd', rec_td: 'rec_td', fum_lost: 'fumble_lost', bonus_rec_te: 'te_bonus' };
  // IDP (owner 2026-10-18): Sleeper's idp_* keys are ours as-is; a league without them keeps the site's IDP weights
  const SLEEPER_IDP = ['idp_tkl_solo', 'idp_tkl_ast', 'idp_tkl_loss', 'idp_sack', 'idp_qb_hit', 'idp_int', 'idp_ff', 'idp_fum_rec',
                       'idp_pass_def', 'idp_def_td', 'idp_safe', 'idp_blk_kick'];
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
  const SLEEPER_USED = new Set([...Object.keys(SLEEPER_SCORE), ...SLEEPER_IDP, 'fgm', 'fgmiss', 'fgm_yds', 'fgm_yds_over_30', 'xpm', 'xpmiss',
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
      if (SLEEPER_IDP.some(k => k in (lg.scoring_settings || {}))) SLEEPER_IDP.forEach(k => { scoring[k] = +((lg.scoring_settings || {})[k] || 0); });
      const byRoster = Object.fromEntries((mu || []).map(m => [m.roster_id, m]));
      const kw = sleeperK(lg.scoring_settings || {}), dw = sleeperD(lg.scoring_settings || {});
      const unmodeled = Object.entries(lg.scoring_settings || {}).filter(([k, v]) => +v && !SLEEPER_USED.has(k)).map(([k]) => NICE[k] || k.replace(/_/g, ' '));
      return {
        platform: 'sleeper', id, name: lg.name, season: lg.season, week, kw, dw, unmodeled,
        // waivers (owner 2026-10-18, the week clock): the league's run day (JS weekday, Sun = 0) or daily waivers
        waiverDay: lg.settings && lg.settings.daily_waivers ? 'daily' : ((((lg.settings || {}).waiver_day_of_week ?? 2) + 1) % 7),
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
                         starters: { [teamId]: (me.starters || []).map(String), [opp.roster_id]: (opp.starters || []).map(String) },
                         pp: Object.assign({}, me.players_points || {}, opp.players_points || {}) } : null;  // each player's points, league scoring
        },
        defName: t => t,  // Sleeper team defenses are the team code ("MIN")
      };
    },
  };
  // ESPN public leagues (ESPN's documented-by-use v3 API; owner confirmed working 2026-10-22)
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
        platform: 'espn', id, name: st.name, season, week, slots, scoring, kw, dw, unmodeled, teams, espnNames: names, waiverDay: 3,
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
    // claimed teams (owner 2026-10-20: "claim and switch between multiple teams"): { list: [{ platform, league, team,
    // user, label, lname }], active }; the single saved league from before migrates in as the first
    let TEAMS_ = null;
    try { TEAMS_ = JSON.parse(localStorage.getItem(LT) || 'null'); } catch (e) { /* none */ }
    if (!TEAMS_ || !Array.isArray(TEAMS_.list)) TEAMS_ = { list: saved && saved.league ? [saved] : [], active: 0 };
    if (TEAMS_.list.length) saved = TEAMS_.list[Math.min(TEAMS_.active || 0, TEAMS_.list.length - 1)];
    const sameTeam = (a, b) => a && b && a.platform === b.platform && String(a.league) === String(b.league) && String(a.team) === String(b.team);
    const saveTeams = () => { try { localStorage.setItem(LT, JSON.stringify(TEAMS_)); } catch (e) { /* private mode */ } };
    // the view is the site's Fantasy sub-tab (shell.js NAV: #league/<view>)
    const VIEWS = ['lineup', 'matchup', 'live', 'teams', 'waivers', 'trade'];
    const fromHash = () => { const m = location.hash.match(/^#league\/(\w+)/); return m && VIEWS.includes(m[1]) ? m[1] : null; };
    let L = null, mine = null, ROS = null, view = fromHash() || 'lineup', feedWho = 'mine';
    const save = () => {
      try { localStorage.setItem(LS, JSON.stringify(saved)); } catch (e) { /* private mode */ }
      // the active entry follows (team picked, names learned); a new one is added and becomes active
      if (saved && saved.league) {
        const i = TEAMS_.list.findIndex(x => x.platform === saved.platform && String(x.league) === String(saved.league)
                                             && (x.team == null || saved.team == null || String(x.team) === String(saved.team)));
        if (i >= 0) { TEAMS_.list[i] = saved; TEAMS_.active = i; } else { TEAMS_.list.push(saved); TEAMS_.active = TEAMS_.list.length - 1; }
        saveTeams();
      }
    };
    // the gamecast marks the viewer's players and this week's opponent's (owner 2026-10-18: "viewers might want to know
    // how their fantasy players are doing"): our player ids, written whenever the league or the team changes
    const shareMine = () => {
      try {
        const m = L.matchup(mine.id), opp = m && L.teams.find(t => t.id === m.opp);
        const ids = t => (t ? t.ext : []).map(gsisOf).filter(Boolean);
        const n = s => L.slots.filter(x => x === s).length;
        const lg = { teams: L.teams.length, QB: n('QB'), RB: n('RB'), WR: n('WR'), TE: n('TE'), flex: n('FLEX') + n('WRRB_FLEX') + n('REC_FLEX'), superflex: n('SUPER_FLEX') };
        localStorage.setItem('nfledge-mine', JSON.stringify({ league: L.name, mine: ids(mine), opp: ids(opp), oppName: opp ? opp.name : '', w: L.scoring, lg, kw: L.kw || null, dw: L.dw || null }));
      } catch (e) { /* private mode */ }
      document.dispatchEvent(new Event('nfle-mine'));  // Rankings follows the active team's scoring
    };
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
        return { ext: x, pid: `DST-${dt}`, name: `${(TEAMS[dt] || {}).nick || dt} D/ST`, pos: 'DEF', team: dt, proj: v ? v.pts : null, pa: v ? 1 : 0, exp: v ? v.pts : null, locked: started(dt),
                 sd: 5.5, inactive: 0, opp: v ? v.opp : '', home: v ? (v.home ? 'vs' : '@') : '', why: v ? '' : 'on bye' };
      }
      const e = L.espnNames && L.espnNames[x], dst = /^[A-Z]{2,3}$/.test(x);
      return { ext: x, pid: dst ? `DST-${x}` : undefined, name: e ? e.name : (dst ? `${(TEAMS[x] || {}).nick || x} D/ST` : `Player ${x}`), pos: e ? e.pos : (dst ? 'DEF' : ''),
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
      if (!p) {  // not on this week's board: the rest-of-season file knows him (owner 2026-10-18: bye-week players count)
        const r = ROS && ROS.players && ROS.players[g], team = r ? r.team : nm ? nm[2] : '';
        const bye = !!(ROS && team && ((ROS.byes || {})[team] || []).includes(D.week));
        return { ext: x, pid: g, name: r ? r.name : nm ? nm[0] : g, pos: r ? r.pos : nm ? nm[1] : '', team, photo: r && r.photo, espn: r && r.espn,
                 proj: null, exp: null, why: bye ? 'on bye this week' : 'not projected this week' };  // short: the line sits beside his name (owner 2026-10-20)
      }
      // expected points: his chance to take the field (injury x healthy scratch x backup role; (AY3) "play"), not just health
      const proj = pts(p.sc.pj, L.scoring, p.pos), pa = p.play != null ? p.play : 1 - (p.inactive || 0);
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

    // "Questionable (ESPN) (DL)" -> "Questionable per ESPN; practice: DNP, limited"
    const statusWords = st => {
      const m = String(st || '').match(/^(.*?)\s*\(([DLF-]+)\)\s*$/), des = (m ? m[1] : String(st || '')).trim().replace(/\s*\(ESPN\)/, ' per ESPN');
      const days = m ? [...m[2]].map(c => ({ D: 'DNP', L: 'limited', F: 'full', '-': 'not listed' })[c]).join(', ') : '';
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
    // chance to play is a chip ("65% to play"; owner 2026-10-17: one way everywhere), and the position chip shows only where the slot doesn't already say it
    // (FLEX, bench) or there is no slot (waivers sit under a position heading, so none there either).
    const badgesOf = (p, o = {}) => {
      const out = p.proj != null && p.inactive >= 0.05 && p.inactive < 0.99 ?  // ruled out: the O chip says it
        `<span class="lg-out${p.inactive >= 0.5 ? ' hi' : ''}" title="Chance he plays">${NFLE.fmt.toPlay(p.inactive)} to play</span>` : '';
      const lock = p.locked && !o.noLock ? '<span class="lg-lock" title="His game has kicked off: his spot is set">locked</span>' : '';
      // no "+0.5 if X plays" badge (owner 2026-10-20: the in-depth detail is on the player's page)
      const inner = lock + NFLE.injTag(p.status || '', p.proj != null ? p.inactive : null, p.pid || null) + out;
      return inner ? `<div class="badges lg-badges">${inner}</div>` : '';
    };
    const row = (slot, p, extra = '', o = {}) => {
      const slotTd = o.noSlot ? '' : `<td class="lg-slot">${esc(slot)}</td>`;
      if (!p) return `<tr>${slotTd}<td colspan="2" class="muted">empty</td>${extra}</tr>`;
      const pos = o.noSlot || slot === p.pos ? '' : p.pos;
      return `<tr class="teamrow" style="${NFLE.fmt.rowStyle(TEAMS, p.team)}"${p.pid ? ` data-open-pid="${esc(p.pid)}"` : ''}>${slotTd}
        <td class="lg-who">${NFLE.ui.player({ name: p.name, pos, team: p.team, photo: p.photo, espn: p.espn, pid: p.pid,
          subHtml: p.opp ? `${esc(p.home)} ${NFLE.ui.tm(p.opp)}` : p.why ? esc(p.why) : NFLE.ui.tm(p.team), badges: badgesOf(p) }, TEAMS)}</td>
        <td class="num"><b>${p.proj != null ? f1(p.proj) : /bye/.test(p.why || '') ? '<span class="muted">Bye</span>' : '—'}</b></td>${extra}</tr>`;
    };
    const table = (body, head = '<th>Slot</th><th>Player</th><th class="num">Proj</th>') =>
      `<div class="lg-scroll"><table class="bx tiles lg-tbl"><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table></div>`;

    // Waiver claim window (owner 2026-10-17; on the week clock 2026-10-18): the order resets when the week rolls over
    // (Tuesday); claims run on the league's waiver day (Sleeper: its setting; ESPN: Wednesday) at ~03:00 ET; after that
    // unclaimed players are free agents, first come first served, so the order only matters inside that window (a
    // player dropped later is on waivers for a day: rare enough to skip). Daily-waiver leagues: always a claim race.
    const waiverRun = () => {
      const w = NFLE.clock && NFLE.clock.waivers();  // the clock's default run: Wednesday 03:00 ET after the rollover
      if (w == null || L.waiverDay === 'daily') return null;
      return w + (((L.waiverDay ?? 3) - 3 + 7) % 7) * 864e5;
    };
    const claimWindow = () => {
      if (L.waiverDay === 'daily') return true;
      const run = waiverRun(), roll = NFLE.clock && NFLE.clock.rollover();
      return run != null && roll != null && Date.now() >= roll - 4 * 3600e3 && Date.now() < run;
    };
    const runText = () => { const r = waiverRun();
      return L.waiverDay === 'daily' ? 'claims process daily' : r ? `claims process ${new Date(r).toLocaleString([], { weekday: 'short', hour: 'numeric' })}` : 'claims process Wed'; };
    // The waiver wire as information, not orders (owner 2026-10-17: close calls are the manager's judgment, e.g. a
    // backup's upside the projections can't see): the free agents who'd improve your team most, and your players
    // whose own rest-of-season projection free agents at their position beat. No add-drop pairs.
    const movesCard = () => {
      if (!ROS) { NFLE.load('data/ros.json').then(j => { ROS = j; if (view === 'lineup') draw(); }, () => {}); return '<div class="lg-mv lg-moves"><div class="muted">Checking the waiver wire…</div></div>'; }
      const { moves } = movesFor(), weeks = rosWeeks();
      // the top three free agents at each position that improve the team (owner 2026-10-20: a friend's list was three
      // QBs, the same upgrade three ways, hiding a receiver who beat her WRs; "top 3 to add at each position"),
      // positions ordered by their best gain
      const byPos = {};
      moves.filter(m => m.ros >= 1).forEach(m => { (byPos[m.add.pos] = byPos[m.add.pos] || []).push(m); });
      const best = Object.values(byPos).sort((a, b) => b[0].ros - a[0].ros).flatMap(ms => ms.slice(0, 3));
      const fa = freeAgents();
      const own = mine.ext.filter(x => !(mine.ir || []).includes(x)).map(x => ({ x, p: player(x), ros: weeks.reduce((t, k) => t + ((weekOf(x, k) || {}).exp || 0), 0), games: gamesOf(x) }));
      const below = own.map(o => ({ ...o, beat: fa.filter(f => f.pos === o.p.pos && f.ros > o.ros) }))
        .filter(o => o.beat.length && o.p.pos).sort((a, b) => b.beat.length - a.beat.length || a.ros - b.ros).slice(0, 4);
      const wv = mine.faab != null ? `$${mine.faab} FAAB left` : mine.waiver && claimWindow() ? `${runText()} · you're #${mine.waiver} of ${L.teams.length}` : '';
      // (owner 2026-10-18) the same player rows as the lineup: photo, name, team colors; what he's worth on the right
      const infoRow = (p, tag, val, sub, cls = '', pre = '') => `<tr class="teamrow" style="${NFLE.fmt.rowStyle(TEAMS, p.team)}"${p.pid ? ` data-open-pid="${esc(p.pid)}"` : ''}>
          <td class="lg-slot">${esc(tag)}</td><td class="lg-who">${NFLE.ui.player({ name: p.name, team: p.team, photo: p.photo, espn: p.espn, pid: p.pid, subHtml: sub }, TEAMS)}</td>
          ${pre}<td class="num"><b class="${cls}">${val}</b></td></tr>`;
      // Proj = this week's projection, as the lineup rows show it (owner 2026-10-20); what he adds to your team per week
      // (the order) moves to the line under his name
      const projCell = a => a.proj != null ? f1(a.proj) : /bye/.test(a.why || '') ? '<span class="muted">Bye</span>' : '—';
      // grouped by position (owner 2026-10-20): a label row per position, its best three under it
      const POSW = { QB: 'Quarterbacks', RB: 'Running backs', WR: 'Receivers', TE: 'Tight ends', K: 'Kickers', DEF: 'Defenses' };
      const addRows = best.map((m, i) => (i === 0 || best[i - 1].add.pos !== m.add.pos ? `<tr class="lg-grp"><td colspan="4">${esc(POSW[m.add.pos] || m.add.pos)}</td></tr>` : '')
        + infoRow(m.add, m.add.pos, projCell(m.add), '', '', `<td class="num"><b class="good">${perWk(m.ros)}</b></td>`));
      const belowRows = below.map(o => { const top = o.beat.sort((a, b) => b.ros - a.ros)[0];
        return infoRow(o.p, o.p.pos, o.beat.length, `${perG(o.ros, o.games)}/g · top FA ${esc(last(top.name))} ${perG(top.ros, top.games)}`, 'bad'); });
      return `<h3 class="lg-h">Waiver wire${wv ? ` <span class="muted lg-wv">${wv}</span>` : ''}</h3>
          <div class="lg-mv-sub">Best available for you</div>
          ${addRows.length ? table(addRows.join(''), '<th>Pos</th><th>Free agent</th><th class="num" title="What he adds to your team per week, rest of season (the order)">+/wk</th><th class="num" title="His projection this week, your scoring">Proj</th>').replace('lg-tbl', 'lg-tbl lg-grouped')
            : '<p class="muted">No free agent improves your team over the rest of the season by our projections.</p>'}
          ${belowRows.length ? `<div class="lg-mv-sub">Below the waiver wire</div>${table(belowRows.join(''), '<th>Pos</th><th>Your player</th><th class="num" title="Free agents at his position who project more the rest of the season">Beat by</th>')}` : ''}
          <p class="muted lg-note">Best available = the top three free agents at each position that improve your team. +/wk = what he'd add to your team per week (the order); Proj = his projection this week, your best lineup each remaining week through ${ROS.through}, making room with whoever costs least (one QB, TE, K and D/ST is enough; ${DEPTH_MIN} RBs and WRs stay). Beat by = free agents at his position who project more (top FA = the best of them). /g = expected points per remaining game, byes skipped. Upside the projections can't see is your call.</p>`;
    };
    // IR (owner 2026-10-17: "no mention of IR slots"): listed under the bench with when he's likely back (the first week
    // the return model gives him at least an even chance to play); never in the lineup
    const backWeek = x => { const g = gsisOf(x), r = ROS && g && ROS.players[g];
      if (!ROS) return ''; if (!r) return 'not projected back this season';
      const e = r.w.find(z => z[1] >= 0.5); return e ? `likely back week ${e[0]}` : 'not projected back this season'; };
    const irSection = () => { const ir = (mine.ir || []).filter(x => mine.ext.includes(x));
      const ready = ir.filter(x => { const p = player(x); return p.proj != null && p.inactive < 0.5; });
      return ir.length ? `<h3 class="lg-h">IR</h3>${table(ir.map(x => { const p = player(x);
        // projected to play this week (owner 2026-10-17: an IR player can have a projection): starting him means
        // activating him first, which takes a roster spot
        return row('IR', Object.assign({}, p, ready.includes(x) ? {} : { opp: '', why: backWeek(x) || p.why || 'injured reserve', inactive: 0 })); }).join(''))}
        ${ready.length ? `<p class="muted lg-note">${ready.map(x => { const q = player(x); return q.pid ? `<button type="button" class="nm-link" data-open-pid="${esc(q.pid)}"><b>${esc(q.name)}</b></button>` : `<b>${esc(q.name)}</b>`; }).join(', ')} ${ready.length > 1 ? 'project' : 'projects'} to play this week: starting ${ready.length > 1 ? 'them' : 'him'} means activating off IR first, which takes a roster spot.</p>` : ''}` : ''; };
    // open roster spots (owner 2026-10-20: "display empty bench spots"): the league's roster size (starters + bench, IR
    // and taxi apart) minus the players on it; a free agent fills one without a drop
    const emptyBench = n => { const k = L.size ? Math.max(0, L.size - n) : 0;
      return Array.from({ length: k }, () => `<tr class="lg-empty"><td class="lg-slot">BN</td><td class="muted">Empty <span class="lg-empty-sub">· open roster spot</span></td><td class="num muted">&mdash;</td></tr>`).join(''); };
    const lineupView = () => {
      const irSet = new Set(mine.ir || []);
      const ps = mine.ext.filter(x => !irSet.has(x)).map(player), cur = new Set(mine.starters);
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
        : p.inactive >= 0.15 ? `${NFLE.fmt.toPlay(p.inactive)} to play · ${f1(p.proj)} if he plays · ${esc(statusWords(p.status))}`
        : `projects ${f1(p.exp)}`;
      // names open their player (owner 2026-10-20: "make player names clickable ... wherever else they show up")
      const nm = p => p && p.pid ? `<button type="button" class="nm-link" data-open-pid="${esc(p.pid)}"><b>${esc(p.name)}</b></button>` : `<b>${esc(p ? p.name : '')}</b>`;
      const sureCard = sure.length ? `<div class="lg-mv">
          <div class="lg-mv-row"><span class="lg-mv-k good">Start</span><div>${fill.slice(0, sure.length).map(p =>
            `<div>${nm(p)} <span class="muted">${f1(p.exp)}</span></div>`).join('')}</div></div>
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
            <div class="muted lg-mv-s">${NFLE.fmt.toPlay(p.inactive)} to play · ${esc(statusWords(p.status))}</div>
            <div class="lg-mv-row"><span class="lg-mv-k good">Plays</span><div>start him <b>${f1(p.proj)}</b></div></div>
            <div class="lg-mv-row"><span class="lg-mv-k bad">Out</span><div>${out}</div></div>
          </div>`;
      }).join('');
      const swaps = !benchIn.length ? '<div class="lg-swaps good">Your lineup is already the best one by our projections.</div>'
        : `<div class="lg-swaps">${sureCard}${gtCards}
          <div class="muted lg-mv-f">Best lineup: <b class="good">+${f1(gain)}</b> expected points.${unsure.length ? ' Inactives are posted 90 minutes before each kickoff.' : ''}</div></div>`;
      const unproj = curRows.filter(r => r.p && r.p.exp == null && r.slot !== 'DEF' && r.slot !== 'K').map(r => r.p);
      // players with no projection this week (on bye, out) stay listed, after the projected ones (owner 2026-10-18)
      const bench = ps.filter(p => !bestSet.has(p.ext)).sort((a, b) => (b.exp != null) - (a.exp != null) || (b.exp || 0) - (a.exp || 0));
      return `${swaps}${unproj.length ? `<p class="muted lg-note">Starting with no projection: ${unproj.map(p => `${p.pid ? `<button type="button" class="nm-link" data-open-pid="${esc(p.pid)}">${esc(p.name)}</button>` : esc(p.name)} (${esc(p.why || 'not projected')})`).join(', ')}.</p>` : ''}
        <h3 class="lg-h">Best lineup <span class="muted">${f1(total(best))} expected</span></h3>
        ${table(best.map(r => row(r.slot, r.p)).join(''))}
        <h3 class="lg-h">Bench</h3>${table(bench.map(p => row('BN', p)).join('') + emptyBench(ps.length) || '<tr><td colspan="3" class="muted">No projected bench players.</td></tr>')}
        ${irSection()}
        ${movesCard()}
        <p class="muted lg-note">Expected points = our projection under your league's scoring x his chance to play. Kickers and team defenses are projected under your league's own kicking and D/ST settings (3-and-outs and 4th-down stops aren't modeled). Scoring bonuses (100-yard games, 2-point tries) aren't modeled.${L.slots.some(x => /^(DL|LB|DB|IDP_FLEX|DE|DT|CB|S)$/.test(x)) ? ' Defender (IDP) slots are not projected yet, so they stay as you set them on your platform.' : ''}</p>`;
    };

    // A starter whose game is on or over (owner 2026-10-19: the win chance ignored live scores): his points so far
    // (ESPN's live box score, your scoring) plus his projection for the part of the game left, its spread shrinking with
    // it; final = exactly what he scored (no stat line = 0). Kickers and defenses keep their projection (the live box
    // doesn't carry their scoring).
    const gameDone = team => {
      const gm = (D.games || []).find(g => g.away.team === team || g.home.team === team);
      const st = gm && NFLE.live && NFLE.live.byGame && NFLE.live.byGame[gm.id];
      if (!st || st.state === 'pre') return null;
      if (st.state === 'post') return 1;
      const [mm, ss] = String(st.clock || '15:00').split(':').map(Number), per = +st.period || 1;
      return per > 4 ? 0.98 : Math.min(0.98, ((per - 1) * 900 + (900 - (mm * 60 + (ss || 0)))) / 3600);
    };
    // a finished game: the platform's own points for him when it has them (your league's exact scoring, bonuses,
    // kickers and defenses included); in progress: ESPN's live box (refreshed every 30 s; the platform's is from page load)
    const inGame = (p, pp) => {
      if (!p || p.exp == null) return p;
      const f = gameDone(p.team);
      if (f == null) return p;
      const plat = f >= 1 && pp && pp[p.ext] != null ? +pp[p.ext] : null;
      if (plat == null && ['K', 'DEF'].includes(p.pos)) return p;
      const ln = p.espn && NFLE.live && NFLE.live.lines && NFLE.live.lines[String(p.espn)];
      const now = plat != null ? plat : ln ? pts(ln.line, L.scoring, p.pos) : 0, left = 1 - f;
      return Object.assign({}, p, { live: now, fin: f >= 1, exp: now + p.proj * left, proj: p.proj * left, sd: p.sd * Math.sqrt(left), pa: 1 });
    };
    const matchupView = () => {
      const m = L.matchup(mine.id);
      if (!m) return '<p class="muted">No matchup this week (bye or playoffs over).</p>';
      const opp = L.teams.find(t => t.id === m.opp);
      const lineupOf = t => {
        const ps = t.ext.map(player);
        const st = (m.starters && m.starters[t.id]) || t.starters;
        return L.slots.map((s, i) => ({ slot: s, p: inGame(ps.find(p => p.ext === st[i]) || null, m.pp) }));
      };
      const a = lineupOf(mine), b = lineupOf(opp), ea = total(a), eb = total(b), sd = spreadDiff(a, b) || 1;
      const pw = phi((ea - eb) / sd);
      // Head to head by slot (owner 2026-10-17, after Sleeper's match screen): your starter on the left, theirs on the
      // right, the slot in the middle with each side's projection next to it
      const short = n => { const w = String(n || '').split(' '); return w.length > 1 && !/D\/ST$/.test(n) ? `${w[0][0]}. ${w.slice(1).join(' ')}` : n; };
      const when = p => { if (!p || !p.team) return ''; const k = NFLE.fmt.kickoff(D.games, p.team);
        if (k == null) return p.why ? esc(p.why) : '';
        const t = new Date(k).toLocaleString([], { weekday: 'short', hour: 'numeric', minute: '2-digit' });
        return `${Date.now() >= k ? 'played' : esc(t)} ${esc(p.home || '')} ${p.opp ? NFLE.ui.tm(p.opp) : ''}`; };
      const cell = (p, right) => !p ? '<div class="lg-hh-p muted">empty</div>'
        : `<div class="lg-hh-p${right ? ' r' : ''}"${p.pid ? ` data-open-pid="${esc(p.pid)}"` : ''}><b>${esc(short(p.name))}</b>
            <span class="lg-hh-s"><span class="posb posb-${esc(p.pos)}">${esc(p.pos)}</span> ${NFLE.ui.tm(p.team)}</span>
            <span class="lg-hh-s muted">${when(p)}</span>${badgesOf(p, { noLock: true })}</div>`;
      const num = p => !p || p.proj == null ? '–' : p.live != null ? `<span class="lg-hh-lv">${f1(p.live)}<small>${p.fin ? 'final' : 'live'}</small></span>` : f1(p.proj);
      const rows = L.slots.map((s, i) => `<div class="lg-hh-row">${cell(a[i].p, false)}<div class="lg-hh-n">${num(a[i].p)}</div>
          <span class="lg-hh-slot posb ${/FLEX|^BN$/.test(s) ? 'lg-slot-any' : `posb-${s}`}">${esc(s === 'SUPER_FLEX' ? 'SF' : s === 'FLEX' ? 'FLX' : s)}</span>
          <div class="lg-hh-n">${num(b[i].p)}</div>${cell(b[i].p, true)}</div>`).join('');
      const live = id => m.points[id] ? `<div class="muted lg-hh-live">${f1(m.points[id])} so far</div>` : '';
      return `<div class="lg-hh-top"><div><div class="lg-tn">${esc(mine.name)}</div><div class="lg-big">${f1(ea)}</div>${live(mine.id)}</div>
          <div class="lg-hh-wp"><b>${pct(pw)}</b><span class="muted">to win</span></div>
          <div class="r"><div class="lg-tn">${esc(opp.name)}</div><div class="lg-big">${f1(eb)}</div>${live(opp.id)}</div></div>
        <div class="lg-bar"><span style="width:${(100 * pw).toFixed(1)}%"></span></div>
        <div class="lg-hh">${rows}</div>
        <p class="muted lg-note">Win chance: each starter's projection and range under your scoring and his chance to play, for both lineups, counting how players in the same game rise and fall together (a QB and his receivers most). Once a game starts, its players count their live points (ESPN, your scoring) plus their projection for the time left, so the chance moves with the games; totals above are those expected finals. "So far" is the platform's own live total.</p>`;
    };

    const WHEAD = '<th>Player</th><th class="num">This wk</th><th class="num" title="Expected points per remaining game, byes skipped">ROS/g</th>';
    const waiversView = () => {
      if (!ROS) return '<p class="muted">Loading rest-of-season projections…</p>';
      const { moves } = movesFor(), gain = Object.fromEntries(moves.map(m => [m.add.key, m]));
      const forYou = p => { const m = gain[p.key];
        return `<td class="num lg-gain ${m && m.ros > 0.5 ? 'good' : 'muted'}"${m ? ` title="${esc(`${perWk(m.ros)} per week to your team (${m.ros >= 0 ? '+' : ''}${Math.round(m.ros)} through week ${ROS.through}), ${NFLE.fmt.signed1(m.wk)} this week`)}"` : ''}>${m ? perWk(m.ros) : ''}</td>`; };
      const fa = freeAgents();
      const pick = pos => fa.filter(p => p.pos === pos).sort((a, b) => b.ros - a.ros).slice(0, MOVE_POOL)
        .sort((a, b) => ((gain[b.key] || {}).ros ?? -1e9) - ((gain[a.key] || {}).ros ?? -1e9) || b.ros - a.ros).slice(0, 6);
      const sect = (pos, label = pos) => { const list = pick(pos);
        return list.length ? `<h3 class="lg-h">${label}</h3>${table(list.map(p => row(pos, p, `<td class="num" title="${esc(`${Math.round(p.ros)} expected points over ${p.games} games`)}">${perG(p.ros, p.games)}</td>${forYou(p)}`, { noSlot: true })).join(''),
          (pos === 'DEF' ? WHEAD.replace('Player', 'Team') : WHEAD) + '<th class="num" title="What he adds to your team per remaining week">For you</th>')}` : ''; };
      return `<p class="muted lg-note">Unrostered in your league. ROS/g = his expected points per remaining game through week ${ROS.through} under your scoring (byes skipped); For you = what adding him does to your team's best lineups, per remaining week. Each position's best ${MOVE_POOL}, most useful to you first.</p>
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
    // ROS shown per game (owner 2026-10-17: "50 points over however many weeks are left ... did he have his bye
    // already?"): his expected points over his remaining games (byes skipped); team gains per remaining week
    // his TEAM's remaining games (a week he isn't projected counts as 0 points, not as no game)
    const teamOfKey = key => { if (key.startsWith('d:')) return key.slice(2);
      const g = key.startsWith('g:') ? key.slice(2) : gsisOf(key);
      return g ? ((ROS.players[g] || D.players[g] || KBY[g] || {}).team) : dstTeam(key); };
    const gamesOf = key => { const t = teamOfKey(key), byes = new Set(((ROS.byes || {})[t]) || []);
      return rosWeeks().filter(k => !byes.has(k) && !(k === ROS.from && started(t))).length; };
    const perG = (tot, n) => n ? f1(tot / n) : '–';
    const perWk = v => `${v >= 0.05 ? '+' : ''}${f1(v / Math.max(1, rosWeeks().length))}`;
    const valueOf = (keys, weeks) => weeks.reduce((t, k) => t + total(optimize(keys.map(x => weekOf(x, k)).filter(Boolean), L.slots)), 0);
    // Free agents with rest-of-season points (expected, under this league's scoring), best first per position
    const freeAgents = () => {
      const rostered = new Set(L.teams.flatMap(t => t.ext.map(gsisOf).filter(Boolean)));
      const ros = g => rosWeeks().reduce((t, k) => t + ((weekOf(`g:${g}`, k) || {}).exp || 0), 0);
      // this week's board plus the rest-of-season file (owner 2026-10-18: a free agent on bye this week still counts)
      const cand = new Map(Object.entries(D.players).map(([pid, p]) => [pid, p.pos]));
      Object.entries((ROS && ROS.players) || {}).forEach(([pid, p]) => { if (!cand.has(pid)) cand.set(pid, p.pos); });
      const out = [...cand].filter(([pid, pos]) => !rostered.has(pid) && ['QB', 'RB', 'WR', 'TE'].includes(pos))
        .map(([pid]) => Object.assign(fromPid(pid, pid), { key: `g:${pid}`, ros: ros(pid), games: gamesOf(`g:${pid}`) }));
      if (L.slots.includes('K')) Object.entries(KBY).filter(([g]) => !rostered.has(g))
        .forEach(([g]) => out.push(Object.assign(fromPid(g, g), { key: `g:${g}`, ros: ros(g), games: gamesOf(`g:${g}`) })));
      const rosteredD = new Set(L.teams.flatMap(t => t.ext.map(dstTeam).filter(Boolean)));
      if (L.slots.includes('DEF') && KD && KD.dst) Object.keys(KD.dst).filter(t => !rosteredD.has(t)).forEach(t => {
        const r = player(L.platform === 'espn' ? String(-16000 - +(Object.entries(ESPN_TEAM).find(([, c]) => c === t) || [0])[0]) : t);
        out.push(Object.assign(r, { key: `d:${t}`, ros: rosWeeks().reduce((a, k) => a + ((weekOf(`d:${t}`, k) || {}).exp || 0), 0), games: gamesOf(`d:${t}`) }));
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
      // IR players (owner 2026-10-17) take no roster spot and are never drops, but count once they're projected back
      const ir = (mine.ir || []).filter(x => mine.ext.includes(x)), withIr = k => [...k, ...ir];
      const baseRos = valueOf(withIr(base), weeks), baseWk = valueOf(withIr(base), now);
      const open = L.size ? base.length < L.size : false;
      const fa = freeAgents();
      const pool = ['QB', 'RB', 'WR', 'TE', 'K', 'DEF'].flatMap(pos => fa.filter(p => p.pos === pos).sort((a, b) => b.ros - a.ros).slice(0, MOVE_POOL));
      const drops = open ? [null, ...base] : base;
      const moves = pool.map(a => {
        let best = null;
        drops.forEach(d => {
          if (!allowed(base, a, d)) return;
          const keys = withIr([...base.filter(x => x !== d), a.key]);
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


    // ---- trades (owner 2026-10-17: "trade value is relative to your team and the league's rules"): what a trade does
    // to EACH side's best lineups through week 17 (the waiver card's method), per remaining week; this week alongside;
    // roster depth after it. A fair trade helps both. The finder searches 1-for-1 and 2-for-1 swaps with every team for
    // ones that help both sides, ranked by the smaller gain.
    let trade = { team: null, give: new Set(), get: new Set(), found: null };
    const keysOf = t => t.ext.filter(x => !(t.ir || []).includes(x));
    const depthIssues = keys => {
      const n = pos => keys.filter(k => posOf(k) === pos).length, out = [];
      ['RB', 'WR'].forEach(pos => { if (n(pos) < DEPTH_MIN) out.push(`${n(pos)} ${pos}s`); });
      ['QB', 'TE', 'K', 'DEF'].forEach(pos => { if (L.slots.includes(pos) && !n(pos)) out.push(`no ${pos === 'DEF' ? 'D/ST' : pos}`); });
      return out;
    };
    // Waiver replacement level for trades (owner 2026-10-17: "most people aren't looking for an upgrade at QB, not in
    // return for a downgrade at flex"): each week either team may also start the best free agent at each position, so a
    // player is worth only his edge over what's on waivers (a 1-QB league's spare QB, a TE or D/ST, ~nothing; a scarce
    // RB or WR, most of his points). One free agent per position per week. Not used by the waiver card: there the free
    // agent is the move.
    let FAW = null, FAL = null;
    const faWeek = k => {
      if (FAL !== L) { FAW = new Map(); FAL = L; }
      if (!FAW.has(k)) {
        const fa = freeAgents(), best = {};
        fa.forEach(p => { const v = weekOf(p.key, k); if (v && (!best[p.pos] || v.exp > best[p.pos].exp)) best[p.pos] = { ext: `fa:${p.pos}`, pos: p.pos, exp: v.exp }; });
        FAW.set(k, Object.values(best));
      }
      return FAW.get(k);
    };
    const valueRepl = (keys, weeks) => weeks.reduce((t, k) => t + total(optimize([...keys.map(x => weekOf(x, k)).filter(Boolean), ...faWeek(k)], L.slots)), 0);
    const tradeEval = (them, give, get) => {
      const weeks = rosWeeks(), now = [weeks[0]], valueOf = valueRepl;
      const side = (t, out, inn) => {
        const before = t.ext, after = [...before.filter(x => !out.includes(x)), ...inn];
        const active = k => k.filter(x => !(t.ir || []).includes(x) || inn.includes(x));  // an IR player traded in needs a spot
        return { ros: (valueOf(after, weeks) - valueOf(before, weeks)) / Math.max(1, weeks.length), wk: valueOf(after, now) - valueOf(before, now),
                 depth: depthIssues(active(after)), extra: active(after).length - active(before).length };
      };
      return { me: side(mine, give, get), them: side(them, get, give) };
    };
    const verdict = r => r.me.ros > 0.05 && r.them.ros > 0.05 ? ['good', 'Helps both']
      : r.me.ros > 0.05 ? ['', 'Helps you, costs them'] : r.them.ros > 0.05 ? ['bad', 'Helps them, costs you'] : ['bad', 'Helps neither'];
    const findTrades = (only = null) => {
      const out = [], mk = keysOf(mine).filter(x => !['K', 'DEF'].includes(posOf(x)));
      L.teams.filter(t => t.id !== mine.id && (!only || t.id === only)).forEach(t => {
        const tk = keysOf(t).filter(x => !['K', 'DEF'].includes(posOf(x)));
        const tryIt = (give, get) => {
          const r = tradeEval(t, give, get);
          if (r.me.ros > 0.05 && r.them.ros > 0.05 && !r.me.depth.length && !r.them.depth.length) out.push({ t, give, get, r });
        };
        mk.forEach(a => tk.forEach(b => tryIt([a], [b])));
        mk.forEach((a, i) => mk.slice(i + 1).forEach(a2 => tk.forEach(b => tryIt([a, a2], [b]))));  // you consolidate
      });
      // variety: none of your players in more than two ideas
      const used = {}, pick = [];
      out.sort((x, y) => Math.min(y.r.me.ros, y.r.them.ros) - Math.min(x.r.me.ros, x.r.them.ros)).forEach(f => {
        if (pick.length < 8 && f.give.every(x => (used[x] || 0) < 2)) { pick.push(f); f.give.forEach(x => { used[x] = (used[x] || 0) + 1; }); }
      });
      return pick;
    };
    const nameOf = x => player(x).name;
    const shortName = n => { const w = String(n || '').split(' '); return w.length > 1 && !/D\/ST$/.test(n) ? `${w[0][0]}. ${w.slice(1).join(' ')}` : n; };
    const tradeView = () => {
      if (!ROS) { NFLE.load('data/ros.json').then(j => { ROS = j; if (view === 'trade') draw(); }, () => {}); return '<p class="muted">Loading rest-of-season projections…</p>'; }
      const others = L.teams.filter(t => t.id !== mine.id);
      const them = others.find(t => t.id === trade.team) || null;
      const weeks = rosWeeks();
      // grouped by position (owner 2026-10-17), best first by points per game; the two sides' blocks line up
      const POS_ORDER = ['QB', 'RB', 'WR', 'TE', 'K', 'DEF'];
      const pick = (t, side, pos) => t.ext.map(x => ({ x, p: player(x) })).filter(o => o.p.pos === pos).map(o => {
        const ros = weeks.reduce((u, k) => u + ((weekOf(o.x, k) || {}).exp || 0), 0), g = gamesOf(o.x);
        return { ...o, pg: g ? ros / g : 0, ros, g };
      }).sort((a, b) => b.pg - a.pg).map(({ x, p, ros, g }) => {
        const on = trade[side].has(x);
        return `<button type="button" class="lg-tp${on ? ' on' : ''}" data-side="${side}" data-x="${esc(x)}"><span class="lg-tp-n"><b>${esc(shortName(p.name))}</b><span class="muted">${(t.ir || []).includes(x) ? 'IR · ' : ''}${perG(ros, g)}/g</span></span></button>`;
      }).join('');
      let result = '';
      if (them && (trade.give.size || trade.get.size)) {
        const r = tradeEval(them, [...trade.give], [...trade.get]), [cls, txt] = verdict(r);
        const sideHtml = (label, x) => `<div class="lg-tr-side"><div class="lg-tn">${esc(label)}</div>
            <div class="lg-big ${x.ros > 0.05 ? 'good' : x.ros < -0.05 ? 'bad' : ''}">${x.ros >= 0 ? '+' : ''}${f1(x.ros)}<small> /wk</small></div>
            <div class="muted">rest of season · ${NFLE.fmt.signed1(x.wk)} this week</div>
            ${x.depth.length ? `<div class="lg-tr-warn">Leaves ${esc(x.depth.join(', '))}</div>` : ''}
            ${x.extra > 0 ? `<div class="muted">needs ${x.extra} roster spot${x.extra === 1 ? '' : 's'} (a drop)</div>` : ''}</div>`;
        result = `<div class="lg-mv lg-trade"><div class="lg-mv-h"><span class="lg-verdict ${cls}">${txt}</span></div>
            <div class="lg-tr-sides">${sideHtml('You', r.me)}${sideHtml(them.name, r.them)}</div></div>`;
      }
      const found = trade.found;
      const finder = found == null ? `<button type="button" class="sbtn lg-find">${them ? `Find trades with ${esc(them.name)} that help both` : 'Find trades that help both teams'}</button>`
        : found.length ? `<div class="lg-mv"><div class="lg-mv-h">Trades that help both</div>${found.map((f, i) =>
            `<button type="button" class="lg-tf" data-i="${i}"><div><b>${esc(f.t.name)}</b>: you give ${f.give.map(x => `<b>${esc(nameOf(x))}</b>`).join(' + ')}, get <b>${esc(nameOf(f.get[0]))}</b></div>
              <div class="muted">you ${f.r.me.ros >= 0 ? '+' : ''}${f1(f.r.me.ros)}/wk · them ${f.r.them.ros >= 0 ? '+' : ''}${f1(f.r.them.ros)}/wk</div></button>`).join('')}</div>`
        : '<p class="muted">No 1-for-1 or 2-for-1 trade helps both teams by our projections.</p>';
      return `<p class="muted lg-note">Pick a team, then tap players to give and get. Each side's change = its best lineup every remaining week through ${ROS.through}, per week. A fair trade helps both. Either team could also start the best free agent at each spot, so a player counts only for his edge over the waiver wire (a spare QB in a one-QB league is worth little). Values assume healthy players stay healthy; trades that leave fewer than ${DEPTH_MIN} RBs or WRs are flagged.</p>
        ${result}
        <div class="lg-tr-cols"><div class="lg-tr-h"><b>${esc(mine.name)}</b><span class="muted">you give</span></div>
          <div class="lg-tr-h r"><select class="lg-trteam" aria-label="Trade with"><option value="">Any team</option>${others.map(t => `<option value="${esc(t.id)}"${them && t.id === them.id ? ' selected' : ''}>${esc(t.name)}</option>`).join('')}</select><span class="muted">you get</span></div></div>
        ${POS_ORDER.filter(pos => mine.ext.some(x => player(x).pos === pos) || (them && them.ext.some(x => player(x).pos === pos))).map(pos =>
          `<div class="lg-tr-pos"><span class="posb ${/FLEX|^BN$/.test(pos) ? 'lg-slot-any' : `posb-${pos}`}">${pos === 'DEF' ? 'D/ST' : pos}</span></div>
          <div class="lg-tr-cols"><div class="lg-tps">${pick(mine, 'give', pos)}</div><div class="lg-tps">${them ? pick(them, 'get', pos) : ''}</div></div>`).join('')}
        ${them ? '' : '<p class="muted">Choose a team to pick players from theirs, or find trades with any team below.</p>'}
        <div class="lg-finder">${finder}</div>`;
    };
    const wireTrade = box => {
      const sel = box.querySelector('.lg-trteam');
      if (sel) sel.onchange = () => { trade.team = sel.value || null; trade.get = new Set(); trade.found = null; draw(); };  // a new partner: new ideas
      box.querySelectorAll('.lg-tp').forEach(b => b.onclick = () => { const set = trade[b.dataset.side]; set.has(b.dataset.x) ? set.delete(b.dataset.x) : set.add(b.dataset.x); draw(); });
      const f = box.querySelector('.lg-find');
      if (f) f.onclick = () => { f.textContent = 'Searching…'; f.disabled = true; setTimeout(() => { trade.found = findTrades(trade.team); draw(); }, 30); };
      box.querySelectorAll('.lg-tf').forEach(b => b.onclick = () => { const x = trade.found[+b.dataset.i];
        trade = { ...trade, team: x.t.id, give: new Set(x.give), get: new Set(x.get) }; draw(); box.scrollIntoView({ block: 'start', behavior: 'smooth' }); });
    };
    // Live plays (owner 2026-10-18): every play this week that moved your starters' points (your opponent's too, on
    // request), newest first, scored under this league's settings; gamecast.js builds the feed from the live box scores
    const liveView = () => {
      const m = L.matchup(mine.id), opp = m && L.teams.find(t => t.id === m.opp);
      // starters as our ids; a team defense (Sleeper's team code, ESPN's team id) as DST-<team> (scored per play too)
      const st = t => ((m && m.starters && m.starters[t.id]) || t.starters || []).map(x => gsisOf(x) || (dstTeam(x) ? `DST-${dstTeam(x)}` : null)).filter(Boolean);
      const ids = new Map();
      if (feedWho !== 'mine' && opp) st(opp).forEach(g => ids.set(g, 'opp'));
      if (feedWho !== 'opp') st(mine).forEach(g => ids.set(g, 'mine'));
      const cards = NFLE.livePlays ? NFLE.livePlays(ids, L.scoring, { kw: L.kw, dw: L.dw }) : [];
      const seg = `<div class="seg lpf-who">${[['mine', 'My starters'], ['both', opp ? `+ ${opp.name}` : 'Both'], ['opp', opp ? opp.name : 'Opponent']].map(([k, l]) => `<button type="button" data-who="${k}" class="${feedWho === k ? 'on' : ''}">${esc(l)}</button>`).join('')}</div>`;
      return `${seg}<p class="muted lg-note">Every play that moved these players' points, newest first, under your league's scoring (kickers and defenses too; a defense's points-allowed tier counts only at the end of its game); the number beside each player is his game total after the play. Updates every 20 seconds while open.</p>
        ${NFLE.livePlaysHtml ? NFLE.livePlaysHtml(cards) : ''}`;
    };
    const draw = () => {
      if (!L) return connectView();
      const box = sec.querySelector('.lg-body');
      NFLE.feedOpen = view === 'live';
      box.innerHTML = view === 'live' ? liveView() : view === 'lineup' ? lineupView() : view === 'matchup' ? matchupView() : view === 'teams' ? teamsView() : view === 'trade' ? tradeView() : waiversView();
      box.querySelectorAll('[data-who]').forEach(b => b.onclick = () => { feedWho = b.dataset.who; draw(); });
      if (view === 'trade') wireTrade(box);
      // the site-wide id map (kickers in the live feed): redraw once when it arrives, never again after
      if (NFLE.ui && NFLE.ui.ready && !NFLE.ui.ids) NFLE.ui.ready.then(() => { if (L && view === 'live') draw(); });
    };

    const header = () => {
      sec.innerHTML = `<div class="sec-head"><div><h2>${esc(L.name)}</h2><p>${L.platform === 'sleeper' ? 'Sleeper' : 'ESPN'} · week ${esc(String(L.week))} · ${L.teams.length} teams · our projections under your league's scoring.</p>${(L.unmodeled || []).length ? `<details class="lg-unmod"><summary>${new Set(L.unmodeled).size} scoring rules not modeled</summary><p class="muted">Your league also scores ${esc([...new Set(L.unmodeled)].join(', '))}: not in our projections yet.</p></details>` : ''}</div></div>
        ${switcher()}
        <div class="lg-top"><label title="Which team in this league is yours: changing it re-claims this chip">Your team <select class="lg-team">${L.teams.map(t => `<option value="${esc(t.id)}"${mine && t.id === mine.id ? ' selected' : ''}>${esc(t.name)}</option>`).join('')}</select></label>
          <button type="button" class="lg-change">Remove this team</button>
          <small class="muted lg-tnote">Not yours? Pick yours here: this team's chip switches to it.</small></div>
        <div class="lg-body"></div>`;
      wireSwitcher(sec);
      sec.querySelector('.lg-team').onchange = e => { mine = L.teams.find(t => t.id === e.target.value);
        TEAMS_.list = TEAMS_.list.filter(x => !(sameTeam(x, Object.assign({}, saved, { team: mine.id })) && x !== saved));  // no duplicate claim
        saved = Object.assign(saved, { team: mine.id, label: mine.name, lname: L.name, unpicked: false }); save(); shareMine();
        sec.querySelector('.lg-switch').outerHTML = switcher(); wireSwitcher(sec);
        trade = { team: null, give: new Set(), get: new Set(), found: null }; draw(); };
      sec.querySelector('.lg-change').onclick = () => {
        TEAMS_.list = TEAMS_.list.filter(x => x !== saved && !sameTeam(x, saved));
        TEAMS_.active = 0; saveTeams();
        try { localStorage.removeItem('nfledge-mine'); } catch (e) { /* ignore */ }
        document.dispatchEvent(new Event('nfle-mine'));
        L = null; NFLE.leagueDst = null;
        if (TEAMS_.list.length) open(TEAMS_.list[0]); else { saved = null; try { localStorage.removeItem(LS); } catch (e) { /* ignore */ } connectView(); }
      };
    };

    const setView = v => {
      if (!VIEWS.includes(v)) return;
      view = v;
      if (!L) return;
      if (['waivers', 'teams', 'trade'].includes(view) && !ROS) NFLE.load('data/ros.json').then(j => { ROS = j; draw(); }, () => draw()); else draw();
    };
    document.addEventListener('nfle-route', e => { if (e.detail && e.detail.parent === 'league') setView(e.detail.sub); else NFLE.feedOpen = false; });
    // the feed redraws on every live update while it's showing
    document.addEventListener('nfle-live', () => { if (L && (view === 'live' || view === 'matchup') && sec.isConnected && !sec.hidden) draw(); });  // the matchup's win chance follows the live scores
    const open = async s => {
      sec.innerHTML = '<p class="muted">Loading your league…</p>';
      try {
        L = s.platform === 'espn' ? await espn.load(s.league, season) : await sleeper.load(s.league);
        NFLE.leagueDst = L && L.dw ? { w: L.dw, name: L.name } : null;  // D/ST cards score with this league's settings
        mine = L.teams.find(t => t.id === s.team) || L.teams.find(t => s.user && t.owner === s.user) || L.teams[0];
        // an ESPN league has no owner to match: until a team is picked, the first one shows and the switcher says so
        const picked = s.team != null || !!(s.user && L.teams.some(t => t.owner === s.user));
        saved = Object.assign(s, { team: mine.id, label: mine.name, lname: L.name, unpicked: !picked && L.platform === 'espn' }); save(); shareMine();
        header(); setView(view);
      } catch (e) {
        connectView(`Couldn't load that league: ${e.message}`);
      }
    };

    // the claimed teams as chips: tap one to switch, + to add another (owner 2026-10-20)
    const switcher = () => `<div class="lg-switch">${TEAMS_.list.map((x, i) => `<button type="button" class="lg-chip${x === saved ? ' on' : ''}" data-i="${i}">
        <b>${esc(x.unpicked ? 'Pick your team' : (x.label || 'Team'))}</b><small>${esc(x.lname || (x.platform === 'espn' ? 'ESPN league' : 'Sleeper league'))}</small></button>`).join('')}
        <button type="button" class="lg-chip lg-add" aria-label="Add a team">+</button></div>`;
    const wireSwitcher = root => {
      const sw = root.querySelector('.lg-switch'); if (!sw) return;
      sw.onclick = e => {
        const b = e.target.closest('.lg-chip'); if (!b) return;
        if (b.classList.contains('lg-add')) { connectView(); return; }
        const x = TEAMS_.list[+b.dataset.i];
        // on the add screen every chip goes back to its team, the active one too (owner 2026-10-20: "my navigation gets
        // locked here"); on a team's page the active chip is already showing
        const adding = !!sec.querySelector('.lg-connect');
        if (x && (x !== saved || adding)) { TEAMS_.active = +b.dataset.i; saveTeams(); trade = { team: null, give: new Set(), get: new Set(), found: null }; open(x); }
      };
    };
    // Sleeper: every team the user owns this season, claimed at once (owner: "auto claim")
    const claimSleeper = async (username) => {
      const r = await sleeper.leaguesFor(username, season);
      if (!r.leagues.length) throw new Error(`No ${season} Sleeper leagues for ${username}`);
      const B = 'https://api.sleeper.app/v1', found = [];
      await Promise.all(r.leagues.map(async l => {
        const [rosters, users] = await Promise.all([getJSON(`${B}/league/${l.id}/rosters`), getJSON(`${B}/league/${l.id}/users`)]);
        (rosters || []).filter(x => x.owner_id === r.user || (x.co_owners || []).includes(r.user)).forEach(x => {
          const u = (users || []).find(z => z.user_id === x.owner_id) || {};
          found.push({ platform: 'sleeper', league: l.id, user: r.user, team: String(x.roster_id),
                       label: (u.metadata && u.metadata.team_name) || u.display_name || `Team ${x.roster_id}`, lname: l.name });
        });
      }));
      return found;
    };

    function connectView(err = '') {
      sec.innerHTML = `<div class="sec-head"><div><h2>${TEAMS_.list.length ? 'Add a team' : 'My League'}</h2><p>Bring your fantasy league here: your lineup, matchup and waiver pickups with our projections under your league's own scoring.</p></div></div>
        ${TEAMS_.list.length ? `${switcher()}<p class="muted lg-hint">Tap a team to go back to it.</p>` : ''}
        ${err ? `<p class="lg-err">${esc(err)}</p>` : ''}
        <div class="card lg-connect">
          <div class="seg lg-plat"><button type="button" data-p="sleeper" class="on">Sleeper</button><button type="button" data-p="espn">ESPN</button></div>
          <p class="muted lg-hint">Sleeper: your username (claims every team you own) or a league id.</p>
          <div class="lg-form"><input type="text" class="lg-in" placeholder="Sleeper username or league id" autocomplete="off"><button type="button" class="sbtn lg-go">Connect</button></div>
          <div class="lg-pick"></div>
          <p class="muted lg-note">Saved on this device only. ESPN: public leagues only (league settings: "make league viewable to public"); the id is the leagueId= number in your league's web address. Yahoo isn't supported (it needs a login server).</p>
        </div>`;
      wireSwitcher(sec);
      let plat = 'sleeper';
      const inp = sec.querySelector('.lg-in'), pick = sec.querySelector('.lg-pick');
      sec.querySelector('.lg-plat').onclick = e => { const b = e.target.closest('[data-p]'); if (!b) return; plat = b.dataset.p;
        sec.querySelectorAll('.lg-plat button').forEach(x => x.classList.toggle('on', x === b));
        inp.placeholder = plat === 'espn' ? 'ESPN league id' : 'Sleeper username or league id';
        sec.querySelector('.lg-hint').textContent = plat === 'espn' ? 'ESPN: your public league\'s id; then pick your team.' : 'Sleeper: your username (claims every team you own) or a league id.'; };
      const go = async () => {
        const v = inp.value.trim(); if (!v) return;
        if (plat === 'espn') {  // a pasted web address: the number after leagueId= (joining every digit folded in the season)
          const m = v.match(/leagueId=(\d+)/i);
          return open({ platform: 'espn', league: m ? m[1] : v.replace(/\D/g, '') });
        }
        if (/^\d{10,}$/.test(v)) return open({ platform: 'sleeper', league: v });
        pick.innerHTML = '<p class="muted">Finding your teams…</p>';
        try {
          const found = await claimSleeper(v);
          if (!found.length) { pick.innerHTML = `<p class="lg-err">${esc(v)} doesn't own a team in a ${season} Sleeper league.</p>`; return; }
          const fresh = found.filter(f => !TEAMS_.list.some(x => sameTeam(x, f)));
          TEAMS_.list.push(...fresh); saveTeams();
          const first = fresh[0] || TEAMS_.list.find(x => sameTeam(x, found[0]));
          TEAMS_.active = TEAMS_.list.indexOf(first); saveTeams();
          open(first);
        } catch (e) { pick.innerHTML = `<p class="lg-err">${esc(e.message)}</p>`; }
      };
      sec.querySelector('.lg-go').onclick = go;
      inp.onkeydown = e => { if (e.key === 'Enter') go(); };
    }

    if (saved && saved.league) open(saved); else connectView();
  }
})();
