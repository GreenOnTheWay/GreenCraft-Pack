#!/usr/bin/env python3
from __future__ import annotations
import json, sys, urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = "https://piston-meta.mojang.com/mc/game/version_manifest_v2.json"

def main():
    req = urllib.request.Request(MANIFEST, headers={"User-Agent":"GreenCraft/2.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        latest = json.loads(r.read().decode())["latest"]["release"]
    stable_file = ROOT / "stable" / "greencraft-release.json"
    stable = json.loads(stable_file.read_text(encoding="utf-8")) if stable_file.exists() else {}
    current = stable.get("minecraft")
    print(json.dumps({"latest":latest,"stable":current}))
    if latest == current:
        return 0
    print(f"NEW_RELEASE={latest}")
    return 10

if __name__ == "__main__":
    raise SystemExit(main())
