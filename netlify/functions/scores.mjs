// Live NFL scores for this week's games, from ESPN's public scoreboard.
// Netlify's CDN caches the response for 60 seconds, so every visitor shares one lookup a minute.
const ESPN = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard";
const ABBR = { WSH: "WAS", LAR: "LA" }; // ESPN -> nflverse team codes

export default async () => {
  let d;
  try {
    const r = await fetch(ESPN, { headers: { "user-agent": "mybettingbuddy" } });
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
    };
  });
  return new Response(JSON.stringify({ updated: new Date().toISOString(), games }), {
    headers: {
      "content-type": "application/json",
      "cache-control": "public, max-age=30",
      "netlify-cdn-cache-control": "public, durable, s-maxage=60, stale-while-revalidate=30",
    },
  });
};

export const config = {
  path: "/api/scores",
  rateLimit: { windowLimit: 60, windowSize: 60, aggregateBy: ["ip", "domain"] },
};
