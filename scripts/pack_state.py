"""Pack integrity and release identity shared by build, CI and local promotion."""
from __future__ import annotations

import hashlib
import json
import re
import tomllib
from pathlib import Path

from build_pack import BuildError, emit_index, emit_pack, sha256_file

CONTROL_FILES = {'pack.toml', 'index.toml', 'greencraft-release.json', 'status.json'}


def read_release(folder: Path) -> dict:
    return json.loads((folder / 'greencraft-release.json').read_text(encoding='utf-8'))


def write_release(folder: Path, release: dict) -> None:
    (folder / 'greencraft-release.json').write_text(
        json.dumps(release, indent=2, ensure_ascii=False) + '\n', encoding='utf-8', newline='\n')


def installed_files(folder: Path) -> list[Path]:
    return sorted(p for p in folder.rglob('*') if p.is_file()
                  and p.relative_to(folder).as_posix() not in CONTROL_FILES)


def refresh(folder: Path) -> None:
    """Rebuild the complete hash chain; mutable control metadata is never installed."""
    old_index = folder / 'index.toml'
    previous = tomllib.loads(old_index.read_text(encoding='utf-8')) if old_index.exists() else {}
    preserved = {e['file'] for e in previous.get('files', []) if e.get('preserve')}
    entries = []
    for p in installed_files(folder):
        name = p.relative_to(folder).as_posix()
        entries.append({'file': name, 'hash': sha256_file(p),
                        'metafile': name.endswith('.pw.toml'),
                        'preserve': name in preserved or name in {'options.txt', 'config/iris.properties'}})
    release = read_release(folder)
    index_hash = emit_index(folder, entries)
    emit_pack(folder, release['minecraft'], release['fabric'], index_hash, release['release'])


def content_digest(folder: Path) -> str:
    """Identity for update detection, independent of bookkeeping and pack version."""
    pack = tomllib.loads((folder / 'pack.toml').read_text(encoding='utf-8'))
    release = read_release(folder)
    identity = {'versions': pack['versions'], 'graphics': release.get('graphics'),
                'content': release['content'], 'warnings': release.get('warnings', []),
                'files': [(p.relative_to(folder).as_posix(), sha256_file(p))
                          for p in installed_files(folder)]}
    return hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()


def payload_digest(folder: Path) -> str:
    """Test evidence includes the manifest/version, but excludes mutable status."""
    identity = [content_digest(folder), sha256_file(folder / 'pack.toml'),
                sha256_file(folder / 'index.toml')]
    return hashlib.sha256(json.dumps(identity).encode()).hexdigest()


def next_version(*versions: str) -> str:
    parsed = []
    for version in versions:
        if not re.fullmatch(r'\d+\.\d+\.\d+', version):
            raise BuildError(f'Invalid GreenCraft version: {version}')
        parsed.append(tuple(map(int, version.split('.'))))
    major, minor, patch = max(parsed)
    return f'{major}.{minor}.{patch + 1}'


def require_preserved_content(previous: dict, updated: dict) -> None:
    missing = {x['slug'] for x in previous['content']} - {x['slug'] for x in updated['content']}
    if missing:
        raise BuildError(f'Update would remove installed components: {sorted(missing)}')


def validate(folder: Path) -> dict:
    pack = tomllib.loads((folder / 'pack.toml').read_text(encoding='utf-8'))
    release = read_release(folder)
    if (pack['version'] != release['release'] or
            release['release'] != f"{release['minecraft']}-{release['greencraft_version']}" or
            pack['versions'] != {'minecraft': release['minecraft'], 'fabric': release['fabric']}):
        raise BuildError('Pack manifest and release metadata disagree')
    if pack['index'] != {'file': 'index.toml', 'hash-format': 'sha256',
                         'hash': sha256_file(folder / 'index.toml')}:
        raise BuildError('Invalid index hash or index reference')
    index = tomllib.loads((folder / 'index.toml').read_text(encoding='utf-8'))
    if index['hash-format'] != 'sha256':
        raise BuildError('Expected a SHA-256 index')
    seen = set()
    metas = {}
    for entry in index.get('files', []):
        name = entry['file']
        if name in CONTROL_FILES or name in seen or '\\' in name or Path(name).is_absolute():
            raise BuildError(f'Invalid or duplicate indexed path: {name}')
        target = (folder / name).resolve()
        if not target.is_relative_to(folder.resolve()) or not target.is_file():
            raise BuildError(f'Missing/unsafe indexed file: {name}')
        if entry.get('hash-format', 'sha256') != 'sha256' or sha256_file(target) != entry['hash']:
            raise BuildError(f'Invalid hash: {name}')
        seen.add(name)
        if name.endswith('.pw.toml'):
            if entry.get('metafile') is not True:
                raise BuildError(f'Missing metafile flag: {name}')
            meta = tomllib.loads(target.read_text(encoding='utf-8'))
            download = meta['download']
            algorithm = download['hash-format']
            size = {'sha512': 128, 'sha1': 40}.get(algorithm)
            if not size or not re.fullmatch(r'[0-9a-fA-F]{' + str(size) + '}', download['hash']):
                raise BuildError(f'Invalid download hash: {name}')
            filename = meta['filename']
            if '/' in filename or '\\' in filename or filename in {'.', '..'}:
                raise BuildError(f'Invalid installed filename: {name}')
            update = meta['update']['modrinth']
            pid = update['mod-id']
            if pid in metas:
                raise BuildError(f'Duplicate project: {pid}')
            metas[pid] = meta
    actual = {p.relative_to(folder).as_posix() for p in installed_files(folder)}
    if seen != actual:
        raise BuildError(f'Index coverage mismatch: {sorted(seen ^ actual)}')
    content = release['content']
    if len(content) != len(metas) or len({x['project_id'] for x in content}) != len(content):
        raise BuildError('Release content does not match installed metafiles')
    for item in content:
        meta = metas.get(item['project_id'])
        if not meta or (meta['update']['modrinth']['version'], meta['filename'], meta['side']) != (
                item['version_id'], item['filename'], item['side']):
            raise BuildError(f"Release content mismatch: {item['slug']}")
        prefix = {'mod': 'mods', 'shaderpack': 'shaderpacks', 'resourcepack': 'resourcepacks'}[item['kind']]
        expected_path = f"{prefix}/{item['slug']}.pw.toml"
        if expected_path not in seen:
            raise BuildError(f'Wrong content location: {expected_path}')
    return release


def require_ci_evidence(folder: Path) -> dict:
    release = validate(folder)
    evidence = release.get('validation', {})
    if (evidence.get('payload_sha256') != payload_digest(folder) or
            not all(evidence.get(k) is True for k in ('metadata', 'downloads', 'server'))):
        raise BuildError('Missing or stale metadata/download/server validation evidence')
    return release
