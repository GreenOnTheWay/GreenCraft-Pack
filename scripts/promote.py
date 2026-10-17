#!/usr/bin/env python3
"""Promote only the exact candidate validated by CI and the real GPU test."""
import argparse
import datetime as dt
import shutil
import tempfile
from pathlib import Path
from build_pack import ROOT, BuildError
from pack_state import (payload_digest, read_release, write_release,
                        require_ci_evidence, validate)


def promote(candidate: Path, stable: Path, archive: Path) -> dict:
    data = require_ci_evidence(candidate)
    evidence = data['validation']
    if data['status'] not in {'GPU_PASS', 'READY_FOR_PROMOTION'}:
        raise BuildError('Candidate has not passed its GPU test')
    if evidence.get('gpu_payload_sha256') != payload_digest(candidate):
        raise BuildError('GPU evidence does not match candidate')
    if stable.exists() and evidence.get('base_stable_sha256') != payload_digest(stable):
        raise BuildError('Stable changed since candidate was prepared; rebuild and retest')
    if stable.exists():
        old = read_release(stable)
        old_version = tuple(map(int, old['greencraft_version'].split('.')))
        new_version = tuple(map(int, data['greencraft_version'].split('.')))
        if new_version <= old_version:
            raise BuildError('Promotion must increment the pack version')
    stable.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='greencraft-promote-', dir=stable.parent) as td:
        staged = Path(td) / 'stable'
        shutil.copytree(candidate, staged)
        require_ci_evidence(staged)
        if evidence['gpu_payload_sha256'] != payload_digest(staged):
            raise BuildError('Candidate changed while staging promotion')
        data.update(status='STABLE', promoted_at_utc=dt.datetime.now(dt.timezone.utc).isoformat())
        write_release(staged, data)
        validate(staged)
        if stable.exists():
            if evidence.get('base_stable_sha256') != payload_digest(stable):
                raise BuildError('Stable changed while staging promotion')
            old = read_release(stable)
            archive.mkdir(parents=True, exist_ok=True)
            dest = archive / old['release']
            if not dest.resolve().is_relative_to(archive.resolve()):
                raise BuildError('Invalid archive path')
            if dest.exists():
                raise BuildError(f'Archive already exists: {dest}')
            shutil.copytree(stable, dest)
            shutil.rmtree(stable)
        shutil.copytree(staged, stable)
    return data


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--candidate', default='candidate')
    ap.add_argument('--stable', default='stable')
    ap.add_argument('--archive', default='releases/archive')
    args = ap.parse_args()
    result = promote(ROOT / args.candidate, ROOT / args.stable, ROOT / args.archive)
    print(f"PROMOTED {result['release']} -> STABLE")


if __name__ == '__main__':
    main()
