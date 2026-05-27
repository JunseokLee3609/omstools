from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

import pandas as pd


L1_RATE_COLUMNS = [
    "run",
    "bit",
    "pathname",
    "lumisection",
    "start_time",
    "end_time",
    "init_lumi",
    "beams_stable",
    "rate",
    "rate_field",
]

L1_PRESCALE_COLUMNS = [
    "bit",
    "name",
    "mask",
    "pre_dt_before_prescale_rate",
    "pre_dt_before_prescale_counter",
    "pre_dt_rate",
    "pre_dt_counter",
    "inferred_prescale",
    "post_dt_rate",
    "post_dt_counter",
    "post_dt_hlt_rate",
    "post_dt_hlt_counter",
    "initial_prescale_index",
    "initial_prescale_name",
    "initial_prescale",
    "final_prescale_index",
    "final_prescale_name",
    "final_prescale",
]

L1_TRIGGER_SUMMARY_COLUMNS = ["name", "rate", "counter"]
DEADTIME_COLUMNS = ["name", "percent", "counter"]


PathLike = Union[str, Path]


def load_trigger_list(path: PathLike) -> List[str]:
    trigger_path = Path(path).expanduser()
    with trigger_path.open() as handle:
        return [
            line.strip()
            for line in handle
            if line.strip() and not line.strip().startswith("#")
        ]


def _oms():
    import util.oms as oms

    return oms


def _first_data(query: Any) -> Optional[Dict[str, Any]]:
    data = query.data().json().get("data", [])
    return data[0] if data else None


def _paged_data(query: Any, per_page: int = 1000) -> List[Dict[str, Any]]:
    rows = []  # type: List[Dict[str, Any]]
    page = 1
    while True:
        query.paginate(page=page, per_page=per_page)
        payload = query.data().json()
        rows.extend(payload.get("data", []))
        links = payload.get("links") or {}
        if not links.get("next"):
            break
        page += 1
    return rows


def _normalize_run(data: Dict[str, Any]) -> Dict[str, Any]:
    attr = data.get("attributes", {})
    run_number = attr.get("run_number") or data.get("id")
    summary = {
        "id": data.get("id"),
        "run_number": int(run_number) if run_number is not None else None,
        "fill_number": attr.get("fill_number"),
        "start_time": attr.get("start_time"),
        "end_time": attr.get("end_time"),
        "duration": attr.get("duration"),
        "stable_beam": attr.get("stable_beam"),
        "last_lumisection_number": attr.get("last_lumisection_number"),
        "l1_rate": attr.get("l1_rate"),
        "l1_menu": attr.get("l1_menu"),
        "l1_key": attr.get("l1_key"),
        "hlt_key": attr.get("hlt_key"),
        "hlt_physics_throughput": attr.get("hlt_physics_throughput"),
        "initial_prescale_index": attr.get("initial_prescale_index"),
        "trigger_mode": attr.get("trigger_mode"),
        "delivered_lumi": attr.get("delivered_lumi"),
        "recorded_lumi": attr.get("recorded_lumi"),
        "init_lumi": attr.get("init_lumi"),
        "end_lumi": attr.get("end_lumi"),
        "era": attr.get("era"),
        "sequence": attr.get("sequence"),
        "raw": data,
    }
    return summary


def get_current_global_run() -> Dict[str, Any]:
    oms = _oms()
    q = oms.omsapi.query("runs")
    q.set_verbose(False)
    q.attrs(
        [
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
            "delivered_lumi",
            "recorded_lumi",
            "init_lumi",
            "end_lumi",
            "era",
            "sequence",
        ]
    )
    q.filter("sequence", "GLOBAL-RUN")
    q.sort("run_number", asc=False).paginate(per_page=1)
    data = _first_data(q)
    if data is None:
        raise RuntimeError("No GLOBAL-RUN entry was returned by OMS.")
    return _normalize_run(data)


def get_run_summary(run: int) -> Dict[str, Any]:
    oms = _oms()
    q = oms.omsapi.query("runs")
    q.set_verbose(False)
    q.filter("run_number", int(run))
    q.paginate(per_page=1)
    data = _first_data(q)
    if data is None:
        raise RuntimeError(f"Run {run} was not found in OMS.")

    summary = _normalize_run(data)
    fill_number = summary.get("fill_number")
    summary["bunches_colliding"] = (
        get_bunches_colliding(int(fill_number)) if fill_number is not None else None
    )
    return summary


