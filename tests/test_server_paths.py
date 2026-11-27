from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from app.server import file_for


class ProductionAssetTests(unittest.TestCase):
    def test_vite_bundles_and_comparison_images_have_separate_routes(self):
        with tempfile.TemporaryDirectory(dir='data/test-tmp') as folder:
            root=Path(folder).resolve()
            assets=root/'frontend/dist/assets';assets.mkdir(parents=True)
            javascript=assets/'index-abc123.js';javascript.write_text('console.log("app")')
            stylesheet=assets/'index-abc123.css';stylesheet.write_text('body{}')
            app=Mock()
            with patch('app.server.ROOT',root):
                self.assertEqual(file_for(app,'/assets/index-abc123.js'),javascript)
                self.assertEqual(file_for(app,'/assets/index-abc123.css'),stylesheet)
                image=root/'image.svg'
                app.asset.return_value=image
                self.assertEqual(file_for(app,'/results/'+'a'*24+'/before/layer.svg'),image)
                app.asset.assert_called_once_with('a'*24,'before/layer.svg')
