#!/usr/bin/env python3
"""Resolve current-version updates first, then investigate the next Minecraft."""
import datetime as dt
import os
import shutil
import tempfile
from pathlib import Path
from build_pack import ROOT, BuildError, Http, build, latest_release
from pack_state import (content_digest, payload_digest, next_version, read_release,
                        write_release, refresh, validate, require_preserved_content,
                        require_ci_evidence)


def publish_candidate(built: Path, stable: Path, candidate: Path) -> bool:
    release = validate(built)
    current = validate(stable)
    require_preserved_content(current, release)
    if content_digest(built) == content_digest(stable):
        return False
    previous = read_release(candidate) if candidate.exists() else {}
    if previous and content_digest(built) == content_digest(candidate):
        try:
            pending = require_ci_evidence(candidate)
            if pending['validation'].get('base_stable_sha256') == payload_digest(stable):
                return False
        except BuildError:
            pass  # Legacy/failed candidate must pass the new validation pipeline.
    version = next_version(current['greencraft_version'],
                           previous.get('greencraft_version', current['greencraft_version']))
    release.update(greencraft_version=version,
                   release=f"{release['minecraft']}-{version}", status='CANDIDATE',
                   validation={'base_stable_sha256': payload_digest(stable)},
                   status_updated_at_utc=dt.datetime.now(dt.timezone.utc).isoformat())
    write_release(built, release)
    refresh(built)
    validate(built)
    if candidate.exists():
        shutil.rmtree(candidate)
    shutil.copytree(built, candidate)
    return True


def prepare(stable: Path, candidate: Path) -> bool:
    current = validate(stable)
    with tempfile.TemporaryDirectory(prefix='greencraft-candidate-') as td:
        built = Path(td) / 'pack'
        build(current['minecraft'], built, 'CANDIDATE')
        if content_digest(built) != content_digest(stable):
            # Even unchanged pending updates take priority, preserving their GPU status.
            return publish_candidate(built, stable, candidate)
        latest = latest_release(Http())
        if latest != current['minecraft']:
            build(latest, built, 'CANDIDATE')
            return publish_candidate(built, stable, candidate)
    return False


def main():
    changed = prepare(ROOT / 'stable', ROOT / 'candidate')
    output = os.environ.get('GITHUB_OUTPUT')
    if output:
        with open(output, 'a', encoding='utf-8') as f:
            f.write(f"changed={str(changed).lower()}\n")
    print('Candidate updated' if changed else 'No new candidate; existing validation preserved')


if __name__ == '__main__':
    main()
