#!/usr/bin/env python3
"""
OMS L1 Rate Dashboard — Flask Backend

Serves a custom frontend plus APIs for current GLOBAL-RUN monitoring and
Heavy Ion reference-run bunch projection.
"""
import json
import math
import os
import re
import signal
import socket
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

import pandas as pd
from flask import Flask, jsonify, render_template, request, send_from_directory

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from web import config
from web.services import oms_data, projection


app = Flask(
    __name__,
    static_folder=str(Path(__file__).resolve().parent / "static"),
    template_folder=str(Path(__file__).resolve().parent / "templates"),
)


def _df_records(df):
    if df is None or df.empty:
        return []
    clean = df.replace([float("inf"), float("-inf")], pd.NA)
    return json.loads(clean.to_json(orient="records"))


def _clean_value(value):
    if value is None:
        return None
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    return value


def _float_or_none(value):
    if value in (None, ""):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(number) or math.isinf(number):
        return None
    return number


def _public_run_summary(summary):
    keys = [
        "run_number",
        "fill_number",
        "start_time",
        "end_time",
        "duration",
        "stable_beam",
        "last_lumisection_number",
        "l1_rate",
        "l1_menu",
        "l1_key",
        "hlt_key",
        "hlt_physics_throughput",
        "initial_prescale_index",
        "trigger_mode",
        "delivered_lumi",
        "recorded_lumi",
        "init_lumi",
        "end_lumi",
        "era",
        "sequence",
        "bunches_colliding",
    ]
    return {key: _clean_value(summary.get(key)) for key in keys}


def _int_arg(name, default=None, minimum=None):
    raw = request.args.get(name, default)
    if raw in (None, ""):
        return default
    value = int(raw)
    if minimum is not None:
        value = max(minimum, value)
    return value


def _payload_int(payload, name, default=None, minimum=None):
    raw = payload.get(name, default)
    if raw in (None, ""):
        return default
    value = int(raw)
    if minimum is not None:
        value = max(minimum, value)
    return value


def _payload_float(payload, name, default=None, minimum=None):
    raw = payload.get(name, default)
    if raw in (None, ""):
        return default
    value = float(raw)
    if minimum is not None:
        value = max(minimum, value)
    return value


def _payload_run_list(payload, name):
    raw = payload.get(name)
    if raw in (None, ""):
        return []
    values = raw if isinstance(raw, list) else re.split(r"[,\s]+", str(raw))
    runs = []
    seen = set()
    for value in values:
        if value in (None, ""):
            continue
        try:
            run = int(value)
        except (TypeError, ValueError):
            continue
        if run <= 0 or run in seen:
            continue
        seen.add(run)
        runs.append(run)
    return runs


def _resolve_trigger_selection(value):
    selection = str(value or "").strip()
    if not selection or selection.upper() == "ALL" or selection == "*":
        return [], "ALL L1 seeds", True
    path = Path(selection).expanduser()
    if path.exists() or selection.endswith(".txt"):
        triggers = oms_data.load_trigger_list(selection)
        return triggers, selection, False
    triggers = [
        item.strip()
        for item in re.split(r"[,\s]+", selection)
        if item and item.strip()
    ]
    return triggers, "inline trigger list", False


def _monitoring_seed_file():
    return Path(config.DEFAULT_TRIGGER_FILE).resolve()


def _normalize_seed_list(raw_seeds):
    seen = set()
    seeds = []
    for raw in raw_seeds or []:
        seed = str(raw or "").strip()
        if not seed or seed.startswith("#"):
            continue
        if not re.match(r"^[A-Za-z0-9_]+$", seed):
            raise ValueError(f"Invalid seed name: {seed}")
        if seed not in seen:
            seen.add(seed)
            seeds.append(seed)
    return seeds


def _write_monitoring_seed_file(seeds):
    path = _monitoring_seed_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = "\n".join(seeds)
    if payload:
        payload += "\n"
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(payload)
    tmp_path.replace(path)


def _default_rate_field(value=None):
    valid_fields = set(config.RATE_FIELD_OPTIONS.values())
    if value in valid_fields:
        return value
    return config.DEFAULT_RATE_FIELD


PROJECTION_SETTING_KEYS = {
    "trigger_file",
    "rate_field",
    "reference_run",
    "reference_lumi_mode",
    "reference_ls_min",
    "reference_ls_max",
    "reference_single_ls",
    "reference_hardcoded_lumi",
    "comparison_run",
    "current_lumi_mode",
    "current_ls_window",
    "current_ls_min",
    "current_ls_max",
    "current_single_ls",
    "current_hardcoded_lumi",
    "include_unstable",
    "comparisons",
}


DASHBOARD_REFERENCE_SETTING_KEYS = {
    "reference_run",
    "reference_ls_min",
    "reference_ls_max",
    "max_lumisections",
    "auto_refresh",
}


def _read_json_settings(path, allowed_keys):
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(payload, dict):
        return {}
    return {key: value for key, value in payload.items() if key in allowed_keys}


def _write_json_settings(path, settings, allowed_keys):
    clean = {
        key: value
        for key, value in (settings or {}).items()
        if key in allowed_keys
    }
    config.STATE_DIR.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(json.dumps(clean, indent=2, sort_keys=True))
    tmp_path.replace(path)
    return clean


def _read_projection_settings():
    return _read_json_settings(config.PROJECTION_SETTINGS_FILE, PROJECTION_SETTING_KEYS)


def _write_projection_settings(settings):
    return _write_json_settings(
        config.PROJECTION_SETTINGS_FILE,
        settings,
        PROJECTION_SETTING_KEYS,
    )


