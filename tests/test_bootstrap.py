"""Execute bootstrap orchestration in a temporary tree with fake OS/tool boundaries.

This is a shell integration test, not a Debian/package/network acceptance test.
"""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
BASH = ('C:/Program Files/Git/bin/bash.exe' if os.name == 'nt' else shutil.which('bash'))


@unittest.skipUnless(BASH and Path(BASH).is_file(), 'Bash unavailable')
class BootstrapTests(unittest.TestCase):
    def scenario(self, mode):
        (ROOT / 'test-results').mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='bootstrap-test-', dir=ROOT / 'test-results') as directory:
            root = Path(directory)
            def shellpath(path):
                value = path.as_posix()
                return '/' + value[0].lower() + value[2:] if os.name == 'nt' else value
            base = './test-results/' + root.name if os.name == 'nt' else shellpath(root)
            dest = root / 'checkout'
            (dest / '.git').mkdir(parents=True)
            (dest / '.venv/bin').mkdir(parents=True)
            (root / 'bin').mkdir()
            (root / 'os-release').write_text('ID=debian\nVERSION_ID=13\n')
            source = (ROOT / 'bootstrap.sh').read_text()
            # Replace privileged OS/filesystem boundaries only in this test copy.
            source = source.replace('[[ $EUID -eq 0 ]]', '[[ 1 -eq 1 ]]')
            for old, new in (('/etc/os-release', base + '/os-release'),
                             ('/opt/egames-fork', base + '/checkout'),
                             ('/var/log/egames-fork', base + '/logs'),
                             ('/usr/local/bin/', base + '/bin/'),
                             ('/run/lock/egames-fork-bootstrap.lock', base + '/bootstrap.lock')):
                source = source.replace(old, new)
            (root / 'bootstrap.sh').write_text(source, newline='\n')
            def executable(path, text):
                path.write_text('#!/usr/bin/env bash\nset -eu\n' + text, newline='\n')
                path.chmod(0o755)
            executable(dest / '.venv/bin/python', 'exit 0\n')
            executable(dest / 'install.sh', '''
printf '%s\n' "$*" >> "$TEST_ROOT/calls"
if [[ $1 == --check ]]; then
  if [[ -e $TEST_ROOT/checked && $TEST_MODE == post-failure ]]; then exit 7; fi
  touch "$TEST_ROOT/checked"
fi
''')
            executable(root / 'bin/docker', 'exit 0\n')
            executable(root / 'bin/flock', 'exit 0\n')
            executable(root / 'bin/dpkg-query', "printf 'install ok installed\\n'\n")
            executable(root / 'bin/git', '''
case "$*" in
  *'remote get-url origin') echo https://github.com/test-alexsun/egames-fork.git ;;
  *'rev-parse HEAD') echo "$EGAMES_FORK_REF" ;;
  *'status --porcelain'*) exit 0 ;;
  *' show '*) cat "$TEST_ROOT/bootstrap.sh" ;;
  *) exit 9 ;;
esac
''')
            env = dict(os.environ, TEST_ROOT=base, TEST_MODE=mode,
                       EGAMES_FORK_REF='a' * 40)
            # Bash uses a POSIX PATH, independently of Windows PATH conversion.
            driver = root / 'driver.sh'
            driver.write_text('export PATH="$TEST_ROOT/bin:/usr/bin:/bin:$PATH"\nexec bash "$TEST_ROOT/bootstrap.sh" ' +
                              ('--dry-run' if mode == 'dry-run' else '--yes') + '\n', newline='\n')
            result = subprocess.run([BASH, base + '/driver.sh'], cwd=ROOT, env=env, text=True,
                                    encoding='utf-8', errors='replace', capture_output=True, timeout=30)
            calls = (root / 'calls').read_text().splitlines() if (root / 'calls').exists() else []
            return result, calls

    def test_dry_run_stops_before_backup_apply(self):
        result, calls = self.scenario('dry-run')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(calls, ['--check'])

    def test_success_applies_backup_and_postcheck(self):
        result, calls = self.scenario('success')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(calls, ['--check', '--backup', '--install --yes', '--check'])

    def test_postcheck_failure_invokes_public_restore_and_exits_nonzero(self):
        result, calls = self.scenario('post-failure')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(calls, ['--check', '--backup', '--install --yes', '--check', '--restore --yes'])
        self.assertIn('guarded transaction rollback completed', result.stderr)


if __name__ == '__main__':
    unittest.main()
