# ============================================================
# main.py（JOBD 完全削除版・OBD2 専用・安定版・メーカー判定統一版）
# ============================================================

import sys
import traceback
import json
import tkinter as tk
from tkinter import ttk, messagebox
import serial
import time
import os
import csv
import threading
from datetime import datetime

# ------------------------------------------------------------
# グローバル例外ハンドラ
# ------------------------------------------------------------
def global_exception_handler(exc_type, exc_value, exc_traceback):
    try:
        add_log(f"[GLOBAL ERROR] {exc_value}")
    except:
        print(f"[GLOBAL ERROR] {exc_value}")

sys.excepthook = global_exception_handler

# ------------------------------------------------------------
# 基本設定
# ------------------------------------------------------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

# ------------------------------------------------------------
# 外部データ
# ------------------------------------------------------------
WMI_TO_MAKER  = load_json("wmi_map.json")
VDS_TO_ENGINE = load_json("vds_map.json")
PID_NORMAL    = load_json("pid_normal.json")
DTC_DB        = load_json("dtc_database.json")

ser = None  # OBD シリアル保持

# ------------------------------------------------------------
# 自動学習用
# ------------------------------------------------------------
learning_enabled = False
learning_buffer = {
    "RPM": [],
    "ECT": [],
    "MAF": []
}

# ============================================================
# VIN → メーカー判定（統一版）
# ============================================================
def vin_to_maker(vin: str, wmi_map: dict) -> str | None:
    if not vin:
        return None

    vin = vin.strip().upper()

    if len(vin) < 3:
        return None

    for ch in ("I", "O", "Q"):
        if ch in vin:
            return None

    wmi3 = vin[:3]
    if wmi3 in wmi_map:
        return wmi_map[wmi3]

    wmi2 = vin[:2]
    if wmi2 in wmi_map:
        return wmi_map[wmi2]

    return None

# ============================================================
# VIN → エンジン型式判定
# ============================================================
def detect_engine_type(vin: str, maker: str | None) -> str | None:
    if not vin or not maker:
        return None

    vin = vin.strip().upper()
    maker = maker.lower()

    if len(vin) < 9:
        return None

    vds = vin[3:9]

    if maker not in VDS_TO_ENGINE:
        return None

    maker_map = VDS_TO_ENGINE[maker]

    if vds in maker_map:
        return maker_map[vds]

    for key in maker_map:
        if len(key) == 5 and vds.startswith(key):
            return maker_map[key]

    for key in maker_map:
        if len(key) == 4 and vds.startswith(key):
            return maker_map[key]

    for key in maker_map:
        if len(key) == 3 and vds.startswith(key):
            return maker_map[key]

    return "UNKNOWN"

# ============================================================
# DTC 用
# ============================================================
def detect_manufacturer(vin: str) -> str:
    maker = vin_to_maker(vin, WMI_TO_MAKER)
    return maker.lower() if maker else "generic"

def get_dtc_description_auto(code: str, maker: str) -> str:
    maker = maker.lower()

    if code not in DTC_DB:
        return f"{code}: 未登録のDTCコードです。"

    info = DTC_DB[code]

    if maker in info:
        return info[maker]

    if "generic" in info:
        return info["generic"]

    return f"{code}: 説明が登録されていません。"

# ============================================================
# ★ OBD2 安定送信（完全版）
# ============================================================
def safe_send(ser, command, wait=0.3):
    try:
        if command.strip().upper() == b"ATZ":
            wait = 1.0

        ser.write(command)
        time.sleep(wait)

        raw1 = ser.read(256).decode(errors="ignore")

        time.sleep(0.1)
        raw2 = ser.read(256).decode(errors="ignore")

        data = raw1 + raw2

        add_log(f"[DEBUG] safe_send response: {data}")

        if "BUS INIT" in data or "SEARCHING" in data:
            time.sleep(0.5)
            return ""

        if not data.strip():
            return ""

        return data

    except Exception as e:
        add_log(f"[SEND ERROR] {e}")
        return ""

def send_obd(cmd):
    global ser
    try:
        if ser:
            ser.write(cmd.encode())
            add_log(f"ECU ← {cmd.strip()}")
    except Exception as e:
        add_log(f"[SEND ERROR] {e}")

