# @logica-mind/sdk

Thin TypeScript client for the [Logica Mind](../) memory server.

Run the server (headless):

```bash
logica-mind ui --no-open        # serves the REST API on http://localhost:8420
```

Use it:

```ts
import { LogicaMind } from "@logica-mind/sdk";

const mind = new LogicaMind({ namespace: "my-agent" });

await mind.remember("The user prefers concise answers in Portuguese.");
await mind.log("Talked about the deploy pipeline.", "user");

const hits = await mind.recall("what language should I use?");
for (const h of hits) console.log(h.score, h.memory.content);

console.log(await mind.user());     // dialectic user model
console.log(await mind.stats());
```

Zero dependencies — uses the global `fetch` (Node 18+ or browser). Apache-2.0.
