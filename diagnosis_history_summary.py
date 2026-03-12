import argparse
import csv
import sys
from collections import Counter
from pathlib import Path


DEFAULT_LIMIT = 5


def get_default_history_path() -> Path:
    return Path(__file__).resolve().parent / "logs" / "diagnosis_history.csv"


def load_diagnosis_history(path: Path) -> list[dict[str, str]] | None:
    if not path.exists():
        return None

    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        return list(reader)


def split_dtc_codes(value: str) -> list[str]:
    return [code.strip() for code in str(value or "").split("|") if code.strip()]


def sort_rows(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    return sorted(rows, key=lambda row: str(row.get("diagnosis_datetime", "")), reverse=True)


def filter_rows(
    rows: list[dict[str, str]],
    dtc: str = "",
    vin: str = "",
    symptom: str = "",
) -> list[dict[str, str]]:
    filtered = rows

    if dtc:
        target = dtc.strip().upper()
        filtered = [
            row for row in filtered if target in [code.upper() for code in split_dtc_codes(row.get("dtc_codes", ""))]
        ]

    if vin:
        target_vin = vin.strip()
        filtered = [row for row in filtered if str(row.get("vin", "")).strip() and str(row.get("vin", "")).strip() == target_vin]

    if symptom:
        keyword = symptom.strip().lower()
        filtered = [row for row in filtered if keyword in str(row.get("symptom", "")).lower()]

    return sort_rows(filtered)


def summarize_dtc_counts(rows: list[dict[str, str]]) -> list[tuple[str, int]]:
    counter = Counter()
    for row in rows:
        for code in split_dtc_codes(row.get("dtc_codes", "")):
            counter[code] += 1
    return counter.most_common()


def build_row_line(row: dict[str, str]) -> str:
    diagnosis_datetime = str(row.get("diagnosis_datetime", "") or "日時不明")
    vin = str(row.get("vin", "") or "-")
    dtc_codes = str(row.get("dtc_codes", "") or "-")
    symptom = str(row.get("symptom", "") or "-")
    overall_level = str(row.get("overall_level", "") or "-")
    return f"- 日時: {diagnosis_datetime} / VIN: {vin} / DTC: {dtc_codes} / 症状: {symptom} / 総合緊急度: {overall_level}"


def print_summary(rows: list[dict[str, str]], limit: int = DEFAULT_LIMIT) -> None:
    print(f"総件数: {len(rows)}")
    print("DTC別件数:")
    dtc_counts = summarize_dtc_counts(rows)
    if not dtc_counts:
        print("- DTC情報はありません")
    else:
        for code, count in dtc_counts[:limit]:
            print(f"- {code}: {count}")
    print("")
    print(f"直近履歴: {min(limit, len(rows))}件")
    print_rows(rows, limit=limit)


def print_rows(rows: list[dict[str, str]], limit: int = DEFAULT_LIMIT) -> None:
    if not rows:
        print("- 表示できる履歴はありません")
        return

    for row in rows[:limit]:
        print(build_row_line(row))


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="diagnosis_history.csv の履歴確認を簡単に行う補助CLIです。")
    parser.add_argument("--dtc", help="指定DTCを含む履歴だけ表示します")
    parser.add_argument("--vin", help="VIN完全一致で履歴を抽出します")
    parser.add_argument("--symptom", help="症状キーワードで部分一致検索します")
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT, help="表示件数を制限します")
    parser.add_argument("--path", default=str(get_default_history_path()), help=argparse.SUPPRESS)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    history_path = Path(args.path)

    try:
        rows = load_diagnosis_history(history_path)
    except Exception as e:
        print(f"diagnosis_history.csv の読み込みに失敗しました: {e}")
        return 1

    if rows is None:
        print("diagnosis_history.csv が見つかりません")
        print("まだ診断履歴が保存されていない可能性があります")
        return 0

    limit = max(args.limit, 0)
    filtered_rows = filter_rows(rows, dtc=args.dtc or "", vin=args.vin or "", symptom=args.symptom or "")

    if args.dtc or args.vin or args.symptom:
        print(f"該当件数: {len(filtered_rows)}")
        print_rows(filtered_rows, limit=limit)
        return 0

    sorted_rows = sort_rows(rows)
    print_summary(sorted_rows, limit=limit)
    return 0


if __name__ == "__main__":
    sys.exit(main())
