import copy
import inspect
import json
from pydantic import BaseModel, Field
from typing import Callable, get_type_hints
from types import UnionType


def merge_dicts(dest: dict, source: dict) -> dict:
    """
    Recursively merges 'source' into 'dest' without overwriting existing
    non-dict values. If both values are dicts, they are merged recursively.
    """
    for key, value in source.items():
        if key not in dest:
            dest[key] = value
        else:
            if isinstance(dest[key], dict) and isinstance(value, dict):
                merge_dicts(dest[key], value)
            # Otherwise, do not overwrite existing values.
    return dest


def get_json_type(py_type):
    types_map = {
        str: "string",
        float: "number",
        int: "integer",
        bool: "boolean",
        list: "array",
        set: "array",
        tuple: "array",
        dict: "object",
        type(None): "null",
    }

    if py_type in types_map:
        return types_map[py_type]
    elif getattr(py_type, "__origin__", 0) in types_map:
        return types_map[getattr(py_type, "__origin__", 0)]
    elif isinstance(py_type, UnionType):
        return [get_json_type(sub) for sub in py_type.__args__]
    else:
        return "anyOf"


def extract_params(func: Callable, template: dict, add_code: bool = False):
    # We do not mutate the original template
    template_copy = copy.deepcopy(template)

    # Get annotations (excluding return)
    type_hints = get_type_hints(func)
    type_hints.pop("return", None)

    # Prepare a dictionary with data from the function
    new_dict = {
        "name": func.__name__,
        "strict": True,
        "parameters": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    }

    sig = inspect.signature(func)

    # Формируем список обязательных параметров
    for param_name, param in sig.parameters.items():
        # Определяем, есть ли default
        has_default = param.default != inspect.Parameter.empty

        # Если нет дефолта, делаем параметр обязательным
        if not has_default:
            new_dict["parameters"]["required"].append(param_name)

        new_dict["parameters"]["additionalProperties"] = False
        # Определяем тип
        param_type = type_hints.get(param_name)

        # Если параметр — Pydantic-модель
        if param_type and issubclass(param_type, BaseModel):
            prop_def = param_type.model_json_schema()
            # Если есть default — добавляем
            if has_default:
                prop_def["default"] = param.default
        # Если тип есть
        elif param_type is not None:
            prop_def = {"type": get_json_type(param_type)}
            # Добавляем default, если есть
            if has_default:
                prop_def["default"] = param.default
        else:
            # Если аннотации нет
            prop_def = {"type": "anyOf"}
            if has_default:
                prop_def["default"] = param.default

        prop_def["additionalProperties"] = False
        new_dict["parameters"]["properties"][param_name] = prop_def

    # Merge template_copy (dest, higher priority) with new_dict (source, lower priority)
    final_merged = merge_dicts(template_copy, new_dict)

    # Append code if it is needed
    if add_code:
        if final_merged.get("description"):
            final_merged["description"] += "\ncode:\n" + inspect.getsource(func)
        else:
            final_merged["description"] = "code:\n" + inspect.getsource(func)

    return final_merged


# ===================== Example Usage =====================
if __name__ == "__main__":
    template = {
        "description": "Get current weather for a city",
        "name": "get_weather",
        "strict": True,
        "parameters": {
            "type": "object",
            "properties": {
                "city": {"type": "array"},
                "key": {"type": "string"},
            },
        },
    }

    class CitySchema(BaseModel):
        name: str = Field(..., description="The city name in English")

    def get_weather(city: CitySchema, key: str = "aboba") -> str:
        return "Weather is nice), 24 degrees"

    output = extract_params(get_weather, template)
    print(json.dumps(output, indent=4, ensure_ascii=False))
