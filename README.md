# car_diagnosis_ai

Pythonで作る初心者向けの車診断支援ツールです。  
GUIは使わず、CLI（ターミナル）中心で開発しています。

OBD接続でDTC/PID（車両状態の読み取り値）を読み取り、診断支援結果の表示とレポート保存ができます。  
OBD機器を使う方法と、手入力で診断する方法の両方に対応しています。

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
├─ simulator.py
├─ utils.py
├─ wmi_map.json / vds_map.json / manufacturers.json
├─ pid_normal.json / dtc_database.json / dtc_merged.json
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
- `simulator.py`  
  テスト補助用（動作確認用）の補助スクリプトです。
- 各 `json` ファイル  
  メーカー判定、VIN補助、PID/DTC補助データなどを保持します。

---

## `main.py` の使い方（手入力診断CLI）

1. `python main.py` を実行  
2. 画面の案内に従って、メーカー / 車種 / 年式 / 走行距離 / DTC / 症状 を入力  
3. 診断結果が表示され、`reports/` に保存されます

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

## 実車確認

実車で OBD 接続から診断まで順番に確認したい場合は、以下のチェックリストを参照してください。  
[実車確認チェックリスト](docs/obd_test_checklist.md)

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

Windows のコマンドプロンプトや PowerShell で、そのまま実行できます。

---

## 基本テストの実行

軽い確認用テストとして `tests/test_cli_basic.py` を用意しています。  
`unittest`（Python標準ライブラリ）のみを使っているため、追加インストールは不要です。

```bash
cd /d C:\Users\User\Desktop\car_diagnosis_ai
python -m unittest tests.test_cli_basic -v
```

このテストでは、主に以下を確認します。
- DTC変換
- VINメーカー判定
- `normalize_maker_name()`
- `normalize_symptom_name()`
- `parse_year_to_western()`
- `run_multi_diagnosis()`

---

## 保存先

- 診断レポート: `reports/`
- 実行ログ（主にOBD CLI）: `logs/`
- セッションログ: `logs/session_YYYYMMDD_HHMMSS.log`
- ライブデータCSV（任意保存）: `logs/live_YYYYMMDD_HHMMSS.csv`
- `.pyc` / `__pycache__/` / `logs/` / `reports/` などは `.gitignore` で除外しています

---

## 注意

- このツールは診断支援用です。最終判断は実車確認・追加点検を前提にしてください。
- DTC消去は、原因確認と必要な記録を行ってから実施してください。
- 古い車両やメーカー独自コードでは、追加の整備情報確認が必要になる場合があります。
