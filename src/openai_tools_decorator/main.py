import json
import asyncio
import inspect
from openai import OpenAI


class OpenAIT(OpenAI):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.open_ai_tools = []
        self.tools = {}

    def add_tool(self, tool_details):
        def decorator(func):
            # Присваиваем имя функции инструменту
            tool_details["name"] = func.__name__

            self.open_ai_tools.append({"type": "function", "function": tool_details})
            self.tools[func.__name__] = func

            return func

        return decorator

    async def run_tool(self, tool_name: str, **kwargs) -> str:
        func = self.tools.get(tool_name)
        if not func:
            raise ValueError(f"Функция {tool_name} не найдена")

        # Определяем, является ли функция асинхронной
        if inspect.iscoroutinefunction(func):
            return await func(**kwargs)
        return func(**kwargs)

    @staticmethod
    def get_tool_calls(response):
        return getattr(response.choices[0].message, "tool_calls", None)

    async def run_with_tool(
        self, request: str, messages: list[dict], model="gpt-4o"
    ) -> str:
        # Добавляем пользовательское сообщение
        messages.append({"role": "user", "content": request})

        response = await asyncio.to_thread(
            lambda: self.chat.completions.create(
                model=model,
                messages=messages,
                tools=self.open_ai_tools,
            )
        )

        # Проверяем наличие вызовов инструментов
        while self.get_tool_calls(response):
            tool_calls = response.choices[0].message.tool_calls
            messages.append(
                {
                    "role": response.choices[0].message.role,
                    "content": response.choices[0].message.content,
                    "tool_calls": [
                        {
                            "id": tc.id,
                            "type": tc.type,
                            "function": {
                                "name": tc.function.name,
                                "arguments": tc.function.arguments,
                            },
                        }
                        for tc in tool_calls
                    ],
                }
            )

            # Запускаем все инструменты, которые нужны
            await asyncio.gather(
                *(
                    self._process_tool_call(tc, messages)
                    for tc in tool_calls
                    if tc.type == "function"
                )
            )

            # Создаём новый запрос после ответа инструментов
            response = await asyncio.to_thread(
                lambda: self.chat.completions.create(
                    model=model,
                    messages=messages,
                    tools=self.open_ai_tools,
                )
            )

        messages.append(
            {"role": "assistant", "content": response.choices[0].message.content}
        )
        return response.choices[0].message.content

    async def run_with_tool_by_thread_id(
        self, request: str, thread_id: str, **kwargs
    ) -> str:
        # Отправляем сообщение в указанный поток
        self.beta.threads.messages.create(thread_id, role="user", content=request)
        kwargs["tools"] = self.open_ai_tools

        run_response = await asyncio.to_thread(
            lambda: self.beta.threads.runs.create_and_poll(
                thread_id=thread_id, **kwargs
            )
        )

        # Пока статус не "completed", обрабатываем вызовы
        while run_response.status != "completed":
            result = await asyncio.gather(
                *(
                    self._process_tool_call_with_thread(tc)
                    for tc in run_response.required_action.submit_tool_outputs.tool_calls
                    if tc.type == "function"
                )
            )

            run_response = self.beta.threads.runs.submit_tool_outputs_and_poll(
                thread_id=thread_id,
                run_id=run_response.id,
                tool_outputs=result,
            )

        # По завершению возвращаем финальный ответ
        final_response = await self._get_response(thread_id)
        return final_response.data[0].content[0].text.value

    async def _get_response(self, thread_id: str) -> dict:
        # Возвращаем последнее сообщение
        return self.beta.threads.messages.list(thread_id, limit=1)

    async def _process_tool_call(self, tool_call, messages):
        func_name = tool_call.function.name
        args = json.loads(tool_call.function.arguments)

        if func_name not in self.tools:
            raise Exception(f"Функция {func_name} не найдена")

        result = await self.run_tool(func_name, **args)
        messages.append(
            {"role": "tool", "content": result, "tool_call_id": tool_call.id}
        )

    async def _process_tool_call_with_thread(self, tool_call):
        func_name = tool_call.function.name
        args = json.loads(tool_call.function.arguments)

        if func_name not in self.tools:
            raise Exception(f"Функция {func_name} не найдена")

        function_result = await self.run_tool(func_name, **args)
        return {"tool_call_id": tool_call.id, "output": function_result}