def get_bunches_colliding(fill: int) -> Optional[int]:
    oms = _oms()
    for category in ("filldetailx", "fills"):
        try:
            q = oms.omsapi.query(category)
            q.set_verbose(False)
            q.attrs(["fill_number", "bunches_colliding"])
            q.filter("fill_number", int(fill))
            q.paginate(per_page=1)
            data = _first_data(q)
            if data:
                bunches = data.get("attributes", {}).get("bunches_colliding")
                if bunches is not None:
                    return int(bunches)
        except Exception:
            continue

    try:
        q = oms.omsapi.query("bunches")
        q.set_verbose(False)
        q.filter("fill_number", int(fill))
        rows = _paged_data(q, per_page=10000)
        colliding = 0
        for row in rows:
            attr = row.get("attributes", {})
            if attr.get("beam_1_configured") and attr.get("beam_2_configured"):
                colliding += 1
        return colliding or None
    except Exception:
        return None


def _get_lumisections(run: int, ls_min: Optional[int], ls_max: Optional[int]) -> pd.DataFrame:
    oms = _oms()
    q = oms.omsapi.query("lumisections")
    q.set_verbose(False)
    q.attrs(
        [
            "run_number",
            "lumisection_number",
            "start_time",
            "end_time",
            "init_lumi",
            "beams_stable",
        ]
    )
    q.filter("run_number", int(run))
    if ls_min is not None:
        q.filter("lumisection_number", int(ls_min), "GE")
    if ls_max is not None:
        q.filter("lumisection_number", int(ls_max), "LE")
    q.sort("lumisection_number", asc=True)
    rows = _paged_data(q, per_page=1000)

    records = []
    for row in rows:
        attr = row.get("attributes", {})
        ls = attr.get("lumisection_number")
        if ls is None:
            continue
        if ls_min is not None and ls < int(ls_min):
            continue
        if ls_max is not None and ls > int(ls_max):
            continue
        records.append(
            {
                "run": int(run),
                "lumisection": int(ls),
                "start_time": attr.get("start_time"),
                "end_time": attr.get("end_time"),
                "init_lumi": attr.get("init_lumi"),
                "beams_stable": attr.get("beams_stable"),
            }
        )
    return pd.DataFrame(records)


def get_lumisections(
    run: int,
    ls_min: Optional[int] = None,
    ls_max: Optional[int] = None,
) -> pd.DataFrame:
    return _get_lumisections(
        int(run),
        int(ls_min) if ls_min is not None else None,
        int(ls_max) if ls_max is not None else None,
    ).copy()


def get_lumi_summary(
    run: int,
    ls_min: Optional[int] = None,
    ls_max: Optional[int] = None,
) -> Dict[str, Any]:
    lumisections = _get_lumisections(run, ls_min, ls_max)
    if lumisections.empty:
        return {
            "ls_min": ls_min,
            "ls_max": ls_max,
            "n_lumisections": 0,
            "latest_lumisection": None,
            "latest_init_lumi": None,
            "average_init_lumi": None,
            "stable_average_init_lumi": None,
        }

    clean = lumisections.copy()
    clean["init_lumi"] = pd.to_numeric(clean["init_lumi"], errors="coerce")
    ordered = clean.sort_values("lumisection")
    latest = ordered.dropna(subset=["init_lumi"]).tail(1)
    stable = ordered[ordered["beams_stable"] == True]

    return {
        "ls_min": int(ordered["lumisection"].min()),
        "ls_max": int(ordered["lumisection"].max()),
        "n_lumisections": int(len(ordered)),
        "latest_lumisection": int(latest.iloc[0]["lumisection"]) if not latest.empty else None,
        "latest_init_lumi": float(latest.iloc[0]["init_lumi"]) if not latest.empty else None,
        "average_init_lumi": float(ordered["init_lumi"].mean()) if ordered["init_lumi"].notna().any() else None,
        "stable_average_init_lumi": float(stable["init_lumi"].mean())
        if not stable.empty and stable["init_lumi"].notna().any()
        else None,
    }


