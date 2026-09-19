"""Verify the shell page survived the encoding incident intact."""

from __future__ import annotations

import collections
import os
import re

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
path = os.path.join(REPO, "app", "ui", "index.html")
html = open(path, encoding="utf-8").read()

ids = re.findall(r'\bid="([^"]+)"', html)
duplicates = {name: count for name, count in collections.Counter(ids).items() if count > 1}
mojibake = sum(html.count(marker) for marker in ("鎻", "锛", "鈥", "鍏", "銆"))

print(f"lines: {html.count(chr(10)) + 1}")
print(f"single </body> and </html>: {html.count('</body>') == 1 and html.count('</html>') == 1}")
print(f"dialog precedes the scripts: "
      f"{html.find('close-confirm-dialog') < html.find('i18n.js')}")
print(f"mojibake markers: {mojibake}")
print(f"duplicate ids: {duplicates or 'none'}")
for probe in ("关闭窗口时最小化到系统托盘", "关闭窗口时先弹出确认界面", "关闭 DeepSeek Harness？",
              "最小化到托盘", "关闭应用"):
    print(f"  text intact {probe!r}: {probe in html}")
