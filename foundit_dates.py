"""Read-only: how old are the scraped Foundit postings?
Usage (server):  python3 foundit_dates.py /home/uenvision/uenvision-capstone/data/jsons/foundit"""
import json, sys
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

PH = timezone(timedelta(hours=8))
now = datetime.now(PH)
folder = Path(sys.argv[1])
dates, closed, inactive = [], 0, 0
for p in folder.glob("*.json"):
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        continue
    if d.get("createdAt"):
        dates.append(datetime.fromtimestamp(d["createdAt"] / 1000, PH))
    if d.get("closedAt") and d["closedAt"] / 1000 < now.timestamp():
        closed += 1
    if d.get("isJobActive") is False:
        inactive += 1
dates.sort()
print("files with a date:", len(dates))
if dates:
    print("oldest:", dates[0].date(), " newest:", dates[-1].date(), " median:", dates[len(dates) // 2].date())
    print("by year:", dict(sorted(Counter(x.year for x in dates).items())))
    print("by month:", dict(sorted(Counter(x.strftime("%Y-%m") for x in dates).items())[-18:]))
    for days in (90, 180, 365):
        print(f"older than {days} days:", sum(1 for x in dates if now - x > timedelta(days=days)))
print("already closed:", closed, " marked inactive:", inactive)
