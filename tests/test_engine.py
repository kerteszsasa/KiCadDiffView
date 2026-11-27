from pathlib import Path
import json
import subprocess
import tempfile
import time
import unittest
from unittest.mock import patch

from app.engine import Application
from app.server import check_host, check_origin, read_body


class EngineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir='data/test-tmp')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        repo = self.root/'repo'
        repo.mkdir()
        subprocess.run(['git','init','-q',str(repo)],check=True)
        for args in (['config','user.email','test@local'],['config','user.name','Test']):
            subprocess.run(['git','-C',str(repo),*args],check=True)
        (repo/'board.kicad_pro').write_text('{}')
        (repo/'board.kicad_sch').write_text('(kicad_sch (uuid "root"))')
        (repo/'board.kicad_pcb').write_text('(kicad_pcb)')
        subprocess.run(['git','-C',str(repo),'add','.'],check=True)
        subprocess.run(['git','-C',str(repo),'commit','-qm','Initial'],check=True)
        self.application = Application([repo],self.root/'data')
        self.addCleanup(self.application.close)
        self.payload = {'repo':str(repo),'project':'board.kicad_pro','base':'HEAD','head':'HEAD'}

    def wait(self,identifier):
        deadline = time.monotonic()+5
        while time.monotonic()<deadline:
            job=self.application.job(identifier)
            if job['status'] not in ('queued','running'):
                return job
            time.sleep(.02)
        self.fail('Job did not finish')

    def test_saved_comparison_lifecycle_and_reuse(self):
        with patch('app.engine.Exporter') as factory:
            factory.return_value.export.return_value=[]
            job=self.application.create(self.payload)
            result=self.wait(job['id'])
            self.assertEqual(result['status'],'ready',result['error'])
            self.assertIn('components',result['result'])
            self.assertEqual(self.application.create(self.payload)['id'],job['id'])
            self.assertEqual(factory.return_value.export.call_count,1)
            self.assertFalse((self.application.data/'work'/job['id']).exists())
            self.application.delete(job['id'])
            self.assertEqual(self.application.store.jobs(),[])

    def test_job_error_is_persisted(self):
        with patch('app.engine.Exporter') as factory:
            factory.return_value.export.side_effect=ValueError('Bad export')
            job=self.application.create(self.payload)
            result=self.wait(job['id'])
            self.assertEqual(result['status'],'error')
            self.assertIn('Bad export',result['error'])

    def test_revision_details_are_saved_and_survive_unavailable_source(self):
        repo=Path(self.payload['repo'])
        (repo/'board.kicad_pcb').write_text('(kicad_pcb (version 2))')
        subprocess.run(['git','-C',str(repo),'commit','-qam','Update board\n\nComplete commit description.'],check=True)
        payload={**self.payload,'base':'HEAD~1'}
        with patch('app.engine.Exporter') as factory:
            factory.return_value.export.return_value=[]
            job=self.application.create(payload)
            result=self.wait(job['id'])
        self.assertEqual(result['status'],'ready',result['error'])
        revisions=result['result']['revisions']
        self.assertEqual(revisions['base']['subject'],'Initial')
        self.assertEqual(revisions['head']['subject'],'Update board')
        self.assertIn('Complete commit description.',revisions['head']['message'])
        self.assertEqual(revisions['head']['sha'],result['result']['head'])
        manifest=self.application.data/'results'/job['id']/'manifest.json'
        self.assertEqual(json.loads(manifest.read_text())['revisions'],revisions)
        with patch.object(self.application.repositories,'commit',side_effect=ValueError('Source unavailable')) as read_commit:
            self.assertEqual(self.application.job(job['id'])['result']['revisions'],revisions)
            read_commit.assert_not_called()

    def test_legacy_results_get_revision_details_without_regenerating(self):
        with patch('app.engine.Exporter') as factory:
            factory.return_value.export.return_value=[]
            job=self.application.create(self.payload)
            self.assertEqual(self.wait(job['id'])['status'],'ready')
            path=self.application.data/'results'/job['id']/'manifest.json'
            legacy=json.loads(path.read_text())
            legacy.pop('revisions',None)
            path.write_text(json.dumps(legacy))
            original=path.read_bytes()
            result=self.application.job(job['id'])['result']
            self.assertEqual(result['revisions']['base']['subject'],'Initial')
            self.assertEqual(result['revisions']['head']['sha'],legacy['head'])
            self.assertEqual(path.read_bytes(),original)
            factory.assert_called_once()
            with patch.object(self.application.repositories,'commit',side_effect=ValueError('Source unavailable')):
                unavailable=self.application.job(job['id'])['result']
                self.assertEqual(unavailable['revisions'],{})
                self.assertEqual(unavailable['head'],legacy['head'])

    def test_invalid_asset_path_and_id_cannot_escape(self):
        with self.assertRaises(ValueError):
            self.application.asset('../anything','x.svg')
        with self.assertRaises(FileNotFoundError):
            self.application.asset('a'*24,'../../../repo/board.kicad_sch')

    def test_api_input_and_origin(self):
        self.assertTrue(self.application.dispatch('GET','/api/config',{})['roots'])
        with self.assertRaises(ValueError):
            check_origin('https://foreign.example','localhost:8080')
        with self.assertRaises(ValueError):
            read_body(b'[]','application/json')
        with self.assertRaises(ValueError):
            read_body(b'{}','text/plain')

    def test_host_format_and_same_origin_are_checked(self):
        for host in ('', 'user@localhost:8080', 'localhost/path'):
            with self.assertRaises(ValueError):
                check_host(host)
        for host in ('localhost:8080','127.0.0.1:8080','[::1]:8080','server.local:8080','192.168.1.10:8080'):
            check_host(host)
        with self.assertRaises(ValueError):
            check_origin('http://attacker.example:8080','server.local:8080')

    def test_escaping_sheet_is_rejected_before_export(self):
        repo=Path(self.payload['repo'])
        (repo/'board.kicad_sch').write_text('(kicad_sch (uuid "root") (sheet (uuid "child") (property "Sheetname" "Outside") (property "Sheetfile" "../../outside.kicad_sch")))')
        subprocess.run(['git','-C',str(repo),'commit','-qam','Escaping sheet'],check=True)
        with patch('app.engine.Exporter') as factory:
            job=self.application.create(self.payload)
            result=self.wait(job['id'])
            self.assertEqual(result['status'],'error')
            factory.assert_not_called()

    def test_second_process_cannot_reset_active_history(self):
        with self.assertRaisesRegex(ValueError, 'data directory'):
            Application(self.application.repositories.roots,self.application.data)


if __name__ == '__main__':
    unittest.main()
