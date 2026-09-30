"""Build the site's data files from nflverse.

Writes three JSON files to --out (default: out/):
  nfl.json      current season: teams, team game logs, this week's slate, player game logs
  ou_hist.json  every game since 2015 with its pregame spread/total (O/U and Spread Splicers)
  pp_hist.json  player game logs by opposing defense, last three seasons (Player Prop Splicer)

Run by GitHub Actions on a schedule; also runnable locally:  python scripts/build_data.py --out out
"""
import argparse, io, json, math, os, urllib.request
import pandas as pd

GAMES_URL = "https://raw.githubusercontent.com/nflverse/nfldata/master/data/games.csv"
TEAMS_URL = "https://github.com/nflverse/nflverse-data/releases/download/teams/teams_colors_logos.csv"
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
                           'exp': num(exp), 'tot': num(r.total_line), 'res': 'W' if m > 0 else ('L' if m < 0 else 'T')})
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
                      'spread': num(r.spread_line), 'total': num(r.total_line), 'aml': num(r.away_moneyline), 'hml': num(r.home_moneyline)})
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
    files = {'nfl.json': build_current(games, teams, pw, season), 'ou_hist.json': build_ou(games, teams), 'pp_hist.json': build_pp(games, pw, seasons)}
    for name, obj in files.items():
        s = json.dumps(obj, separators=(',', ':'))
        open(os.path.join(a.out, name), 'w').write(s)
        print(name, len(s))
    nfl = files['nfl.json']
    print('season', season, 'week', nfl['week'], 'slate', len(nfl['slate']), 'players', len(nfl['players']))


if __name__ == '__main__':
    main()
