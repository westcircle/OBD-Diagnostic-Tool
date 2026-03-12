import unittest

from diagnosis import run_multi_diagnosis
import main_cli
from utils import normalize_maker_name, normalize_symptom_name, parse_year_to_western


class TestMainCliBasics(unittest.TestCase):
    def test_parse_dtc_from_43_basic(self):
        raw = "43 0171 0300 0000 >"
        self.assertEqual(main_cli.parse_dtc_from_43(raw), ["P0171", "P0300"])

    def test_parse_dtc_from_43_dedup(self):
        raw = "43 0171 0171 0000 >"
        self.assertEqual(main_cli.parse_dtc_from_43(raw), ["P0171"])

    def test_parse_dtc_from_43_empty_single_4300(self):
        self.assertEqual(main_cli.parse_dtc_from_43("4300 >"), [])

    def test_parse_dtc_from_43_empty_repeated_4300(self):
        self.assertEqual(main_cli.parse_dtc_from_43("4300 4300 >"), [])

    def test_parse_dtc_from_43_empty_repeated_spaced_4300(self):
        self.assertEqual(main_cli.parse_dtc_from_43("43 00 43 00 >"), [])

    def test_vin_to_maker_lookup(self):
        original = dict(main_cli.WMI_TO_MAKER)
        try:
            main_cli.WMI_TO_MAKER.clear()
            main_cli.WMI_TO_MAKER.update({"JT": "toyota", "JTD": "toyota"})
            self.assertEqual(main_cli.vin_to_maker("JTD12345678901234"), "toyota")
            self.assertEqual(main_cli.vin_to_maker("JT123456789012345"), "toyota")
            self.assertIsNone(main_cli.vin_to_maker("AXZH111000662"))
        finally:
            main_cli.WMI_TO_MAKER.clear()
            main_cli.WMI_TO_MAKER.update(original)

    def test_read_vin_stable_with_indexed_multiframe_0902(self):
        original_safe_send = main_cli.safe_send
        original_sleep = main_cli.time.sleep
        try:
            main_cli.safe_send = lambda *args, **kwargs: "014 0:490201575657 1:5A5A5A314B5A42 2:57303735333339 >"
            main_cli.time.sleep = lambda *_args, **_kwargs: None
            self.assertEqual(main_cli.read_vin_stable(None), "WVWZZZ1KZBW075339")
        finally:
            main_cli.safe_send = original_safe_send
            main_cli.time.sleep = original_sleep

    def test_build_dtc_pid_hints_for_maf_and_speed(self):
        hints = main_cli.build_dtc_pid_hints(["P0102", "P0500"], {"MAF": None, "SPEED": 0})
        self.assertTrue(any("MAF値は未取得" in hint for hint in hints))
        self.assertTrue(any("車速は0km/h" in hint for hint in hints))

    def test_build_dtc_pid_hints_empty_when_no_dtc(self):
        hints = main_cli.build_dtc_pid_hints([], {"MAF": 3.0, "SPEED": 0})
        self.assertEqual(hints, [])

    def test_build_dtc_pid_hints_for_p0171_low_maf(self):
        hints = main_cli.build_dtc_pid_hints(
            ["P0171"],
            {"RPM": 780, "ECT": 82, "MAF": 3.5, "SPEED": 0, "IAT": 18, "THROTTLE": 8},
        )
        self.assertTrue(any("二次エア" in hint or "エアフロ汚れ" in hint for hint in hints))

    def test_build_dtc_pid_hints_for_p0500_speed_missing(self):
        hints = main_cli.build_dtc_pid_hints(
            ["P0500"],
            {"RPM": 900, "ECT": 80, "MAF": 4.0, "SPEED": None, "IAT": 20, "THROTTLE": 9},
        )
        self.assertTrue(any("車速PIDは未取得" in hint for hint in hints))

    def test_build_dtc_pid_hints_for_b2797(self):
        hints = main_cli.build_dtc_pid_hints(
            ["B2797"],
            {"RPM": None, "ECT": None, "MAF": None, "SPEED": None, "IAT": None, "THROTTLE": None},
        )
        self.assertTrue(any("イモビ系" in hint or "認証系" in hint for hint in hints))

    def test_build_dtc_pid_hints_for_b2797_with_empty_pid_dict(self):
        hints = main_cli.build_dtc_pid_hints(["B2797"], {})
        self.assertNotEqual(hints, [])

    def test_build_dtc_pid_hints_with_many_missing_pids(self):
        hints = main_cli.build_dtc_pid_hints(
            ["P0500", "B2797"],
            {"RPM": None, "ECT": None, "MAF": None, "SPEED": None, "IAT": None, "THROTTLE": 10},
        )
        self.assertTrue(any("PID取得が限定的" in hint for hint in hints))

    def test_classify_vin_text(self):
        self.assertTrue(main_cli.classify_vin_text("WVWZZZ1KZBW075339")["is_full_vin"])
        partial = main_cli.classify_vin_text("AXZH111000662")
        self.assertEqual(partial["label"], "VIN候補")
        self.assertIn("17文字未満", partial["note"])
        missing = main_cli.classify_vin_text("")
        self.assertEqual(missing["value"], "未取得")

    def test_get_vehicle_profile_by_maker(self):
        profile = main_cli.get_vehicle_profile(maker="volkswagen")
        self.assertIsNotNone(profile)
        self.assertIn("VW", profile["title"])

    def test_get_vehicle_profile_lexus_es_hybrid(self):
        profile = main_cli.get_vehicle_profile(maker="lexus", model="ES300h")
        self.assertIsNotNone(profile)
        self.assertIn("レクサスES", profile["title"])
        self.assertIn("VIN候補", profile["vin_hint"])

    def test_get_vehicle_profile_ucf21_celsior(self):
        profile = main_cli.get_vehicle_profile(maker="toyota", model="UCF21 セルシオ")
        self.assertIsNotNone(profile)
        self.assertIn("セルシオ", profile["title"])
        self.assertIn("UNABLE TO CONNECT", profile["connect_hint"])

    def test_analyze_live_csv_summary(self):
        import os
        import tempfile

        with tempfile.NamedTemporaryFile("w", delete=False, newline="", encoding="utf-8", suffix=".csv") as f:
            f.write("time,rpm,ect,maf,speed,iat,thr\n")
            f.write("10:00:00,750,55,3.2,0,22,11\n")
            f.write("10:00:01,780,60,,0,23,12\n")
            path = f.name
        try:
            summary = main_cli.analyze_live_csv(path)
            self.assertEqual(summary["row_count"], 2)
            self.assertEqual(summary["rpm"]["min"], 750.0)
            self.assertEqual(summary["rpm"]["max"], 780.0)
            self.assertEqual(summary["ect"]["max"], 60.0)
            self.assertEqual(summary["maf"]["missing"], 1)
        finally:
            os.unlink(path)

    def test_build_idle_hint_idle_like(self):
        hints = main_cli.build_idle_hint(
            {
                "rpm": {"avg": 780.0},
                "speed": {"max": 0.0},
                "thr": {"avg": 11.0},
            }
        )
        self.assertTrue(any("アイドル中心" in hint for hint in hints))

    def test_build_idle_hint_drive_like(self):
        hints = main_cli.build_idle_hint(
            {
                "rpm": {"avg": 1850.0},
                "speed": {"max": 38.0},
                "thr": {"avg": 28.0},
            }
        )
        self.assertTrue(any("走行を含む" in hint for hint in hints))

    def test_build_warmup_hint_warming_up(self):
        hints = main_cli.build_warmup_hint(
            {
                "ect": {"count": 4, "missing": 0, "min": 42.0, "max": 63.0, "avg": 54.0},
            }
        )
        self.assertTrue(any("暖機途中" in hint for hint in hints))

    def test_build_warmup_hint_warmed(self):
        hints = main_cli.build_warmup_hint(
            {
                "ect": {"count": 4, "missing": 0, "min": 78.0, "max": 86.0, "avg": 82.0},
            }
        )
        self.assertTrue(any("暖機後" in hint for hint in hints))

    def test_build_warmup_hint_missing(self):
        hints = main_cli.build_warmup_hint(
            {
                "ect": {"count": 0, "missing": 5},
            }
        )
        self.assertTrue(any("判定保留" in hint for hint in hints))

    def test_build_missing_column_summary(self):
        info = main_cli.build_missing_column_summary(
            {
                "row_count": 10,
                "rpm": {"missing": 0},
                "ect": {"missing": 0},
                "maf": {"missing": 8},
                "speed": {"missing": 0},
                "iat": {"missing": 2},
                "thr": {"missing": 6},
            }
        )
        self.assertIn("MAF: 空欄 8/10", info["details"])
        self.assertIn("MAF", info["many_missing"])
        self.assertIn("THR", info["many_missing"])

    def test_classify_live_log_type_stopped(self):
        result = main_cli.classify_live_log_type(
            {
                "row_count": 4,
                "speed": {"count": 4, "max": 0.0, "avg": 0.0},
                "rpm": {"avg": 780.0},
                "thr": {"avg": 11.0},
            }
        )
        self.assertEqual(result["label"], "停止中心ログ")

    def test_classify_live_log_type_driving(self):
        result = main_cli.classify_live_log_type(
            {
                "row_count": 4,
                "speed": {"count": 4, "max": 40.0, "avg": 30.0},
                "rpm": {"avg": 1800.0},
                "thr": {"avg": 24.0},
            }
        )
        self.assertEqual(result["label"], "走行ありログ")

    def test_classify_live_log_type_mixed(self):
        result = main_cli.classify_live_log_type(
            {
                "row_count": 4,
                "speed": {"count": 4, "max": 30.0, "avg": 15.0},
                "rpm": {"avg": 1200.0},
                "thr": {"avg": 15.0},
            }
        )
        self.assertEqual(result["label"], "混在ログ")

    def test_classify_live_log_type_pending(self):
        result = main_cli.classify_live_log_type(
            {
                "row_count": 4,
                "speed": {"count": 0, "missing": 4},
                "rpm": {"avg": 900.0},
                "thr": {"avg": 12.0},
            }
        )
        self.assertEqual(result["label"], "判定保留")

    def test_build_dtc_history_hints_with_matches(self):
        import os
        import tempfile

        with tempfile.NamedTemporaryFile("w", delete=False, newline="", encoding="utf-8", suffix=".csv") as f:
            f.write("日時,VIN,メーカー,車種,年式,走行距離,DTC一覧,症状,総合緊急度,実車確認メモ\n")
            f.write("2026-03-10 10:00:00,,toyota,,, ,P0420,燃費悪化,中,\n")
            f.write("2026-03-11 11:00:00,,toyota,,, ,P0420,燃費悪化,中,\n")
            path = f.name
        try:
            hints = main_cli.build_dtc_history_hints(["P0420"], history_path=path)
            self.assertTrue(any("過去 2 回" in hint for hint in hints))
            self.assertTrue(any("前回履歴" in hint for hint in hints))
        finally:
            os.unlink(path)

    def test_build_dtc_history_hints_without_history_file(self):
        hints = main_cli.build_dtc_history_hints(["P0420"], history_path="C:\\not_found_history.csv")
        self.assertEqual(hints, [])

    def test_build_dtc_history_hints_without_matches(self):
        import os
        import tempfile

        with tempfile.NamedTemporaryFile("w", delete=False, newline="", encoding="utf-8", suffix=".csv") as f:
            f.write("日時,VIN,メーカー,車種,年式,走行距離,DTC一覧,症状,総合緊急度,実車確認メモ\n")
            f.write("2026-03-10 10:00:00,,toyota,,, ,P0171,燃費悪化,中,\n")
            path = f.name
        try:
            hints = main_cli.build_dtc_history_hints(["P0420"], history_path=path)
            self.assertEqual(hints, [])
        finally:
            os.unlink(path)


