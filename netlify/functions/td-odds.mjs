// Anytime TD odds for one NFL game, from The Odds API.
// Your API key lives in Netlify (Site configuration > Environment variables > ODDS_API_KEY),
// never in the page, so visitors can't see or use it.
//
// Credits: listing events is free; each game's anytime-TD odds cost 1 credit (1 market x 1 region).
// Netlify's CDN caches every game's response for CACHE_HOURS, so a game is fetched at most
// once per window no matter how many people look at it. 16 games x 1 fetch/day ~ 480 credits/month,
// which fits the free 500. Lower CACHE_HOURS for fresher odds once you're on a paid plan.

const CACHE_HOURS = Number(Netlify.env.get("CACHE_HOURS") || 24);
const SPORT_KEYS = { nfl: "americanfootball_nfl", ncaaf: "americanfootball_ncaaf" };
const apiFor = (sport) => `https://api.the-odds-api.com/v4/sports/${SPORT_KEYS[sport]}`;

// Only real NFL team names are accepted for the NFL, and plain school names for college, so junk requests never reach The Odds API.
const TEAMS = new Set([
  "Arizona Cardinals","Atlanta Falcons","Baltimore Ravens","Buffalo Bills","Carolina Panthers","Chicago Bears",
  "Cincinnati Bengals","Cleveland Browns","Dallas Cowboys","Denver Broncos","Detroit Lions","Green Bay Packers",
  "Houston Texans","Indianapolis Colts","Jacksonville Jaguars","Kansas City Chiefs","Las Vegas Raiders",
  "Los Angeles Chargers","Los Angeles Rams","Miami Dolphins","Minnesota Vikings","New England Patriots",
  "New Orleans Saints","New York Giants","New York Jets","Philadelphia Eagles","Pittsburgh Steelers",
  "San Francisco 49ers","Seattle Seahawks","Tampa Bay Buccaneers","Tennessee Titans","Washington Commanders",
]);

const json = (body, status = 200, cacheSeconds = 0) =>
  new Response(JSON.stringify(body), {
    status,
    headers: {
      "content-type": "application/json",
      "cache-control": "public, max-age=300",
      ...(cacheSeconds
        ? {
            "netlify-cdn-cache-control": `public, durable, s-maxage=${cacheSeconds}, stale-while-revalidate=3600`,
            // Cache by the two team names only: extra ?junk=1 parameters can't bypass the cache and burn credits.
            "netlify-vary": "query=sport|home|away",
          }
        : {}),
    },
  });

export default async (req) => {
  const key = Netlify.env.get("ODDS_API_KEY");
  if (!key) return json({ error: "ODDS_API_KEY is not set in Netlify environment variables" }, 500);

  const url = new URL(req.url);
  const sport = url.searchParams.get("sport") || "nfl";
  const home = url.searchParams.get("home");
  const away = url.searchParams.get("away");
  const okName = (n) => (sport === "nfl" ? TEAMS.has(n) : /^[A-Za-z0-9&'().\- ]{3,48}$/.test(n));
  if (!SPORT_KEYS[sport] || !home || !away || !okName(home) || !okName(away) || home === away)
    return json({ error: "Pass ?sport=nfl|ncaaf&home=<full team name>&away=<full team name>" }, 400);
  const API = apiFor(sport);

  // Free call: find this game's event id.
  const evRes = await fetch(`${API}/events?apiKey=${key}`);
  if (!evRes.ok) return json({ error: `Odds API events request failed (${evRes.status})` }, 502);
  const events = await evRes.json();
  const ev = events.find((e) => e.home_team === home && e.away_team === away);
  if (!ev) return json({ players: {}, note: "Game not listed (finished or not posted yet)" }, 200, 3600);

  // 1 credit: anytime TD odds from US books.
  const oRes = await fetch(
    `${API}/events/${ev.id}/odds?apiKey=${key}&regions=us&markets=player_anytime_td&oddsFormat=american`
  );
  if (!oRes.ok) return json({ error: `Odds API odds request failed (${oRes.status})` }, 502);
  const data = await oRes.json();

  // Shape: { updated, players: { "Player Name": { bookKey: americanPrice, ... } } }
  const players = {};
  let updated = null;
  for (const bk of data.bookmakers || []) {
    const mkt = (bk.markets || []).find((m) => m.key === "player_anytime_td");
    if (!mkt) continue;
    if (!updated || mkt.last_update > updated) updated = mkt.last_update;
    for (const o of mkt.outcomes || []) {
      if (o.name !== "Yes" || !o.description) continue;
      if (/D\/ST|Defense/.test(o.description)) continue;
      (players[o.description] ||= {})[bk.key] = o.price;
    }
  }

  return json(
    {
      updated: updated || new Date().toISOString(),
      remaining: oRes.headers.get("x-requests-remaining"),
      players,
    },
    200,
    CACHE_HOURS * 3600
  );
};

export const config = {
  path: "/api/td-odds",
  // Netlify rate limit: each visitor gets 30 calls a minute; more than that gets a 429.
  rateLimit: { windowLimit: 30, windowSize: 60, aggregateBy: ["ip", "domain"] },
};
