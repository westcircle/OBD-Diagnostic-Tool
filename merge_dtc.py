import json

BASE_FILE = "dtc_database.json"            # 既存のデータ
AUTO_FILE = "dtc_auto_generated.json"      # 自動生成データ
DESC_FILE = "dtc_description.json"         # 手作業の高品質データ
OUTPUT_FILE = "dtc_merged.json"            # 統合後の出力

def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)

def merge_dtc():
    base = load_json(BASE_FILE)
    auto = load_json(AUTO_FILE)
    desc = load_json(DESC_FILE)

    merged = base.copy()

    # ① 手作業の高品質データを最優先で統合
    for code, text in desc.items():
        if code not in merged:
            merged[code] = {}
        merged[code]["generic"] = text  # 最優先で上書き

    # ② 自動生成データで空欄を補完
    for code, info in auto.items():
        if code not in merged:
            merged[code] = info
        else:
            if "generic" not in merged[code]:
                merged[code]["generic"] = info["generic"]

            for maker in ["toyota", "nissan"]:
                if maker not in merged[code]:
                    merged[code][maker] = info[maker]

    save_json(OUTPUT_FILE, merged)
    print(f"統合完了 → {OUTPUT_FILE} に保存しました。")

if __name__ == "__main__":
    merge_dtc()
