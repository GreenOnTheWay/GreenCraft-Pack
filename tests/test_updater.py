import copy
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import tomllib
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import build_pack as builder


class StatusRegressionTests(unittest.TestCase):
    def test_status_change_cannot_invalidate_installer_hashes(self):
        with tempfile.TemporaryDirectory() as td:
            folder = Path(td) / 'candidate'
            shutil.copytree(ROOT / 'candidate', folder)
            result = subprocess.run([sys.executable, str(ROOT / 'scripts/set_status.py'),
                                     'READY_FOR_GPU', '--folder', str(folder)], capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr.decode())
            index = tomllib.loads((folder / 'index.toml').read_text())
            self.assertNotIn('greencraft-release.json', [e['file'] for e in index['files']])
            for entry in index['files']:
                self.assertEqual(entry['hash'], hashlib.sha256((folder / entry['file']).read_bytes()).hexdigest())


class ResolverTests(unittest.TestCase):
    def resolver(self):
        return builder.ModrinthResolver(None, '26.3')

    def test_cyclic_required_dependencies_terminate(self):
        resolver = self.resolver()
        project = {'id': 'a', 'slug': 'a', 'project_type': 'mod'}
        version = {'id': 'a1', 'project_id': 'a', 'version_number': '1',
                   'version_type': 'release', 'game_versions': ['26.3'], 'loaders': ['fabric'],
                   'dependencies': [{'dependency_type': 'required', 'version_id': 'a1'}]}
        with patch.object(resolver, 'version_by_id', return_value=version), patch.object(resolver, 'project', return_value=project):
            resolver.resolve_dependency({'dependency_type': 'required', 'version_id': 'a1'}, 'client')
        self.assertEqual(list(resolver.resolved), ['a'])

    def test_no_unstable_loader_fallback(self):
        class Http:
            def json(self, url):
                return [{'loader': {'stable': False, 'version': 'beta'}}]
        with self.assertRaises(builder.BuildError):
            builder.fabric_loader(Http(), '26.3')


