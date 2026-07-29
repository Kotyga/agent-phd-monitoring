from __future__ import annotations

import argparse
from collections import defaultdict, deque
from pathlib import Path

try:
    from .common import (
        NORMALIZED_DIR,
        RESULTS_DIR,
        ensure_runtime_dirs,
        normalize_contest_group,
        read_csv,
        write_csv,
    )
except ImportError:  # pragma: no cover - for direct script execution
    from common import (
        NORMALIZED_DIR,
        RESULTS_DIR,
        ensure_runtime_dirs,
        normalize_contest_group,
        read_csv,
        write_csv,
    )


def _group_id(contest_group: str, place_type: str) -> str:
    return f"{contest_group}::{place_type}"


def _to_int(value: str, default: int = 0) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _place_type_priority(place_type: str) -> int:
    normalized = (place_type or "").strip().lower()
    if normalized == "budget":
        return 0
    if normalized == "paid":
        return 1
    return 2


def _build_rankings(applications: list[dict]) -> tuple[dict[str, list[str]], dict[str, dict[str, int]]]:
    grouped_rows: dict[str, list[dict]] = defaultdict(list)
    for row in applications:
        grouped_rows[row["group_id"]].append(row)

    rankings: dict[str, list[str]] = {}
    ranks: dict[str, dict[str, int]] = {}
    for group, rows in grouped_rows.items():
        sorted_rows = sorted(
            rows,
            key=lambda item: (
                _to_int(item["rank_position"], default=10**9),
                -_to_int(item["score"], default=0),
                _to_int(item["priority"], default=999),
                item["unique_code"],
            ),
        )
        unique_codes: list[str] = []
        seen: set[str] = set()
        for row in sorted_rows:
            code = row["unique_code"]
            if code not in seen:
                seen.add(code)
                unique_codes.append(code)
        rankings[group] = unique_codes
        ranks[group] = {code: idx for idx, code in enumerate(unique_codes)}
    return rankings, ranks


def _deferred_acceptance(
    preferences: dict[str, list[str]],
    capacities: dict[str, int],
    group_ranks: dict[str, dict[str, int]],
) -> dict[str, str]:
    accepted_by_group: dict[str, set[str]] = defaultdict(set)
    accepted_group_for_code: dict[str, str] = {}
    preference_index: dict[str, int] = {code: 0 for code in preferences}
    queue = deque(preferences.keys())

    while queue:
        code = queue.popleft()
        prefs = preferences.get(code, [])
        if preference_index[code] >= len(prefs):
            continue
        group = prefs[preference_index[code]]
        preference_index[code] += 1

        current = set(accepted_by_group[group])
        current.add(code)
        ordered = sorted(
            current,
            key=lambda c: group_ranks.get(group, {}).get(c, 10**9),
        )
        keep = set(ordered[: capacities.get(group, 0)])
        rejected = current - keep
        accepted_by_group[group] = keep

        for kept_code in keep:
            accepted_group_for_code[kept_code] = group

        for rejected_code in rejected:
            if accepted_group_for_code.get(rejected_code) == group:
                del accepted_group_for_code[rejected_code]
            queue.append(rejected_code)

    return accepted_group_for_code


