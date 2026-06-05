"""How an external AI system plugs Logica Mind in as its memory provider.

The host only needs two verbs — recall() and save() — so Logica Mind drops into
any framework (LangChain BaseMemory, LlamaIndex, a raw loop, or a custom host) without
the host knowing anything about stores or embeddings.
"""
from logica_mind import LogicaMind, MemoryLayer


class LogicaMindProvider:
    """Thin, framework-agnostic adapter."""

    def __init__(self, agent_id: str, **mind_kwargs):
        self.mind = LogicaMind(namespace=agent_id, **mind_kwargs)

    # what a host calls before generating a reply
    def recall(self, query: str, limit: int = 6) -> str:
        hits = self.mind.recall(query, limit=limit)
        if not hits:
            return ""
        lines = [f"- {h.memory.content}" for h in hits]
        return "Relevant memory:\n" + "\n".join(lines)

    # what a host calls after a turn
    def save(self, user_msg: str, assistant_msg: str) -> None:
        self.mind.log(user_msg, role="user")
        self.mind.log(assistant_msg, role="assistant")
        # let the model also learn durable facts from the user's message
        self.mind.remember(user_msg)

    # occasional background consolidation
    def dream(self):
        return self.mind.dream()


if __name__ == "__main__":
    provider = LogicaMindProvider(agent_id="support-bot")
    provider.save("My plan is the Pro tier and I'm in Brazil.",
                  "Got it — Pro tier, Brazil. How can I help?")
    print(provider.recall("which plan is the customer on?"))
