import json
import tempfile
import unittest
from pathlib import Path
from PIL import Image
from image_processing import load_processed_image
from image_processing_A import prepare_full_image, build_full_package


class FullImageTests(unittest.TestCase):
    def test_exif_orientation_matches_bc_and_output_has_no_rotation(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / 'rotated.jpg'
            exif = Image.Exif()
            exif[274] = 6
            im = Image.new('RGB', (24,40), 'white')
            im.paste('red', (0,0,12,20))
            im.save(source, exif=exif)
            expected = load_processed_image(source)
            manifest = Path(prepare_full_image(source, 'orientation', root / 'A', expected.size))
            m = json.loads(manifest.read_text(encoding='utf-8'))
            with Image.open(manifest.parent / m['payload']) as decoded:
                decoded.load()
                self.assertEqual(decoded.size, (40,24))
                self.assertEqual(decoded.mode, 'RGB')
                self.assertNotIn(274, decoded.getexif())
                # 同参数编码B/C公共预处理结果，验证朝向、内容和编码参数一致。
                expected.save(root / 'expected.jpg', quality=80)
                self.assertEqual((root / 'expected.jpg').read_bytes(), (manifest.parent / m['payload']).read_bytes())
            self.assertEqual(m['size_bytes'], (manifest.parent / 'full.jpg').stat().st_size)
            before = (manifest.parent / 'full.jpg').read_bytes()
            with self.assertRaises(ValueError):
                prepare_full_image(source, 'orientation', manifest.parent)
            self.assertEqual(before, (manifest.parent / 'full.jpg').read_bytes())

    def test_output_cannot_be_inside_or_contain_bc(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            bc = root / 'BC'
            bc.mkdir()
            for output in [bc, bc / 'A', root]:
                with self.assertRaises(ValueError):
                    build_full_package(bc, output)


if __name__ == '__main__':
    unittest.main()
