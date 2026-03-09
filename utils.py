# utils.py
# 共通処理

import unicodedata


MAKER_ALIASES = {
    "トヨタ": "トヨタ",
    "TOYOTA": "トヨタ",
    "日産": "日産",
    "ニッサン": "日産",
    "NISSAN": "日産",
    "ホンダ": "ホンダ",
    "HONDA": "ホンダ",
    "スズキ": "スズキ",
    "SUZUKI": "スズキ",
    "ダイハツ": "ダイハツ",
    "DAIHATSU": "ダイハツ",
}

SYMPTOM_NORMALIZE_RULES = [
    ("エンスト", ["エンスト", "エンストする", "止まる", "すぐ止まる", "停止する"]),
    (
        "アイドリング不安定",
        [
            "アイドリング不安定",
            "アイドリングが変",
            "回転が不安定",
            "停車中に回転がばらつく",
            "回転がばらつく",
        ],
    ),
    ("加速不良", ["加速不良", "加速しない", "加速が悪い", "伸びない", "もたつく"]),
    ("燃費悪化", ["燃費悪化", "燃費悪い", "燃費が悪い", "燃費落ちた", "燃費が落ちた"]),
]


def normalize_text(text: str) -> str:
    """None対策をしつつ文字列化して前後空白を除去"""
    if text is None:
        return ""
    return str(text).strip()


def unique_keep_order(items: list) -> list:
    """重複を除きつつ順序を維持"""
    seen = set()
    result = []

    for item in items:
        if item not in seen:
            seen.add(item)
            result.append(item)

    return result


def split_dtc_codes(dtc_text: str) -> list:
    """DTC入力文字列を分割し、正規化して重複除去したリストを返す"""
    normalized = normalize_text(dtc_text)
    if not normalized:
        return []

    # 全角カンマを半角カンマに吸収
    normalized = normalized.replace("，", ",")

    raw_codes = normalized.split(",")
    cleaned_codes = []

    for code in raw_codes:
        normalized_code = normalize_text(code).upper().replace(" ", "")
        if normalized_code:
            cleaned_codes.append(normalized_code)

    return unique_keep_order(cleaned_codes)


def normalize_maker_name(maker: str) -> str:
    """メーカー名の入力ゆれを吸収して標準表記へ正規化する"""
    normalized = normalize_text(maker)
    if not normalized:
        return ""

    # 全角半角の軽いゆれを吸収
    normalized = unicodedata.normalize("NFKC", normalized)

    # スペース混在を吸収して英字大文字化
    alias_key = normalized.replace(" ", "").upper()
    if alias_key in MAKER_ALIASES:
        return MAKER_ALIASES[alias_key]

    # 日本語表記の直接一致にも対応
    return MAKER_ALIASES.get(normalized, normalized)


def parse_year_to_western(year_text: str) -> int | None:
    """年式文字列を西暦4桁へ変換する。解釈できない場合は None を返す"""
    normalized = normalize_text(year_text)
    if not normalized:
        return None

    # 全角半角のゆれを吸収し、空白を除去
    normalized = unicodedata.normalize("NFKC", normalized)
    compact = normalized.replace(" ", "").replace("　", "")

    if compact.endswith("年"):
        compact = compact[:-1]

    # 西暦4桁の直接入力
    if compact.isdigit():
        western = int(compact)
        if 1000 <= western <= 9999:
            return western
        return None

    # 英字元号は大文字化して判定
    upper_text = compact.upper()

    # 平成: 平成1年 = 1989
    if compact.startswith("平成"):
        era_year_text = compact.replace("平成", "", 1)
        if era_year_text.isdigit():
            era_year = int(era_year_text)
            if era_year >= 1:
                return 1988 + era_year
        return None
    if upper_text.startswith("H"):
        era_year_text = upper_text[1:]
        if era_year_text.isdigit():
            era_year = int(era_year_text)
            if era_year >= 1:
                return 1988 + era_year
        return None

    # 令和: 令和1年 = 2019
    if compact.startswith("令和"):
        era_year_text = compact.replace("令和", "", 1)
        if era_year_text.isdigit():
            era_year = int(era_year_text)
            if era_year >= 1:
                return 2018 + era_year
        return None
    if upper_text.startswith("R"):
        era_year_text = upper_text[1:]
        if era_year_text.isdigit():
            era_year = int(era_year_text)
            if era_year >= 1:
                return 2018 + era_year
        return None

    return None


def normalize_symptom_name(symptom: str) -> str:
    """症状入力のゆれを吸収し、標準症状名へ正規化する"""
    normalized = normalize_text(symptom)
    if not normalized:
        return ""

    # 全角半角ゆれを吸収し、空白を取り除く
    normalized = unicodedata.normalize("NFKC", normalized)
    compact = normalized.replace(" ", "").replace("　", "")

    for standard_name, patterns in SYMPTOM_NORMALIZE_RULES:
        for pattern in patterns:
            pattern_compact = unicodedata.normalize("NFKC", pattern).replace(" ", "").replace("　", "")
            if pattern_compact and pattern_compact in compact:
                return standard_name

    return normalized
