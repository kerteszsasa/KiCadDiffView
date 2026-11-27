"""Exercise the public scripts without requiring a Docker daemon."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

PROJECT = Path(__file__).resolve().parents[1]


class LaunchPolicyTests(unittest.TestCase):
    def setUp(self):
        scratch = PROJECT/'data/test-tmp'
        scratch.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=scratch)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.project = self.root/'project folder'
        self.project.mkdir()
        for script in ('run.sh', 'build_docker_image.sh'):
            if (PROJECT/script).exists():
                shutil.copy2(PROJECT/script, self.project/script)
        self.caller = self.root/'caller directory'
        self.caller.mkdir()
        self.repo = self.root/'repo root'
        self.repo.mkdir()
        self.data = self.root/'writable data'
        self.capture = self.root/'docker-calls.jsonl'
        binary = self.root/'bin'
        binary.mkdir()
        fake = binary/'docker'
        fake.write_text('''#!/usr/bin/env python3
import json, os, sys
from pathlib import Path
args = sys.argv[1:]
with Path(os.environ['DOCKER_CAPTURE']).open('a') as log:
    log.write(json.dumps(args) + '\\n')
if args[:1] == ['info']:
    sys.exit(int(os.environ.get('DOCKER_UNAVAILABLE', '0')))
if args[:2] == ['image', 'inspect']:
    sys.exit(int(os.environ.get('IMAGE_MISSING', '0')))
if args[:1] == ['build']:
    sys.exit(int(os.environ.get('BUILD_EXIT', '0')))
''')
        fake.chmod(0o755)
        self.env = {**os.environ, 'PATH': str(binary)+os.pathsep+os.environ['PATH'],
                    'DATA_DIR': str(self.data), 'PORT': '8080',
                    'DOCKER_CAPTURE': str(self.capture)}
        for key in ('REPOS_DIR', 'IMAGE_MISSING', 'DOCKER_UNAVAILABLE', 'BUILD_EXIT'):
            self.env.pop(key, None)

    def invoke(self, script, *args, **environment):
        env = dict(self.env)
        for key, value in environment.items():
            if value is None:
                env.pop(key, None)
            else:
                env[key] = value
        return subprocess.run(['bash', str(self.project/script), *map(str, args)],
                              cwd=self.caller, env=env, capture_output=True, text=True)

    def calls(self):
        return [json.loads(line) for line in self.capture.read_text().splitlines()] if self.capture.exists() else []

    def run_arguments(self):
        runs = [call[1:] for call in self.calls() if call[0] == 'run']
        self.assertEqual(len(runs), 1, self.calls())
        return runs[0]

    def test_build_only_uses_its_project_as_context(self):
        result = self.invoke('build_docker_image.sh')
        self.assertEqual(result.returncode, 0, result.stderr)
        builds = [call for call in self.calls() if call[0] == 'build']
        self.assertEqual(builds, [['build', '--tag', 'kicaddiffview:local', str(self.project)]])
        self.assertFalse(any(call[0] == 'run' for call in self.calls()))
        self.assertFalse(self.data.exists())
        self.assertFalse((self.project/'data').exists())

    def test_sources_and_container_are_read_only_with_separate_data(self):
        result = self.invoke('run.sh', self.repo)
        self.assertEqual(result.returncode, 0, result.stderr)
        args = self.run_arguments()
        self.assertFalse(any(call[0] == 'build' for call in self.calls()))
        self.assertIn(['image', 'inspect', 'kicaddiffview:local'], self.calls())
        for flag in ('--read-only', '--init', '--rm'):
            self.assertIn(flag, args)
        self.assertEqual(args[args.index('--user')+1], f'{os.getuid()}:{os.getgid()}')
        self.assertEqual(args[args.index('--name')+1], 'kicaddiffview')
        self.assertIn(f'type=bind,source={self.repo},target={self.repo},readonly', args)
        self.assertIn(f'type=bind,source={self.data},target=/data', args)
        self.assertIn(f'KICADDIFFVIEW_REPO_ROOTS={self.repo}', args)
        self.assertIn('8080:8080', args)
        self.assertEqual(args[-1], 'kicaddiffview:local')
        self.assertTrue(self.data.is_dir())

    def test_relative_paths_use_the_callers_directory(self):
        result = self.invoke('run.sh', Path('..')/self.repo.name, DATA_DIR='runtime state', PORT='9090')
        self.assertEqual(result.returncode, 0, result.stderr)
        data = self.caller/'runtime state'
        args = self.run_arguments()
        self.assertIn(f'type=bind,source={self.repo},target={self.repo},readonly', args)
        self.assertIn(f'type=bind,source={data},target=/data', args)
        self.assertIn('9090:8080', args)
        self.assertTrue(data.is_dir())
        self.assertFalse((self.project/'runtime state').exists())

    def test_default_data_is_beside_the_script(self):
        result = self.invoke('run.sh', self.repo, DATA_DIR=None)
        self.assertEqual(result.returncode, 0, result.stderr)
        data = self.project/'data'
        self.assertTrue(data.is_dir())
        self.assertIn(f'type=bind,source={data},target=/data', self.run_arguments())
        self.assertFalse((self.caller/'data').exists())

    def test_repo_argument_is_required_even_with_legacy_environment(self):
        result = self.invoke('run.sh', REPOS_DIR=str(self.repo))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Usage:', result.stderr)
        self.assertEqual(self.calls(), [])
        self.assertFalse(self.data.exists())

    def test_invalid_arguments_have_no_docker_or_data_side_effects(self):
        regular_file = self.root/'not-a-directory'
        regular_file.write_text('file')
        cases = [('',), (self.root/'missing',), (regular_file,),
                 ('--native',), ('--build',), ('--stop',), ('--unknown',),
                 (self.repo, 'extra'), ('--help', 'extra')]
        for args in cases:
            with self.subTest(args=args):
                result = self.invoke('run.sh', *args)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(self.calls(), [])
                self.assertFalse(self.data.exists())

    def test_invalid_ports_do_not_create_data(self):
        for port in ('0', '65536', '999999', '-1', 'text'):
            with self.subTest(port=port):
                result = self.invoke('run.sh', self.repo, PORT=port)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('PORT', result.stderr)
                self.assertEqual(self.calls(), [])
                self.assertFalse(self.data.exists())

    def test_unsupported_mount_delimiters_do_not_create_data(self):
        for name in ('repo,with-comma', 'repo:with-colon'):
            repo = self.root/name
            repo.mkdir()
            with self.subTest(name=name):
                result = self.invoke('run.sh', repo)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(self.calls(), [])
                self.assertFalse(self.data.exists())
        data = self.root/'data,with-comma'
        result = self.invoke('run.sh', self.repo, DATA_DIR=str(data))
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(data.exists())

    def test_missing_image_explains_how_to_build_without_starting(self):
        result = self.invoke('run.sh', self.repo, IMAGE_MISSING='1')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('build_docker_image.sh', result.stderr)
        self.assertFalse(any(call[0] in ('build', 'run') for call in self.calls()))
        self.assertFalse(self.data.exists())

    def test_source_and_data_trees_cannot_overlap(self):
        for data in (self.repo, self.repo/'generated/data', self.repo/'.git', self.root):
            with self.subTest(data=data):
                self.capture.unlink(missing_ok=True)
                before = set(self.repo.rglob('*'))
                result = self.invoke('run.sh', self.repo, DATA_DIR=str(data))
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('source', result.stderr)
                self.assertEqual(self.calls(), [])
                self.assertEqual(set(self.repo.rglob('*')), before)
        # Similar names are not overlapping directories.
        data = self.repo.with_name(self.repo.name+'-data')
        result = self.invoke('run.sh', self.repo, DATA_DIR=str(data))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(data.is_dir())

    def test_unavailable_docker_does_not_create_data(self):
        result = self.invoke('run.sh', self.repo, DOCKER_UNAVAILABLE='1')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Docker', result.stderr)
        self.assertFalse(any(call[0] in ('build', 'run') for call in self.calls()))
        self.assertFalse(self.data.exists())

    def test_help_needs_no_docker_or_repo(self):
        for script in ('build_docker_image.sh', 'run.sh'):
            with self.subTest(script=script):
                result = self.invoke(script, '--help', PORT='invalid')
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn('Usage:', result.stdout)
                self.assertEqual(self.calls(), [])
                self.assertFalse(self.data.exists())

    def test_build_failure_is_propagated(self):
        result = self.invoke('build_docker_image.sh', BUILD_EXIT='42')
        self.assertEqual(result.returncode, 42, result.stderr)
        self.assertFalse(any(call[0] == 'run' for call in self.calls()))
        self.assertFalse(self.data.exists())
