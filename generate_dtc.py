import json

# 出力ファイル名
OUTPUT_FILE = "dtc_auto_generated.json"

# 自動生成ルール（パターンごとに説明を割り当て）
def generate_description(code_num):
    # 0000〜0999：汎用パワートレイン
    if 0 <= code_num <= 99:
        return "パワートレイン系の一般的な異常（詳細不明）"

    # 0100〜0199：吸気・MAF/MAP
    if 100 <= code_num <= 199:
        return "吸気系センサー（MAF/MAP）関連の異常"

    # 0200〜0299：燃料系
    if 200 <= code_num <= 299:
        return "燃料系統の異常（インジェクタ・燃圧など）"

    # 0300〜0399：ミスファイア
    if 300 <= code_num <= 399:
        return "ミスファイア検出（点火系統の異常）"

    # 0400〜0499：排気・EVAP
    if 400 <= code_num <= 499:
        return "排気系統またはEVAP系統の異常"

    # 0500〜0599：アイドル・速度制御
    if 500 <= code_num <= 599:
        return "アイドル制御または車速センサーの異常"

    # 0600〜0699：ECM/PCM 内部
    if 600 <= code_num <= 699:
        return "ECM/PCM 内部回路の異常"

    # 0700〜0799：AT/ミッション
    if 700 <= code_num <= 799:
        return "AT（オートマチックトランスミッション）系統の異常"

    # 0800〜0899：補機類
    if 800 <= code_num <= 899:
        return "補機類（電装・冷却・充電系）の異常"

    # 0900〜0999：その他
    if 900 <= code_num <= 999:
        return "パワートレイン系の異常（詳細不明）"

    # 1000〜3999：メーカー固有
    if 1000 <= code_num <= 3999:
        return "メーカー固有のパワートレイン異常（詳細不明）"

    # その他
    return "パワートレイン系の異常（詳細不明）"


# 自動生成本体
def generate_dtc_database():
    dtc_data = {}

    # P0000〜P3999 を生成
    for num in range(0, 4000):
        code = f"P{num:04d}"
        desc = generate_description(num)

        dtc_data[code] = {
            "generic": desc,
            "toyota": f"トヨタ固有の異常（{code}）",
            "nissan": f"日産固有の異常（{code}）"
        }

    return dtc_data


# JSON 出力
if __name__ == "__main__":
    data = generate_dtc_database()

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)

    print(f"{OUTPUT_FILE} に DTC データベースを生成しました。")
