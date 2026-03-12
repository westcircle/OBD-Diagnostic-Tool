LIVE_ANOMALY_THRESHOLDS = {
    "idle_rpm_span_warn": 150,
    "ect_low_max": 60,
    "ect_high_max": 105,
    "maf_low_idle_avg": 1.5,
    "maf_high_idle_avg": 8.0,
    "thr_high_idle_avg": 20.0,
}


LIVE_ANOMALY_PROFILE_OVERRIDES = {
    "セルシオ参考": {
        "idle_rpm_span_warn": 220,
    },
    "VW系参考": {
        "maf_high_idle_avg": 10.0,
    },
    "日産キューブ参考": {
        "thr_high_idle_avg": 24.0,
    },
    "レクサスES / HV系参考": {
        "maf_low_idle_avg": 1.0,
        "thr_high_idle_avg": 28.0,
    },
    "トヨタ / レクサスHV系参考": {
        "maf_low_idle_avg": 1.0,
        "thr_high_idle_avg": 28.0,
    },
}


def build_idle_hint(summary):
    rpm = summary.get("rpm", {})
    speed = summary.get("speed", {})
    thr = summary.get("thr", {})

    speed_max = speed.get("max")
    rpm_avg = rpm.get("avg")
    thr_avg = thr.get("avg")

    if speed_max is None and rpm_avg is None:
        return []

    if speed_max == 0 and (rpm_avg is None or rpm_avg <= 1200) and (thr_avg is None or thr_avg <= 20):
        return [
            "参考: この記録はアイドル中心の可能性があります",
            "参考: 停止中の観察ログとして見やすいです",
        ]

    if (speed_max is not None and speed_max > 0) or (rpm_avg is not None and rpm_avg > 1500) or (thr_avg is not None and thr_avg > 25):
        return [
            "参考: 走行を含む記録の可能性があります",
            "参考: 純粋なアイドル観察用ログではない可能性があります",
        ]

    return []


def build_warmup_hint(summary):
    ect = summary.get("ect", {})
    ect_count = ect.get("count", 0)
    ect_missing = ect.get("missing", 0)

    if ect_count == 0:
        return ["参考: ECT未取得のため暖機状態は判定保留です"]

    if ect_missing > ect_count:
        return ["参考: ECTの空欄が多いため暖機状態は参考程度に見てください"]

    ect_min = ect.get("min")
    ect_max = ect.get("max")
    ect_avg = ect.get("avg")

    if ect_max is None:
        return []

    if ect_max < 70 or (ect_min is not None and ect_max - ect_min >= 10 and ect_avg is not None and ect_avg < 75):
        return [
            "参考: この記録は暖機途中の可能性があります",
            "参考: 水温の上がり方の確認に使えます",
        ]

    if 75 <= ect_max <= 105:
        return ["参考: 暖機後の確認ログとして見られる可能性があります"]

    return []


