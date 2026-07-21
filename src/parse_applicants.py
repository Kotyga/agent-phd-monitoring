from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

try:
    from .common import NORMALIZED_DIR, RAW_DIR, ensure_runtime_dirs, utc_now_iso, write_csv
    from .html_table import parse_tables
except ImportError:  # pragma: no cover - for direct script execution
    from common import NORMALIZED_DIR, RAW_DIR, ensure_runtime_dirs, utc_now_iso, write_csv
    from html_table import parse_tables


def _clean_text(value: str) -> str:
    return " ".join(value.replace("\xa0", " ").split())


def _parse_int(value: str) -> int | None:
    value = _clean_text(value)
    if not value or value in {"-", "—"}:
        return None
    match = re.search(r"\d+", value)
    return int(match.group(0)) if match else None


def _extract_title(html_text: str) -> str:
    match = re.search(r"<title[^>]*>(.*?)</title>", html_text, flags=re.IGNORECASE | re.DOTALL)
    if not match:
        return "Unknown contest group"
    return _clean_text(re.sub(r"<[^>]+>", " ", match.group(1)))


def _extract_h6_value(html_text: str, label: str) -> str:
    pattern = rf"<h6>\s*{re.escape(label)}\s*-\s*(.*?)</h6>"
    match = re.search(pattern, html_text, flags=re.IGNORECASE | re.DOTALL)
    if not match:
        return ""
    return _clean_text(re.sub(r"<[^>]+>", " ", match.group(1)))


def _detect_place_type(source_url: str, title: str) -> str:
    token = f"{source_url} {title}".lower()
    if any(keyword in token for keyword in ("kontrakt", "контракт", "платн", "paid")):
        return "paid"
    return "budget"


def _normalize_contest_group(title: str) -> str:
    clean = title
    clean = re.sub(r"\s*[-|].*$", "", clean)
    clean = re.sub(r"\s+(бюджет|контракт|платные места|бюджетные места).*", "", clean, flags=re.IGNORECASE)
    return clean.strip() or title.strip()


def _column_map(header: list[str]) -> dict[str, int]:
    mapping: dict[str, int] = {}
    for index, name in enumerate(header):
        low = name.lower()
        if "приоритет" in low and "priority" not in mapping:
            mapping["priority"] = index
        elif ("уник" in low and "код" in low) or "снилс" in low or ("код" in low and "абит" in low):
            mapping.setdefault("unique_code", index)
        elif "балл" in low or "сумма" in low:
            mapping.setdefault("score", index)
        elif ("место" in low or "позици" in low or "ранг" in low) and "rank_position" not in mapping:
            mapping["rank_position"] = index
        elif low in {"№", "n", "номер"} and "rank_position" not in mapping:
            mapping["rank_position"] = index
        elif "соглас" in low or "оригинал" in low:
            mapping.setdefault("has_consent", index)
        elif "вид документа" in low or ("документ" in low and "вид" in low):
            mapping.setdefault("document_type", index)
    return mapping


def _looks_like_header(cells: list[str]) -> bool:
    token = " ".join(cells).lower()
    markers = ("приоритет", "балл", "конкурс", "снилс", "уник", "ранг", "место")
    return any(marker in token for marker in markers)


def _extract_table_rows(table: list[list], source_url: str, snapshot_time: str, title: str) -> list[dict]:
    if not table:
        return []

    header_idx = None
    header_map: dict[str, int] = {}
    for index, row in enumerate(table[:4]):
        row_text = [_clean_text(cell.text) for cell in row]
        if _looks_like_header(row_text):
            possible_map = _column_map(row_text)
            if "unique_code" in possible_map and "priority" in possible_map:
                header_idx = index
                header_map = possible_map
                break

    if header_idx is None:
        return []

    contest_group = _normalize_contest_group(title)
    place_type = _detect_place_type(source_url, title)
    records: list[dict] = []

    for row in table[header_idx + 1 :]:
        row_text = [_clean_text(cell.text) for cell in row]
        if not row_text:
            continue
        if len(row_text) <= max(header_map.values()):
            continue

        unique_code = row_text[header_map["unique_code"]].strip()
        if not unique_code or unique_code in {"Код", "СНИЛС"}:
            continue

        priority = _parse_int(row_text[header_map["priority"]]) or 999
        rank_position = _parse_int(row_text[header_map["rank_position"]]) if "rank_position" in header_map else None
        score = _parse_int(row_text[header_map["score"]]) if "score" in header_map else None
        consent_raw = (
            row_text[header_map["has_consent"]].lower()
            if "has_consent" in header_map and len(row_text) > header_map["has_consent"]
            else ""
        )
        has_consent = consent_raw in {"да", "yes", "истина", "true", "1", "+"}
        document_type = (
            row_text[header_map["document_type"]].strip()
            if "document_type" in header_map and len(row_text) > header_map["document_type"]
            else ""
        )

        records.append(
            {
                "unique_code": unique_code,
                "contest_group": contest_group,
                "place_type": place_type,
                "priority": priority,
                "rank_position": rank_position if rank_position is not None else 10**9,
                "score": score if score is not None else 0,
                "document_type": document_type,
                "has_consent": str(has_consent).lower(),
                "snapshot_time": snapshot_time,
                "source_url": source_url,
            }
        )
    return records


