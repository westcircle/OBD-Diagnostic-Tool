import argparse
import csv
import glob
import os
import sys

import main_cli


PID_COLUMNS = [
    ("rpm", "RPM"),
    ("ect", "ECT"),
    ("maf", "MAF"),
    ("speed", "SPEED"),
    ("iat", "IAT"),
    ("thr", "THR"),
]


def choose_latest_two_live_csv(log_dir=main_cli.LOG_DIR):
    files = sorted(
        [
            path
            for path in glob.glob(os.path.join(log_dir, "live_*.csv"))
            if os.path.isfile(path)
        ]
    )
    if len(files) < 2:
        return None, None
    return files[-2], files[-1]


def safe_float(value):
    text = str(value or "").strip()
    if not text:
        return None
    if text.upper() == "NO DATA" or text == "未取得":
        return None
    try:
        return float(text)
    except Exception:
        return None


def load_live_csv(path):
    with open(path, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
        return rows, reader.fieldnames or []


def summarize_pid(rows, key):
    values = []
    missing = 0
    for row in rows:
        value = safe_float(row.get(key))
        if value is None:
            missing += 1
        else:
            values.append(value)

    summary = {"count": len(values), "missing": missing}
    if values:
        summary["min"] = min(values)
        summary["max"] = max(values)
        summary["avg"] = round(sum(values) / len(values), 2)
    return summary


def classify_log_type(rows):
    summary = {"row_count": len(rows)}
    for key, _label in PID_COLUMNS:
        summary[key] = summarize_pid(rows, key)
    return main_cli.classify_live_log_type(summary)


def build_summary(path):
    rows, fieldnames = load_live_csv(path)
    summary = {
        "path": path,
        "row_count": len(rows),
        "fieldnames": fieldnames,
    }
    for key, _label in PID_COLUMNS:
        summary[key] = summarize_pid(rows, key)
    summary["log_type"] = main_cli.classify_live_log_type(summary)
    return summary


def format_value(value):
    if value is None:
        return "N/A"
    if float(value).is_integer():
        return f"{value:.1f}"
    return f"{value:.2f}"


def format_diff(value_a, value_b):
    if value_a is None or value_b is None:
        return "N/A"
    diff = round(value_b - value_a, 2)
    return f"{diff:+.2f}"


def build_compare_comments(summary_a, summary_b):
    comments = []

    def add_comment(text):
        if text and text not in comments:
            comments.append(text)

    ect_a = summary_a.get("ect", {}).get("avg")
    ect_b = summary_b.get("ect", {}).get("avg")
    if ect_a is not None and ect_b is not None and abs(ect_b - ect_a) >= 5:
        add_comment("参考: ECT平均に差があり、暖機条件の違いが含まれる可能性があります")

    speed_max_a = summary_a.get("speed", {}).get("max")
    speed_max_b = summary_b.get("speed", {}).get("max")
    if speed_max_a is not None and speed_max_b is not None and abs(speed_max_b - speed_max_a) >= 10:
        add_comment("参考: speed最大値の差が大きく、走行条件が異なる可能性があります")

    rpm_a = summary_a.get("rpm", {}).get("avg")
    rpm_b = summary_b.get("rpm", {}).get("avg")
    if rpm_a is not None and rpm_b is not None and abs(rpm_b - rpm_a) >= 80:
        add_comment("参考: RPM平均に差があり、アイドル条件や操作条件の違いも参考確認してください")

    maf_a = summary_a.get("maf", {}).get("avg")
    maf_b = summary_b.get("maf", {}).get("avg")
    if maf_a is not None and maf_b is not None and abs(maf_b - maf_a) >= 1.5:
        add_comment("参考: MAF平均に差があります。吸気量差や測定条件差も含めて確認してください")

    for key, label in PID_COLUMNS:
        missing_a = summary_a.get(key, {}).get("missing", 0)
        missing_b = summary_b.get(key, {}).get("missing", 0)
        row_count_a = max(summary_a.get("row_count", 0), 1)
        row_count_b = max(summary_b.get("row_count", 0), 1)
        if missing_a >= row_count_a // 2 and missing_b == 0 and summary_b.get(key, {}).get("count", 0):
            add_comment(f"参考: {label} は B のほうが取得安定性が良い可能性があります")
            break
        if missing_b >= row_count_b // 2 and missing_a == 0 and summary_a.get(key, {}).get("count", 0):
            add_comment(f"参考: {label} は A のほうが取得安定性が良い可能性があります")
            break

    if summary_a.get("log_type", {}).get("label") != summary_b.get("log_type", {}).get("label"):
        add_comment("参考: 記録タイプが異なるため、単純比較では条件差も考慮してください")

    return comments[:4]


def print_pid_compare(summary_a, summary_b):
    print("[PID比較]")
    for key, label in PID_COLUMNS:
        info_a = summary_a.get(key, {})
        info_b = summary_b.get(key, {})
        print(f"{label}:")
        print(
            f"  A avg={format_value(info_a.get('avg'))} min={format_value(info_a.get('min'))} max={format_value(info_a.get('max'))}"
        )
        print(
            f"  B avg={format_value(info_b.get('avg'))} min={format_value(info_b.get('min'))} max={format_value(info_b.get('max'))}"
        )
        print(f"  差分(B-A): {format_diff(info_a.get('avg'), info_b.get('avg'))}")
        print("")


def print_missing_compare(summary_a, summary_b):
    print("[未取得比較]")
    for key, label in PID_COLUMNS:
        print(f"{label}:")
        print(f"  A 空欄 {summary_a.get(key, {}).get('missing', 0)}/{summary_a.get('row_count', 0)}")
        print(f"  B 空欄 {summary_b.get(key, {}).get('missing', 0)}/{summary_b.get('row_count', 0)}")


def print_compare_report(path_a, path_b, summary_a, summary_b):
    print("==================================================")
    print("CSVログ比較")
    print(f"A: {path_a}")
    print(f"B: {path_b}")
    print("==================================================")
    print("")
    print("[基本情報]")
    print(f"A 行数: {summary_a['row_count']}")
    print(f"B 行数: {summary_b['row_count']}")
    print("")
    print("[記録タイプ]")
    print(f"A: {summary_a.get('log_type', {}).get('label', '判定保留')}")
    print(f"B: {summary_b.get('log_type', {}).get('label', '判定保留')}")
    print("")
    print_pid_compare(summary_a, summary_b)
    comments = build_compare_comments(summary_a, summary_b)
    print("[比較コメント]")
    if not comments:
        print("- 大きな差分コメントはありません。条件差も含めて参考確認してください")
    else:
        for line in comments:
            print(f"- {line}")
    print("")
    print_missing_compare(summary_a, summary_b)


def main():
    parser = argparse.ArgumentParser(
        description="保存済みの live CSV 2本を比較し、主要PIDの差をテキストで表示します。"
    )
    parser.add_argument("csv_a", nargs="?", help="比較元AのCSV")
    parser.add_argument("csv_b", nargs="?", help="比較先BのCSV")
    args = parser.parse_args()

    path_a = args.csv_a
    path_b = args.csv_b
    if not path_a or not path_b:
        path_a, path_b = choose_latest_two_live_csv()
        if not path_a or not path_b:
            print("比較対象のライブCSVが2件見つかりません。CSVを2本指定するか、logs に live_*.csv を2件以上用意してください。")
            return 1

    if not os.path.exists(path_a):
        print(f"A のCSVが見つかりません: {path_a}")
        return 1
    if not os.path.exists(path_b):
        print(f"B のCSVが見つかりません: {path_b}")
        return 1

    try:
        summary_a = build_summary(path_a)
        summary_b = build_summary(path_b)
    except Exception as e:
        print(f"CSV比較に失敗しました: {e}")
        return 1

    print_compare_report(path_a, path_b, summary_a, summary_b)
    return 0


if __name__ == "__main__":
    sys.exit(main())
