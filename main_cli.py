import json
import os
import sys
import time
import csv
import re
from datetime import datetime
import msvcrt

import serial
from serial.tools import list_ports

from diagnosis import run_multi_diagnosis
from report import format_report, save_report_text

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


def vin_to_maker(vin):
    if not vin:
        return None
    vin = vin.strip().upper()
    if len(vin) < 3:
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


def read_basic_pid(ser):
    values = {
        "RPM": None,
        "ECT": None,
        "MAF": None,
        "SPEED": None,
        "IAT": None,
        "THROTTLE": None,
    }

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
        parsed = parse_after_header(raw_value, header, count)
        if parsed is not None:
            try:
                values[key] = decoder(parsed)
            except Exception:
                values[key] = None

    return values


def build_pid_comment_lines(pid):
    lines = []

    speed = pid.get("SPEED")
    if speed is not None:
        if speed == 0:
            lines.append("停車中のため車速は 0km/h です")
        elif speed >= 1:
            lines.append("走行中のため車速が出ています")

    ect = pid.get("ECT")
    if ect is not None:
        if ect <= 49:
            lines.append("水温は低めで暖機途中の可能性があります")
        elif ect <= 89:
            lines.append("水温は実用範囲です")
        else:
            lines.append("水温は高めです。冷却系も確認してください")

    rpm = pid.get("RPM")
    if rpm is not None:
        if rpm == 0:
            lines.append("エンジン停止または取得異常の可能性があります")
        elif rpm <= 900:
            lines.append("回転数はアイドル付近です")
        elif rpm <= 1500:
            lines.append("回転数はやや高めです")
        else:
            lines.append("回転数は高めです")

    maf = pid.get("MAF")
    if maf is None:
        lines.append("吸入空気量は未取得です")
    elif maf <= 2:
        lines.append("吸入空気量は少なめです")
    elif maf <= 10:
        lines.append("吸入空気量は大きな違和感はありません")
    else:
        lines.append("吸入空気量はやや多めです")

    throttle = pid.get("THROTTLE")
    if throttle is not None:
        if throttle <= 5:
            lines.append("スロットルはほぼ閉じています")
        elif throttle <= 25:
            lines.append("スロットルは軽く開いています")
        else:
            lines.append("スロットル開度はやや大きめです")

    iat = pid.get("IAT")
    if iat is not None:
        lines.append(f"吸気温の目安は {iat}°C です")

    return lines


def print_pid_comment_block(pid):
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
    if not vin:
        print("車両情報: VIN未取得")
        print("案内: VINは汎用OBD2で取得できない車種もあります。")
        return
    maker = vin_to_maker(vin) or "generic"
    engine = detect_engine_type(vin, maker)
    print(f"VIN    : {vin}")
    print(f"メーカー: {maker.upper()}")
    print(f"エンジン: {engine}")


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
    print_dtc_knowledge_block(codes)
    return codes


def clear_dtc(ser):
    data = safe_send(ser, "04", wait=0.5, retries=1, clear_buffer=True)
    if data:
        add_log("INFO", "DTC消去コマンド送信完了")
    else:
        add_log("WARN", "DTC消去 応答なし")


def live_basic_pid_mode(ser, interval=1.0, display_mode="fixed"):
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
            if display_mode == "fixed":
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

    report_text = format_report(result)
    print("")
    print(report_text)
    saved_path = save_report_text(report_text, result, project_root=BASE_DIR)
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
    vin_text = cached_vin if cached_vin else "未取得"
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
    print(f"VIN  : {vin_text}")
    print(f"DTC  : {dtc_text}")


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


def main():
    global LAST_CONNECT_REASON
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
                    add_log("OK", f"VIN取得成功: {cached_vin}")
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
                pid = read_basic_pid(ser)
                print(f"RPM        : {pid['RPM'] if pid['RPM'] is not None else 'N/A'}")
                print(f"ECT        : {pid['ECT'] if pid['ECT'] is not None else 'N/A'}")
                print(f"MAF        : {pid['MAF'] if pid['MAF'] is not None else 'N/A'}")
                print(f"SPEED      : {pid['SPEED'] if pid['SPEED'] is not None else 'N/A'}")
                print(f"IAT        : {pid['IAT'] if pid['IAT'] is not None else 'N/A'}")
                print(f"THROTTLE   : {pid['THROTTLE'] if pid['THROTTLE'] is not None else 'N/A'}")
                print_pid_availability_hint(pid)
                add_log("INFO", "センサー簡易診断を表示")
                print_pid_comment_block(pid)

            elif cmd == "7":
                if not ser:
                    add_log("WARN", "先に OBD接続 を実行してください")
                    continue
                display_mode = input("ライブ表示モード [F=固定 / l=従来ログ] : ").strip().lower()
                live_basic_pid_mode(ser, interval=1.0, display_mode="log" if display_mode == "l" else "fixed")

            elif cmd == "8":
                if not ser:
                    add_log("WARN", "先に OBD接続 を実行してください")
                    continue
                diag_codes = run_obd_diagnosis_flow(ser, cached_vin)
                if diag_codes is not None:
                    last_dtc_codes = diag_codes

            elif cmd == "9":
                add_log("INFO", "終了します")
                break

            else:
                print("不正な入力です。1〜10を選択してください。")
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
