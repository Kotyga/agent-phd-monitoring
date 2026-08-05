import sys
import asyncio

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_openai import ChatOpenAI
from langchain.agents import create_agent
from langchain_ollama import ChatOllama


async def main():
    global agent
    # llm = ChatOpenAI(
    #     api_key='ollama',
    #     model='gemma4',
    #     base_url='http://localhost:11434/v1/',
    #     temperature=0
    # )

    llm = ChatOllama(
    model="qwen3.5:9b",
    base_url="http://localhost:11434",
    temperature=0,
    num_ctx=16384,
    num_predict=2048,
    )

    mcp_severs = {
        'mcp': {
            'transport': 'stdio',
            'command': sys.executable,
            'args': ['./agent-phd-monitoring/mcp_mipt.py']
        }
    }

    mcp_client = MultiServerMCPClient(mcp_severs)
    tools = await mcp_client.get_tools()

    print('Доступные инструменты', [tool.name for tool in tools])

    agent = create_agent(
        model=llm,
        tools=tools
    )

    messages = [
    SystemMessage(
        content="""
        Ты — консультант по поступлению в аспирантуру МФТИ.

        Используй MCP-инструменты и только фактические данные из Excel, HTML и Markdown.
        Не придумывай отсутствующие значения: используй None.

        Порядок действий:
        1. Прочитай последний Markdown-отчёт, если он существует.
        2. Обнови конкурсный снимок.
        3. Получи время обновления HTML и названия колонок Excel.
        4. Найди абитуриента и соседей по рейтингу в той же группе и типе места.
        5. Проверь остальные заявления соседей.
        6. Определи попадание в бюджетное окно и оцени шансы.
        7. Сравни результат с предыдущим отчётом.
        8. Запиши новый отчёт через write_file.

        Новый Markdown создавай только после чтения предыдущего.
        Отвечай по-русски.
        """
            ),
    HumanMessage(
                content="""
        Проведи анализ:

        unique_code: <your value here>
        place_type: <your value here>
        contest_group: <your value here>
        budget_places: <your value here>

        В Markdown укажи:
        - время обновления и дату отчёта;
        - место, баллы, приоритет, статус и согласие абитуриента;
        - входит ли он в <your value here> бюджетных мест;
        - данные ближайшего участника выше и ниже;
        - другие конкурсные группы этих участников;
        - оценку шансов с кратким обоснованием;
        - предыдущий файл;
        - изменилось ли что-то: Да, Нет или None;
        - описание изменений.

        Если предыдущего файла нет, значения сравнения должны быть None.
        Обязательно сохрани отчёт через write_file и сообщи путь.
        """
            ),
        ]
    result = await agent.ainvoke(
        {"messages": messages},
        config={"recursion_limit": 300},
    )

    final_message = result["messages"][-1]
    report = final_message.content

    if not isinstance(report, str) or not report.strip():
        raise RuntimeError(
            "Агент завершил работу, но не сформировал текст отчёта"
        )

    write_tool = next(
        (tool for tool in tools if tool.name == "write_file"),
        None,
    )

    if write_tool is None:
        raise RuntimeError(
            "MCP-инструмент write_file отсутствует"
        )

    try:
        saved_path = await write_tool.ainvoke({
            "content": report,
        })
    except Exception as error:
        raise RuntimeError(
            f"Не удалось сохранить Markdown-отчёт: {error}"
        ) from error

    print("\nСформированный отчёт:\n")
    print(report)

    print("\nФайл успешно сохранён:")
    print(saved_path)

if __name__ == '__main__':
    asyncio.run(main())
