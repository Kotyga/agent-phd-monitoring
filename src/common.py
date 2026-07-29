from __future__ import annotations

import csv
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable


ROOT_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT_DIR / "data"
RAW_DIR = DATA_DIR / "raw"
NORMALIZED_DIR = DATA_DIR / "normalized"
RESULTS_DIR = DATA_DIR / "results"
REPORTS_DIR = ROOT_DIR / "reports"
LOGS_DIR = ROOT_DIR / "logs"


def ensure_runtime_dirs() -> None:
    for directory in (
        DATA_DIR,
        RAW_DIR,
        NORMALIZED_DIR,
        RESULTS_DIR,
        REPORTS_DIR,
        LOGS_DIR,
    ):
        directory.mkdir(parents=True, exist_ok=True)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def slugify(value: str) -> str:
    value = value.strip().lower()
    value = re.sub(r"[^\w\s-]", "", value, flags=re.UNICODE)
    value = re.sub(r"[\s_-]+", "-", value, flags=re.UNICODE)
    return value.strip("-")


def _contest_group_match_rank(name: str, canonical: str) -> int | None:
    if canonical == name:
        return 0
    if canonical.startswith(f"{name},"):
        return 1
    if canonical.startswith(f"{name} /") or canonical.startswith(f"{name}/"):
        return 2
    for part in re.split(r"\s*/\s*", canonical):
        if part == name or part.startswith(f"{name},"):
            return 3
    if canonical.startswith(f"{name} "):
        return 4
    return None


def resolve_contest_group(name: str, canonical_names: Iterable[str]) -> str:
    """Map a short applicants-page name to the canonical places-table name."""
    cleaned = name.strip()
    unique = sorted(set(canonical_names))
    if cleaned in unique:
        return cleaned

    ranked: list[tuple[int, int, str]] = []
    for canonical in unique:
        rank = _contest_group_match_rank(cleaned, canonical)
        if rank is not None:
            ranked.append((rank, len(canonical), canonical))

    if not ranked:
        return cleaned
    ranked.sort()
    return ranked[0][2]


def normalize_contest_group(name: str, place_type: str, places_rows: Iterable[dict]) -> str:
    canonical_by_type = [
        row["contest_group"]
        for row in places_rows
        if row.get("place_type") == place_type
    ]
    return resolve_contest_group(name, canonical_by_type)


def write_csv(path: Path, rows: Iterable[dict], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key) for key in fieldnames})


def read_csv(path: Path) -> list[dict]:
    with path.open("r", newline="", encoding="utf-8") as file:
        return list(csv.DictReader(file))


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file:
        json.dump(payload, file, ensure_ascii=False, indent=2)
