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
                        "dtc_codes": "P0300",
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
            self.assertEqual(text.count("- 日時:"), 2)


if __name__ == "__main__":
    unittest.main()
