from __future__ import annotations

import argparse
import re
from pathlib import Path

try:
    from .common import NORMALIZED_DIR, RAW_DIR, ensure_runtime_dirs, write_csv
    from .html_table import parse_tables
except ImportError:  # pragma: no cover - for direct script execution
    from common import NORMALIZED_DIR, RAW_DIR, ensure_runtime_dirs, write_csv
    from html_table import parse_tables


def _clean_cell(value: str) -> str:
    return " ".join(value.replace("\xa0", " ").split())


def _parse_int(value: str) -> int | None:
    value = _clean_cell(value)
    if not value or value in {"-", "—"}:
        return None
    match = re.search(r"\d+", value)
    return int(match.group(0)) if match else None


def _detect_school(text: str) -> bool:
    return bool(re.search(r"^[А-ЯA-ZЁ][А-ЯA-ZЁa-zа-яё\-\s]{1,}$", text)) and len(text) <= 35


def _extract_rows_from_table(table: list[list]) -> list[dict]:
    rows: list[dict] = []
    for row in table:
        texts = [_clean_cell(cell.text) for cell in row]
        if len(texts) < 3:
            continue

        subdivision = texts[0]
        contest_group = texts[1]
        if not subdivision or not contest_group:
            continue
        if "Группа научных специальностей" in subdivision:
            continue
        if subdivision.startswith("Итого"):
            continue
        if contest_group.startswith("**") or contest_group == "Конкурсная группа":
            continue

        budget_places = _parse_int(texts[2]) if len(texts) > 2 else None
        paid_places = _parse_int(texts[-1]) if len(texts) > 3 else None
        if budget_places is None and paid_places is None:
            continue

        rows.append(
            {
                "subdivision": subdivision,
                "contest_group": contest_group,
                "budget_places": budget_places or 0,
                "paid_places": paid_places or 0,
            }
        )
    return rows


def parse_places_html(places_html: str) -> list[dict]:
    tables = parse_tables(places_html)
    if not tables:
        raise ValueError("No tables found in places HTML")

    all_rows: list[dict] = []
    for table in tables:
        all_rows.extend(_extract_rows_from_table(table))

    # Deduplicate by contest group and subdivision, keep max places.
    unique: dict[tuple[str, str], dict] = {}
    for row in all_rows:
        key = (row["subdivision"], row["contest_group"])
        current = unique.get(key)
        if current is None:
            unique[key] = row
            continue
        current["budget_places"] = max(current["budget_places"], row["budget_places"])
        current["paid_places"] = max(current["paid_places"], row["paid_places"])

    normalized: list[dict] = []
    for row in unique.values():
        if row["budget_places"] > 0:
            normalized.append(
                {
                    "subdivision": row["subdivision"],
                    "contest_group": row["contest_group"],
                    "place_type": "budget",
                    "places": row["budget_places"],
                }
            )
        if row["paid_places"] > 0:
            normalized.append(
                {
                    "subdivision": row["subdivision"],
                    "contest_group": row["contest_group"],
                    "place_type": "paid",
                    "places": row["paid_places"],
                }
            )

    return sorted(normalized, key=lambda x: (x["contest_group"], x["place_type"]))


def parse_places(raw_path: Path = RAW_DIR / "2026_places.html") -> Path:
    ensure_runtime_dirs()
    html_text = raw_path.read_text(encoding="utf-8")
    rows = parse_places_html(html_text)
    output_path = NORMALIZED_DIR / "places.csv"
    write_csv(
        output_path,
        rows=rows,
        fieldnames=["subdivision", "contest_group", "place_type", "places"],
    )
    return output_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Parse places table")
    parser.add_argument(
        "--raw-path",
        type=Path,
        default=RAW_DIR / "2026_places.html",
        help="Path to raw places HTML",
    )
    args = parser.parse_args()

    output_path = parse_places(args.raw_path)
    print(f"Places saved to: {output_path}")


if __name__ == "__main__":
    main()
