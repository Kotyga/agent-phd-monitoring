from __future__ import annotations

import argparse
import html
import json
from collections import defaultdict
from pathlib import Path

try:
    from .common import REPORTS_DIR, RESULTS_DIR, ensure_runtime_dirs, read_csv, utc_now_iso
except ImportError:  # pragma: no cover - for direct script execution
    from common import REPORTS_DIR, RESULTS_DIR, ensure_runtime_dirs, read_csv, utc_now_iso


STATUS_LABELS = {
    "green": "Проходит сюда",
    "yellow": "Проходит по конкурсу, но закреплён в более высоком приоритете",
    "red": "Не проходит сюда, но проходит в другое направление",
    "gray": "Совсем никуда не проходит",
}


def _escape(text: str) -> str:
    return html.escape(text or "", quote=True)


def _status_class(value: str) -> str:
    return value if value in {"green", "yellow", "red", "gray"} else "gray"


def _build_html(by_direction: list[dict], by_code: list[dict], generated_at: str) -> str:
    grouped: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for row in by_direction:
        grouped[(row["contest_group"], row["place_type"])].append(row)

    index_by_code = {row["unique_code"]: row for row in by_code}
    code_rows_js = json.dumps(index_by_code, ensure_ascii=False)

    sections: list[str] = []
    for (contest_group, place_type), rows in sorted(grouped.items(), key=lambda item: item[0]):
        sorted_rows = sorted(rows, key=lambda r: (int(r["rank_position"]), int(r["priority"]), r["unique_code"]))
        tr_html: list[str] = []
        for row in sorted_rows:
            status = _status_class(row["status"])
            tr_html.append(
                "".join(
                    [
                        f'<tr class="status-{status}">',
                        f'<td>{_escape(row["unique_code"])}</td>',
                        f"<td>{_escape(row.get('document_type', ''))}</td>",
                        f"<td>{_escape(str(row['rank_position']))}</td>",
                        f"<td>{_escape(str(row['priority']))}</td>",
                        f"<td>{_escape(str(row['score']))}</td>",
                        f"<td>{_escape(STATUS_LABELS.get(status, status))}</td>",
                        f"<td>{_escape(row['assigned_contest_group'])}</td>",
                        "</tr>",
                    ]
                )
            )
        title = f"{contest_group} ({'Бюджет' if place_type == 'budget' else 'Платно'})"
        sections.append(
            f"""
            <section class="group">
              <h2>{_escape(title)}</h2>
              <table>
                <thead>
                  <tr>
                    <th>Уникальный код</th>
                    <th>Вид документа</th>
                    <th>Место в рейтинге</th>
                    <th>Приоритет</th>
                    <th>Балл</th>
                    <th>Статус</th>
                    <th>Куда проходит сейчас</th>
                  </tr>
                </thead>
                <tbody>
                  {''.join(tr_html)}
                </tbody>
              </table>
            </section>
            """
        )

    return f"""<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Проверка прохода в аспирантуру МФТИ 2026</title>
  <style>
    body {{ font-family: system-ui, sans-serif; margin: 24px; color: #1f2937; }}
    h1, h2 {{ margin-bottom: 8px; }}
    .meta {{ color: #6b7280; margin-bottom: 16px; }}
    .legend {{ display: flex; gap: 12px; margin: 10px 0 20px; flex-wrap: wrap; }}
    .badge {{ padding: 6px 10px; border-radius: 8px; font-size: 14px; }}
    .green {{ background: #dcfce7; }}
    .yellow {{ background: #fef9c3; }}
    .red {{ background: #fee2e2; }}
    .gray {{ background: #e5e7eb; }}
    .search-box {{ margin-bottom: 20px; }}
    input {{ padding: 8px; min-width: 280px; }}
    #searchResult {{ margin-top: 8px; font-weight: 600; }}
    table {{ border-collapse: collapse; width: 100%; margin-bottom: 24px; }}
    th, td {{ border: 1px solid #e5e7eb; padding: 6px 8px; text-align: left; font-size: 13px; }}
    th {{ background: #f8fafc; }}
    tr.status-green td {{ background: #f0fdf4; }}
    tr.status-yellow td {{ background: #fefce8; }}
    tr.status-red td {{ background: #fef2f2; }}
    tr.status-gray td {{ background: #f3f4f6; }}
  </style>
</head>
<body>
  <h1>Проверка прохода в аспирантуру МФТИ 2026</h1>
  <p class="meta">Последнее обновление: {generated_at} UTC</p>

  <div class="search-box">
    <label for="codeInput">Проверка по уникальному коду:</label><br>
    <input id="codeInput" type="text" placeholder="Введите уникальный код" />
    <button onclick="checkCode()">Проверить</button>
    <div id="searchResult"></div>
  </div>

  <div class="legend">
    <span class="badge green">Зелёный: проходит сюда</span>
    <span class="badge yellow">Жёлтый: проходит в рейтинге, но закреплён выше по приоритету</span>
    <span class="badge red">Красный: не проходит сюда, но проходит в другое направление</span>
    <span class="badge gray">Серый: совсем никуда не проходит</span>
  </div>

  {''.join(sections)}

  <script>
    const codeIndex = {code_rows_js};
    function checkCode() {{
      const input = document.getElementById('codeInput');
      const target = document.getElementById('searchResult');
      const code = (input.value || '').trim();
      if (!code) {{
        target.textContent = 'Введите код';
        return;
      }}
      const item = codeIndex[code];
      if (!item) {{
        target.textContent = 'Код не найден в текущих списках';
        return;
      }}
      if (item.assigned_contest_group) {{
        const place = item.assigned_place_type === 'budget' ? 'бюджет' : 'платно';
        const docType = item.assigned_document_type ? `, документ: ${{item.assigned_document_type}}` : '';
        target.textContent = `Сейчас проходит: ${{item.assigned_contest_group}} (${{place}})${{docType}}`;
      }} else {{
        target.textContent = 'Пока не проходит ни в одну группу';
      }}
    }}
  </script>
</body>
</html>
"""


