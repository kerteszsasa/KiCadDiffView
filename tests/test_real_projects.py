"""Explicit integration runner; ordinary unit discovery skips costly exports."""
import hashlib
import json
import os
from pathlib import Path
import time
import unittest
import xml.etree.ElementTree as ET

from app.engine import Application


@unittest.skipUnless(os.environ.get('KICADDIFFVIEW_REAL_TESTS') == '1', 'Set KICADDIFFVIEW_REAL_TESTS=1 for KiCad integration')
class RealProjectTests(unittest.TestCase):
    def test_both_projects_and_read_only_sources(self):
        repo = Path('/home/kerteszs/hw/idata/hardware')
        if not repo.is_dir():
            self.skipTest('Local hardware repository is unavailable')
        selected = [('lea6s_to_maxm10s/lea6s_to_maxm10s.kicad_pro','7b75987','ea63d8b'),
                    ('Armfed/Armfed/Armfed.kicad_pro','7c96f105c84e3abd1975e235742a56e6c79eca9a','bed6b9bbb014fc2f4fc744a7263bbc3a8737f116')]
        originals = [p for project,_,_ in selected for p in (repo/project).parent.glob('*.kicad_*') if p.is_file()]
        originals += [repo/'.git/index',repo/'.git/HEAD',repo/'.git/config']
        hashes = {p:hashlib.sha256(p.read_bytes()).hexdigest() for p in originals if p.is_file()}
        app = Application([repo],Path('data').resolve())
        self.addCleanup(app.close)
        for project,base,head in selected:
            record = app.create(dict(repo=str(repo),project=project,base=base,head=head))
            identifier = record['id']
            deadline = time.monotonic()+600
            last = None
            while time.monotonic() < deadline:
                job = app.job(identifier)
                status = (job['status'],job['progress'])
                if status != last:
                    print(project, *status, flush=True)
                    last = status
                if job['status'] in ('ready','error'):
                    break
                time.sleep(.25)
            self.assertEqual(job['status'],'ready',job.get('error'))
            result = job['result']
            self.assertTrue(result['components']['sch'])
            self.assertTrue(result['components']['pcb'])
            self.assertEqual({f['type'] for f in result['files']},{'sch','pcb'})
            output = app.data/'results'/identifier
            for file in result['files']:
                items = file.get('layers',file.get('pages',[]))
                self.assertTrue(items)
                for item in items:
                    for side in ('before','after','colored'):
                        if item[side]:
                            path = output/item[side]
                            self.assertTrue(path.is_file(),path)
                            self.assertEqual([float(v) for v in ET.parse(path).getroot().get('viewBox').split()],file['canvas'])
            if project.startswith('Armfed'):
                pcb = next(f for f in result['files'] if f['type']=='pcb')
                layer_ids = {l['id'] for l in pcb['layers']}
                self.assertTrue({'F.Cu','B.Cu','In1.Cu','In2.Cu','Edge.Cuts'} <= layer_ids)
                self.assertGreater(len(pcb['layers']),5)
                edge = next(l for l in pcb['layers'] if l['id']=='Edge.Cuts')
                def geometry(path):
                    return [e.get('d') for e in ET.parse(output/path).getroot().iter() if e.get('d')]
                self.assertEqual(geometry(edge['before']),geometry(edge['after']))
                self.assertGreater(len(next(f for f in result['files'] if f['type']=='sch')['pages']),1)
            print('PASS',project,identifier,flush=True)
        self.assertEqual(hashes,{p:hashlib.sha256(p.read_bytes()).hexdigest() for p in hashes})
        print('PASS: source project and Git metadata checksums unchanged.',flush=True)


if __name__ == '__main__':
    unittest.main()
