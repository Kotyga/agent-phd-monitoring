from mcp.server.fastmcp import FastMCP
from datetime import datetime
import pandas as pd
import subprocess
import sys
from pathlib import Path
from bs4 import BeautifulSoup
from typing import Any

mcp = FastMCP('mipt-phd')

FILE_PATH_EXCEL = Path(
    "./agent-phd-monitoring/reports/admission_snapshot.xlsx"
)

FILE_PATH_HTML = Path(
    "./agent-phd-monitoring/reports/index.html"
)

FILE_PATH_MD = Path(
    "./agent-phd-monitoring/reports/md"
)

@mcp.tool()
def read_rating_neighbours(
    unique_code: int,
    place_type: str,
    contest_group: str,
) -> dict:
    """
    Возвращает абитуриента и ближайших участников выше и ниже в рейтинге.
    """
    df = pd.read_excel(FILE_PATH_EXCEL)

    required_columns = {
        "unique_code",
        "place_type",
        "contest_group",
        "rank_position",
    }
    missing = required_columns - set(df.columns)

    if missing:
        raise ValueError(
            f"В Excel отсутствуют колонки: {sorted(missing)}"
        )

    group = df[
        (df["place_type"] == place_type)
        & (df["contest_group"] == contest_group)
    ].copy()

    current = group[group["unique_code"].astype(str) == str(unique_code)]

    if current.empty:
        return {
            "found": False,
            "applicant": None,
            "above": None,
            "below": None,
        }

    current_row = current.iloc[0]
    current_rank = current_row["rank_position"]

    above = group[group["rank_position"] < current_rank].sort_values(
        "rank_position",
        ascending=False,
    )
    below = group[group["rank_position"] > current_rank].sort_values(
        "rank_position",
        ascending=True,
    )

    def serialize(row):
        if row is None:
            return None

        return {
            str(column): None if pd.isna(value) else value
            for column, value in row.items()
        }

    return {
        "found": True,
        "applicant": serialize(current_row),
        "above": serialize(above.iloc[0]) if not above.empty else None,
        "below": serialize(below.iloc[0]) if not below.empty else None,
    }

@mcp.tool()
def get_info_snapshot() -> str:
    """
    Возвращает указанную в HTML-отчёте дату и время последнего обновления.

    Returns:
        str: Например,
            `Последнее обновление: 2026-08-03T07:52:16+00:00 UTC`.

    Raises:
        FileNotFoundError: Если HTML-отчёт не найден.
        ValueError: Если элемент с информацией об обновлении отсутствует.
    """
    html_path = Path(FILE_PATH_HTML)

    if not html_path.is_file():
        raise FileNotFoundError(f"HTML-отчёт не найден: {html_path}")

    soup = BeautifulSoup(
        html_path.read_text(encoding="utf-8"),
        "html.parser",
    )

    meta = soup.select_one("p.meta")

    if meta is None:
        raise ValueError("В HTML-отчёте не найден элемент `p.meta`")

    value = meta.get_text(" ", strip=True)

    if not value.startswith("Последнее обновление:"):
        raise ValueError(
            f"Элемент `p.meta` имеет неожидаемое содержимое: {value}"
        )

    return value

@mcp.tool()
def read_excel_columns() -> list[str]:
    """
    Возвращает названия всех столбцов актуального Excel-снимка.

    Returns:
        list[str]: Названия столбцов в исходном порядке.
    """
    if not FILE_PATH_EXCEL.is_file():
        raise FileNotFoundError(
            f"Excel-снимок не найден: {FILE_PATH_EXCEL}"
        )

    return [
        str(column)
        for column in pd.read_excel(FILE_PATH_EXCEL, nrows=0).columns
    ]

@mcp.tool()
def read_column_value(column: str) -> list:
    """
    Возвращает список уникальных значений указанного столбца Excel-снимка.

    Args:
        column: Название столбца.

    Returns:
        list: Уникальные значения столбца.

    Raises:
        ValueError: Если указанный столбец отсутствует.
    """
    df = pd.read_excel(FILE_PATH_EXCEL)

    if column not in df.columns:
        raise ValueError(f"Неизвестный столбец: {column}")

    return df[column].dropna().unique().tolist()