class StateTests(unittest.TestCase):
    def setUp(self):
        import pack_state
        self.state = pack_state
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name) / 'pack'
        shutil.copytree(ROOT / 'stable', self.folder)
        self.state.refresh(self.folder)

    def test_status_and_timestamps_do_not_change_payload(self):
        before = self.state.payload_digest(self.folder)
        release = self.state.read_release(self.folder)
        release.update(status='GPU_PASS', generated_at_utc='tomorrow')
        self.state.write_release(self.folder, release)
        self.assertEqual(before, self.state.payload_digest(self.folder))

    def test_manifest_and_json_version_must_agree(self):
        release = self.state.read_release(self.folder)
        release['release'] = '26.3-99.0.0'
        self.state.write_release(self.folder, release)
        with self.assertRaises(builder.BuildError):
            self.state.validate(self.folder)

    def test_detects_corrupt_metafile_and_unindexed_file(self):
        p = self.folder / 'mods/sodium.pw.toml'
        p.write_text(p.read_text() + '\n# changed\n')
        with self.assertRaises(builder.BuildError):
            self.state.validate(self.folder)
        self.state.refresh(self.folder)
        (self.folder / 'mods/unindexed.pw.toml').write_text(p.read_text())
        with self.assertRaises(builder.BuildError):
            self.state.validate(self.folder)

    def test_version_increments_above_stable_and_candidate(self):
        self.assertEqual(self.state.next_version('2.0.9', '2.0.11'), '2.0.12')
        self.assertEqual(self.state.next_version('2.1.0', '2.0.99'), '2.1.1')

    def test_unchanged_build_does_not_reset_pending_gpu_test(self):
        from prepare_candidate import publish_candidate
        stable = Path(self.temp.name) / 'stable'
        pending = Path(self.temp.name) / 'pending'
        shutil.copytree(self.folder, stable)
        shutil.copytree(self.folder, pending)
        # Distinct actual content from stable; bookkeeping alone is not an update.
        options = self.folder / 'options.txt'
        options.write_text(options.read_text() + 'maxFps:144\n')
        self.state.refresh(self.folder)
        shutil.copyfile(options, pending / 'options.txt')
        self.state.refresh(pending)
        release = self.state.read_release(pending)
        release.update(status='READY_FOR_GPU', status_updated_at_utc='2026-01-01T00:00:00+00:00')
        release['validation'] = {'payload_sha256': self.state.payload_digest(pending),
            'metadata': True, 'downloads': True, 'server': True,
            'base_stable_sha256': self.state.payload_digest(stable)}
        self.state.write_release(pending, release)
        before = (pending / 'greencraft-release.json').read_bytes()
        self.assertFalse(publish_candidate(self.folder, stable, pending))
        self.assertEqual(before, (pending / 'greencraft-release.json').read_bytes())

    def test_changed_build_allocates_version_and_invalidates_old_evidence(self):
        from prepare_candidate import publish_candidate
        stable = Path(self.temp.name) / 'stable'
        pending = Path(self.temp.name) / 'pending'
        shutil.copytree(self.folder, stable)
        options = self.folder / 'options.txt'
        options.write_text(options.read_text() + 'maxFps:144\n')
        self.state.refresh(self.folder)
        self.assertTrue(publish_candidate(self.folder, stable, pending))
        release = self.state.validate(pending)
        self.assertEqual(release['greencraft_version'], self.state.next_version(self.state.read_release(stable)['greencraft_version']))
        self.assertFalse(release['validation'].get('server', False))

    def test_download_hash_validation_rejects_corruption(self):
        from validate_pack import verify_download
        download = {'url': (self.folder / 'options.txt').as_uri(),
                    'hash-format': 'sha512', 'hash': '0' * 128}
        with self.assertRaises(builder.BuildError):
            verify_download(download)

    def test_promote_rejects_changed_stable_after_candidate_testing(self):
        from promote import promote
        stable = Path(self.temp.name) / 'stable'
        shutil.copytree(self.folder, stable)
        release = self.state.read_release(self.folder)
        digest = self.state.payload_digest(self.folder)
        release.update(status='GPU_PASS', validation={'payload_sha256': digest,
            'metadata': True, 'downloads': True, 'server': True,
            'gpu_payload_sha256': digest, 'base_stable_sha256': self.state.payload_digest(stable)})
        self.state.write_release(self.folder, release)
        options = stable / 'options.txt'
        options.write_text(options.read_text() + 'maxFps:144\n')
        with self.assertRaises(builder.BuildError):
            promote(self.folder, stable, Path(self.temp.name) / 'archive')

    def test_missing_previously_installed_optional_content_blocks_update(self):
        previous = self.state.read_release(self.folder)
        changed = copy.deepcopy(previous)
        changed['content'] = [x for x in changed['content'] if x['slug'] != 'sodium-extra']
        with self.assertRaises(builder.BuildError):
            self.state.require_preserved_content(previous, changed)

    def test_promotion_rejects_status_without_matching_test_evidence(self):
        from promote import promote
        release = self.state.read_release(self.folder)
        release['status'] = 'GPU_PASS'
        release.pop('validation', None)
        self.state.write_release(self.folder, release)
        stable = Path(self.temp.name) / 'stable'
        with self.assertRaises(builder.BuildError):
            promote(self.folder, stable, Path(self.temp.name) / 'archive')
        self.assertFalse(stable.exists())

    def test_promotion_archives_and_keeps_exact_tested_payload(self):
        from promote import promote
        stable = Path(self.temp.name) / 'stable'
        shutil.copytree(self.folder, stable)
        release = self.state.read_release(self.folder)
        next_pack_version = self.state.next_version(release['greencraft_version'])
        release.update(greencraft_version=next_pack_version,
                       release=f"{release['minecraft']}-{next_pack_version}", status='GPU_PASS')
        self.state.write_release(self.folder, release)
        self.state.refresh(self.folder)
        digest = self.state.payload_digest(self.folder)
        release['validation'] = {'payload_sha256': digest, 'metadata': True, 'downloads': True,
                                 'server': True, 'gpu_payload_sha256': digest,
                                 'base_stable_sha256': self.state.payload_digest(stable)}
        self.state.write_release(self.folder, release)
        promote(self.folder, stable, Path(self.temp.name) / 'archive')
        self.assertEqual(self.state.payload_digest(stable), digest)
        self.state.validate(stable)
        self.assertEqual(self.state.read_release(stable)['status'], 'STABLE')
        self.assertTrue(list((Path(self.temp.name) / 'archive').iterdir()))

    def test_promotion_rechecks_the_copied_payload(self):
        from promote import promote
        release = self.state.read_release(self.folder)
        digest = self.state.payload_digest(self.folder)
        release.update(status='GPU_PASS', validation={'payload_sha256': digest,
            'metadata': True, 'downloads': True, 'server': True, 'gpu_payload_sha256': digest})
        self.state.write_release(self.folder, release)
        real_copy = shutil.copytree
        def change_during_copy(source, destination, *args, **kwargs):
            if Path(source) == self.folder:
                options = self.folder / 'options.txt'
                options.write_text(options.read_text() + 'maxFps:144\n')
                self.state.refresh(self.folder)
            return real_copy(source, destination, *args, **kwargs)
        with patch('promote.shutil.copytree', side_effect=change_during_copy):
            with self.assertRaises(builder.BuildError):
                promote(self.folder, Path(self.temp.name) / 'stable', Path(self.temp.name) / 'archive')


if __name__ == '__main__':
    unittest.main()
