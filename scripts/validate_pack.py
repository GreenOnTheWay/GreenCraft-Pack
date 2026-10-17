#!/usr/bin/env python3
"""Validate all content, including client-only files that a server never loads."""
import argparse
import datetime as dt
import hashlib
import os
import tomllib
import urllib.request
from pathlib import Path
from build_pack import ROOT, POLICY, Http, MODRINTH, FABRIC_META, USER_AGENT, BuildError
from pack_state import validate, payload_digest, write_release, require_ci_evidence


def verify_download(download: dict) -> None:
    digest = hashlib.new(download['hash-format'])
    request = urllib.request.Request(download['url'], headers={'User-Agent': USER_AGENT})
    with urllib.request.urlopen(request, timeout=90) as response:
        for chunk in iter(lambda: response.read(1024 * 1024), b''):
            digest.update(chunk)
    if digest.hexdigest().lower() != download['hash'].lower():
        raise BuildError(f"Download hash mismatch: {download['url']}")


def verify_dependencies(versions: dict, records: dict) -> None:
    for pid, version in versions.items():
        for dep in version.get('dependencies', []):
            kind = dep['dependency_type']
            target = dep.get('project_id')
            version_id = dep.get('version_id')
            selected = versions.get(target) if target else next(
                (v for v in versions.values() if v['id'] == version_id), None)
            if kind == 'required':
                if not selected or (version_id and selected['id'] != version_id):
                    raise BuildError(f'Missing/conflicting required dependency for {pid}: {dep}')
                child = records[selected['project_id']]
                parent = records[pid]
                if parent['side'] == 'both' and child['side'] != 'both':
                    raise BuildError(f'Required dependency missing on one side: {dep}')
                if parent['side'] != 'both' and child['side'] not in {parent['side'], 'both'}:
                    raise BuildError(f'Required dependency on wrong side: {dep}')
            if kind == 'incompatible' and selected and (not version_id or selected['id'] == version_id):
                raise BuildError(f'Incompatible installed dependency for {pid}: {dep}')


def online_validate(folder: Path, downloads: bool = True) -> dict:
    release = validate(folder)
    http = Http()
    loaders = http.json(FABRIC_META.format(mc=release['minecraft']))
    if not any(x['loader'].get('stable') and x['loader']['version'] == release['fabric'] for x in loaders):
        raise BuildError('Pinned Fabric loader is not a stable compatible build')
    records = {x['project_id']: x for x in release['content']}
    slugs = {x['slug'] for x in release['content']}
    missing = {x['slug'] for x in POLICY['content'] if x.get('gate')} - slugs
    if missing or slugs.intersection(POLICY['disabled_by_policy']):
        raise BuildError(f'Content policy violation; missing components: {sorted(missing)}')
    versions = {}
    for metafile in sorted(folder.rglob('*.pw.toml')):
        meta = tomllib.loads(metafile.read_text(encoding='utf-8'))
        update = meta['update']['modrinth']
        version = http.json(f"{MODRINTH}/version/{update['version']}")
        pid = update['mod-id']
        record = records[pid]
        expected_loader = {'mod': 'fabric', 'shaderpack': 'iris', 'resourcepack': 'minecraft'}[record['kind']]
        if (version['project_id'] != pid or version.get('version_type') != 'release' or
                release['minecraft'] not in version['game_versions'] or
                expected_loader not in version['loaders']):
            raise BuildError(f"Incompatible release metadata: {record['slug']}")
        download = meta['download']
        if not any(f['filename'] == meta['filename'] and f['url'] == download['url'] and
                   f['hashes'].get(download['hash-format']) == download['hash'] for f in version['files']):
            raise BuildError(f"Download metadata differs from Modrinth: {record['slug']}")
        versions[pid] = version
        if downloads:
            verify_download(download)
        print(f"Verified {record['slug']} {record['version_id']}", flush=True)
    verify_dependencies(versions, records)
    return release


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--folder', default='candidate')
    ap.add_argument('--online', action='store_true')
    ap.add_argument('--metadata-only', action='store_true')
    ap.add_argument('--record', action='store_true')
    ap.add_argument('--server-pass', action='store_true')
    ap.add_argument('--require-ci', action='store_true')
    ap.add_argument('--digest', action='store_true')
    args = ap.parse_args()
    folder = ROOT / args.folder
    release = validate(folder)
    if args.require_ci:
        require_ci_evidence(folder)
    if args.digest:
        print(payload_digest(folder))
        return
    if args.online:
        release = online_validate(folder, not args.metadata_only)
    if args.record:
        if not args.online or args.metadata_only:
            raise BuildError('Recording validation requires online metadata AND download verification')
        base = release.get('validation', {}).get('base_stable_sha256')
        release['validation'] = {'payload_sha256': payload_digest(folder), 'metadata': True,
            'downloads': True, 'base_stable_sha256': base, 'server': False,
            'checked_at_utc': dt.datetime.now(dt.timezone.utc).isoformat(),
            'run_url': (f"{os.environ.get('GITHUB_SERVER_URL', 'https://github.com')}/"
                        f"{os.environ.get('GITHUB_REPOSITORY', 'GreenOnTheWay/GreenCraft-Pack')}/"
                        f"actions/runs/{os.environ.get('GITHUB_RUN_ID', 'local')}")}
        write_release(folder, release)
    if args.server_pass:
        evidence = release.get('validation', {})
        if (evidence.get('payload_sha256') != payload_digest(folder) or
                not evidence.get('metadata') or not evidence.get('downloads')):
            raise BuildError('Server result has no matching metadata/download validation')
        evidence['server'] = True
        write_release(folder, release)
    print(f"VALID: {release['release']} ({payload_digest(folder)})")


if __name__ == '__main__':
    main()
