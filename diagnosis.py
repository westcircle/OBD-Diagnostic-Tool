# diagnosis.py
# DTCコードと症状をもとに診断結果を組み立てる

from copy import deepcopy

from dtc_data import DTC_DB
from maker_notes import MAKER_NOTES
from symptom_rules import SYMPTOM_RULES
from utils import parse_year_to_western, unique_keep_order


def _calculate_overall_level(levels: list[str]) -> str:
    """緊急度リストから総合緊急度を返す（高 > 中 > 低 > 不明）"""
    priority = ["高", "中", "低", "不明"]
    normalized_levels = [level if level in priority else "不明" for level in levels]

    for level in priority:
        if level in normalized_levels:
            return level
    return "不明"


def _safe_parse_year(year: str) -> int | None:
    """年式文字列を安全に整数化する。失敗時は None を返す"""
    return parse_year_to_western(year)


def _get_unknown_dtc_result(dtc_code: str) -> dict:
    """未登録DTC用の診断結果を返す"""
    return {
        "dtc_title": "未登録のDTCコード",
        "causes": [
            "DTCデータベースに未登録です",
            "メーカー独自コードの可能性があります",
            "コード読み取りミスの可能性があります",
        ],
        "checks": [
            "コードが正しいか再確認してください",
            "メーカー別診断情報を確認してください",
            "再スキャンして同じコードが出るか確認してください",
        ],
        "level": "不明",
        "notes": ["汎用コードではない場合、車種専用情報が必要になることがあります"],
    }


def _apply_symptom_rule(base_result: dict, symptom: str) -> dict:
    """症状ルールを診断結果へ反映する"""
    if not symptom:
        return base_result

    symptom_rule = SYMPTOM_RULES.get(symptom)
    if not symptom_rule:
        return base_result

    extra_causes = symptom_rule.get("extra_causes", [])
    base_result["causes"].extend(extra_causes)

    extra_checks = symptom_rule.get("extra_checks", [])
    base_result["checks"].extend(extra_checks)

    note = symptom_rule.get("note")
    if note:
        base_result["notes"].append(note)

    base_result["causes"] = unique_keep_order(base_result["causes"])
    base_result["checks"] = unique_keep_order(base_result["checks"])
    base_result["notes"] = unique_keep_order(base_result["notes"])

    return base_result


def _apply_maker_notes(base_result: dict, maker: str, year: str) -> dict:
    """メーカー別メモを診断結果へ反映する"""
    maker_note_data = MAKER_NOTES.get(maker)
    if not maker_note_data:
        return base_result

    notes_to_add = []
    notes_to_add.extend(maker_note_data.get("common", []))

    parsed_year = _safe_parse_year(year)
    if parsed_year is not None and parsed_year <= 2000:
        notes_to_add.extend(maker_note_data.get("older", []))

    if not notes_to_add:
        return base_result

    base_result["notes"].extend(notes_to_add)
    base_result["notes"] = unique_keep_order(base_result["notes"])
    return base_result


def run_diagnosis(
    maker: str,
    model: str,
    year: str,
    mileage: str,
    dtc_code: str,
    symptom: str,
) -> dict:
    """単一DTCの診断結果を返す"""
    if dtc_code in DTC_DB:
        base = deepcopy(DTC_DB[dtc_code])
    else:
        base = _get_unknown_dtc_result(dtc_code)

    if "notes" not in base:
        base["notes"] = []

    base = _apply_symptom_rule(base, symptom)
    base = _apply_maker_notes(base, maker, year)

    result = {
        "maker": maker if maker else "未入力",
        "model": model if model else "未入力",
        "year": year if year else "未入力",
        "mileage": mileage if mileage else "未入力",
        "dtc_code": dtc_code if dtc_code else "未入力",
        "symptom": symptom if symptom else "未入力",
        "dtc_title": base.get("dtc_title", "不明"),
        "causes": unique_keep_order(base.get("causes", [])),
        "checks": unique_keep_order(base.get("checks", [])),
        "level": base.get("level", "不明"),
        "overall_level": base.get("level", "不明"),
        "notes": unique_keep_order(base.get("notes", [])),
    }

    if not dtc_code:
        result["dtc_code"] = "未入力"
        result["dtc_title"] = "DTCコード未入力"
        result["notes"].append("DTCコードがないため、症状ベースの参考診断です")

    return result


def run_multi_diagnosis(
    maker: str,
    model: str,
    year: str,
    mileage: str,
    dtc_codes: list,
    symptom: str,
) -> dict:
    """複数DTC入力を順番に診断し、レポート用の結果にまとめる"""
    normalized_codes = unique_keep_order([code for code in dtc_codes if code])

    diagnoses = []
    if not normalized_codes:
        diagnoses.append(
            run_diagnosis(
                maker=maker,
                model=model,
                year=year,
                mileage=mileage,
                dtc_code="",
                symptom=symptom,
            )
        )
    else:
        for code in normalized_codes:
            diagnoses.append(
                run_diagnosis(
                    maker=maker,
                    model=model,
                    year=year,
                    mileage=mileage,
                    dtc_code=code,
                    symptom=symptom,
                )
            )

    return {
        "maker": maker if maker else "未入力",
        "model": model if model else "未入力",
        "year": year if year else "未入力",
        "mileage": mileage if mileage else "未入力",
        "symptom": symptom if symptom else "未入力",
        "dtc_codes": normalized_codes,
        "diagnoses": diagnoses,
        "overall_level": _calculate_overall_level(
            [diagnosis.get("level", "不明") for diagnosis in diagnoses]
        ),
    }