def _export_xlsx(by_direction: list[dict], output_path: Path) -> None:
    try:
        from openpyxl import Workbook  # type: ignore
    except ImportError:
        # Fallback for environments without openpyxl.
        csv_fallback = output_path.with_suffix(".csv")
        headers = [
            "unique_code",
            "contest_group",
            "place_type",
            "priority",
            "rank_position",
            "score",
            "status",
            "assigned_contest_group",
        ]
        lines = [",".join(headers)]
        for row in by_direction:
            lines.append(",".join(str(row.get(key, "")) for key in headers))
        csv_fallback.write_text("\n".join(lines), encoding="utf-8")
        return

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "admission_snapshot"
    headers = [
        "unique_code",
        "contest_group",
        "place_type",
        "priority",
        "rank_position",
        "score",
        "document_type",
        "status",
        "assigned_contest_group",
    ]
    sheet.append(headers)
    for row in by_direction:
        sheet.append([row.get(key, "") for key in headers])
    workbook.save(output_path)


def build_report(
    by_direction_path: Path = RESULTS_DIR / "by_direction.csv",
    by_code_path: Path = RESULTS_DIR / "by_code.csv",
) -> tuple[Path, Path]:
    ensure_runtime_dirs()
    by_direction = read_csv(by_direction_path)
    by_code = read_csv(by_code_path)
    generated_at = utc_now_iso()

    html_text = _build_html(by_direction, by_code, generated_at=generated_at)
    html_path = REPORTS_DIR / "index.html"
    html_path.write_text(html_text, encoding="utf-8")

    xlsx_path = REPORTS_DIR / "admission_snapshot.xlsx"
    _export_xlsx(by_direction, xlsx_path)
    return html_path, xlsx_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Build HTML report")
    parser.add_argument(
        "--by-direction",
        type=Path,
        default=RESULTS_DIR / "by_direction.csv",
        help="Path to by_direction.csv",
    )
    parser.add_argument(
        "--by-code",
        type=Path,
        default=RESULTS_DIR / "by_code.csv",
        help="Path to by_code.csv",
    )
    args = parser.parse_args()
    html_path, xlsx_path = build_report(args.by_direction, args.by_code)
    print(f"Report: {html_path}")
    print(f"Excel: {xlsx_path}")


if __name__ == "__main__":
    main()
