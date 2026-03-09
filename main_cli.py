import json
import os
import sys
import time
import csv
from datetime import datetime
import msvcrt

import serial
from serial.tools import list_ports

from diagnosis import run_multi_diagnosis
from report import format_report, save_report_text

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_DIR = os.path.join(BASE_DIR, "logs")
os.makedirs(LOG_DIR, exist_ok=True)
SESSION_STARTED_AT = datetime.now()
SESSION_ID = SESSION_STARTED_AT.strftime("%Y%m%d_%H%M%S")
LOG_FILE = os.path.join(LOG_DIR, f"session_{SESSION_ID}.log")

DEFAULT_PORTS = ["COM15", "COM3", "COM4", "COM5"]
BAUD_LIST = [115200, 38400, 9600]
LAST_CONNECT_REASON = "未実行"
DEBUG = True


def add_log(level, message):
    if level == "DEBUG" and not DEBUG:
        return
    line = f"[{level}] {message}"
    print(line)
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


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
    memo="",
):
    history_file = os.path.join(LOG_DIR, "history.csv")
    file_exists = os.path.exists(history_file)

    with open(history_file, "a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        if not file_exists:
            writer.writerow(
                ["日時", "VIN", "メーカー", "車種", "年式", "走行距離", "DTC一覧", "症状", "総合緊急度", "memo"]
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
                memo or "",
            ]
        )


WMI_TO_MAKER = load_json("wmi_map.json", {})
VDS_TO_ENGINE = load_json("vds_map.json", {})
DTC_DB = load_json("dtc_database.json", {})


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

    for line in data.replace("\r", "\n").split("\n"):
        line = line.strip()
        if not line.startswith("43"):
            continue
        parts = [p for p in line.split(" ") if p]
        if len(parts) < 2:
            continue
        for p in parts[1:]:
            if len(p) == 4 and all(c in "0123456789ABCDEFabcdef" for c in p):
                dtc = to_dtc(p.upper())
                if dtc and dtc not in seen:
                    seen.add(dtc)
                    codes.append(dtc)
    return codes


def dtc_desc(code, maker):
    maker = (maker or "generic").lower()
    info = DTC_DB.get(code)
    if not info:
        return f"{code}: 説明なし"
    if maker in info:
        return f"{code}: {info[maker]}"
    if "generic" in info:
        return f"{code}: {info['generic']}"
    return f"{code}: 説明なし"


def read_vin_stable(ser):
    def parse_vin_from_49_02(raw):
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

        vin_chars = []
        for key in sorted(frame_data.keys()):
            for b in frame_data[key]:
                try:
                    vin_chars.append(chr(int(b, 16)))
                except Exception:
                    pass

        vin = "".join(vin_chars).strip()
        vin = "".join(ch for ch in vin if ch.isalnum())
        if len(vin) >= 17:
            return vin[:17]

        vin_chars = []
        for b in fallback_bytes:
            try:
                vin_chars.append(chr(int(b, 16)))
            except Exception:
                pass
        vin2 = "".join(vin_chars).strip()
        vin2 = "".join(ch for ch in vin2 if ch.isalnum())
        if len(vin2) >= 17:
            return vin2[:17]
        if len(vin2) >= 10:
            return vin2
        return None

    for _ in range(3):
        data = safe_send(ser, "0902", wait=0.35, retries=1, clear_buffer=True)
        if "49 02" not in data:
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
        if header not in data:
            return None
        try:
            parts = data.split(header, 1)[1].strip().split(" ")
            if len(parts) < count:
                return None
            return [int(parts[i], 16) for i in range(count)]
        except Exception:
            return None

    d_rpm = safe_send(ser, "010C", wait=0.2, retries=1, clear_buffer=True)
    p = parse_after_header(d_rpm, "41 0C", 2)
    if p:
        values["RPM"] = ((p[0] * 256) + p[1]) / 4

    d_ect = safe_send(ser, "0105", wait=0.2, retries=1, clear_buffer=True)
    p = parse_after_header(d_ect, "41 05", 1)
    if p:
        values["ECT"] = p[0] - 40

    d_maf = safe_send(ser, "0110", wait=0.2, retries=1, clear_buffer=True)
    p = parse_after_header(d_maf, "41 10", 2)
    if p:
        values["MAF"] = ((p[0] * 256) + p[1]) / 100

    d_speed = safe_send(ser, "010D", wait=0.2, retries=1, clear_buffer=True)
    p = parse_after_header(d_speed, "41 0D", 1)
    if p:
        values["SPEED"] = p[0]

    d_iat = safe_send(ser, "010F", wait=0.2, retries=1, clear_buffer=True)
    p = parse_after_header(d_iat, "41 0F", 1)
    if p:
        values["IAT"] = p[0] - 40

    d_throttle = safe_send(ser, "0111", wait=0.2, retries=1, clear_buffer=True)
    p = parse_after_header(d_throttle, "41 11", 1)
    if p:
        values["THROTTLE"] = round((p[0] * 100) / 255, 1)

    return values


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


