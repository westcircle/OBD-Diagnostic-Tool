# report.py
# 診断結果を整形・保存する

from datetime import datetime
from pathlib import Path


def _sanitize_filename_part(text: str, fallback: str, max_length: int = 20) -> str:
    """ファイル名に使えるように文字列を安全化する"""
    normalized = str(text).strip() if text is not None else ""
    if not normalized or normalized in ["未入力", "不明"]:
        return fallback

    invalid_chars = '\\/:*?"<>|'
    safe_chars = []
    for ch in normalized:
        if ch in invalid_chars:
            continue
        if ch.isspace():
            safe_chars.append("_")
        else:
            safe_chars.append(ch)

    safe_text = "".join(safe_chars).strip("._")
    while "__" in safe_text:
        safe_text = safe_text.replace("__", "_")

    if not safe_text:
        return fallback
    return safe_text[:max_length]


def _extract_first_dtc(result: dict) -> str:
    """結果辞書から先頭DTCを取り出す"""
    dtc_codes = result.get("dtc_codes", [])
    if dtc_codes:
        return str(dtc_codes[0])

    dtc_code = str(result.get("dtc_code", "")).strip()
    if dtc_code and dtc_code != "未入力":
        return dtc_code

    diagnoses = result.get("diagnoses", [])
    if diagnoses:
        first_code = str(diagnoses[0].get("dtc_code", "")).strip()
        if first_code and first_code != "未入力":
            return first_code

    return "NO_DTC"


def _build_report_filename(result: dict) -> str:
    """保存用のファイル名を作る"""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    maker = _sanitize_filename_part(result.get("maker", ""), "UNKNOWN_MAKER", max_length=20)
    model = _sanitize_filename_part(result.get("model", ""), "UNKNOWN_MODEL", max_length=20)
    dtc = _sanitize_filename_part(_extract_first_dtc(result), "NO_DTC", max_length=16)

    return f"report_{timestamp}_{maker}_{model}_{dtc}.txt"


def _get_dtc_list_text(result: dict) -> str:
    """結果辞書から表示用DTC一覧テキストを作る"""
    dtc_codes = result.get("dtc_codes", [])
    if dtc_codes:
        return ", ".join(dtc_codes)

    dtc_code = str(result.get("dtc_code", "")).strip()
    if dtc_code:
        return dtc_code

    diagnoses = result.get("diagnoses", [])
    if diagnoses:
        first_code = str(diagnoses[0].get("dtc_code", "")).strip()
        return first_code if first_code else "未入力"

    return "未入力"


def _build_input_summary(result: dict) -> str:
    """保存本文の先頭に付ける入力サマリーを作る"""
    lines = []
    lines.append("入力サマリー:")
    lines.append(f"- メーカー: {result.get('maker', '未入力')}")
    lines.append(f"- 車種: {result.get('model', '未入力')}")
    lines.append(f"- 年式: {result.get('year', '未入力')}")
    lines.append(f"- 走行距離: {result.get('mileage', '未入力')}")
    lines.append(f"- DTC: {_get_dtc_list_text(result)}")
    lines.append(f"- 症状: {result.get('symptom', '未入力')}")
    return "\n".join(lines)


def _build_disclaimer_text() -> str:
    """保存本文の末尾に付ける簡単な免責文を作る"""
    lines = []
    lines.append("-" * 40)
    lines.append("【ご案内】")
    lines.append("この結果は診断支援用の参考情報です。")
    lines.append("最終判断には実車確認や追加点検が必要です。")
    lines.append("修理や部品交換は必要に応じて専門家への相談もご検討ください。")
    return "\n".join(lines)


def _resolve_unique_path(directory: Path, filename: str) -> Path:
    """重複しない保存先パスを返す。重複時は _001, _002... を付与する"""
    base_path = directory / filename
    if not base_path.exists():
        return base_path

    stem = base_path.stem
    suffix = base_path.suffix

    counter = 1
    while True:
        candidate = directory / f"{stem}_{counter:03d}{suffix}"
        if not candidate.exists():
            return candidate
        counter += 1


def _format_list(title: str, items: list) -> str:
    lines = [f"{title}:"]
    if not items:
        lines.append("- 情報なし")
        return "\n".join(lines)

    for item in items:
        lines.append(f"- {item}")
    return "\n".join(lines)


def _format_single_diagnosis_block(result: dict) -> str:
    lines = []
    lines.append(f"DTC: {result['dtc_code']}")
    lines.append("コード説明")
    lines.append(result["dtc_title"])
    lines.append("")
    lines.append(_format_list("原因候補", result["causes"]))
    lines.append("")
    lines.append(_format_list("確認手順", result["checks"]))
    lines.append("")
    lines.append(f"緊急度: {result['level']}")
    lines.append("")
    lines.append(_format_list("注意点", result["notes"]))
    return "\n".join(lines)


def format_report(result: dict) -> str:
    """診断結果を表示用の文字列にする"""
    # 既存の単一結果フォーマットとの互換も維持
    if "diagnoses" not in result:
        lines = []
        lines.append("=== 診断結果 ===")
        lines.append(f"診断日時: {result.get('diagnosis_datetime', '不明')}")
        lines.append(f"メーカー: {result['maker']}")
        lines.append(f"車種: {result['model']}")
        lines.append(f"年式: {result['year']}")
        lines.append(f"走行距離: {result['mileage']}")
        lines.append(f"入力DTC一覧: {result['dtc_code']}")
        lines.append(f"症状: {result['symptom']}")
        lines.append(f"総合緊急度: {result.get('overall_level', '不明')}")
        lines.append("")
        lines.append(_format_single_diagnosis_block(result))
        return "\n".join(lines)

    dtc_list_text = _get_dtc_list_text(result)

    lines = []
    lines.append("=== 診断結果 ===")
    lines.append(f"診断日時: {result.get('diagnosis_datetime', '不明')}")
    lines.append(f"メーカー: {result['maker']}")
    lines.append(f"車種: {result['model']}")
    lines.append(f"年式: {result['year']}")
    lines.append(f"走行距離: {result['mileage']}")
    lines.append(f"入力DTC一覧: {dtc_list_text}")
    lines.append(f"症状: {result['symptom']}")
    lines.append(f"総合緊急度: {result.get('overall_level', '不明')}")

    diagnoses = result.get("diagnoses", [])
    for diagnosis in diagnoses:
        lines.append("")
        lines.append("-" * 40)
        lines.append(_format_single_diagnosis_block(diagnosis))

    return "\n".join(lines)


def save_report_text(report_text: str, result: dict, project_root: Path | str = ".") -> str:
    """レポート文字列を reports フォルダ配下の txt に保存する"""
    root_path = Path(project_root)
    reports_dir = root_path / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)

    filename = _build_report_filename(result)
    file_path = _resolve_unique_path(reports_dir, filename)
    summary_text = _build_input_summary(result)
    disclaimer_text = _build_disclaimer_text()
    save_text = f"{summary_text}\n\n{report_text}\n\n{disclaimer_text}"

    with file_path.open("w", encoding="utf-8") as f:
        f.write(save_text)

    return str(file_path)