def _read_dashboard_reference_settings():
    return _read_json_settings(
        config.DASHBOARD_REFERENCE_SETTINGS_FILE,
        DASHBOARD_REFERENCE_SETTING_KEYS,
    )


def _write_dashboard_reference_settings(settings):
    return _write_json_settings(
        config.DASHBOARD_REFERENCE_SETTINGS_FILE,
        settings,
        DASHBOARD_REFERENCE_SETTING_KEYS,
    )


EXPORT_COLUMNS = [
    ("bit", "L1 bit"),
    ("pathname", "L1 trigger name"),
    ("reference_rate", "Reference rate"),
    ("lumi_ratio", "Lumi ratio"),
    ("expected_rate", "Projection"),
    ("rate", "Measured"),
    ("ratio", "Ratio"),
    ("run", "Run"),
    ("lumisection", "LS"),
    ("model_status", "Status"),
]


def _csv_export_frame(df):
    keys = [key for key, _label in EXPORT_COLUMNS]
    labels = {key: label for key, label in EXPORT_COLUMNS}
    if df is None or df.empty:
        return pd.DataFrame(columns=[label for _key, label in EXPORT_COLUMNS])
    export = df.copy()
    for key in keys:
        if key not in export.columns:
            export[key] = pd.NA
    return export[keys].rename(columns=labels)


def _write_projection_export(kind, rows, context):
    config.EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    ref_run = context.get("reference_run", "ref")
    cur_run = context.get("current_run", "cur")
    safe_kind = "full" if kind == "full" else "latest"
    filename = f"oms_l1_projection_ref{ref_run}_run{cur_run}_{stamp}_{safe_kind}.csv"
    path = config.EXPORT_DIR / filename
    frame = pd.DataFrame(rows or [])
    _csv_export_frame(frame).to_csv(path, index=False)
    return {
        "filename": filename,
        "path": str(path),
        "url": f"/api/exports/{filename}",
    }


def _filtered_plot_frame(df, stable_only=True):
    if df is None or df.empty:
        return pd.DataFrame(columns=oms_data.L1_RATE_COLUMNS)
    frame = df.copy()
    if stable_only and "beams_stable" in frame.columns:
        frame = frame[frame["beams_stable"] == True]
    frame = frame.dropna(subset=["pathname", "init_lumi", "rate"])
    return frame


def _lumi_stats_from_frame(df):
    if df is None or df.empty or "init_lumi" not in df.columns:
        return {"average": None, "latest": None, "points": 0}
    clean = df.copy()
    clean["init_lumi"] = pd.to_numeric(clean["init_lumi"], errors="coerce")
    clean = clean.dropna(subset=["init_lumi"])
    clean = clean[clean["init_lumi"] > 0]
    if clean.empty:
        return {"average": None, "latest": None, "points": 0}
    ordered = clean.sort_values("lumisection") if "lumisection" in clean.columns else clean
    return {
        "average": float(ordered["init_lumi"].mean()),
        "latest": float(ordered.tail(1).iloc[0]["init_lumi"]),
        "points": int(len(ordered)),
    }


def _trim_latest_lumisections(df, max_lumisections):
    if df is None or df.empty or max_lumisections is None:
        return df
    if "lumisection" not in df.columns:
        return df
    try:
        max_count = int(max_lumisections)
    except (TypeError, ValueError):
        return df
    if max_count <= 0:
        return df
    values = sorted(
        int(value)
        for value in pd.to_numeric(df["lumisection"], errors="coerce").dropna().unique()
    )
    if len(values) <= max_count:
        return df
    keep = set(values[-max_count:])
    return df[df["lumisection"].isin(keep)].copy()


def _apply_lumi_override(df, value):
    if value is None or df is None or df.empty:
        return df
    updated = df.copy()
    updated["init_lumi"] = float(value)
    return updated


def _latest_stable_lumisection(run, last_ls, chunk_size=300):
    try:
        run = int(run)
        end_ls = int(last_ls)
    except (TypeError, ValueError):
        return None
    if run <= 0 or end_ls <= 0:
        return None

    while end_ls > 0:
        start_ls = max(1, end_ls - int(chunk_size) + 1)
        lumisections = oms_data.get_lumisections(run, start_ls, end_ls)
        if not lumisections.empty and "beams_stable" in lumisections.columns:
            stable = lumisections[lumisections["beams_stable"] == True]
            if not stable.empty and "lumisection" in stable.columns:
                values = pd.to_numeric(stable["lumisection"], errors="coerce").dropna()
                if not values.empty:
                    return int(values.max())
        if start_ls <= 1:
            break
        end_ls = start_ls - 1

    return None


