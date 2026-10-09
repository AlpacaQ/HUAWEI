"""检查正式队友模块与接收端的交接；合成图片仅作功能测试。

在仓库根目录运行：python ui/test_receiver_integration.py
临时图片会自动清理，不进入真实实验记录。
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

from PIL import Image, ImageDraw

import team_bridge
from ui_support import events_csv, render_received


class ReceiverIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.scratch = tempfile.TemporaryDirectory(prefix=".receiver_check_", dir=Path(__file__).parent)
        cls.root = Path(cls.scratch.name)
        cls.size = (641, 479)  # 不能整除4，能发现边缘像素遗漏。
        picture = Image.new("RGB", cls.size, "navy")
        draw = ImageDraw.Draw(picture)
        for number in range(16):
            x, y = number % 4 * 641 // 4, number // 4 * 479 // 4
            draw.rectangle((x + 8, y + 8, x + 80, y + 70),
                           fill=(number * 13, 240 - number * 9, 50 + number * 7))
            draw.text((x + 10, y + 80), f"TEST ONLY {number}", fill="white")
        cls.input_path = cls.root / "synthetic.png"
        picture.save(cls.input_path)
        cls.roi = (500, 380, 630, 470)
        cls.manifest_path = Path(team_bridge.prepare_image(cls.input_path, cls.roi, cls.root / "encoded"))
        cls.manifest = team_bridge.load_ui_manifest(cls.manifest_path)
        cls.packets = {p["packet_id"]: p for p in cls.manifest["packets"]}
        cls.paths = {key: cls.manifest_path.parent / p["file"] for key, p in cls.packets.items()}
        cls.hashes = {key: hashlib.sha256(path.read_bytes()).hexdigest() for key, path in cls.paths.items()}

    @classmethod
    def tearDownClass(cls):
        cls.scratch.cleanup()

    def test_team_manifest_and_odd_size_coverage(self):
        raw = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        # 原始输出应为邱雪瑶的格式，不能悄悄退回demo_backend。
        self.assertIn("thumbnail", raw)
        self.assertIn("tiles", raw)
        self.assertEqual(len(raw["tiles"]), 16)
        width, height = self.size
        covered = bytearray(width * height)
        for key, packet in self.packets.items():
            self.assertEqual(packet["nbytes"], self.paths[key].stat().st_size)
            if key == "thumb":
                continue
            x0, y0, x1, y1 = packet["bbox"]
            self.assertTrue(0 <= x0 < x1 <= width and 0 <= y0 < y1 <= height)
            for y in range(y0, y1):
                start, end = y * width + x0, y * width + x1
                self.assertNotIn(1, covered[start:end], "图片块不应重叠")
                covered[start:end] = b"\x01" * (x1 - x0)
            expected_roi = max(x0, self.roi[0]) < min(x1, self.roi[2]) and max(y0, self.roi[1]) < min(y1, self.roi[3])
            self.assertEqual(packet["priority"] == 1, expected_roi)
        self.assertNotIn(0, covered, "图片块应覆盖边缘的每一个像素")

    def test_three_rates_share_payload_and_final_pixels(self):
        expected = Image.new("RGB", self.size)
        for key, packet in self.packets.items():
            if key != "thumb":
                with Image.open(self.paths[key]) as tile:
                    expected.paste(tile.convert("RGB"), tuple(packet["bbox"][:2]))
        total = sum(p["nbytes"] for p in self.packets.values())
        for rate in (0.25, 1.0, 5.0):
            results = {mode: team_bridge.simulate(self.manifest_path, rate, mode) for mode in ("B", "C")}
            self.assertEqual(results["B"]["full_complete_s"], results["C"]["full_complete_s"])
            self.assertLess(results["C"]["roi_complete_s"], results["B"]["roi_complete_s"])
            for mode, result in results.items():
                with self.subTest(rate=rate, mode=mode):
                    self.assertEqual(result["total_bytes"], total)
                    self.assertEqual(result["full_complete_s"], total * 8 / (rate * 1_000_000))
                    order = sorted(self.packets, key=lambda key: (key != "thumb", key))
                    if mode == "C":
                        order = sorted(self.packets, key=lambda key: (self.packets[key]["priority"], key))
                    self.assertEqual([e["packet_id"] for e in result["events"]], order)
                    cumulative = 0
                    for event in result["events"]:
                        self.assertEqual(event["start_s"], cumulative * 8 / (rate * 1_000_000))
                        cumulative += self.packets[event["packet_id"]]["nbytes"]
                        self.assertEqual(event["cumulative_bytes"], cumulative)
                        self.assertEqual(event["arrival_s"], cumulative * 8 / (rate * 1_000_000))
                    final, stats = render_received(self.manifest_path, result["events"], result["full_complete_s"])
                    self.assertEqual(final.tobytes(), expected.tobytes())
                    self.assertEqual(stats["tiles_received"], 16)
        self.assertEqual(self.hashes, {key: hashlib.sha256(path.read_bytes()).hexdigest() for key, path in self.paths.items()})

    def test_receiver_only_reads_completed_packets_at_boundaries(self):
        original_read, original_open = Path.read_bytes, Image.open
        for mode in ("B", "C"):
            result = team_bridge.simulate(self.manifest_path, 1.0, mode)
            boundaries = [result["events"][0]["arrival_s"], result["roi_complete_s"], result["full_complete_s"]]
            times = [0.0] + [t for boundary in boundaries for t in (math.nextafter(boundary, -math.inf), boundary)]
            for t in times:
                reads, decoded = [], []

                def read_bytes(path):
                    if path.suffix.lower() in (".jpg", ".jpeg"):
                        reads.append(path.resolve())
                    return original_read(path)

                def image_open(payload, *args, **kwargs):
                    raw = payload.getvalue() if hasattr(payload, "getvalue") else original_read(Path(payload))
                    decoded.append(hashlib.sha256(raw).hexdigest())
                    return original_open(payload, *args, **kwargs)

                with self.subTest(mode=mode, time=t), mock.patch.object(Path, "read_bytes", new=read_bytes), mock.patch.object(Image, "open", side_effect=image_open):
                    image, stats = render_received(self.manifest_path, result["events"], t)
                    received = {e["packet_id"] for e in result["events"] if e["arrival_s"] <= t}
                    self.assertCountEqual(reads, [self.paths[key].resolve() for key in received])
                    self.assertCountEqual(decoded, [self.hashes[key] for key in received])
                    self.assertEqual(stats["received_bytes"], sum(self.packets[key]["nbytes"] for key in received))
                    self.assertEqual(stats["roi_complete"], t >= result["roi_complete_s"])
                    if t == 0:
                        self.assertEqual(len(image.getcolors(maxcolors=2)), 1)

    def test_csv_preserves_test_source_and_actual_bytes(self):
        label = "合成图片接口测试，非真实巡检实验"
        result = team_bridge.simulate(self.manifest_path, 0.25, "C")
        rows = list(csv.DictReader(io.StringIO(events_csv(self.manifest_path, result, "C", 0.25, label).decode("utf-8-sig"))))
        self.assertEqual(len(rows), 17)
        self.assertTrue(all(row["source_label"] == label for row in rows))
        self.assertEqual(sum(int(row["nbytes"]) for row in rows), result["total_bytes"])
        self.assertEqual(float(rows[-1]["arrival_s"]), result["full_complete_s"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
