# /// script
# requires-python = ">=3.10"
# dependencies = ["aspose-cells-python"]
# ///
"""
Export the final Markdown inventory to a single-sheet Excel workbook.

Reads the final migration inventory Markdown, parses metadata, section
headings, and Markdown tables, then writes everything into one worksheet
using Aspose.Cells for Python.
"""

import argparse
import re
import sys
from pathlib import Path

import aspose.cells as cells
from aspose.pydrawing import Color


def clean_md_text(text: str) -> str:
    """Remove simple inline Markdown markers for Excel display."""
    text = text.strip()
    text = re.sub(r"\*\*(.*?)\*\*", r"\1", text)
    text = re.sub(r"`([^`]*)`", r"\1", text)
    return text.strip()


def parse_md(md_path: Path) -> tuple[list[str], list[dict]]:
    """Parse metadata lines, section tables, and section rationale."""
    content = md_path.read_text(encoding="utf-8")
    lines = content.splitlines()

    metadata: list[str] = []
    sections: list[dict] = []
    current_section = ""
    i = 0

    while i < len(lines):
        line = lines[i].rstrip()
        stripped = line.strip()

        if stripped.startswith("> "):
            metadata.append(stripped[2:].strip())
            i += 1
            continue

        if stripped.startswith("## "):
            current_section = stripped[3:].strip()
            i += 1
            continue

        if (
            stripped.startswith("|")
            and "---" not in stripped
            and i + 1 < len(lines)
            and re.match(r"^\|[\s\-:|]+\|$", lines[i + 1].strip())
        ):
            headers = [h.strip() for h in stripped.split("|")[1:-1]]
            rows: list[list[str]] = []
            i += 2
            while i < len(lines):
                row_line = lines[i].strip()
                if not (row_line.startswith("|") and row_line.endswith("|")):
                    break
                cells_in_row = [c.strip() for c in row_line.split("|")[1:-1]]
                if len(cells_in_row) == len(headers):
                    rows.append(cells_in_row)
                i += 1

            rationale: list[str] = []
            while i < len(lines):
                paragraph_line = lines[i].strip()
                if not paragraph_line:
                    i += 1
                    continue
                if paragraph_line.startswith("## ") or paragraph_line.startswith("|"):
                    break
                if paragraph_line.startswith("**Recommendation rationale:**"):
                    rationale.append(clean_md_text(paragraph_line))
                i += 1

            sections.append(
                {
                    "title": current_section or "Table",
                    "headers": headers,
                    "rows": rows,
                    "rationale": rationale,
                }
            )
            continue

        i += 1

    return metadata, sections


def apply_style(target, *, bold=False, font_size=None, bg=None, wrap=True):
    """Apply a simple style to a cell or range."""
    style = target.get_style()
    style.font.is_bold = bold
    if font_size is not None:
        style.font.size = font_size
    if bg is not None:
        style.pattern = cells.BackgroundType.SOLID
        style.foreground_color = Color.from_argb(bg)
    style.is_text_wrapped = wrap
    target.set_style(style)


def export_single_sheet(input_path: Path, output_path: Path):
    metadata, sections = parse_md(input_path)

    workbook = cells.Workbook()
    sheet = workbook.worksheets[0]
    sheet.name = "Inventory"
    cell_collection = sheet.cells

    max_columns = max(
        [1]
        + [len(section["headers"]) for section in sections]
    )

    row = 0

    title = Path(input_path).stem.replace("_", " ").title()
    cell_collection.get(row, 0).put_value(title)
    cell_collection.merge(row, 0, 1, max_columns)
    apply_style(
        cell_collection.get(row, 0),
        bold=True,
        font_size=16,
        wrap=False,
    )
    row += 2

    for item in metadata:
        cell_collection.get(row, 0).put_value(clean_md_text(item))
        cell_collection.merge(row, 0, 1, max_columns)
        apply_style(
            cell_collection.get(row, 0),
            bold=False,
            font_size=11,
        )
        row += 1

    if metadata:
        row += 1

    for section in sections:
        headers = section["headers"]
        rows = section["rows"]

        cell_collection.get(row, 0).put_value(section["title"])
        cell_collection.merge(row, 0, 1, max(len(headers), 1))
        apply_style(
            cell_collection.get(row, 0),
            bold=True,
            font_size=13,
            bg=0xD9EAF7,
        )
        row += 1

        for col, header in enumerate(headers):
            cell_collection.get(row, col).put_value(header)
            apply_style(
                cell_collection.get(row, col),
                bold=True,
                bg=0xEDEDED,
            )
        row += 1

        for data_row in rows:
            for col, value in enumerate(data_row):
                cell_collection.get(row, col).put_value(value)
                apply_style(cell_collection.get(row, col))
            row += 1

        for rationale_line in section.get("rationale", []):
            cell_collection.get(row, 0).put_value(rationale_line)
            cell_collection.merge(row, 0, 1, max_columns)
            apply_style(
                cell_collection.get(row, 0),
                bold=False,
                font_size=11,
                bg=0xF7F3E8,
            )
            row += 1

        row += 1

    sheet.auto_fit_columns(0, max_columns - 1)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    workbook.save(str(output_path))


def main():
    parser = argparse.ArgumentParser(
        description="Export billing Markdown inventory to single-sheet Excel"
    )
    parser.add_argument("--input", required=True, type=Path, help="Input Markdown file")
    parser.add_argument("--output", required=True, type=Path, help="Output .xlsx file")
    args = parser.parse_args()

    if not args.input.exists():
        print(f"Error: Input file not found: {args.input}", file=sys.stderr)
        sys.exit(1)

    export_single_sheet(args.input, args.output)
    print(f"Done. Excel written to {args.output}")


if __name__ == "__main__":
    main()