def _resolve_projection_lumi_window(payload, prefix, summary, default_mode):
    mode = str(payload.get(f"{prefix}_lumi_mode") or default_mode).strip()
    hardcoded_lumi = None
    last_ls = int(summary.get("last_lumisection_number") or 0)
    anchor_lumisection = None
    anchor_kind = None

    if mode == "latest_window":
        window = _payload_int(
            payload,
            f"{prefix}_ls_window",
            config.DEFAULT_CURRENT_LS_WINDOW,
            minimum=1,
        )
        run = summary.get("run_number")
        stable_ls = _latest_stable_lumisection(run, last_ls)
        if stable_ls is not None:
            ls_max = stable_ls
            anchor_lumisection = stable_ls
            anchor_kind = "last_stable"
        else:
            ls_max = last_ls
            anchor_lumisection = last_ls
            anchor_kind = "last_run"
        ls_min = max(1, ls_max - int(window) + 1) if ls_max > 0 else 1
    elif mode == "single":
        single_ls = _payload_int(payload, f"{prefix}_single_ls", minimum=1)
        if single_ls is None:
            raise ValueError(f"{prefix}_single_ls is required for specific LS mode")
        ls_min = single_ls
        ls_max = single_ls
    elif mode in {"range", "hardcoded"}:
        ls_min = _payload_int(payload, f"{prefix}_ls_min", minimum=1)
        ls_max = _payload_int(payload, f"{prefix}_ls_max", minimum=1)
        if ls_min is None or ls_max is None:
            raise ValueError(f"{prefix}_ls_min and {prefix}_ls_max are required")
        if mode == "hardcoded":
            hardcoded_lumi = _payload_float(
                payload,
                f"{prefix}_hardcoded_lumi",
                minimum=0.0,
            )
            if hardcoded_lumi is None:
                raise ValueError(f"{prefix}_hardcoded_lumi is required for hardcoded mode")
    else:
        raise ValueError(f"Unsupported {prefix} lumi mode: {mode}")

    if ls_max < ls_min:
        raise ValueError(f"{prefix} LS max must be >= LS min")

    return {
        "mode": mode,
        "ls_min": int(ls_min),
        "ls_max": int(ls_max),
        "anchor_lumisection": anchor_lumisection,
        "anchor_kind": anchor_kind,
        "hardcoded_lumi": hardcoded_lumi,
    }


def _is_port_in_use(port, host="0.0.0.0"):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind((host, port))
            return False
        except OSError:
            return True