def build_missing_column_summary(summary):
    row_count = summary.get("row_count", 0)
    columns = [
        ("RPM", "rpm"),
        ("ECT", "ect"),
        ("MAF", "maf"),
        ("SPEED", "speed"),
        ("IAT", "iat"),
        ("THR", "thr"),
    ]
    details = []
    many_missing = []

    for label, key in columns:
        missing = summary.get(key, {}).get("missing", 0)
        details.append(f"{label}: 空欄 {missing}/{row_count}")
        if row_count > 0 and missing >= max(2, row_count // 2):
            many_missing.append(label)

    return {"details": details, "many_missing": many_missing}


def classify_live_log_type(summary):
    speed = summary.get("speed", {})
    rpm = summary.get("rpm", {})
    thr = summary.get("thr", {})

    speed_count = speed.get("count", 0)
    speed_max = speed.get("max")

    if speed_count < 2 or speed_max is None:
        return {
            "label": "判定保留",
            "hint": "参考: SPEED未取得または有効データが少ないため、記録タイプは保留です",
        }

    row_count = max(summary.get("row_count", 0), speed_count)
    moving_count = 0
    stop_count = 0

    if row_count > 0:
        moving_count = int(round(speed_count * speed.get("avg", 0) / max(speed_max, 1)))
        moving_count = max(0, min(moving_count, speed_count))
        stop_count = speed_count - moving_count

    moving_ratio = moving_count / speed_count if speed_count else 0
    stop_ratio = stop_count / speed_count if speed_count else 0

    if speed_max == 0:
        return {
            "label": "停止中心ログ",
            "hint": "参考: 停止中の観察に向いたログです",
        }

    if moving_count == 0 and speed_max <= 1:
        return {
            "label": "停止中心ログ",
            "hint": "参考: ほぼ停止中の観察に向いたログです",
        }

    if stop_ratio >= 0.2 and moving_ratio >= 0.2 and moving_ratio < 0.7 and speed_max < 40:
        return {
            "label": "混在ログ",
            "hint": "参考: 停止と走行が混ざったログの可能性があります",
        }

    if moving_ratio >= 0.7 or speed_max >= 40:
        return {
            "label": "走行ありログ",
            "hint": "参考: 走行を含むため、アイドル観察専用ではありません",
        }

    if speed_max <= 3 and (rpm.get("avg") is None or rpm.get("avg") <= 1200) and (thr.get("avg") is None or thr.get("avg") <= 20):
        return {
            "label": "停止中心ログ",
            "hint": "参考: 停止中心の可能性があります。低速移動が少し混ざる場合もあります",
        }

    return {
        "label": "判定保留",
        "hint": "参考: 停止と走行の比率が読み切れず、記録タイプは参考保留です",
    }


def get_live_anomaly_thresholds(profile=None):
    thresholds = dict(LIVE_ANOMALY_THRESHOLDS)
    profile_info = profile or {}
    title = profile_info.get("title")
    if title in LIVE_ANOMALY_PROFILE_OVERRIDES:
        thresholds.update(LIVE_ANOMALY_PROFILE_OVERRIDES[title])
    return thresholds


def build_live_anomaly_comments(summary, profile=None):
    comments = []
    row_count = summary.get("row_count", 0)
    rpm = summary.get("rpm", {})
    ect = summary.get("ect", {})
    maf = summary.get("maf", {})
    speed = summary.get("speed", {})
    iat = summary.get("iat", {})
    thr = summary.get("thr", {})
    missing_info = build_missing_column_summary(summary)
    log_type = summary.get("log_type") or classify_live_log_type(summary)
    thresholds = get_live_anomaly_thresholds(profile or summary.get("vehicle_profile") or summary.get("profile"))

    def finalize_level(level):
        final_level = level
        if row_count < 5 or log_type.get("label") == "判定保留":
            final_level = "弱"
        elif missing_info["many_missing"] and level == "中":
            final_level = "弱"
        return final_level

    def add_comment(text, level="弱"):
        if not text:
            return
        final_text = f"[{finalize_level(level)}] {text}"
        if final_text not in comments:
            comments.append(final_text)

    if rpm.get("count", 0) >= 5 and log_type.get("label") == "停止中心ログ":
        rpm_span = rpm.get("max", 0) - rpm.get("min", 0)
        if rpm_span >= thresholds["idle_rpm_span_warn"]:
            add_comment("参考: RPMのばらつきがやや大きく、アイドル不安定傾向の可能性があります", level="中")

    if ect.get("count", 0) >= 3:
        if ect.get("max") is not None and ect.get("max") < thresholds["ect_low_max"]:
            add_comment("参考: ECTが低めで、まだ暖機途中の可能性があります", level="弱")
        elif ect.get("max") is not None and ect.get("max") > thresholds["ect_high_max"]:
            add_comment("参考: ECTが高めに見えます。測定条件差も含めて要確認です", level="中")

    if log_type.get("label") == "停止中心ログ" and maf.get("count", 0):
        maf_avg = maf.get("avg")
        if maf_avg is not None and maf_avg < thresholds["maf_low_idle_avg"]:
            add_comment("参考: MAFが低めの傾向です。吸気条件差も含めて参考確認してください", level="中")
        elif maf_avg is not None and maf_avg > thresholds["maf_high_idle_avg"]:
            add_comment("参考: MAFが高めの傾向です。負荷条件や吸気状態も参考確認してください", level="中")
    if row_count > 0 and maf.get("missing", 0) >= max(2, row_count // 2):
        add_comment("参考: MAFの未取得が多く、取得条件やPID対応状況も要確認です", level="中")

    if speed.get("count", 0) >= 3 and speed.get("max") == 0:
        add_comment("参考: SPEEDがすべて0のため、停止中心ログの可能性があります", level="弱")
    elif row_count > 0 and speed.get("missing", 0) >= max(2, row_count // 2):
        add_comment("参考: SPEEDの取得が限定的です。車速信号や通信条件差も参考確認してください", level="中")

    if iat.get("count", 0) and (iat.get("avg", 0) < -20 or iat.get("avg", 0) > 60):
        add_comment("参考: IATが不自然寄りに見えます。吸気温センサー値も要確認です", level="弱")

    if log_type.get("label") == "停止中心ログ" and thr.get("count", 0) and thr.get("avg", 0) > thresholds["thr_high_idle_avg"]:
        add_comment("参考: 停止中心としてはTHROTTLEが高めです。操作条件差も含めて確認してください", level="中")

    if missing_info["many_missing"]:
        add_comment(f"参考: 未取得が多い項目があります ({', '.join(missing_info['many_missing'])})", level="弱")

    if row_count < 5 and comments:
        add_comment("参考: サンプル数が少なめのため、上記は傾向確認として見てください", level="弱")

    return comments[:5]


def build_overall_reference_notes(dtc_list=None, dtc_pid_hints=None, anomaly_comments=None, summary=None):
    notes = []
    codes = {str(code).strip().upper() for code in (dtc_list or []) if code}
    hint_text = " ".join(dtc_pid_hints or [])
    anomaly_text = " ".join(anomaly_comments or [])
    combined_text = f"{hint_text} {anomaly_text}"
    log_type = (summary or {}).get("log_type", {}).get("label")
    missing_info = build_missing_column_summary(summary or {"row_count": 0})

    def add_note(text):
        if text and text not in notes:
            notes.append(text)

    if "P0171" in codes or any(word in combined_text for word in ("二次エア", "エアフロ", "吸気", "燃調")):
        add_note("燃調/吸気系の参考確認を優先してください。MAF取得状況や吸気条件差も含めて見てください")

    if "P0500" in codes or any(word in combined_text for word in ("車速PID", "車速信号", "SPEEDの取得")):
        add_note("車速系と取得条件差の両面を参考確認してください")

    if "B2797" in codes:
        add_note("認証系/イモビ系も別系統として参考確認してください")

    if any(word in combined_text for word in ("暖機途中", "ECTが低め", "暖機条件")):
        add_note("暖機条件をそろえて再確認すると、今回の傾向を比較しやすくなります")

    if any(word in combined_text for word in ("未取得が多い", "PID取得が限定的", "未取得データが多く")) or missing_info["many_missing"]:
        add_note("PID未取得が多い場合は、今回結果を参考範囲として見てください")

    if log_type == "停止中心ログ":
        add_note("停止中心ログのため、必要に応じて走行条件でも再確認すると判断しやすくなります")

    return notes[:3]


def build_dtc_pid_hints(dtc_list, pid_values):
    if not dtc_list:
        return []
    if pid_values is None:
        pid_values = {}

    hints = []
    missing_keys = [key for key in ("RPM", "ECT", "MAF", "SPEED", "IAT", "THROTTLE") if pid_values.get(key) is None]
    codes = {str(code).strip().upper() for code in dtc_list if code}
    rpm = pid_values.get("RPM")
    ect = pid_values.get("ECT")
    iat = pid_values.get("IAT")
    maf = pid_values.get("MAF")
    speed = pid_values.get("SPEED")
    throttle = pid_values.get("THROTTLE")

    def add_hint(text):
        if text and text not in hints:
            hints.append(text)

    if "P0171" in codes:
        if maf is not None and throttle is not None and throttle <= 15 and maf <= 4:
            add_hint("参考: P0171で低開度かつMAF低めです。吸気側の二次エアやエアフロ汚れも要確認です")
        elif iat is not None and (iat < -20 or iat > 60):
            add_hint("参考: P0171で吸気温の値が不自然寄りです。吸気温センサー系も参考確認してください")

    if {"P0100", "P0101", "P0102", "P0103"} & codes:
        if maf is None:
            add_hint("参考: MAF系DTCがありますが、MAF値は未取得です。配線やセンサー電源も要確認です")
        elif maf < 2:
            add_hint("参考: MAF系DTCがあり、吸入空気量は低めです。吸気漏れやセンサー汚れ要確認です")
        elif maf > 100:
            add_hint("参考: MAF系DTCがあり、吸入空気量は高めです。信号異常や吸気系要確認です")

    if {"P0110", "P0115", "P0116", "P0117", "P0118"} & codes:
        if iat is not None and (iat < -20 or iat > 60):
            add_hint("参考: 温度系DTCがあり、吸気温の値が不自然寄りです。センサー値と配線を要確認です")
        elif ect is not None and (ect < -20 or ect > 110):
            add_hint("参考: 温度系DTCがあり、水温の値が不自然寄りです。実温度との差を要確認です")

    if {"P0120", "P0122", "P0123"} & codes:
        if throttle is None:
            add_hint("参考: スロットル系DTCがありますが、開度値は未取得です。TPS信号と配線を要確認です")
        elif throttle < 1 or throttle > 80:
            add_hint("参考: スロットル系DTCがあり、開度値が偏っています。センサーずれや配線を要確認です")

    if {"P0300", "P0301", "P0302", "P0303", "P0304"} & codes:
        if rpm is not None and rpm < 900 and throttle is not None and throttle <= 15:
            add_hint("参考: ミスファイア系DTCがあり、現在はアイドル域です。点火系や燃調ばらつきも要確認です")
        elif maf is not None and maf < 2:
            add_hint("参考: ミスファイア系DTCがあり、吸入空気量は少なめです。吸気系や燃料系も要確認です")

    if "P0500" in codes:
        if speed is None:
            add_hint("参考: 車速系DTCがありますが、車速PIDは未取得です。信号系と配線を要確認です")
        elif speed == 0:
            add_hint("参考: 車速系DTCがあり、現在の車速は0km/hです。走行中にも0固定なら要確認です")

    if "P0420" in codes:
        if ect is not None and ect >= 75:
            add_hint("参考: P0420があり、現在は暖機後の可能性があります。触媒効率やO2系も要確認です")
        else:
            add_hint("参考: P0420はPID単独では断定不可です。O2センサー波形や排気漏れ確認が有効です")

    if {"P0135", "P0141"} & codes:
        if ect is not None and ect < 70:
            add_hint("参考: O2ヒーター系DTCがあり、まだ暖機途中寄りです。ヒーター回路や配線も要確認です")
        else:
            add_hint("参考: O2ヒーター系DTCです。冷間始動時の再現性や配線状態も参考確認してください")

    if "P0401" in codes:
        if ect is not None and ect >= 75:
            add_hint("参考: P0401が暖機後にも出る場合、EGR通路詰まりや制御不足も参考確認してください")

    if "P0440" in codes:
        add_hint("参考: P0440は蒸発ガス系DTCです。フューエルキャップや配管も要確認です")

    if "B2797" in codes:
        add_hint("参考: B2797はイモビ系や認証系の確認対象です。エンジンPIDだけでは判断しにくいため別系統も要確認です")

    if len(missing_keys) >= 4 and hints:
        add_hint("参考: PID取得が限定的なため、上記コメントは参考範囲で確認してください")

    unique_hints = []
    for hint in hints:
        if hint not in unique_hints:
            unique_hints.append(hint)
    return unique_hints[:4]


def annotate_failure_candidates(dtc_code, failure_candidates, dtc_pid_hints=None):
    candidates = [str(candidate).strip() for candidate in (failure_candidates or []) if str(candidate).strip()]
    if not candidates:
        return []

    hint_text = " ".join(str(hint) for hint in (dtc_pid_hints or [])).upper()
    normalized_code = str(dtc_code or "").strip().upper()

    def has_any(*keywords):
        return any(keyword.upper() in hint_text for keyword in keywords)

    def build_suffix(candidate):
        if normalized_code == "P0171":
            if "吸気漏れ" in candidate and has_any("吸気", "燃調", "二次エア"):
                return "（燃調/吸気系ヒントあり）"
            if "MAF" in candidate and has_any("MAF", "エアフロ"):
                return "（PID傾向から参考優先）"
            if "燃圧" in candidate and has_any("燃料", "燃圧"):
                return "（燃料系ヒントあり）"
        elif normalized_code == "P0300":
            if "点火" in candidate and has_any("ミスファイア", "点火"):
                return "（失火系ヒントあり）"
            if "燃料" in candidate and has_any("燃料", "燃圧"):
                return "（燃料系ヒントあり）"
            if "吸気" in candidate and has_any("吸気", "二次エア"):
                return "（吸気系ヒントあり）"
        elif normalized_code == "P0420":
            if "O2" in candidate and has_any("O2", "A/F"):
                return "（O2系ヒントあり）"
            if "排気漏れ" in candidate and has_any("排気漏れ", "排気"):
                return "（排気系ヒントあり）"
        elif normalized_code == "P0100":
            if "MAF" in candidate and has_any("MAF", "エアフロ"):
                return "（MAF系ヒントあり）"
        elif normalized_code == "P0110":
            if ("IAT" in candidate or "吸気温" in candidate) and has_any("IAT", "吸気温"):
                return "（吸気温系ヒントあり）"
        elif normalized_code == "P0120":
            if ("TPS" in candidate or "スロットル" in candidate) and has_any("THROTTLE", "TPS", "開度"):
                return "（開度系ヒントあり）"
        return ""

    lines = []
    for index, candidate in enumerate(candidates, start=1):
        suffix = build_suffix(candidate)
        lines.append(f"{index}. {candidate}{suffix}")
    return lines
