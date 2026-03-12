# dtc_data.py
# DTCコードごとの基本データ

DTC_DB = {
    "P0171": {
        "dtc_title": "混合気が薄い（バンク1）",
        "causes": [
            "吸気系のエア漏れ",
            "エアフロセンサー汚れ",
            "燃料圧力低下",
            "インジェクターの噴射不足",
            "O2センサー/空燃比センサー異常",
        ],
        "checks": [
            "吸気ホースやガスケットのエア吸い確認",
            "エアフロセンサーの汚れ確認",
            "燃圧確認",
            "O2センサー/空燃比センサーの状態確認",
            "インジェクターの作動確認",
        ],
        "level": "中",
        "notes": ["放置すると燃費悪化や加速不良につながることがあります"],
    },
    "P0300": {
        "dtc_title": "ランダム/複数気筒ミスファイア",
        "causes": [
            "点火プラグ劣化",
            "イグニッションコイル不良",
            "燃料供給不良",
            "圧縮不良",
            "吸気系トラブル",
        ],
        "checks": [
            "点火プラグの摩耗確認",
            "イグニッションコイル確認",
            "インジェクター作動確認",
            "圧縮測定",
            "吸気漏れ確認",
        ],
        "level": "高",
        "notes": ["症状が強い場合は走行を控えた方がよい場合があります"],
    },
    "P0420": {
        "dtc_title": "触媒効率低下（バンク1）",
        "causes": [
            "触媒の劣化",
            "O2センサー異常",
            "空燃比不良",
            "排気漏れ",
        ],
        "checks": [
            "触媒の状態確認",
            "前後O2センサーの値確認",
            "排気漏れ確認",
            "燃焼状態確認",
        ],
        "level": "中",
        "notes": [
            "他の燃調異常コードがある場合は先にそちらを確認した方がよいことがあります"
        ],
    },
    "P0500": {
        "dtc_title": "車速センサー異常",
        "causes": [
            "車速センサー不良",
            "配線不良",
            "コネクタ接触不良",
            "ECU側の受信異常",
        ],
        "checks": [
            "車速センサー点検",
            "配線導通確認",
            "コネクタ点検",
            "実測値とメーター表示の差を確認",
        ],
        "level": "中",
        "notes": ["車速信号はAT制御やメーター系にも影響することがあります"],
    },
}

import json
from pathlib import Path


def load_dtc_failure_map(path: str | Path | None = None) -> dict:
    file_path = Path(path) if path else Path(__file__).resolve().parent / "dtc_failure_map.json"
    try:
        with file_path.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _normalize_failure_candidate_item(candidate) -> dict | None:
    if isinstance(candidate, str):
        name = candidate.strip()
        if not name:
            return None
        return {"name": name, "check": ""}

    if not isinstance(candidate, dict):
        return None

    name = str(candidate.get("name", "")).strip()
    if not name:
        return None

    check = str(candidate.get("check", "")).strip()
    return {"name": name, "check": check}


def get_dtc_failure_candidate_items(
    code: str,
    limit: int = 3,
    failure_map: dict | None = None,
    path: str | Path | None = None,
) -> list[dict[str, str]]:
    normalized = str(code or "").strip().upper()
    if not normalized:
        return []

    source_map = failure_map if isinstance(failure_map, dict) else load_dtc_failure_map(path=path)
    item = source_map.get(normalized, {})
    if not isinstance(item, dict):
        return []

    candidates = item.get("candidates", [])
    if not isinstance(candidates, list):
        return []

    cleaned = []
    for candidate in candidates:
        normalized_item = _normalize_failure_candidate_item(candidate)
        if normalized_item:
            cleaned.append(normalized_item)

    return cleaned[: max(limit, 0)]


def get_dtc_failure_candidates(code: str, limit: int = 3, failure_map: dict | None = None, path: str | Path | None = None) -> list[str]:
    items = get_dtc_failure_candidate_items(code, limit=limit, failure_map=failure_map, path=path)
    return [item["name"] for item in items if item.get("name")]