def _get_listener_pid(port):
    try:
        res = subprocess.run(
            ["ss", "-ltnp"],
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError:
        return None

    pid_pattern = re.compile(r"pid=(\d+)")
    port_pattern = re.compile(rf":{port}\b")
    for line in res.stdout.splitlines():
        if not port_pattern.search(line):
            continue
        pid_match = pid_pattern.search(line)
        if pid_match:
            return int(pid_match.group(1))
    return None


def _get_process_args(pid):
    try:
        res = subprocess.run(
            ["ps", "-p", str(pid), "-o", "args="],
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError:
        return ""
    return res.stdout.strip()


def _is_this_dashboard_process(pid):
    args = _get_process_args(pid)
    return bool(re.search(r"\bpython(?:3(?:\.\d+)?)?\b.*\bweb/flask_app\.py\b", args))


def _terminate_pid(pid, timeout_sec=5.0):
    try:
        os.kill(pid, signal.SIGTERM)
    except OSError:
        return True

    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        try:
            os.kill(pid, 0)
            time.sleep(0.2)
        except OSError:
            return True

    try:
        os.kill(pid, signal.SIGKILL)
    except OSError:
        return True
    time.sleep(0.2)
    try:
        os.kill(pid, 0)
        return False
    except OSError:
        return True


def _find_next_free_port(start_port, host="0.0.0.0", max_tries=200):
    for port in range(start_port, start_port + max_tries):
        if not _is_port_in_use(port, host):
            return port
    return None


@app.after_request
def apply_response_headers(response):
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault("Cache-Control", "no-store")
    return response


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/health")
def api_health():
    return jsonify(
        {
            "status": "ok",
            "server_time": datetime.now().isoformat(timespec="seconds"),
        }
    )


@app.route("/api/config")
def api_config():
    return jsonify(
        {
            "default_trigger_file": str(config.DEFAULT_TRIGGER_FILE),
            "default_trigger_selection": str(config.DEFAULT_TRIGGER_FILE),
            "default_rate_field": config.DEFAULT_RATE_FIELD,
            "rate_field_options": config.RATE_FIELD_OPTIONS,
            "default_current_ls_window": config.DEFAULT_CURRENT_LS_WINDOW,
            "default_projection_plot_ls_limit": config.DEFAULT_PROJECTION_PLOT_LS_LIMIT,
            "default_refresh_seconds": config.DEFAULT_REFRESH_SECONDS,
            "export_dir": str(config.EXPORT_DIR),
            "projection_settings_path": str(config.PROJECTION_SETTINGS_FILE),
            "dashboard_reference_settings_path": str(config.DASHBOARD_REFERENCE_SETTINGS_FILE),
        }
    )


@app.route("/api/projection-settings", methods=["GET"])
def api_projection_settings_get():
    return jsonify(
        {
            "path": str(config.PROJECTION_SETTINGS_FILE),
            "settings": _read_projection_settings(),
        }
    )


@app.route("/api/projection-settings", methods=["PUT"])
def api_projection_settings_put():
    payload = request.get_json(silent=True) or {}
    settings = payload.get("settings", payload)
    if not isinstance(settings, dict):
        return jsonify({"error": "Projection settings must be a JSON object."}), 400
    clean = _write_projection_settings(settings)
    return jsonify(
        {
            "status": "saved",
            "path": str(config.PROJECTION_SETTINGS_FILE),
            "settings": clean,
        }
    )


@app.route("/api/dashboard-reference-settings", methods=["GET"])
def api_dashboard_reference_settings_get():
    return jsonify(
        {
            "path": str(config.DASHBOARD_REFERENCE_SETTINGS_FILE),
            "settings": _read_dashboard_reference_settings(),
        }
    )


@app.route("/api/dashboard-reference-settings", methods=["PUT"])
def api_dashboard_reference_settings_put():
    payload = request.get_json(silent=True) or {}
    settings = payload.get("settings", payload)
    if not isinstance(settings, dict):
        return jsonify({"error": "Dashboard reference settings must be a JSON object."}), 400
    clean = _write_dashboard_reference_settings(settings)
    return jsonify(
        {
            "status": "saved",
            "path": str(config.DASHBOARD_REFERENCE_SETTINGS_FILE),
            "settings": clean,
        }
    )


@app.route("/api/l1-prescale-table")
def api_l1_prescale_table():
    run = _int_arg("run", None, minimum=1)
    if run is None:
        current = oms_data.get_current_global_run()
        run = int(current["run_number"])
    summary = oms_data.get_run_summary(int(run))
    table = oms_data.get_l1_prescale_table(int(run))
    lumi = oms_data.get_lumi_summary(int(run))
    return jsonify(
        {
            "run": _public_run_summary(summary),
            "lumi": lumi,
            "count": int(len(table)),
            "rows": _df_records(table),
        }
    )


@app.route("/api/rate-snapshot")
def api_rate_snapshot():
    run = _int_arg("run", None, minimum=1)
    reference_run = _int_arg("reference_run", None, minimum=1)
    rate_field = _default_rate_field(request.args.get("rate_field"))

    ls_mode = str(request.args.get("ls_mode", "run") or "run").strip().lower()
    reference_ls_mode = str(
        request.args.get("reference_ls_mode", "run") or "run"
    ).strip().lower()

    if run is None:
        current = oms_data.get_current_global_run()
        run = int(current["run_number"])

    def parse_ls_selection(mode, min_key, max_key, single_key):
        ls_min = None
        ls_max = None
        if mode == "range":
            ls_min_value = _int_arg(min_key, None, minimum=1)
            ls_max_value = _int_arg(max_key, None, minimum=1)
            if (
                ls_min_value is not None
                and ls_max_value is not None
                and ls_min_value > ls_max_value
            ):
                ls_min_value, ls_max_value = ls_max_value, ls_min_value
            ls_min = ls_min_value
            ls_max = ls_max_value
        elif mode == "single":
            single_ls = _int_arg(single_key, None, minimum=1)
            ls_min = single_ls
            ls_max = single_ls
        else:
            mode = "run"
        return mode, ls_min, ls_max

    def selection_label(mode, ls_min_value, ls_max_value):
        if mode == "range":
            return f"LS {ls_min_value or '-'}-{ls_max_value or '-'}"
        if mode == "single":
            return f"LS {ls_min_value or '-'}"
        return "Run summary"

    def averaged_ls_rates(target_run, seeds, ls_min_value, ls_max_value):
        rates = {}
        points = {}
        if not seeds:
            return rates, points
        ls_rates = oms_data.get_l1_ls_rates(
            int(target_run),
            seeds,
            ls_min_value,
            ls_max_value,
            rate_field,
        )
        if ls_rates.empty:
            return rates, points
        ls_rates["rate"] = pd.to_numeric(ls_rates["rate"], errors="coerce")
        grouped = ls_rates.dropna(subset=["rate"]).groupby("pathname")["rate"].agg(["mean", "count"])
        rates = {str(pathname): float(row["mean"]) for pathname, row in grouped.iterrows()}
        points = {str(pathname): int(row["count"]) for pathname, row in grouped.iterrows()}
        return rates, points

    ls_mode, ls_min, ls_max = parse_ls_selection(
        ls_mode,
        "ls_min",
        "ls_max",
        "ls",
    )
    reference_ls_mode, reference_ls_min, reference_ls_max = parse_ls_selection(
        reference_ls_mode,
        "reference_ls_min",
        "reference_ls_max",
        "reference_ls",
    )

    summary = oms_data.get_run_summary(int(run))
    lumi = oms_data.get_lumi_summary(int(run), ls_min, ls_max)
    table = oms_data.get_l1_prescale_table(int(run))
    l1_summary = oms_data.get_l1_trigger_summary(int(run))
    deadtimes = oms_data.get_deadtime_summary(int(run))
    monitoring_path = _monitoring_seed_file()
    monitoring_seeds = oms_data.load_trigger_list(monitoring_path) if monitoring_path.exists() else []

    if not table.empty and monitoring_seeds:
        wanted = {seed.strip() for seed in monitoring_seeds if seed.strip()}
        table = table[table["name"].isin(wanted)].copy()

    rate_label = next(
        (label for label, field in config.RATE_FIELD_OPTIONS.items() if field == rate_field),
        rate_field,
    )

    selected_rates = {}
    selected_points = {}
    if ls_mode in {"range", "single"}:
        selected_rates, selected_points = averaged_ls_rates(
            int(run),
            monitoring_seeds,
            ls_min,
            ls_max,
        )

    reference_payload = None
    reference_rates = {}
    reference_points = {}
    if reference_run is not None:
        reference_summary = oms_data.get_run_summary(int(reference_run))
        reference_lumi = oms_data.get_lumi_summary(
            int(reference_run),
            reference_ls_min,
            reference_ls_max,
        )
        if reference_ls_mode in {"range", "single"}:
            reference_rates, reference_points = averaged_ls_rates(
                int(reference_run),
                monitoring_seeds,
                reference_ls_min,
                reference_ls_max,
            )
        else:
            reference_table = oms_data.get_l1_prescale_table(int(reference_run))
            for reference_row in _df_records(reference_table):
                reference_name = reference_row.get("name")
                if reference_name:
                    reference_rates[str(reference_name)] = reference_row.get(rate_field)

        reference_payload = {
            "run": _public_run_summary(reference_summary),
            "lumi": reference_lumi,
            "selection": {
                "mode": reference_ls_mode,
                "ls_min": reference_ls_min,
                "ls_max": reference_ls_max,
                "label": selection_label(reference_ls_mode, reference_ls_min, reference_ls_max),
            },
        }

    rows = []
    for row in _df_records(table):
        name = row.get("name")
        selected_rate = selected_rates.get(str(name)) if ls_mode in {"range", "single"} else row.get(rate_field)
        reference_rate = reference_rates.get(str(name)) if reference_run is not None else None
        selected_rate_num = _float_or_none(selected_rate)
        reference_rate_num = _float_or_none(reference_rate)
        raw_ratio = None
        if selected_rate_num is not None and reference_rate_num not in (None, 0):
            raw_ratio = selected_rate_num / reference_rate_num
        rows.append(
            {
                "current_run": run_info.get("run_number"),
                "bit": row.get("bit"),
                "name": name,
                "rate": selected_rate,
                "reference_rate": reference_rate,
                "raw_ratio": raw_ratio,
                "rate_field": rate_field,
                "rate_label": rate_label,
                "points": selected_points.get(str(name)) if ls_mode in {"range", "single"} else None,
                "reference_points": (
                    reference_points.get(str(name))
                    if reference_run is not None and reference_ls_mode in {"range", "single"}
                    else None
                ),
                "initial_prescale": row.get("initial_prescale"),
                "final_prescale": row.get("final_prescale"),
            }
        )

    return jsonify(
        {
            "run": _public_run_summary(summary),
            "lumi": lumi,
            "reference": reference_payload,
            "selection": {
                "mode": ls_mode,
                "ls_min": ls_min,
                "ls_max": ls_max,
                "label": selection_label(ls_mode, ls_min, ls_max),
            },
            "rate_field": rate_field,
            "rate_label": rate_label,
            "l1_triggers": _df_records(l1_summary),
            "deadtimes": _df_records(deadtimes),
            "monitoring_path": str(monitoring_path),
            "monitoring_count": len(monitoring_seeds),
            "rows": rows,
        }
    )


@app.route("/api/exports/<path:filename>")
def api_export_file(filename):
    safe_name = os.path.basename(filename)
    if safe_name != filename:
        return jsonify({"error": "Invalid export filename"}), 400
    path = config.EXPORT_DIR / safe_name
    if not path.exists():
        return jsonify({"error": "Export file not found"}), 404
    return send_from_directory(
        str(config.EXPORT_DIR),
        safe_name,
        mimetype="text/csv",
        as_attachment=True,
    )


@app.route("/api/exports")
def api_exports():
    config.EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    files = []
    for path in sorted(config.EXPORT_DIR.glob("*.csv"), key=lambda p: p.stat().st_mtime, reverse=True):
        stat = path.stat()
        files.append(
            {
                "filename": path.name,
                "path": str(path),
                "url": f"/api/exports/{path.name}",
                "size_bytes": stat.st_size,
                "modified_time": datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds"),
            }
        )
    return jsonify(
        {
            "export_dir": str(config.EXPORT_DIR),
            "count": len(files),
            "files": files,
        }
    )


@app.route("/api/export-projection", methods=["POST"])
def api_export_projection():
    payload = request.get_json(silent=True) or {}
    kind = str(payload.get("kind") or "latest").strip()
    if kind not in {"latest", "full"}:
        return jsonify({"error": "Invalid export kind"}), 400
    rows = payload.get("rows") or []
    if not isinstance(rows, list) or not rows:
        return jsonify({"error": "No rows to export"}), 400
    context = payload.get("context") or {}
    export = _write_projection_export(kind, rows, context)
    return jsonify({"status": "saved", "export": export})


@app.route("/api/monitoring-seeds", methods=["GET"])
def api_monitoring_seeds():
    path = _monitoring_seed_file()
    seeds = oms_data.load_trigger_list(path) if path.exists() else []
    return jsonify(
        {
            "path": str(path),
            "count": len(seeds),
            "seeds": seeds,
        }
    )


@app.route("/api/monitoring-seeds", methods=["PUT"])
def api_monitoring_seeds_update():
    payload = request.get_json(silent=True) or {}
    raw_seeds = payload.get("seeds")
    if raw_seeds is None and "text" in payload:
        raw_seeds = str(payload.get("text") or "").splitlines()
    if not isinstance(raw_seeds, list):
        return jsonify({"error": "Field 'seeds' must be a list."}), 400
    try:
        seeds = _normalize_seed_list(raw_seeds)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    _write_monitoring_seed_file(seeds)
    return jsonify(
        {
            "path": str(_monitoring_seed_file()),
            "count": len(seeds),
            "seeds": seeds,
        }
    )


@app.route("/api/l1-seeds")
def api_l1_seeds():
    run = _int_arg("run", None, minimum=1)
    rate_field = _default_rate_field(request.args.get("rate_field"))
    if run is None:
        current = oms_data.get_current_global_run()
        run = int(current["run_number"])

    summary = oms_data.get_run_summary(int(run))
    table = oms_data.get_l1_prescale_table(int(run))
    if not table.empty and "name" in table.columns:
        seeds = sorted(str(seed) for seed in table["name"].dropna().unique())
        return jsonify(
            {
                "run": int(run),
                "ls": None,
                "source": "prescale_table",
                "count": len(seeds),
                "seeds": seeds,
            }
        )

    last_ls = int(summary.get("last_lumisection_number") or 0)
    if last_ls <= 0:
        return jsonify({"run": int(run), "ls": None, "source": "none", "count": 0, "seeds": []})

    seed_ls = _latest_stable_lumisection(int(run), last_ls) or last_ls

    rates = oms_data.get_l1_ls_rates(
        int(run),
        [],
        ls_min=seed_ls,
        ls_max=seed_ls,
        rate_field=rate_field,
    )
    if rates.empty:
        seeds = []
    else:
        seeds = sorted(str(seed) for seed in rates["pathname"].dropna().unique())
    return jsonify(
        {
            "run": int(run),
            "ls": seed_ls,
            "source": "stable_lumisection" if seed_ls != last_ls else "last_lumisection",
            "count": len(seeds),
            "seeds": seeds,
        }
    )


@app.route("/api/dashboard")
def api_dashboard():
    trigger_file = request.args.get("trigger_file") or "ALL"
    window = _int_arg("window", config.DEFAULT_CURRENT_LS_WINDOW, minimum=1)
    rate_field = _default_rate_field(request.args.get("rate_field"))
    include_rates = request.args.get("include_rates", "1") != "0"

    current = oms_data.get_current_global_run()
    summary = oms_data.get_run_summary(int(current["run_number"]))
    triggers, trigger_label, all_triggers = _resolve_trigger_selection(trigger_file)
    last_ls = int(summary.get("last_lumisection_number") or 0)

    rates = pd.DataFrame()
    if include_rates and last_ls > 0:
        ls_min = max(1, last_ls - int(window) + 1)
        rates = oms_data.get_l1_ls_rates(
            int(summary["run_number"]),
            triggers,
            ls_min=ls_min,
            ls_max=last_ls,
            rate_field=rate_field,
        )

    latest = projection.latest_by_pathname(rates)
    return jsonify(
        {
            "run": _public_run_summary(summary),
            "is_live": summary.get("end_time") is None,
            "trigger_file": trigger_label,
            "trigger_count": int(rates["pathname"].nunique()) if not rates.empty else len(triggers),
            "all_triggers": all_triggers,
            "rates_loaded": include_rates,
            "rate_field": rate_field,
            "latest": _df_records(latest),
            "series": _df_records(rates),
        }
    )


@app.route("/api/dashboard/reference-ratio", methods=["POST"])
def api_dashboard_reference_ratio():
    payload = request.get_json(silent=True) or {}
    reference_run = _payload_int(payload, "reference_run", minimum=1)
    if reference_run is None:
        return jsonify({"error": "Missing required field: reference_run"}), 400

    max_lumisections = _payload_int(payload, "max_lumisections", 120, minimum=1)
    rate_field = _default_rate_field(payload.get("rate_field"))
    triggers = oms_data.load_trigger_list(_monitoring_seed_file())
    if not triggers:
        return jsonify({"error": "Monitoring seed list is empty."}), 400

    current = oms_data.get_current_global_run()
    current_run = int(current["run_number"])
    ref_summary = oms_data.get_run_summary(int(reference_run))
    cur_summary = oms_data.get_run_summary(current_run)
    current_last_ls = int(cur_summary.get("last_lumisection_number") or 0)
    if current_last_ls <= 0:
        return jsonify(
            {
                "context": {
                    "reference_run": int(reference_run),
                    "current_run": current_run,
                    "trigger_count": len(triggers),
                    "rate_field": rate_field,
                    "row_count": 0,
                },
                "rows": [],
            }
        )

    try:
        reference_window = _resolve_projection_lumi_window(
            payload,
            "reference",
            ref_summary,
            "range",
        )
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    reference_df = oms_data.get_l1_ls_rates(
        int(reference_run),
        triggers,
        ls_min=reference_window["ls_min"],
        ls_max=reference_window["ls_max"],
        rate_field=rate_field,
    )
    reference_df = _apply_lumi_override(reference_df, reference_window["hardcoded_lumi"])
    reference_df = _filtered_plot_frame(reference_df, stable_only=True)

    scan_window = max(int(max_lumisections) * 4, int(max_lumisections), 40)
    current_ls_min = max(1, current_last_ls - scan_window + 1)
    current_df = oms_data.get_l1_ls_rates(
        current_run,
        triggers,
        ls_min=current_ls_min,
        ls_max=current_last_ls,
        rate_field=rate_field,
    )
    current_df = _filtered_plot_frame(current_df, stable_only=False)
    current_df = _trim_latest_lumisections(current_df, max_lumisections)

    reference_lumi_stats = _lumi_stats_from_frame(reference_df)
    current_lumi_stats = _lumi_stats_from_frame(current_df)
    projected = projection.apply_spreadsheet_projection(reference_df, current_df)
    if not projected.empty:
        projected = projected.sort_values(["lumisection", "pathname"])

    current_lumisections = []
    if not current_df.empty and "lumisection" in current_df.columns:
        current_lumisections = sorted(
            int(value)
            for value in pd.to_numeric(current_df["lumisection"], errors="coerce").dropna().unique()
        )

    context = {
        "reference_run": int(reference_run),
        "reference_lumi_mode": reference_window["mode"],
        "reference_ls_min": reference_window["ls_min"],
        "reference_ls_max": reference_window["ls_max"],
        "reference_anchor_lumisection": reference_window["anchor_lumisection"],
        "reference_anchor_kind": reference_window["anchor_kind"],
        "reference_inst_lumi_avg": reference_lumi_stats["average"],
        "reference_inst_lumi_latest": reference_lumi_stats["latest"],
        "current_run": current_run,
        "current_ls_min": current_lumisections[0] if current_lumisections else None,
        "current_ls_max": current_lumisections[-1] if current_lumisections else None,
        "current_inst_lumi_avg": current_lumi_stats["average"],
        "current_inst_lumi_latest": current_lumi_stats["latest"],
        "stable_only": False,
        "max_lumisections": int(max_lumisections),
        "trigger_count": len(triggers),
        "rate_field": rate_field,
        "row_count": int(len(projected)),
    }
    return jsonify(
        {
            "context": context,
            "reference_run": _public_run_summary(ref_summary),
            "current_run": _public_run_summary(cur_summary),
            "rows": _df_records(projected),
        }
    )


@app.route("/api/projection", methods=["POST"])
def api_projection():
    started_at = time.monotonic()

    def log_step(label):
        elapsed = time.monotonic() - started_at
        print(f"[projection] {label} ({elapsed:.1f}s)", flush=True)

    payload = request.get_json(silent=True) or {}
    trigger_file = payload.get("trigger_file") or "ALL"
    rate_field = _default_rate_field(payload.get("rate_field"))
    stable_only = bool(payload.get("stable_only", True))
    triggers, trigger_label, all_triggers = _resolve_trigger_selection(trigger_file)
    log_step(f"start trigger={trigger_label} all={all_triggers}")

    reference_run = _payload_int(payload, "reference_run", minimum=1)
    current_run = _payload_int(payload, "current_run", minimum=1)

    if reference_run is None:
        return jsonify({"error": "Missing required field: reference_run"}), 400

    if current_run is None:
        current = oms_data.get_current_global_run()
        current_run = int(current["run_number"])

    log_step("fetch run summaries")
    ref_summary = oms_data.get_run_summary(int(reference_run))
    cur_summary = oms_data.get_run_summary(int(current_run))

    try:
        reference_window = _resolve_projection_lumi_window(
            payload,
            "reference",
            ref_summary,
            "range",
        )
        current_window = _resolve_projection_lumi_window(
            payload,
            "current",
            cur_summary,
            "latest_window",
        )
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    log_step(
        f"fetch reference rates run={reference_run} "
        f"ls={reference_window['ls_min']}-{reference_window['ls_max']}"
    )
    reference_df = oms_data.get_l1_ls_rates(
        int(reference_run),
        triggers,
        ls_min=reference_window["ls_min"],
        ls_max=reference_window["ls_max"],
        rate_field=rate_field,
    )
    log_step(f"reference rows={len(reference_df)}")
    log_step(
        f"fetch current rates run={current_run} "
        f"ls={current_window['ls_min']}-{current_window['ls_max']}"
    )
    current_df = oms_data.get_l1_ls_rates(
        int(current_run),
        triggers,
        ls_min=current_window["ls_min"],
        ls_max=current_window["ls_max"],
        rate_field=rate_field,
    )
    log_step(f"current rows={len(current_df)}")
    reference_df = _apply_lumi_override(reference_df, reference_window["hardcoded_lumi"])
    current_df = _apply_lumi_override(current_df, current_window["hardcoded_lumi"])
    if stable_only:
        reference_df = _filtered_plot_frame(reference_df, stable_only=True)
        current_df = _filtered_plot_frame(current_df, stable_only=True)

    reference_lumi_stats = _lumi_stats_from_frame(reference_df)
    current_lumi_stats = _lumi_stats_from_frame(current_df)

    log_step("apply spreadsheet projection")
    plot_limit = _payload_int(
        payload,
        "projection_plot_ls_limit",
        config.DEFAULT_PROJECTION_PLOT_LS_LIMIT,
        minimum=1,
    )
    current_last_ls = int(cur_summary.get("last_lumisection_number") or 0)
    current_plot_df = pd.DataFrame()
    if current_last_ls > 0:
        log_step(f"fetch recorded LS list run={current_run} ls=1-{current_last_ls}")
        plot_lumi_df = oms_data.get_lumisections(int(current_run), 1, current_last_ls)
        plot_lumi_df = _trim_latest_lumisections(plot_lumi_df, plot_limit)
        plot_ls = []
        if not plot_lumi_df.empty and "lumisection" in plot_lumi_df.columns:
            plot_ls = sorted(
                int(value)
                for value in pd.to_numeric(plot_lumi_df["lumisection"], errors="coerce").dropna().unique()
            )
        if plot_ls:
            log_step(
                f"fetch plot rates run={current_run} "
                f"recorded ls={plot_ls[0]}-{plot_ls[-1]} "
                f"count={len(plot_ls)}"
            )
            current_plot_df = oms_data.get_l1_ls_rates(
                int(current_run),
                triggers,
                ls_min=plot_ls[0],
                ls_max=plot_ls[-1],
                rate_field=rate_field,
            )
            current_plot_df = _filtered_plot_frame(current_plot_df, stable_only=False)
            current_plot_df = current_plot_df[current_plot_df["lumisection"].isin(plot_ls)].copy()
            log_step(f"plot rows={len(current_plot_df)}")

    projected = projection.apply_spreadsheet_projection(reference_df, current_plot_df)
    latest = projection.apply_spreadsheet_projection_summary(
        reference_df,
        current_df,
    )
    plot_lumisections = []
    if not current_plot_df.empty and "lumisection" in current_plot_df.columns:
        plot_lumisections = sorted(
            int(value)
            for value in pd.to_numeric(current_plot_df["lumisection"], errors="coerce").dropna().unique()
        )
    context = {
        "trigger_file": trigger_label,
        "trigger_count": int(projected["pathname"].nunique()) if not projected.empty else len(triggers),
        "all_triggers": all_triggers,
        "rate_field": rate_field,
        "stable_only": stable_only,
        "reference_run": int(reference_run),
        "reference_lumi_mode": reference_window["mode"],
        "reference_ls_min": reference_window["ls_min"],
        "reference_ls_max": reference_window["ls_max"],
        "reference_anchor_lumisection": reference_window["anchor_lumisection"],
        "reference_anchor_kind": reference_window["anchor_kind"],
        "reference_hardcoded_lumi": reference_window["hardcoded_lumi"],
        "reference_inst_lumi_avg": reference_lumi_stats["average"],
        "reference_inst_lumi_latest": reference_lumi_stats["latest"],
        "reference_lumi_points": reference_lumi_stats["points"],
        "current_run": int(current_run),
        "current_lumi_mode": current_window["mode"],
        "current_ls_min": current_window["ls_min"],
        "current_ls_max": current_window["ls_max"],
        "current_anchor_lumisection": current_window["anchor_lumisection"],
        "current_anchor_kind": current_window["anchor_kind"],
        "current_hardcoded_lumi": current_window["hardcoded_lumi"],
        "current_inst_lumi_avg": current_lumi_stats["average"],
        "current_inst_lumi_latest": current_lumi_stats["latest"],
        "current_lumi_points": current_lumi_stats["points"],
        "plot_stable_only": False,
        "plot_includes_unstable": True,
        "plot_ls_limit": int(plot_limit),
        "plot_ls_min": plot_lumisections[0] if plot_lumisections else None,
        "plot_ls_max": plot_lumisections[-1] if plot_lumisections else None,
        "plot_lumisection_count": len(plot_lumisections),
    }
    log_step("done")

    return jsonify(
        {
            "context": context,
            "reference_run": _public_run_summary(ref_summary),
            "current_run": _public_run_summary(cur_summary),
            "latest": _df_records(latest),
            "series": _df_records(projected),
            "exports": {},
        }
    )


@app.route("/api/rate-plots", methods=["POST"])
def api_rate_plots():
    payload = request.get_json(silent=True) or {}
    trigger_file = payload.get("trigger_file") or str(_monitoring_seed_file())
    rate_field = _default_rate_field(payload.get("rate_field"))
    stable_only = bool(payload.get("stable_only", True))
    triggers, trigger_label, all_triggers = _resolve_trigger_selection(trigger_file)

    reference_run = _payload_int(payload, "reference_run", minimum=1)
    comparison_runs = _payload_run_list(payload, "current_runs")
    current_run = _payload_int(payload, "current_run", minimum=1)
    if reference_run is None:
        return jsonify({"error": "Missing required field: reference_run"}), 400
    if not comparison_runs and current_run is not None:
        comparison_runs = [int(current_run)]
    if not comparison_runs:
        current = oms_data.get_current_global_run()
        comparison_runs = [int(current["run_number"])]

    ref_summary = oms_data.get_run_summary(int(reference_run))
    reference_df = oms_data.get_l1_ls_rates(
        int(reference_run),
        triggers,
        ls_min=None,
        ls_max=None,
        rate_field=rate_field,
    )
    reference_df = _filtered_plot_frame(reference_df, stable_only=stable_only)

    rows = []
    for label, frame in [(f"Reference {int(reference_run)}", reference_df)]:
        if frame.empty:
            continue
        for row in _df_records(frame):
            row["sample"] = label
            rows.append(row)

    comparison_windows = {}
    for run in comparison_runs:
        cur_summary = oms_data.get_run_summary(int(run))
        current_df = oms_data.get_l1_ls_rates(
            int(run),
            triggers,
            ls_min=None,
            ls_max=None,
            rate_field=rate_field,
        )
        current_df = _filtered_plot_frame(current_df, stable_only=stable_only)
        comparison_windows[int(run)] = {
            "mode": "all_lumisections",
            "ls_min": None,
            "ls_max": int(cur_summary.get("last_lumisection_number") or 0) or None,
        }
        if current_df.empty:
            continue
        for row in _df_records(current_df):
            row["sample"] = f"Run {int(run)}"
            rows.append(row)

    return jsonify(
        {
            "context": {
                "rate_field": rate_field,
                "stable_only": stable_only,
                "trigger_file": trigger_label,
                "all_triggers": all_triggers,
                "trigger_count": len(triggers),
                "reference_run": int(reference_run),
                "reference_lumi_mode": "all_lumisections",
                "reference_ls_min": None,
                "reference_ls_max": int(ref_summary.get("last_lumisection_number") or 0) or None,
                "comparison_runs": comparison_runs,
                "comparison_windows": comparison_windows,
            },
            "rows": rows,
        }
    )


@app.errorhandler(404)
def not_found(error):
    if request.path.startswith("/api/"):
        return jsonify({"error": "Not found"}), 404
    return render_template("index.html"), 404


@app.errorhandler(500)
def server_error(error):
    return jsonify({"error": "Internal server error", "detail": str(error)}), 500


if __name__ == "__main__":
    host = os.environ.get("OMS_DASHBOARD_HOST", "0.0.0.0")
    requested_port = int(os.environ.get("OMS_DASHBOARD_PORT", "8502"))
    run_port = requested_port

    if _is_port_in_use(requested_port, host):
        listener_pid = _get_listener_pid(requested_port)
        if listener_pid and _is_this_dashboard_process(listener_pid):
            print(
                f"[startup] Port {requested_port} is used by dashboard PID {listener_pid}. "
                "Stopping it..."
            )
            if not _terminate_pid(listener_pid):
                run_port = _find_next_free_port(requested_port + 1, host=host)
        else:
            run_port = _find_next_free_port(requested_port + 1, host=host)
        if run_port is None:
            raise RuntimeError(f"No free port found near {requested_port}.")
        if run_port != requested_port:
            print(f"[startup] Port {requested_port} is occupied. Using {run_port}.")

    print(f"[startup] Starting OMS L1 dashboard on {host}:{run_port}")
    app.run(host=host, port=run_port, debug=False)
