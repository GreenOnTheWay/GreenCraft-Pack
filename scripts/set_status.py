#!/usr/bin/env python3
import argparse, json, datetime as dt
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
ap = argparse.ArgumentParser()
ap.add_argument("status")
ap.add_argument("--folder", default="candidate")
args = ap.parse_args()
p = ROOT / args.folder / "greencraft-release.json"
if not p.exists():
    raise SystemExit(f"Missing {p}")
d = json.loads(p.read_text(encoding="utf-8"))
d["status"] = args.status
d["status_updated_at_utc"] = dt.datetime.now(dt.timezone.utc).isoformat()
p.write_text(json.dumps(d, indent=2, ensure_ascii=False), encoding="utf-8")
print(args.status)
