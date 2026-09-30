"""Assemble the site page from scripts/template.html.

  python scripts/build_page.py            -> site/index.html (live site: loads data files from the repo's data branch)
  python scripts/build_page.py --preview out/ preview.html
                                          -> single file with the data embedded (for offline previews)
"""
import json, os, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO = os.environ.get("MBB_REPO", "dwood8820/mybettingbuddy")
DATA_BASE = f"https://raw.githubusercontent.com/{REPO}/data/"

t = open(os.path.join(ROOT, "scripts", "template.html")).read()
if len(sys.argv) > 1 and sys.argv[1] == "--preview":
    src, dest = sys.argv[2], sys.argv[3]
    rd = lambda f: open(os.path.join(src, f)).read()
    extra = {}
    for key, f in (("td", "td_snapshot.json"), ("wx", "wx_snapshot.json")):
        p = os.path.join(src, f)
        extra[key] = open(p).read() if os.path.exists(p) else "{}"
    embed = '{"nfl":%s,"ou":%s,"pp":%s,"td":%s,"wx":%s}' % (rd("nfl.json"), rd("ou_hist.json"), rd("pp_hist.json"), extra["td"], extra["wx"])
    out = t.replace("__EMBED__", embed).replace("__DATA_BASE__", "")
else:
    dest = os.path.join(ROOT, "site", "index.html")
    out = t.replace("__EMBED__", "null").replace("__DATA_BASE__", DATA_BASE)
open(dest, "w").write(out)
print("wrote", dest, len(out))
