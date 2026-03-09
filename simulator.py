import time
import serial

# 仮想COMポート（com0com で作ったポート）
PORT = "COM16"
BAUD = 115200

def respond(cmd):
    cmd = cmd.strip().upper()

    # ELM327 初期応答
    if cmd == "ATZ":
        return "ELM327 v1.5\r"

    if cmd == "ATI":
        return "ELM327 v1.5\r"

    if cmd == "ATE0":
        return "OK\r"

    # VIN (Mode 09 PID 02)
    if cmd == "0902":
        return (
            "49 02 01 57 50 30 5A 5A 5A 39\r\n"
            "49 02 02 39 5A 54 53 33 39 32\r\n"
            "49 02 03 31 32 34 00 00 00 00\r\n"
    )

    # RPM (010C)
    if cmd == "010C":
        rpm = 800
        A = (rpm * 4) // 256
        B = (rpm * 4) % 256
        return f"41 0C {A:02X} {B:02X}\r"

    # ECT (0105)
    if cmd == "0105":
        temp = 85
        A = temp + 40
        return f"41 05 {A:02X}\r"

    # MAF (0110)
    if cmd == "0110":
        maf = 3.20
        value = int(maf * 100)
        A = value // 256
        B = value % 256
        return f"41 10 {A:02X} {B:02X}\r"

    # DTC 読み取り (03)
    if cmd == "03":
        return "43 01 33 00 00 00\r"

    # DTC 消去 (04)
    if cmd == "04":
        return "44\r"

    return "OK\r"

def main():
    print(f"OBD2 Simulator running on {PORT} ...")
    ser = serial.Serial(PORT, BAUD, timeout=0.1)

    while True:
        if ser.in_waiting:
            raw = ser.read(ser.in_waiting).decode(errors="ignore")
            for line in raw.split("\r"):
                line = line.strip()
                if line:
                    print("ECU ←", line)
                    ans = respond(line)
                    print("ECU →", ans.strip())
                    ser.write((ans + "\r").encode())
        time.sleep(0.01)


if __name__ == "__main__":
    main()