def connect_obd_auto(possible_ports=None):
    global LAST_CONNECT_REASON

    def classify_0100(data):
        data_u = (data or "").upper()
        if not data_u.strip():
            return "timeout", "タイムアウト（ECUから応答がありません）"
        if "UNABLE TO CONNECT" in data_u:
            return "unable_to_connect", "UNABLE TO CONNECT（ECUと通信確立できません）"
        if "NO DATA" in data_u:
            return "no_data", "NO DATA（ECUから応答がありません）"
        if "BUS INIT" in data_u:
            return "bus_init", "BUS INIT...（通信初期化中のまま応答なし）"
        if "SEARCHING" in data_u and "41 00" not in data_u:
            return "searching", "SEARCHING...（プロトコル探索中で応答なし）"
        if "OK" in data_u and "41 00" not in data_u:
            return "adapter_only", "アダプタ応答のみで ECU応答なし（0100 -> OK）"
        if "41 00" in data_u:
            return "ok", "ECU応答あり"
        return "unknown", "ATコマンドは通るが ECU応答なし"

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
        for baud in BAUD_LIST:
            add_log("INFO", f"{port} を試行中... ({baud}bps)")
            ser = None
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

                check = safe_send(ser, "0100", wait=0.6, retries=1, clear_buffer=True)
                reason_code, reason_text = classify_0100(check)
                check_u = check.upper()
                add_log("CHECK", f"0100応答: {normalize_hex(check)[:140] if check else '(empty)'}")

                if "41 00" in check_u and "UNABLE TO CONNECT" not in check_u:
                    LAST_CONNECT_REASON = "接続成功"
                    add_log("OK", f"ECU接続成功: {port} / {baud}bps")
                    return ser, port, baud

                add_log("WARN", f"0100初回判定[{reason_code}]: {reason_text}")
                add_log("WARN", "接続確認失敗。再初期化を1回実施")

                init_adapter(ser)
                proto2 = safe_send(ser, "ATDP", wait=0.3, retries=0, clear_buffer=False)
                if proto2:
                    add_log("INFO", f"再初期化後プロトコル: {normalize_hex(proto2)[:120]}")

                check2 = safe_send(ser, "0100", wait=0.6, retries=1, clear_buffer=True)
                reason2_code, reason2_text = classify_0100(check2)
                check2_u = check2.upper()
                add_log("CHECK", f"0100再試行応答: {normalize_hex(check2)[:140] if check2 else '(empty)'}")

                if "41 00" in check2_u and "UNABLE TO CONNECT" not in check2_u:
                    LAST_CONNECT_REASON = "接続成功(再試行)"
                    add_log("OK", f"ECU接続成功(再試行): {port} / {baud}bps")
                    return ser, port, baud

                LAST_CONNECT_REASON = reason2_text
                add_log("WARN", f"接続失敗理由[{reason2_code}]: {reason2_text}")

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

    if LAST_CONNECT_REASON in ("接続試行中", "不明"):
        LAST_CONNECT_REASON = "アダプタ応答なし"
    add_log("ERROR", f"接続失敗: {LAST_CONNECT_REASON}")
    return None, None, None


