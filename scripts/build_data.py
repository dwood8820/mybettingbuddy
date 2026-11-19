"""Build the site's data files from nflverse.

Writes three JSON files to --out (default: out/):
  nfl.json      current season: teams, team game logs, this week's slate, player game logs
  ou_hist.json  every game since 2015 with its pregame spread/total (O/U and Spread Splicers)
  pp_hist.json  player game logs by opposing defense, last three seasons (Player Prop Splicer)

Run by GitHub Actions on a schedule; also runnable locally:  python scripts/build_data.py --out out
"""
import argparse, io, json, math, os, urllib.request
import sys
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from espn_moves import add_moves  # opening vs current lines

GAMES_URL = "https://raw.githubusercontent.com/nflverse/nfldata/master/data/games.csv"
TEAMS_URL = "https://github.com/nflverse/nflverse-data/releases/download/teams/teams_colors_logos.csv"
PBP_URL = "https://github.com/nflverse/nflverse-data/releases/download/pbp/play_by_play_{}.parquet"
PSTATS_URL = "https://github.com/nflverse/nflverse-data/releases/download/stats_player/stats_player_week_{}.csv"
KEYS = ['passing_yards','passing_tds','completions','attempts','rushing_yards','rushing_tds','carries',
        'receiving_yards','receptions','targets','receiving_tds']
PO = {'WC':19,'DIV':20,'CON':21,'SB':22}


