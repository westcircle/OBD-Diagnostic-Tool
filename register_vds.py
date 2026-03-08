import json
import os

PID_FILE = "pid_normal.json"

# JSON 読み込み
def load_json(filename):
    if not os.path.exists(filename):
        return {}
    with open(filename, "r", encoding="utf-8") as f:
        return json.load(f)

# JSON 保存
def save_json(filename, data):
    with open(filename, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)

def main():
    print("=== 正常値辞書 自動登録ツール ===")

    engine = input("エンジン型式を入力してください： ").strip()
    if not engine:
        print("エンジン型式が入力されていません。")
        return

    print("\n--- 正常値を入力してください ---")

    try:
        rpm_low = float(input("RPM 下限： "))
        rpm_high = float(input("RPM 上限： "))
        ect_low = float(input("ECT 下限： "))
        ect_high = float(input("ECT 上限： "))
        maf_low = float(input("MAF 下限： "))
        maf_high = float(input("MAF 上限： "))
    except:
        print("数値として認識できませんでした。")
        return

    # JSON 読み込み
    pid_map = load_json(PID_FILE)

    # 既存データ確認
    if engine in pid_map:
        print(f"\n既に登録されています： {engine}")
        print(pid_map[engine])
        overwrite = input("上書きしますか？ (y/n)： ").lower()
        if overwrite != "y":
            print("キャンセルしました。")
            return

    # 登録データ作成
    pid_map[engine] = {
        "RPM": [rpm_low, rpm_high],
        "ECT": [ect_low, ect_high],
        "MAF": [maf_low, maf_high]
    }

    # 保存
    save_json(PID_FILE, pid_map)

    print(f"\n登録完了： {engine}")
    print(pid_map[engine])

if __name__ == "__main__":
    main()