@mcp.tool()
def read_filter_condition(filters: dict[str, Any]) -> str:
    """
    Читает Excel-снимок и возвращает строки, соответствующие фильтрам.

    Каждый ключ объекта `filters` является названием столбца. Значение может
    быть одиночным значением или списком допустимых значений.

    Если передано одиночное значение, выполняется точное сравнение:

        {"status": "green"}

    Если передан список, возвращаются строки, в которых значение столбца
    совпадает с любым элементом списка:

        {"status": ["green", "yellow"]}

    Несколько фильтров объединяются условием AND:

        {
            "status": ["green", "yellow"],
            "priority": 1
        }

    Args:
        filters: Словарь фильтров в формате
            `{название_столбца: значение_или_список}`.

    Returns:
        str: Найденные строки в текстовом табличном формате. Если совпадений
        нет, возвращается соответствующее сообщение.

    Raises:
        ValueError: Если указан неизвестный столбец или список значений пуст.
    """
    df = pd.read_excel(FILE_PATH_EXCEL)

    for column, value in filters.items():
        if column not in df.columns:
            raise ValueError(f"Неизвестный столбец: {column}")

        if isinstance(value, list):
            if not value:
                raise ValueError(
                    f"Для столбца «{column}» передан пустой список значений"
                )

            df = df[df[column].isin(value)]
        else:
            df = df[df[column] == value]

    if df.empty:
        return "По заданным условиям строки не найдены."

    return df.to_string(index=False)


def _get_safe_md_path(filename: str) -> Path:
    """
    Возвращает безопасный путь к Markdown-файлу внутри FILE_PATH_MD.

    Запрещает передачу вложенных и абсолютных путей, чтобы MCP-инструмент
    не мог прочитать произвольный файл за пределами папки со снимками.
    """
    if not filename:
        raise ValueError("Имя файла не может быть пустым")

    file_path = Path(filename)

    if file_path.name != filename:
        raise ValueError("Необходимо передать только имя файла без пути")

    if file_path.suffix.lower() != ".md":
        raise ValueError("Поддерживаются только файлы с расширением .md")

    return FILE_PATH_MD/ file_path


@mcp.tool()
def get_current_time() -> str:
    """
    Возвращает текущие локальные дату и время в формате ISO 8601.

    Пример результата:
        `2025-07-19T09:10:03+03:00`

    Значение предназначено для отображения в отчёте. Имя нового Markdown-снимка
    формируется автоматически инструментом `write_file`.
    """
    return datetime.now().astimezone().isoformat(timespec="seconds")


@mcp.tool()
def read_dir() -> list[str]:
    """
    Возвращает список сохранённых Markdown-снимков конкурсной позиции.

    Файлы сортируются от самого нового к самому старому. Ожидается, что
    их имена имеют формат `YYYY_MM_DD_HH_MM_SS_microseconds.md`.

    Returns:
        list[str]: Имена Markdown-файлов. Если снимков ещё нет, возвращается
        пустой список.
    """
    FILE_PATH_MD.mkdir(parents=True, exist_ok=True)

    return sorted(
        (
            path.name
            for path in FILE_PATH_MD.iterdir()
            if path.is_file() and path.suffix.lower() == ".md"
        ),
        reverse=True,
    )


@mcp.tool()
def write_file(content: str) -> str:
    """
    Сохраняет новый текстовый снимок анализа конкурсной позиции.

    Имя файла создаётся автоматически на основе текущих локальных даты
    и времени в формате:

        `YYYY_MM_DD_HH_MM_SS_microseconds.md`

    Микросекунды добавлены, чтобы два последовательных запуска не создали
    файлы с одинаковыми именами. Существующие снимки не перезаписываются.

    Args:
        content: Полный текст нового анализа. Текст может содержать текущее
            место в рейтинге, ближайших преследователей, попадание в бюджетное
            окно, расчёт с учётом согласий и сравнение с предыдущим снимком.

    Returns:
        str: Полный путь к созданному Markdown-файлу.
    """
    FILE_PATH_MD.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().astimezone().strftime(
        "%Y_%m_%d_%H_%M_%S_%f"
    )
    file_path = FILE_PATH_MD / f"{timestamp}.md"

    file_path.write_text(content, encoding="utf-8")

    return str(file_path)


