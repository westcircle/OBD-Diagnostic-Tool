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

    def test_vin_to_maker_lookup(self):
        original = dict(main_cli.WMI_TO_MAKER)
        try:
            main_cli.WMI_TO_MAKER.clear()
            main_cli.WMI_TO_MAKER.update({"JT": "toyota", "JTD": "toyota"})
            self.assertEqual(main_cli.vin_to_maker("JTD12345678901234"), "toyota")
            self.assertEqual(main_cli.vin_to_maker("JT123456789012345"), "toyota")
        finally:
            main_cli.WMI_TO_MAKER.clear()
            main_cli.WMI_TO_MAKER.update(original)


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
