"""Smallest possible Logica Mind example — no API keys, no extra deps.

This is all it takes to plug Logica Mind in and start storing + recalling memory.
Swap in your own content; the default store (SQLite) and embedder (hashing) work
fully offline.
"""
from logica_mind import LogicaMind

mind = LogicaMind(namespace="my-app")

# remember durable facts (extraction + dedup happen automatically)
mind.remember("The user prefers dark mode and concise answers.")
mind.remember("The user is based in Lisbon and works in fintech.")
mind.remember("The project deadline is the end of the quarter.")

# log a raw conversational turn (episodic, no extraction)
mind.log("Asked about the billing integration today.", role="user")

print("Recall: 'what are the user's preferences?'")
for hit in mind.recall("what are the user's preferences?"):
    print(f"  {hit.score:.3f}  {hit.memory.content}")

print("\nStats:", mind.stats())