# ============================================================
# 標準 OBD2 PID 読み取り
# ============================================================
def read_rpm(ser):
    data = safe_send(ser, b"010C\r")
    if "41 0C" in data:
        try:
            parts = data.split("41 0C")[1].strip().split(" ")
            if len(parts) >= 2:
                A = int(parts[0], 16)
                B = int(parts[1], 16)
                return ((A * 256) + B) / 4
        except:
            return None
    return None

def read_ect(ser):
    data = safe_send(ser, b"0105\r")
    if "41 05" in data:
        try:
            parts = data.split("41 05")[1].strip().split(" ")
            if len(parts) >= 1:
                A = int(parts[0], 16)
                return A - 40
        except:
            return None
    return None

def read_maf(ser):
    data = safe_send(ser, b"0110\r")
    if "41 10" in data:
        try:
            parts = data.split("41 10")[1].strip().split(" ")
            if len(parts) >= 2:
                A = int(parts[0], 16)
                B = int(parts[1], 16)
                return ((A * 256) + B) / 100
        except:
            return None
    return None

# ============================================================
# VIN 読み取り
# ============================================================
def read_vin_stable(ser):
    try:
        ser.reset_input_buffer()
        ser.reset_output_buffer()
        ser.timeout = 1.0

        ser.write(b"0902\r")
        time.sleep(0.2)

        raw = ser.read(256)
        if not raw:
            return None

        data = raw.decode(errors="ignore")

        if "49 02" not in data:
            return None

        vin_chars = []
        lines = data.split("\r")
        for line in lines:
            if "49 02" in line:
                parts = line.strip().split(" ")
                for p in parts[3:]:
                    try:
                        vin_chars.append(chr(int(p, 16)))
                    except:
                        pass

        vin = "".join(vin_chars).strip()
        return vin if len(vin) >= 10 else None

    except Exception as e:
        add_log(f"[ERROR] read_vin: {e}")
        return None

# ============================================================
# ログ出力
# ============================================================
def add_log(message):
    timestamp = datetime.now().strftime("[%H:%M:%S] ")
    log_line = timestamp + message + "\n"

    try:
        log_text.after(0, lambda: log_text.insert(tk.END, log_line))
        log_text.after(0, lambda: log_text.see(tk.END))
        log_text.after(0, lambda: log_text.update_idletasks())
    except:
        print(log_line, end="")

    try:
        with open("diagnostic_log.txt", "a", encoding="utf-8") as f:
            f.write(log_line)
    except:
        pass

# ============================================================
# OBD 接続処理
# ============================================================
def open_with_timeout(port, baud, timeout=1):
    try:
        ser = serial.Serial(port, baudrate=baud, timeout=timeout)
        return ser, None
    except Exception as e:
        return None, e

def connect_obd_auto():
    add_log("=== OBD 自動接続開始 ===")

    possible_ports = ["COM15"]
    baud_list = [115200, 38400, 9600]

    for port in possible_ports:
        for baud in baud_list:
            add_log(f"試行中：{port} / {baud}bps")

            ser, err = open_with_timeout(port, baud, timeout=1)
            if err:
                add_log(f"OPEN ERROR: {err}")
                continue

            if ser is None:
                add_log("OPEN TIMEOUT")
                continue

            try:
                response = safe_send(ser, b"ATZ\r")

                if "ELM" in response or "OK" in response:
                    add_log(f"接続成功：{port} / {baud}bps")
                    send_obd("0902")
                    obd_port_label.config(text=f"OBD ポート：{port} ({baud}bps)")
                    obd_status_label.config(text="OBD 状態：接続中", fg="green")
                    return ser
            except Exception as e:
                add_log(f"ERROR: {e}")

            ser.close()

    add_log("接続失敗：対応ポートなし")
    obd_port_label.config(text="OBD ポート：見つかりません")
    obd_status_label.config(text="OBD 状態：未接続", fg="red")
    return None

# ============================================================
# OBD 接続スレッド
# ============================================================
def connect_obd_thread():
    global ser
    try:
        ser = connect_obd_auto()

        if ser:
            threading.Thread(target=vin_read_thread, daemon=True).start()

    except Exception as e:
        add_log(f"[ERROR] connect_obd_thread: {e}")

