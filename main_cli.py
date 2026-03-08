import time
import serial

from logger import add_log
from maker import vin_to_maker, detect_engine_type
from learning import learning_buffer, auto_learn

# ------------------------------------------------------------
# 高速版 safe_send（ELM327最適化）
# ------------------------------------------------------------
def safe_send(ser, cmd, wait=0.02):
    try:
        add_log(f"ECU ← {cmd.decode().strip()}")
        ser.reset_input_buffer()
        ser.write(cmd)

        time.sleep(wait)
        data = ser.read_until(b">", 2048).decode(errors="ignore")

        add_log(f"ECU → {data.strip()}")
        return data
    except Exception as e:
        add_log(f"[SEND ERROR] {e}")
        return ""


# ------------------------------------------------------------
# VIN 読み取り（高速版）
# ------------------------------------------------------------
def read_vin(ser):
    ser.reset_input_buffer()
    ser.write(b"0902\r")
    time.sleep(0.05)
    raw = ser.read_until(b">", 1024).decode(errors="ignore")

    if "49 02" not in raw:
        return None

    chars = []
    for line in raw.split("\r"):
        if "49 02" in line:
            parts = line.split(" ")[3:]
            for p in parts:
                try:
                    chars.append(chr(int(p, 16)))
                except:
                    pass

    vin = "".join(chars).strip()
    return vin if len(vin) >= 10 else None


# ------------------------------------------------------------
# PIDまとめ読み（高速版）
# ------------------------------------------------------------
def read_multi_pid(ser):
    """
    RPM(0C), ECT(05), MAF(10) を1回の通信で取得する高速版
    """
    data = safe_send(ser, b"01 0C 05 10\r", wait=0.02)

    rpm = None
    ect = None
    maf = None

    # RPM
    if "41 0C" in data:
        try:
            parts = data.split("41 0C")[1].strip().split(" ")
            A = int(parts[0], 16)
            B = int(parts[1], 16)
            rpm = ((A * 256) + B) / 4
        except:
            pass

    # ECT
    if "41 05" in data:
        try:
            A = int(data.split("41 05")[1].strip().split(" ")[0], 16)
            ect = A - 40
        except:
            pass

    # MAF
    if "41 10" in data:
        try:
            parts = data.split("41 10")[1].strip().split(" ")
            A = int(parts[0], 16)
            B = int(parts[1], 16)
            maf = ((A * 256) + B) / 100
        except:
            pass

    return rpm, ect, maf


# ------------------------------------------------------------
# DTC 読み取り（03）
# ------------------------------------------------------------
def read_dtc(ser):
    data = safe_send(ser, b"03\r", wait=0.05)
    if not data:
        return []

    codes = []
    for line in data.replace("\r", "\n").split("\n"):
        line = line.strip()
        if not line.startswith("43"):
            continue
        parts = line.split(" ")[1:]
        for p in parts:
            if len(p) == 4:
                codes.append(p.upper())
    return codes


# ------------------------------------------------------------
# メイン CLI
# ------------------------------------------------------------
learning_enabled = True

def main():
    global learning_enabled

    print("=== OBD2 診断ツール（CLI版・高速PID対応） ===")

    ser = serial.Serial("COM15", baudrate=115200, timeout=0.1)

    # VIN取得
    vin = None
    for _ in range(5):
        vin = read_vin(ser)
        if vin:
            break
        time.sleep(0.05)

    if not vin:
        print("VIN 取得失敗")
        return

    maker = vin_to_maker(vin) or "generic"
    engine = detect_engine_type(vin, maker)

    add_log(f"VIN: {vin}")
    add_log(f"メーカー: {maker.upper()}")
    add_log(f"エンジン型式: {engine}")
    print("----------------------------------")

    while True:
        print("1: PID 表示（学習バッファに追加）")
        print("2: DTC 読み取り")
        print("3: DTC 消去")
        print("4: 学習 ON/OFF 切り替え")
        print("5: CAN Raw モード")
        print("6: CAN Sniffer モード")
        print("7: CAN 送信")
        print("8: 終了")

        cmd = input("> ").strip()

        if cmd == "1":
            rpm, ect, maf = read_multi_pid(ser)

            add_log(f"PID: RPM={rpm}, ECT={ect}, MAF={maf}")

            print(f"RPM: {rpm}")
            print(f"ECT: {ect} °C")
            print(f"MAF: {maf} g/s")

            if learning_enabled:
                if rpm is not None:
                    learning_buffer["RPM"].append(rpm)
                if ect is not None:
                    learning_buffer["ECT"].append(ect)
                if maf is not None:
                    learning_buffer["MAF"].append(maf)

                auto_learn(maker, engine)

            print("----------------------------------")

        elif cmd == "2":
            codes = read_dtc(ser)
            add_log(f"DTC 結果: {codes}")

            if not codes:
                print("DTC: なし")
            else:
                print(f"DTC {len(codes)}件:")
                for c in codes:
                    print(" -", c)
            print("----------------------------------")

        elif cmd == "3":
            safe_send(ser, b"04\r")
            print("DTC 消去完了")
            print("----------------------------------")

        elif cmd == "4":
            learning_enabled = not learning_enabled
            state = "ON" if learning_enabled else "OFF"
            add_log(f"学習モード: {state}")
            print(f"学習モード: {state}")
            print("----------------------------------")

        elif cmd == "5":
            can_raw_mode(ser)

        elif cmd == "6":
            can_sniffer_mode(ser)

        elif cmd == "7":
            can_send_mode(ser)

        elif cmd == "8":
            add_log("診断ツール終了")
            print("終了します")
            break

        else:
            print("無効な入力です")