@mcp.tool()
def read_file(filename: str) -> str:
    """
    Читает сохранённый Markdown-снимок конкурсной позиции.

    Args:
        filename: Имя файла из результата `read_dir`, например
            `2025_07_19_09_10_03_123456.md`. Нужно передавать только имя,
            без пути к директории.

    Returns:
        str: Содержимое Markdown-файла.

    Raises:
        ValueError: Если передано некорректное имя или файл не имеет
            расширение `.md`.
        FileNotFoundError: Если указанный файл не существует.
    """
    file_path = _get_safe_md_path(filename)

    if not file_path.is_file():
        raise FileNotFoundError(f"Markdown-снимок не найден: {filename}")

    return file_path.read_text(encoding="utf-8")

@mcp.tool()
def get_phd_snapshot():
    """
    Запускает формирование актуального снимка конкурсных списков аспирантуры.

    Инструмент выполняет скрипт `src/run_pipeline.py` с параметром
    `--skip-fetch`. Это означает, что загрузка новых страниц с сайта
    пропускается, а отчёты формируются на основе уже имеющихся исходных
    данных.

    В результате работы обновляются файлы:

    - `./agent-phd-monitoring/reports/admission_snapshot.xlsx`
      — Excel-снимок конкурсных списков и рассчитанных статусов поступления;

    - `./agent-phd-monitoring/reports/index.html`
      — HTML-отчёт с возможностью поиска абитуриента по уникальному коду.

    Снимок не является накопительным: при каждом запуске предыдущие версии
    файлов перезаписываются. Если требуется сравнение с предыдущим состоянием,
    старый снимок необходимо прочитать или сохранить до вызова этого инструмента.

    Рассчитываемые статусы:

    - `green` — абитуриент проходит на это направление;
    - `yellow` — проходит по конкурсу, но закреплён за направлением с более
      высоким приоритетом;
    - `orange` — не проходит на это направление, но проходит на другое;
    - `red` — не проходит ни на одно направление.

    Returns:
        str: Стандартный вывод (`stdout`) скрипта формирования отчётов.

    Raises:
        subprocess.CalledProcessError: Если скрипт завершился с ненулевым
            кодом возврата.
        FileNotFoundError: Если Python-интерпретатор или файл
            `src/run_pipeline.py` не найден.
    """
    result = subprocess.run(
        [sys.executable, "src/run_pipeline.py", "--skip-fetch"],
        check=True,
        capture_output=True,
        text=True
    )
    return result.stdout

@mcp.tool()
def read_latest_file() -> dict:
    """
    Возвращает последний сохранённый Markdown-снимок конкурсной позиции.

    Returns:
        dict: Объект с полями:

        - `found` — найден ли предыдущий снимок;
        - `filename` — имя последнего файла или `None`;
        - `content` — содержимое файла или `None`.
    """
    FILE_PATH_MD.mkdir(parents=True, exist_ok=True)

    files = sorted(
        (
            path
            for path in FILE_PATH_MD.iterdir()
            if path.is_file() and path.suffix.lower() == ".md"
        ),
        key=lambda path: path.name,
        reverse=True,
    )

    if not files:
        return {
            "found": False,
            "filename": None,
            "content": None,
        }

    latest_file = files[0]

    return {
        "found": True,
        "filename": latest_file.name,
        "content": latest_file.read_text(encoding="utf-8"),
    }

# @mcp.tool()
# def send_report():
#     ...

if __name__ == '__main__':
    mcp.run()
