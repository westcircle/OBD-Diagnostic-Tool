import os
import tempfile
import unittest

import compare_live_csv


class TestCompareLiveCsv(unittest.TestCase):
    def test_safe_float_handles_missing_values(self):
        self.assertIsNone(compare_live_csv.safe_float(""))
        self.assertIsNone(compare_live_csv.safe_float("NO DATA"))
        self.assertIsNone(compare_live_csv.safe_float("未取得"))
        self.assertEqual(compare_live_csv.safe_float("12.5"), 12.5)

    def test_summarize_pid_returns_stats(self):
        rows = [
            {"rpm": "700"},
            {"rpm": "800"},
            {"rpm": ""},
        ]
        summary = compare_live_csv.summarize_pid(rows, "rpm")
        self.assertEqual(summary["count"], 2)
        self.assertEqual(summary["missing"], 1)
        self.assertEqual(summary["min"], 700.0)
        self.assertEqual(summary["max"], 800.0)
        self.assertEqual(summary["avg"], 750.0)

    def test_classify_log_type_stopped_and_driving(self):
        stopped = compare_live_csv.classify_log_type(
            [{"speed": "0", "rpm": "750", "thr": "10"}, {"speed": "0", "rpm": "780", "thr": "11"}]
        )
        driving = compare_live_csv.classify_log_type(
            [{"speed": "30", "rpm": "1800", "thr": "20"}, {"speed": "40", "rpm": "2100", "thr": "24"}]
        )
        self.assertEqual(stopped["label"], "停止中心ログ")
        self.assertEqual(driving["label"], "走行ありログ")

    def test_build_summary_handles_missing_columns(self):
        with tempfile.NamedTemporaryFile("w", delete=False, newline="", encoding="utf-8", suffix=".csv") as f:
            f.write("time,rpm,ect\n")
            f.write("10:00:00,750,60\n")
            path = f.name
        try:
            summary = compare_live_csv.build_summary(path)
            self.assertEqual(summary["row_count"], 1)
            self.assertEqual(summary["maf"]["count"], 0)
            self.assertEqual(summary["speed"]["missing"], 1)
        finally:
            os.unlink(path)

    def test_build_summary_can_reuse_main_cli_anomalies(self):
        with tempfile.NamedTemporaryFile("w", delete=False, newline="", encoding="utf-8", suffix=".csv") as f:
            f.write("time,rpm,ect,maf,speed,iat,thr\n")
            f.write("10:00:00,700,80,3.0,0,20,10\n")
            f.write("10:00:01,900,81,3.2,0,20,10\n")
            f.write("10:00:02,720,82,3.1,0,21,11\n")
            f.write("10:00:03,910,82,3.2,0,21,11\n")
            f.write("10:00:04,730,83,3.0,0,21,10\n")
            path = f.name
        try:
            summary = compare_live_csv.build_summary(path)
            self.assertIn("anomalies", summary)
            self.assertTrue(any("RPMのばらつき" in line for line in summary["anomalies"]))
        finally:
            os.unlink(path)

    def test_build_summary_anomalies_with_missing_columns_does_not_fail(self):
        with tempfile.NamedTemporaryFile("w", delete=False, newline="", encoding="utf-8", suffix=".csv") as f:
            f.write("time,rpm\n")
            f.write("10:00:00,750\n")
            path = f.name
        try:
            summary = compare_live_csv.build_summary(path)
            self.assertIn("anomalies", summary)
            self.assertIsInstance(summary["anomalies"], list)
        finally:
            os.unlink(path)

    def test_print_single_anomaly_section_with_empty_comments(self):
        compare_live_csv.print_single_anomaly_section(
            {"anomalies": [], "row_count": 0},
            {"anomalies": [], "row_count": 0},
        )


if __name__ == "__main__":
    unittest.main()
