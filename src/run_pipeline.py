from __future__ import annotations

import argparse
import logging
from pathlib import Path

try:
    from .build_report import build_report
    from .common import LOGS_DIR, ensure_runtime_dirs
    from .compute_admission import compute_admission
    from .fetch_sources import fetch_all_sources
    from .parse_applicants import parse_applicants
    from .parse_places import parse_places
except ImportError:  # pragma: no cover - for direct script execution
    from build_report import build_report
    from common import LOGS_DIR, ensure_runtime_dirs
    from compute_admission import compute_admission
    from fetch_sources import fetch_all_sources
    from parse_applicants import parse_applicants
    from parse_places import parse_places


def _configure_logger(log_path: Path) -> logging.Logger:
    logger = logging.getLogger("phd_pipeline")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()

    formatter = logging.Formatter("%(asctime)s | %(levelname)s | %(message)s")

    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)
    logger.addHandler(stream_handler)

    file_handler = logging.FileHandler(log_path, encoding="utf-8")
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    return logger


def run_pipeline(skip_fetch: bool = False) -> dict:
    ensure_runtime_dirs()
    log_path = LOGS_DIR / "pipeline.log"
    logger = _configure_logger(log_path)
    logger.info("Pipeline started")

    result: dict = {"status": "ok"}
    try:
        if not skip_fetch:
            manifest = fetch_all_sources()
            logger.info("Fetched sources: %s", len(manifest.get("sources", [])))
        applicants_path = parse_applicants()
        places_path = parse_places()
        logger.info("Normalized files: %s, %s", applicants_path, places_path)

        by_direction_path, by_code_path = compute_admission(applicants_path, places_path)
        logger.info("Computed admission: %s, %s", by_direction_path, by_code_path)

        report_path, excel_path = build_report(by_direction_path, by_code_path)
        logger.info("Generated report: %s", report_path)
        logger.info("Generated excel: %s", excel_path)
        result.update(
            {
                "report_path": str(report_path),
                "excel_path": str(excel_path),
                "log_path": str(log_path),
            }
        )
    except Exception as exc:  # noqa: BLE001 - want full fail-safe log
        logger.exception("Pipeline failed: %s", exc)
        result["status"] = "error"
        result["error"] = str(exc)
        result["log_path"] = str(log_path)
        raise
    finally:
        logger.info("Pipeline finished")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Run full admission pipeline")
    parser.add_argument(
        "--skip-fetch",
        action="store_true",
        help="Do not fetch web pages, reuse current raw snapshots",
    )
    args = parser.parse_args()

    output = run_pipeline(skip_fetch=args.skip_fetch)
    print(output)


if __name__ == "__main__":
    main()