def _extract_rows_regex(html_text: str, source_url: str, snapshot_time: str) -> list[dict]:
    thead_match = re.search(r"<thead[^>]*>(.*?)</thead>", html_text, flags=re.IGNORECASE | re.DOTALL)
    tbody_match = re.search(r"<tbody[^>]*>(.*?)</tbody>", html_text, flags=re.IGNORECASE | re.DOTALL)
    if not thead_match or not tbody_match:
        return []

    header_cells_raw = re.findall(r"<th[^>]*>(.*?)</th>", thead_match.group(1), flags=re.IGNORECASE | re.DOTALL)
    headers = [_clean_text(re.sub(r"<[^>]+>", " ", cell)) for cell in header_cells_raw]
    header_map = _column_map(headers)
    if "unique_code" not in header_map or "priority" not in header_map:
        return []

    contest_group = _extract_h6_value(html_text, "Конкурсная группа")
    if not contest_group:
        contest_group = _normalize_contest_group(_extract_title(html_text))

    basis = _extract_h6_value(html_text, "Основание поступления")
    place_type = "paid" if "возмещ" in basis.lower() else _detect_place_type(source_url, basis)

    row_chunks = re.findall(r"<tr[^>]*>(.*?)</tr>", tbody_match.group(1), flags=re.IGNORECASE | re.DOTALL)
    records: list[dict] = []
    for chunk in row_chunks:
        td_cells_raw = re.findall(r"<td[^>]*>(.*?)</td>", chunk, flags=re.IGNORECASE | re.DOTALL)
        row_text = [_clean_text(re.sub(r"<[^>]+>", " ", cell)) for cell in td_cells_raw]
        if len(row_text) <= max(header_map.values()):
            continue
        unique_code = row_text[header_map["unique_code"]].strip()
        if not unique_code or not re.search(r"\d", unique_code):
            continue
        priority = _parse_int(row_text[header_map["priority"]]) or 999
        rank_position = _parse_int(row_text[header_map["rank_position"]]) if "rank_position" in header_map else None
        score = _parse_int(row_text[header_map["score"]]) if "score" in header_map else None
        consent_raw = (
            row_text[header_map["has_consent"]].lower()
            if "has_consent" in header_map and len(row_text) > header_map["has_consent"]
            else ""
        )
        has_consent = consent_raw in {"да", "yes", "истина", "true", "1", "+"}
        document_type = (
            row_text[header_map["document_type"]].strip()
            if "document_type" in header_map and len(row_text) > header_map["document_type"]
            else ""
        )
        records.append(
            {
                "unique_code": unique_code,
                "contest_group": contest_group,
                "place_type": place_type,
                "priority": priority,
                "rank_position": rank_position if rank_position is not None else 10**9,
                "score": score if score is not None else 0,
                "document_type": document_type,
                "has_consent": str(has_consent).lower(),
                "snapshot_time": snapshot_time,
                "source_url": source_url,
            }
        )
    return records


def parse_applicants(manifest_path: Path = RAW_DIR / "manifest.json") -> Path:
    ensure_runtime_dirs()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    snapshot_time = manifest.get("fetched_at", utc_now_iso())
    rows: list[dict] = []

    for source in manifest.get("sources", []):
        saved_to = source.get("saved_to", "")
        if "applications_" not in Path(saved_to).name:
            continue
        raw_path = Path(saved_to)
        if not raw_path.exists():
            continue
        html_text = raw_path.read_text(encoding="utf-8")
        title = _extract_title(html_text)
        page_rows: list[dict] = []
        for table in parse_tables(html_text):
            page_rows.extend(
                _extract_table_rows(
                    table=table,
                    source_url=source.get("source_url", ""),
                    snapshot_time=snapshot_time,
                    title=title,
                )
            )
        if not page_rows:
            page_rows = _extract_rows_regex(
                html_text=html_text,
                source_url=source.get("source_url", ""),
                snapshot_time=snapshot_time,
            )
        rows.extend(page_rows)

    # Keep best line per (code, group, place type): best rank, then highest score.
    deduped: dict[tuple[str, str, str], dict] = {}
    for row in rows:
        key = (row["unique_code"], row["contest_group"], row["place_type"])
        current = deduped.get(key)
        if current is None:
            deduped[key] = row
            continue
        better_rank = int(row["rank_position"]) < int(current["rank_position"])
        better_score = int(row["score"]) > int(current["score"])
        if better_rank or (int(row["rank_position"]) == int(current["rank_position"]) and better_score):
            deduped[key] = row

    output_rows = sorted(
        deduped.values(),
        key=lambda item: (
            item["contest_group"],
            item["place_type"],
            int(item["priority"]),
            int(item["rank_position"]),
        ),
    )
    output_path = NORMALIZED_DIR / "applicants.csv"
    write_csv(
        output_path,
        rows=output_rows,
        fieldnames=[
            "unique_code",
            "contest_group",
            "place_type",
            "priority",
            "rank_position",
            "score",
            "document_type",
            "has_consent",
            "snapshot_time",
            "source_url",
        ],
    )
    return output_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Parse applicants tables")
    parser.add_argument(
        "--manifest-path",
        type=Path,
        default=RAW_DIR / "manifest.json",
        help="Path to raw data manifest",
    )
    args = parser.parse_args()
    output_path = parse_applicants(args.manifest_path)
    print(f"Applicants saved to: {output_path}")


if __name__ == "__main__":
    main()
