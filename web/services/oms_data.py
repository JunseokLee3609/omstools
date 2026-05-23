from pathlib import Path
from functools import lru_cache
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
    "pre_dt_before_prescale_rate",
    "pre_dt_rate",
    "inferred_prescale",
    "post_dt_rate",
    "post_dt_hlt_rate",
]


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
                "pre_dt_before_prescale_rate": before,
                "pre_dt_rate": after,
                "inferred_prescale": inferred,
                "post_dt_rate": attr.get("post_dt_rate"),
                "post_dt_hlt_rate": attr.get("post_dt_hlt_rate"),
            }
        )

    if not records:
        return pd.DataFrame(columns=L1_PRESCALE_COLUMNS)
    return pd.DataFrame(records).reindex(columns=L1_PRESCALE_COLUMNS)
