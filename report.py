# report.py
# 診断結果を整形・保存する

import csv
from datetime import datetime
from pathlib import Path

from diagnostic_comments import annotate_failure_candidates
from dtc_data import get_dtc_failure_candidate_items


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


def _get_dtc_codes_list(result: dict) -> list[str]:
    dtc_codes = result.get("dtc_codes", [])
    if isinstance(dtc_codes, list):
        return [str(code).strip() for code in dtc_codes if str(code).strip()]

    dtc_code = str(result.get("dtc_code", "")).strip()
    if dtc_code and dtc_code != "未入力":
        return [dtc_code]

    diagnoses = result.get("diagnoses", [])
    codes = []
    for diagnosis in diagnoses:
        code = str(diagnosis.get("dtc_code", "")).strip()
        if code and code != "未入力" and code not in codes:
            codes.append(code)
    return codes


def _build_diagnosis_history_row(result: dict) -> dict[str, str]:
    dtc_codes = _get_dtc_codes_list(result)
    overall_notes = result.get("overall_reference_notes", [])
    if not isinstance(overall_notes, list):
        overall_notes = [str(overall_notes)] if overall_notes else []

    return {
        "diagnosis_datetime": str(result.get("diagnosis_datetime", "") or datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
        "vin": str(result.get("vin", "") or ""),
        "maker": str(result.get("maker", "") or ""),
        "model": str(result.get("model", "") or ""),
        "year": str(result.get("year", "") or ""),
        "mileage": str(result.get("mileage", "") or ""),
        "symptom": str(result.get("symptom", "") or ""),
        "dtc_count": str(len(dtc_codes)),
        "dtc_codes": "|".join(dtc_codes),
        "overall_level": str(result.get("overall_level", "") or ""),
        "overall_reference_notes": " / ".join(str(note) for note in overall_notes[:3] if str(note).strip()),
    }


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


def _format_failure_candidates(dtc_code: str, dtc_pid_hints: list[str] | None = None) -> str:
    candidate_items = get_dtc_failure_candidate_items(dtc_code)
    if not candidate_items:
        return ""

    lines = ["[故障候補]", "- 参考候補です。優先確認の当たりとして見てください"]
    annotated_lines = annotate_failure_candidates(dtc_code, candidate_items[:3], dtc_pid_hints=dtc_pid_hints)
    for item, line in zip(candidate_items[:3], annotated_lines):
        lines.append(f"- {line}")
        check = str(item.get("check", "")).strip()
        if check:
            lines.append(f"  確認ポイント: {check}")
    return "\n".join(lines)


def _format_single_diagnosis_block(result: dict, dtc_pid_hints: list[str] | None = None) -> str:
    lines = []
    lines.append(f"DTC: {result['dtc_code']}")
    lines.append("コード説明")
    lines.append(result["dtc_title"])
    diagnosis_hints = result.get("dtc_pid_hints")
    if diagnosis_hints is None:
        diagnosis_hints = dtc_pid_hints
    failure_candidates_text = _format_failure_candidates(result["dtc_code"], dtc_pid_hints=diagnosis_hints)
    if failure_candidates_text:
        lines.append("")
        lines.append(failure_candidates_text)
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
    overall_notes = result.get("overall_reference_notes", [])
    root_dtc_pid_hints = result.get("dtc_pid_hints")

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
        lines.append(_format_single_diagnosis_block(result, dtc_pid_hints=root_dtc_pid_hints))
        if overall_notes:
            lines.append("")
            lines.append("[総合参考メモ]")
            for note in overall_notes[:3]:
                lines.append(f"- {note}")
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
        diagnosis_hints = diagnosis.get("dtc_pid_hints")
        if diagnosis_hints is None and len(diagnoses) == 1:
            diagnosis_hints = root_dtc_pid_hints
        lines.append(_format_single_diagnosis_block(diagnosis, dtc_pid_hints=diagnosis_hints))

    if overall_notes:
        lines.append("")
        lines.append("[総合参考メモ]")
        for note in overall_notes[:3]:
            lines.append(f"- {note}")

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


def append_diagnosis_history_csv(result: dict, project_root: Path | str = ".") -> str | None:
    """診断結果を logs/diagnosis_history.csv に追記する。失敗時は None を返す。"""
    try:
        root_path = Path(project_root)
        logs_dir = root_path / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)
        file_path = logs_dir / "diagnosis_history.csv"
        row = _build_diagnosis_history_row(result)
        fieldnames = list(row.keys())
        file_exists = file_path.exists()

        with file_path.open("a", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            if not file_exists:
                writer.writeheader()
            writer.writerow(row)

        return str(file_path)
    except Exception:
        return None
