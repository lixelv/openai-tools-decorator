import json
import asyncio
import inspect

from openai import OpenAI
from typing import Callable, get_type_hints
from pydantic import BaseModel
from .meta import extract_params


class OpenAIT(OpenAI):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.open_ai_tools = []
        self.tools = {}

    def add_tool(
        self, tool_details: dict = {}, use_metadata: bool = True, add_code: bool = False
    ):
        def decorator(func):
            # Assign the function name to the tool
            tool_details["name"] = func.__name__

            self.open_ai_tools.append(
                {
                    "type": "function",
                    "function": extract_params(func, tool_details, add_code=add_code)
                    if use_metadata
                    else tool_details,
                }
            )

            self.tools[func.__name__] = func

            return func

        return decorator

    def remove_tool(self, tool_name: str):
        if tool_name not in self.tools:
            raise ValueError(f"Function {tool_name} not found")

        self.open_ai_tools = [
            tool for tool in self.open_ai_tools if tool["function"]["name"] != tool_name
        ]
        del self.tools[tool_name]

    def get_tool_details(self, tool_name: str):
        if tool_name not in self.tools:
            raise ValueError(f"Function {tool_name} not found")

        return self.tools[tool_name]

    def pydentificate(self, func: Callable, kwargs: dict = {}) -> dict:
        type_hints = get_type_hints(func)
        type_hints.pop("return", None)

        for param_name, param_type in type_hints.items():
            if param_name in kwargs and issubclass(param_type, BaseModel):
                kwargs[param_name] = param_type.model_validate(kwargs[param_name])

        return kwargs

    async def run_tool(self, tool_name: str, **kwargs) -> str:
        func = self.tools.get(tool_name)
        if not func:
            raise ValueError(f"Function {tool_name} not found")

        # Determine if the function is asynchronous
        if inspect.iscoroutinefunction(func):
            return await func(**self.pydentificate(func, kwargs))
        else:
            return await asyncio.to_thread(
                lambda: func(**self.pydentificate(func, kwargs))
            )

    @staticmethod
    def get_tool_calls(response):
        return getattr(response.choices[0].message, "tool_calls", None)

    async def run_with_tool(
        self, request: str, messages: list[dict], model="gpt-4o", **kwargs
    ) -> str:
        # Add user message
        messages.append({"role": "user", "content": request})

        response = await asyncio.to_thread(
            lambda: self.chat.completions.create(
                model=model, messages=messages, tools=self.open_ai_tools, **kwargs
            )
        )

        # Check for tool calls
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

            # Run all necessary tools
            await asyncio.gather(
                *(
                    self._process_tool_call(tc, messages)
                    for tc in tool_calls
                    if tc.type == "function"
                )
            )

            # Create new request after tool responses
            response = await asyncio.to_thread(
                lambda: self.chat.completions.create(
                    model=model, messages=messages, tools=self.open_ai_tools, **kwargs
                )
            )

        messages.append(
            {"role": "assistant", "content": response.choices[0].message.content}
        )
        return response.choices[0].message.content

    async def run_with_tool_by_thread_id(
        self, request: str, thread_id: str, assistant_id: str, **kwargs
    ) -> str:
        # If thread is empty, add tools, otherwise don't because they're already there
        if len((await self._get_response(thread_id)).data) == 0:
            kwargs["tools"] = self.open_ai_tools

        # Send message to specified thread
        self.beta.threads.messages.create(thread_id, role="user", content=request)
        print(json.dumps(self.open_ai_tools, indent=4))
        run_response = await asyncio.to_thread(
            lambda: self.beta.threads.runs.create_and_poll(
                thread_id=thread_id, assistant_id=assistant_id, **kwargs
            )
        )

        # While status is not "completed", process tool calls
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

        # Return final response
        final_response = await self._get_response(thread_id)
        return final_response.data[0].content[0].text.value

    async def _get_response(self, thread_id: str) -> dict:
        # Return last message
        return self.beta.threads.messages.list(thread_id, limit=1)

    async def _process_tool_call(self, tool_call, messages):
        func_name = tool_call.function.name
        args = json.loads(tool_call.function.arguments)

        if func_name not in self.tools:
            raise Exception(f"Function {func_name} not found")

        result = await self.run_tool(func_name, **args)
        messages.append(
            {"role": "tool", "content": result, "tool_call_id": tool_call.id}
        )

    async def _process_tool_call_with_thread(self, tool_call):
        func_name = tool_call.function.name
        args = json.loads(tool_call.function.arguments)

        if func_name not in self.tools:
            raise Exception(f"Function {func_name} not found")

        function_result = await self.run_tool(func_name, **args)
        return {"tool_call_id": tool_call.id, "output": function_result}

    def __str__(self):
        return str(self.open_ai_tools)
