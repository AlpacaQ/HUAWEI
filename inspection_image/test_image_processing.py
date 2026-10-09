"""正确性测试用合成图片；不是巡检实验或真实网络测量。"""
import json
import tempfile
import unittest
from pathlib import Path

from PIL import Image

from image_processing import prepare_image, load_processed_image, validate_roi, tile_boxes, intersects
from check_image import check_image


class ImageProcessingTests(unittest.TestCase):
    def test_non_divisible_pixels_and_manifest(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            image = Image.new("RGB", (83, 61))
            image.putdata([(x * 3 % 256, y * 5 % 256, (x+y) % 256)
                           for y in range(61) for x in range(83)])
            source = root / "source.png"
            image.save(source)
            manifest_path = prepare_image(source, [41, 30, 83, 61], root / "encoded")
            report = check_image(source, manifest_path, root / "check")
            self.assertTrue(report["pre_encoding_pixel_equal"])
            manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
            self.assertEqual([t["tile_id"] for t in manifest["tiles"]], list(range(16)))
            self.assertEqual(sum(t["w"]*t["h"] for t in manifest["tiles"]), 83*61)
            self.assertEqual(manifest["total_size_bytes"], sum(p.stat().st_size for p in (root/"encoded").glob("*.jpg")))
            self.assertGreaterEqual(manifest["image_processing_seconds"], 0)
            self.assertEqual(len(list((root/"encoded").glob("*.jpg"))), 17)
            with Image.open(root/"encoded"/"thumbnail.jpg") as thumb:
                self.assertLessEqual(max(thumb.size), 256)
            with self.assertRaises(ValueError):
                prepare_image(source, [0, 0, 83, 61], root / "encoded")

    def test_boundary_contact_and_full_roi(self):
        boxes = tile_boxes(8, 8)
        self.assertEqual([i for i, b in enumerate(boxes) if intersects(b, [0, 0, 2, 2])], [0])
        self.assertTrue(all(intersects(b, [0, 0, 8, 8]) for b in boxes))

    def test_invalid_roi_and_small_images(self):
        for roi in (None, [0, 0, 1], [0, 0, 0, 1], [-1, 0, 1, 1],
                    [0, 0, 9, 1], [0, 0, 1.0, 1], [False, 0, 1, 1], [2, 0, 1, 1]):
            with self.subTest(roi=roi), self.assertRaises(ValueError):
                validate_roi(roi, 8, 8)
        with self.assertRaises(ValueError):
            tile_boxes(3, 8)

    def test_exif_rotation_and_rgb(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "rotated.jpg"
            original = Image.new("RGB", (12, 8))
            original.putdata([(x*20, y*30, 40) for y in range(8) for x in range(12)])
            exif = Image.Exif()
            exif[274] = 6
            original.save(source, exif=exif)
            with Image.open(source) as decoded:
                expected = decoded.transpose(Image.Transpose.ROTATE_270).convert("RGB")
                expected.load()
            processed = load_processed_image(source)
            self.assertEqual(processed.size, (8, 12))
            self.assertEqual(processed.tobytes(), expected.tobytes())
            manifest_path = prepare_image(source, [0, 8, 8, 12], Path(directory)/"encoded")
            self.assertTrue(check_image(source, manifest_path, Path(directory)/"check")["pre_encoding_pixel_equal"])
            for mode in ("L", "RGBA", "P"):
                source = Path(directory) / f"{mode}.png"
                Image.new(mode, (8, 8)).save(source)
                self.assertEqual(load_processed_image(source).mode, "RGB")


if __name__ == "__main__":
    unittest.main()
