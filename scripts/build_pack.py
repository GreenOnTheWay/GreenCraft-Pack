#!/usr/bin/env python3
"""
GreenCraft pack builder.
- Resolves a Minecraft release, Fabric Loader and Modrinth content.
- Resolves required dependencies recursively.
- Treats Iris -> Sodium as an atomic dependency relationship.
- Emits a valid packwiz 1.1.0 pack with SHA-256 index integrity and SHA-512 downloads.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import shutil
import sys
import tempfile
import time
import tomllib
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
POLICY = json.loads((ROOT / "policy.json").read_text(encoding="utf-8"))
USER_AGENT = "GreenCraft/2.0 (+https://github.com/GreenOnTheWay)"

MOJANG_MANIFEST = "https://piston-meta.mojang.com/mc/game/version_manifest_v2.json"
FABRIC_META = "https://meta.fabricmc.net/v2/versions/loader/{mc}"
MODRINTH = "https://api.modrinth.com/v2"


class BuildError(RuntimeError):
    pass


class Http:
    def __init__(self, retries: int = 3, timeout: int = 30):
        self.retries = retries
        self.timeout = timeout

    def json(self, url: str) -> Any:
        last = None
        for attempt in range(self.retries):
            try:
                req = urllib.request.Request(
                    url,
                    headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
                )
                with urllib.request.urlopen(req, timeout=self.timeout) as r:
                    return json.loads(r.read().decode("utf-8"))
            except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError) as e:
                last = e
                if attempt + 1 < self.retries:
                    time.sleep(1.5 * (attempt + 1))
        raise BuildError(f"HTTP/API failure: {url} :: {last}")


def qjson(value: list[str]) -> str:
    return json.dumps(value, separators=(",", ":"))


def latest_release(http: Http) -> str:
    data = http.json(MOJANG_MANIFEST)
    return str(data["latest"]["release"])


def fabric_loader(http: Http, mc: str) -> str:
    data = http.json(FABRIC_META.format(mc=urllib.parse.quote(mc, safe="")))
    stable = [x for x in data if x.get("loader", {}).get("stable") is True]
    if stable:
        return str(stable[0]["loader"]["version"])
    if data:
        return str(data[0]["loader"]["version"])
    raise BuildError(f"Fabric Loader has no build for Minecraft {mc}")


class ModrinthResolver:
    def __init__(self, http: Http, mc: str):
        self.http = http
        self.mc = mc
        self.project_cache: dict[str, dict] = {}
        self.version_cache: dict[str, dict] = {}
        self.resolved: dict[str, dict] = {}  # project_id -> record
        self.warnings: list[str] = []

    def project(self, ident: str) -> dict:
        if ident not in self.project_cache:
            p = self.http.json(f"{MODRINTH}/project/{urllib.parse.quote(ident, safe='')}")
            self.project_cache[ident] = p
            self.project_cache[str(p["id"])] = p
            self.project_cache[str(p["slug"])] = p
        return self.project_cache[ident]

    def version_by_id(self, version_id: str) -> dict:
        if version_id not in self.version_cache:
            self.version_cache[version_id] = self.http.json(
                f"{MODRINTH}/version/{urllib.parse.quote(version_id, safe='')}"
            )
        return self.version_cache[version_id]

    def versions(self, project: dict, loader: str | None) -> list[dict]:
        params = {"game_versions": qjson([self.mc])}
        if loader:
            params["loaders"] = qjson([loader])
        qs = urllib.parse.urlencode(params)
        url = f"{MODRINTH}/project/{project['id']}/version?{qs}"
        versions = self.http.json(url)
        releases = [v for v in versions if v.get("version_type") == "release"]
        releases.sort(key=lambda v: v.get("date_published", ""), reverse=True)
        return releases

    @staticmethod
    def merge_side(a: str, b: str) -> str:
        if a == b:
            return a
        if "both" in (a, b):
            return "both"
        return "both"  # client + server

    @staticmethod
    def inferred_side(project: dict, parent_side: str) -> str:
        if parent_side in ("client", "server"):
            return parent_side
        c = project.get("client_side", "optional")
        s = project.get("server_side", "optional")
        if c == "unsupported" and s != "unsupported":
            return "server"
        if s == "unsupported" and c != "unsupported":
            return "client"
        return "both"

    def choose(self, slug: str, loader: str | None) -> tuple[dict, dict] | None:
        p = self.project(slug)
        versions = self.versions(p, loader)
        if not versions:
            return None
        return p, versions[0]

    @staticmethod
    def primary_file(version: dict) -> dict:
        files = version.get("files") or []
        if not files:
            raise BuildError(f"Version {version.get('id')} has no files")
        for f in files:
            if f.get("primary") is True:
                return f
        return files[0]

    def add_record(self, project: dict, version: dict, side: str, kind: str, top_level: bool) -> dict:
        pid = str(project["id"])
        if pid in self.resolved:
            rec = self.resolved[pid]
            if rec["version"]["id"] != version["id"]:
                raise BuildError(
                    f"Dependency conflict for {project['slug']}: "
                    f"{rec['version']['version_number']} vs {version['version_number']}"
                )
            rec["side"] = self.merge_side(rec["side"], side)
            rec["top_level"] = rec["top_level"] or top_level
            return rec

        rec = {
            "project": project,
            "version": version,
            "side": side,
            "kind": kind,
            "top_level": top_level,
        }
        self.resolved[pid] = rec
        return rec

    def resolve_dependency(self, dep: dict, parent_side: str) -> None:
        if dep.get("dependency_type") != "required":
            return

        version = None
        project = None
        if dep.get("version_id"):
            version = self.version_by_id(str(dep["version_id"]))
            project = self.project(str(version["project_id"]))
        elif dep.get("project_id"):
            project = self.project(str(dep["project_id"]))
            chosen = self.choose(str(project["id"]), "fabric")
            if chosen:
                project, version = chosen

        if not project or not version:
            raise BuildError(f"Unable to resolve required dependency: {dep}")

        if self.mc not in version.get("game_versions", []):
            raise BuildError(
                f"Required dependency {project['slug']} version "
                f"{version.get('version_number')} does not declare Minecraft {self.mc}"
            )
        # Dependencies of Fabric mods should be Fabric compatible if a loader list is declared.
        loaders = version.get("loaders") or []
        if loaders and project.get("project_type") == "mod" and "fabric" not in loaders:
            raise BuildError(
                f"Required dependency {project['slug']} is not a Fabric build: {loaders}"
            )

        side = self.inferred_side(project, parent_side)
        rec = self.add_record(project, version, side, "mod", top_level=False)
        for child in version.get("dependencies") or []:
            self.resolve_dependency(child, rec["side"])

    def resolve_top(self, item: dict) -> bool:
        if item.get("managed_by") == "iris_dependency":
            return True

        chosen = self.choose(item["slug"], item.get("loader"))
        if not chosen:
            if item.get("gate", False):
                raise BuildError(
                    f"Required GreenCraft component has no RELEASE build for "
                    f"Minecraft {self.mc}: {item['slug']}"
                )
            self.warnings.append(
                f"Optional component omitted for {self.mc}: {item['slug']}"
            )
            return False

        project, version = chosen
        rec = self.add_record(
            project, version, item["side"], item["kind"], top_level=True
        )
        for dep in version.get("dependencies") or []:
            self.resolve_dependency(dep, rec["side"])
        return True

    def verify_managed_dependencies(self) -> None:
        # Anything marked managed_by must already have appeared as a dependency.
        for item in POLICY["content"]:
            if not item.get("managed_by"):
                continue
            p = self.project(item["slug"])
            rec = self.resolved.get(str(p["id"]))
            if rec is None:
                raise BuildError(
                    f"{item['slug']} was expected as {item['managed_by']} but was not resolved"
                )
            rec["side"] = self.merge_side(rec["side"], item["side"])


def toml_quote(s: str) -> str:
    # JSON string syntax is valid TOML basic-string syntax for our values.
    return json.dumps(str(s), ensure_ascii=False)


def safe_meta_name(slug: str) -> str:
    return "".join(c if c.isalnum() or c in "-_." else "-" for c in slug.lower())


def write_metafile(folder: Path, rec: dict) -> tuple[Path, str]:
    project = rec["project"]
    version = rec["version"]
    f = ModrinthResolver.primary_file(version)
    hashes = f.get("hashes") or {}
    hash_format = "sha512" if hashes.get("sha512") else "sha1"
    file_hash = hashes.get(hash_format)
    if not file_hash:
        raise BuildError(f"No usable hash for {project['slug']} / {f.get('filename')}")

    folder.mkdir(parents=True, exist_ok=True)
    meta = folder / f"{safe_meta_name(project['slug'])}.pw.toml"
    content = "\n".join([
        f"name = {toml_quote(project.get('title') or project['slug'])}",
        f"filename = {toml_quote(f['filename'])}",
        f"side = {toml_quote(rec['side'])}",
        "",
        "[download]",
        f"url = {toml_quote(f['url'])}",
        f"hash-format = {toml_quote(hash_format)}",
        f"hash = {toml_quote(file_hash)}",
        "",
        "[update.modrinth]",
        f"mod-id = {toml_quote(project['id'])}",
        f"version = {toml_quote(version['id'])}",
        "",
    ])
    meta.write_text(content, encoding="utf-8", newline="\n")
    return meta, f["filename"]


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fp:
        for chunk in iter(lambda: fp.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def emit_index(out: Path, entries: list[dict]) -> str:
    lines = ['hash-format = "sha256"', ""]
    for e in sorted(entries, key=lambda x: x["file"].lower()):
        lines += ["[[files]]", f"file = {toml_quote(e['file'])}", f"hash = {toml_quote(e['hash'])}"]
        if e.get("metafile"):
            lines.append("metafile = true")
        if e.get("preserve"):
            lines.append("preserve = true")
        lines.append("")
    text = "\n".join(lines)
    (out / "index.toml").write_text(text, encoding="utf-8", newline="\n")
    return sha256_file(out / "index.toml")


def emit_pack(out: Path, mc: str, fabric: str, index_hash: str, release_version: str) -> None:
    content = "\n".join([
        f"name = {toml_quote(POLICY['pack_name'])}",
        f"author = {toml_quote('GreenOnTheWay')}",
        f"version = {toml_quote(release_version)}",
        'pack-format = "packwiz:1.1.0"',
        "",
        "[index]",
        'file = "index.toml"',
        'hash-format = "sha256"',
        f"hash = {toml_quote(index_hash)}",
        "",
        "[versions]",
        f"minecraft = {toml_quote(mc)}",
        f"fabric = {toml_quote(fabric)}",
        "",
    ])
    (out / "pack.toml").write_text(content, encoding="utf-8", newline="\n")


def build(mc_arg: str, output: Path, status: str) -> dict:
    http = Http()
    mc = latest_release(http) if mc_arg == "latest" else mc_arg
    fabric = fabric_loader(http, mc)

    resolver = ModrinthResolver(http, mc)

    # Resolve priority content first (Iris); its exact Sodium dependency becomes authoritative.
    priority = [x for x in POLICY["content"] if x.get("resolve_first")]
    normal = [x for x in POLICY["content"] if not x.get("resolve_first") and not x.get("managed_by")]
    for item in priority + normal:
        resolver.resolve_top(item)
    resolver.verify_managed_dependencies()

    temp = Path(tempfile.mkdtemp(prefix="greencraft-build-"))
    try:
        entries: list[dict] = []
        resolved_summary = []

        for rec in sorted(resolver.resolved.values(), key=lambda r: r["project"]["slug"]):
            kind = rec["kind"]
            if kind == "shaderpack":
                sub = "shaderpacks"
            elif kind == "resourcepack":
                sub = "resourcepacks"
            else:
                sub = "mods"

            meta, installed_filename = write_metafile(temp / sub, rec)
            rel = meta.relative_to(temp).as_posix()
            entries.append({"file": rel, "hash": sha256_file(meta), "metafile": True})

            resolved_summary.append({
                "slug": rec["project"]["slug"],
                "project_id": rec["project"]["id"],
                "version_id": rec["version"]["id"],
                "version": rec["version"]["version_number"],
                "side": rec["side"],
                "kind": kind,
                "filename": installed_filename,
                "top_level": rec["top_level"],
            })

        # Determine actual pinned shader/resourcepack filenames for first-install defaults.
        shader = next((x for x in resolved_summary if x["kind"] == "shaderpack"), None)
        resource = next((x for x in resolved_summary if x["kind"] == "resourcepack"), None)

        config_dir = temp / "config"
        config_dir.mkdir(parents=True, exist_ok=True)
        iris_props = config_dir / "iris.properties"
        if shader:
            iris_props.write_text(
                f"shaderPack={shader['filename']}\nenableShaders=true\n",
                encoding="utf-8",
                newline="\n",
            )
            entries.append({
                "file": "config/iris.properties",
                "hash": sha256_file(iris_props),
                "preserve": True,
            })

        options = temp / "options.txt"
        option_lines = []
        if resource:
            # Keep only a tiny first-install default. preserve=true means GreenCraft will not
            # overwrite the user's options on future updates.
            fn = resource["filename"].replace("\\", "/").replace('"', '\\"')
            option_lines.append(f'resourcePacks:["vanilla","file/{fn}"]')
            option_lines.append("incompatibleResourcePacks:[]")
        option_lines += [
            "renderDistance:16",
            "simulationDistance:10",
        ]
        options.write_text("\n".join(option_lines) + "\n", encoding="utf-8", newline="\n")
        entries.append({"file": "options.txt", "hash": sha256_file(options), "preserve": True})

        release_version = f"{mc}-{POLICY['pack_version']}"
        release = {
            "schema": 2,
            "pack": POLICY["pack_name"],
            "greencraft_version": POLICY["pack_version"],
            "release": release_version,
            "minecraft": mc,
            "fabric": fabric,
            "status": status,
            "generated_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
            "graphics": POLICY["graphics"],
            "warnings": resolver.warnings,
            "content": resolved_summary,
        }
        relfile = temp / "greencraft-release.json"
        relfile.write_text(json.dumps(release, indent=2, ensure_ascii=False), encoding="utf-8", newline="\n")
        entries.append({"file": "greencraft-release.json", "hash": sha256_file(relfile)})

        index_hash = emit_index(temp, entries)
        emit_pack(temp, mc, fabric, index_hash, release_version)

        # Validate every TOML we emitted before publishing it.
        tomllib.loads((temp / "pack.toml").read_text(encoding="utf-8"))
        tomllib.loads((temp / "index.toml").read_text(encoding="utf-8"))
        for p in temp.rglob("*.pw.toml"):
            tomllib.loads(p.read_text(encoding="utf-8"))

        if output.exists():
            shutil.rmtree(output)
        shutil.copytree(temp, output)
        return release
    finally:
        shutil.rmtree(temp, ignore_errors=True)


def self_test() -> int:
    # Offline structural test for the pack/index writer.
    with tempfile.TemporaryDirectory(prefix="greencraft-selftest-") as td:
        p = Path(td)
        (p / "mods").mkdir()
        m = p / "mods" / "fake.pw.toml"
        m.write_text(
            'name = "Fake"\nfilename = "fake.jar"\nside = "client"\n'
            '[download]\nurl = "https://example.invalid/fake.jar"\n'
            'hash-format = "sha512"\nhash = "' + ("0" * 128) + '"\n'
            '[update.modrinth]\nmod-id = "fake"\nversion = "fake-v"\n',
            encoding="utf-8",
        )
        entries = [{"file": "mods/fake.pw.toml", "hash": sha256_file(m), "metafile": True}]
        idx_hash = emit_index(p, entries)
        emit_pack(p, "26.2", "0.19.3", idx_hash, "selftest")
        tomllib.loads((p / "pack.toml").read_text(encoding="utf-8"))
        tomllib.loads((p / "index.toml").read_text(encoding="utf-8"))
        tomllib.loads(m.read_text(encoding="utf-8"))
    print("SELF-TEST OK")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--minecraft", default="latest")
    ap.add_argument("--output", default="candidate")
    ap.add_argument("--status", default="CANDIDATE")
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()

    if args.self_test:
        return self_test()

    out = (ROOT / args.output).resolve()
    try:
        release = build(args.minecraft, out, args.status)
        print(json.dumps(release, indent=2, ensure_ascii=False))
        return 0
    except BuildError as e:
        out.mkdir(parents=True, exist_ok=True)
        status = {
            "schema": 2,
            "status": "WAITING_FOR_MODS",
            "minecraft_requested": args.minecraft,
            "error": str(e),
            "time_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        }
        (out / "status.json").write_text(json.dumps(status, indent=2), encoding="utf-8")
        print(f"GREENCRAFT BUILD BLOCKED: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
