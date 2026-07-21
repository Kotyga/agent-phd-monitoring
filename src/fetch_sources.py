from __future__ import annotations

import argparse
import re
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Iterable
from urllib.parse import urljoin
from urllib.request import Request, urlopen

try:
    from .common import RAW_DIR, ensure_runtime_dirs, utc_now_iso, write_json
except ImportError:  # pragma: no cover - for direct script execution
    from common import RAW_DIR, ensure_runtime_dirs, utc_now_iso, write_json


DECREE_URL = "https://pk.mipt.ru/phd/2026_decree/"
PLACES_URL = "https://pk.mipt.ru/phd/2026_places/"


@dataclass
class SourceSnapshot:
    source_url: str
    saved_to: str
    fetched_at: str


def fetch_url(url: str, timeout: int = 30) -> str:
    request = Request(
        url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (X11; Linux x86_64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/126.0 Safari/537.36"
            )
        },
    )
    with urlopen(request, timeout=timeout) as response:
        return response.read().decode("utf-8", errors="replace")


def extract_applications_links(decree_html: str) -> list[str]:
    # Links in decree page point to per-group lists hosted at priem.mipt.ru.
    raw_links = re.findall(
        r'href=["\']([^"\']*applications(?:_v2|%5Fv2)[^"\']+)["\']',
        decree_html,
        flags=re.IGNORECASE,
    )
    unique_links = sorted(set(urljoin(DECREE_URL, link) for link in raw_links))
    return unique_links


def write_raw_html(name: str, html_text: str) -> Path:
    path = RAW_DIR / f"{name}.html"
    path.write_text(html_text, encoding="utf-8")
    return path


def fetch_all_sources() -> dict:
    ensure_runtime_dirs()
    fetched_at = utc_now_iso()

    decree_html = fetch_url(DECREE_URL)
    places_html = fetch_url(PLACES_URL)
    decree_path = write_raw_html("2026_decree", decree_html)
    places_path = write_raw_html("2026_places", places_html)

    application_links = extract_applications_links(decree_html)
    application_snapshots: list[SourceSnapshot] = []

    for index, app_url in enumerate(application_links, start=1):
        html_text = fetch_url(app_url)
        output = write_raw_html(f"applications_{index:03d}", html_text)
        application_snapshots.append(
            SourceSnapshot(source_url=app_url, saved_to=str(output), fetched_at=fetched_at)
        )

    snapshots: list[SourceSnapshot] = [
        SourceSnapshot(source_url=DECREE_URL, saved_to=str(decree_path), fetched_at=fetched_at),
        SourceSnapshot(source_url=PLACES_URL, saved_to=str(places_path), fetched_at=fetched_at),
        *application_snapshots,
    ]

    manifest = {
        "fetched_at": fetched_at,
        "sources": [asdict(item) for item in snapshots],
        "application_links": application_links,
    }
    write_json(RAW_DIR / "manifest.json", manifest)
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch MIPT admission sources")
    parser.add_argument(
        "--print-summary",
        action="store_true",
        help="Print brief summary after fetching data",
    )
    args = parser.parse_args()

    manifest = fetch_all_sources()
    if args.print_summary:
        print(f"Fetched: {len(manifest['sources'])} pages")
        print(f"Applications pages: {len(manifest['application_links'])}")
        print(f"Raw data directory: {RAW_DIR}")


if __name__ == "__main__":
    main()
