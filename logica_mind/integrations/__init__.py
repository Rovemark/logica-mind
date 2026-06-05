"""Framework adapters — make Logica Mind the memory behind LangChain / LlamaIndex."""

__all__ = ["LangChainMemory", "LlamaIndexMemory"]


def __getattr__(name):
    if name == "LangChainMemory":
        from .langchain import LogicaMindMemory
        return LogicaMindMemory
    if name == "LlamaIndexMemory":
        from .llamaindex import LogicaMindMemory
        return LogicaMindMemory
    raise AttributeError(name)
