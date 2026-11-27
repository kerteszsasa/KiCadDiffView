import hashlib
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from app.storage import Store
from app import remotes


class RemoteTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.url = 'https://example.com/team/board.git'
        self.service = remotes.ManagedRepos(self.root/'data', os.environ.copy())
        self.addCleanup(self.service.close)

    def test_url_policy_and_identifier(self):
        self.assertEqual(self.service.normalize_url('  https://EXAMPLE.com:443/team/board.git  '), self.url)
        self.assertEqual(self.service.identifier(self.url), hashlib.sha256(self.url.encode()).hexdigest()[:24])
        for url in ['http://example.com/a', 'file:///tmp/a', 'git@example.com:a', '-ohttps://example.com/a',
                    'https://user@example.com/a', 'https://u:p@example.com/a', 'https://example.com/a?q=1',
                    'https://example.com/a#b', 'https://example.com/a\nb', 'https://example.com/%0afoo',
                    'https://example.com/a?','https://example.com/a#']:
            with self.subTest(url=url), self.assertRaises(ValueError):
                self.service.normalize_url(url)

    def test_registry_persists_and_recovers_interrupted_refresh(self):
        store = Store(self.root/'db')
        identifier = self.service.identifier(self.url)
        record = dict(id=identifier, url=self.url, path=str(self.service.path(identifier)), status='running',
                      progress='Fetching', error=None, created='a', updated='b', last_refreshed='c', usable=True)
        store.save_remote(record)
        self.assertEqual(store.remote(identifier), record)
        restored = Store(self.root/'db').remote(identifier)
        self.assertEqual(restored['status'], 'error')
        self.assertIn('interrupt', restored['error'].lower())
        self.assertTrue(restored['usable'])
        self.assertEqual(len(store.remotes()), 1)
        store.remember(record['path'])
        store.forget(record['path'])
        self.assertEqual(store.repos(), [])
        store.delete_remote(identifier)
        self.assertIsNone(store.remote(identifier))

    def fixture(self):
        source = self.root/'source'
        subprocess.run(['git', 'init', '-q', '-b', 'main', str(source)], check=True)
        def git(*args):
            return subprocess.check_output(['git', '-C', str(source), *args], text=True).strip()
        git('config', 'user.name', 'Test')
        git('config', 'user.email', 'test@local')
        (source/'board').write_text('initial')
        git('add', '.')
        git('commit', '-qm', 'Initial')
        git('branch', 'other')
        git('tag', 'v1')
        return source, git

    def network(self, source):
        original = subprocess.Popen
        def local_git(command, **kwargs):
            command = [str(source) if part == self.url else part for part in command]
            kwargs['env'] = dict(kwargs['env'], GIT_ALLOW_PROTOCOL='file:https')
            return original(command, **kwargs)
        return patch('app.remotes.subprocess.Popen', side_effect=local_git)

    def test_clone_all_refs_and_refresh_default_branch(self):
        source, git = self.fixture()
        identifier = self.service.identifier(self.url)
        record = dict(id=identifier, url=self.url, path=str(self.service.path(identifier)))
        with self.network(source):
            self.service.clone(record)
        target = self.service.path(identifier)
        def target_git(*args):
            return subprocess.check_output(['git', '-C', str(target), *args], text=True).strip()
        self.assertEqual(target_git('rev-parse', 'refs/remotes/origin/other'), git('rev-parse', 'other'))
        self.assertEqual(target_git('rev-parse', 'v1'), git('rev-parse', 'v1'))
        self.assertGreater(self.service.size(identifier), 0)
        git('checkout', '-qb', 'new-default')
        (source/'board').write_text('updated')
        git('commit', '-qam', 'Updated')
        # Keep the stored public URL even though the fixture clone used a local source.
        subprocess.run(['git', '-C', str(target), 'remote', 'set-url', 'origin', self.url], check=True)
        with self.network(source):
            self.service.refresh(record)
        self.assertEqual((target/'board').read_text(), 'updated')
        self.assertEqual(target_git('symbolic-ref', '--short', 'HEAD'), 'new-default')
        self.assertEqual(target_git('symbolic-ref', 'refs/remotes/origin/HEAD'), 'refs/remotes/origin/new-default')
        self.service.remove(identifier)
        self.assertFalse(target.exists())

    def test_failure_keeps_existing_checkout(self):
        source, git = self.fixture()
        identifier = self.service.identifier(self.url)
        record = dict(id=identifier, url=self.url)
        with self.network(source):
            self.service.clone(record)
        target = self.service.path(identifier)
        before = (target/'board').read_text()
        original = self.service._git
        def fail_checkout(args, **kwargs):
            if 'checkout' in args:
                raise ValueError('simulated checkout failure')
            return original(args, **kwargs)
        git('checkout', '-qb', 'new-default')
        subprocess.run(['git', '-C', str(target), 'remote', 'set-url', 'origin', self.url], check=True)
        with self.network(source), patch.object(self.service, '_git', side_effect=fail_checkout):
            with self.assertRaises(ValueError):
                self.service.refresh(record)
        self.assertEqual((target/'board').read_text(), before)
        self.assertEqual(subprocess.check_output(['git', '-C', str(target), 'symbolic-ref', '--short', 'HEAD'], text=True).strip(), 'main')

    def test_symlinks_and_invalid_ids_cannot_escape(self):
        identifier = self.service.identifier(self.url)
        outside = self.root/'outside'
        outside.mkdir()
        (outside/'keep').write_text('safe')
        target = self.service.path(identifier)
        target.symlink_to(outside, target_is_directory=True)
        with self.assertRaises(ValueError):
            self.service.remove(identifier)
        with self.assertRaises(ValueError):
            self.service.size(identifier)
        self.assertTrue((outside/'keep').exists())
        with self.assertRaises(ValueError):
            self.service.path('../outside')
        target.unlink()
        self.service.root.rmdir()
        self.service.root.symlink_to(outside, target_is_directory=True)
        with self.assertRaises(ValueError):
            self.service.remove(identifier)

    def test_git_runs_with_isolated_https_security_policy(self):
        with patch('app.remotes.subprocess.Popen') as popen:
            popen.return_value.communicate.return_value = ('ok', '')
            popen.return_value.returncode = 0
            self.service._git(['ls-remote', '--symref', self.url, 'HEAD'])
        command = popen.call_args.args[0]
        options = popen.call_args.kwargs
        self.assertIn('protocol.allow=never', command)
        self.assertIn('protocol.https.allow=always', command)
        self.assertIn('credential.helper=', command)
        self.assertIn('core.hooksPath=/dev/null', command)
        self.assertEqual(options['env']['GIT_TERMINAL_PROMPT'], '0')
        self.assertEqual(options['env']['GIT_CONFIG_NOSYSTEM'], '1')
        self.assertTrue(options['start_new_session'])
        popen.return_value.communicate.assert_called_once_with(timeout=900)

    def test_failed_clone_cleans_staging_and_does_not_publish(self):
        identifier = self.service.identifier(self.url)
        record = dict(id=identifier, url=self.url)
        def fail(args, **kwargs):
            staging = Path(args[-1])
            staging.mkdir()
            (staging/'partial').write_text('incomplete')
            raise ValueError('network unavailable')
        with patch.object(self.service, '_git', side_effect=fail):
            with self.assertRaisesRegex(ValueError, 'network unavailable'):
                self.service.clone(record)
        self.assertFalse(self.service.path(identifier).exists())
        self.assertFalse((self.service.root/f'.staging-{identifier}').exists())

    def test_timeout_terminates_process_group_and_raises_value_error(self):
        with patch('app.remotes.subprocess.Popen') as popen, patch('app.remotes.os.killpg') as kill:
            process = popen.return_value
            process.pid = 12345
            process.communicate.side_effect = [subprocess.TimeoutExpired('git', 900), ('', '')]
            with self.assertRaisesRegex(ValueError, 'timed out'):
                self.service._git(['ls-remote', self.url])
            kill.assert_called_once_with(12345, remotes.signal.SIGKILL)

    def test_close_terminates_active_processes_and_rejects_more_work(self):
        with patch('app.remotes.subprocess.Popen') as popen, patch('app.remotes.os.killpg') as kill:
            process = popen.return_value
            process.pid = 12345
            def finish(**kwargs):
                self.service.close()
                return '', ''
            process.communicate.side_effect = finish
            process.returncode = 0
            self.service._git(['ls-remote', self.url])
            kill.assert_called_once_with(12345, remotes.signal.SIGKILL)
            with self.assertRaisesRegex(ValueError, 'closed'):
                self.service._git(['ls-remote', self.url])

    def test_git_launch_failure_is_a_value_error(self):
        with patch('app.remotes.subprocess.Popen', side_effect=OSError('git missing')):
            with self.assertRaisesRegex(ValueError, 'git missing'):
                self.service._git(['ls-remote', self.url])

    def test_git_failure_bounds_error_output_and_disables_inherited_configuration(self):
        service = remotes.ManagedRepos(self.root/'other', dict(os.environ, GIT_SSL_NO_VERIFY='true', GIT_CONFIG_COUNT='1'))
        self.addCleanup(service.close)
        def noisy_process(command, **kwargs):
            kwargs['stderr'].write(b'x' * 20000)
            process = unittest.mock.Mock()
            process.communicate.return_value = ('', '')
            process.returncode = 1
            return process
        with patch('app.remotes.subprocess.Popen', side_effect=noisy_process):
            with self.assertRaises(ValueError) as result:
                service._git(['ls-remote', self.url])
        self.assertLess(len(str(result.exception)), 4200)
        self.assertNotIn('GIT_SSL_NO_VERIFY', service.env)
        self.assertNotIn('GIT_CONFIG_COUNT', service.env)

    def test_public_path_rejects_external_git_directory(self):
        identifier = self.service.identifier(self.url)
        target = self.service.path(identifier)
        target.mkdir()
        (target/'.git').write_text('gitdir: /outside\n')
        with self.assertRaises(ValueError):
            self.service.path(identifier)
        (target/'.git').unlink()
        (target/'.git').symlink_to(self.root/'outside')
        with self.assertRaises(ValueError):
            self.service.path(identifier)

    def test_size_counts_staging_and_ignores_nested_symlinks(self):
        identifier = self.service.identifier(self.url)
        staging = self.service.root/f'.staging-{identifier}'
        staging.mkdir()
        (staging/'partial').write_text('12345')
        (staging/'external').symlink_to('/etc')
        self.assertEqual(self.service.size(identifier), 5)

    def test_subprocess_home_is_dedicated_empty_directory(self):
        self.assertNotEqual(self.service.env['HOME'], os.environ.get('HOME'))
        home = Path(self.service.env['HOME'])
        self.assertTrue(home.is_dir())
        self.assertEqual(list(home.iterdir()), [])

    def test_retry_after_interrupted_publication_reuses_complete_clone_without_network(self):
        source, _ = self.fixture()
        identifier = self.service.identifier(self.url)
        record = dict(id=identifier, url=self.url)
        with self.network(source):
            self.service.clone(record)
        original = self.service._git
        def local_only(args, **kwargs):
            self.assertNotIn('clone', args)
            self.assertNotIn('fetch', args)
            self.assertNotIn('ls-remote', args)
            return original(args, **kwargs)
        with patch.object(self.service, '_git', side_effect=local_only):
            self.service.clone(record)
        self.assertEqual((self.service.path(identifier)/'board').read_text(), 'initial')

    def test_retry_rejects_incomplete_existing_directory(self):
        identifier = self.service.identifier(self.url)
        target = self.service.path(identifier)
        target.mkdir()
        with self.assertRaisesRegex(ValueError, 'incomplete|invalid'):
            self.service.clone(dict(id=identifier, url=self.url))

    def test_shutdown_during_checkout_finishes_local_rollback(self):
        source, git = self.fixture()
        identifier = self.service.identifier(self.url)
        record = dict(id=identifier, url=self.url)
        with self.network(source):
            self.service.clone(record)
        target = self.service.path(identifier)
        previous = (target/'board').read_text()
        git('checkout', '-qb', 'new-default')
        (source/'board').write_text('updated')
        git('commit', '-qam', 'Updated')
        original = self.service._git
        def interrupted(args, **kwargs):
            if 'checkout' in args:
                (target/'board').write_text('partial checkout')
                (target/'.git/index.lock').write_text('interrupted Git lock')
                self.service.close()
                raise ValueError('Git operation interrupted')
            return original(args, **kwargs)
        with self.network(source), patch.object(self.service, '_git', side_effect=interrupted):
            with self.assertRaisesRegex(ValueError, 'interrupted'):
                self.service.refresh(record)
        self.assertEqual((target/'board').read_text(), previous)
        self.assertEqual(subprocess.check_output(['git', '-C', str(target), 'symbolic-ref', '--short', 'HEAD'], text=True).strip(), 'main')
        with self.assertRaisesRegex(ValueError, 'closed'):
            self.service._git(['ls-remote', self.url])

    def test_local_recovery_disables_all_network_and_lazy_fetch(self):
        self.service.close()
        with patch('app.remotes.subprocess.Popen') as popen:
            popen.return_value.communicate.return_value = ('', '')
            popen.return_value.returncode = 0
            self.service._git(['reset', '--hard', 'a' * 40], _recovery=True)
        command = popen.call_args.args[0]
        environment = popen.call_args.kwargs['env']
        self.assertIn('protocol.https.allow=never', command)
        self.assertNotIn('protocol.https.allow=always', command)
        self.assertEqual(environment['GIT_ALLOW_PROTOCOL'], '')
        self.assertEqual(environment['GIT_NO_LAZY_FETCH'], '1')
