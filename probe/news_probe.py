import json, os, urllib.request
os.makedirs("pout", exist_ok=True)
def get(u):
    r = urllib.request.urlopen(urllib.request.Request(u, headers={"User-Agent": "mybettingbuddy"}), timeout=60)
    return json.loads(r.read())
L = {"nfl": "football/nfl", "ncaaf": "football/college-football", "nba": "basketball/nba", "ncaab": "basketball/mens-college-basketball"}
res = {}
for k, path in L.items():
    out = {}
    try:
        q = "?groups=80&limit=300" if k == "ncaaf" else "?groups=50&limit=400" if k == "ncaab" else ""
        sb = get(f"https://site.api.espn.com/apis/site/v2/sports/{path}/scoreboard{q}")
        evs = sb.get("events", [])
        # prefer a game that hasn't started, with notable teams
        ev = next((e for e in evs if e["status"]["type"]["state"] == "pre"), evs[0] if evs else None)
        out["event"] = ev and {"id": ev["id"], "name": ev["name"]}
        s = get(f"https://site.api.espn.com/apis/site/v2/sports/{path}/summary?event={ev['id']}")
        out["keys"] = list(s.keys())
        inj = s.get("injuries") or []
        out["injuries_teams"] = len(inj)
        out["injuries_sample"] = [{"team": (t.get("team") or {}).get("abbreviation"), "n": len(t.get("injuries", [])),
                                   "first": (t.get("injuries") or [None])[:2]} for t in inj]
        news = s.get("news") or {}
        arts = news.get("articles", []) if isinstance(news, dict) else news
        out["news_n"] = len(arts)
        out["news_sample"] = arts[:2]
        out["article"] = s.get("article") and {k2: s["article"].get(k2) for k2 in ("headline", "description", "published")}
        # team news feed
        tid = ev["competitions"][0]["competitors"][0]["team"]["id"]
        tn = get(f"https://site.api.espn.com/apis/site/v2/sports/{path}/news?team={tid}&limit=5")
        out["team_news_n"] = len(tn.get("articles", []))
        out["inj_full"] = (inj[0].get("injuries") or [None])[0] if inj else None
        out["team_news_full"] = tn.get("articles", [])[:2]
        out["team_news_sample"] = [{k2: a.get(k2) for k2 in ("headline", "description", "published", "type")} | {"link": ((a.get("links") or {}).get("web") or {}).get("href")} for a in tn.get("articles", [])[:3]]
    except Exception as e:
        out["error"] = repr(e)
    res[k] = out
json.dump(res, open("pout/news_probe.json", "w"), indent=1, default=str)
print({k: (v.get("event"), v.get("injuries_teams"), v.get("news_n"), v.get("team_news_n"), v.get("error")) for k, v in res.items()})
