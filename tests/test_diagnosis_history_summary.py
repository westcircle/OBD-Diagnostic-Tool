import csv
import io
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory

import diagnosis_history_summary


FIELDNAMES = [
    "diagnosis_datetime",
    "vin",
    "maker",
    "model",
    "year",
    "mileage",
    "symptom",
    "dtc_count",
    "dtc_codes",
    "overall_level",
    "overall_reference_notes",
]


def write_history_csv(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)


class TestDiagnosisHistorySummary(unittest.TestCase):
    def test_main_handles_missing_csv(self):
        with TemporaryDirectory() as tmpdir:
            missing_path = Path(tmpdir) / "logs" / "diagnosis_history.csv"
            output = io.StringIO()
            with redirect_stdout(output):
                exit_code = diagnosis_history_summary.main(["--path", str(missing_path)])
            self.assertEqual(exit_code, 0)
            text = output.getvalue()
            self.assertIn("diagnosis_history.csv が見つかりません", text)
            self.assertIn("まだ診断履歴が保存されていない可能性があります", text)

    def test_summarize_dtc_counts_splits_pipe_delimited_codes(self):
        rows = [
            {"dtc_codes": "P0171|P0420"},
            {"dtc_codes": "P0171"},
            {"dtc_codes": ""},
        ]
        counts = dict(diagnosis_history_summary.summarize_dtc_counts(rows))
        self.assertEqual(counts["P0171"], 2)
        self.assertEqual(counts["P0420"], 1)

    def test_summarize_recurring_dtc_details_returns_count_and_last_seen(self):
        rows = [
            {"diagnosis_datetime": "2026-03-10 10:00:00", "dtc_codes": "P0171"},
            {"diagnosis_datetime": "2026-03-12 10:00:00", "dtc_codes": "P0171"},
            {"diagnosis_datetime": "2026-03-11 09:00:00", "dtc_codes": "P0300"},
            {"diagnosis_datetime": "2026-03-09 09:00:00", "dtc_codes": "P0300"},
        ]
        recurring = diagnosis_history_summary.summarize_recurring_dtc_details(rows)
        self.assertEqual(
            recurring,
            [
                {"code": "P0171", "count": 2, "last_seen": "2026-03-12 10:00:00"},
                {"code": "P0300", "count": 2, "last_seen": "2026-03-11 09:00:00"},
            ],
        )

    def test_summarize_recurring_dtc_counts_returns_only_codes_with_two_or_more_hits(self):
        rows = [
            {"dtc_codes": "P0171|P0420"},
            {"dtc_codes": "P0171|P0300"},
            {"dtc_codes": "P0300"},
            {"dtc_codes": "P0300"},
        ]
        recurring = diagnosis_history_summary.summarize_recurring_dtc_counts(rows)
        self.assertEqual(recurring, [("P0300", 3), ("P0171", 2)])

    def test_summarize_recurring_dtc_counts_returns_empty_when_all_codes_are_single_hit(self):
        rows = [
            {"dtc_codes": "P0171"},
            {"dtc_codes": "P0420"},
            {"dtc_codes": "P0300"},
        ]
        self.assertEqual(diagnosis_history_summary.summarize_recurring_dtc_counts(rows), [])

    def test_summarize_recurring_dtc_details_ignores_empty_datetime(self):
        rows = [
            {"diagnosis_datetime": "", "dtc_codes": "P0171"},
            {"diagnosis_datetime": "2026-03-12 10:00:00", "dtc_codes": "P0171"},
        ]
        recurring = diagnosis_history_summary.summarize_recurring_dtc_details(rows)
        self.assertEqual(recurring[0]["last_seen"], "2026-03-12 10:00:00")

    def test_filter_rows_by_dtc(self):
        rows = [
            {"diagnosis_datetime": "2026-03-12 10:00:00", "dtc_codes": "P0171|P0420", "vin": "VIN1", "symptom": "燃費悪化"},
            {"diagnosis_datetime": "2026-03-12 09:00:00", "dtc_codes": "P0300", "vin": "VIN2", "symptom": "失火"},
        ]
        filtered = diagnosis_history_summary.filter_rows(rows, dtc="P0171")
        self.assertEqual(len(filtered), 1)
        self.assertEqual(filtered[0]["vin"], "VIN1")

    def test_filter_rows_by_vin(self):
        rows = [
            {"diagnosis_datetime": "2026-03-12 10:00:00", "dtc_codes": "P0171", "vin": "TESTVIN123", "symptom": "燃費悪化"},
            {"diagnosis_datetime": "2026-03-12 09:00:00", "dtc_codes": "P0171", "vin": "TESTVIN999", "symptom": "燃費悪化"},
            {"diagnosis_datetime": "2026-03-12 08:00:00", "dtc_codes": "P0171", "vin": "", "symptom": "燃費悪化"},
        ]
        filtered = diagnosis_history_summary.filter_rows(rows, vin="TESTVIN123")
        self.assertEqual(len(filtered), 1)
        self.assertEqual(filtered[0]["vin"], "TESTVIN123")

    def test_filter_rows_by_symptom(self):
        rows = [
            {"diagnosis_datetime": "2026-03-12 10:00:00", "dtc_codes": "P0171", "vin": "VIN1", "symptom": "燃費悪化"},
            {"diagnosis_datetime": "2026-03-12 09:00:00", "dtc_codes": "P0171", "vin": "VIN2", "symptom": "始動不良"},
        ]
        filtered = diagnosis_history_summary.filter_rows(rows, symptom="燃費")
        self.assertEqual(len(filtered), 1)
        self.assertEqual(filtered[0]["vin"], "VIN1")

    def test_filter_rows_by_maker(self):
        rows = [
            {"diagnosis_datetime": "2026-03-12 10:00:00", "maker": "トヨタ", "model": "セルシオ", "dtc_codes": "P0171", "vin": "VIN1", "symptom": "燃費悪化", "overall_level": "中"},
            {"diagnosis_datetime": "2026-03-12 09:00:00", "maker": "日産", "model": "キューブ", "dtc_codes": "P0300", "vin": "VIN2", "symptom": "失火", "overall_level": "高"},
        ]
        filtered = diagnosis_history_summary.filter_rows(rows, maker="トヨタ")
        self.assertEqual(len(filtered), 1)
        self.assertEqual(filtered[0]["maker"], "トヨタ")

    def test_filter_rows_by_model(self):
        rows = [
            {"diagnosis_datetime": "2026-03-12 10:00:00", "maker": "トヨタ", "model": "UCF21 セルシオ", "dtc_codes": "P0171", "vin": "VIN1", "symptom": "燃費悪化", "overall_level": "中"},
            {"diagnosis_datetime": "2026-03-12 09:00:00", "maker": "日産", "model": "キューブ", "dtc_codes": "P0300", "vin": "VIN2", "symptom": "失火", "overall_level": "高"},
        ]
        filtered = diagnosis_history_summary.filter_rows(rows, model="セルシオ")
        self.assertEqual(len(filtered), 1)
        self.assertIn("セルシオ", filtered[0]["model"])

    def test_filter_rows_by_level(self):
        rows = [
            {"diagnosis_datetime": "2026-03-12 10:00:00", "maker": "トヨタ", "model": "セルシオ", "dtc_codes": "P0171", "vin": "VIN1", "symptom": "燃費悪化", "overall_level": "高"},
            {"diagnosis_datetime": "2026-03-12 09:00:00", "maker": "トヨタ", "model": "セルシオ", "dtc_codes": "P0300", "vin": "VIN2", "symptom": "失火", "overall_level": "中"},
            {"diagnosis_datetime": "2026-03-12 08:00:00", "maker": "トヨタ", "model": "セルシオ", "dtc_codes": "P0420", "vin": "VIN3", "symptom": "加速不良", "overall_level": "低"},
        ]
        filtered = diagnosis_history_summary.filter_rows(rows, level="中")
        self.assertEqual(len(filtered), 1)
        self.assertEqual(filtered[0]["overall_level"], "中")

    def test_filter_rows_with_combined_conditions(self):
        rows = [
            {"diagnosis_datetime": "2026-03-12 10:00:00", "maker": "トヨタ", "model": "セルシオ", "dtc_codes": "P0171|P0420", "vin": "VIN1", "symptom": "燃費悪化", "overall_level": "中"},
            {"diagnosis_datetime": "2026-03-12 09:00:00", "maker": "トヨタ", "model": "セルシオ", "dtc_codes": "P0300", "vin": "VIN2", "symptom": "失火", "overall_level": "中"},
            {"diagnosis_datetime": "2026-03-12 08:00:00", "maker": "日産", "model": "キューブ", "dtc_codes": "P0171", "vin": "VIN3", "symptom": "燃費悪化", "overall_level": "中"},
        ]
        filtered = diagnosis_history_summary.filter_rows(rows, maker="トヨタ", dtc="P0171")
        self.assertEqual(len(filtered), 1)
        self.assertEqual(filtered[0]["vin"], "VIN1")

    def test_main_applies_limit(self):
        with TemporaryDirectory() as tmpdir:
            history_path = Path(tmpdir) / "logs" / "diagnosis_history.csv"
            write_history_csv(
                history_path,
                [
                    {
                        "diagnosis_datetime": "2026-03-12 10:00:00",
                        "vin": "VIN1",
                        "maker": "トヨタ",
                        "model": "A",
                        "year": "2020",
                        "mileage": "10000",
                        "symptom": "燃費悪化",
                        "dtc_count": "2",
                        "dtc_codes": "P0171|P0420",
                        "overall_level": "中",
                        "overall_reference_notes": "",
                    },
                    {
                        "diagnosis_datetime": "2026-03-12 09:00:00",
                        "vin": "VIN2",
                        "maker": "トヨタ",
                        "model": "B",
                        "year": "2020",
                        "mileage": "20000",
                        "symptom": "始動不良",
                        "dtc_count": "1",
                        "dtc_codes": "P0171",
                        "overall_level": "高",
                        "overall_reference_notes": "",
                    },
                    {
                        "diagnosis_datetime": "2026-03-12 08:00:00",
                        "vin": "VIN3",
                        "maker": "トヨタ",
                        "model": "C",
                        "year": "2020",
                        "mileage": "30000",
                        "symptom": "加速不良",
                        "dtc_count": "0",
                        "dtc_codes": "",
                        "overall_level": "低",
                        "overall_reference_notes": "",
                    },
                ],
            )
            output = io.StringIO()
            with redirect_stdout(output):
                exit_code = diagnosis_history_summary.main(["--path", str(history_path), "--limit", "2"])
            self.assertEqual(exit_code, 0)
            text = output.getvalue()
            self.assertIn("総件数: 3", text)
            self.assertIn("再発上位DTC:", text)
            self.assertIn("最新:", text)
            self.assertEqual(text.count("- 日時:"), 2)

    def test_main_filters_by_new_options(self):
        with TemporaryDirectory() as tmpdir:
            history_path = Path(tmpdir) / "logs" / "diagnosis_history.csv"
            write_history_csv(
                history_path,
                [
                    {
                        "diagnosis_datetime": "2026-03-12 10:00:00",
                        "vin": "VIN1",
                        "maker": "トヨタ",
                        "model": "UCF21 セルシオ",
                        "year": "2020",
                        "mileage": "10000",
                        "symptom": "燃費悪化",
                        "dtc_count": "1",
                        "dtc_codes": "P0171",
                        "overall_level": "中",
                        "overall_reference_notes": "",
                    },
                    {
                        "diagnosis_datetime": "2026-03-12 09:00:00",
                        "vin": "VIN2",
                        "maker": "日産",
                        "model": "キューブ",
                        "year": "2020",
                        "mileage": "20000",
                        "symptom": "始動不良",
                        "dtc_count": "1",
                        "dtc_codes": "P0300",
                        "overall_level": "高",
                        "overall_reference_notes": "",
                    },
                ],
            )
            output = io.StringIO()
            with redirect_stdout(output):
                exit_code = diagnosis_history_summary.main(
                    ["--path", str(history_path), "--maker", "トヨタ", "--level", "中"]
                )
            self.assertEqual(exit_code, 0)
            text = output.getvalue()
            self.assertIn("該当件数: 1", text)
            self.assertIn("VIN1", text)

    def test_main_recurring_option_prints_only_recurring_summary(self):
        with TemporaryDirectory() as tmpdir:
            history_path = Path(tmpdir) / "logs" / "diagnosis_history.csv"
            write_history_csv(
                history_path,
                [
                    {
                        "diagnosis_datetime": "2026-03-12 10:00:00",
                        "vin": "VIN1",
                        "maker": "トヨタ",
                        "model": "A",
                        "year": "2020",
                        "mileage": "10000",
                        "symptom": "燃費悪化",
                        "dtc_count": "2",
                        "dtc_codes": "P0171|P0420",
                        "overall_level": "中",
                        "overall_reference_notes": "",
                    },
                    {
                        "diagnosis_datetime": "2026-03-12 09:00:00",
                        "vin": "VIN2",
                        "maker": "トヨタ",
                        "model": "B",
                        "year": "2020",
                        "mileage": "20000",
                        "symptom": "失火",
                        "dtc_count": "1",
                        "dtc_codes": "P0171",
                        "overall_level": "高",
                        "overall_reference_notes": "",
                    },
                ],
            )
            output = io.StringIO()
            with redirect_stdout(output):
                exit_code = diagnosis_history_summary.main(["--path", str(history_path), "--recurring", "--limit", "5"])
            self.assertEqual(exit_code, 0)
            text = output.getvalue()
            self.assertIn("再発上位DTC:", text)
            self.assertIn("- P0171: 2（最新: 2026-03-12 10:00:00）", text)
            self.assertNotIn("直近履歴:", text)


if __name__ == "__main__":
    unittest.main()