# ============================================================
# VIN 読み取りスレッド（メーカー判定統一版）
# ============================================================
def vin_read_thread():
    try:
        for _ in range(5):
            vin_obd = read_vin_stable(ser)
            if vin_obd:
                vin_entry.delete(0, tk.END)
                vin_entry.insert(0, vin_obd)

                maker = vin_to_maker(vin_obd, WMI_TO_MAKER)
                maker_label.config(text=f"メーカー：{(maker or 'generic').upper()}")

                update_vin_info(vin_obd)
                vin_status_label.config(text="VIN 自動取得：成功", fg="green")
                return

            time.sleep(0.2)

        vin_status_label.config(text="VIN 自動取得：未対応車種", fg="red")

    except Exception as e:
        add_log(f"[ERROR] vin_read_thread: {e}")

# ============================================================
# PID 更新ループ
# ============================================================
def update_obd():
    try:
        if ser:
            rpm = read_rpm(ser)
            ect = read_ect(ser)
            maf = read_maf(ser)

            if rpm is not None:
                rpm_value_label.config(text=f"RPM：{rpm:.0f}")
            if ect is not None:
                ect_value_label.config(text=f"ECT：{ect:.0f}")
            if maf is not None:
                maf_value_label.config(text=f"MAF：{maf:.2f}")

            if learning_enabled:
                if rpm is not None:
                    learning_buffer["RPM"].append(rpm)
                if ect is not None:
                    learning_buffer["ECT"].append(ect)
                if maf is not None:
                    learning_buffer["MAF"].append(maf)

                for key in learning_buffer:
                    if len(learning_buffer[key]) > 300:
                        learning_buffer[key] = learning_buffer[key][-300:]

    except Exception as e:
        add_log(f"[ERROR] update_obd: {e}")

    root.after(1000, update_obd)

# ============================================================
# 自動学習ループ
# ============================================================
def auto_learn_pid_normal():
    try:
        if not learning_enabled:
            root.after(10000, auto_learn_pid_normal)
            return

        vin = vin_entry.get().strip().upper()
        maker = vin_to_maker(vin, WMI_TO_MAKER)
        engine = detect_engine_type(vin, maker)

        if not maker or not engine:
            root.after(10000, auto_learn_pid_normal)
            return

        if len(learning_buffer["RPM"]) < 30:
            root.after(10000, auto_learn_pid_normal)
            return

        avg_rpm = sum(learning_buffer["RPM"]) / len(learning_buffer["RPM"])
        avg_ect = sum(learning_buffer["ECT"]) / len(learning_buffer["ECT"])
        avg_maf = sum(learning_buffer["MAF"]) / len(learning_buffer["MAF"])

        new_normal = {
            "RPM": [int(avg_rpm * 0.9), int(avg_rpm * 1.1)],
            "ECT": [int(avg_ect * 0.9), int(avg_ect * 1.1)],
            "MAF": [round(avg_maf * 0.9, 2), round(avg_maf * 1.1, 2)]
        }

        if maker not in PID_NORMAL:
            PID_NORMAL[maker] = {}
        PID_NORMAL[maker][engine] = new_normal

        with open("pid_normal.json", "w", encoding="utf-8") as f:
            json.dump(PID_NORMAL, f, indent=4, ensure_ascii=False)

        add_log(f"[学習] {maker}/{engine} の正常値を更新：{new_normal}")

        for key in learning_buffer:
            learning_buffer[key].clear()

    except Exception as e:
        add_log(f"[ERROR] auto_learn_pid_normal: {e}")

    root.after(10000, auto_learn_pid_normal)

# ============================================================
# DTC 読み取り・クリア
# ============================================================
def read_dtc_codes(ser):
    try:
        data = safe_send(ser, b"03\r", wait=0.5)
        if not data:
            return []

        lines = data.replace("\r", "\n").split("\n")
        codes = []
        for line in lines:
            line = line.strip()
            if not line or not line.startswith("43"):
                continue
            parts = line.split(" ")
            for p in parts[1:]:
                if len(p) == 4:
                    codes.append(p.upper())
        return codes
    except Exception as e:
        add_log(f"[ERROR] read_dtc_codes: {e}")
        return []

