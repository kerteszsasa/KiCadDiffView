"""Remote ownership and cascade deletion through the application API."""
from pathlib import Path
import shutil
import subprocess
import threading
from unittest.mock import patch
import unittest
import test_engine

class RemoteEngineTests(unittest.TestCase):
    setUp = test_engine.EngineTests.setUp
    wait = test_engine.EngineTests.wait
    def import_fixture(self):
        def clone(record):
            shutil.copytree(self.payload['repo'], record['path'])
        with patch.object(self.application.remotes, 'clone', side_effect=clone):
            record = self.application.import_remote('https://example.org/team/board.git')
            self.application.worker.submit(lambda: None).result(5)
        return self.application.remote_record(record['id'])

    def test_import_reuse_and_cascade_preserve_local(self):
        subprocess.run(['git', '-C', self.payload['repo'], 'remote', 'add', 'origin', 'https://example.org/team/board.git'], check=True)
        remote = self.import_fixture()
        self.assertEqual(remote['status'], 'ready', remote['error'])
        with patch.object(self.application.remotes, 'clone') as clone:
            self.assertEqual(self.application.import_remote(remote['url'])['id'], remote['id'])
            clone.assert_not_called()
        opened = self.application.dispatch('POST','/api/repos',{}, {'path':remote['path']})
        self.assertEqual(opened['source_url'], remote['url'])
        self.assertEqual(opened['projects'][0]['path'], 'board.kicad_pro')
        with patch('app.engine.Exporter') as factory:
            factory.return_value.export.return_value=[]
            local = self.application.create(self.payload)
            self.wait(local['id'])
            job = self.application.create({**self.payload,'repo':remote['path']})
            result = self.wait(job['id'])
        self.assertEqual(result['result']['remote_repo_id'], remote['id'])
        self.assertEqual(self.application.remote_record(remote['id'])['comparison_count'], 1)
        self.application.delete_remote(remote['id'])
        self.assertIsNone(self.application.store.job(job['id']))
        self.assertIsNotNone(self.application.store.job(local['id']))
        self.assertTrue(Path(self.payload['repo']).exists())
        self.assertFalse(Path(remote['path']).exists())
        with self.assertRaises(ValueError):
            self.application.repositories.allowed(remote['path'])

    def test_queued_comparison_blocks_delete_and_refresh(self):
        remote = self.import_fixture()
        gate = threading.Event()
        self.application.worker.submit(gate.wait, 5)
        try:
            job = self.application.create({**self.payload,'repo':remote['path']})
            with self.assertRaisesRegex(ValueError, 'comparison'):
                self.application.delete_remote(remote['id'])
            with self.assertRaisesRegex(ValueError, 'comparison'):
                self.application.refresh_remote(remote['id'])
        finally:
            gate.set()
        self.wait(job['id'])

    def test_failed_refresh_retains_usable_cache(self):
        remote = self.import_fixture()
        with patch.object(self.application.remotes,'refresh',side_effect=ValueError('Offline')):
            self.application.refresh_remote(remote['id'])
            self.application.worker.submit(lambda: None).result(5)
        record=self.application.remote_record(remote['id'])
        self.assertEqual(record['status'],'error')
        self.assertTrue(record['usable'])
        self.assertTrue(self.application.repositories.projects(remote['path']))

    def test_unregistered_data_clone_is_not_a_source(self):
        path=self.application.data/'repos'/('a'*24)
        path.mkdir(parents=True)
        with self.assertRaises(ValueError):
            self.application.repositories.repository(path)

    def test_managed_symlink_cannot_become_a_local_source(self):
        remote = self.import_fixture()
        path = Path(remote['path'])
        shutil.rmtree(path)
        path.symlink_to(self.payload['repo'], target_is_directory=True)
        with self.assertRaises(ValueError):
            self.application.repositories.repository(path)
        with self.assertRaises(ValueError):
            self.application.create({**self.payload, 'repo': str(path)})

    def test_duplicate_import_uses_one_queued_operation(self):
        gate = threading.Event()
        self.application.worker.submit(gate.wait, 5)
        def clone(record):
            shutil.copytree(self.payload['repo'], record['path'])
        with patch.object(self.application.remotes, 'clone', side_effect=clone) as run:
            try:
                first = self.application.import_remote('https://example.org/duplicate.git')
                second = self.application.import_remote('https://example.org/duplicate.git')
                self.assertEqual(first['id'], second['id'])
                self.assertEqual(second['status'], 'queued')
                with self.assertRaises(ValueError):
                    self.application.delete_remote(first['id'])
            finally:
                gate.set()
            self.application.worker.submit(lambda: None).result(5)
            self.assertEqual(run.call_count, 1)

    def test_cascade_removes_failed_artifacts_and_allows_reimport(self):
        remote = self.import_fixture()
        with patch('app.engine.Exporter') as factory:
            factory.return_value.export.side_effect = ValueError('Bad export')
            job = self.application.create({**self.payload, 'repo': remote['path']})
            self.assertEqual(self.wait(job['id'])['status'], 'error')
        work = self.application.data/'work'/job['id']
        self.assertTrue(work.exists())
        record = self.application.remote_record(remote['id'])
        self.assertGreater(record['delete_bytes'], record['size_bytes'])
        self.application.delete_remote(remote['id'])
        self.assertFalse(work.exists())
        self.assertIsNone(self.application.store.remote(remote['id']))
        self.assertNotIn(remote['path'], [row['path'] for row in self.application.store.repos()])
        self.assertEqual(self.import_fixture()['status'], 'ready')

    def test_restart_retains_managed_source_registration(self):
        remote = self.import_fixture()
        self.application.close()
        self.application = test_engine.Application([self.payload['repo']], self.application.data)
        self.addCleanup(self.application.close)
        self.assertEqual(self.application.remote_record(remote['id'])['status'], 'ready')
        self.assertEqual(self.application.repositories.projects(remote['path'])[0]['path'], 'board.kicad_pro')

    def test_remote_endpoints_and_local_delete_rejection(self):
        remote = self.import_fixture()
        listing = self.application.dispatch('GET', '/api/remote-repos', {})
        self.assertEqual(listing['repos'][0]['url'], remote['url'])
        self.assertIsInstance(listing['repos'][0]['size_bytes'], int)
        with self.assertRaises(FileNotFoundError):
            self.application.dispatch('DELETE', '/api/remote-repos/'+'a'*24, {})
        with patch.object(self.application.remotes, 'refresh'):
            self.application.dispatch('POST', '/api/remote-repos/'+remote['id']+'/refresh', {})
            self.application.worker.submit(lambda: None).result(5)
        self.assertTrue(self.application.dispatch('DELETE', '/api/remote-repos/'+remote['id'], {})['deleted'])
        self.assertEqual(self.application.dispatch('GET', '/api/remote-repos', {})['repos'], [])
        self.assertTrue(Path(self.payload['repo']).is_dir())
