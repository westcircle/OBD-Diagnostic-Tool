import json
import os
import sys
import time
import csv
import re
import glob
from datetime import datetime
import msvcrt

import serial
from serial.tools import list_ports

from diagnostic_comments import (
    build_dtc_pid_hints,
    build_idle_hint,
    build_live_anomaly_comments,
    build_missing_column_summary,
    build_overall_reference_notes,
    build_warmup_hint,
    classify_live_log_type,
)
from diagnosis import run_multi_diagnosis
from report import append_diagnosis_history_csv, format_report, save_report_text

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_DIR = os.path.join(BASE_DIR, "logs")


def ensure_logs_dir():
    os.makedirs(LOG_DIR, exist_ok=True)


def create_session_log_path(started_at: datetime) -> str:
    session_id = started_at.strftime("%Y-%m-%d_%H%M%S")
    return os.path.join(LOG_DIR, f"session_{session_id}.log")


def append_session_log(log_path: str, line: str) -> None:
    try:
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


ensure_logs_dir()
SESSION_STARTED_AT = datetime.now()
LOG_FILE = create_session_log_path(SESSION_STARTED_AT)

DEFAULT_PORTS = ["COM13", "COM15", "COM3", "COM4", "COM5"]
BAUD_LIST = [115200, 38400, 9600]
LAST_CONNECT_REASON = "未実行"
DEBUG = True
CONSOLE_LOG_MUTED = False
MECHANIC_MODE = False


def add_log(level, message):
    if level == "DEBUG" and not DEBUG:
        return
    now = datetime.now().strftime("%H:%M:%S")
    line = f"[{now}] [{level}] {message}"
    if not CONSOLE_LOG_MUTED:
        print(line)
    append_session_log(LOG_FILE, line)


