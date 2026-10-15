"""检查图片包配对、不可变性与人工确认状态；不代表读数准确率实验。"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest import mock

from PIL import Image

from shared_package import list_shared_packages, truth_information
from team_bridge import REPOSITORY_ROOT


class SharedPackageTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="shared_package_software_test_")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        # 复制最小样本后才做故障注入；仓库交付包始终只读。
        self.bc = self.root / "inspection_image/delivery_v2"
        self.a = self.root / "inspection_image/delivery_A_v1"
        for destination, index_name in ((self.bc, "package_index.json"), (self.a, "package_index_A.json")):
            original = REPOSITORY_ROOT / destination.relative_to(self.root)
            shutil.copytree(original / "meter05", destination / "meter05")
            index = json.loads((original / index_name).read_text(encoding="utf-8"))
            index["images"] = [entry for entry in index["images"] if entry["image_id"] == "meter05"]
            index["image_count"] = 1
            index["total_size_bytes"] = index["images"][0].get("total_size_bytes", index["images"][0].get("size_bytes"))
            if "transmission_jpeg_count" in index:
                index["transmission_jpeg_count"] = 17
            self.write_json(destination / index_name, index)

    @staticmethod
    def write_json(path, data):
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    def mutate(self, relative, mutation):
        path = self.root / relative
        value = json.loads(path.read_text(encoding="utf-8"))
        mutation(value)
        self.write_json(path, value)

    def snapshot(self):
        return {p.relative_to(self.root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in self.root.rglob("*") if p.is_file()}

    def test_five_actual_packages_pair_and_preserve_truth_states(self):
        packages = list_shared_packages()
        self.assertEqual([p["image_id"] for p in packages], [f"meter{i:02d}" for i in range(1, 6)])
        self.assertEqual([p["image_id"] for p in packages if p["truth_confirmed"]], ["meter01"])
        self.assertEqual([p["truth_status"] for p in packages],
                         ["confirmed", "unable_to_confirm", "pending", "unable_to_confirm", "pending"])
        for item in packages:
            self.assertTrue(Path(item["manifest_a"]).is_absolute())
            self.assertEqual(item["metadata"]["verification"], "sha256_and_size_checked")
            self.assertEqual(len(item["metadata"]["payload_sha256_bc"]), 17)

    def test_read_only_verification_does_not_decode_images(self):
        before = self.snapshot()
        with mock.patch.object(Image, "open", side_effect=AssertionError("不得提前解码图片")):
            result = list_shared_packages(self.root)
        self.assertEqual(len(result), 1)
        self.assertEqual(self.snapshot(), before)
        self.assertFalse(result[0]["truth_confirmed"])
        self.assertTrue(result[0]["ground_truth"]["use_for_reading_accuracy"])

    def test_different_source_same_size_payload_and_missing_file_rejected(self):
        with self.subTest("来源不配对"):
            self.mutate("inspection_image/delivery_A_v1/meter05/manifest_A.json",
                        lambda data: data.update(source_sha256="0" * 64))
            with self.assertRaisesRegex(ValueError, "来源SHA256"):
                list_shared_packages(self.root)
        original_a = REPOSITORY_ROOT / "inspection_image/delivery_A_v1/meter05/manifest_A.json"
        shutil.copyfile(original_a, self.a / "meter05/manifest_A.json")
        tile = self.bc / "meter05/payload/tile_00.jpg"
        before = tile.read_bytes()
        with self.subTest("相同长度的内容变化"):
            tile.write_bytes(bytes([before[0] ^ 1]) + before[1:])
            with self.assertRaisesRegex(ValueError, "SHA256核验失败"):
                list_shared_packages(self.root)
        with self.subTest("缺少文件"):
            tile.unlink()
            with self.assertRaises(FileNotFoundError):
                list_shared_packages(self.root)

    def test_mismatched_image_sets_and_escaping_paths_rejected(self):
        index = self.a / "package_index_A.json"
        original = index.read_bytes()
        self.mutate(index.relative_to(self.root), lambda data: data["images"][0].update(image_id="different"))
        with self.assertRaisesRegex(ValueError, "图片编号集合"):
            list_shared_packages(self.root)
        index.write_bytes(original)
        self.mutate("inspection_image/delivery_v2/package_index.json",
                    lambda data: data["images"][0].update(source_file="../outside.jpg"))
        with self.assertRaisesRegex(ValueError, "不能越出"):
            list_shared_packages(self.root)

    def test_candidate_or_missing_answer_cannot_become_confirmed(self):
        for status in ("pending", "unable_to_confirm", "visually_reviewed"):
            self.assertFalse(truth_information({"human_confirmation": {"status": status},
                             "reading_text": "1.23", "use_for_reading_accuracy": True})["truth_confirmed"])
        self.assertFalse(truth_information({"human_confirmation": {"status": "confirmed"},
                                          "reading_text": None})["truth_confirmed"])
        self.assertTrue(truth_information({"human_confirmation": {"status": "confirmed"},
                                         "reading_text": "1.23", "unit": "V"})["truth_confirmed"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
