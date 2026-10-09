"""适配层功能测试。仅使用临时合成图片，不属于真实巡检实验数据。

在仓库根目录运行：python -m unittest discover -s ui -p test_team_bridge.py -v
所有图片包都在临时目录生成，测试结束自动清理。
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from PIL import Image, ImageDraw

import team_bridge as bridge


class TeamBridgeTests(unittest.TestCase):
    def setUp(self):
        # 受限环境可指定可写目录，正常电脑默认使用系统临时目录。
        scratch = os.environ.get("ROI_TEST_TMPDIR")
        if scratch:
            scratch = Path(scratch).resolve()
            scratch.mkdir(parents=True, exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(prefix="roi_bridge_software_test_", dir=scratch)
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        source = self.root / "SYNTHETIC_SOFTWARE_TEST.png"
        image = Image.new("RGB", (401, 277), "#c5d2df")
        drawing = ImageDraw.Draw(image)
        drawing.rectangle((270, 180, 389, 259), fill="white", outline="black", width=3)
        drawing.text((282, 204), "TEST 123.4", fill="black")
        drawing.text((10, 10), "SYNTHETIC TEST / NOT FIELD DATA", fill="black")
        image.save(source)
        self.manifest_path = Path(bridge.prepare_image(source, [270, 180, 390, 260], self.root / "image_package"))
        self.canonical = json.loads(self.manifest_path.read_text(encoding="utf-8"))

    def write_mutation(self, change):
        changed = copy.deepcopy(self.canonical)
        change(changed)
        self.manifest_path.write_text(json.dumps(changed), encoding="utf-8")

    def test_real_modules_three_rates_share_payload_and_preserve_originals(self):
        """真实调用两位队友：检查公平对照、图块哈希以及原始清单不变。"""
        image_dir = self.manifest_path.parent
        original_hashes = {path.name: hashlib.sha256(path.read_bytes()).hexdigest()
                           for path in image_dir.iterdir()}
        transmitter = bridge._team_module("transmission")
        with mock.patch.object(transmitter, "simulate", wraps=transmitter.simulate) as wrapped:
            for rate in (0.25, 1, 5):
                normal = bridge.simulate(self.manifest_path, rate, "B")
                prioritized = bridge.simulate(self.manifest_path, rate, "C")
                self.assertEqual(normal["total_bytes"], prioritized["total_bytes"])
                self.assertEqual(normal["total_bytes"], self.canonical["total_size_bytes"])
                self.assertEqual(normal["full_complete_s"], prioritized["full_complete_s"])
                self.assertEqual(normal["full_complete_s"], normal["total_bytes"] * 8 / (rate * 1_000_000))
                self.assertLessEqual(prioritized["roi_complete_s"], normal["roi_complete_s"])
                self.assertEqual([event["packet_id"] for event in normal["events"]],
                                 ["thumb"] + [f"tile_{index:02d}" for index in range(16)])
                self.assertEqual(len(prioritized["events"]), 17)
                self.assertEqual(prioritized["events"][0]["packet_id"], "thumb")
                self.assertEqual(sorted(event["packet_id"] for event in normal["events"]),
                                 sorted(event["packet_id"] for event in prioritized["events"]))
                self.assertEqual([event["priority"] for event in prioritized["events"]],
                                 sorted(event["priority"] for event in prioritized["events"]))
            self.assertEqual(wrapped.call_count, 6)
        for name, original_hash in original_hashes.items():
            self.assertEqual(hashlib.sha256((image_dir / name).read_bytes()).hexdigest(), original_hash)

    def test_view_reused_without_rewriting_and_mismatch_rejected(self):
        bridge.simulate(self.manifest_path, 1, "B")
        view_path = self.manifest_path.parent / bridge.TRANSMISSION_VIEW_NAME
        before = view_path.stat().st_mtime_ns
        before_bytes = view_path.read_bytes()
        bridge.simulate(self.manifest_path, 5, "C")
        self.assertEqual(view_path.read_bytes(), before_bytes)
        self.assertEqual(view_path.stat().st_mtime_ns, before)
        bad = json.loads(before_bytes)
        bad["tiles"][0]["is_roi"] = not bad["tiles"][0]["is_roi"]
        view_path.write_text(json.dumps(bad), encoding="utf-8")
        changed_bytes = view_path.read_bytes()
        with self.assertRaisesRegex(ValueError, "拒绝覆盖"):
            bridge.simulate(self.manifest_path, 1, "B")
        self.assertEqual(view_path.read_bytes(), changed_bytes)

    def test_metadata_does_not_open_jpegs(self):
        original_open = Path.open

        def guarded_open(path, *args, **kwargs):
            if path.suffix.lower() in (".jpg", ".jpeg"):
                self.fail("读取接收端元数据时提前打开了JPEG")
            return original_open(path, *args, **kwargs)

        with mock.patch.object(Path, "open", guarded_open):
            manifest = bridge.load_ui_manifest(self.manifest_path)
        self.assertEqual(manifest["processing_ms"], {"total_ms": self.canonical["image_processing_seconds"] * 1000})
        self.assertEqual(len(manifest["packets"]), 17)
        self.assertEqual(manifest["packets"][0]["encoded_size"],
                         [self.canonical["thumbnail"]["width"], self.canonical["thumbnail"]["height"]])
        self.assertNotIn("encode_ms", manifest["processing_ms"])

    def test_missing_jpeg_allowed_for_metadata_but_rejected_by_sender(self):
        missing = self.manifest_path.parent / self.canonical["tiles"][0]["payload"]
        missing.unlink()
        bridge.load_ui_manifest(self.manifest_path)
        with self.assertRaises(FileNotFoundError):
            bridge.simulate(self.manifest_path, 1, "B")

    def test_sender_checks_actual_jpeg_size(self):
        path = self.manifest_path.parent / self.canonical["tiles"][0]["payload"]
        with path.open("ab") as stream:
            stream.write(b"test-extra-byte")
        bridge.load_ui_manifest(self.manifest_path)
        with self.assertRaisesRegex(ValueError, "字节数不符"):
            bridge.simulate(self.manifest_path, 1, "C")

    def test_invalid_roi_priority_geometry_ids_fields_and_totals_rejected(self):
        mutations = {
            "missing_roi": lambda data: data.pop("roi"),
            "empty_roi": lambda data: data.update(roi=[1, 1, 1, 2]),
            "priority_wrong": lambda data: data["tiles"][0].update(priority=1),
            "no_roi_tiles": lambda data: [tile.update(priority=0) for tile in data["tiles"]],
            "priority_bool": lambda data: data["tiles"][0].update(priority=False),
            "tile_id_bool": lambda data: data["tiles"][0].update(tile_id=False),
            "duplicate_id": lambda data: data["tiles"][1].update(tile_id=0),
            "wrong_box": lambda data: data["tiles"][0].update(box=[0, 0, 99, 69]),
            "wrong_width": lambda data: data["tiles"][0].update(w=999),
            "wrong_image_id": lambda data: data["tiles"][0].update(image_id="other-image"),
            "missing_size": lambda data: data["tiles"][0].pop("size_bytes"),
            "wrong_total": lambda data: data.update(total_size_bytes=1),
            "escaping_path": lambda data: data["tiles"][0].update(payload="../outside.jpg"),
            "absolute_path": lambda data: data["tiles"][0].update(payload="C:/outside.jpg"),
            "duplicate_path": lambda data: data["tiles"][0].update(payload=data["thumbnail"]["payload"]),
            "thumbnail_geometry": lambda data: data["thumbnail"].update(width=1000),
            "missing_processing_seconds": lambda data: data.pop("image_processing_seconds"),
        }
        for name, mutate in mutations.items():
            with self.subTest(name=name):
                self.write_mutation(mutate)
                with self.assertRaises(ValueError):
                    bridge.load_ui_manifest(self.manifest_path)

    def test_legacy_demo_packets_remain_readable(self):
        normalized = bridge.load_ui_manifest(self.manifest_path)
        normalized.pop("total_size_bytes")
        self.manifest_path.write_text(json.dumps(normalized), encoding="utf-8")
        self.assertEqual(bridge.load_ui_manifest(self.manifest_path), normalized)

    def test_backend_metadata_identifies_actual_module_bytes(self):
        metadata = bridge.backend_metadata()
        for key in ("image_processing", "transmission", "bridge"):
            path = bridge.REPOSITORY_ROOT / metadata[key]["path"]
            self.assertEqual(metadata[key]["sha256"], hashlib.sha256(path.read_bytes()).hexdigest())


if __name__ == "__main__":
    unittest.main(verbosity=2)
