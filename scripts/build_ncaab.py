"""Build NCAAB (Division I men's) data files.

  ncaab.json          current season: D1 teams + conferences, team game logs vs closing lines, the day's slate with lines
  ncaab_ou_hist.json  D1-vs-D1 games with a closing line since 2019-20 (Over/Under and Spread graphs)
  ncaab_lines.json    cache of closing lines by ESPN game id (each past game's line is fetched once)

Games: sportsdataverse team box scores (ESPN data). Lines + ranks + today's slate: ESPN.
"""
import argparse, io, json, os, sys, time, urllib.request
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from espn_moves import add_moves  # opening vs current lines

REL = "https://github.com/sportsdataverse/sportsdataverse-data/releases/download/espn_mens_college_basketball_team_boxscores"
SITE = "https://site.api.espn.com/apis/site/v2/sports/basketball/mens-college-basketball"
CORE = "https://sports.core.api.espn.com/v2/sports/basketball/leagues/mens-college-basketball"
STAND = "https://site.web.api.espn.com/apis/v2/sports/basketball/mens-college-basketball/standings?group=50"
FIRST = 2020  # the 2019-20 season


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


SHORT = {"Atlantic Coast": "ACC", "Southeastern": "SEC", "Big Ten": "Big Ten", "Big 12": "Big 12", "Big East": "Big East",
         "Atlantic 10": "A-10", "Metro Atlantic Athletic": "MAAC", "Coastal Athletic Association": "CAA", "Ohio Valley": "OVC",
         "Mid-American": "MAC", "Mid-Eastern Athletic": "MEAC", "Southwestern Athletic": "SWAC", "Western Athletic": "WAC",
         "Missouri Valley": "Missouri Valley", "Mountain West": "Mountain West", "West Coast": "WCC", "American Athletic": "American",
         "Conference USA": "C-USA", "Atlantic Sun": "ASUN", "ASUN": "ASUN", "Southern": "SoCon", "Southland": "Southland",
         "Horizon League": "Horizon", "Northeast": "NEC", "Patriot League": "Patriot", "Ivy League": "Ivy", "Big Sky": "Big Sky",
         "Big South": "Big South", "Big West": "Big West", "Summit League": "Summit", "Sun Belt": "Sun Belt", "America East": "America East"}


CODES = {"acc": "ACC", "big10": "Big Ten", "sec": "SEC", "big12": "Big 12", "bige": "Big East", "belt": "Sun Belt", "atl10": "A-10",
         "Metro": "MAAC", "col": "CAA", "American": "American", "midam": "MAC", "land": "Southland", "swac": "SWAC", "bigw": "Big West",
         "hor": "Horizon", "south": "SoCon", "bsky": "Big Sky", "mvc": "Missouri Valley", "usa": "C-USA", "mwest": "Mountain West",
         "pat": "Patriot", "wcc": "WCC", "ovc": "OVC", "bsou": "Big South", "neast": "NEC", "UAC": "UAC", "pac12": "Pac-12",
         "aeast": "America East", "summ": "Summit", "ASUN": "ASUN", "ivy": "Ivy", "meac": "MEAC", "wac": "WAC"}


def conf_name(c):
    for k in (c.get("abbreviation"), c.get("name"), c.get("shortName")):
        if k in CODES:
            return CODES[k]
    raw = c.get("name") or c.get("shortName") or c.get("abbreviation") or ""
    base = raw.replace(" Conference", "").replace(" Men's Basketball", "").strip()
    return SHORT.get(base) or c.get("shortName") or base or raw


def conferences():
    """team id -> conference short name, for every D1 team, from ESPN's standings."""
    out = {}
    try:
        d = get_json(STAND)
        for c in d.get("children", []):
            name = conf_name(c)
            for e in (c.get("standings") or {}).get("entries", []):
                out[str(e["team"]["id"])] = name
    except Exception as e:
        print("standings fail", e, file=sys.stderr)
    return out


