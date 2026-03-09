# main.py
# 車両診断支援ツールの実行ファイル

from datetime import datetime

from diagnosis import run_multi_diagnosis
from report import format_report, save_report_text
from utils import normalize_maker_name, normalize_symptom_name, normalize_text, split_dtc_codes


def ask_input(prompt_text: str) -> str:
    """入力を受け取り、前後の空白を除去して返す"""
    return input(prompt_text).strip()


def main() -> None:
    print("=== 車両診断支援ツール ===")
    print("DTCコードや症状から、原因候補と確認ポイントを表示します。")
    print()

    maker = ask_input("メーカー名を入力してください（例: トヨタ）: ")
    model = ask_input("車種名を入力してください（例: セルシオ）: ")
    year = ask_input("年式を入力してください（例: 1997）: ")
    mileage = ask_input("走行距離を入力してください（例: 220000km）: ")
    dtc_input = ask_input("DTCコードを入力してください（例: P0171,P0300）: ")
    symptom = ask_input("症状を入力してください（例: 燃費悪化）: ")

    # 軽い前処理
    maker = normalize_text(maker)
    maker = normalize_maker_name(maker)
    model = normalize_text(model)
    year = normalize_text(year)
    mileage = normalize_text(mileage)
    dtc_codes = split_dtc_codes(dtc_input)
    symptom = normalize_text(symptom)
    symptom = normalize_symptom_name(symptom)
    diagnosis_datetime = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    result = run_multi_diagnosis(
        maker=maker,
        model=model,
        year=year,
        mileage=mileage,
        dtc_codes=dtc_codes,
        symptom=symptom,
    )
    result["diagnosis_datetime"] = diagnosis_datetime

    report_text = format_report(result)

    print()
    print(report_text)

    saved_path = save_report_text(report_text, result)
    print()
    print(f"診断結果を保存しました: {saved_path}")


if __name__ == "__main__":
    main()