def show_dtc():
    if not ser:
        messagebox.showerror("エラー", "OBD が未接続です")
        return

    vin = vin_entry.get().strip().upper()
    maker = detect_manufacturer(vin) if vin else "generic"

    codes = read_dtc_codes(ser)
    if not codes:
        dtc_label.config(text="DTC：なし")
        add_log("DTC なし")
        return

    lines = []
    for c in codes:
        desc = get_dtc_description_auto(c, maker)
        lines.append(desc)

    dtc_label.config(text=f"DTC：{len(codes)}件")
    msg = "\n".join(lines)
    messagebox.showinfo("DTC 一覧", msg)
    add_log(f"DTC 読み取り：{codes}")

def clear_dtc_action():
    if not ser:
        messagebox.showerror("エラー", "OBD が未接続です")
        return

    if not messagebox.askyesno("確認", "DTC を消去しますか？"):
        return

    try:
        _ = safe_send(ser, b"04\r", wait=0.5)
        add_log("DTC 消去コマンド送信")
        dtc_label.config(text="DTC：未取得")
    except Exception as e:
        add_log(f"[ERROR] clear_dtc_action: {e}")

# ============================================================
# PID_NORMAL / VDS 編集 GUI
# ============================================================
def open_pid_editor():
    win = tk.Toplevel()
    win.title("PID_NORMAL 編集")
    win.geometry("500x400")

    text = tk.Text(win, font=("Consolas", 10))
    text.pack(fill="both", expand=True)

    text.insert("1.0", json.dumps(PID_NORMAL, indent=4, ensure_ascii=False))

    def save_pid():
        try:
            data = text.get("1.0", tk.END).strip()
            obj = json.loads(data)
            with open("pid_normal.json", "w", encoding="utf-8") as f:
                json.dump(obj, f, indent=4, ensure_ascii=False)
            global PID_NORMAL
            PID_NORMAL = obj
            messagebox.showinfo("保存完了", "pid_normal.json を更新しました")
        except Exception as e:
            add_log(f"[ERROR] save_pid: {e}")
            messagebox.showerror("エラー", f"保存に失敗しました：{e}")

    tk.Button(win, text="保存", command=save_pid).pack(pady=5)

def open_engine_add_gui():
    win = tk.Toplevel()
    win.title("エンジン型式追加")
    win.geometry("400x250")

    tk.Label(win, text="メーカー（例：suzuki, toyota）").pack()
    maker_var = tk.StringVar()
    tk.Entry(win, textvariable=maker_var).pack()

    tk.Label(win, text="エンジン型式（例：R06A_NA）").pack()
    engine_var = tk.StringVar()
    tk.Entry(win, textvariable=engine_var).pack()

    tk.Label(win, text="RPM 正常範囲（例：600,900）").pack()
    rpm_var = tk.StringVar()
    tk.Entry(win, textvariable=rpm_var).pack()

    tk.Label(win, text="ECT 正常範囲（例：80,95）").pack()
    ect_var = tk.StringVar()
    tk.Entry(win, textvariable=ect_var).pack()

    tk.Label(win, text="MAF 正常範囲（例：2.0,4.5）").pack()
    maf_var = tk.StringVar()
    tk.Entry(win, textvariable=maf_var).pack()

    def save_engine():
        try:
            maker = maker_var.get().strip().lower()
            engine = engine_var.get().strip()
            rpm_min, rpm_max = map(int, rpm_var.get().split(","))
            ect_min, ect_max = map(int, ect_var.get().split(","))
            maf_min, maf_max = map(float, maf_var.get().split(","))

            if maker not in PID_NORMAL:
                PID_NORMAL[maker] = {}
            PID_NORMAL[maker][engine] = {
                "RPM": [rpm_min, rpm_max],
                "ECT": [ect_min, ect_max],
                "MAF": [maf_min, maf_max]
            }

            with open("pid_normal.json", "w", encoding="utf-8") as f:
                json.dump(PID_NORMAL, f, indent=4, ensure_ascii=False)

            messagebox.showinfo("保存完了", f"{maker}/{engine} を追加しました")
        except Exception as e:
            add_log(f"[ERROR] save_engine: {e}")
            messagebox.showerror("エラー", f"保存に失敗しました：{e}")

    tk.Button(win, text="保存", command=save_engine).pack(pady=10)

