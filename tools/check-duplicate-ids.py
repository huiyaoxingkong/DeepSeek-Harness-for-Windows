"""Report duplicate DOM ids in the shell page (they break getElementById)."""

from __future__ import annotations

import collections
import os
import re

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
html = open(os.path.join(REPO, "app", "ui", "index.html"), encoding="utf-8").read()
ids = re.findall(r'\bid="([^"]+)"', html)
dupes = {k: v for k, v in collections.Counter(ids).items() if v > 1}
print("duplicate ids:", dupes or "none")
for name in dupes:
    for match in re.finditer(r"<[^>]*\bid=\"" + re.escape(name) + r"\"[^>]*>", html):
        line = html[: match.start()].count("\n") + 1
        print(f"  line {line}: {match.group(0)[:110]}")
