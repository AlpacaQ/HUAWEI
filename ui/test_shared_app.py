"""检查共享包 A/B/C 页面的实际控件、真值状态和日志。"""

import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from streamlit.testing.v1 import AppTest


class SharedAppTests(unittest.TestCase):
    def setUp(self):
        self.scratch = tempfile.TemporaryDirectory(prefix=".shared_app_", dir=Path(__file__).parent)
        self.addCleanup(self.scratch.cleanup)
        self.root = Path(self.scratch.name)
        env = mock.patch.dict(os.environ, {"ROI_TRANSFER_WORKSPACE": str(self.root)})
        env.start()
        self.addCleanup(env.stop)
        self.app = AppTest.from_file(str(Path(__file__).with_name("app.py").resolve()), default_timeout=60).run()
        self.assert_clean()

    def assert_clean(self):
        self.assertFalse(self.app.exception, str(self.app.exception))
        self.assertFalse(self.app.error, [item.value for item in self.app.error])

    def generate(self):
        self.app.button(key="shared_generate").click().run()
        self.assert_clean()
        return self.app.session_state["shared_run"]

    def test_default_shared_abc_shortcuts_and_downloads(self):
        self.assertEqual(self.app.radio(key="workflow").value, "共享图片包 A/B/C")
        self.assertFalse(self.app.number_input, "共享包不应让用户改 ROI 后继续沿用旧 JPEG")
        run = self.generate()
        self.assertEqual(set(run["results"]), {"A", "B", "C"})
        self.assertEqual(len(self.app.get("download_button")), 4)
        record = json.loads(run["record"])
        self.assertEqual(record["ground_truth"], "3.23 V")
        for key, expected in {
            "zero": 0.0,
            "thumb": run["results"]["C"]["events"][0]["arrival_s"],
            "roi": run["results"]["C"]["roi_complete_s"],
            "a": run["results"]["A"]["full_complete_s"],
            "full": max(item["full_complete_s"] for item in run["results"].values()),
        }.items():
            self.app.button(key="shared_time_" + key).click().run()
            self.assert_clean()
            self.assertEqual(self.app.session_state["shared_time"], expected)
        self.app.checkbox(key="shared_show_roi").check().run()
        self.assert_clean()
        saved = json.loads((self.root / "logs" / f"{run['run_id']}_record.json").read_text(encoding="utf-8"))
        final_time = max(item["full_complete_s"] for item in run["results"].values())
        self.assertEqual(saved["last_receiver_snapshot"]["simulation_time_s"], final_time)
        self.assertEqual(saved["last_receiver_snapshot"]["groups"]["A"]["received_bytes"], run["results"]["A"]["total_bytes"])
        self.assertGreaterEqual(saved["last_receiver_snapshot"]["groups"]["C"]["decode_ms"], 0)
        self.assertIn("A", saved["image_processing"])
        self.assertEqual(len(list((self.root / "logs").glob("abc_*"))), 4)

    def test_changed_rate_hides_old_result_and_pending_truth_stays_pending(self):
        first = self.generate()
        self.app.selectbox(key="shared_rate").set_value(1.0).run()
        self.assert_clean()
        self.assertFalse(self.app.slider)
        second = self.generate()
        self.assertEqual(first["paths"], second["paths"])
        for mode in "ABC":
            self.assertAlmostEqual(first["results"][mode]["full_complete_s"],
                                   second["results"][mode]["full_complete_s"] * 4)
        self.app.selectbox(key="shared_image").set_value("meter03").run()
        self.assert_clean()
        self.assertFalse(self.app.slider)
        pending = json.loads(self.generate()["record"])
        self.assertIsNone(pending["ground_truth"])
        self.assertEqual(pending["ground_truth_status"], "pending")
        self.app.selectbox(key="shared_image").set_value("meter02").run()
        self.assert_clean()
        self.assertIsNone(json.loads(self.generate()["record"])["ground_truth"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
