from pathlib import Path
import subprocess
import tempfile
import unittest

from app.repositories import Repositories


class RepositoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir='data/test-tmp')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.repo = self.root / 'repo'
        self.repo.mkdir()
        subprocess.run(['git', 'init', '-q', str(self.repo)], check=True)
        self.git('config', 'user.email', 'test@local')
        self.git('config', 'user.name', 'Test')
        (self.repo/'board').mkdir()
        (self.repo/'board/board.kicad_pro').write_text('{}')
        (self.repo/'board/board.kicad_sch').write_text('(kicad_sch)')
        self.git('add', '.')
        self.git('commit', '-qm', 'Initial')
        self.base = self.git('rev-parse', 'HEAD').strip()
        (self.repo/'board/board.kicad_sch').write_text('(kicad_sch (version 2))')
        self.git('commit', '-qam', 'Changed board')
        self.head = self.git('rev-parse', 'HEAD').strip()
        self.service = Repositories([self.root], self.root/'data')

    def git(self, *args):
        return subprocess.check_output(['git', '-C', str(self.repo), *args], text=True)

    def test_projects_history_and_resolve(self):
        self.assertEqual(self.service.projects(str(self.repo))[0]['path'], 'board/board.kicad_pro')
        self.assertEqual(self.service.resolve(str(self.repo), 'HEAD~1'), self.base)
        commits = self.service.commits(str(self.repo), 'board/board.kicad_pro')
        self.assertEqual([c['sha'] for c in commits['commits']], [self.head, self.base])

    def test_archive_is_correct_revision_and_source_unchanged(self):
        destination = self.root/'data/snapshot'
        self.service.snapshot(str(self.repo), self.base, destination)
        self.assertEqual((destination/'board/board.kicad_sch').read_text(), '(kicad_sch)')
        self.assertIn('version 2', (self.repo/'board/board.kicad_sch').read_text())
        self.assertEqual(self.git('status', '--porcelain'), '')

    def test_full_commit_messages_preserve_paragraphs_and_pagination(self):
        message = 'Explain the board update\n\nBody-only search marker: árvíz.\nDetails with <tags> and a separator: \x1f retained.\n\nFinal paragraph.'
        (self.repo/'board/board.kicad_sch').write_text('(kicad_sch (version 3))')
        self.git('commit', '-qam', message)
        newest = self.git('rev-parse', 'HEAD').strip()
        first = self.service.commits(str(self.repo), 'board/board.kicad_pro', limit=1)
        self.assertEqual(len(first['commits']), 1)
        self.assertTrue(first['more'])
        self.assertEqual(first['commits'][0]['sha'], newest)
        self.assertEqual(first['commits'][0]['subject'], 'Explain the board update')
        self.assertEqual(first['commits'][0]['message'], message)
        self.assertEqual(self.service.commit(str(self.repo), newest), first['commits'][0])
        next_page = self.service.commits(str(self.repo), 'board/board.kicad_pro', offset=1, limit=1)
        self.assertEqual(next_page['commits'][0]['sha'], self.head)
        self.assertEqual(next_page['commits'][0]['message'], 'Changed board')
        searched = self.service.commits(str(self.repo), 'board/board.kicad_pro', query='Body-only search marker')
        self.assertEqual([commit['sha'] for commit in searched['commits']], [newest])
        self.assertFalse(searched['more'])

    def test_outside_root_and_symlink_are_rejected(self):
        with self.assertRaises(ValueError):
            self.service.browse('/etc')
        (self.root/'outside').symlink_to('/etc', target_is_directory=True)
        with self.assertRaises(ValueError):
            self.service.browse(str(self.root/'outside'))

    def test_project_traversal_is_rejected(self):
        with self.assertRaises(ValueError):
            self.service.commits(str(self.repo), '../outside.kicad_pro')


if __name__ == '__main__':
    unittest.main()
