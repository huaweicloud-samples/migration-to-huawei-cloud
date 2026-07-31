# /// script
# requires-python = ">=3.10"
# dependencies = [
#   "pandas>=2.0",
#   "openpyxl>=3.1",
# ]
# ///
"""Summarize each worksheet in an Azure billing workbook into a CSV file."""

from __future__ import annotations

import argparse
import re
import sys
import zipfile
from pathlib import Path
from typing import Any

import pandas as pd


REQUIRED_COLUMNS = {
    "Meter Sub Category",
    "Meter Category",
    "Region",
    "Resource URI",
    "Term And Billing Cycle",
    "Usage Quantity",
    "Unit",
}
GROUP_COLUMNS = [
    "Region",
    "Meter Category",
    "Meter Sub Category",
    "Resource URI",
    "Term And Billing Cycle",
]
CATEGORY_OUTPUT_COLUMN = "Category (Sub Category)"
OUTPUT_COLUMNS = [
    "Region",
    CATEGORY_OUTPUT_COLUMN,
    "Resource URI",
    "Term And Billing Cycle",
    "Usage Quantity",
    "Unit",
]
INVALID_FILENAME_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
PRICE_COLUMN_PATTERN = re.compile(
    r"^Total\s+Sales\s+Price(?:\s*\([^)]*\))?$", re.IGNORECASE
)


class BillingDataError(ValueError):
    """Raised when a worksheet cannot be summarized safely."""


def _clean_headers(frame: pd.DataFrame) -> pd.DataFrame:
    """Strip accidental header whitespace while preserving the source names."""
    frame = frame.copy()
    frame.columns = [str(column).strip() for column in frame.columns]
    return frame


def _numeric_column(frame: pd.DataFrame, column: str, sheet_name: str) -> pd.Series:
    values = frame[column]
    numeric = pd.to_numeric(values, errors="coerce")
    invalid = values.notna() & numeric.isna()
    if invalid.any():
        rows = (frame.index[invalid] + 2).tolist()
        preview = ", ".join(str(row) for row in rows[:5])
        suffix = "..." if len(rows) > 5 else ""
        raise BillingDataError(
            f"Sheet {sheet_name!r}: {column!r} contains non-numeric values "
            f"at Excel row(s) {preview}{suffix}."
        )
    return numeric.fillna(0)


def _find_price_column(columns: pd.Index, sheet_name: str) -> str:
    candidates = [
        str(column).strip()
        for column in columns
        if PRICE_COLUMN_PATTERN.fullmatch(str(column).strip())
    ]
    if not candidates:
        raise BillingDataError(
            f"Sheet {sheet_name!r} has no Total Sales Price column. "
            "Expected a header such as 'Total Sales Price (MYR)'."
        )
    if len(candidates) > 1:
        raise BillingDataError(
            f"Sheet {sheet_name!r} has multiple possible price columns: "
            f"{', '.join(candidates)}."
        )
    return candidates[0]


def _normalized_unit(value: Any) -> str:
    if pd.isna(value):
        return ""
    return str(value).strip()


def _format_category(category: Any, sub_category: Any) -> str:
    category_value = _normalized_unit(category)
    sub_category_value = _normalized_unit(sub_category)
    if category_value and sub_category_value:
        return f"{category_value} ({sub_category_value})"
    return category_value or sub_category_value


def _format_group(group: tuple[Any, ...]) -> str:
    values = ["" if pd.isna(value) else str(value) for value in group]
    return " | ".join(values)


def summarize_sheet(frame: pd.DataFrame, sheet_name: str) -> pd.DataFrame:
    """Return the requested pivot-style summary for one worksheet."""
    frame = _clean_headers(frame)
    missing = sorted(REQUIRED_COLUMNS - set(frame.columns))
    if missing:
        raise BillingDataError(
            f"Sheet {sheet_name!r} is missing required column(s): {', '.join(missing)}."
        )
    price_column = _find_price_column(frame.columns, sheet_name)

    frame["Usage Quantity"] = _numeric_column(frame, "Usage Quantity", sheet_name)
    frame[price_column] = _numeric_column(frame, price_column, sheet_name)
    frame["__unit"] = frame["Unit"].map(_normalized_unit)

    grouped = frame.groupby(
        GROUP_COLUMNS,
        dropna=False,
        sort=True,
        observed=False,
    )

    unit_values = grouped["__unit"].agg(lambda values: sorted(set(values)))
    conflicts = unit_values[unit_values.map(len) > 1]
    if not conflicts.empty:
        examples = []
        for group, units in conflicts.head(5).items():
            examples.append(f"[{_format_group(group)}] -> {', '.join(units)}")
        more = "" if len(conflicts) <= 5 else f" (+{len(conflicts) - 5} more)"
        raise BillingDataError(
            f"Sheet {sheet_name!r} has multiple Unit values within the same "
            f"five-column group: {'; '.join(examples)}{more}."
        )

    summary = grouped.agg(
        {
            "Usage Quantity": "sum",
            price_column: "sum",
            "__unit": "first",
        }
    ).reset_index()
    summary = summary.rename(columns={"__unit": "Unit"})
    summary["Unit"] = summary["Unit"].fillna("")
    summary[CATEGORY_OUTPUT_COLUMN] = [
        _format_category(category, sub_category)
        for category, sub_category in zip(
            summary["Meter Category"], summary["Meter Sub Category"]
        )
    ]
    output_columns = OUTPUT_COLUMNS + [price_column]
    return summary[output_columns]


def _safe_filename(sheet_name: str, used_names: set[str], index: int) -> str:
    cleaned = INVALID_FILENAME_CHARS.sub("_", sheet_name).strip().rstrip(".")
    cleaned = re.sub(r"\s+", " ", cleaned) or f"sheet_{index}"
    candidate = f"{cleaned}.csv"
    suffix = 2
    while candidate in used_names:
        candidate = f"{cleaned}_{suffix}.csv"
        suffix += 1
    used_names.add(candidate)
    return candidate


def summarize_workbook(input_path: Path, output_dir: Path) -> list[Path]:
    if not input_path.is_file():
        raise FileNotFoundError(f"Input workbook does not exist: {input_path}")
    if input_path.suffix.lower() != ".xlsx":
        raise BillingDataError(
            "Azure billing preprocessing accepts .xlsx workbooks only."
        )

    workbook = pd.read_excel(input_path, sheet_name=None, engine="openpyxl")
    if not workbook:
        raise BillingDataError("The Azure billing workbook contains no worksheets.")

    output_dir.mkdir(parents=True, exist_ok=True)
    output_paths: list[Path] = []
    used_names: set[str] = set()

    for index, (sheet_name, frame) in enumerate(workbook.items(), start=1):
        summary = summarize_sheet(frame, sheet_name)
        output_path = output_dir / _safe_filename(sheet_name, used_names, index)
        summary.to_csv(output_path, index=False, encoding="utf-8-sig")
        output_paths.append(output_path)
        print(f"{sheet_name}: {len(frame):,} rows -> {len(summary):,} groups -> {output_path}")

    return output_paths


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Summarize every worksheet in an Azure billing workbook."
    )
    parser.add_argument("input", type=Path, help="Path to the source .xlsx workbook")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("summaries"),
        help="Directory for generated CSV files (default: summaries)",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        summarize_workbook(args.input, args.output_dir)
    except (
        BillingDataError,
        FileNotFoundError,
        ValueError,
        OSError,
        zipfile.BadZipFile,
    ) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
