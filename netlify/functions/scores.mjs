// Live scores for this week's games, from ESPN's public scoreboard: ?sport=nfl (default), ncaaf (FBS), nba or ncaab (D1).
// Netlify's CDN caches each sport's response for 60 seconds, so every visitor shares one lookup a minute.
const ESPN = {
  nfl: "https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard",
  ncaaf: "https://site.api.espn.com/apis/site/v2/sports/football/college-football/scoreboard?groups=80&limit=300",
  nba: "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard",
  ncaab: "https://site.api.espn.com/apis/site/v2/sports/basketball/mens-college-basketball/scoreboard?groups=50&limit=500",
};
const NFL_ABBR = { WSH: "WAS", LAR: "LA" }; // ESPN -> nflverse team codes

// opening vs current line (DraftKings via ESPN); odds leave the scoreboard once a game starts
const num = (s) => { if (s == null) return null; s = String(s).trim().toLowerCase().replace(/^[ou]/, ""); if (s === "even" || s === "ev") return 100; if (s === "pk") return 0; const v = parseFloat(s); return isNaN(v) ? null : v; };
function move(o) {
  if (!o) return null;
  const at = (d, side, when, k) => num(d?.[side]?.[when]?.[k]);
  const ps = o.pointSpread, tt = o.total, ml = o.moneyline;
  const hso = at(ps, "home", "open", "line"), hsc = at(ps, "home", "close", "line");
  const m = { so: hso == null ? null : -hso, sc: hsc == null ? null : -hsc, to: at(tt, "over", "open", "line"), tc: at(tt, "over", "close", "line"),
    hmo: at(ml, "home", "open", "odds"), hmc: at(ml, "home", "close", "odds"), amo: at(ml, "away", "open", "odds"), amc: at(ml, "away", "close", "odds") };
  return m.so != null || m.to != null ? m : null;
}

export default async (req) => {
  const q = new URL(req.url).searchParams.get("sport");
  const sport = ESPN[q] ? q : "nfl";
  const ABBR = sport === "nfl" ? NFL_ABBR : {};
  let d;
  try {
    const r = await fetch(ESPN[sport], { headers: { "user-agent": "mybettingbuddy" } });
    if (!r.ok) throw new Error(String(r.status));
    d = await r.json();
  } catch (e) {
    return new Response(JSON.stringify({ error: "Scoreboard unavailable" }), { status: 502, headers: { "content-type": "application/json" } });
  }
  const games = (d.events || []).map((ev) => {
    const c = (ev.competitions || [])[0] || {};
    const side = (h) => (c.competitors || []).find((x) => x.homeAway === h) || {};
    const home = side("home"), away = side("away");
    const code = (t) => ABBR[t?.team?.abbreviation] || t?.team?.abbreviation;
    return {
      home: code(home), away: code(away),
      hs: home.score != null ? Number(home.score) : null, as: away.score != null ? Number(away.score) : null,
      state: ev.status?.type?.state, // pre | in | post
      detail: ev.status?.type?.shortDetail, // e.g. "Q3 5:12", "Halftime", "Final"
      mv: move((c.odds || [])[0]),
    };
  });
  return new Response(JSON.stringify({ updated: new Date().toISOString(), games }), {
    headers: {
      "content-type": "application/json",
      "cache-control": "public, max-age=30",
      "netlify-cdn-cache-control": "public, durable, s-maxage=60, stale-while-revalidate=30",
      "netlify-vary": "query=sport",
    },
  });
};

export const config = {
  path: "/api/scores",
  rateLimit: { windowLimit: 60, windowSize: 60, aggregateBy: ["ip", "domain"] },
};
