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
├─ plot_live_csv.py
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
- `plot_live_csv.py`  
  保存済みの `logs/live_*.csv` から、PID推移グラフをPNG保存する補助スクリプトです。
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
- 17文字VINと、17文字未満の VIN候補 の区別表示
- DTC読取
- 基本PID表示
- DTC知識ベースに基づく補足表示
- DTCとPIDを組み合わせた補助コメント表示（参考表示）
- `logs/history.csv` を使ったDTC再発傾向の参考表示
- OBD診断実行（DTCを診断エンジンへ連携）
- 診断レポート保存
- DTC消去
- DTC消去後の再確認
- ライブデータCSV保存と、保存済みCSVの簡易後解析
- 保存済みCSVの要約表示（RPM / ECT / MAF / SPEED / IAT / THR）
- 保存済みCSVのアイドル参考、暖機参考、未取得サマリー、記録タイプ分類の参考表示
- 補助スクリプト `plot_live_csv.py` による、保存済みCSVからのグラフPNG保存
- 一部メーカー / 車種系統の参考プロファイル表示
- レクサスES / トヨタ・レクサスHV系を含む実車傾向ベースの参考表示
- 現在状態表示（接続/VIN/DTCなど）

国産車向けの確認例を基準にしていますが、汎用OBD2に対応した外車でも利用できる場合があります。  
ただし車種・年式・アダプタ相性・メーカー独自仕様により、VINや一部PIDを含め取得できる項目は変わります。  
対応の中心は generic DTC（主に `P0xxx`）と基本PIDで、メーカー専用診断項目は未対応または限定的です。

一部の generic DTC では、初心者向けの補足説明や確認ポイントを表示できます。  
また、DTCがあるときは取得できたPID値に応じて補助コメントを出せる場合がありますが、いずれも参考表示であり単独では故障断定できません。

履歴CSVがある場合は、DTC読取時に過去履歴と照合した短い参考コメントを表示できることがあります。  
同じDTCが過去にも記録されていれば、回数や前回履歴の有無を再発傾向の確認用として表示します。  
`logs/history.csv` がない場合も、そのまま通常どおり動作します。

VINは17文字ちょうどで取得できた場合は通常の VIN として扱います。  
17文字未満の識別文字列が取れた場合は `VIN候補` として表示し、完全VINではない可能性があることを補足表示します。

一部の車種系統では `参考プロファイル` として、接続傾向、VINの見え方、PID確認時の注意を短く表示できます。  
レクサスESやトヨタ / レクサスHV系では、短い識別文字列が返る場合や、ハイブリッド制御のためアイドル値・スロットル値を通常ガソリン車の感覚で単純比較しにくい点も参考表示します。

初回確認は、国産車 / 外車ともに `接続 → VIN取得 → DTC読取 → 基本PID表示` の順で進めると状況を把握しやすくなります。

---

## 実車確認

実車で OBD 接続から診断まで順番に確認したい場合は、以下のチェックリストを参照してください。  
[実車確認チェックリスト](docs/obd_test_checklist.md)

### 実車確認済みの例

日産キューブで、以下の動作を確認しました。

- OBD接続成功
- 基本PID表示成功
- ライブデータ表示成功
- DTC読取成功
- DTCなし判定成功（`03 -> 4300` 系）
- `DTCなしのためOBD診断は実行しません` の流れを確認
- セッションログ保存成功
- ライブデータCSV保存成功
- 保存済みライブCSVの簡易後解析成功
- センサー簡易診断コメント表示成功

実測例として、以下のようなPID値を取得できました。

- RPM: 1087.5
- ECT: 48
- MAF: 4.29
- SPEED: 0
- IAT: 18
- THROTTLE: 6.7

車種や年式、アダプタ相性によって結果は異なる場合があります。  
実車環境により取得できる項目は変動します。

一部のメーカー / 車種系統については、接続時の注意や既知の傾向を `参考プロファイル` として短く表示できる土台があります。  
セルシオ・キューブ・VW系に加え、レクサスES / トヨタ・レクサスHV系などの参考表示も少しずつ追加しています。  
これは参考表示であり、車種の確定や個体差の断定を行うものではありません。

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

```bash
cd /d C:\Users\User\Desktop\car_diagnosis_ai
python plot_live_csv.py
```

```bash
cd /d C:\Users\User\Desktop\car_diagnosis_ai
python plot_live_csv.py logs\live_2026-03-12_151103.csv
```

Windows のコマンドプロンプトや PowerShell で、そのまま実行できます。
`plot_live_csv.py` は補助スクリプトで、保存済みのライブCSVから RPM / ECT / MAF / SPEED / IAT / THR の推移をPNG化します。  
CSVを省略すると最新の `logs/live_*.csv` を自動選択し、必要なら引数で対象CSVを指定できます。

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
- 診断履歴CSV: `logs/history.csv`（実車確認メモも保存）
- `.pyc` / `__pycache__/` / `logs/` / `reports/` などは `.gitignore` で除外しています

`main_cli.py` を実行すると、操作ログは `logs/session_YYYYMMDD_HHMMSS.log` に保存されます。  
ライブデータ表示は `logs/live_YYYYMMDD_HHMMSS.csv` に保存でき、OBD診断履歴は `logs/history.csv` に実車確認メモ付きで残せます。  
接続確認や実車テスト時の記録を残して、あとから見返す用途に使えます。  
この履歴CSVは、同じDTCが過去にも出ていたかを見る簡易な再発確認にも使えます。  
履歴がたまっていくほど、同じコードの再発傾向を参考表示で見返しやすくなります。  
保存済みのライブCSVは、`main_cli.py` のメニューからあとで簡易解析でき、RPM / ECT / MAF / SPEED / IAT / THR の要約と参考コメントを確認できます。
あわせて、アイドル中心かどうかの目安、暖機途中 / 暖機後の参考表示、未取得が多い項目、記録タイプ（停止中心ログ / 走行ありログ / 混在ログ / 判定保留）も確認できます。  
また、`plot_live_csv.py` を使うと保存済みCSVからグラフ画像を `logs/` に保存できます。空欄や未取得列があっても、描画できる範囲でPNG化します。  
後解析の表示はいずれも参考用で、単独で異常や故障を断定するものではありません。

---

## 注意

- このツールは診断支援用です。最終判断は実車確認・追加点検を前提にしてください。
- DTC消去は、原因確認と必要な記録を行ってから実施してください。
- 古い車両やメーカー独自コードでは、追加の整備情報確認が必要になる場合があります。
- DTC知識ベース、DTC+PID補助コメント、車種プロファイル、ライブCSV後解析はいずれも参考表示です。単独では故障断定できません。
- DTC履歴の再発検出も参考表示です。履歴がなくても通常動作し、単独では故障断定できません。
- `VIN候補` は完全VINではない場合があります。再取得できる場合は再試行してください。
- ハイブリッド系ではアイドル値やスロットル値の見え方が通常ガソリン車と異なる場合があります。単純比較で断定しないでください。
- ライブCSVグラフ生成には `matplotlib` が必要です。`requirements.txt` に追記済みです。
- グラフ画像も傾向確認用です。単独で異常や故障を断定するものではありません。
