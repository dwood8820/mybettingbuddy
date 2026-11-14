// Injuries + latest headlines for one game, from ESPN's public game summary and team news feeds.
// GET /api/gamenews?sport=nfl|ncaaf|nba|ncaab&event=<ESPN event id>
// Netlify's CDN caches each game's response for 20 minutes, so every visitor shares one lookup.
const PATH = {
  nfl: "football/nfl",
  ncaaf: "football/college-football",
  nba: "basketball/nba",
  ncaab: "basketball/mens-college-basketball",
};
const NFL_ABBR = { WSH: "WAS", LAR: "LA" }; // ESPN -> nflverse team codes
const SKIP_TYPES = new Set(["Media", "Video", "Podcast"]);
const MAX_AGE_DAYS = 10;

const get = async (url) => {
  const r = await fetch(url, { headers: { "user-agent": "mybettingbuddy" } });
  if (!r.ok) throw new Error(url + " " + r.status);
  return r.json();
};
const https = (u) => (u ? String(u).replace(/^http:/, "https:") : null);

function slimInjury(x) {
  const a = x.athlete || {}, d = x.details || {};
  const what = [d.side && d.side !== "Not Specified" ? d.side : "", d.type, d.detail && d.detail !== "Not Specified" ? `(${d.detail})` : ""]
    .filter(Boolean).join(" ").trim();
  return {
    id: a.id || null,
    n: a.displayName || a.fullName || "",
    pos: a.position?.abbreviation || "",
    st: x.status || x.type?.description || "",
    what: what || null,
    ret: d.returnDate || null,
    date: x.date || null,
  };
}

function teamIdsOf(art) {
  return (art.categories || []).filter((c) => c.type === "team").map((c) => String(c.teamId ?? c.team?.id));
}

export async function build(sport, event) {
  const base = `https://site.api.espn.com/apis/site/v2/sports/${PATH[sport]}`;
  const s = await get(`${base}/summary?event=${event}`);
  const comp = s.header?.competitions?.[0] || {};
  const ABBR = sport === "nfl" ? NFL_ABBR : {};
  const sides = {};
  for (const c of comp.competitors || []) {
    const t = c.team || {};
    sides[c.homeAway] = { tid: String(t.id), abbr: ABBR[t.abbreviation] || t.abbreviation, inj: [] };
  }
  const byTid = Object.fromEntries(Object.values(sides).map((x) => [x.tid, x]));
  const injuriesListed = Array.isArray(s.injuries);
  for (const t of s.injuries || []) {
    const side = byTid[String(t.team?.id)];
    if (side) side.inj = (t.injuries || []).map(slimInjury).filter((x) => x.n);
  }

  // headlines: the game's own preview/recap, plus recent stories tagged to either team
  const tids = new Set(Object.keys(byTid));
  const pool = [...(s.news?.articles || [])];
  const team = await Promise.all([...tids].map((id) => get(`${base}/news?team=${id}&limit=20`).catch(() => ({}))));
  team.forEach((t) => pool.push(...(t.articles || [])));
  const cutoff = Date.now() - MAX_AGE_DAYS * 864e5;
  const seen = new Set(), news = [];
  const g = s.article;
  if (g?.headline) {
    const u = https(g.links?.web?.href) || `https://www.espn.com/${sport === "ncaab" ? "mens-college-basketball" : sport === "ncaaf" ? "college-football" : sport}/game/_/gameId/${event}`;
    news.push({ h: g.headline, d: g.description?.replace(/^—\s*/, "") || "", p: g.published || null, u, k: "game" });
    seen.add(g.headline);
  }
  pool
    .filter((a) => a.headline && !SKIP_TYPES.has(a.type) && a.links?.web?.href)
    .filter((a) => { const ids = teamIdsOf(a); return ids.some((id) => tids.has(id)) && ids.length <= 4; }) // drop league-wide roundups
    .filter((a) => !a.published || Date.parse(a.published) >= cutoff)
    .sort((a, b) => Date.parse(b.published || 0) - Date.parse(a.published || 0))
    .forEach((a) => {
      if (seen.has(a.headline) || seen.has(a.id)) return;
      seen.add(a.headline); seen.add(a.id);
      const ids = teamIdsOf(a);
      const tag = ids.length === 1 ? byTid[ids[0]]?.abbr : null;
      news.push({ h: a.headline, d: (a.description || "").replace(/^—\s*/, ""), p: a.published || null, u: https(a.links.web.href), k: String(a.links.web.href).includes(event) ? "game" : "team", t: tag });
    });

  return { updated: new Date().toISOString(), injuriesListed, home: sides.home || null, away: sides.away || null, news: news.slice(0, 6) };
}

export default async (req) => {
  const q = new URL(req.url).searchParams;
  const sport = PATH[q.get("sport")] ? q.get("sport") : null;
  const event = /^\d{6,12}$/.test(q.get("event") || "") ? q.get("event") : null;
  const json = (body, status, cache) => new Response(JSON.stringify(body), {
    status,
    headers: Object.assign({ "content-type": "application/json" }, cache ? {
      "cache-control": "public, max-age=300",
      "netlify-cdn-cache-control": "public, durable, s-maxage=1200, stale-while-revalidate=600",
      "netlify-vary": "query=sport|event",
    } : {}),
  });
  if (!sport || !event) return json({ error: "Need sport and event" }, 400);
  try {
    return json(await build(sport, event), 200, true);
  } catch (e) {
    return json({ error: "News unavailable" }, 502);
  }
};

export const config = {
  path: "/api/gamenews",
  rateLimit: { windowLimit: 120, windowSize: 60, aggregateBy: ["ip", "domain"] },
};
