"""Exercise the ECS key update without contacting Docker or a server."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

SCRIPT = Path(__file__).with_name('apply-deepseek-ecs.sh')


class DeepSeekConfigTests(unittest.TestCase):
    def exercise(self, fail_check=False):
        with tempfile.TemporaryDirectory(prefix='air-deepseek-') as directory:
            root = Path(directory)
            (root / 'shared').mkdir()
            (root / 'incoming' / 'deepseek-123').mkdir(parents=True)
            release = root / 'releases' / 'previous'
            release.mkdir(parents=True)
            (release / 'compose.ecs.yaml').write_text('services: {}\n')
            (release / 'images.env').write_text('APP_IMAGE=test\n')
            (root / 'current').symlink_to(release)
            env_file = root / 'shared' / '.env'
            original = 'APP_PORT=8092\nDEEPSEEK_API_KEY=\nDEEPSEEK_MODEL=deepseek-flash\n'
            env_file.write_text(original)
            env_file.chmod(0o600)
            key_file = root / 'incoming' / 'deepseek-123' / 'deepseek.key'
            key_file.write_text('sk-test-only\n')
            binary = root / 'bin'
            binary.mkdir()
            docker = binary / 'docker'
            docker.write_text('#!/bin/sh\ncase " $* " in *" exec "*) [ "$FAIL_CHECK" != 1 ];; esac\n')
            docker.chmod(0o755)
            flock = binary / 'flock'
            flock.write_text('#!/bin/sh\nexit 0\n')
            flock.chmod(0o755)
            result = subprocess.run(['bash', str(SCRIPT), str(root), str(key_file)],
                                    env={**os.environ, 'PATH': str(binary) + ':' + os.environ['PATH'],
                                         'FAIL_CHECK': '1' if fail_check else '0'},
                                    text=True, capture_output=True)
            content = env_file.read_text()
            self.assertNotIn('sk-test-only', result.stdout + result.stderr)
            self.assertFalse(key_file.exists(), result.stdout + result.stderr)
            self.assertEqual(env_file.stat().st_mode & 0o777, 0o600)
            self.assertFalse(list((root / 'shared').glob('.env.backup.*')))
            return result, content, original

    def test_configures_key_without_changing_other_settings(self):
        result, content, _ = self.exercise()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(content.count('DEEPSEEK_API_KEY='), 1)
        self.assertIn('DEEPSEEK_API_KEY=sk-test-only\n', content)
        self.assertIn('DEEPSEEK_MODEL=deepseek-flash\n', content)

    def test_failed_health_check_restores_previous_configuration(self):
        result, content, original = self.exercise(fail_check=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(content, original)


if __name__ == '__main__':
    unittest.main()
