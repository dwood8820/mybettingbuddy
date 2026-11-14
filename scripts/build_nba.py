"""Build NBA data files.

  nba.json          current season: teams, team game logs vs closing lines, today's slate with lines, player game logs
  nba_ou_hist.json  every game since 2015-16 with a closing line (Over/Under and Spread graphs)
  nba_pp_hist.json  player games by opposing defense, last three seasons (Player Prop graph)
  nba_lines.json    cache of closing lines by ESPN game id, so each past game's line is fetched once

Box scores: sportsdataverse (ESPN data) releases on GitHub, updated daily.
Lines: ESPN scoreboard (today's DraftKings line) and ESPN's odds feed (closing lines for finished games).
"""
import argparse, io, json, os, sys, time, urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from espn_moves import add_moves  # opening vs current lines

REL = "https://github.com/sportsdataverse/sportsdataverse-data/releases/download"
SITE = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba"
CORE = "https://sports.core.api.espn.com/v2/sports/basketball/leagues/nba"
FIRST = 2016  # the 2015-16 season
CONF = {  # team -> (conference, division)
    "BOS": ("East", "Atlantic"), "BKN": ("East", "Atlantic"), "NY": ("East", "Atlantic"), "PHI": ("East", "Atlantic"), "TOR": ("East", "Atlantic"),
    "CHI": ("East", "Central"), "CLE": ("East", "Central"), "DET": ("East", "Central"), "IND": ("East", "Central"), "MIL": ("East", "Central"),
    "ATL": ("East", "Southeast"), "CHA": ("East", "Southeast"), "MIA": ("East", "Southeast"), "ORL": ("East", "Southeast"), "WSH": ("East", "Southeast"),
    "DEN": ("West", "Northwest"), "MIN": ("West", "Northwest"), "OKC": ("West", "Northwest"), "POR": ("West", "Northwest"), "UTAH": ("West", "Northwest"),
    "GS": ("West", "Pacific"), "LAC": ("West", "Pacific"), "LAL": ("West", "Pacific"), "PHX": ("West", "Pacific"), "SAC": ("West", "Pacific"),
    "DAL": ("West", "Southwest"), "HOU": ("West", "Southwest"), "MEM": ("West", "Southwest"), "NO": ("West", "Southwest"), "SA": ("West", "Southwest"),
}
PSTAT = ["points", "rebounds", "assists", "three_point_field_goals_made", "steals", "blocks", "minutes"]


def get_json(url, tries=4):
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "mybettingbuddy-data"})
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.loads(r.read())
        except Exception:
            if i == tries - 1:
                raise
            time.sleep(1.5 * (i + 1))


def get_parquet(url):
    req = urllib.request.Request(url, headers={"User-Agent": "mybettingbuddy-data"})
    with urllib.request.urlopen(req, timeout=180) as r:
        return pd.read_parquet(io.BytesIO(r.read()))


def num(x):
    try:
        v = float(x)
        return None if v != v else v
    except (TypeError, ValueError):
        return None


def parse_odds(o):
    if not o:
        return None
    sp = num(o.get("spread"))
    h, a = o.get("homeTeamOdds") or {}, o.get("awayTeamOdds") or {}
    if sp is not None:
        if h.get("favorite") is True:
            sp = abs(sp)
        elif a.get("favorite") is True:
            sp = -abs(sp)
        else:
            sp = -sp
    mlo = o.get("moneyline") or {}
    def ml(t, side):
        if t.get("moneyLine") is not None:
            return num(t.get("moneyLine"))
        s = ((mlo.get(side) or {}).get("close") or {}).get("odds")
        return num(str(s).replace("EVEN", "100")) if s not in (None, "", "OFF") else None
    return {"spread": sp, "total": num(o.get("overUnder")), "hml": ml(h, "home"), "aml": ml(a, "away")}


def closing_line(gid):
    try:
        d = get_json(f"{CORE}/events/{gid}/competitions/{gid}/odds")
    except Exception:
        return None
    for it in sorted(d.get("items", []), key=lambda x: (x.get("provider") or {}).get("priority", 99)):
        o = parse_odds(it)
        if o and (o["spread"] is not None or o["total"] is not None):
            return o
    return None


def scoreboard(day):
    try:
        d = get_json(f"{SITE}/scoreboard?dates={day:%Y%m%d}")
    except Exception as e:
        print("scoreboard fail", day, e, file=sys.stderr)
        return []
    out = []
    for ev in d.get("events", []):
        c = ev["competitions"][0]
        comp = {x["homeAway"]: x for x in c["competitors"]}
        if set(comp) != {"home", "away"}:
            continue
        st = ev["status"]["type"]
        t = pd.Timestamp(ev["date"]).tz_convert("America/New_York")
        out.append({"id": ev["id"], "date": t.strftime("%Y-%m-%d"), "time": t.strftime("%H:%M"),
                    "away": comp["away"]["team"]["abbreviation"], "home": comp["home"]["team"]["abbreviation"],
                    "final": bool(st.get("completed")), "state": st.get("state"),
                    "as": int(comp["away"]["score"]) if st.get("state") != "pre" else None,
                    "hs": int(comp["home"]["score"]) if st.get("state") != "pre" else None,
                    "sname": (c.get("venue") or {}).get("fullName"), "odds": parse_odds((c.get("odds") or [None])[0])})
    return out