def open_vds_editor():
    win = tk.Toplevel()
    win.title("VDS マップ編集ツール")
    win.geometry("550x500")

    with open("vds_map.json", "r", encoding="utf-8") as f:
        vds_data = json.load(f)

    tk.Label(win, text="メーカー").pack()
    maker_var = tk.StringVar()
    maker_box = ttk.Combobox(win, textvariable=maker_var, values=list(vds_data.keys()))
    maker_box.pack()

    tk.Label(win, text="VDS（例：R06A0、K6A0、3文字〜6文字）").pack()
    vds_var = tk.StringVar()
    tk.Entry(win, textvariable=vds_var).pack()

    tk.Label(win, text="エンジン型式（例：R06A_NA）").pack()
    engine_var = tk.StringVar()
    tk.Entry(win, textvariable=engine_var).pack()

    def save_vds():
        try:
            maker = maker_var.get()
            vds = vds_var.get().strip().upper()
            engine = engine_var.get().strip()

            if not maker or not vds or not engine:
                messagebox.showerror("エラー", "すべての項目を入力してください")
                return

            if maker not in vds_data:
                vds_data[maker] = {}

            vds_data[maker][vds] = engine

            with open("vds_map.json", "w", encoding="utf-8") as f:
                json.dump(vds_data, f, indent=4, ensure_ascii=False)

            global VDS_TO_ENGINE
            VDS_TO_ENGINE = vds_data

            messagebox.showinfo("保存完了", f"{maker} の VDS {vds} を更新しました")
        except Exception as e:
            add_log(f"[ERROR] save_vds: {e}")

    tk.Button(win, text="保存", command=save_vds).pack(pady=10)

# ============================================================
# GUI 本体
# ============================================================
def start_obd_after_ui():
    threading.Thread(target=connect_obd_thread, daemon=True).start()

root = tk.Tk()
root.title("診断機（OBD2 専用版）")
root.geometry("600x650")

label = tk.Label(root, text="診断機システム 起動中...", font=("Arial", 16))
label.pack(pady=10)

vin_label = tk.Label(root, text="VIN を入力してください：", font=("Arial", 12))
vin_label.pack()

vin_entry = tk.Entry(root, width=30, font=("Arial", 14))
vin_entry.pack(pady=5)

maker_label = tk.Label(root, text="メーカー：-", font=("Arial", 14))
maker_label.pack(pady=5)

obd_port_label = tk.Label(root, text="OBD ポート：未接続", font=("Arial", 12))
obd_port_label.pack(pady=5)

obd_status_label = tk.Label(root, text="OBD 状態：未接続", font=("Arial", 12), fg="red")
obd_status_label.pack(pady=5)

engine_label = tk.Label(root, text="車種（エンジン型式）：-", font=("Arial", 14))
engine_label.pack(pady=5)

vin_status_label = tk.Label(root, text="VIN 自動取得：未実行", font=("Arial", 12))
vin_status_label.pack(pady=5)

log_label = tk.Label(root, text="通信ログ", font=("Arial", 12, "bold"))
log_label.pack()

log_text = tk.Text(root, height=10, width=70, font=("Consolas", 10))
log_text.pack(pady=5)

def save_log_to_csv(filename):
    try:
        lines = log_text.get("1.0", tk.END).strip().split("\n")
        if not lines:
            return

        with open(filename, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["time", "message"])

            for line in lines:
                if line.startswith("[") and "]" in line:
                    t, msg = line.split("]", 1)
                    writer.writerow([t + "]", msg.strip()])
                else:
                    writer.writerow(["", line.strip()])

        add_log(f"CSV に保存しました：{filename}")
    except Exception as e:
        add_log(f"[ERROR] CSV 保存: {e}")

save_button = tk.Button(root, text="CSV 保存", font=("Arial", 12),
                        command=lambda: save_log_to_csv("obd_log.csv"))
save_button.pack(pady=5)

dtc_frame = tk.Frame(root)
dtc_frame.pack(pady=10)

tk.Button(dtc_frame, text="DTC 読み取り", font=("Arial", 12),
          command=show_dtc).pack(side="left", padx=10)

tk.Button(dtc_frame, text="DTC クリア", font=("Arial", 12),
          command=clear_dtc_action).pack(side="left", padx=10)

