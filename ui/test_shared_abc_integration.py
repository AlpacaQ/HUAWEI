"""用已交付的5张图片包检查A/B/C集成，不重新压缩、不写入共享包。

在仓库根目录运行：python ui/test_shared_abc_integration.py
检查5张图片×3档速率×3组的45份时间表，并核对前后全部包文件的SHA256。
这是集成验证，不测量人工读数正确率，不代表真实无线网络实验。
"""

import hashlib
import json
import math
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from PIL import Image

import team_bridge
from ui_support import render_received


ROOT = Path(__file__).resolve().parents[1]
BC_ROOT = ROOT / "inspection_image" / "delivery_v2"
A_ROOT = ROOT / "inspection_image" / "delivery_A_v1"


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def package_snapshot():
    """文件名也纳入比较，能发现新增的派生清单或缓存文件。"""
    return {
        path.relative_to(ROOT).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for folder in (BC_ROOT, A_ROOT) for path in sorted(folder.rglob("*"))
        if path.is_file()
    }


class SharedABCIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.before = package_snapshot()
        cls.bc_index = read_json(BC_ROOT / "package_index.json")
        cls.a_index = read_json(A_ROOT / "package_index_A.json")
        cls.bc_images = {entry["image_id"]: entry for entry in cls.bc_index["images"]}
        cls.a_images = {entry["image_id"]: entry for entry in cls.a_index["images"]}

    @classmethod
    def tearDownClass(cls):
        unittest.TestCase().assertEqual(cls.before, package_snapshot(), "集成过程不能增删或修改共享图片包中的任何文件")

    def test_five_images_three_rates_all_schedules(self):
        self.assertEqual(len(self.bc_images), 5)
        self.assertEqual(set(self.bc_images), set(self.a_images))
        checked = 0
        for image_id, entry in self.bc_images.items():
            bc_path = BC_ROOT / entry["manifest"]
            a_path = A_ROOT / self.a_images[image_id]["manifest"]
            raw_bc, raw_a = read_json(bc_path), read_json(a_path)
            source_digest = hashlib.sha256((BC_ROOT / entry["source_file"]).read_bytes()).hexdigest()
            self.assertEqual(source_digest, entry["source_sha256"])
            self.assertEqual(source_digest, raw_a["source_sha256"])
            self.assertEqual((raw_bc["width"], raw_bc["height"]), (raw_a["width"], raw_a["height"]))
            self.assertTrue(all(tile["quality"] == raw_a["quality"] for tile in raw_bc["tiles"]))
            bc_packets = {p["packet_id"]: p for p in team_bridge.load_ui_manifest(bc_path)["packets"]}
            actual_bc = {key: (bc_path.parent / p["file"]).stat().st_size for key, p in bc_packets.items()}
            actual_a = (a_path.parent / raw_a["payload"]).stat().st_size
            for packet in bc_packets.values():
                digest = hashlib.sha256((bc_path.parent / packet["file"]).read_bytes()).hexdigest()
                self.assertEqual(digest, entry["payload_sha256"][packet["file"]])
            self.assertEqual(hashlib.sha256((a_path.parent / raw_a["payload"]).read_bytes()).hexdigest(), raw_a["payload_sha256"])
            self.assertEqual(sum(actual_bc.values()), entry["total_size_bytes"])
            self.assertEqual(actual_a, self.a_images[image_id]["size_bytes"])
            roi_ids = {f"tile_{tile['tile_id']:02d}" for tile in raw_bc["tiles"] if tile["priority"] == 1}
            self.assertEqual(roi_ids, {f"tile_{tile_id:02d}" for tile_id in entry["priority_tile_ids"]})
            for rate in (0.25, 1.0, 5.0):
                results = {mode: team_bridge.simulate(a_path if mode == "A" else bc_path, rate, mode)
                           for mode in ("A", "B", "C")}
                self.assertEqual(results["B"]["total_bytes"], results["C"]["total_bytes"])
                self.assertEqual(results["B"]["full_complete_s"], results["C"]["full_complete_s"])
                self.assertLessEqual(results["C"]["roi_complete_s"], results["B"]["roi_complete_s"])
                for mode, result in results.items():
                    with self.subTest(image=image_id, rate=rate, mode=mode):
                        sizes = {"full": actual_a} if mode == "A" else actual_bc
                        expected_order = ["full"] if mode == "A" else ["thumb"] + sorted(
                            (key for key in bc_packets if key != "thumb"),
                            key=lambda key: (key not in roi_ids, key) if mode == "C" else key,
                        )
                        self.assertEqual(result["mode"], mode)
                        self.assertEqual(result["rate_mbps"], rate)
                        self.assertEqual([event["packet_id"] for event in result["events"]], expected_order)
                        self.assertEqual(result["total_bytes"], sum(sizes.values()))
                        self.assertEqual(result["full_complete_s"], sum(sizes.values()) * 8 / (rate * 1_000_000))
                        cumulative = 0
                        for event in result["events"]:
                            self.assertEqual(event["start_s"], cumulative * 8 / (rate * 1_000_000))
                            self.assertEqual(event["nbytes"], sizes[event["packet_id"]])
                            cumulative += sizes[event["packet_id"]]
                            self.assertEqual(event["cumulative_bytes"], cumulative)
                            self.assertEqual(event["arrival_s"], cumulative * 8 / (rate * 1_000_000))
                        target_ids = {"full"} if mode == "A" else roi_ids
                        self.assertEqual(result["roi_complete_s"], max(
                            event["arrival_s"] for event in result["events"] if event["packet_id"] in target_ids
                        ))
                        checked += 1
        self.assertEqual(checked, 45)

    def test_existing_meter05_bc_final_pixels_match(self):
        # 一张真实小图完整解码即可验证接收路径，避免45次解码超大图片。
        path = BC_ROOT / self.bc_images["meter05"]["manifest"]
        completed = {}
        for mode in ("B", "C"):
            result = team_bridge.simulate(path, 1.0, mode)
            canvas, stats = render_received(path, result["events"], result["full_complete_s"])
            completed[mode] = canvas.tobytes()
            self.assertEqual(stats["tiles_received"], 16)
            self.assertEqual(stats["received_bytes"], result["total_bytes"])
            self.assertTrue(stats["roi_complete"])
        self.assertEqual(completed["B"], completed["C"])

    def test_existing_meter05_a_waits_for_complete_arrival(self):
        path = A_ROOT / self.a_images["meter05"]["manifest"]
        result = team_bridge.simulate(path, 1.0, "A")
        just_before = math.nextafter(result["full_complete_s"], -math.inf)
        with mock.patch.object(Image, "open", side_effect=AssertionError("不能提前解码整图")):
            canvas, stats = render_received(path, result["events"], just_before)
        self.assertEqual(canvas.getextrema(), ((235, 235),) * 3)
        self.assertEqual(stats["received_bytes"], 0)
        canvas, stats = render_received(path, result["events"], result["full_complete_s"])
        with Image.open(path.parent / "full.jpg") as expected:
            self.assertEqual(canvas.tobytes(), expected.convert("RGB").tobytes())
        self.assertEqual(stats["received_bytes"], result["total_bytes"])
        self.assertEqual(stats["tiles_received"], 1)
        self.assertTrue(stats["roi_complete"])

    def test_zero_benefit_case_is_retained(self):
        # ROI已在第一块时，C组不能声称总有收益；该例只用于逻辑验证。
        with tempfile.TemporaryDirectory(prefix=".zero_benefit_check_", dir=Path(__file__).parent) as scratch:
            folder = Path(scratch)
            source = folder / "synthetic.png"
            Image.new("RGB", (64, 64), "navy").save(source)
            path = team_bridge.prepare_image(source, (0, 0, 8, 8), folder / "payload")
            result_b = team_bridge.simulate(path, 1.0, "B")
            result_c = team_bridge.simulate(path, 1.0, "C")
            self.assertEqual(result_b["events"], result_c["events"])
            self.assertEqual(result_b["roi_complete_s"], result_c["roi_complete_s"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
