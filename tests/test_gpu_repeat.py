"""Exercise the PowerShell guard without launching Minecraft or publishing."""
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PS = shutil.which('powershell') or shutil.which('pwsh')


@unittest.skipUnless(PS, 'PowerShell is required')
class PublishedGpuTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.repo = Path(self.tmp.name)
        self.data = dict(status='GPU_PASS', release='26.3-2.0.0', minecraft='26.3',
                         fabric='0.19.5', greencraft_version='2.0.0', content=[],
                         graphics={'shader_required': True}, warnings=[])
        for name, status in [('candidate', 'GPU_PASS'), ('stable', 'STABLE')]:
            folder = self.repo / name
            folder.mkdir()
            (folder / 'pack.toml').write_text('identical payload')
            (folder / 'greencraft-release.json').write_text(json.dumps(dict(self.data, status=status)))

    def ps(self, code):
        return subprocess.run([PS, '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-Command', code],
                              capture_output=True, text=True)

    def matches(self):
        helper = ROOT / 'scripts/gpu_state.ps1'
        result = self.ps(f"$ErrorActionPreference='Stop'; . '{helper}'; "
                         f"Test-PublishedCandidate '{self.repo}'")
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout.strip() == 'True'

    def test_identical_published_candidate_is_successful_noop(self):
        self.assertTrue(self.matches())

    def test_changed_payload_is_not_already_published(self):
        (self.repo / 'candidate/pack.toml').write_text('changed')
        self.assertFalse(self.matches())

    def test_extra_file_is_not_already_published(self):
        (self.repo / 'stable/extra.txt').write_text('unexpected')
        self.assertFalse(self.matches())

    def test_changed_release_metadata_is_not_already_published(self):
        self.data['fabric'] = 'other'
        (self.repo / 'candidate/greencraft-release.json').write_text(json.dumps(self.data))
        self.assertFalse(self.matches())

    def test_unpublished_stable_status_is_rejected(self):
        (self.repo / 'stable/greencraft-release.json').write_text(json.dumps(self.data))
        self.assertFalse(self.matches())

    def test_missing_stable_is_rejected(self):
        (self.repo / 'stable/greencraft-release.json').unlink()
        self.assertFalse(self.matches())

    def test_script_exits_before_gpu_and_promotion_for_published_candidate(self):
        script = ROOT / 'scripts/gpu_validate.ps1'
        result = self.ps("function git { $global:LASTEXITCODE=0; "
                         "if ($args[0] -eq 'branch') {'main'} }; "
                         "function python {throw 'UNEXPECTED Python/test/promotion'}; "
                         f"& '{script}' -RepoDir '{self.repo}'")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('STABLE', result.stdout)


if __name__ == '__main__':
    unittest.main()
