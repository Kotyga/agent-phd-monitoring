from __future__ import annotations

from dataclasses import dataclass, field
from html.parser import HTMLParser


@dataclass
class HtmlCell:
    text: str
    links: list[str] = field(default_factory=list)


class TableExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._tables: list[list[list[HtmlCell]]] = []
        self._in_table = False
        self._in_row = False
        self._in_cell = False
        self._current_cell_text: list[str] = []
        self._current_cell_links: list[str] = []
        self._current_row: list[HtmlCell] = []
        self._current_table: list[list[HtmlCell]] = []
        self._anchor_depth = 0

    @property
    def tables(self) -> list[list[list[HtmlCell]]]:
        return self._tables

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "table":
            self._in_table = True
            self._current_table = []
            return
        if not self._in_table:
            return
        if tag == "tr":
            self._in_row = True
            self._current_row = []
        elif tag in {"td", "th"}:
            self._in_cell = True
            self._current_cell_text = []
            self._current_cell_links = []
        elif tag == "a":
            self._anchor_depth += 1
            href = dict(attrs).get("href")
            if href:
                self._current_cell_links.append(href)

    def handle_endtag(self, tag: str) -> None:
        if tag == "table" and self._in_table:
            self._in_table = False
            if self._current_table:
                self._tables.append(self._current_table)
            self._current_table = []
            return
        if not self._in_table:
            return
        if tag in {"td", "th"} and self._in_cell:
            self._in_cell = False
            cell = HtmlCell(
                text=" ".join("".join(self._current_cell_text).split()),
                links=self._current_cell_links.copy(),
            )
            self._current_row.append(cell)
        elif tag == "tr" and self._in_row:
            self._in_row = False
            if self._current_row:
                self._current_table.append(self._current_row)
            self._current_row = []
        elif tag == "a" and self._anchor_depth > 0:
            self._anchor_depth -= 1

    def handle_data(self, data: str) -> None:
        if self._in_table and self._in_row and self._in_cell:
            self._current_cell_text.append(data)


def parse_tables(html_text: str) -> list[list[list[HtmlCell]]]:
    parser = TableExtractor()
    parser.feed(html_text)
    return parser.tables