def week_of(day, start):
    return (day - start).days // 7 + 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="out")
    ap.add_argument("--cache", default="")
    ap.add_argument("--no-espn", action="store_true", help="skip ESPN calls (offline test)")
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    now = pd.Timestamp.now(tz="America/New_York")
    season = now.year + 1 if now.month >= 8 else now.year

    # ---- box scores
    def tb(y):
        try:
            return get_parquet(f"{REL}/espn_nba_team_boxscores/team_box_{y}.parquet")
        except Exception as e:
            print("team box missing", y, e)
            return None
    with ThreadPoolExecutor(6) as ex:
        tbs = [d for d in ex.map(tb, range(FIRST, season + 1)) if d is not None]
    T = pd.concat(tbs)
    T = T[T.team_abbreviation.isin(CONF) & T.opponent_team_abbreviation.isin(CONF) & T.season_type.isin([2, 3, 5])]
    T = T[T.team_score.notna() & (T.team_score + T.opponent_team_score > 0)]
    games = T[T.team_home_away == "home"].copy()
    games["tip"] = pd.to_datetime(games.game_date_time)
    print("games", len(games))

    # ---- closing lines (cached)
    cache = {}
    if a.cache:
        try:
            cache = get_json(a.cache) if a.cache.startswith("http") else json.load(open(a.cache))
        except Exception as e:
            print("no cache", e)
    if not a.no_espn:
        need = [str(g) for g in games.game_id if str(g) not in cache]
        print("closing lines to fetch", len(need))
        with ThreadPoolExecutor(16) as ex:
            for gid, line in zip(need, ex.map(closing_line, need)):
                cache[gid] = line
    json.dump(cache, open(os.path.join(a.out, "nba_lines.json"), "w"), separators=(",", ":"))

    # ---- per-season week numbers and rest days
    games = games.sort_values("tip")
    starts = games[games.season_type == 2].groupby("season").game_date.min().to_dict()
    pstarts = games[games.season_type != 2].groupby("season").game_date.min().to_dict()
    last, rest = {}, {}
    for r in games.itertuples():
        for side, tm in (("a", r.opponent_team_abbreviation), ("h", r.team_abbreviation)):
            k = (r.season, tm)
            rest[(r.game_id, side)] = (r.game_date - last[k]).days if k in last else None
            last[k] = r.game_date

    def wk(r):
        if r.season_type == 2:
            return week_of(r.game_date, starts[r.season])
        return 40 + week_of(r.game_date, pstarts[r.season])

    rows = []
    for r in games.itertuples():
        ln = cache.get(str(r.game_id))
        if not ln or ln.get("spread") is None or ln.get("total") is None:
            continue
        h, aw = r.team_abbreviation, r.opponent_team_abbreviation
        m = "D" if CONF[h] == CONF[aw] else "C" if CONF[h][0] == CONF[aw][0] else "N"
        hr_ = r.tip.hour
        slot = "AFT" if hr_ < 18 else "EVE" if hr_ < 22 else "LATE"
        rows.append([int(r.season), wk(r), slot, m, "D", None, None, ln["spread"], ln["total"],
                     int(r.team_score + r.opponent_team_score), aw, h, int(r.opponent_team_score), int(r.team_score),
                     0, rest[(r.game_id, "a")], rest[(r.game_id, "h")], str(r.game_date), None])

    # ---- current season: teams, team logs, slate
    cur = T[T.season == season].sort_values("game_date_time")
    teams = {}
    for r in T[T.season == T.season.max()].drop_duplicates("team_abbreviation").itertuples():
        teams[r.team_abbreviation] = {"name": r.team_display_name, "nick": r.team_name, "short": r.team_short_display_name,
                                      "c1": "#" + str(r.team_color or "333333"), "c2": "#" + str(r.team_alternate_color or "ffffff"),
                                      "conf": CONF[r.team_abbreviation][0], "div": CONF[r.team_abbreviation][1]}
    tg = {k: [] for k in teams}
    for r in cur.itertuples():
        ln = cache.get(str(r.game_id)) or {}
        sp = ln.get("spread")
        home = r.team_home_away == "home"
        exp = None if sp is None else (sp if home else -sp)
        mg = int(r.team_score - r.opponent_team_score)
        d = pd.Timestamp(r.game_date)
        tg[r.team_abbreviation].append({"wk": len(tg[r.team_abbreviation]) + 1, "lbl": f"{d.month}/{d.day}", "opp": r.opponent_team_abbreviation,
                                        "home": home, "pf": int(r.team_score), "pa": int(r.opponent_team_score), "m": mg, "exp": exp,
                                        "tot": ln.get("total"), "res": "W" if mg > 0 else "L", "gid": int(r.game_id)})

    slate, label = [], ""
    if not a.no_espn:
        today = now.normalize().tz_localize(None)
        for off in range(0, 8):
            day = (today + timedelta(days=off)).to_pydatetime()
            sb = scoreboard(day)
            if sb and (off > 0 or not all(g["final"] for g in sb)):
                slate, label = sb, day.strftime("%a, %b %-d")
                break
    for g in slate:
        o = g.pop("odds") or cache.get(g["id"]) or (None if a.no_espn else closing_line(g["id"])) or {}
        g.update({"spread": o.get("spread"), "total": o.get("total"), "aml": o.get("aml"), "hml": o.get("hml"), "wk": label})

    # ---- players (current season) and prop history (last three seasons)
    def pb(y):
        try:
            return get_parquet(f"{REL}/espn_nba_player_boxscores/player_box_{y}.parquet")
        except Exception as e:
            print("player box missing", y, e)
            return None
    with ThreadPoolExecutor(3) as ex:
        pbs = [d for d in ex.map(pb, range(season - 2, season + 1)) if d is not None]
    P = pd.concat(pbs)
    P = P[P.team_abbreviation.isin(CONF) & P.opponent_team_abbreviation.isin(CONF) & P.season_type.isin([2, 3, 5])]
    P = P[(P.did_not_play != True) & (P.minutes.fillna(0) > 0)].copy()
    P[PSTAT] = P[PSTAT].fillna(0)
    grp = lambda pos: "C" if pos == "C" else "G" if pos in ("PG", "SG", "G") else "F"

    pc = P[P.season == season].sort_values("game_date")
    players = []
    team_gno = {(g["gid"], tm): g["wk"] for tm, lst in tg.items() for g in lst}
    for pid, d in pc.groupby("athlete_id"):
        if len(d) < 2 or d.minutes.mean() < 12:
            continue
        gl = []
        for r in d.itertuples():
            dt = pd.Timestamp(r.game_date)
            gl.append([team_gno.get((int(r.game_id), r.team_abbreviation), 0), f"{dt.month}/{dt.day}", r.opponent_team_abbreviation,
                       1 if r.home_away == "home" else 0, "W" if r.team_winner else "L",
                       int(r.points), int(r.rebounds), int(r.assists), int(r.three_point_field_goals_made),
                       int(r.steals), int(r.blocks), int(round(r.minutes))])
        last_ = d.iloc[-1]
        players.append({"id": str(int(pid)), "name": last_.athlete_display_name, "team": last_.team_abbreviation,
                        "pos": last_.athlete_position_abbreviation or "F", "grp": grp(last_.athlete_position_abbreviation), "g": gl})

    allstart = {**{s: d for s, d in starts.items()}}
    pidx, plist, out = {}, [], {}
    P = P.sort_values("game_date")
    for r in P[P.minutes >= 8].itertuples():
        s = int(r.season)
        if r.season_type == 2 and s in starts:
            w = week_of(r.game_date, starts[s])
        elif s in pstarts:
            w = 40 + week_of(r.game_date, pstarts[s])
        else:
            continue
        key = (r.game_id, r.team_abbreviation)
        if key not in out:
            gd = pd.Timestamp(r.game_date)
            out[key] = [s, w, r.team_abbreviation, r.opponent_team_abbreviation, 1 if r.home_away == "home" else 0, [], f"{gd.month}/{gd.day}"]
        if r.athlete_id not in pidx:
            pidx[r.athlete_id] = len(plist); plist.append([r.athlete_display_name, grp(r.athlete_position_abbreviation)])
        out[key][5].append([pidx[r.athlete_id], int(r.points), int(r.rebounds), int(r.assists), int(r.three_point_field_goals_made),
                            int(r.steals), int(r.blocks), int(round(r.minutes))])
    pp = {"p": plist, "g": sorted(out.values(), key=lambda x: (x[0], x[1], x[3])),
          "k": ["points", "rebounds", "assists", "threes", "steals", "blocks", "minutes"]}

    add_moves("nba", slate)
    cur_json = {"sport": "nba", "season": season, "week": label or "", "weekLabel": label,
                "updated": now.strftime("%b %-d, %Y %-I:%M %p ET"), "teams": teams, "tg": tg, "slate": slate,
                "pkeys": ["wk", "lbl", "opp", "home", "res", "points", "rebounds", "assists", "threes", "steals", "blocks", "minutes"],
                "players": players}
    for name, obj in (("nba.json", cur_json), ("nba_ou_hist.json", rows), ("nba_pp_hist.json", pp)):
        s = json.dumps(obj, separators=(",", ":"))
        open(os.path.join(a.out, name), "w").write(s)
        print(name, len(s))
    print("season", season, "slate", label, len(slate), "teams", len(teams), "players", len(players), "hist rows", len(rows),
          "lines cached", sum(1 for v in cache.values() if v))


if __name__ == "__main__":
    main()