def compute_admission(
    applicants_path: Path = NORMALIZED_DIR / "applicants.csv",
    places_path: Path = NORMALIZED_DIR / "places.csv",
) -> tuple[Path, Path]:
    ensure_runtime_dirs()
    applicants_rows = read_csv(applicants_path)
    places_rows = read_csv(places_path)

    capacities: dict[str, int] = {}
    group_meta: dict[str, dict] = {}
    for row in places_rows:
        gid = _group_id(row["contest_group"], row["place_type"])
        capacity = _to_int(row["places"], default=0)
        if capacity <= 0:
            continue
        capacities[gid] = capacity
        group_meta[gid] = row

    applications: list[dict] = []
    for row in applicants_rows:
        contest_group = normalize_contest_group(
            row["contest_group"],
            row["place_type"],
            places_rows,
        )
        gid = _group_id(contest_group, row["place_type"])
        if gid not in capacities:
            continue
        item = dict(row)
        item["contest_group"] = contest_group
        item["group_id"] = gid
        applications.append(item)

    preferences: dict[str, list[dict]] = defaultdict(list)
    for app in applications:
        preferences[app["unique_code"]].append(app)
    pref_group_ids: dict[str, list[str]] = {}
    for code, rows in preferences.items():
        sorted_rows = sorted(
            rows,
            key=lambda item: (
                _place_type_priority(item.get("place_type", "")),
                _to_int(item["priority"], default=999),
                _to_int(item["rank_position"], default=10**9),
                item["group_id"],
            ),
        )
        pref_group_ids[code] = [row["group_id"] for row in sorted_rows]

    ranking_lists, group_ranks = _build_rankings(applications)
    assigned_group_for_code = _deferred_acceptance(pref_group_ids, capacities, group_ranks)

    cutoff_codes: dict[str, set[str]] = {}
    for group_id, ordered_codes in ranking_lists.items():
        cutoff_codes[group_id] = set(ordered_codes[: capacities.get(group_id, 0)])

    # For yellow/orange split we use an "effective queue":
    # candidates assigned to other groups do not occupy seats here.
    removed_prefix_by_group: dict[str, list[int]] = {}
    ranks_by_group = group_ranks
    for group_id, ordered_codes in ranking_lists.items():
        prefix: list[int] = [0]
        removed_count = 0
        for code in ordered_codes:
            assigned = assigned_group_for_code.get(code, "")
            if assigned and assigned != group_id:
                removed_count += 1
            prefix.append(removed_count)
        removed_prefix_by_group[group_id] = prefix

    by_direction_rows: list[dict] = []
    for app in sorted(
        applications,
        key=lambda item: (
            item["contest_group"],
            item["place_type"],
            _to_int(item["rank_position"], default=10**9),
        ),
    ):
        code = app["unique_code"]
        gid = app["group_id"]
        assigned_gid = assigned_group_for_code.get(code, "")
        if assigned_gid == gid:
            status = "green"
        elif assigned_gid:
            code_rank = ranks_by_group.get(gid, {}).get(code, 10**9)
            removed_prefix = removed_prefix_by_group.get(gid, [])
            removed_before = removed_prefix[code_rank] if code_rank < len(removed_prefix) else 10**9
            effective_rank = code_rank - removed_before
            if effective_rank < capacities.get(gid, 0):
                status = "yellow"
            else:
                status = "orange"
        else:
            status = "red"

        by_direction_rows.append(
            {
                "unique_code": code,
                "contest_group": app["contest_group"],
                "place_type": app["place_type"],
                "priority": app["priority"],
                "rank_position": app["rank_position"],
                "score": app["score"],
                "document_type": app.get("document_type", ""),
                "status": status,
                "assigned_group": assigned_gid,
                "assigned_contest_group": group_meta.get(assigned_gid, {}).get("contest_group", ""),
                "assigned_place_type": group_meta.get(assigned_gid, {}).get("place_type", ""),
                "within_cutoff": str(code in cutoff_codes.get(gid, set())).lower(),
                "places_in_group": capacities.get(gid, 0),
            }
        )

    by_code_grouped: dict[str, list[dict]] = defaultdict(list)
    for row in by_direction_rows:
        by_code_grouped[row["unique_code"]].append(row)

    by_code_rows: list[dict] = []
    for code, rows in by_code_grouped.items():
        assigned = assigned_group_for_code.get(code, "")
        selected = next((row for row in rows if row["status"] == "green"), None)
        by_code_rows.append(
            {
                "unique_code": code,
                "assigned_group": assigned,
                "assigned_contest_group": selected["contest_group"] if selected else "",
                "assigned_place_type": selected["place_type"] if selected else "",
                "assigned_document_type": selected["document_type"] if selected else "",
                "green_count": sum(1 for row in rows if row["status"] == "green"),
                "yellow_count": sum(1 for row in rows if row["status"] == "yellow"),
                "orange_count": sum(1 for row in rows if row["status"] == "orange"),
                "red_count": sum(1 for row in rows if row["status"] == "red"),
                "best_priority": min(_to_int(row["priority"], default=999) for row in rows),
            }
        )

    by_direction_path = RESULTS_DIR / "by_direction.csv"
    by_code_path = RESULTS_DIR / "by_code.csv"
    write_csv(
        by_direction_path,
        rows=by_direction_rows,
        fieldnames=[
            "unique_code",
            "contest_group",
            "place_type",
            "priority",
            "rank_position",
            "score",
            "document_type",
            "status",
            "assigned_group",
            "assigned_contest_group",
            "assigned_place_type",
            "within_cutoff",
            "places_in_group",
        ],
    )
    write_csv(
        by_code_path,
        rows=sorted(by_code_rows, key=lambda item: item["unique_code"]),
        fieldnames=[
            "unique_code",
            "assigned_group",
            "assigned_contest_group",
            "assigned_place_type",
            "assigned_document_type",
            "green_count",
            "yellow_count",
            "orange_count",
            "red_count",
            "best_priority",
        ],
    )
    return by_direction_path, by_code_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Compute admission statuses")
    parser.add_argument(
        "--applicants-path",
        type=Path,
        default=NORMALIZED_DIR / "applicants.csv",
        help="Path to normalized applicants CSV",
    )
    parser.add_argument(
        "--places-path",
        type=Path,
        default=NORMALIZED_DIR / "places.csv",
        help="Path to normalized places CSV",
    )
    args = parser.parse_args()

    by_direction, by_code = compute_admission(args.applicants_path, args.places_path)
    print(f"Saved: {by_direction}")
    print(f"Saved: {by_code}")


if __name__ == "__main__":
    main()
