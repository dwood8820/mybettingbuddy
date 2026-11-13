"""Build NCAAF (FBS) data files from ESPN.

  ncaaf.json          current season: FBS teams, team game logs vs closing lines, this week's slate with lines + weather
  ncaaf_ou_hist.json  every FBS-vs-FBS game with a closing line since 2015 (Over/Under and Spread graphs)
  ncaaf_lines.json    cache of closing lines by ESPN event id, so each past game's line is fetched only once

Lines: ESPN's scoreboard carries this week's DraftKings line; finished games' closing lines come from
ESPN's odds feed for that game.  Only games where both teams are FBS are kept.
"""
import argparse, json, os, sys, time, urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone, timedelta

SITE = "https://site.api.espn.com/apis/site/v2/sports/football/college-football"
CORE = "https://sports.core.api.espn.com/v2/sports/football/leagues/college-football"
FBS_CONF = {"1": "ACC", "4": "Big 12", "5": "Big Ten", "8": "SEC", "9": "Pac-12", "12": "C-USA", "15": "MAC",
            "17": "Mountain West", "18": "Independent", "37": "Sun Belt", "151": "American"}
FIRST_HIST = 2015
ET = timezone(timedelta(hours=-5))  # display only; kickoff times are converted with the DST rule below


def get(url, tries=4):
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "mybettingbuddy-data"})
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.loads(r.read())
        except Exception as e:
            if i == tries - 1:
                raise
            time.sleep(1.5 * (i + 1))


def to_et(iso):
    t = datetime.strptime(iso.replace("Z", ""), "%Y-%m-%dT%H:%M").replace(tzinfo=timezone.utc)
    # US Eastern: DST from 2nd Sunday in March to 1st Sunday in November
    y = t.year
    mar = datetime(y, 3, 8, 7, tzinfo=timezone.utc); mar += timedelta(days=(6 - mar.weekday()) % 7)
    nov = datetime(y, 11, 1, 6, tzinfo=timezone.utc); nov += timedelta(days=(6 - nov.weekday()) % 7)
    return t + timedelta(hours=-4 if mar <= t < nov else -5)


def num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def parse_odds(o, home_id):
    """ESPN odds object -> (home-favored spread like nflverse spread_line, total, home ML, away ML)."""
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
            sp = -sp  # ESPN spread is from the home side (negative = home favored)
    ml = lambda t: num(t.get("moneyLine")) if t.get("moneyLine") is not None else None
    return {"spread": sp, "total": num(o.get("overUnder")), "hml": ml(h), "aml": ml(a)}


def week_events(season, stype, week):
    try:
        d = get(f"{SITE}/scoreboard?groups=80&seasontype={stype}&week={week}&dates={season}&limit=400")
    except Exception as e:
        print("scoreboard fail", season, stype, week, e, file=sys.stderr)
        return []
    out = []
    for ev in d.get("events", []):
        c = ev["competitions"][0]
        comp = {x["homeAway"]: x for x in c["competitors"]}
        if "home" not in comp or "away" not in comp:
            continue
        h, a = comp["home"], comp["away"]
        hc, ac = str(h["team"].get("conferenceId")), str(a["team"].get("conferenceId"))
        if hc not in FBS_CONF or ac not in FBS_CONF:
            continue  # FBS vs FBS only
        st = ev["status"]["type"]
        rank = lambda x: (x.get("curatedRank") or {}).get("current") or 99
        w = ev.get("weather") or {}
        ven = c.get("venue") or {}
        out.append({
            "id": ev["id"], "season": season, "stype": stype, "week": week if stype == 2 else 20,
            "date": ev["date"], "done": bool(st.get("completed")), "state": st.get("state"),
            "home": h["team"], "away": a["team"], "hconf": FBS_CONF[hc], "aconf": FBS_CONF[ac],
            "hs": int(h["score"]) if st.get("completed") else None, "as": int(a["score"]) if st.get("completed") else None,
            "hr": rank(h), "ar": rank(a), "neutral": bool(c.get("neutralSite")), "confgame": bool(c.get("conferenceCompetition")),
            "indoor": bool(ven.get("indoor")), "venue": ven.get("fullName"), "city": (ven.get("address") or {}).get("city"),
            "vstate": (ven.get("address") or {}).get("state"), "wx": w.get("displayValue"), "temp": w.get("temperature"),
            "odds": parse_odds((c.get("odds") or [None])[0], h["team"]["id"]),
        })
    return out


def season_events(season):
    evs = []
    for wk in range(1, 17):
        evs += week_events(season, 2, wk)
    evs += week_events(season, 3, 1)
    return evs