def scoreboard(day):
    try:
        d = get_json(f"{SITE}/scoreboard?groups=50&limit=500&dates={day:%Y%m%d}")
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
        rank = lambda x: (x.get("curatedRank") or {}).get("current") or 99
        out.append({"id": ev["id"], "date": t.strftime("%Y-%m-%d"), "time": t.strftime("%H:%M"),
                    "aid": str(comp["away"]["team"]["id"]), "hid": str(comp["home"]["team"]["id"]),
                    "final": bool(st.get("completed")), "state": st.get("state"),
                    "as": int(comp["away"]["score"]) if st.get("state") != "pre" else None,
                    "hs": int(comp["home"]["score"]) if st.get("state") != "pre" else None,
                    "ar": rank(comp["away"]), "hr": rank(comp["home"]), "neutral": bool(c.get("neutralSite")),
                    "sname": (c.get("venue") or {}).get("fullName"), "odds": parse_odds((c.get("odds") or [None])[0]),
                    "teams": {"a": comp["away"]["team"], "h": comp["home"]["team"]}})
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="out")
    ap.add_argument("--cache", default="")
    ap.add_argument("--max-new", type=int, default=22000, help="cap on closing-line lookups per run")
    ap.add_argument("--no-espn", action="store_true")
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    now = pd.Timestamp.now(tz="America/New_York")
    season = now.year + 1 if now.month >= 8 else now.year

    conf = {} if a.no_espn else conferences()
    print("D1 teams from standings", len(conf))

    def tb(y):
        try:
            return get_parquet(f"{REL}/team_box_{y}.parquet")
        except Exception as e:
            print("team box missing", y, e)
            return None
    with ThreadPoolExecutor(6) as ex:
        T = pd.concat([d for d in ex.map(tb, range(FIRST, season + 1)) if d is not None])
    T = T[T.team_score.notna() & (T.team_score + T.opponent_team_score > 0) & T.season_type.isin([2, 3])]
    T["team_id"] = T.team_id.astype(str); T["opponent_team_id"] = T.opponent_team_id.astype(str)
    # Division I = teams in ESPN's D1 standings, plus (for past seasons) anyone with 15+ games that season
    d1 = {}
    for s, d in T.groupby("season"):
        cnt = Counter(d.team_id)
        d1[s] = set(conf) | {t for t, n in cnt.items() if n >= 15}
    T = T[[r_t in d1[s] and r_o in d1[s] for s, r_t, r_o in zip(T.season, T.team_id, T.opponent_team_id)]]
    games = T[T.team_home_away == "home"].copy().sort_values("game_date_time")
    games["tip"] = pd.to_datetime(games.game_date_time)
    print("D1 games", len(games))

    cache = {}
    if a.cache:
        try:
            cache = get_json(a.cache) if a.cache.startswith("http") else json.load(open(a.cache))
        except Exception as e:
            print("no cache", e)
    if not a.no_espn:
        # newest first, so the current and recent seasons fill in before older ones
        need = [str(g) for g in games.game_id[::-1] if str(g) not in cache][: a.max_new]
        print("closing lines to fetch", len(need))
        with ThreadPoolExecutor(16) as ex:
            for gid, line in zip(need, ex.map(closing_line, need)):
                cache[gid] = line
    json.dump(cache, open(os.path.join(a.out, "ncaab_lines.json"), "w"), separators=(",", ":"))

    # team keys: abbreviation, made unique
    key, teams = {}, {}
    cur = T[T.season == season]
    meta = T.sort_values("game_date").drop_duplicates("team_id", keep="last")
    for r in meta.itertuples():
        if r.season < season - 1 and r.team_id not in conf:
            continue
        k = r.team_abbreviation or r.team_id
        if k in teams:
            k = f"{k}{r.team_id}"
        key[r.team_id] = k
        teams[k] = {"name": r.team_display_name, "nick": r.team_short_display_name or r.team_location, "short": r.team_location,
                    "c1": "#" + str(r.team_color or "333333"), "c2": "#" + str(r.team_alternate_color or "ffffff"),
                    "conf": conf.get(r.team_id, "")}
    K = lambda tid: key.get(str(tid))

    starts = games[games.season_type == 2].groupby("season").game_date.min().to_dict()
    pstarts = games[games.season_type == 3].groupby("season").game_date.min().to_dict()
    last, rest = {}, {}
    for r in games.itertuples():
        for side, tm in (("a", r.opponent_team_id), ("h", r.team_id)):
            kk = (r.season, tm)
            rest[(r.game_id, side)] = (r.game_date - last[kk]).days if kk in last else None
            last[kk] = r.game_date
    rows = []
    for r in games.itertuples():
        ln = cache.get(str(r.game_id))
        if not ln or ln.get("spread") is None or ln.get("total") is None:
            continue
        w = ((r.game_date - starts[r.season]).days // 7 + 1) if r.season_type == 2 else 40 + (r.game_date - pstarts[r.season]).days // 7 + 1
        hr_ = r.tip.hour
        slot = "AFT" if hr_ < 18 else "EVE" if hr_ < 21 else "LATE"
        same = conf.get(r.team_id) and conf.get(r.team_id) == conf.get(r.opponent_team_id)
        rows.append([int(r.season), int(w), slot, "C" if same else "N", "D", None, None, ln["spread"], ln["total"],
                     int(r.team_score + r.opponent_team_score), K(r.opponent_team_id) or r.opponent_team_abbreviation,
                     K(r.team_id) or r.team_abbreviation, int(r.opponent_team_score), int(r.team_score), 0,
                     rest[(r.game_id, "a")], rest[(r.game_id, "h")], str(r.game_date), None])

    tg = {}
    for r in cur.sort_values("game_date_time").itertuples():
        k = K(r.team_id)
        if not k:
            continue
        ln = cache.get(str(r.game_id)) or {}
        sp = ln.get("spread")
        home = r.team_home_away == "home"
        mg = int(r.team_score - r.opponent_team_score)
        d = pd.Timestamp(r.game_date)
        lst = tg.setdefault(k, [])
        lst.append({"wk": len(lst) + 1, "lbl": f"{d.month}/{d.day}", "opp": K(r.opponent_team_id), "home": home,
                    "pf": int(r.team_score), "pa": int(r.opponent_team_score), "m": mg,
                    "exp": None if sp is None else (sp if home else -sp), "tot": ln.get("total"), "res": "W" if mg > 0 else "L"})

    slate, label = [], ""
    if not a.no_espn:
        today = now.normalize().tz_localize(None)
        for off in range(0, 8):
            day = (today + timedelta(days=off)).to_pydatetime()
            sb = [g for g in scoreboard(day) if g["aid"] in key and g["hid"] in key]
            if sb and (off > 0 or not all(g["final"] for g in sb)):
                slate, label = sb, day.strftime("%a, %b %-d")
                break
    for g in slate:
        o = g.pop("odds") or cache.get(g["id"]) or closing_line(g["id"]) or {}
        g.pop("teams")
        g.update({"away": key[g.pop("aid")], "home": key[g.pop("hid")], "spread": o.get("spread"), "total": o.get("total"),
                  "aml": o.get("aml"), "hml": o.get("hml"), "wk": label})
        g["aconf"], g["hconf"] = teams[g["away"]]["conf"], teams[g["home"]]["conf"]
    teams = {k: v for k, v in teams.items() if k in tg or any(g["away"] == k or g["home"] == k for g in slate) or v["conf"]}

    add_moves("ncaab", slate)
    cur_json = {"sport": "ncaab", "season": season, "week": label, "weekLabel": label,
                "updated": now.strftime("%b %-d, %Y %-I:%M %p ET"), "teams": teams, "tg": tg, "slate": slate, "players": []}
    for name, obj in (("ncaab.json", cur_json), ("ncaab_ou_hist.json", rows)):
        s = json.dumps(obj, separators=(",", ":"))
        open(os.path.join(a.out, name), "w").write(s)
        print(name, len(s))
    print("season", season, "slate", label, len(slate), "with lines", sum(1 for g in slate if g["spread"] is not None),
          "teams", len(teams), "hist rows", len(rows), "lines cached", sum(1 for v in cache.values() if v), "of", len(cache))


if __name__ == "__main__":
    main()