def _to_float(value: Any, default: float = 0.0) -> float:
    if value in (None, ""):
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _to_int_or_none(value: Any) -> Optional[int]:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _fill_details_by_number(start_year: int, end_year: int) -> Dict[int, Dict[str, Any]]:
    oms = _oms()
    q = oms.omsapi.query("fills")
    q.set_verbose(False)
    q.set_validation(False)
    q.attrs(
        [
            "fill_number",
            "start_time",
            "end_time",
            "era",
            "fill_type_runtime",
            "fill_type_party1",
            "fill_type_party2",
            "stable_beams",
            "bunches_colliding",
            "bunches_target",
            "injection_scheme",
            "delivered_lumi",
            "delivered_lumi_stablebeams",
            "recorded_lumi",
            "recorded_lumi_stablebeams",
            "peak_lumi",
            "init_lumi",
            "first_run_number",
            "last_run_number",
        ]
    )
    q.filter("fill_type_runtime", "IONS")
    q.filter("start_time", f"{int(start_year)}-01-01T00:00:00Z", "GE")
    q.filter("start_time", f"{int(end_year) + 1}-01-01T00:00:00Z", "LT")
    q.sort("fill_number", asc=False)

    details = {}
    for row in _paged_data(q, per_page=1000):
        attr = row.get("attributes", {})
        fill_number = _to_int_or_none(attr.get("fill_number"))
        if fill_number is None:
            continue
        details[fill_number] = {
            "fill_number": fill_number,
            "start_time": attr.get("start_time"),
            "end_time": attr.get("end_time"),
            "era": attr.get("era"),
            "fill_type_runtime": attr.get("fill_type_runtime"),
            "fill_type_party1": attr.get("fill_type_party1"),
            "fill_type_party2": attr.get("fill_type_party2"),
            "stable_beams": attr.get("stable_beams"),
            "bunches_colliding": attr.get("bunches_colliding"),
            "bunches_target": attr.get("bunches_target"),
            "injection_scheme": attr.get("injection_scheme"),
            "delivered_lumi": attr.get("delivered_lumi"),
            "delivered_lumi_stablebeams": attr.get("delivered_lumi_stablebeams"),
            "recorded_lumi": attr.get("recorded_lumi"),
            "recorded_lumi_stablebeams": attr.get("recorded_lumi_stablebeams"),
            "peak_lumi": attr.get("peak_lumi"),
            "init_lumi": attr.get("init_lumi"),
            "first_run_number": attr.get("first_run_number"),
            "last_run_number": attr.get("last_run_number"),
        }
    return details


