"""Opening vs current lines for a slate, from ESPN's public scoreboard (DraftKings odds).

ESPN's scoreboard odds carry an `open` and a `close` (= current, until kickoff) for the spread,
total and moneyline. Odds drop off the scoreboard once a game starts, so finished games keep no movement.
Spreads use the site's convention: positive = home team favored.
"""
import json
import urllib.request

SB = {
    "nfl": "https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard?dates={d}",
    "ncaaf": "https://site.api.espn.com/apis/site/v2/sports/football/college-football/scoreboard?groups=80&limit=400&dates={d}",
    "nba": "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard?dates={d}",
    "ncaab": "https://site.api.espn.com/apis/site/v2/sports/basketball/mens-college-basketball/scoreboard?groups=50&limit=500&dates={d}",
}


def _num(s):
    if s is None:
        return None
    s = str(s).strip().lower().lstrip("ou")
    if s in ("even", "ev"):
        return 100.0
    if s in ("pk", "pick"):
        return 0.0
    try:
        return float(s.replace("+", ""))
    except ValueError:
        return None


def parse_move(o):
    """ESPN scoreboard odds object -> {so, sc, to, tc, hmo, hmc, amo, amc} or None."""
    if not o:
        return None
    ps, tt, ml = o.get("pointSpread") or {}, o.get("total") or {}, o.get("moneyline") or {}
    g = lambda d, side, when, k: _num(((d.get(side) or {}).get(when) or {}).get(k))
    hso, hsc = g(ps, "home", "open", "line"), g(ps, "home", "close", "line")
    m = {
        "so": None if hso is None else -hso, "sc": None if hsc is None else -hsc,
        "to": g(tt, "over", "open", "line"), "tc": g(tt, "over", "close", "line"),
        "hmo": g(ml, "home", "open", "odds"), "hmc": g(ml, "home", "close", "odds"),
        "amo": g(ml, "away", "open", "odds"), "amc": g(ml, "away", "close", "odds"),
    }
    return m if m["so"] is not None or m["to"] is not None else None


def add_moves(sport, slate, key="id"):
    """Attach `mv` to each slate game (matched on ESPN event id in slate[key]). Never raises."""
    moves = {}
    for d in sorted({str(g.get("date", "")).replace("-", "") for g in slate if g.get("date")}):
        try:
            req = urllib.request.Request(SB[sport].format(d=d), headers={"user-agent": "mybettingbuddy"})
            data = json.load(urllib.request.urlopen(req, timeout=30))
        except Exception as e:  # movement is a nice-to-have; never break the build
            print("moves: scoreboard fail", sport, d, e)
            continue
        for ev in data.get("events", []):
            odds = ((ev.get("competitions") or [{}])[0].get("odds") or [None])[0]
            m = parse_move(odds)
            if m:
                moves[str(ev["id"])] = m
    n = 0
    for g in slate:
        m = moves.get(str(g.get(key)))
        if m:
            g["mv"] = m
            n += 1
    print("moves:", sport, n, "of", len(slate), "games")
    return n