def fetch_csv(url):
    req = urllib.request.Request(url, headers={"User-Agent": "mybettingbuddy-data"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return pd.read_csv(io.BytesIO(r.read()), low_memory=False)


def num(x):
    return None if x is None or (isinstance(x, float) and math.isnan(x)) or pd.isna(x) else float(x)


def inum(x):
    v = num(x)
    return None if v is None else int(v)


def build_current(games, teams, pw, season):
    g = games[(games.season == season) & (games.game_type == 'REG')]
    TEAMS = {r.team_abbr: {'name': r.team_name, 'nick': r.team_nick, 'c1': r.team_color, 'c2': r.team_color2}
             for r in teams.itertuples() if r.team_abbr in set(g.home_team) | set(g.away_team)}
    done = g[g.home_score.notna()]
    tg = {k: [] for k in TEAMS}
    res = {}
    for r in done.itertuples():
        for side in ('home', 'away'):
            tm = getattr(r, side + '_team'); op = r.away_team if side == 'home' else r.home_team
            pf = getattr(r, side + '_score'); pa = r.away_score if side == 'home' else r.home_score
            exp = r.spread_line if side == 'home' else -r.spread_line
            m = pf - pa
            tg[tm].append({'wk': int(r.week), 'opp': op, 'home': side == 'home', 'pf': int(pf), 'pa': int(pa), 'm': int(m),
                           'exp': num(exp), 'tot': num(r.total_line), 'res': 'W' if m > 0 else ('L' if m < 0 else 'T'), 'd': str(r.gameday)})
            res[(r.game_id, tm)] = (side == 'home', 'W' if m > 0 else ('L' if m < 0 else 'T'))
    for k in tg:
        tg[k].sort(key=lambda x: x['wk'])
    left = g[g.home_score.isna()]
    cw = int(left.week.min()) if len(left) else int(g.week.max())
    slate = []
    for r in g[g.week == cw].itertuples():
        slate.append({'id': r.game_id, 'wk': cw, 'date': r.gameday, 'time': r.gametime, 'away': r.away_team, 'home': r.home_team,
                      'final': not pd.isna(r.home_score), 'as': inum(r.away_score), 'hs': inum(r.home_score),
                      'stad': r.stadium_id, 'sname': r.stadium, 'temp': num(r.temp), 'wind': num(r.wind),
                      'spread': num(r.spread_line), 'total': num(r.total_line), 'aml': num(r.away_moneyline), 'hml': num(r.home_moneyline),
                      'espn': str(int(r.espn)) if 'espn' in g.columns and not pd.isna(r.espn) else None})
    p = pw[(pw.season == season) & (pw.season_type == 'REG') & pw.position.isin(['QB', 'RB', 'WR', 'TE'])].copy()
    players = []
    for pid, d in p.groupby('player_id'):
        if (d.attempts.fillna(0).sum() + d.carries.fillna(0).sum() + d.targets.fillna(0).sum()) < 1:
            continue
        gl = []
        for r in d.sort_values('week').itertuples():
            key = (r.game_id, r.team)
            if key not in res:
                continue
            h, w = res[key]
            gl.append({'wk': int(r.week), 'opp': r.opponent_team, 'home': h, 'res': w,
                       's': {k: (float(getattr(r, k)) if not pd.isna(getattr(r, k)) else 0.0) for k in KEYS}})
        if gl:
            players.append({'id': pid, 'name': d.player_display_name.iloc[-1], 'team': d.team.iloc[-1], 'pos': d.position.iloc[0], 'g': gl})
    add_moves('nfl', slate, key='espn')
    now = pd.Timestamp.now(tz='America/New_York')
    return {'season': season, 'week': cw, 'updated': now.strftime('%b %-d, %Y %-I:%M %p ET'), 'updatedISO': now.isoformat(),
            'teams': TEAMS, 'tg': tg, 'slate': slate, 'players': players}


def build_ou(games, teams):
    conf = dict(zip(teams.team_abbr, teams.team_conf))
    for o, n in [('OAK', 'LV'), ('SD', 'LAC'), ('STL', 'LA')]:
        conf.setdefault(o, conf.get(n))
    g = games[(games.season >= 2015) & games.total.notna() & games.total_line.notna() & games.spread_line.notna()]

    def slot(r):
        d = r.weekday; h = int(str(r.gametime)[:2]) if isinstance(r.gametime, str) else 13
        if d == 'Thursday': return 'TNF'
        if d == 'Monday': return 'MNF'
        if d == 'Saturday': return 'SAT'
        if d == 'Sunday':
            if h < 12: return 'INT'
            if h < 15: return 'E'
            if h < 19: return 'L'
            return 'SNF'
        return 'OTH'
    rows = []
    for r in g.itertuples():
        wk = PO.get(r.game_type, int(r.week))
        m = 'D' if r.div_game == 1 else ('C' if conf.get(r.away_team) == conf.get(r.home_team) else 'N')
        roof = 'D' if r.roof in ('dome', 'closed') else 'O' if r.roof == 'open' else 'X'
        rows.append([int(r.season), wk, slot(r), m, roof, inum(r.temp), inum(r.wind), float(r.spread_line), float(r.total_line),
                     int(r.total), r.away_team, r.home_team, int(r.away_score), int(r.home_score),
                     1 if r.location == 'Neutral' else 0, inum(r.away_rest), inum(r.home_rest), r.gameday])
    return rows


def build_pp(games, pw, seasons):
    S = ['completions','attempts','passing_yards','passing_tds','carries','rushing_yards','rushing_tds','receptions','targets','receiving_yards','receiving_tds']
    gmap = {r.game_id: (r.game_type, r.home_team) for r in games.itertuples()}
    d = pw[pw.season.isin(seasons) & pw.season_type.isin(['REG', 'POST'])].copy()
    d[S] = d[S].fillna(0)
    d = d[d[S].abs().sum(axis=1) > 0]
    players, plist, out = {}, [], {}
    for r in d.itertuples():
        gt, home = gmap.get(r.game_id, ('REG', None))
        wk = PO.get(gt, int(r.week)) if r.season_type == 'POST' else int(r.week)
        key = (r.game_id, r.team)
        if key not in out:
            out[key] = [int(r.season), wk, r.team, r.opponent_team, 1 if home == r.team else 0, []]
        if r.player_id not in players:
            pos = r.position if r.position in ('QB', 'RB', 'WR', 'TE') else ('RB' if r.position == 'FB' else 'OT')
            players[r.player_id] = len(plist); plist.append([r.player_display_name, pos])
        out[key][5].append([players[r.player_id]] + [int(getattr(r, k)) for k in S])
    return {'p': plist, 'g': sorted(out.values(), key=lambda x: (x[0], x[1], x[3])), 'k': S}


FTD_POS = ('QB', 'RB', 'WR', 'TE', 'DST', 'OTH')


def build_ftd(pw, seasons):
    """First touchdown of each game, credited against the defense it was scored on.

    For every game, the first touchdown (by game clock) is attributed to the team that allowed it
    (the scoring team's opponent) and to the scorer's position: QB, RB (incl. FB), WR, TE,
    DST (any defensive or special-teams return TD) or OTH. Ranks compare defenses on first
    touchdowns only: #1 = allowed the most first TDs to that position.
    """
    pos_of = {}
    for r in pw[['player_id', 'position']].dropna().itertuples():
        pos_of[r.player_id] = 'RB' if r.position in ('FB', 'HB') else r.position
    cols = ['game_id', 'season', 'week', 'season_type', 'posteam', 'defteam', 'home_team', 'away_team',
            'touchdown', 'td_team', 'td_player_id', 'td_player_name', 'return_touchdown', 'game_seconds_remaining']
    out = {}
    for y in seasons:
        try:
            d = pd.read_parquet(io.BytesIO(urllib.request.urlopen(PBP_URL.format(y), timeout=180).read()), columns=cols)
        except Exception as e:  # current season file may not exist before week 1
            print('skip pbp', y, e)
            continue
        d = d[d.season_type.isin(['REG', 'POST'])]
        played = {}
        for g in d[['game_id', 'home_team', 'away_team']].drop_duplicates('game_id').itertuples():
            for t in (g.home_team, g.away_team):
                played[t] = played.get(t, 0) + 1
        td = d[(d.touchdown == 1) & d.td_team.notna()].sort_values(['game_id', 'game_seconds_remaining'], ascending=[True, False])
        first = td.groupby('game_id').head(1)
        cnt = {t: {p: 0 for p in FTD_POS} for t in played}
        log = {t: [] for t in played}
        for r in first.itertuples():
            allowed_by = r.away_team if r.td_team == r.home_team else r.home_team
            if r.return_touchdown == 1 or r.td_team == r.defteam:
                pos = 'DST'
            else:
                pos = pos_of.get(r.td_player_id, 'OTH')
                pos = pos if pos in FTD_POS else 'OTH'
            cnt[allowed_by][pos] += 1
            log[allowed_by].append([int(r.week), r.td_team, r.td_player_name or '', pos])
        rk = {}
        for p in FTD_POS:
            for t in cnt:
                rk.setdefault(t, {})[p] = 1 + sum(1 for o in cnt if cnt[o][p] > cnt[t][p])
        ties = {p: {} for p in FTD_POS}
        for p in FTD_POS:
            for t in cnt:
                ties[p][cnt[t][p]] = ties[p].get(cnt[t][p], 0) + 1
        out[str(y)] = {'gp': played, 'c': cnt, 'rk': rk, 'tie': {p: {t: ties[p][cnt[t][p]] > 1 for t in cnt} for p in FTD_POS},
                       'log': {t: sorted(v) for t, v in log.items()}, 'thru': int(d.week.max())}
    return out


def main():
    ap = argparse.ArgumentParser(); ap.add_argument('--out', default='out'); a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    games = fetch_csv(GAMES_URL); teams = fetch_csv(TEAMS_URL)
    season = int(games[(games.game_type == 'REG')].season.max())
    seasons = [season - 2, season - 1, season]
    frames = []
    for y in seasons:
        try:
            frames.append(fetch_csv(PSTATS_URL.format(y)))
        except Exception as e:  # current season file may not exist before week 1
            print('skip player stats', y, e)
    pw = pd.concat(frames)
    cur = build_current(games, teams, pw, season)
    cur['ftd'] = build_ftd(pw, [season - 1, season])
    files = {'nfl.json': cur, 'ou_hist.json': build_ou(games, teams), 'pp_hist.json': build_pp(games, pw, seasons)}
    for name, obj in files.items():
        s = json.dumps(obj, separators=(',', ':'))
        open(os.path.join(a.out, name), 'w').write(s)
        print(name, len(s))
    nfl = files['nfl.json']
    print('season', season, 'week', nfl['week'], 'slate', len(nfl['slate']), 'players', len(nfl['players']))


if __name__ == '__main__':
    main()
