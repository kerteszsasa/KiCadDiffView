from pathlib import Path
import tempfile
import unittest
import xml.etree.ElementTree as ET

from app.rendering import colored_svg, normalize_svg, union_canvas, board_layers


class RenderingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir='data/test-tmp')
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.before = self.folder/'before.svg'
        self.after = self.folder/'after.svg'
        self.before.write_text('<svg xmlns="http://www.w3.org/2000/svg" width="297mm" height="210mm" viewBox="0 0 297 210"><path d="M 10,20 L 30,40"/></svg>')
        self.after.write_text('<svg xmlns="http://www.w3.org/2000/svg" width="420mm" height="297mm" viewBox="0 0 420 297"><path d="M 10,25 L 30,45"/></svg>')

    def test_common_canvas_preserves_geometry_and_real_movement(self):
        box = union_canvas([[0,0,297,210], [0,0,420,297]])
        for path in (self.before, self.after):
            normalize_svg(path, box)
            self.assertEqual(ET.parse(path).getroot().get('viewBox'), '0 0 420 297')
        self.assertNotEqual(ET.parse(self.before).getroot()[0].get('d'), ET.parse(self.after).getroot()[0].get('d'))

    def test_colored_is_self_contained_and_uses_three_exact_colors(self):
        target = self.folder/'colored.svg'
        colored_svg(self.before, self.after, target, [0,0,420,297])
        text = target.read_text()
        for color in ('#40FF40', '#880808', '#807F7F'):
            self.assertIn(color, text)
        root = ET.parse(target).getroot()
        self.assertEqual(len(list(root.iter('{http://www.w3.org/2000/svg}svg'))), 3)
        for node in root.iter():
            for key, value in node.attrib.items():
                if key.endswith('href'):
                    self.assertTrue(value.startswith('#'), 'Colored must not fetch external resources')

    def test_one_sided_colored(self):
        target = self.folder/'added.svg'
        colored_svg(None, self.after, target, [0,0,420,297])
        self.assertIn('#40FF40', target.read_text())

    def test_custom_and_internal_layers_are_not_dropped(self):
        board = self.folder/'board.kicad_pcb'
        board.write_text('(kicad_pcb\n (layers (0 "F.Cu" signal "Top Layer") (4 "In1.Cu" signal "Inner") (25 "Edge.Cuts" user)))')
        layers = board_layers(board)
        self.assertEqual([x['id'] for x in layers], ['F.Cu','In1.Cu','Edge.Cuts'])
        self.assertEqual(layers[0]['name'], 'Top Layer')


if __name__ == '__main__':
    unittest.main()
