import argparse
import csv
import glob
import os
import sys


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_DIR = os.path.join(BASE_DIR, "logs")
PLOT_COLUMNS = [
    ("rpm", "RPM"),
    ("ect", "ECT"),
    ("maf", "MAF"),
    ("speed", "SPEED"),
    ("iat", "IAT"),
    ("thr", "THR"),
]


def choose_latest_live_csv(log_dir=LOG_DIR):
    files = sorted(glob.glob(os.path.join(log_dir, "live_*.csv")))
    return files[-1] if files else None


def parse_float(value):
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return float(text)
    except Exception:
        return None


def load_live_csv_rows(csv_path):
    with open(csv_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        return list(reader), reader.fieldnames or []


def build_plot_series(rows, key):
    x_values = []
    y_values = []
    for index, row in enumerate(rows, start=1):
        value = parse_float(row.get(key))
        if value is None:
            continue
        x_values.append(index)
        y_values.append(value)
    return x_values, y_values


def build_output_path(csv_path, output_path=None):
    if output_path:
        return output_path
    stem = os.path.splitext(os.path.basename(csv_path))[0]
    return os.path.join(LOG_DIR, f"{stem}_plot.png")


def plot_live_csv(csv_path, output_path=None):
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except Exception:
        print("matplotlib が見つかりません。`pip install matplotlib` を実行してください。")
        return 1

    if not os.path.exists(csv_path):
        print(f"CSVが見つかりません: {csv_path}")
        return 1

    try:
        rows, fieldnames = load_live_csv_rows(csv_path)
    except Exception as e:
        print(f"CSVの読み込みに失敗しました: {e}")
        return 1

    if not rows:
        print("CSVにデータ行がありません。")
        return 1

    output_path = build_output_path(csv_path, output_path=output_path)
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    fig, axes = plt.subplots(len(PLOT_COLUMNS), 1, figsize=(12, 14), sharex=True)
    fig.suptitle(f"Live CSV Plot: {os.path.basename(csv_path)}", fontsize=14)

    plotted_count = 0
    for axis, (key, label) in zip(axes, PLOT_COLUMNS):
        if key not in fieldnames:
            axis.set_title(f"{label} (列なし)")
            axis.text(0.02, 0.5, "このCSVには列がありません", transform=axis.transAxes, fontsize=9)
            axis.grid(True, alpha=0.3)
            continue

        x_values, y_values = build_plot_series(rows, key)
        if not y_values:
            axis.set_title(f"{label} (有効データなし)")
            axis.text(0.02, 0.5, "空欄または数値以外のため描画なし", transform=axis.transAxes, fontsize=9)
            axis.grid(True, alpha=0.3)
            continue

        axis.plot(x_values, y_values, linewidth=1.2)
        axis.set_ylabel(label)
        axis.grid(True, alpha=0.3)
        plotted_count += 1

    axes[-1].set_xlabel("行番号")
    fig.tight_layout(rect=(0, 0, 1, 0.97))

    if plotted_count == 0:
        plt.close(fig)
        print("描画できるPIDデータがありませんでした。")
        return 1

    try:
        fig.savefig(output_path, dpi=140)
    except Exception as e:
        plt.close(fig)
        print(f"PNG保存に失敗しました: {e}")
        return 1

    plt.close(fig)
    print(f"入力CSV : {csv_path}")
    print(f"出力PNG : {output_path}")
    print(f"描画項目: {plotted_count}/{len(PLOT_COLUMNS)}")
    return 0


def main():
    parser = argparse.ArgumentParser(
        description="保存済みの live_*.csv から PID推移グラフをPNG保存します。例: python plot_live_csv.py logs\\live_2026-03-12_151103.csv"
    )
    parser.add_argument("csv_path", nargs="?", help="対象CSV。省略時は logs/live_*.csv の最新ファイルを使います。")
    parser.add_argument("-o", "--output", help="出力PNGパス。省略時は logs 配下に自動保存します。")
    args = parser.parse_args()

    csv_path = args.csv_path or choose_latest_live_csv()
    if not csv_path:
        print("ライブCSVが見つかりません。先に main_cli.py でライブCSVを保存してください。")
        return 1

    return plot_live_csv(csv_path, output_path=args.output)


if __name__ == "__main__":
    sys.exit(main())
