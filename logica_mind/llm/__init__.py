"""LLM providers. Default NullLLM keeps the library usable with no LLM at all."""
from .base import LLM, NullLLM, extract_json

__all__ = ["LLM", "NullLLM", "OpenAILLM", "extract_json"]


def __getattr__(name):
    if name == "OpenAILLM":
        from .openai import OpenAILLM
        return OpenAILLM
    raise AttributeError(name)
