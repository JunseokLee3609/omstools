from typing import Any, Dict, Optional, Union

import numpy as np
import pandas as pd


MODEL_COLUMNS = [
    "pathname",
    "slope",
    "intercept",
    "r_squared",
    "n_points",
    "reference_bunches",
    "status",
    "message",
]


Number = Union[int, float]


def _empty_model(pathname: str, status: str, message: str) -> Dict[str, Any]:
    return {
        "pathname": pathname,
        "slope": np.nan,
        "intercept": np.nan,
        "r_squared": np.nan,
        "n_points": 0,
        "reference_bunches": np.nan,
        "status": status,
        "message": message,
    }


def fit_bunch_projection(
    reference_df: pd.DataFrame,
    reference_bunches: Optional[Number],
) -> Dict[str, Dict[str, Any]]:
    """Fit rate-per-bunch as a linear function of lumi-per-bunch per L1 seed."""
    if reference_df is None or reference_df.empty:
        return {}

    if reference_bunches is None or reference_bunches <= 0:
        return {
            pathname: _empty_model(
                str(pathname),
                "invalid_reference_bunches",
                "Reference bunch count is missing or non-positive.",
            )
            for pathname in sorted(reference_df["pathname"].dropna().unique())
        }

    models: Dict[str, Dict[str, Any]] = {}
    for pathname, group in reference_df.groupby("pathname"):
        clean = group.copy()
        clean = clean.replace([np.inf, -np.inf], np.nan)
        clean = clean.dropna(subset=["init_lumi", "rate"])
        clean = clean[(clean["init_lumi"] > 0) & (clean["rate"] >= 0)]

        if len(clean) < 2 or clean["init_lumi"].nunique() < 2:
            models[str(pathname)] = _empty_model(
                str(pathname),
                "insufficient_points",
                "At least two points with different luminosity are required.",
            )
            continue

        x = clean["init_lumi"].to_numpy(dtype=float) / float(reference_bunches)
        y = clean["rate"].to_numpy(dtype=float) / float(reference_bunches)
        slope, intercept = np.polyfit(x, y, 1)
        predicted = slope * x + intercept

        ss_res = float(np.sum((y - predicted) ** 2))
        ss_tot = float(np.sum((y - np.mean(y)) ** 2))
        r_squared = 1.0 if ss_tot == 0 else 1.0 - (ss_res / ss_tot)

        models[str(pathname)] = {
            "pathname": str(pathname),
            "slope": float(slope),
            "intercept": float(intercept),
            "r_squared": float(r_squared),
            "n_points": int(len(clean)),
            "reference_bunches": float(reference_bunches),
            "status": "ok",
            "message": "",
        }

    return models


def apply_projection(
    current_df: pd.DataFrame,
    current_bunches: Optional[Number],
    models: Dict[str, Dict[str, Any]],
    double_ratio_scale: Number = 1.0,
) -> pd.DataFrame:
    """Apply fitted bunch projection models to current-run L1 rates."""
    if current_df is None or current_df.empty:
        return pd.DataFrame(
            columns=[
                "run",
                "bit",
                "pathname",
                "lumisection",
                "init_lumi",
                "rate",
                "expected_rate",
                "ratio",
                "double_ratio",
                "deviation",
                "deviation_pct",
                "model_status",
                "model_message",
                "r_squared",
                "fit_points",
            ]
        )

    result = current_df.copy()
    result["expected_rate"] = np.nan
    result["ratio"] = np.nan
    result["double_ratio"] = np.nan
    result["deviation"] = np.nan
    result["deviation_pct"] = np.nan
    result["model_status"] = "no_model"
    result["model_message"] = "No projection model was available for this L1 seed."
    result["r_squared"] = np.nan
    result["fit_points"] = 0

    if current_bunches is None or current_bunches <= 0:
        result["model_status"] = "invalid_current_bunches"
        result["model_message"] = "Current bunch count is missing or non-positive."
        return result

    for pathname, model in models.items():
        mask = result["pathname"] == pathname
        if not mask.any():
            continue

        result.loc[mask, "model_status"] = model.get("status", "unknown")
        result.loc[mask, "model_message"] = model.get("message", "")
        result.loc[mask, "r_squared"] = model.get("r_squared", np.nan)
        result.loc[mask, "fit_points"] = model.get("n_points", 0)

        if model.get("status") != "ok":
            continue

        valid = mask & result["init_lumi"].notna() & result["rate"].notna()
        valid = valid & (result["init_lumi"] > 0)
        if not valid.any():
            continue

        lumi_per_bunch = result.loc[valid, "init_lumi"].astype(float) / float(current_bunches)
        expected = (
            model["slope"] * lumi_per_bunch + model["intercept"]
        ) * float(current_bunches)
        result.loc[valid, "expected_rate"] = expected
        result.loc[valid, "deviation"] = result.loc[valid, "rate"].astype(float) - expected

        nonzero = valid & result["expected_rate"].notna() & (result["expected_rate"] != 0)
        result.loc[nonzero, "ratio"] = (
            result.loc[nonzero, "rate"].astype(float) / result.loc[nonzero, "expected_rate"]
        )
        result.loc[nonzero, "double_ratio"] = (
            result.loc[nonzero, "ratio"] * float(double_ratio_scale)
        )
        result.loc[nonzero, "deviation_pct"] = (
            result.loc[nonzero, "deviation"] / result.loc[nonzero, "expected_rate"] * 100.0
        )

    return result