def load_json(path, fallback):
    full_path = os.path.join(BASE_DIR, path)
    try:
        with open(full_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        add_log("WARN", f"{path} の読み込みに失敗: {e}")
        return fallback


def append_history_csv(
    diagnosis_datetime,
    vin,
    maker,
    model,
    year,
    mileage,
    dtc_codes,
    symptom,
    overall_level,
    vehicle_check_memo="",
):
    history_file = os.path.join(LOG_DIR, "history.csv")
    file_exists = os.path.exists(history_file)

    with open(history_file, "a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        if not file_exists:
            writer.writerow(
                ["日時", "VIN", "メーカー", "車種", "年式", "走行距離", "DTC一覧", "症状", "総合緊急度", "実車確認メモ"]
            )
        writer.writerow(
            [
                diagnosis_datetime,
                vin or "",
                maker or "",
                model or "",
                year or "",
                mileage or "",
                ", ".join(dtc_codes) if dtc_codes else "",
                symptom or "",
                overall_level or "",
                vehicle_check_memo or "",
            ]
        )


def load_history_rows(history_path=None):
    history_file = history_path or os.path.join(LOG_DIR, "history.csv")
    if not os.path.exists(history_file):
        return []
    try:
        with open(history_file, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            return list(reader)
    except Exception as e:
        add_log("WARN", f"history.csv の読み込みに失敗: {e}")
        return []


def build_dtc_history_hints(dtc_list, history_path=None):
    codes = []
    seen = set()
    for code in dtc_list or []:
        normalized = (code or "").strip().upper()
        if normalized and normalized not in seen:
            seen.add(normalized)
            codes.append(normalized)

    if not codes:
        return []

    rows = load_history_rows(history_path=history_path)
    if not rows:
        return []

    stats = {code: {"count": 0, "last_seen": None, "recent": False} for code in codes}
    for row in rows:
        dtc_text = str(row.get("DTC一覧", "") or row.get("dtc_codes", "")).upper()
        if not dtc_text.strip():
            continue
        row_codes = {item.strip().upper() for item in dtc_text.split(",") if item.strip()}
        if not row_codes:
            continue
        row_date = str(row.get("日時", "") or row.get("date", "")).strip()
        for code in codes:
            if code in row_codes:
                stats[code]["count"] += 1
                stats[code]["last_seen"] = row_date or "日時不明"

    if rows:
        latest_text = str(rows[-1].get("DTC一覧", "") or rows[-1].get("dtc_codes", "")).upper()
        latest_codes = {item.strip().upper() for item in latest_text.split(",") if item.strip()}
        for code in codes:
            if code in latest_codes:
                stats[code]["recent"] = True

    matched_codes = [code for code in codes if stats[code]["count"] > 0]
    if not matched_codes:
        return []

    hints = []
    for code in matched_codes[:3]:
        count = stats[code]["count"]
        if count >= 2:
            hints.append(f"参考: {code} は過去 {count} 回記録があります")
        else:
            hints.append(f"参考: {code} は過去にも記録があります")
        if stats[code]["recent"]:
            hints.append(f"参考: 前回履歴にも {code} があります")
        elif stats[code]["last_seen"]:
            hints.append(f"参考: {code} の前回記録は {stats[code]['last_seen']} です")

    hints.append("参考: 再発傾向の確認に使えます。単独では故障断定できません")
    return hints[:5]


def create_live_csv_path(started_at: datetime) -> str:
    live_id = started_at.strftime("%Y-%m-%d_%H%M%S")
    return os.path.join(LOG_DIR, f"live_{live_id}.csv")


def init_live_csv(csv_path: str) -> bool:
    try:
        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["time", "rpm", "ect", "maf", "speed", "iat", "thr"])
        return True
    except Exception as e:
        add_log("WARN", f"ライブCSV初期化に失敗: {e}")
        return False


def append_live_csv_row(csv_path: str, row: list) -> bool:
    try:
        with open(csv_path, "a", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(row)
        return True
    except Exception as e:
        add_log("WARN", f"ライブCSV追記に失敗: {e}")
        return False


def choose_latest_live_csv(log_dir=LOG_DIR):
    files = sorted(glob.glob(os.path.join(log_dir, "live_*.csv")))
    return files[-1] if files else None


def parse_live_csv_float(value):
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return float(text)
    except Exception:
        return None


def summarize_live_csv_column(rows, key):
    values = []
    missing = 0
    for row in rows:
        value = parse_live_csv_float(row.get(key))
        if value is None:
            missing += 1
        else:
            values.append(value)
    summary = {"count": len(values), "missing": missing}
    if values:
        summary["min"] = min(values)
        summary["max"] = max(values)
        summary["avg"] = round(sum(values) / len(values), 2)
    return summary


def build_live_csv_comments(summary):
    comments = []
    rpm = summary.get("rpm", {})
    ect = summary.get("ect", {})
    maf = summary.get("maf", {})
    speed = summary.get("speed", {})
    missing_info = build_missing_column_summary(summary)
    log_type = summary.get("log_type") or classify_live_log_type(summary)

    comments.append(f"記録タイプ参考: {log_type['label']}")
    comments.append(log_type["hint"])
    comments.extend(build_idle_hint(summary))
    comments.extend(build_warmup_hint(summary))

    if rpm.get("count"):
        rpm_span = rpm["max"] - rpm["min"]
        if speed.get("max", 0) == 0 and rpm_span <= 150:
            comments.append("参考: アイドル時の回転変動は大きすぎないようです")
        elif speed.get("max", 0) == 0 and rpm_span > 300:
            comments.append("参考: アイドル時の回転ばらつき確認に使えます。変動はやや大きめです")

    if ect.get("count"):
        if ect["max"] < 70:
            comments.append("参考: 水温は暖機途中の可能性があります")
        elif ect["max"] <= 105:
            comments.append("参考: 水温の上がり方の確認に使えます")
        else:
            comments.append("参考: 水温は高めです。単独では断定できませんが冷却系要確認です")

    if maf.get("count"):
        if speed.get("max", 0) == 0 and maf.get("avg", 0) <= 10:
            comments.append("参考: MAFは停止時測定としては大きく外れていない可能性があります")
    elif maf.get("missing", 0):
        comments.append("参考: MAFは未取得データが多く、配線や対応状況の確認が必要です")

    if missing_info["many_missing"]:
        comments.append(f"参考: 未取得が多い項目があります ({', '.join(missing_info['many_missing'])})")
    elif any(summary.get(key, {}).get("missing", 0) for key in ("rpm", "ect", "maf", "speed", "iat", "thr")):
        comments.append("参考: 空欄が多い項目は未取得値として傾向確認に使ってください")

    comments.append("参考値です。単独では故障断定できません")
    return comments[:5]


def analyze_live_csv(csv_path):
    with open(csv_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    summary = {
        "path": csv_path,
        "row_count": len(rows),
        "rpm": summarize_live_csv_column(rows, "rpm"),
        "ect": summarize_live_csv_column(rows, "ect"),
        "maf": summarize_live_csv_column(rows, "maf"),
        "speed": summarize_live_csv_column(rows, "speed"),
        "iat": summarize_live_csv_column(rows, "iat"),
        "thr": summarize_live_csv_column(rows, "thr"),
    }
    summary["log_type"] = classify_live_log_type(summary)
    summary["anomalies"] = build_live_anomaly_comments(summary)
    summary["comments"] = build_live_csv_comments(summary)
    return summary


def print_live_csv_analysis(summary):
    def format_min_max_avg(name, column):
        if not column.get("count"):
            print(f"{name:<10}: データなし (空欄 {column.get('missing', 0)}件)")
            return
        print(
            f"{name:<10}: 平均 {column['avg']} / 最小 {column['min']} / 最大 {column['max']}"
            f" (空欄 {column.get('missing', 0)}件)"
        )

    print("")
    print("=== ライブCSV後解析 ===")
    print(f"対象ファイル: {os.path.basename(summary['path'])}")
    print(f"記録件数    : {summary['row_count']}")
    print(f"記録タイプ  : {summary.get('log_type', {}).get('label', '判定保留')}")
    print("")
    format_min_max_avg("RPM", summary["rpm"])
    format_min_max_avg("ECT", summary["ect"])
    format_min_max_avg("MAF", summary["maf"])
    format_min_max_avg("SPEED", summary["speed"])
    format_min_max_avg("IAT", summary["iat"])
    format_min_max_avg("THR", summary["thr"])
    print("")
    missing_info = build_missing_column_summary(summary)
    print("未取得サマリー:")
    for line in missing_info["details"]:
        print(f"- {line}")
    if missing_info["many_missing"]:
        print(f"- 未取得が多い項目: {', '.join(missing_info['many_missing'])}")
    else:
        print("- すべての主要項目で大きな未取得偏りはありません")
    print("- 一部PIDは車種やECUにより取得できないことがあります")
    print("")
    print("簡易コメント:")
    for line in summary.get("comments", []):
        print(f"- {line}")
    anomalies = summary.get("anomalies", [])
    if anomalies:
        print("")
        print("[ライブ異常検出]")
        for line in anomalies:
            print(f"- {line}")
    overall_notes = build_overall_reference_notes(
        anomaly_comments=anomalies,
        summary=summary,
    )
    if overall_notes:
        print("")
        print("[総合参考メモ]")
        for line in overall_notes:
            print(f"- {line}")


WMI_TO_MAKER = load_json("wmi_map.json", {})
VDS_TO_ENGINE = load_json("vds_map.json", {})
DTC_DB = load_json("dtc_database.json", {})
DTC_KNOWLEDGE = {
    "P0420": {
        "name": "触媒効率低下",
        "causes": ["触媒劣化の可能性", "O2センサー劣化の可能性", "排気漏れの可能性"],
        "checks": ["排気漏れ確認", "O2センサー確認", "触媒状態確認"],
        "priority": "中",
    },
    "P0171": {
        "name": "燃調リーン異常",
        "causes": ["吸気漏れの可能性", "MAF汚れの可能性", "燃圧低下の可能性"],
        "checks": ["吸気系の二次エア確認", "MAFセンサー確認", "燃料系確認"],
        "priority": "中",
    },
    "P0300": {
        "name": "ランダムミスファイア",
        "causes": ["点火系の可能性", "燃料系の可能性", "吸気系の可能性"],
        "checks": ["プラグとコイル確認", "燃料状態確認", "吸気漏れ確認"],
        "priority": "高",
    },
    "P0135": {
        "name": "O2センサヒーター異常",
        "causes": ["O2センサー本体の可能性", "ヒーター回路の可能性", "配線の可能性"],
        "checks": ["O2センサー配線確認", "ヒーター回路確認", "センサー本体確認"],
        "priority": "中",
    },
    "P0141": {
        "name": "後段O2センサヒーター異常",
        "causes": ["後段O2センサーの可能性", "ヒーター回路の可能性", "配線の可能性"],
        "checks": ["後段O2センサー確認", "ヒーター回路確認", "配線とカプラ確認"],
        "priority": "中",
    },
    "P0100": {
        "name": "吸入空気流量回路異常",
        "causes": ["MAFセンサー本体の可能性", "配線接触不良の可能性", "吸気系の影響"],
        "checks": ["MAF値確認", "配線とコネクタ確認", "吸気経路確認"],
        "priority": "中",
    },
    "P0101": {
        "name": "吸入空気流量範囲・性能異常",
        "causes": ["MAFセンサーずれの可能性", "吸気漏れの可能性", "エアクリーナ詰まりの可能性"],
        "checks": ["MAF値の変化確認", "吸気漏れ確認", "吸気経路確認"],
        "priority": "中",
    },
    "P0102": {
        "name": "吸入空気流量入力低異常",
        "causes": ["MAF信号低下の可能性", "配線断線の可能性", "コネクタ接触不良の可能性"],
        "checks": ["配線とカプラ確認", "MAF電源確認", "吸気系確認"],
        "priority": "中",
    },
    "P0103": {
        "name": "吸入空気流量入力高異常",
        "causes": ["MAF信号高すぎの可能性", "配線短絡の可能性", "センサー本体異常の可能性"],
        "checks": ["配線短絡確認", "コネクタ確認", "MAF値確認"],
        "priority": "中",
    },
    "P0110": {
        "name": "吸気温センサ回路異常",
        "causes": ["IATセンサー本体の可能性", "配線異常の可能性", "カプラ接触不良の可能性"],
        "checks": ["吸気温表示確認", "センサー配線確認", "コネクタ確認"],
        "priority": "低〜中",
    },
    "P0115": {
        "name": "水温センサ回路異常",
        "causes": ["水温センサー本体の可能性", "配線異常の可能性", "コネクタ接触不良の可能性"],
        "checks": ["水温PID確認", "センサー配線確認", "カプラ確認"],
        "priority": "中",
    },
    "P0116": {
        "name": "水温センサ範囲・性能異常",
        "causes": ["水温センサーずれの可能性", "サーモスタット影響の可能性", "配線異常の可能性"],
        "checks": ["暖機時の水温変化確認", "冷間時の値確認", "冷却系確認"],
        "priority": "中",
    },
    "P0117": {
        "name": "水温センサ入力低異常",
        "causes": ["水温信号低下の可能性", "配線短絡の可能性", "センサー異常の可能性"],
        "checks": ["配線短絡確認", "カプラ確認", "水温表示確認"],
        "priority": "中",
    },
    "P0118": {
        "name": "水温センサ入力高異常",
        "causes": ["水温信号高すぎの可能性", "配線断線の可能性", "センサー異常の可能性"],
        "checks": ["配線断線確認", "コネクタ確認", "水温表示確認"],
        "priority": "中",
    },
    "P0120": {
        "name": "スロットル開度センサ回路異常",
        "causes": ["TPSセンサー本体の可能性", "配線異常の可能性", "スロットル系の可能性"],
        "checks": ["スロットル開度PID確認", "配線確認", "スロットルボディ確認"],
        "priority": "中",
    },
    "P0122": {
        "name": "スロットル開度センサ入力低異常",
        "causes": ["TPS信号低下の可能性", "配線断線の可能性", "センサーずれの可能性"],
        "checks": ["TPS値確認", "配線とカプラ確認", "スロットル動作確認"],
        "priority": "中",
    },
    "P0123": {
        "name": "スロットル開度センサ入力高異常",
        "causes": ["TPS信号高すぎの可能性", "配線短絡の可能性", "センサー本体異常の可能性"],
        "checks": ["TPS値確認", "配線短絡確認", "コネクタ確認"],
        "priority": "中",
    },
    "P0130": {
        "name": "前段O2センサ回路異常",
        "causes": ["O2センサー本体の可能性", "配線異常の可能性", "排気漏れの可能性"],
        "checks": ["O2センサー配線確認", "排気漏れ確認", "センサー応答確認"],
        "priority": "中",
    },
    "P0401": {
        "name": "EGR流量不足",
        "causes": ["EGR通路詰まりの可能性", "EGRバルブ不良の可能性", "制御系の可能性"],
        "checks": ["EGR通路確認", "EGRバルブ確認", "負圧や制御確認"],
        "priority": "中",
    },
    "P0136": {
        "name": "後段O2センサ回路異常",
        "causes": ["後段O2センサー本体の可能性", "配線異常の可能性", "排気系影響の可能性"],
        "checks": ["後段O2センサー確認", "配線とカプラ確認", "排気系確認"],
        "priority": "中",
    },
    "P0172": {
        "name": "燃調リッチ異常",
        "causes": ["燃料多めの可能性", "MAFずれの可能性", "O2センサー影響の可能性"],
        "checks": ["燃調補正確認", "MAF値確認", "O2センサー確認"],
        "priority": "中",
    },
    "P0301": {
        "name": "1番気筒ミスファイア",
        "causes": ["1番の点火系の可能性", "インジェクタの可能性", "圧縮低下の可能性"],
        "checks": ["1番プラグとコイル確認", "インジェクタ確認", "圧縮確認"],
        "priority": "高",
    },
    "P0302": {
        "name": "2番気筒ミスファイア",
        "causes": ["2番の点火系の可能性", "インジェクタの可能性", "圧縮低下の可能性"],
        "checks": ["2番プラグとコイル確認", "インジェクタ確認", "圧縮確認"],
        "priority": "高",
    },
    "P0303": {
        "name": "3番気筒ミスファイア",
        "causes": ["3番の点火系の可能性", "インジェクタの可能性", "圧縮低下の可能性"],
        "checks": ["3番プラグとコイル確認", "インジェクタ確認", "圧縮確認"],
        "priority": "高",
    },
    "P0304": {
        "name": "4番気筒ミスファイア",
        "causes": ["4番の点火系の可能性", "インジェクタの可能性", "圧縮低下の可能性"],
        "checks": ["4番プラグとコイル確認", "インジェクタ確認", "圧縮確認"],
        "priority": "高",
    },
    "P0325": {
        "name": "ノックセンサ回路異常",
        "causes": ["ノックセンサー本体の可能性", "配線劣化の可能性", "カプラ接触不良の可能性"],
        "checks": ["ノックセンサー配線確認", "カプラ確認", "関連ハーネス確認"],
        "priority": "中",
    },
    "P0335": {
        "name": "クランク角センサ回路異常",
        "causes": ["クランク角センサー本体の可能性", "配線異常の可能性", "回転信号不安定の可能性"],
        "checks": ["始動時回転信号確認", "配線確認", "センサー本体確認"],
        "priority": "高",
    },
    "P0340": {
        "name": "カム角センサ回路異常",
        "causes": ["カム角センサー本体の可能性", "配線異常の可能性", "同期信号異常の可能性"],
        "checks": ["センサー配線確認", "カプラ確認", "始動時信号確認"],
        "priority": "高",
    },
    "P0351": {
        "name": "イグニッションコイルA回路異常",
        "causes": ["点火コイル不良の可能性", "配線異常の可能性", "制御信号異常の可能性"],
        "checks": ["対象コイル確認", "配線確認", "プラグ状態確認"],
        "priority": "高",
    },
    "P0352": {
        "name": "イグニッションコイルB回路異常",
        "causes": ["点火コイル不良の可能性", "配線異常の可能性", "制御信号異常の可能性"],
        "checks": ["対象コイル確認", "配線確認", "プラグ状態確認"],
        "priority": "高",
    },
    "P0402": {
        "name": "EGR流量過大",
        "causes": ["EGRバルブ開き過ぎの可能性", "制御異常の可能性", "通路不具合の可能性"],
        "checks": ["EGRバルブ動作確認", "負圧や制御確認", "アイドル状態確認"],
        "priority": "中",
    },
    "P0440": {
        "name": "EVAP系異常",
        "causes": ["燃料タンク蒸発ガス系の漏れ可能性", "キャップ不良の可能性", "配管異常の可能性"],
        "checks": ["燃料キャップ確認", "EVAPホース確認", "配管漏れ確認"],
        "priority": "低〜中",
    },
    "P0441": {
        "name": "EVAPパージ流量異常",
        "causes": ["パージバルブ固着の可能性", "ホース接続不良の可能性", "制御系異常の可能性"],
        "checks": ["パージバルブ動作確認", "EVAPホース取り回し確認", "関連配線確認"],
        "priority": "低〜中",
    },
    "P0442": {
        "name": "EVAP小漏れ検出",
        "causes": ["燃料キャップ密閉不良の可能性", "細いホース亀裂の可能性", "配管接続緩みの可能性"],
        "checks": ["燃料キャップ締付確認", "EVAPホースのひび確認", "配管接続部確認"],
        "priority": "低",
    },
    "P0455": {
        "name": "EVAP大漏れ検出",
        "causes": ["燃料キャップ外れや緩みの可能性", "EVAP配管外れの可能性", "大きな漏れの可能性"],
        "checks": ["燃料キャップ状態確認", "EVAP配管外れ確認", "タンク周辺の漏れ確認"],
        "priority": "低〜中",
    },
    "P0500": {
        "name": "車速センサ異常",
        "causes": ["車速センサ本体の可能性", "配線の可能性", "コネクタの可能性", "メーター信号の可能性", "ECU入力異常の可能性"],
        "checks": ["速度表示確認", "走行中の車速PID確認", "配線確認", "カプラ確認"],
        "priority": "中",
    },
    "P0505": {
        "name": "アイドル制御系異常",
        "causes": ["ISC系汚れの可能性", "吸気漏れの可能性", "制御系異常の可能性"],
        "checks": ["アイドル回転確認", "吸気漏れ確認", "スロットル周辺確認"],
        "priority": "中",
    },
    "B2797": {
        "name": "イモビライザー通信線異常",
        "causes": ["イモビ系通信異常の可能性", "配線異常の可能性", "キー認証系の可能性", "一時的記録の可能性"],
        "checks": ["始動性確認", "キー認識確認", "関連配線確認"],
        "priority": "低〜中",
    },
}

VEHICLE_PROFILES = [
    {
        "maker_aliases": ["volkswagen", "vw"],
        "model_aliases": [],
        "title": "VW系参考",
        "note": "VIN multi-frame成功例や、DTCなし判定が通る実車例があります",
        "connect_hint": "SEARCHING...4100... の継続応答や 0902 multi-frame を確認してください",
        "pid_hint": "一部PIDは NO DATA の場合があります。基本PID中心で確認してください",
        "recommended": "通常接続で反応が弱い場合も、VIN取得は再試行価値があります",
    },
    {
        "maker_aliases": ["lexus"],
        "model_aliases": ["es", "es300h", "es300", "axzh", "axzh11"],
        "title": "レクサスES / HV系参考",
        "note": "接続は比較的良好で、COM13 / 115200 で安定した実車例があります",
        "connect_hint": "PID取得や DTCなし判定は通常手順で確認しやすい傾向があります",
        "vin_hint": "短い識別文字列が取れる場合があります。その場合は VIN候補 として扱ってください",
        "pid_hint": "ハイブリッド系ではアイドル値や THR を通常ガソリン車の感覚で断定しないでください",
        "recommended": "停止時ログでも HV制御の影響があるため、単独値より全体傾向を見てください",
    },
    {
        "maker_aliases": ["toyota", "lexus"],
        "model_aliases": ["hybrid", "hv", "プリウス", "prius", "カムリ", "camry", "axvh", "axuh", "axzh"],
        "title": "トヨタ / レクサスHV系参考",
        "note": "接続自体は比較的安定でも、エンジン停止制御で見え方が変わる場合があります",
        "connect_hint": "基本PID取得はしやすい一方、停止中でも値の解釈は慎重に見てください",
        "vin_hint": "17文字VINではなく短い識別文字列として返る場合があります",
        "pid_hint": "ハイブリッド系ではアイドル回転やスロットル値を単純比較しないでください",
        "recommended": "VIN候補表示やログ全体の傾向を併せて判断する使い方が無難です",
    },
    {
        "maker_aliases": ["toyota"],
        "model_aliases": ["セルシオ", "celsior", "ucf21"],
        "title": "セルシオ参考",
        "note": "古い車両では接続不安定で、VIN未取得がありうる傾向があります",
        "connect_hint": "SEARCHING...4100... や UNABLE TO CONNECT が混在する前提で再試行してください",
        "vin_hint": "VINが取れなくても異常ではありません。DTCと基本PIDを先に確認してください",
        "recommended": "VIN未取得でも DTC と基本PID の確認を先に進める運用が無難です",
    },
    {
        "maker_aliases": ["nissan"],
        "model_aliases": ["キューブ", "cube"],
        "title": "日産キューブ参考",
        "note": "比較的安定して接続しやすく、ライブ表示も取りやすい実車例があります",
        "connect_hint": "通常接続と基本PID確認から入る流れが使いやすいです",
        "pid_hint": "PIDやライブ表示がきれいに取りやすい傾向があります",
        "recommended": "VIN、DTC、基本PID の順で確認すると状況整理しやすいです",
    },
    {
        "maker_aliases": ["mitsubishi", "fuso", "mitsubishi fuso"],
        "model_aliases": ["キャンター", "canter"],
        "title": "キャンター参考",
        "note": "BUS INIT / BUS BUSY 系が出やすく、初期化待ちが長めになることがあります",
        "connect_hint": "通信初期化系メッセージ時は、時間を置いた再試行や安定モード確認が有効です",
        "recommended": "ECU応答が弱い場合でも DTC や一部PID が読めるか段階的に確認してください",
    },
]


def vin_to_maker(vin):
    if not vin:
        return None
    vin = vin.strip().upper()
    if len(vin) != 17:
        return None
    wmi3 = vin[:3]
    if wmi3 in WMI_TO_MAKER:
        return WMI_TO_MAKER[wmi3]
    wmi2 = vin[:2]
    if wmi2 in WMI_TO_MAKER:
        return WMI_TO_MAKER[wmi2]
    return None


def detect_engine_type(vin, maker):
    if not vin or not maker:
        return None
    vin = vin.strip().upper()
    maker = maker.lower()
    if len(vin) < 9:
        return None
    vds = vin[3:9]
    maker_map = VDS_TO_ENGINE.get(maker, {})
    if vds in maker_map:
        return maker_map[vds]
    for n in (5, 4, 3):
        for key, value in maker_map.items():
            if len(key) == n and vds.startswith(key):
                return value
    return "UNKNOWN"


def classify_vin_text(vin_text):
    text = (vin_text or "").strip().upper()
    if not text:
        return {
            "label": "VIN",
            "value": "未取得",
            "note": None,
            "is_full_vin": False,
            "kind": "missing",
        }
    if len(text) == 17:
        return {
            "label": "VIN",
            "value": text,
            "note": None,
            "is_full_vin": True,
            "kind": "full",
        }
    return {
        "label": "VIN候補",
        "value": text,
        "note": "17文字未満のため完全VINではない可能性があります",
        "is_full_vin": False,
        "kind": "partial",
    }


def normalize_profile_token(text):
    return (text or "").strip().lower()


def get_vehicle_profile(vin=None, maker=None, model=None):
    maker_norm = normalize_profile_token(maker or vin_to_maker(vin))
    model_norm = normalize_profile_token(model)

    fallback = None
    for profile in VEHICLE_PROFILES:
        maker_aliases = [normalize_profile_token(item) for item in profile.get("maker_aliases", [])]
        model_aliases = [normalize_profile_token(item) for item in profile.get("model_aliases", [])]
        maker_match = bool(maker_norm and maker_norm in maker_aliases)
        model_match = bool(model_norm and any(alias and alias in model_norm for alias in model_aliases))
        if maker_match and model_match:
            return profile
        if maker_match and not model_aliases and fallback is None:
            fallback = profile
    return fallback


def print_vehicle_profile_hint(vin=None, maker=None, model=None):
    profile = get_vehicle_profile(vin=vin, maker=maker, model=model)
    if not profile:
        return
    print("")
    print("参考プロファイル:")
    print(f"- {profile['title']}")
    print(f"- 傾向: {profile['note']}")
    print(f"- 接続時: {profile['connect_hint']}")
    if profile.get("vin_hint"):
        print(f"- VIN補足: {profile['vin_hint']}")
    if profile.get("pid_hint"):
        print(f"- 取得補足: {profile['pid_hint']}")


def normalize_hex(text):
    return " ".join(text.replace("\r", " ").replace("\n", " ").split())


def classify_0100_response(data):
    data_norm = normalize_hex(data).upper()
    data_compact = data_norm.replace(" ", "")
    has_4100 = ("41 00" in data_norm) or ("4100" in data_compact)
    if not data_norm.strip():
        return "timeout", "タイムアウト（ECUから応答がありません）"
    if has_4100:
        return "ok", "ECU応答あり"
    if "UNABLE TO CONNECT" in data_norm:
        return "unable_to_connect", "UNABLE TO CONNECT（ECUと通信確立できません）"
    if "NO DATA" in data_norm:
        return "no_data", "NO DATA（ECUから応答がありません）"
    if "BUS INIT" in data_norm:
        return "bus_init", "BUS INIT...（通信初期化中のまま応答なし）"
    if "SEARCHING" in data_norm and not has_4100:
        return "searching", "SEARCHING...（プロトコル探索中で応答なし）"
    if "OK" in data_norm and not has_4100:
        return "adapter_only", "アダプタ応答のみで ECU応答なし（0100 -> OK）"
    return "unknown", "ATコマンドは通るが ECU応答なし"


def safe_send(ser, command, wait=0.25, retries=1, clear_buffer=True):
    try:
        if isinstance(command, bytes):
            cmd_bytes = command
            cmd_text = command.decode(errors="ignore").strip().upper()
        else:
            cmd_text = str(command).strip().upper()
            cmd_bytes = cmd_text.encode()

        if not cmd_bytes.endswith(b"\r"):
            cmd_bytes += b"\r"

        if cmd_text == "ATZ":
            wait = max(wait, 1.8)
        elif cmd_text == "0100":
            wait = max(wait, 0.6)
        elif cmd_text.startswith("AT"):
            wait = max(wait, 0.3)
        else:
            wait = max(wait, 0.2)

        for attempt in range(retries + 1):
            if clear_buffer:
                try:
                    ser.reset_input_buffer()
                except Exception:
                    pass
                try:
                    ser.reset_output_buffer()
                except Exception:
                    pass

            add_log("SEND", cmd_text)
            ser.write(cmd_bytes)
            time.sleep(wait)

            chunks = []
            read_cycles = 9 if cmd_text == "0100" else 5
            for _ in range(read_cycles):
                raw = ser.read(256)
                if raw:
                    text = raw.decode(errors="ignore").replace("\x00", "")
                    chunks.append(text)
                    if cmd_text == "0100":
                        joined = "".join(chunks).upper()
                        if (
                            "41 00" in joined
                            or "4100" in joined
                            or "NO DATA" in joined
                            or "UNABLE TO CONNECT" in joined
                            or ">" in joined
                        ):
                            break
                    elif ">" in text:
                        break
                else:
                    time.sleep(0.08)

            data = "".join(chunks).strip()
            data_u = data.upper()
            summary = normalize_hex(data)[:220]
            add_log("RECV", summary if summary else "(empty)")

            if "UNABLE TO CONNECT" in data_u:
                add_log("ERROR", f"{cmd_text} -> UNABLE TO CONNECT（ECUと通信確立できない）")
                return data
            if "ERROR" in data_u:
                add_log("ERROR", f"{cmd_text} 実行エラー")
                return data
            if "NO DATA" in data_u:
                add_log("WARN", f"{cmd_text} -> NO DATA（ECU応答なし）")
                return data

            if data and ("SEARCHING" in data_u or "BUS INIT" in data_u):
                if "SEARCHING" in data_u:
                    add_log("INFO", f"{cmd_text} -> SEARCHING...（プロトコル探索中）")
                if "BUS INIT" in data_u:
                    add_log("INFO", f"{cmd_text} -> BUS INIT...（通信初期化中）")
                extra_rounds = 3 if cmd_text == "0100" else 1
                for _ in range(extra_rounds):
                    time.sleep(0.25)
                    extra = ser.read(256).decode(errors="ignore").replace("\x00", "")
                    if extra:
                        data = (data + extra).strip()
                        data_u = data.upper()
                        add_log("RECV", normalize_hex(data)[:220])
                    if cmd_text == "0100" and (
                        "41 00" in data_u
                        or "4100" in data_u
                        or "NO DATA" in data_u
                        or "UNABLE TO CONNECT" in data_u
                    ):
                        break

            if data:
                return data

            if attempt < retries:
                add_log("WARN", f"{cmd_text} 応答なし。再試行します ({attempt + 1}/{retries})")
                time.sleep(0.15)

        add_log("WARN", f"{cmd_text} -> タイムアウト（応答なし）")
        return ""
    except KeyboardInterrupt:
        add_log("WARN", f"{cmd_text if 'cmd_text' in locals() else 'CMD'} -> ユーザー中断")
        raise
    except Exception as e:
        add_log("ERROR", f"safe_send 例外: {e}")
        return ""


def parse_dtc_from_43(data):
    codes = []
    seen = set()
    dtc_prefix = ["P", "C", "B", "U"]

    def to_dtc(word):
        if len(word) != 4:
            return None
        try:
            value = int(word, 16)
        except Exception:
            return None
        if value == 0:
            return None
        pfx = dtc_prefix[(value >> 14) & 0x03]
        d1 = (value >> 12) & 0x03
        d2 = (value >> 8) & 0x0F
        d3 = (value >> 4) & 0x0F
        d4 = value & 0x0F
        return f"{pfx}{d1}{d2:X}{d3:X}{d4:X}"

    data_norm = normalize_hex(data).upper()
    payload_hex = "".join(ch for ch in data_norm if ch in "0123456789ABCDEF")
    bytes_list = [payload_hex[i : i + 2] for i in range(0, len(payload_hex), 2) if len(payload_hex[i : i + 2]) == 2]

    if "43" not in bytes_list:
        return codes

    for idx, byte in enumerate(bytes_list):
        if byte != "43":
            continue
        frame_bytes = []
        for next_byte in bytes_list[idx + 1 :]:
            if next_byte == "43":
                break
            frame_bytes.append(next_byte)
        for pos in range(0, len(frame_bytes), 2):
            word_bytes = frame_bytes[pos : pos + 2]
            if len(word_bytes) != 2:
                continue
            dtc = to_dtc("".join(word_bytes))
            if dtc and dtc not in seen:
                seen.add(dtc)
                codes.append(dtc)
    return codes


def dtc_desc(code, maker):
    maker = (maker or "generic").lower()
    info = DTC_DB.get(code)
    if not info:
        return f"{code}: 説明なし"
    # 汎用OBD2で読みやすい generic DTC を優先しつつ、メーカー別定義があればそれを使う。
    if maker in info:
        return f"{code}: {info[maker]}"
    if "generic" in info:
        return f"{code}: {info['generic']}"
    return f"{code}: 説明なし"


def get_dtc_knowledge(code):
    return DTC_KNOWLEDGE.get((code or "").strip().upper())


def print_dtc_knowledge_block(codes):
    shown = False
    for code in codes or []:
        info = get_dtc_knowledge(code)
        if not info:
            continue
        if not shown:
            print("")
            print("=== DTC知識ベース ===")
            shown = True
        print(f"コード: {code}")
        print(f"名称: {info['name']}")
        print(f"緊急度: {info['priority']}")
        print("原因候補:")
        for cause in info["causes"]:
            print(f"- {cause}")
        print("次に確認:")
        for check in info["checks"]:
            print(f"- {check}")
        print("")


def print_obd_scope_hint():
    print("補足: 汎用OBD2の範囲で読める項目のみ取得できる場合があります。")
    print("補足: VINや一部PIDは車種によって取得できないことがあります。")


def print_connection_failure_hint():
    print("案内: アダプタ応答があっても、ECU応答は車種や年式によって限定的な場合があります。")
    print("案内: メーカー独自項目は本ツールでは未対応の場合があります。")


def print_pid_availability_hint(pid):
    missing = [key for key, value in pid.items() if value is None]
    if not missing:
        return
    print(f"補足: 一部PIDは未取得です ({', '.join(missing)})")
    print("補足: 車種によっては汎用OBD2で読める基本PIDだけ表示されます。")


def read_vin_stable(ser):
    def parse_vin_from_49_02(raw):
        def decode_vin_hex(vin_hex):
            vin_hex = "".join(ch for ch in vin_hex.upper() if ch in "0123456789ABCDEF")
            if vin_hex.startswith("490201"):
                vin_hex = vin_hex[6:]
            vin_chars = []
            for i in range(0, len(vin_hex) - 1, 2):
                try:
                    vin_chars.append(chr(int(vin_hex[i : i + 2], 16)))
                except Exception:
                    pass
            vin = "".join(vin_chars).strip()
            vin = "".join(ch for ch in vin if ch.isalnum())
            if len(vin) >= 17:
                return vin[:17]
            if len(vin) >= 10:
                return vin
            return None

        indexed_frames = {}
        for seq, payload in re.findall(r"([0-9A-Fa-f]+)\s*:\s*([0-9A-Fa-f]+)", raw):
            indexed_frames[seq.upper()] = payload.upper()
        if indexed_frames:
            vin_hex = "".join(indexed_frames[key] for key in sorted(indexed_frames.keys(), key=lambda x: int(x, 16)))
            vin = decode_vin_hex(vin_hex)
            if vin:
                return vin

        frame_data = {}
        fallback_bytes = []

        for line in raw.replace("\n", "\r").split("\r"):
            line = line.strip()
            if "49 02" not in line:
                continue
            parts = [p for p in line.split(" ") if p]
            try:
                idx = parts.index("49")
            except ValueError:
                continue
            if len(parts) <= idx + 2 or parts[idx + 1] != "02":
                continue

            seq = parts[idx + 2]
            payload = parts[idx + 3:]
            if len(seq) == 2 and all(c in "0123456789ABCDEFabcdef" for c in seq):
                frame_data[seq.upper()] = payload
            else:
                fallback_bytes.extend(parts[idx + 2:])

        vin_hex = "".join("".join(frame_data[key]) for key in sorted(frame_data.keys(), key=lambda x: int(x, 16)))
        vin = decode_vin_hex(vin_hex)
        if vin:
            return vin

        vin2 = decode_vin_hex("".join(fallback_bytes))
        if vin2:
            return vin2
        return None

    for _ in range(3):
        data = safe_send(ser, "0902", wait=0.35, retries=1, clear_buffer=True)
        data_norm = normalize_hex(data).upper()
        data_compact = data_norm.replace(" ", "")
        if ("49 02" not in data_norm) and ("4902" not in data_compact):
            time.sleep(0.15)
            continue
        vin = parse_vin_from_49_02(data)
        if vin and len(vin) >= 17:
            return vin
        if vin and len(vin) >= 10:
            return vin
        time.sleep(0.15)
    return None


def read_basic_pid(ser, return_details=False):
    values = {
        "RPM": None,
        "ECT": None,
        "MAF": None,
        "SPEED": None,
        "IAT": None,
        "THROTTLE": None,
    }
    raw_map = {}
    notes = []

    def parse_after_header(data, header, count):
        data_norm = normalize_hex(data).upper()
        data_compact = data_norm.replace(" ", "")
        header_compact = header.replace(" ", "")
        start = data_compact.find(header_compact)
        if start < 0:
            return None
        try:
            payload = data_compact[start + len(header_compact) :]
            payload = "".join(ch for ch in payload if ch in "0123456789ABCDEF")
            if len(payload) < count * 2:
                return None
            return [int(payload[i * 2 : (i + 1) * 2], 16) for i in range(count)]
        except Exception:
            return None

    pid_specs = [
        ("RPM", "010C", "41 0C", 2, lambda raw: ((raw[0] * 256) + raw[1]) / 4),
        ("ECT", "0105", "41 05", 1, lambda raw: raw[0] - 40),
        ("MAF", "0110", "41 10", 2, lambda raw: ((raw[0] * 256) + raw[1]) / 100),
        ("SPEED", "010D", "41 0D", 1, lambda raw: raw[0]),
        ("IAT", "010F", "41 0F", 1, lambda raw: raw[0] - 40),
        ("THROTTLE", "0111", "41 11", 1, lambda raw: round((raw[0] * 100) / 255, 1)),
    ]

    for key, command, header, count, decoder in pid_specs:
        raw_value = safe_send(ser, command, wait=0.2, retries=1, clear_buffer=True)
        raw_norm = normalize_hex(raw_value) if raw_value else ""
        if return_details:
            raw_map[key] = raw_norm
        parsed = parse_after_header(raw_value, header, count)
        if parsed is not None:
            try:
                values[key] = decoder(parsed)
            except Exception:
                values[key] = None
        if return_details:
            raw_upper = raw_norm.upper()
            header_compact = header.replace(" ", "")
            raw_compact = raw_upper.replace(" ", "")
            if not raw_upper:
                notes.append(f"{key}: 未取得")
            elif "NO DATA" in raw_upper:
                notes.append(f"{key}: NO DATA")
            elif ":" in raw_upper or raw_compact.count(header_compact) >= 2:
                notes.append(f"{key}: 複数応答あり")
            elif parsed is not None:
                notes.append(f"{key}: 単一応答")
            elif raw_upper in {"OK", "SEARCHING"}:
                notes.append(f"{key}: アダプタ応答のみ")
            elif parsed is None:
                notes.append(f"{key}: 要確認")

    if return_details:
        return values, raw_map, notes
    return values


def analyze_pid_conditions(pid_values):
    lines = []

    rpm = pid_values.get("RPM")
    if rpm is not None:
        if rpm < 500:
            lines.append("回転数は低すぎます")
        elif rpm <= 900:
            lines.append("回転数はアイドル範囲です")
        elif rpm <= 2000:
            lines.append("回転数は軽負荷域です")
        elif rpm > 3000:
            lines.append("回転数は高回転です")

    ect = pid_values.get("ECT")
    if ect is not None:
        if ect < 40:
            lines.append("水温は冷間状態です")
        elif ect <= 70:
            lines.append("水温は暖機状態です")
        elif ect <= 105:
            lines.append("水温は正常範囲です")
        else:
            lines.append("水温は高すぎます。オーバーヒートに注意してください")

    iat = pid_values.get("IAT")
    if iat is not None:
        if -10 <= iat <= 10:
            lines.append("吸気温は冬季相当です")
        elif 10 < iat <= 40:
            lines.append("吸気温は正常範囲です")
        elif iat > 50:
            lines.append("吸気温が高めです")

    speed = pid_values.get("SPEED")
    if speed is not None:
        if speed == 0:
            lines.append("停車中のため車速は 0km/h です")
        elif speed >= 1:
            lines.append("走行中のため車速が出ています")

    throttle = pid_values.get("THR")
    if throttle is None:
        throttle = pid_values.get("THROTTLE")
    if throttle is not None:
        if throttle <= 5:
            lines.append("スロットル開度は閉じ気味です")
        elif throttle <= 15:
            lines.append("スロットル開度はアイドル範囲です")
        elif throttle <= 40:
            lines.append("スロットル開度は軽加速です")
        else:
            lines.append("スロットル開度は強加速です")

    maf = pid_values.get("MAF")
    if maf is None:
        lines.append("吸入空気量は未取得です")
    elif maf < 2:
        lines.append("吸入空気量は低すぎます")
    elif maf <= 10:
        lines.append("吸入空気量はアイドル範囲です")
    elif maf > 100:
        lines.append("吸入空気量は高負荷域です")

    return lines


def build_pid_comment_lines(pid):
    return analyze_pid_conditions(pid)


def print_pid_comment_block(pid, dtc_list=None):
    print("")
    print("=== センサー簡易診断 ===")
    print(f"RPM   : {pid['RPM'] if pid['RPM'] is not None else 'N/A'}")
    print(f"ECT   : {pid['ECT'] if pid['ECT'] is not None else 'N/A'}")
    print(f"MAF   : {pid['MAF'] if pid['MAF'] is not None else 'N/A'}")
    print(f"SPEED : {pid['SPEED'] if pid['SPEED'] is not None else 'N/A'}")
    print(f"IAT   : {pid['IAT'] if pid['IAT'] is not None else 'N/A'}")
    print(f"THR   : {pid['THROTTLE'] if pid['THROTTLE'] is not None else 'N/A'}")
    print("")
    print("判定:")
    for line in build_pid_comment_lines(pid):
        print(f"- {line}")
    hint_lines = build_dtc_pid_hints(dtc_list, pid)
    if hint_lines:
        print("")
        print("DTC連動補足:")
        for line in hint_lines:
            print(f"- {line}")
    overall_notes = build_overall_reference_notes(
        dtc_list=dtc_list,
        dtc_pid_hints=hint_lines,
    )
    if overall_notes:
        print("")
        print("[総合参考メモ]")
        for line in overall_notes:
            print(f"- {line}")


def format_pid_value(value):
    if value is None:
        return "未取得"
    if isinstance(value, float):
        text = f"{value:.2f}".rstrip("0").rstrip(".")
        return text
    return str(value)


def print_mechanic_pid_screen(ser, connected_port, connected_baud, cached_vin, last_dtc_codes):
    os.system("cls" if os.name == "nt" else "clear")
    pid, raw_map, notes = read_basic_pid(ser, return_details=True)
    dtc_text = "未取得" if last_dtc_codes is None else ("なし" if not last_dtc_codes else ", ".join(last_dtc_codes))
    dtc_pid_hints = build_dtc_pid_hints(last_dtc_codes, pid)
    vin_info = classify_vin_text(cached_vin)

    print("============================================================")
    print("                 OBD2 CLI / 整備士モード")
    print("============================================================")
    print("画面種別 : 基本PID詳細")
    print(f"接続     : {(connected_port if connected_port else '未取得')} / {(connected_baud if connected_baud else '未取得')}")
    print(f"{vin_info['label']:<8}: {vin_info['value']}")
    print(f"DTC      : {dtc_text}")
    if vin_info["note"]:
        print(f"補足     : {vin_info['note']}")
    print("============================================================")
    print("")
    print("[現在値]")
    print(f"RPM        : {format_pid_value(pid['RPM'])}")
    print(f"ECT        : {format_pid_value(pid['ECT'])}")
    print(f"MAF        : {format_pid_value(pid['MAF'])}")
    print(f"SPEED      : {format_pid_value(pid['SPEED'])}")
    print(f"IAT        : {format_pid_value(pid['IAT'])}")
    print(f"THROTTLE   : {format_pid_value(pid['THROTTLE'])}")
    print("")
    print("[取得状態]")
    for note in notes:
        print(f"- {note}")
    print("")
    print("[PID RAW応答]")
    print(format_live_raw_line("010C", raw_map.get("RPM"), "RPM"))
    print(format_live_raw_line("0105", raw_map.get("ECT"), "ECT"))
    print(format_live_raw_line("0110", raw_map.get("MAF"), "MAF"))
    print(format_live_raw_line("010D", raw_map.get("SPEED"), "SPEED"))
    print(format_live_raw_line("010F", raw_map.get("IAT"), "IAT"))
    print(format_live_raw_line("0111", raw_map.get("THROTTLE"), "THR"))
    print("")
    print("[応答補足]")
    if not dtc_pid_hints:
        print("- DTC連動補足はありません")
    for line in dtc_pid_hints:
        print(f"- {line}")
    print("")
    print("[簡易判定]")
    for line in build_pid_comment_lines(pid):
        print(f"- {line}")
    print("")
    print("------------------------------------------------------------")
    print("Enter: メニューへ戻る")
    print("------------------------------------------------------------")
    try:
        input("")
    except KeyboardInterrupt:
        print("")


def format_live_raw_line(command, raw_text, label=None):
    raw_text = raw_text or "未取得"
    if len(raw_text) > 72:
        raw_text = raw_text[:69] + "..."
    if label:
        return f"{f'{command} ({label})':<16} -> {raw_text}"
    return f"{command} -> {raw_text}"


def init_adapter(ser):
    init_cmds = [
        ("ATZ", 1.8, True),
        ("ATE0", 0.3, False),
        ("ATL0", 0.3, False),
        ("ATH0", 0.3, False),
        ("ATS0", 0.3, False),
        ("ATAT1", 0.35, False),
        ("ATSP0", 0.35, False),
    ]

    for cmd, wait, clear_buffer in init_cmds:
        res = safe_send(ser, cmd, wait=wait, retries=1, clear_buffer=clear_buffer)
        if not res:
            add_log("WARN", f"[INIT] {cmd} 応答なし")
        else:
            add_log("INIT", f"{cmd} -> {normalize_hex(res)[:120]}")
        if cmd == "ATSP0":
            time.sleep(0.35)


def connect_obd_auto(possible_ports=None):
    global LAST_CONNECT_REASON

    def classify_0100(data):
        return classify_0100_response(data)

    def try_manual_protocols(ser):
        add_log("INFO", "手動プロトコル試験開始")
        for proto_code in ("3", "4", "5"):
            cmd = f"ATSP{proto_code}"
            add_log("INFO", f"{cmd} を試行")
            sp_res = safe_send(ser, cmd, wait=0.35, retries=0, clear_buffer=False)
            if not sp_res:
                add_log("WARN", f"{cmd} 応答なし")
                continue

            time.sleep(0.25)
            check = safe_send(ser, "0100", wait=0.85, retries=1, clear_buffer=True)
            reason_code, reason_text = classify_0100(check)
            add_log("CHECK", f"{cmd} 0100応答: {normalize_hex(check)[:140] if check else '(empty)'}")
            if reason_code == "ok":
                proto_name = safe_send(ser, "ATDP", wait=0.3, retries=0, clear_buffer=False)
                proto_text = normalize_hex(proto_name)[:120] if proto_name else "不明"
                add_log("OK", f"{cmd} 成功: ECU応答あり")
                add_log("INFO", f"手動プロトコル確定: {cmd} / {proto_text}")
                return True, proto_code, reason_text
            add_log("WARN", f"{cmd} 失敗[{reason_code}]: {reason_text}")

        return False, "manual_failed", "手動プロトコル試験すべて失敗"

    if possible_ports is None:
        detected_ports = []
        try:
            detected_ports = [p.device for p in list_ports.comports() if p.device]
        except Exception as e:
            add_log("WARN", f"COMポート列挙に失敗: {e}")

        possible_ports = []
        for p in DEFAULT_PORTS + detected_ports:
            if p not in possible_ports:
                possible_ports.append(p)

    LAST_CONNECT_REASON = "接続試行中"
    add_log("INFO", "ポート接続開始（0100でECU応答確認）")
    for port in possible_ports:
        trial_bauds = [115200] if str(port).upper() == "COM13" else BAUD_LIST
        for baud in trial_bauds:
            add_log("INFO", f"{port} を試行中... ({baud}bps)")
            ser = None
            stop_other_ports = False
            try:
                ser = serial.Serial(port, baudrate=baud, timeout=0.25)
                time.sleep(0.25)
                try:
                    ser.reset_input_buffer()
                    ser.reset_output_buffer()
                except Exception:
                    pass

                init_adapter(ser)

                proto = safe_send(ser, "ATDP", wait=0.3, retries=0, clear_buffer=False)
                if proto:
                    add_log("INFO", f"プロトコル: {normalize_hex(proto)[:120]}")
                else:
                    add_log("WARN", "アダプタ応答なし（ATDP）")
                confirmed_adapter = str(port).upper() == "COM13" and baud == 115200 and bool(proto)
                if confirmed_adapter:
                    add_log("INFO", "有効アダプタ確認: COM13 / 115200")

                check = safe_send(ser, "0100", wait=0.6, retries=1, clear_buffer=True)
                reason_code, reason_text = classify_0100(check)
                check_norm = normalize_hex(check).upper()
                check_compact = check_norm.replace(" ", "")
                add_log("CHECK", f"0100応答: {check_norm[:140] if check else '(empty)'}")

                if (("41 00" in check_norm) or ("4100" in check_compact)) and "UNABLE TO CONNECT" not in check_norm:
                    LAST_CONNECT_REASON = "接続成功"
                    add_log("OK", f"ECU接続成功: {port} / {baud}bps")
                    return ser, port, baud

                add_log("WARN", f"0100初回判定[{reason_code}]: {reason_text}")
                add_log("WARN", "接続確認失敗。再初期化を1回実施")

                init_adapter(ser)
                proto2 = safe_send(ser, "ATDP", wait=0.3, retries=0, clear_buffer=False)
                if proto2:
                    add_log("INFO", f"再初期化後プロトコル: {normalize_hex(proto2)[:120]}")

                time.sleep(0.2)
                check2 = safe_send(ser, "0100", wait=0.75, retries=1, clear_buffer=True)
                reason2_code, reason2_text = classify_0100(check2)
                check2_norm = normalize_hex(check2).upper()
                check2_compact = check2_norm.replace(" ", "")
                add_log("CHECK", f"0100再試行応答: {check2_norm[:140] if check2 else '(empty)'}")

                if (("41 00" in check2_norm) or ("4100" in check2_compact)) and "UNABLE TO CONNECT" not in check2_norm:
                    LAST_CONNECT_REASON = "接続成功(再試行)"
                    add_log("OK", f"ECU接続成功(再試行): {port} / {baud}bps")
                    return ser, port, baud

                if reason2_code in ("unable_to_connect", "searching", "no_data", "timeout", "bus_init", "adapter_only"):
                    manual_ok, manual_code, manual_text = try_manual_protocols(ser)
                    if manual_ok:
                        LAST_CONNECT_REASON = f"接続成功(手動ATSP{manual_code})"
                        add_log("OK", f"ECU接続成功(手動プロトコル): {port} / {baud}bps")
                        return ser, port, baud
                    reason2_code, reason2_text = manual_code, manual_text

                LAST_CONNECT_REASON = reason2_text
                add_log("WARN", f"接続失敗理由[{reason2_code}]: {reason2_text}")
                if confirmed_adapter:
                    add_log("WARN", "有効アダプタ上でECU接続失敗。他ポート探索を終了します。")
                    stop_other_ports = True

            except KeyboardInterrupt:
                LAST_CONNECT_REASON = "ユーザー中断"
                add_log("WARN", "接続処理を中断しました")
                if ser:
                    try:
                        ser.close()
                    except Exception:
                        pass
                raise
            except PermissionError as e:
                LAST_CONNECT_REASON = "COMポートが使用中です（または権限不足）"
                add_log("ERROR", f"{port} を開けません (使用中/権限): {e}")
            except serial.SerialException as e:
                LAST_CONNECT_REASON = "COMポートが使用中です（または権限不足）"
                add_log("WARN", f"{port} 接続失敗: {e}")
            except Exception as e:
                LAST_CONNECT_REASON = f"例外: {e}"
                add_log("ERROR", f"{port} 例外: {e}")

            if ser:
                try:
                    ser.close()
                except Exception:
                    pass
            if stop_other_ports:
                add_log("ERROR", f"接続失敗: {LAST_CONNECT_REASON}")
                return None, None, None

    if LAST_CONNECT_REASON in ("接続試行中", "不明"):
        LAST_CONNECT_REASON = "アダプタ応答なし"
    add_log("ERROR", f"接続失敗: {LAST_CONNECT_REASON}")
    return None, None, None


def connect_obd_stable_mode():
    global LAST_CONNECT_REASON

    port = "COM13"
    baud = 115200
    init_settle_wait = 0.55
    attempts = [
        ("AUTO", None, 0.7, 1.15),
        ("ATSP3", "ATSP3", 1.6, 1.25),
        ("ATSP4", "ATSP4", 1.15, 1.15),
        ("ATSP5", "ATSP5", 1.15, 1.15),
    ]

    add_log("INFO", "古い車向け接続安定モード開始")
    ser = None
    try:
        add_log("INFO", f"安定モード対象: {port} / {baud}bps")
        ser = serial.Serial(port, baudrate=baud, timeout=0.25)
        time.sleep(0.25)
        try:
            ser.reset_input_buffer()
            ser.reset_output_buffer()
        except Exception:
            pass

        init_adapter(ser)
        time.sleep(init_settle_wait)
        proto = safe_send(ser, "ATDP", wait=0.3, retries=0, clear_buffer=False)
        if proto:
            add_log("INFO", f"安定モード: アダプタ応答あり ({normalize_hex(proto)[:120]})")
        else:
            LAST_CONNECT_REASON = "COM13 / 115200 でアダプタ応答を確認できませんでした"
            add_log("WARN", LAST_CONNECT_REASON)
            return None, None, None

        for idx, (label, cmd, settle_wait, pid_wait) in enumerate(attempts, start=1):
            add_log("INFO", f"試行{idx}: {port} / {baud} / {label}")
            if cmd:
                sp_res = safe_send(ser, cmd, wait=0.4, retries=0, clear_buffer=False)
                if not sp_res:
                    add_log("WARN", f"試行{idx} プロトコル設定応答なし: {label}")
                    continue
            time.sleep(settle_wait)
            check = safe_send(ser, "0100", wait=pid_wait, retries=1, clear_buffer=True)
            reason_code, reason_text = classify_0100_response(check)
            check_norm = normalize_hex(check).upper()
            add_log("CHECK", f"試行{idx} 0100応答: {check_norm[:140] if check else '(empty)'}")
            add_log("INFO", f"試行{idx} 判定: {reason_text}")
            if reason_code == "ok":
                LAST_CONNECT_REASON = f"接続成功(安定モード:{label})"
                add_log("OK", "安定モードでECU接続成功")
                add_log("INFO", "この設定は古い車で相性が良い場合があります")
                add_log("INFO", "安定モード終了")
                return ser, port, baud

        LAST_CONNECT_REASON = "COM13 / 115200 ではアダプタ応答あり、ECU応答が不安定でした"
        add_log("WARN", LAST_CONNECT_REASON)
        add_log("WARN", "車種や年式、プロトコル相性の影響が考えられます")
        add_log("INFO", "安定モード終了")
        if ser:
            try:
                ser.close()
            except Exception:
                pass
        return None, None, None
    except KeyboardInterrupt:
        LAST_CONNECT_REASON = "ユーザー中断"
        add_log("WARN", "安定モード接続を中断しました")
        if ser:
            try:
                ser.close()
            except Exception:
                pass
        raise
    except PermissionError as e:
        LAST_CONNECT_REASON = "COMポートが使用中です（または権限不足）"
        add_log("ERROR", f"{port} を開けません (使用中/権限): {e}")
    except serial.SerialException as e:
        LAST_CONNECT_REASON = "COMポートが使用中です（または権限不足）"
        add_log("WARN", f"{port} 接続失敗: {e}")
    except Exception as e:
        LAST_CONNECT_REASON = f"例外: {e}"
        add_log("ERROR", f"安定モード例外: {e}")

    add_log("INFO", "安定モード終了")
    if ser:
        try:
            ser.close()
        except Exception:
            pass
    return None, None, None


def show_vehicle_info(vin):
    vin_info = classify_vin_text(vin)
    if vin_info["kind"] == "missing":
        print("車両情報: VIN未取得")
        print("案内: VINは汎用OBD2で取得できない車種もあります。")
        return
    maker = vin_to_maker(vin) or "generic"
    print(f"{vin_info['label']:<6}: {vin_info['value']}")
    if vin_info["note"]:
        print(f"補足    : {vin_info['note']}")
    if not vin_info["is_full_vin"]:
        print("メーカー: 判定保留")
        print("案内: 識別文字列として取得されています。完全VIN取得は再試行してください。")
        return
    engine = detect_engine_type(vin, maker)
    print(f"メーカー: {maker.upper()}")
    print(f"エンジン: {engine}")
    print_vehicle_profile_hint(vin=vin, maker=maker)


def read_dtc(ser, maker):
    data = safe_send(ser, "03", wait=0.35, retries=1, clear_buffer=True)
    if not data:
        add_log("WARN", "DTC読取 応答なし")
        return None
    data_norm = normalize_hex(data).upper()
    if "UNABLE TO CONNECT" in data_norm or "NO DATA" in data_norm or "ERROR" in data_norm:
        add_log("WARN", f"DTC読取失敗: {data_norm[:120]}")
        return None
    codes = parse_dtc_from_43(data)
    if not codes:
        add_log("INFO", "DTCなし")
        return []
    add_log("INFO", f"DTC {len(codes)}件検出")
    print("補足: generic DTC（主に P0xxx）を優先して表示します。")
    for c in codes:
        print(" -", dtc_desc(c, maker))
    for line in build_dtc_history_hints(codes):
        print(line)
    print_dtc_knowledge_block(codes)
    return codes


def clear_dtc(ser):
    data = safe_send(ser, "04", wait=0.5, retries=1, clear_buffer=True)
    if data:
        add_log("INFO", "DTC消去コマンド送信完了")
    else:
        add_log("WARN", "DTC消去 応答なし")


def live_basic_pid_mode(
    ser,
    interval=1.0,
    display_mode="fixed",
    mechanic_detail=False,
    connected_port=None,
    connected_baud=None,
    cached_vin=None,
    last_dtc_codes=None,
):
    global CONSOLE_LOG_MUTED
    ensure_logs_dir()
    live_csv_file = create_live_csv_path(datetime.now())
    if init_live_csv(live_csv_file):
        add_log("INFO", f"ライブCSV保存先: {live_csv_file}")
    else:
        live_csv_file = None

    print("ライブデータ表示を開始します。Enter または Ctrl+C で終了します。")
    add_log("INFO", "ライブデータ表示開始")
    last_event = "PID取得待機中"
    previous_mute = CONSOLE_LOG_MUTED
    if display_mode == "fixed":
        CONSOLE_LOG_MUTED = True
    try:
        while True:
            raw_map = {}
            notes = []
            if mechanic_detail:
                pid, raw_map, notes = read_basic_pid(ser, return_details=True)
            else:
                pid = read_basic_pid(ser)
            now = datetime.now().strftime("%H:%M:%S")
            if live_csv_file:
                append_live_csv_row(
                    live_csv_file,
                    [
                        now,
                        pid["RPM"] if pid["RPM"] is not None else "",
                        pid["ECT"] if pid["ECT"] is not None else "",
                        pid["MAF"] if pid["MAF"] is not None else "",
                        pid["SPEED"] if pid["SPEED"] is not None else "",
                        pid["IAT"] if pid["IAT"] is not None else "",
                        pid["THROTTLE"] if pid["THROTTLE"] is not None else "",
                    ],
                )
                last_event = "CSV保存中 / PID取得継続中"
            else:
                last_event = "PID取得継続中"
            if mechanic_detail:
                os.system("cls" if os.name == "nt" else "clear")
                dtc_text = "未取得" if last_dtc_codes is None else ("なし" if not last_dtc_codes else ", ".join(last_dtc_codes))
                dtc_pid_hints = build_dtc_pid_hints(last_dtc_codes, pid)
                vin_info = classify_vin_text(cached_vin)
                print("============================================================")
                print("                 OBD2 CLI / 整備士モード")
                print("============================================================")
                print("画面種別 : ライブ詳細")
                print(f"接続     : {(connected_port if connected_port else '未取得')} / {(connected_baud if connected_baud else '未取得')}")
                print(f"{vin_info['label']:<8}: {vin_info['value']}")
                print(f"DTC      : {dtc_text}")
                print(f"更新時刻 : {now}")
                if vin_info["note"]:
                    print(f"補足     : {vin_info['note']}")
                print("============================================================")
                print("")
                print("[現在値]")
                print(f"RPM        : {format_pid_value(pid['RPM'])}")
                print(f"ECT        : {format_pid_value(pid['ECT'])}")
                print(f"MAF        : {format_pid_value(pid['MAF'])}")
                print(f"SPEED      : {format_pid_value(pid['SPEED'])}")
                print(f"IAT        : {format_pid_value(pid['IAT'])}")
                print(f"THROTTLE   : {format_pid_value(pid['THROTTLE'])}")
                print("")
                print("[取得状態]")
                for note in notes:
                    print(f"- {note}")
                print("")
                print("[PID RAW応答]")
                print(format_live_raw_line("010C", raw_map.get("RPM"), "RPM"))
                print(format_live_raw_line("0105", raw_map.get("ECT"), "ECT"))
                print(format_live_raw_line("0110", raw_map.get("MAF"), "MAF"))
                print(format_live_raw_line("010D", raw_map.get("SPEED"), "SPEED"))
                print(format_live_raw_line("010F", raw_map.get("IAT"), "IAT"))
                print(format_live_raw_line("0111", raw_map.get("THROTTLE"), "THR"))
                print("")
                print("[応答補足]")
                for line in dtc_pid_hints:
                    print(f"- {line}")
                print(f"- CSV: {'保存中' if live_csv_file else 'OFF'} / PID取得継続中")
                if not dtc_pid_hints and not vin_info["note"]:
                    print("- 追加補足はありません")
                print("[簡易判定]")
                for line in build_pid_comment_lines(pid):
                    print(f"- {line}")
                print("")
                print("------------------------------------------------------------")
                print(f"Enter: 終了   Ctrl+C: 強制終了   CSV: {'保存中' if live_csv_file else 'OFF'}")
                print("------------------------------------------------------------")
            elif display_mode == "fixed":
                os.system("cls" if os.name == "nt" else "clear")
                print("=== ライブデータ ===")
                print(f"RPM   : {pid['RPM'] if pid['RPM'] is not None else 'N/A'}")
                print(f"ECT   : {pid['ECT'] if pid['ECT'] is not None else 'N/A'}")
                print(f"MAF   : {pid['MAF'] if pid['MAF'] is not None else 'N/A'}")
                print(f"SPEED : {pid['SPEED'] if pid['SPEED'] is not None else 'N/A'}")
                print(f"IAT   : {pid['IAT'] if pid['IAT'] is not None else 'N/A'}")
                print(f"THR   : {pid['THROTTLE'] if pid['THROTTLE'] is not None else 'N/A'}")
                print("")
                print(f"更新時刻: {now}")
                print("終了: Enter / Ctrl+C")
                print("")
                print("--- 最新イベント ---")
                print(last_event)
            else:
                print(
                    f"[{now}] "
                    f"RPM:{pid['RPM'] if pid['RPM'] is not None else 'N/A'} "
                    f"ECT:{pid['ECT'] if pid['ECT'] is not None else 'N/A'} "
                    f"MAF:{pid['MAF'] if pid['MAF'] is not None else 'N/A'} "
                    f"SPEED:{pid['SPEED'] if pid['SPEED'] is not None else 'N/A'} "
                    f"IAT:{pid['IAT'] if pid['IAT'] is not None else 'N/A'} "
                    f"THR:{pid['THROTTLE'] if pid['THROTTLE'] is not None else 'N/A'}"
                )

            end_at = time.time() + interval
            while time.time() < end_at:
                if msvcrt.kbhit():
                    key = msvcrt.getwch()
                    if key in ("\r", "\n"):
                        CONSOLE_LOG_MUTED = previous_mute
                        add_log("INFO", "ライブデータ表示終了 (Enter)")
                        return
                time.sleep(0.05)
    except KeyboardInterrupt:
        CONSOLE_LOG_MUTED = previous_mute
        add_log("WARN", "ライブデータ表示終了 (Ctrl+C)")
        return
    finally:
        CONSOLE_LOG_MUTED = previous_mute


def run_obd_diagnosis_flow(ser, cached_vin):
    if not ser:
        add_log("WARN", "先に OBD接続 を実行してください")
        return None

    add_log("INFO", "OBD診断実行開始")
    maker_hint = (vin_to_maker(cached_vin) if cached_vin else None) or ""
    codes = read_dtc(ser, maker_hint or "generic")
    if codes is None:
        add_log("WARN", "DTCが読めなかったため、OBD診断実行を中止します")
        print("DTCが取得できませんでした。接続状態を確認して再試行してください。")
        print("案内: DTCは読めてもVINや一部PIDは取れない、またはその逆の車種もあります。")
        return None
    if not codes:
        add_log("INFO", "DTCなしのため、OBD診断実行を見送ります")
        print("DTCなしのためOBD診断は実行しません。")
        return []
    add_log("INFO", f"使用DTC一覧: {', '.join(codes)}")
    print(f"DTC読取結果: {', '.join(codes)}")

    maker_prompt = (
        f"メーカー名を入力してください [候補: {maker_hint}]: "
        if maker_hint
        else "メーカー名を入力してください: "
    )
    maker_input = input(maker_prompt).strip()
    maker = maker_input if maker_input else maker_hint
    model = input("車種を入力してください: ").strip()
    year = input("年式を入力してください: ").strip()
    mileage = input("走行距離を入力してください: ").strip()
    symptom = input("症状を入力してください（未入力可）: ").strip()
    if not symptom:
        add_log("INFO", "症状未入力: 空入力のまま診断を実行")

    result = run_multi_diagnosis(
        maker=maker,
        model=model,
        year=year,
        mileage=mileage,
        dtc_codes=codes,
        symptom=symptom,
    )
    result["diagnosis_datetime"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    result["overall_reference_notes"] = build_overall_reference_notes(
        dtc_list=codes,
    )

    report_text = format_report(result)
    print("")
    print(report_text)
    saved_path = save_report_text(report_text, result, project_root=BASE_DIR)
    diagnosis_history_path = append_diagnosis_history_csv(result, project_root=BASE_DIR)
    if diagnosis_history_path:
        add_log("INFO", f"診断履歴CSV保存先: {diagnosis_history_path}")
    else:
        add_log("WARN", "diagnosis_history.csv への保存をスキップしました")
    vehicle_check_memo = input("実車確認メモを入力してください（任意）: ").strip()
    if vehicle_check_memo:
        add_log("INFO", "実車確認メモ入力あり")
    else:
        add_log("INFO", "実車確認メモ未入力")
    append_history_csv(
        diagnosis_datetime=result["diagnosis_datetime"],
        vin=cached_vin,
        maker=maker,
        model=model,
        year=year,
        mileage=mileage,
        dtc_codes=codes,
        symptom=symptom,
        overall_level=result.get("overall_level", "不明"),
        vehicle_check_memo=vehicle_check_memo,
    )
    add_log("INFO", "診断完了")
    add_log("INFO", f"総合緊急度: {result.get('overall_level', '不明')}")
    add_log("INFO", f"レポート保存先: {saved_path}")
    add_log("OK", f"診断結果を保存しました: {saved_path}")

    add_log("INFO", "DTC消去確認を表示")
    clear_confirm = input("DTCを消去しますか？ [y/N]: ").strip().lower()
    if clear_confirm == "y":
        add_log("INFO", "DTC消去実行")
        clear_dtc(ser)
        time.sleep(0.6)
        add_log("INFO", "DTC消去後再確認開始")
        post_codes = read_dtc(ser, maker or maker_hint or "generic")
        if post_codes is None:
            print("消去後DTC再取得失敗")
            add_log("WARN", "再確認結果: 取得失敗")
            return None
        if not post_codes:
            print("消去後DTCなし")
            add_log("INFO", "再確認結果: なし")
            return []
        else:
            print(f"まだDTCあり: {', '.join(post_codes)}")
            add_log("WARN", f"再確認結果: 残存あり ({', '.join(post_codes)})")
            return post_codes
    else:
        add_log("INFO", "DTC消去を見送りました")
        return codes


def print_current_status(ser, connected_port, connected_baud, cached_vin, last_dtc_codes):
    connected = "接続済み" if ser else "未接続"
    port_text = connected_port if connected_port else ("未接続" if not ser else "未取得")
    baud_text = str(connected_baud) if connected_baud else ("未接続" if not ser else "未取得")
    vin_info = classify_vin_text(cached_vin)
    profile = get_vehicle_profile(vin=cached_vin)
    if last_dtc_codes is None:
        dtc_text = "未取得"
    elif not last_dtc_codes:
        dtc_text = "なし"
    else:
        dtc_text = ", ".join(last_dtc_codes)

    print("=== 現在状態 ===")
    print(f"接続: {connected}")
    print(f"ポート: {port_text}")
    print(f"baud : {baud_text}")
    print(f"{vin_info['label']:<5}: {vin_info['value']}")
    if vin_info["note"]:
        print(f"補足 : {vin_info['note']}")
    print(f"DTC  : {dtc_text}")
    if profile:
        print(f"参考PF: {profile['title']}")
    print(f"整備士モード: {'ON' if MECHANIC_MODE else 'OFF'}")


def print_menu():
    print("")
    print("=== OBD2 CLI メニュー ===")
    print("1. OBD接続")
    print("2. 車両情報表示")
    print("3. VIN取得")
    print("4. DTC読取")
    print("5. DTC消去")
    print("6. 基本PID表示")
    print("7. ライブデータ表示")
    print("8. OBD診断実行")
    print("9. 終了")
    print("10. 古い車向け接続安定モード")
    print(f"11. 整備士モード ON/OFF (現在: {'ON' if MECHANIC_MODE else 'OFF'})")
    print("12. ライブCSV後解析")


def main():
    global LAST_CONNECT_REASON, MECHANIC_MODE
    print("OBD2 CLI ツール (軽量/安定重視)")
    print(f"Python {sys.version.split()[0]}")
    add_log("INFO", "セッション開始")
    add_log("INFO", f"起動日時: {SESSION_STARTED_AT.strftime('%Y-%m-%d %H:%M:%S')}")
    add_log("INFO", f"ログ保存先: {LOG_FILE}")

    ser = None
    connected_port = None
    connected_baud = None
    cached_vin = None
    last_dtc_codes = None

    try:
        while True:
            print_current_status(ser, connected_port, connected_baud, cached_vin, last_dtc_codes)
            print_menu()
            cmd = input("> ").strip()

            if cmd == "1":
                if ser:
                    add_log("INFO", "再接続確認を表示")
                    reconnect = input("すでに接続済みです。再接続しますか？ [y/N]: ").strip().lower()
                    if reconnect != "y":
                        add_log("INFO", "再接続を見送りました")
                        continue
                    add_log("INFO", "再接続を実行")
                    try:
                        ser.close()
                        add_log("INFO", "既存接続を閉じました")
                    except Exception as e:
                        add_log("WARN", f"既存接続のクローズで例外: {e}")
                    ser = None
                    connected_port = None
                    connected_baud = None
                    cached_vin = None
                    last_dtc_codes = None
                ser, connected_port, connected_baud = connect_obd_auto()
                if ser:
                    time.sleep(0.3)
                    add_log("OK", f"接続先: {connected_port} / {connected_baud}bps")
                    print_obd_scope_hint()
                else:
                    add_log("ERROR", f"接続失敗理由: {LAST_CONNECT_REASON}")
                    print_connection_failure_hint()

            elif cmd == "10":
                if ser:
                    add_log("INFO", "再接続確認を表示")
                    reconnect = input("すでに接続済みです。再接続しますか？ [y/N]: ").strip().lower()
                    if reconnect != "y":
                        add_log("INFO", "再接続を見送りました")
                        continue
                    add_log("INFO", "安定モード再接続を実行")
                    try:
                        ser.close()
                        add_log("INFO", "既存接続を閉じました")
                    except Exception as e:
                        add_log("WARN", f"既存接続のクローズで例外: {e}")
                    ser = None
                    connected_port = None
                    connected_baud = None
                    cached_vin = None
                    last_dtc_codes = None
                ser, connected_port, connected_baud = connect_obd_stable_mode()
                if ser:
                    time.sleep(0.3)
                    add_log("OK", f"接続先: {connected_port} / {connected_baud}bps")
                    print_obd_scope_hint()
                else:
                    add_log("ERROR", f"接続失敗理由: {LAST_CONNECT_REASON}")
                    print_connection_failure_hint()

            elif cmd == "2":
                show_vehicle_info(cached_vin)

            elif cmd == "3":
                if not ser:
                    add_log("WARN", "先に OBD接続 を実行してください")
                    continue
                cached_vin = read_vin_stable(ser)
                if cached_vin:
                    vin_info = classify_vin_text(cached_vin)
                    if vin_info["is_full_vin"]:
                        add_log("OK", f"VIN取得成功: {cached_vin}")
                    else:
                        add_log("OK", f"VIN候補取得: {cached_vin}")
                    show_vehicle_info(cached_vin)
                else:
                    add_log("WARN", "VIN取得失敗")
                    print("VINを取得できませんでした。DTC読取や基本PID表示を先に試してください。")
                    print("案内: 外車ではVINだけ取得できない場合があります。")

            elif cmd == "4":
                if not ser:
                    add_log("WARN", "先に OBD接続 を実行してください")
                    continue
                maker = (vin_to_maker(cached_vin) if cached_vin else None) or "generic"
                codes = read_dtc(ser, maker)
                last_dtc_codes = codes
                if codes is None:
                    print("DTC: 未取得")
                    print("案内: ECU応答が限定的な場合でも、別項目は取得できることがあります。")
                elif not codes:
                    print("DTC: なし")

            elif cmd == "5":
                if not ser:
                    add_log("WARN", "先に OBD接続 を実行してください")
                    continue
                clear_dtc(ser)

            elif cmd == "6":
                if not ser:
                    add_log("WARN", "先に OBD接続 を実行してください")
                    continue
                add_log("INFO", "基本PID表示を実行")
                if MECHANIC_MODE:
                    add_log("INFO", "整備士モード詳細画面を表示")
                    print("整備士モード詳細画面を開きます。Enter / Ctrl+C でメニューへ戻ります。")
                    print_mechanic_pid_screen(ser, connected_port, connected_baud, cached_vin, last_dtc_codes)
                else:
                    pid = read_basic_pid(ser)
                    print(f"RPM        : {pid['RPM'] if pid['RPM'] is not None else 'N/A'}")
                    print(f"ECT        : {pid['ECT'] if pid['ECT'] is not None else 'N/A'}")
                    print(f"MAF        : {pid['MAF'] if pid['MAF'] is not None else 'N/A'}")
                    print(f"SPEED      : {pid['SPEED'] if pid['SPEED'] is not None else 'N/A'}")
                    print(f"IAT        : {pid['IAT'] if pid['IAT'] is not None else 'N/A'}")
                    print(f"THROTTLE   : {pid['THROTTLE'] if pid['THROTTLE'] is not None else 'N/A'}")
                    print_pid_availability_hint(pid)
                    add_log("INFO", "センサー簡易診断を表示")
                    print_pid_comment_block(pid, last_dtc_codes)

            elif cmd == "7":
                if not ser:
                    add_log("WARN", "先に OBD接続 を実行してください")
                    continue
                if MECHANIC_MODE:
                    add_log("INFO", "整備士モードライブ詳細画面を表示")
                    print("整備士モードのライブ詳細画面を開始します。Enter / Ctrl+C で終了します。")
                    display_mode = "fixed"
                else:
                    display_mode = input("ライブ表示モード [F=固定 / l=従来ログ] : ").strip().lower()
                live_basic_pid_mode(
                    ser,
                    interval=1.0,
                    display_mode="log" if display_mode == "l" else "fixed",
                    mechanic_detail=MECHANIC_MODE,
                    connected_port=connected_port,
                    connected_baud=connected_baud,
                    cached_vin=cached_vin,
                    last_dtc_codes=last_dtc_codes,
                )

            elif cmd == "8":
                if not ser:
                    add_log("WARN", "先に OBD接続 を実行してください")
                    continue
                diag_codes = run_obd_diagnosis_flow(ser, cached_vin)
                if diag_codes is not None:
                    last_dtc_codes = diag_codes

            elif cmd == "11":
                MECHANIC_MODE = not MECHANIC_MODE
                add_log("INFO", f"整備士モード {'ON' if MECHANIC_MODE else 'OFF'}")
                print(f"整備士モードを {'ON' if MECHANIC_MODE else 'OFF'} にしました。")

            elif cmd == "12":
                latest_csv = choose_latest_live_csv()
                if not latest_csv:
                    print("ライブCSVが見つかりませんでした。先にライブデータ表示を実行してください。")
                    continue
                try:
                    summary = analyze_live_csv(latest_csv)
                    print_live_csv_analysis(summary)
                except Exception as e:
                    add_log("WARN", f"ライブCSV後解析に失敗: {e}")
                    print("ライブCSVの解析に失敗しました。CSV形式を確認してください。")
                    continue
                input("Enterでメニューへ戻る")

            elif cmd == "9":
                add_log("INFO", "終了します")
                break

            else:
                print("不正な入力です。1〜12を選択してください。")
    except KeyboardInterrupt:
        LAST_CONNECT_REASON = "ユーザー中断"
        add_log("WARN", "ユーザー操作で終了します")

    if ser:
        try:
            ser.close()
        except Exception:
            pass


if __name__ == "__main__":
    main()