def closing_line(eid):
    try:
        d = get(f"{CORE}/events/{eid}/competitions/{eid}/odds")
    except Exception:
        return None
    items = sorted(d.get("items", []), key=lambda x: (x.get("provider") or {}).get("priority", 99))
    for it in items:
        o = parse_odds(it, None)
        if o and (o["spread"] is not None or o["total"] is not None):
            return o
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="out")
    ap.add_argument("--cache", default="", help="URL or path of an existing ncaaf_lines.json")
    ap.add_argument("--first", type=int, default=FIRST_HIST)
    ap.add_argument("--max-new", type=int, default=12000, help="cap on closing-line lookups per run")
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    now = datetime.now(timezone.utc)
    season = now.year if now.month >= 7 else now.year - 1

    cache = {}
    if a.cache:
        try:
            cache = get(a.cache) if a.cache.startswith("http") else json.load(open(a.cache))
        except Exception as e:
            print("no cache", e)
    seasons = list(range(a.first, season + 1))
    with ThreadPoolExecutor(8) as ex:
        all_events = [e for s in ex.map(season_events, seasons) for e in s]
    print("events", len(all_events))

    need = [e["id"] for e in all_events if e["done"] and e["id"] not in cache][: a.max_new]
    print("closing lines to fetch", len(need))
    with ThreadPoolExecutor(16) as ex:
        for eid, line in zip(need, ex.map(closing_line, need)):
            cache[eid] = line
    json.dump(cache, open(os.path.join(a.out, "ncaaf_lines.json"), "w"), separators=(",", ":"))

    def line_of(e):
        if e["done"]:
            return cache.get(e["id"]) or e["odds"]
        return e["odds"]

    # team keys: ESPN abbreviation, made unique
    teams, key_of = {}, {}
    cur = [e for e in all_events if e["season"] == season]
    for e in cur:
        for side, cf in (("home", "hconf"), ("away", "aconf")):
            t = e[side]
            if t["id"] in key_of:
                continue
            k = t.get("abbreviation") or t["id"]
            if k in teams:
                k = f"{k}{t['id']}"
            key_of[t["id"]] = k
            teams[k] = {"name": t.get("displayName"), "nick": t.get("shortDisplayName") or t.get("name"),
                        "c1": "#" + (t.get("color") or "333333"), "c2": "#" + (t.get("alternateColor") or "ffffff"),
                        "conf": e[cf], "logo": t.get("logo")}
    K = lambda t: key_of.get(t["id"])

    tg = {k: [] for k in teams}
    for e in sorted(cur, key=lambda x: x["date"]):
        if not e["done"]:
            continue
        ln = line_of(e) or {}
        for side in ("home", "away"):
            me, op = (e["home"], e["away"]) if side == "home" else (e["away"], e["home"])
            pf, pa = (e["hs"], e["as"]) if side == "home" else (e["as"], e["hs"])
            sp = ln.get("spread")
            exp = None if sp is None else (sp if side == "home" else -sp)
            m = pf - pa
            tg[K(me)].append({"wk": e["week"], "opp": K(op), "home": side == "home" and not e["neutral"], "neutral": e["neutral"],
                              "pf": pf, "pa": pa, "m": m, "exp": exp, "tot": ln.get("total"),
                              "res": "W" if m > 0 else "L" if m < 0 else "T"})

    open_ = [e for e in cur if not e["done"]]
    if open_:
        cw_key = min((e["stype"], e["week"]) for e in open_)
    else:
        cw_key = max((e["stype"], e["week"]) for e in cur)
    slate = []
    for e in sorted(cur, key=lambda x: x["date"]):
        if (e["stype"], e["week"]) != cw_key:
            continue
        t = to_et(e["date"][:16])
        ln = line_of(e) or {}
        slate.append({"id": e["id"], "wk": e["week"], "date": t.strftime("%Y-%m-%d"), "time": t.strftime("%H:%M"),
                      "away": K(e["away"]), "home": K(e["home"]), "aconf": e["aconf"], "hconf": e["hconf"],
                      "ar": e["ar"], "hr": e["hr"], "neutral": e["neutral"], "final": e["done"], "as": e["as"], "hs": e["hs"],
                      "sname": e["venue"], "city": e["city"], "vstate": e["vstate"], "indoor": e["indoor"],
                      "wx": e["wx"], "temp": e["temp"],
                      "spread": ln.get("spread"), "total": ln.get("total"), "aml": ln.get("aml"), "hml": ln.get("hml")})

    nowet = to_et(now.strftime("%Y-%m-%dT%H:%M"))
    cur_json = {"sport": "ncaaf", "season": season, "week": cw_key[1] if cw_key[0] == 2 else "Bowls",
                "updated": nowet.strftime("%b %-d, %Y %-I:%M %p ET"), "teams": teams, "tg": tg, "slate": slate, "players": []}

    # history rows (same layout as the NFL file, plus ranks):
    # [season, week, slot, matchup, roof, temp, wind, spread, total, points, away, home, away pts, home pts,
    #  neutral, away rest, home rest, date, ranked]
    last = {}
    rows = []
    for e in sorted(all_events, key=lambda x: x["date"]):
        t = to_et(e["date"][:16])
        rest = []
        for side in ("away", "home"):
            tid = e[side]["id"]
            rest.append((t - last[tid]).days if tid in last else None)
            last[tid] = t
        if not e["done"]:
            continue
        ln = cache.get(e["id"])
        if not ln or ln.get("spread") is None or ln.get("total") is None:
            continue
        wd, hr = t.strftime("%A"), t.hour
        if wd == "Saturday":
            slot = "SNOON" if hr < 14 else "SAFT" if hr < 18 else "SNIGHT"
        elif wd in ("Tuesday", "Wednesday", "Thursday", "Friday"):
            slot = wd[:3].upper()
        else:
            slot = "OTH"
        ranked = "RR" if e["hr"] <= 25 and e["ar"] <= 25 else "R" if min(e["hr"], e["ar"]) <= 25 else "-"
        rows.append([e["season"], e["week"], slot, "C" if e["confgame"] else "N", "D" if e["indoor"] else "X", None, None,
                     ln["spread"], ln["total"], e["hs"] + e["as"], e["away"].get("abbreviation"), e["home"].get("abbreviation"),
                     e["as"], e["hs"], 1 if e["neutral"] else 0, rest[0], rest[1], t.strftime("%Y-%m-%d"), ranked])

    for name, obj in (("ncaaf.json", cur_json), ("ncaaf_ou_hist.json", rows)):
        s = json.dumps(obj, separators=(",", ":"))
        open(os.path.join(a.out, name), "w").write(s)
        print(name, len(s))
    print("season", season, "week", cur_json["week"], "slate", len(slate), "teams", len(teams), "hist rows", len(rows),
          "slate with lines", sum(1 for g in slate if g["spread"] is not None))


if __name__ == "__main__":
    main()