def _rate_summary(df: pd.DataFrame, suffix: str) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame(
            columns=[
                "pathname",
                f"run_{suffix}",
                f"bit_{suffix}",
                f"lumisection_{suffix}",
                f"lumisection_min_{suffix}",
                f"lumisection_max_{suffix}",
                f"init_lumi_{suffix}",
                f"rate_{suffix}",
                f"n_points_{suffix}",
            ]
        )

    clean = df.copy()
    clean = clean.replace([np.inf, -np.inf], np.nan)
    clean = clean.dropna(subset=["pathname", "rate"])
    if clean.empty:
        return pd.DataFrame()
    if "init_lumi" in clean.columns:
        clean["init_lumi"] = pd.to_numeric(clean["init_lumi"], errors="coerce")
        clean = clean[clean["init_lumi"] > 0]
        if clean.empty:
            return pd.DataFrame()

    rows = []
    for pathname, group in clean.groupby("pathname"):
        ordered = group.sort_values("lumisection") if "lumisection" in group.columns else group
        latest = ordered.tail(1).iloc[0]
        rows.append(
            {
                "pathname": str(pathname),
                f"run_{suffix}": latest.get("run", np.nan),
                f"bit_{suffix}": latest.get("bit", np.nan),
                f"lumisection_{suffix}": latest.get("lumisection", np.nan),
                f"lumisection_min_{suffix}": ordered["lumisection"].min()
                if "lumisection" in ordered.columns
                else np.nan,
                f"lumisection_max_{suffix}": ordered["lumisection"].max()
                if "lumisection" in ordered.columns
                else np.nan,
                f"init_lumi_{suffix}": ordered["init_lumi"].dropna().astype(float).mean()
                if "init_lumi" in ordered.columns
                else np.nan,
                f"rate_{suffix}": ordered["rate"].dropna().astype(float).mean(),
                f"n_points_{suffix}": int(len(ordered)),
            }
        )
    return pd.DataFrame(rows)