@lru_cache(maxsize=8)
def get_hi_fill_run_summary(
    start_year: int = 2023,
    end_year: int = 2026,
    stable_runs_only: bool = False,
) -> Dict[str, Any]:
    start_year = int(start_year)
    end_year = int(end_year)
    if end_year < start_year:
        start_year, end_year = end_year, start_year

    oms = _oms()
    q = oms.omsapi.query("runs")
    q.set_verbose(False)
    q.set_validation(False)
    q.attrs(
        [
            "run_number",
            "fill_number",
            "start_time",
            "end_time",
            "duration",
            "stable_beam",
            "last_lumisection_number",
            "l1_rate",
            "hlt_physics_throughput",
            "delivered_lumi",
            "recorded_lumi",
            "init_lumi",
            "end_lumi",
            "era",
            "sequence",
            "fill_type_runtime",
            "fill_type_party1",
            "fill_type_party2",
            "l1_key",
            "hlt_key",
        ]
    )
    q.filter("fill_type_runtime", "IONS")
    q.filter("start_time", f"{start_year}-01-01T00:00:00Z", "GE")
    q.filter("start_time", f"{end_year + 1}-01-01T00:00:00Z", "LT")
    if stable_runs_only:
        q.filter("stable_beam", True)
    q.sort("start_time", asc=False)
    rows = _paged_data(q, per_page=1000)

    fill_details = _fill_details_by_number(start_year, end_year)
    fills = {}  # type: Dict[int, Dict[str, Any]]
    run_count = 0
    stable_run_count = 0
    effective_run_count = 0

    for row in rows:
        attr = row.get("attributes", {})
        run_number = _to_int_or_none(attr.get("run_number") or row.get("id"))
        fill_number = _to_int_or_none(attr.get("fill_number"))
        if run_number is None or fill_number is None:
            continue

        recorded_lumi = _to_float(attr.get("recorded_lumi"))
        delivered_lumi = _to_float(attr.get("delivered_lumi"))
        last_ls = _to_int_or_none(attr.get("last_lumisection_number"))
        stable_beam = bool(attr.get("stable_beam"))
        effective = stable_beam and recorded_lumi > 0 and (last_ls or 0) > 0
        run_count += 1
        stable_run_count += 1 if stable_beam else 0
        effective_run_count += 1 if effective else 0

        fill = fills.setdefault(
            fill_number,
            {
                **fill_details.get(fill_number, {"fill_number": fill_number}),
                "run_count": 0,
                "stable_run_count": 0,
                "effective_run_count": 0,
                "run_recorded_lumi_sum": 0.0,
                "run_delivered_lumi_sum": 0.0,
                "best_run_number": None,
                "best_run_recorded_lumi": 0.0,
                "best_run_last_ls": None,
                "best_run_l1_rate": None,
                "runs": [],
            },
        )

        run_record = {
            "run_number": run_number,
            "start_time": attr.get("start_time"),
            "end_time": attr.get("end_time"),
            "duration": attr.get("duration"),
            "stable_beam": stable_beam,
            "last_lumisection_number": last_ls,
            "recorded_lumi": recorded_lumi,
            "delivered_lumi": delivered_lumi,
            "init_lumi": attr.get("init_lumi"),
            "end_lumi": attr.get("end_lumi"),
            "l1_rate": attr.get("l1_rate"),
            "hlt_physics_throughput": attr.get("hlt_physics_throughput"),
            "era": attr.get("era"),
            "sequence": attr.get("sequence"),
            "fill_type_runtime": attr.get("fill_type_runtime"),
            "fill_type_party1": attr.get("fill_type_party1"),
            "fill_type_party2": attr.get("fill_type_party2"),
            "l1_key": attr.get("l1_key"),
            "hlt_key": attr.get("hlt_key"),
            "effective": effective,
        }
        fill["runs"].append(run_record)
        fill["run_count"] += 1
        fill["stable_run_count"] += 1 if stable_beam else 0
        fill["effective_run_count"] += 1 if effective else 0
        fill["run_recorded_lumi_sum"] += recorded_lumi
        fill["run_delivered_lumi_sum"] += delivered_lumi
        if recorded_lumi > _to_float(fill.get("best_run_recorded_lumi")):
            fill["best_run_number"] = run_number
            fill["best_run_recorded_lumi"] = recorded_lumi
            fill["best_run_last_ls"] = last_ls
            fill["best_run_l1_rate"] = attr.get("l1_rate")

    fill_rows = []
    for fill in fills.values():
        fill["runs"].sort(
            key=lambda item: (
                not bool(item.get("effective")),
                -_to_float(item.get("recorded_lumi")),
                -(item.get("run_number") or 0),
            )
        )
        fill_rows.append(fill)

    fill_rows.sort(
        key=lambda item: (
            -_to_float(item.get("run_recorded_lumi_sum")),
            -(item.get("fill_number") or 0),
        )
    )
    return {
        "start_year": start_year,
        "end_year": end_year,
        "stable_runs_only": bool(stable_runs_only),
        "fill_count": len(fill_rows),
        "run_count": run_count,
        "stable_run_count": stable_run_count,
        "effective_run_count": effective_run_count,
        "fills": fill_rows,
    }


def _get_l1_rates_for_path(
    run: int,
    pathname: str,
    rate_field: str,
    ls_min: Optional[int] = None,
    ls_max: Optional[int] = None,
) -> Dict[int, Dict[str, Any]]:
    oms = _oms()
    q = oms.omsapi.query("l1algorithmtriggers")
    q.set_verbose(False)
    q.set_validation(False)
    q.custom("group[granularity]", "lumisection")
    q.filter("run_number", int(run))
    q.filter("name", pathname)
    if ls_min is not None:
        q.filter("last_lumisection_number", int(ls_min), "GE")
    if ls_max is not None:
        q.filter("last_lumisection_number", int(ls_max), "LE")
    q.sort("last_lumisection_number", asc=True)
    rows = _paged_data(q, per_page=1000)

    rates = {}  # type: Dict[int, Dict[str, Any]]
    for row in rows:
        attr = row.get("attributes", {})
        ls = attr.get("last_lumisection_number") or attr.get("lumisection_number")
        rate = attr.get(rate_field)
        if ls is None or rate is None:
            continue
        rates[int(ls)] = {
            "rate": float(rate),
            "bit": attr.get("bit"),
        }
    return rates


