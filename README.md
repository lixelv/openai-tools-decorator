# openai_tools_decorator

A lightweight Python library that streamlines creating and invoking “tools” (functions) in your OpenAI ChatCompletion-based projects. It lets you register and call both **synchronous** and **asynchronous** functions via decorators.

## Installation

```bash
pip install openai_tools_decorator
```

## Quick Start

### 1. Import and Initialization

```python
from openai_tools_decorator import OpenAIT

client = OpenAIT()
```

### 2. Adding Tools

Wrap your function (sync or async) with `@client.add_tool(...)`. The decorator registers it and provides a JSON Schema describing the function’s parameters:

```python
@client.add_tool(
    {
        "description": "Get current weather for a city",
        "parameters": {
            "type": "object",
            "properties": {
                "city": {"type": "string", "description": "The city name in English"}
            },
            "required": ["city"]
        },
    }
)
def get_weather(city: str):
    # Or async def get_weather(...) if you prefer
    return f"Weather in {city}: 25°C"
```

### 3. Using Tools with Chat

When you call `run_with_tool(...)` or `run_with_tool_by_thread_id(...)`, the ChatCompletion model can opt to invoke any matching tool. For example:

```python
user_input = "How cold is it in Moscow right now?"
response = await client.run_with_tool(
    user_input,
    messages=[],
    model="gpt-4o"
)
print(response)  # The assistant’s response, possibly including a tool call
```

## Example

```python
import asyncio
import aiohttp
from openai_tools_decorator import OpenAIT

client = OpenAIT()
api_key = "<YOUR_API_KEY>"

async def fetch_url(url):
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as resp:
            return await resp.text()

@client.add_tool(
    {
        "description": "Fetch weather from an API",
        "parameters": {
            "type": "object",
            "properties": {
                "city": {
                    "type": "string",
                    "description": "The city name in English"
                }
            },
            "required": ["city"]
        },
    }
)
async def get_weather(city: str):
    url = f"https://api.openweathermap.org/data/2.5/weather?q={city}&appid={api_key}&units=metric"
    return await fetch_url(url)

async def main():
    question = "What's the temperature in London?"
    result = await client.run_with_tool(question, messages=[])
    print("Assistant says:", result)

asyncio.run(main())
```

## Key Points

-   You can decorate **both synchronous and asynchronous** functions.
-   Tools get automatically registered and described for the OpenAI model.
-   The model decides whether or not to call your tool during the conversation.

## License

Distributed under MIT or any other license of your choice. Contributions and feedback are always welcome!