def _current_lumisection_points(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame(
            columns=[
                "run",
                "bit",
                "pathname",
                "lumisection",
                "lumisection_min",
                "lumisection_max",
                "init_lumi",
                "rate",
                "n_points",
            ]
        )

    clean = df.copy()
    clean = clean.replace([np.inf, -np.inf], np.nan)
    clean = clean.dropna(subset=["pathname", "lumisection", "rate"])
    if clean.empty:
        return pd.DataFrame()

    clean["lumisection"] = pd.to_numeric(clean["lumisection"], errors="coerce")
    clean["rate"] = pd.to_numeric(clean["rate"], errors="coerce")
    clean["init_lumi"] = pd.to_numeric(clean.get("init_lumi"), errors="coerce")
    clean = clean.dropna(subset=["lumisection", "rate"])
    clean = clean[clean["init_lumi"] > 0]
    if clean.empty:
        return pd.DataFrame()

    rows = []
    for (pathname, lumisection), group in clean.groupby(["pathname", "lumisection"]):
        latest = group.tail(1).iloc[0]
        rows.append(
            {
                "run": latest.get("run", np.nan),
                "bit": latest.get("bit", np.nan),
                "pathname": str(pathname),
                "lumisection": int(lumisection),
                "lumisection_min": int(lumisection),
                "lumisection_max": int(lumisection),
                "init_lumi": group["init_lumi"].dropna().astype(float).mean(),
                "rate": group["rate"].dropna().astype(float).mean(),
                "n_points": int(len(group)),
            }
        )
    return pd.DataFrame(rows)


def _apply_spreadsheet_from_current(
    current: pd.DataFrame,
    reference_df: pd.DataFrame,
    double_ratio_scale: Optional[Number] = None,
) -> pd.DataFrame:
    if current.empty:
        return pd.DataFrame(
            columns=[
                "run",
                "bit",
                "pathname",
                "lumisection",
                "lumisection_min",
                "lumisection_max",
                "init_lumi",
                "reference_lumi",
                "lumi_ratio",
                "reference_rate",
                "rate",
                "expected_rate",
                "ratio",
                "double_ratio",
                "deviation",
                "deviation_pct",
                "model_status",
                "model_message",
                "r_squared",
                "n_points",
                "reference_points",
                "fit_points",
            ]
        )

    reference = _rate_summary(reference_df, "reference")
    result = current.merge(reference, on="pathname", how="left")
    result = result.rename(
        columns={
            "run_current": "run",
            "bit_current": "bit",
            "lumisection_current": "lumisection",
            "lumisection_min_current": "lumisection_min",
            "lumisection_max_current": "lumisection_max",
            "init_lumi_current": "init_lumi",
            "rate_current": "rate",
            "n_points_current": "n_points",
            "init_lumi_reference": "reference_lumi",
            "rate_reference": "reference_rate",
            "n_points_reference": "reference_points",
        }
    )

    for column in ["reference_rate", "rate", "init_lumi", "reference_lumi"]:
        if column not in result.columns:
            result[column] = np.nan
        result[column] = pd.to_numeric(result[column], errors="coerce")

    result["expected_rate"] = np.nan
    result["ratio"] = np.nan
    result["double_ratio"] = np.nan
    result["deviation"] = np.nan
    result["deviation_pct"] = np.nan
    result["lumi_ratio"] = np.nan
    result["r_squared"] = np.nan
    if "n_points" not in result.columns:
        result["n_points"] = np.nan
    if "reference_points" not in result.columns:
        result["reference_points"] = np.nan
    result["fit_points"] = result["reference_points"]
    result["model_status"] = "ok"
    result["model_message"] = ""

    missing_reference = result["reference_rate"].isna()
    result.loc[missing_reference, "model_status"] = "no_reference_rate"
    result.loc[missing_reference, "model_message"] = "No reference rate was available for this L1 seed."

    valid_lumi = (
        result["init_lumi"].notna()
        & result["reference_lumi"].notna()
        & (result["reference_lumi"] != 0)
    )
    result.loc[valid_lumi, "lumi_ratio"] = (
        result.loc[valid_lumi, "init_lumi"] / result.loc[valid_lumi, "reference_lumi"]
    )

    valid_projection = result["reference_rate"].notna() & result["lumi_ratio"].notna()
    result.loc[valid_projection, "expected_rate"] = (
        result.loc[valid_projection, "reference_rate"]
        * result.loc[valid_projection, "lumi_ratio"]
    )
    result["deviation"] = result["rate"] - result["expected_rate"]

    nonzero_projection = result["expected_rate"].notna() & (result["expected_rate"] != 0)
    result.loc[nonzero_projection, "ratio"] = (
        result.loc[nonzero_projection, "rate"] / result.loc[nonzero_projection, "expected_rate"]
    )
    result.loc[nonzero_projection, "double_ratio"] = result.loc[nonzero_projection, "ratio"]
    result.loc[nonzero_projection, "deviation_pct"] = (
        result.loc[nonzero_projection, "deviation"]
        / result.loc[nonzero_projection, "expected_rate"]
        * 100.0
    )

    if double_ratio_scale is not None:
        fallback = result["ratio"].notna() & result["double_ratio"].isna()
        result.loc[fallback, "double_ratio"] = result.loc[fallback, "ratio"] * float(double_ratio_scale)

    zero_reference = result["reference_rate"].notna() & (result["reference_rate"] == 0)
    result.loc[zero_reference, "model_status"] = "zero_reference_rate"
    result.loc[zero_reference, "model_message"] = "Reference rate is zero, so ratio is undefined."

    columns = [
        "run",
        "bit",
        "pathname",
        "lumisection",
        "lumisection_min",
        "lumisection_max",
        "init_lumi",
        "reference_lumi",
        "lumi_ratio",
        "reference_rate",
        "rate",
        "expected_rate",
        "ratio",
        "double_ratio",
        "deviation",
        "deviation_pct",
        "model_status",
        "model_message",
        "r_squared",
        "n_points",
        "reference_points",
        "fit_points",
    ]
    for column in columns:
        if column not in result.columns:
            result[column] = np.nan
    return result[columns]


def apply_spreadsheet_projection_summary(
    reference_df: pd.DataFrame,
    current_df: pd.DataFrame,
    double_ratio_scale: Optional[Number] = None,
) -> pd.DataFrame:
    """Return one spreadsheet-style average row per L1 seed."""
    current = _rate_summary(current_df, "current")
    return _apply_spreadsheet_from_current(current, reference_df, double_ratio_scale)


def apply_spreadsheet_projection(
    reference_df: pd.DataFrame,
    current_df: pd.DataFrame,
    double_ratio_scale: Optional[Number] = None,
) -> pd.DataFrame:
    """Return LS-level spreadsheet-style comparison rows for plotting.

    Reference values are averaged over the selected reference range. Current
    values are kept per lumisection so trend plots show the full LS window.
    """
    current = _current_lumisection_points(current_df)
    return _apply_spreadsheet_from_current(current, reference_df, double_ratio_scale)


def models_to_dataframe(models: Dict[str, Dict[str, Any]]) -> pd.DataFrame:
    if not models:
        return pd.DataFrame(columns=MODEL_COLUMNS)
    return pd.DataFrame(models.values()).reindex(columns=MODEL_COLUMNS)


def latest_by_pathname(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()
    ordered = df.sort_values(["pathname", "lumisection"])
    return ordered.groupby("pathname", as_index=False).tail(1).sort_values("pathname")
