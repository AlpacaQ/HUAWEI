"""A组接收因果性检查：整张JPEG完整到达前不能读取或解码。

在仓库根目录运行：python ui/test_receiver_abc.py
这些小型合成图片只用于接口检查，不是巡检实验数据。
"""

import csv
import hashlib
import io
import json
import math
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from PIL import Image

from ui_support import events_csv, render_received


class FullImageReceiverTests(unittest.TestCase):
    def setUp(self):
        self.scratch = tempfile.TemporaryDirectory(prefix=".receiver_a_check_", dir=Path(__file__).parent)
        self.addCleanup(self.scratch.cleanup)
        self.root = Path(self.scratch.name)
        self.image_size = (63, 47)
        self.payload = self.root / "full.jpg"
        Image.new("RGB", self.image_size, "navy").save(self.payload, "JPEG", quality=80)
        self.raw = self.payload.read_bytes()
        self.manifest = self.root / "manifest_A.json"
        self.metadata = {
            "schema_version": 1, "group": "A", "image_id": "synthetic_receiver_a",
            "source_name": "synthetic.png", "source_sha256": "0" * 64,
            "payload": "full.jpg", "width": self.image_size[0], "height": self.image_size[1],
            "mode": "RGB", "quality": 80,
            "size_bytes": len(self.raw), "total_size_bytes": len(self.raw),
            "payload_sha256": hashlib.sha256(self.raw).hexdigest(),
            "image_processing_seconds": 0.0,
            "processing_time_scope": "synthetic receiver test; no encoding benchmark",
        }
        self.write_manifest()
        self.arrival = len(self.raw) * 8 / 1_000_000
        self.events = [{
            "packet_id": "full", "start_s": 0.0, "arrival_s": self.arrival,
            "cumulative_bytes": len(self.raw), "nbytes": len(self.raw), "priority": 1,
        }]

    def write_manifest(self):
        self.manifest.write_text(json.dumps(self.metadata), encoding="utf-8")

    def test_a_is_blank_until_full_jpeg_arrives(self):
        original_read, original_open = Path.read_bytes, Image.open
        for t in (0.0, math.nextafter(self.arrival, -math.inf), self.arrival):
            reads, decoded = [], []

            def read_bytes(path):
                if path.suffix.lower() in (".jpg", ".jpeg"):
                    reads.append(path.resolve())
                return original_read(path)

            def image_open(payload, *args, **kwargs):
                decoded.append(hashlib.sha256(payload.getvalue()).hexdigest())
                return original_open(payload, *args, **kwargs)

            with self.subTest(time=t), mock.patch.object(Path, "read_bytes", new=read_bytes), mock.patch.object(Image, "open", side_effect=image_open):
                canvas, stats = render_received(self.manifest, self.events, t)
            complete = t >= self.arrival
            self.assertEqual(reads, [self.payload.resolve()] if complete else [])
            self.assertEqual(decoded, [hashlib.sha256(self.raw).hexdigest()] if complete else [])
            self.assertEqual(stats["received_bytes"], len(self.raw) if complete else 0)
            self.assertEqual(stats["tiles_received"], int(complete))
            self.assertEqual(stats["roi_complete"], complete)
            if complete:
                with Image.open(io.BytesIO(self.raw)) as expected:
                    self.assertEqual(canvas.tobytes(), expected.convert("RGB").tobytes())
            else:
                self.assertEqual(canvas.getextrema(), ((235, 235),) * 3)
                self.assertEqual(stats["decode_ms"], 0.0)

    def test_a_jpeg_dimensions_are_checked_only_at_arrival(self):
        # 清单声明比真实JPEG宽1像素，只有接收到图片后才能发现这个错误。
        self.metadata["width"] += 1
        self.write_manifest()
        canvas, stats = render_received(self.manifest, self.events, math.nextafter(self.arrival, -math.inf))
        self.assertEqual(canvas.getextrema(), ((235, 235),) * 3)
        self.assertFalse(stats["roi_complete"])
        with self.assertRaisesRegex(ValueError, "JPEG尺寸"):
            render_received(self.manifest, self.events, self.arrival)

    def test_a_csv_has_one_full_packet_with_actual_bytes(self):
        label = "合成图A组接收测试，非正式实验"
        rows = list(csv.DictReader(io.StringIO(events_csv(
            self.manifest, {"events": self.events}, "A", 1.0, label,
        ).decode("utf-8-sig"))))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["packet_id"], "full")
        self.assertEqual(rows[0]["mode"], "A")
        self.assertEqual(rows[0]["source_label"], label)
        self.assertEqual(int(rows[0]["nbytes"]), len(self.raw))
        self.assertEqual(int(rows[0]["cumulative_bytes"]), len(self.raw))
        self.assertEqual(float(rows[0]["arrival_s"]), self.arrival)


if __name__ == "__main__":
    unittest.main(verbosity=2)
