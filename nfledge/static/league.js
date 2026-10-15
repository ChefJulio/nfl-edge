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
  const DSTAT = ['sack', 'int', 'fum_rec', 'ff', 'def_td', 'st_td', 'safe', 'blk', 'pass_def', 'tkl_loss', 'forced_punts', 'def_2pt'];
  const erf = x => { const t = 1 / (1 + 0.3275911 * Math.abs(x)), y = 1 - (((((1.061405429 * t - 1.453152027) * t) + 1.421413741) * t - 0.284496736) * t + 0.254829592) * t * Math.exp(-x * x); return x >= 0 ? y : -y; };
  const Phi = z => 0.5 * (1 + erf(z / Math.SQRT2));
  const pBetween = (mu, sd, lo, hi) => (hi === Infinity ? 1 : Phi((hi + 0.5 - mu) / sd)) - (lo <= 0 ? 0 : Phi((lo - 0.5 - mu) / sd));
  const dstScore = (ln, w) => {
    let t = DSTAT.reduce((a, k) => a + (ln[k] || 0) * (w[k] || 0), 0);
    (w.pa_tiers || []).forEach(([lo, hi, pts]) => { t += pts * pBetween(ln.pa_mu, ln.pa_sd, lo, hi); });
    (w.ya_tiers || []).forEach(([lo, hi, pts]) => { t += pts * pBetween(ln.ya_mu, ln.ya_sd, lo, hi); });
    return t + (w.pts_allow || 0) * ln.pa_mu + (w.yds_allow || 0) * ln.ya_mu;
  };
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
        scoring,
        teams: (rosters || []).map(r => { const st = r.settings || {};
          return { id: String(r.roster_id), owner: r.owner_id, name: uName[r.owner_id] || `Team ${r.roster_id}`,
                   ext: (r.players || []).map(String), starters: (r.starters || []).map(String),
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
                 ext: entries.map(e => String(e.playerId)), starters,
                 record: { w: ov.wins || 0, l: ov.losses || 0, t: ov.ties || 0, pf: ov.pointsFor || 0 } };
      });
      const games = (d.schedule || []).filter(g => g.matchupPeriodId === week || (g.home && g.home.pointsByScoringPeriod && g.home.pointsByScoringPeriod[week] != null));
      return {
        platform: 'espn', id, name: st.name, season, week, slots, scoring, kw, dw, unmodeled, teams, espnNames: names,
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
        return { ext: x, name: `${(TEAMS[dt] || {}).nick || dt} D/ST`, pos: 'DEF', team: dt, proj: v ? v.pts : null, pa: v ? 1 : 0, exp: v ? v.pts : null,
                 sd: 5.5, inactive: 0, opp: v ? v.opp : '', home: v ? (v.home ? 'vs' : '@') : '', why: v ? '' : 'on bye' };
      }
      const e = L.espnNames && L.espnNames[x], dst = /^[A-Z]{2,3}$/.test(x);
      return { ext: x, name: e ? e.name : (dst ? `${(TEAMS[x] || {}).nick || x} D/ST` : `Player ${x}`), pos: e ? e.pos : (dst ? 'DEF' : ''),
               team: dst ? x : '', proj: null, exp: null };
    };
    const fromPid = (g, x) => {
      const p = D.players[g], nm = IDS.names[g];
      if (!p && KBY[g]) {  // a kicker: our kicking projection under this league's kicking settings
        const o = KBY[g], proj = kWeek(g, KD.from);
        return { ext: x, pid: g, name: o.name, pos: 'K', team: o.team, proj, pa: proj == null ? 0 : 1, exp: proj, sd: 4.3, inactive: 0,
                 why: proj == null ? 'on bye' : '' };
      }
      if (!p) return { ext: x, pid: g, name: nm ? nm[0] : g, pos: nm ? nm[1] : '', team: nm ? nm[2] : '', proj: null, exp: null, why: 'no projection this week (bye, out, or not on our board)' };
      const proj = pts(p.sc.pj, L.scoring, p.pos), pa = 1 - (p.inactive || 0);
      // sd from his range (10th-90th percentile spans 2.56 sd), rescaled to this league's scoring
      const base = pts(p.sc.pj, D.score.built, p.pos), r = base > 0.3 ? proj / base : 1;
      const sd = ((p.q[4] - p.q[0]) * r) / 2.563;
      // two worlds for a teammate of an uncertain player, in this league's scoring
      const cond = p.cond ? { name: p.cond[0], pid: p.cond[1], pSit: p.cond[2], plays: p.cond[3] * r, sits: p.cond[4] * r } : null;
      return { ext: x, pid: g, name: p.name, pos: p.pos, team: p.team, photo: p.photo, espn: p.espn, status: p.status, opp: p.opp, home: p.home,
               proj, pa, exp: proj * pa, sd, inactive: p.inactive || 0, cond };
    };

    // "Questionable (ESPN) (DL)" -> "Questionable per ESPN; practice: DNP, limited"
    const statusWords = st => {
      const m = String(st || '').match(/^(.*?)\s*\(([DLF]+)\)\s*$/), des = (m ? m[1] : String(st || '')).trim().replace(/\s*\(ESPN\)/, ' per ESPN');
      const days = m ? [...m[2]].map(c => ({ D: 'DNP', L: 'limited', F: 'full' })[c]).join(', ') : '';
      return [des, days && `practice: ${days}`].filter(Boolean).join('; ') || 'injury report';
    };
    // ---- best lineup: fixed slots first (scarcest eligibility), then flex / superflex, by expected points -----------
    const optimize = (players, slots, current = []) => {
      const pool = players.filter(p => p.exp != null).sort((a, b) => b.exp - a.exp), used = new Set(), out = [];
      const keep = current.filter(p => p && p.exp == null && ['DEF', 'K'].includes(p.pos));  // on bye / not projected: as you set them
      const order = [...slots].sort((a, b) => (ELIG[a] || []).length - (ELIG[b] || []).length);
      order.forEach(s => {
        const el = ELIG[s] || [], pick = pool.find(p => !used.has(p.ext) && el.includes(p.pos))
          || keep.find(p => !used.has(p.ext) && el.includes(p.pos));
        if (pick) used.add(pick.ext);
        out.push({ slot: s, p: pick || null });
      });
      return out;
    };
    const total = rows => rows.reduce((t, r) => t + (r.p && r.p.exp != null ? r.p.exp : 0), 0);
    const spread = rows => Math.sqrt(rows.reduce((t, r) => {
      const p = r.p; if (!p || p.exp == null) return t;
      return t + p.pa * p.sd * p.sd + p.pa * (1 - p.pa) * p.proj * p.proj;  // range + the chance he sits
    }, 0));
    const phi = z => 0.5 * (1 + Math.tanh(0.7978845608 * (z + 0.044715 * z * z * z)));

    // ---- views --------------------------------------------------------------------------------------------------
    const row = (slot, p, extra = '') => p ? `<tr class="teamrow" style="${NFLE.fmt.rowStyle(TEAMS, p.team)}"${p.pid ? ` data-open-pid="${esc(p.pid)}"` : ''}>
        <td class="lg-slot">${esc(slot)}</td><td>${NFLE.ui.player({ name: p.name, pos: p.pos, team: p.team, photo: p.photo, espn: p.espn, pid: p.pid,
          sub: p.opp ? `${p.home} ${p.opp}` : (p.why || p.team || ''), badges: NFLE.injTag(p.status || '')
            + (p.cond ? `<span class="lg-cond">${f1(p.cond.pSit >= 0.5 ? p.cond.plays : p.cond.sits)} if ${esc(p.cond.name.split(' ').slice(-1)[0])} ${p.cond.pSit >= 0.5 ? 'plays' : 'sits'}</span>` : '') }, TEAMS)}</td>
        <td class="num"><b>${p.proj != null ? f1(p.proj) : '—'}</b></td><td class="num muted">${p.proj != null ? (p.inactive >= 0.05 ? pct(p.inactive) : '') : ''}</td>${extra}</tr>`
      : `<tr><td class="lg-slot">${esc(slot)}</td><td colspan="3" class="muted">empty</td>${extra}</tr>`;
    const table = (body, head = '<th>Slot</th><th>Player</th><th class="num">Proj</th><th class="num">Out%</th>') =>
      `<div class="lg-scroll"><table class="bx tiles lg-tbl"><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table></div>`;

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
      const unsure = benchOut.filter(p => p.exp != null && p.inactive >= 0.15 && p.inactive <= 0.85);
      const sure = benchOut.filter(p => !unsure.includes(p));
      const fill = benchIn.slice().sort((a, b) => b.exp - a.exp);
      const outName = p => `${esc(p.name)}${p.exp == null ? ` <span class="muted">(${esc(p.why ? 'not projected: bye, IR or out' : 'not projected')})</span>` : ''}`;
      const swaps = !benchIn.length ? '<div class="lg-swaps good">Your lineup is already the best one by our projections.</div>'
        : `<div class="lg-swaps">${sure.length ? `<div><b>Start ${fill.slice(0, sure.length).map(p => esc(p.name)).join(', ')}</b> over ${sure.map(outName).join(', ')}.</div>` : ''}
          ${unsure.map(p => {
            // his backup on YOUR roster (a teammate whose projection depends on him), in the "he sits" world
            const cuff = ps.filter(q => q.cond && q.cond.pid === p.pid).sort((a, b) => b.cond.sits - a.cond.sits)[0];
            const other = fill.length ? fill[fill.length - 1] : null;
            const useCuff = cuff && (!other || cuff.cond.sits >= other.proj);  // the better of his backup (in that world) and the next man up
            const alt = useCuff ? `start ${esc(cuff.name)} (${f1(cuff.cond.sits)} with ${esc(p.name.split(' ').slice(-1)[0])} out, ${f1(cuff.cond.plays)} if he plays)`
              : other ? `start ${esc(other.name)} (${f1(other.proj)})${cuff ? `; your ${esc(cuff.name)} only rises to ${f1(cuff.cond.sits)}` : ''}` : 'pick up a fill-in';
            return `<div><b>${esc(p.name)}: game-time call.</b> ${pct(p.inactive)} to sit (${esc(statusWords(p.status))}). Inactives come out 90 minutes before kickoff: <b>if he plays, start him (${f1(p.proj)})</b>; if he's out, ${alt}.</div>`;
          }).join('')}
          <div class="muted">By expected points the best lineup gains <b class="good">+${f1(gain)}</b>.</div></div>`;
      const unproj = curRows.filter(r => r.p && r.p.exp == null && r.slot !== 'DEF' && r.slot !== 'K').map(r => r.p);
      const bench = ps.filter(p => !bestSet.has(p.ext) && p.exp != null).sort((a, b) => b.exp - a.exp);
      return `${swaps}${unproj.length ? `<p class="muted lg-note">Starting with no projection: ${unproj.map(p => `${esc(p.name)} (${esc(p.why || 'not projected')})`).join(', ')}.</p>` : ''}
        <h3 class="lg-h">Best lineup <span class="muted">${f1(total(best))} expected</span></h3>
        ${table(best.map(r => row(r.slot, r.p)).join(''))}
        <h3 class="lg-h">Bench</h3>${table(bench.map(p => row('BN', p)).join('') || '<tr><td colspan="4" class="muted">No projected bench players.</td></tr>')}
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
      const a = lineupOf(mine), b = lineupOf(opp), ea = total(a), eb = total(b), sd = Math.hypot(spread(a), spread(b)) || 1;
      const pw = phi((ea - eb) / sd);
      const side = (t, rows, e, live) => `<div class="lg-side"><div class="lg-tn">${esc(t.name)}</div><div class="lg-big">${f1(e)}</div>
        <div class="muted">projected${live ? ` · ${f1(live)} so far` : ''}</div>${table(rows.map(r => row(r.slot, r.p)).join(''))}</div>`;
      return `<div class="lg-wp"><b>${pct(pw)}</b> to win <span class="muted">(projected ${f1(ea)} - ${f1(eb)}, both teams' current lineups)</span>
          <div class="lg-bar"><span style="width:${(100 * pw).toFixed(1)}%"></span></div></div>
        <div class="lg-vs">${side(mine, a, ea, m.points[mine.id])}${side(opp, b, eb, m.points[opp.id])}</div>
        <p class="muted lg-note">Win chance: each starter's projection and range under your scoring, and his chance to sit, added up for both lineups. Live points are the platform's.</p>`;
    };

    const waiversView = () => {
      const rostered = new Set(L.teams.flatMap(t => t.ext.map(gsisOf).filter(Boolean)));
      const rosByPid = {};
      if (ROS) Object.entries(ROS.players).forEach(([pid, x]) => {
        let t = 0; x.w.forEach(([wk, pa, mu, opp, home, line]) => { if (!(wk === ROS.from && x.k && Date.now() >= Date.parse(x.k))) t += pa * pts(line, L.scoring, x.pos); });
        rosByPid[pid] = t;
      });
      const free = Object.entries(D.players).filter(([pid, p]) => !rostered.has(pid) && ['QB', 'RB', 'WR', 'TE'].includes(p.pos)).map(([pid]) => fromPid(pid, pid));
      const byPos = ['QB', 'RB', 'WR', 'TE'].map(pos => {
        const list = free.filter(p => p.pos === pos).map(p => Object.assign(p, { ros: rosByPid[p.pid] })).sort((x, y) => (y.ros ?? y.exp) - (x.ros ?? x.exp)).slice(0, 6);
        return `<h3 class="lg-h">${pos}</h3>${table(list.map(p => row(pos, p, `<td class="num">${p.ros != null ? Math.round(p.ros) : ''}</td>`)).join('') || '<tr><td colspan="5" class="muted">None projected.</td></tr>',
          '<th></th><th>Player</th><th class="num">This wk</th><th class="num">Out%</th><th class="num">ROS</th>')}`;
      }).join('');
      const kFree = Object.entries(KBY).filter(([g]) => !rostered.has(g)).map(([g, o]) => {
        const r = fromPid(g, g); r.ros = o.w.reduce((t, e) => t + kScore(e[2]), 0); return r; })
        .sort((a, b) => b.ros - a.ros).slice(0, 6);
      const rosteredD = new Set(L.teams.flatMap(t => t.ext.map(dstTeam).filter(Boolean)));
      const dFree = KD && KD.dst ? Object.keys(KD.dst).filter(t => !rosteredD.has(t)).map(t => {
        const r = player(L.platform === 'espn' ? String(-16000 - +(Object.entries(ESPN_TEAM).find(([, c]) => c === t) || [0])[0]) : t);
        r.ros = KD.dst[t].w.reduce((a, e) => a + (dWeek(t, e[0]) || { pts: 0 }).pts, 0); return r; }).sort((a, b) => b.ros - a.ros).slice(0, 6) : [];
      const dHtml = L.slots.includes('DEF') ? `<h3 class="lg-h">D/ST</h3>${table(dFree.map(p => row('DEF', p, `<td class="num">${Math.round(p.ros)}</td>`)).join(''),
        '<th></th><th>Team</th><th class="num">This wk</th><th class="num">Out%</th><th class="num">ROS</th>')}` : '';
      const kHtml = L.slots.includes('K') ? `<h3 class="lg-h">K</h3>${table(kFree.map(p => row('K', p, `<td class="num">${Math.round(p.ros)}</td>`)).join(''),
        '<th></th><th>Player</th><th class="num">This wk</th><th class="num">Out%</th><th class="num">ROS</th>')}` : '';
      return `${kHtml ? '' : ''}<p class="muted lg-note">Unrostered in your league, best rest-of-season first (expected points through week 17 under your scoring).</p>${byPos}${kHtml}${dHtml}`;
    };

    // ---- league rankings: every team's best lineup this week and for each remaining week through 17 (ros.json:
    // each week's projected stat line x his chance to play, so byes, injuries and returns all count), summed
    const teamsView = () => {
      if (!ROS) return '<p class="muted">Loading rest-of-season projections…</p>';
      const now = Date.now(), weeks = [];
      for (let k = ROS.from; k <= ROS.through; k++) weeks.push(k);
      const rows = L.teams.map(t => {
        const ps = t.ext.map(player);
        const wk = total(optimize(ps, L.slots));
        let ros = 0;
        weeks.forEach(k => {
          const cand = t.ext.map(x => {
            const g = gsisOf(x), r = g && ROS.players[g];
            const dt = !g && dstTeam(x);
            if (dt) { const v = dWeek(dt, k); return v ? { ext: x, pos: 'DEF', exp: v.pts } : null; }
            if (!r && g && KBY[g]) { const v = kWeek(g, k); return v == null || (k === KD.from && false) ? null : { ext: x, pos: 'K', exp: v }; }
            if (!r) return null;
            const e = r.w.find(z => z[0] === k);
            if (!e || (k === ROS.from && r.k && now >= Date.parse(r.k))) return null;
            return { ext: x, pos: r.pos, exp: e[1] * pts(e[5], L.scoring, r.pos) };
          }).filter(Boolean);
          ros += total(optimize(cand, L.slots));
        });
        return { t, wk, ros };
      });
      rows.sort((a, b) => b.ros - a.ros);
      const avg = rows.reduce((s_, r) => s_ + r.ros, 0) / rows.length;
      const wkRank = rows.slice().sort((a, b) => b.wk - a.wk).map(r => r.t.id);
      const body = rows.map((r, i) => {
        const rc = r.t.record || {};
        return `<tr class="${r.t.id === mine.id ? 'lg-me' : ''}"><td class="num"><b>${i + 1}</b></td><td><b>${esc(r.t.name)}</b>${r.t.id === mine.id ? ' <span class="lg-you">you</span>' : ''}</td>
          <td class="num"><b>${Math.round(r.ros)}</b></td><td class="num ${r.ros >= avg ? 'good' : 'bad'}">${r.ros >= avg ? '+' : ''}${Math.round(r.ros - avg)}</td>
          <td class="num">${f1(r.wk)} <span class="muted">(${wkRank.indexOf(r.t.id) + 1})</span></td>
          <td class="num">${rc.w ?? ''}-${rc.l ?? ''}${rc.t ? `-${rc.t}` : ''}</td><td class="num muted">${rc.pf ? Math.round(rc.pf) : ''}</td></tr>`;
      }).join('');
      return `<p class="muted lg-note">Ranked by rest-of-season strength: each team's best lineup by our projections for every remaining week through ${ROS.through}, summed (byes, injuries and players coming back included). This week's number in parentheses is its rank. Kickers and team defenses included.</p>
        <div class="lg-scroll"><table class="bx lg-tbl lg-rank"><thead><tr><th class="num">#</th><th>Team</th><th class="num">ROS</th><th class="num">vs avg</th><th class="num">This wk</th><th class="num">Record</th><th class="num">PF</th></tr></thead><tbody>${body}</tbody></table></div>`;
    };

    const draw = () => {
      if (!L) return connectView();
      const box = sec.querySelector('.lg-body');
      box.innerHTML = view === 'lineup' ? lineupView() : view === 'matchup' ? matchupView() : view === 'teams' ? teamsView() : waiversView();
      if (NFLE.ui && NFLE.ui.ready) NFLE.ui.ready.then(() => {});
    };

    const header = () => {
      sec.innerHTML = `<div class="sec-head"><div><h2>${esc(L.name)}</h2><p>${L.platform === 'sleeper' ? 'Sleeper' : 'ESPN'} · week ${esc(String(L.week))} · ${L.teams.length} teams · our projections under your league's scoring.</p>${(L.unmodeled || []).length ? `<p class="muted lg-note">Your league also scores ${esc([...new Set(L.unmodeled)].join(', '))}: not in our projections yet.</p>` : ''}</div></div>
        <div class="lg-top"><label>Your team <select class="lg-team">${L.teams.map(t => `<option value="${esc(t.id)}"${mine && t.id === mine.id ? ' selected' : ''}>${esc(t.name)}</option>`).join('')}</select></label>
          <button type="button" class="sbtn lg-change">Change league</button></div>
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
