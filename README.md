# car_diagnosis_ai

Pythonで作る初心者向けの車診断支援ツールです。  
GUIは使わず、CLI（ターミナル）中心で開発しています。

OBD接続でDTC/PIDを読み取り、診断支援結果の表示とレポート保存ができます。

---

## できること

- 手入力またはOBD読取のDTCを使った診断支援
- DTCコードの意味、原因候補、確認項目、緊急度の表示
- 診断レポートの `reports` フォルダ保存
- 接続ログの `logs` フォルダ保存（`main_cli.py` 利用時）

---

## 主要ファイルの役割

```text
car_diagnosis_ai/
├─ main.py
├─ main_cli.py
├─ diagnosis.py
├─ dtc_data.py
├─ maker_notes.py
├─ symptom_rules.py
├─ report.py
├─ utils.py
├─ requirements.txt
├─ README.md
├─ reports/
└─ logs/
```

- `main.py`  
  手入力診断CLI。DTCと症状を入力して診断結果を表示・保存します。
- `main_cli.py`  
  OBD接続対応の本命CLI。接続、読取、診断、保存まで一連で実行できます。
- `diagnosis.py`  
  `run_multi_diagnosis()` など、診断ロジック本体です。
- `report.py`  
  `format_report()` と `save_report_text()` で表示整形と保存を担当します。
- `dtc_data.py` / `maker_notes.py` / `symptom_rules.py` / `utils.py`  
  DTC辞書、メーカー補足、症状ルール、入力正規化などを担当します。

---

## `main_cli.py` でできること

- OBD接続
- 接続済み時の再接続確認
- VIN取得
- DTC読取
- 基本PID表示
- OBD診断実行（DTCを診断エンジンへ連携）
- 診断レポート保存
- DTC消去
- DTC消去後の再確認
- 現在状態表示（接続/VIN/DTCなど）

---

## 実行方法

```bash
cd /d C:\Users\User\Desktop\car_diagnosis_ai
python main.py
```

```bash
cd /d C:\Users\User\Desktop\car_diagnosis_ai
python main_cli.py
```

---

## 保存先

- 診断レポート: `reports/`
- 実行ログ（主にOBD CLI）: `logs/`

---

## 注意

- このツールは診断支援用です。最終判断は実車確認・追加点検を前提にしてください。
- DTC消去は、原因確認と必要な記録を行ってから実施してください。