def show_vehicle_info(vin):
    if not vin:
        print("車両情報: VIN未取得")
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
        return []
    codes = parse_dtc_from_43(data)
    if not codes:
        add_log("INFO", "DTCなし")
        return []
    add_log("INFO", f"DTC {len(codes)}件検出")
    for c in codes:
        print(" -", dtc_desc(c, maker))
    return codes


def clear_dtc(ser):
    data = safe_send(ser, "04", wait=0.5, retries=1, clear_buffer=True)
    if data:
        add_log("INFO", "DTC消去コマンド送信完了")
    else:
        add_log("WARN", "DTC消去 応答なし")


def live_basic_pid_mode(ser, interval=1.0):
    save_csv = input("ライブデータをCSV保存しますか？ [y/N]: ").strip().lower() == "y"
    live_csv_file = None
    if save_csv:
        live_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        live_csv_file = os.path.join(LOG_DIR, f"live_{live_id}.csv")
        with open(live_csv_file, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["timestamp", "rpm", "ect", "maf", "speed", "iat", "throttle"])
        add_log("INFO", f"ライブCSV保存先: {live_csv_file}")

    print("ライブデータ表示を開始します。Enter または Ctrl+C で終了します。")
    add_log("INFO", "ライブデータ表示開始")
    try:
        while True:
            pid = read_basic_pid(ser)
            now = datetime.now().strftime("%H:%M:%S")
            if live_csv_file:
                with open(live_csv_file, "a", newline="", encoding="utf-8") as f:
                    writer = csv.writer(f)
                    writer.writerow(
                        [
                            now,
                            pid["RPM"],
                            pid["ECT"],
                            pid["MAF"],
                            pid["SPEED"],
                            pid["IAT"],
                            pid["THROTTLE"],
                        ]
                    )
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
                        add_log("INFO", "ライブデータ表示終了 (Enter)")
                        return
                time.sleep(0.05)
    except KeyboardInterrupt:
        add_log("WARN", "ライブデータ表示終了 (Ctrl+C)")
        return


def run_obd_diagnosis_flow(ser, cached_vin):
    if not ser:
        add_log("WARN", "先に OBD接続 を実行してください")
        return None

    add_log("INFO", "OBD診断実行開始")
    maker_hint = (vin_to_maker(cached_vin) if cached_vin else None) or ""
    codes = read_dtc(ser, maker_hint or "generic")
    if not codes:
        add_log("WARN", "DTCが読めなかったため、OBD診断実行を中止します")
        print("DTCが取得できませんでした。接続状態を確認して再試行してください。")
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
    memo = input("補足メモを入力してください（未入力可）: ").strip()
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
        memo=memo,
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


def main():
    global LAST_CONNECT_REASON
    print("OBD2 CLI ツール (軽量/安定重視)")
    print(f"Python {sys.version.split()[0]}")
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
                else:
                    add_log("ERROR", f"接続失敗理由: {LAST_CONNECT_REASON}")

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

            elif cmd == "4":
                if not ser:
                    add_log("WARN", "先に OBD接続 を実行してください")
                    continue
                maker = (vin_to_maker(cached_vin) if cached_vin else None) or "generic"
                codes = read_dtc(ser, maker)
                last_dtc_codes = codes
                if not codes:
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
                pid = read_basic_pid(ser)
                print(f"RPM        : {pid['RPM'] if pid['RPM'] is not None else 'N/A'}")
                print(f"ECT        : {pid['ECT'] if pid['ECT'] is not None else 'N/A'}")
                print(f"MAF        : {pid['MAF'] if pid['MAF'] is not None else 'N/A'}")
                print(f"SPEED      : {pid['SPEED'] if pid['SPEED'] is not None else 'N/A'}")
                print(f"IAT        : {pid['IAT'] if pid['IAT'] is not None else 'N/A'}")
                print(f"THROTTLE   : {pid['THROTTLE'] if pid['THROTTLE'] is not None else 'N/A'}")

            elif cmd == "7":
                if not ser:
                    add_log("WARN", "先に OBD接続 を実行してください")
                    continue
                live_basic_pid_mode(ser, interval=1.0)

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
                print("不正な入力です。1〜9を選択してください。")
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