def _get_all_l1_rates(
    run: int,
    rate_field: str,
    ls_min: Optional[int],
    ls_max: Optional[int],
) -> List[Dict[str, Any]]:
    oms = _oms()
    q = oms.omsapi.query("l1algorithmtriggers")
    q.set_verbose(False)
    q.set_validation(False)
    q.custom("group[granularity]", "lumisection")
    q.filter("run_number", int(run))
    if ls_min is not None:
        q.filter("last_lumisection_number", int(ls_min), "GE")
    if ls_max is not None:
        q.filter("last_lumisection_number", int(ls_max), "LE")
    q.sort("last_lumisection_number", asc=True)
    rows = _paged_data(q, per_page=1000)

    records = []  # type: List[Dict[str, Any]]
    for row in rows:
        attr = row.get("attributes", {})
        ls = attr.get("last_lumisection_number") or attr.get("lumisection_number")
        pathname = attr.get("name") or attr.get("pathname") or attr.get("algorithm_name")
        rate = attr.get(rate_field)
        if ls is None or pathname is None or rate is None:
            continue
        ls = int(ls)
        if ls_min is not None and ls < int(ls_min):
            continue
        if ls_max is not None and ls > int(ls_max):
            continue
        records.append(
            {
                "lumisection": ls,
                "bit": attr.get("bit"),
                "pathname": str(pathname),
                "rate": float(rate),
            }
        )
    return records


@lru_cache(maxsize=64)
def _get_l1_ls_rates_cached(
    run: int,
    pathnames_key: tuple,
    ls_min: Optional[int] = None,
    ls_max: Optional[int] = None,
    rate_field: str = "pre_dt_before_prescale_rate",
) -> pd.DataFrame:
    pathnames = [p.strip() for p in pathnames_key if p and p.strip()]

    lumisections = _get_lumisections(run, ls_min, ls_max)
    if lumisections.empty:
        return pd.DataFrame(columns=L1_RATE_COLUMNS)

    records = []  # type: List[Dict[str, Any]]
    ls_records = lumisections.to_dict("records")
    if not pathnames:
        ls_by_number = {int(row["lumisection"]): row for row in ls_records}
        for rate_info in _get_all_l1_rates(run, rate_field, ls_min, ls_max):
            ls_info = ls_by_number.get(int(rate_info["lumisection"]))
            if ls_info is None:
                continue
            records.append(
                {
                    **ls_info,
                    "bit": rate_info.get("bit"),
                    "pathname": rate_info.get("pathname"),
                    "rate": rate_info.get("rate"),
                    "rate_field": rate_field,
                }
            )
        if not records:
            return pd.DataFrame(columns=L1_RATE_COLUMNS)
        return pd.DataFrame(records).reindex(columns=L1_RATE_COLUMNS)

    for pathname in pathnames:
        rate_by_ls = _get_l1_rates_for_path(run, pathname, rate_field, ls_min, ls_max)
        for ls_info in ls_records:
            rate_info = rate_by_ls.get(int(ls_info["lumisection"]))
            if rate_info is None:
                continue
            records.append(
                {
                    **ls_info,
                    "bit": rate_info.get("bit"),
                    "pathname": pathname,
                    "rate": rate_info.get("rate"),
                    "rate_field": rate_field,
                }
            )

    if not records:
        return pd.DataFrame(columns=L1_RATE_COLUMNS)
    return pd.DataFrame(records).reindex(columns=L1_RATE_COLUMNS)


def get_l1_ls_rates(
    run: int,
    pathnames: Optional[List[str]],
    ls_min: Optional[int] = None,
    ls_max: Optional[int] = None,
    rate_field: str = "pre_dt_before_prescale_rate",
) -> pd.DataFrame:
    pathnames_key = tuple(p.strip() for p in pathnames or [] if p and p.strip())
    frame = _get_l1_ls_rates_cached(
        int(run),
        pathnames_key,
        int(ls_min) if ls_min is not None else None,
        int(ls_max) if ls_max is not None else None,
        rate_field,
    )
    return frame.copy()


