"""检查界面操作的关键交接；不启动常驻网页服务，也不生成正式实验。

在仓库根目录运行：python ui/test_app_integration.py
需要先安装 ui/requirements.txt 中的依赖。
"""

import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from PIL import Image
from streamlit.testing.v1 import AppTest


class AppIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.scratch = tempfile.TemporaryDirectory(prefix=".app_check_", dir=Path(__file__).parent)
        self.addCleanup(self.scratch.cleanup)
        self.root = Path(self.scratch.name)
        environment = mock.patch.dict(os.environ, {"ROI_TRANSFER_WORKSPACE": str(self.root)})
        environment.start()
        self.addCleanup(environment.stop)
        self.app = AppTest.from_file(str(Path(__file__).resolve().with_name("app.py")), default_timeout=30).run()
        self.assert_clean()

    def assert_clean(self):
        self.assertFalse(self.app.exception, str(self.app.exception))
        self.assertFalse(self.app.error, [entry.value for entry in self.app.error])

    def generate(self):
        self.app.button(key="generate").click().run()
        self.assert_clean()
        return self.app.session_state["run"]

    def test_formal_backend_and_four_time_shortcuts(self):
        self.assertEqual(self.app.radio(key="backend").value, "队友正式模块（软件仿真）")
        run = self.generate()
        times = {"time_zero": 0.0,
                 "time_thumbnail": run["results"]["C"]["events"][0]["arrival_s"],
                 "time_roi": run["results"]["C"]["roi_complete_s"],
                 "time_full": run["results"]["B"]["full_complete_s"]}
        for key, expected in times.items():
            with self.subTest(button=key):
                self.app.button(key=key).click().run()
                self.assert_clean()
                self.assertEqual(self.app.session_state["view_time"], expected)
        record = json.loads((self.root / "logs" / f"{run['run_id']}_record.json").read_text(encoding="utf-8"))
        self.assertIsNone(record["ground_truth"])
        self.assertIn("非正式实验", record["stage"])
        self.assertEqual(record["manifest_sha256"], hashlib.sha256(Path(run["manifest_path"]).read_bytes()).hexdigest())

    def test_rate_reuses_jpegs_and_roi_change_hides_old_result(self):
        before = self.generate()
        manifest = Path(before["manifest_path"])
        encoded = {p.name: (p.stat().st_mtime_ns, hashlib.sha256(p.read_bytes()).hexdigest())
                   for p in manifest.parent.glob("*.jpg")}
        self.app.selectbox(key="rate").set_value(1.0).run()
        self.assert_clean()
        self.assertFalse(self.app.slider, "改变参数后不应继续显示旧结果")
        after = self.generate()
        self.assertEqual(after["manifest_path"], before["manifest_path"])
        self.assertEqual(encoded, {p.name: (p.stat().st_mtime_ns, hashlib.sha256(p.read_bytes()).hexdigest())
                                   for p in manifest.parent.glob("*.jpg")})
        self.assertEqual(after["results"]["B"]["total_bytes"], before["results"]["B"]["total_bytes"])
        self.assertAlmostEqual(after["results"]["B"]["full_complete_s"] * 4, before["results"]["B"]["full_complete_s"])
        self.app.number_input(key="x0").set_value(self.app.number_input(key="x0").value + 1).run()
        self.assert_clean()
        self.assertFalse(self.app.slider)
        self.assertTrue(any("参数已经改变" in entry.value for entry in self.app.info))

    def test_ground_truth_confirmation_resets_on_image_change(self):
        self.app.text_input(key="truth").set_value("合成测试标签123.4").run()
        self.app.checkbox(key="truth_checked").check().run()
        self.assertTrue(self.app.checkbox(key="truth_checked").value)
        before = self.generate()
        record = json.loads((self.root / "logs" / f"{before['run_id']}_record.json").read_text(encoding="utf-8"))
        self.assertEqual(record["ground_truth"], "合成测试标签123.4")
        images = self.root / "images"
        images.mkdir()
        Image.new("RGB", (641, 479), "teal").save(images / "another_synthetic_image.png")
        self.app.radio(key="source").set_value("从 images 文件夹选择").run()
        self.assert_clean()
        self.assertEqual(self.app.text_input(key="truth").value, "")
        self.assertFalse(self.app.checkbox(key="truth_checked").value)
        self.assertFalse(self.app.slider)


if __name__ == "__main__":
    unittest.main(verbosity=2)
