#!/usr/bin/env python3
from __future__ import annotations
import argparse, json, shutil, datetime as dt
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ap = argparse.ArgumentParser()
ap.add_argument("--candidate", default="candidate")
ap.add_argument("--stable", default="stable")
args = ap.parse_args()
cand = ROOT / args.candidate
stable = ROOT / args.stable

rel = cand / "greencraft-release.json"
if not rel.exists():
    raise SystemExit("Candidate has no greencraft-release.json")
data = json.loads(rel.read_text(encoding="utf-8"))
if data.get("status") not in ("GPU_PASS", "READY_FOR_PROMOTION"):
    raise SystemExit(f"Candidate status is {data.get('status')}, not GPU_PASS")

archive = ROOT / "releases" / "archive"
archive.mkdir(parents=True, exist_ok=True)
if stable.exists() and (stable / "greencraft-release.json").exists():
    old = json.loads((stable / "greencraft-release.json").read_text(encoding="utf-8"))
    old_name = old.get("release", "unknown").replace("/", "_")
    dest = archive / old_name
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(stable, dest)

if stable.exists():
    shutil.rmtree(stable)
shutil.copytree(cand, stable)
stable_rel = stable / "greencraft-release.json"
d = json.loads(stable_rel.read_text(encoding="utf-8"))
d["status"] = "STABLE"
d["promoted_at_utc"] = dt.datetime.now(dt.timezone.utc).isoformat()
stable_rel.write_text(json.dumps(d, indent=2, ensure_ascii=False), encoding="utf-8")
print(f"PROMOTED {d.get('release')} -> STABLE")