@lru_cache(maxsize=64)
def get_l1_prescale_table(run: int) -> pd.DataFrame:
    oms = _oms()
    q = oms.omsapi.query("l1algorithmtriggers")
    q.set_verbose(False)
    q.set_validation(False)
    q.custom("group[granularity]", "run")
    q.filter("run_number", int(run))
    q.sort("bit", asc=True)
    rows = _paged_data(q, per_page=1000)

    records = []
    for row in rows:
        attr = row.get("attributes", {})
        before = attr.get("pre_dt_before_prescale_rate")
        after = attr.get("pre_dt_rate")
        initial = attr.get("initial_prescale") or {}
        final = attr.get("final_prescale") or {}
        inferred = None
        try:
            if before is not None and after not in (None, 0):
                inferred = float(before) / float(after)
        except (TypeError, ValueError, ZeroDivisionError):
            inferred = None
        records.append(
            {
                "bit": attr.get("bit"),
                "name": attr.get("name") or attr.get("pathname") or attr.get("algorithm_name"),
                "mask": attr.get("mask"),
                "pre_dt_before_prescale_rate": before,
                "pre_dt_before_prescale_counter": attr.get("pre_dt_before_prescale_counter"),
                "pre_dt_rate": after,
                "pre_dt_counter": attr.get("pre_dt_counter"),
                "inferred_prescale": inferred,
                "post_dt_rate": attr.get("post_dt_rate"),
                "post_dt_counter": attr.get("post_dt_counter"),
                "post_dt_hlt_rate": attr.get("post_dt_hlt_rate"),
                "post_dt_hlt_counter": attr.get("post_dt_hlt_counter"),
                "initial_prescale_index": initial.get("prescale_index"),
                "initial_prescale_name": initial.get("prescale_name"),
                "initial_prescale": initial.get("prescale"),
                "final_prescale_index": final.get("prescale_index"),
                "final_prescale_name": final.get("prescale_name"),
                "final_prescale": final.get("prescale"),
            }
        )

    if not records:
        return pd.DataFrame(columns=L1_PRESCALE_COLUMNS)
    return pd.DataFrame(records).reindex(columns=L1_PRESCALE_COLUMNS)


@lru_cache(maxsize=64)
def get_l1_trigger_summary(run: int) -> pd.DataFrame:
    oms = _oms()
    q = oms.omsapi.query("l1triggerrates")
    q.set_verbose(False)
    q.set_validation(False)
    q.filter("run_number", int(run))
    q.paginate(per_page=1)
    rows = q.data().json().get("data", [])
    if not rows:
        return pd.DataFrame(columns=L1_TRIGGER_SUMMARY_COLUMNS)

    attr = rows[0].get("attributes", {})
    keys = [
        ("L1A calibration", "l1a_calibration"),
        ("L1A physics", "l1a_physics"),
        ("L1A random", "l1a_random"),
        ("Total L1A", "l1a_total"),
        ("PhysicsGeneratedFDL GT", "physics_generated_fdl_gt"),
        ("PhysicsGeneratedFDL TCDS", "physics_generated_fdl_tcds"),
        ("Total before deadtime", "total_before_deadtime"),
        ("Trigger physics beam active", "trigger_physics_beam_active"),
        ("Trigger physics beam inactive", "trigger_physics_beam_inactive"),
    ]
    records = []
    for name, key in keys:
        value = attr.get(key) or {}
        records.append(
            {
                "name": name,
                "rate": value.get("rate"),
                "counter": value.get("counter"),
            }
        )
    return pd.DataFrame(records).reindex(columns=L1_TRIGGER_SUMMARY_COLUMNS)


@lru_cache(maxsize=64)
def get_deadtime_summary(run: int) -> pd.DataFrame:
    oms = _oms()
    q = oms.omsapi.query("deadtimes")
    q.set_verbose(False)
    q.set_validation(False)
    q.filter("run_number", int(run))
    q.paginate(per_page=1)
    rows = q.data().json().get("data", [])
    if not rows:
        return pd.DataFrame(columns=DEADTIME_COLUMNS)

    attr = rows[0].get("attributes", {})
    keys = [
        ("Total", "overall_total_deadtime"),
        ("TTS", "overall_tts"),
        ("Trigger Rules", "overall_trigger_rules"),
        ("Bunch Mask", "overall_bunch_mask"),
        ("ReTri", "overall_re_tri"),
        ("APVE", "overall_apve"),
        ("Calibration", "overall_calibration"),
        ("Software Pause", "overall_software_pause"),
        ("Firmware Pause", "overall_firmware_pause"),
    ]
    records = []
    for name, key in keys:
        value = attr.get(key) or {}
        records.append(
            {
                "name": name,
                "percent": value.get("percent"),
                "counter": value.get("counter"),
            }
        )
    return pd.DataFrame(records).reindex(columns=DEADTIME_COLUMNS)