class TestUtilsNormalize(unittest.TestCase):
    def test_normalize_maker_name(self):
        self.assertEqual(normalize_maker_name(" toyota "), "トヨタ")
        self.assertEqual(normalize_maker_name("ニッサン"), "日産")

    def test_normalize_symptom_name(self):
        self.assertEqual(normalize_symptom_name("停車中に回転がばらつく"), "アイドリング不安定")
        self.assertEqual(normalize_symptom_name("燃費が悪い"), "燃費悪化")

    def test_parse_year_to_western(self):
        self.assertEqual(parse_year_to_western("1997"), 1997)
        self.assertEqual(parse_year_to_western("平成10年"), 1998)
        self.assertEqual(parse_year_to_western("R5"), 2023)
        self.assertIsNone(parse_year_to_western("不明"))


class TestDiagnosisBasic(unittest.TestCase):
    def test_run_multi_diagnosis_with_codes(self):
        result = run_multi_diagnosis(
            maker="トヨタ",
            model="テスト車",
            year="1999",
            mileage="100000",
            dtc_codes=["P0171", "P0300", "P0171"],
            symptom="燃費悪化",
        )
        self.assertEqual(result["dtc_codes"], ["P0171", "P0300"])
        self.assertEqual(len(result["diagnoses"]), 2)
        self.assertIn(result["overall_level"], ["高", "中", "低", "不明"])

    def test_run_multi_diagnosis_without_codes(self):
        result = run_multi_diagnosis(
            maker="",
            model="",
            year="",
            mileage="",
            dtc_codes=[],
            symptom="",
        )
        self.assertEqual(result["dtc_codes"], [])
        self.assertEqual(len(result["diagnoses"]), 1)
        self.assertEqual(result["diagnoses"][0]["dtc_code"], "未入力")


if __name__ == "__main__":
    unittest.main()
