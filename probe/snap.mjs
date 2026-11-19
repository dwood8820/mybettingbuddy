// cross-check: first touchdown of every 2026 NFL game per ESPN scoring plays
import fs from "fs";
const csv = await (await fetch("https://github.com/nflverse/nflverse-data/releases/download/schedules/games.csv")).text();
const rows = csv.trim().split("\n"); const H = rows[0].split(",");
const ix = (k) => H.indexOf(k);
const games = rows.slice(1).map((l) => l.split(",")).filter((r) => r[ix("season")] === "2026" && r[ix("home_score")] !== "" && r[ix("home_score")] !== "NA");
const out = {};
for (const r of games) {
  const gid = r[ix("game_id")], ev = r[ix("espn")];
  try {
    const s = await (await fetch(`https://site.api.espn.com/apis/site/v2/sports/football/nfl/summary?event=${ev}`)).json();
    const sp = (s.scoringPlays || []);
    const td = sp.find((p) => /touchdown/i.test(p.scoringType?.name || p.scoringType?.displayName || "") || p.scoringType?.abbreviation === "TD");
    out[gid] = td ? { team: td.team?.abbreviation, text: td.text, type: td.type?.text, period: td.period?.number, clock: td.clock?.displayValue, ev,
      athletes: (td.participants || []).map((p) => p.athlete?.id) } : { none: true, n: sp.length, ev };
  } catch (e) { out[gid] = { err: String(e), ev }; }
}
fs.mkdirSync("pout", { recursive: true });
fs.writeFileSync("pout/news_snap.json", JSON.stringify(out));
console.log("games", games.length, "done", Object.keys(out).length);