dtc_label = tk.Label(root, text="DTC：未取得", font=("Arial", 12))
dtc_label.pack(pady=5)

tk.Button(root, text="PID_NORMAL 編集", command=open_pid_editor).pack()
tk.Button(root, text="エンジン型式追加", command=open_engine_add_gui).pack()
tk.Button(root, text="VDS マップ編集", command=open_vds_editor).pack()

value_frame = tk.Frame(root)
value_frame.pack(pady=20)

normal_frame = tk.Frame(value_frame)
normal_frame.pack(side="left", padx=20)

actual_frame = tk.Frame(value_frame)
actual_frame.pack(side="right", padx=20)

tk.Label(normal_frame, text="正常値", font=("Arial", 14, "bold")).pack()
normal_rpm_label = tk.Label(normal_frame, text="RPM：-", font=("Arial", 12))
normal_rpm_label.pack(anchor="w")
normal_ect_label = tk.Label(normal_frame, text="ECT：-", font=("Arial", 12))
normal_ect_label.pack(anchor="w")
normal_maf_label = tk.Label(normal_frame, text="MAF：-", font=("Arial", 12))
normal_maf_label.pack(anchor="w")

tk.Label(actual_frame, text="実測値", font=("Arial", 14, "bold")).pack()
rpm_value_label = tk.Label(actual_frame, text="RPM：-", font=("Arial", 14))
rpm_value_label.pack(anchor="w")
ect_value_label = tk.Label(actual_frame, text="ECT：-", font=("Arial", 14))
ect_value_label.pack(anchor="w")
maf_value_label = tk.Label(actual_frame, text="MAF：-", font=("Arial", 14))
maf_value_label.pack(anchor="w")

def update_vin_info(vin: str):
    try:
        vin = vin.strip().upper()

        if len(vin) < 3:
            maker_label.config(text="メーカー：-")
            engine_label.config(text="車種（エンジン型式）：-")
            normal_rpm_label.config(text="RPM：-")
            normal_ect_label.config(text="ECT：-")
            normal_maf_label.config(text="MAF：-")
            return

        maker = vin_to_maker(vin, WMI_TO_MAKER)
        if maker is None:
            maker = "generic"

        maker_label.config(text=f"メーカー：{maker.upper()}")

        engine = detect_engine_type(vin, maker)
        engine_label.config(text=f"車種（エンジン型式）：{engine}")

        if maker in PID_NORMAL and engine in PID_NORMAL[maker]:
            normal = PID_NORMAL[maker][engine]
            normal_rpm_label.config(text=f"RPM：{normal['RPM'][0]}〜{normal['RPM'][1]}")
            normal_ect_label.config(text=f"ECT：{normal['ECT'][0]}〜{normal['ECT'][1]}")
            normal_maf_label.config(text=f"MAF：{normal['MAF'][0]}〜{normal['MAF'][1]}")
        else:
            normal_rpm_label.config(text="RPM：-")
            normal_ect_label.config(text="ECT：-")
            normal_maf_label.config(text="MAF：-")

    except Exception as e:
        add_log(f"[ERROR] update_vin_info: {e}")

def on_vin_change(event):
    try:
        vin = vin_entry.get().strip().upper()
        update_vin_info(vin)
    except Exception as e:
        add_log(f"[ERROR] VIN 入力イベント: {e}")

vin_entry.bind("<KeyRelease>", on_vin_change)

def toggle_learning():
    global learning_enabled
    learning_enabled = not learning_enabled
    if learning_enabled:
        learning_button.config(text="学習モード：ON", fg="green")
        add_log("学習モードを ON にしました")
    else:
        learning_button.config(text="学習モード：OFF", fg="red")
        add_log("学習モードを OFF にしました")

learning_button = tk.Button(root, text="学習モード：OFF", fg="red",
                            command=toggle_learning)
learning_button.pack(pady=5)

def tk_exception_handler(exc_type, exc_value, tb):
    add_log(f"[TK ERROR] {exc_value}")

root.report_callback_exception = tk_exception_handler

root.after(500, start_obd_after_ui)
root.after(1000, update_obd)
root.after(10000, auto_learn_pid_normal)

root.mainloop()
