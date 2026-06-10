# Graph explorer — layouts, facets & spotlight

The dashboard's Graph view is not a static picture: it is an explorer you can
**organize**, **colour** and **interrogate**. This guide covers the three layout
modes, the six colour facets (including the generic **channel** facet), and the
click-spotlight interactions.

---

## Organisation modes (layouts)

The **Organize** button (orbit icon, next to the palette) switches how the graph
is arranged. The choice is remembered per browser.

| Mode | What it does | Best for |
|---|---|---|
| **Web** | Organic force layout (Obsidian-style): connected core centred, fragments ringed around it. | Reading real link structure — clusters emerge from the data. |
| **Orbits** | Facet hubs arranged on an inner circle, each hub's members orbiting it (best-connected innermost). Facet-less nodes form the outer rim. A centre disc shows the active namespace. | The org-map look: *"show me each channel/agent/area as a department with its participants around it."* |
| **Rings** | Concentric tiers by PageRank importance — hubs in the middle, periphery outside — sliced into one angular sector per facet value. | Seeing at a glance what matters most, grouped by facet. |

Switching layouts **morphs** the graph smoothly (nodes keep their identity and
glide to their new positions) instead of teleporting.

Both Orbits and Rings group by the **active colour facet**: colour by agent →
one orbit per agent; by entity type → one per type; by channel → one per
channel, exactly like an organisation map.

## Colour facets

The **palette** button picks what colour (and, in Orbits/Rings, what grouping)
means:

- **Namespace** — one stable colour per agent/clone/namespace.
- **Community** — connected components, each its own colour.
- **Life area** — every one of the 34 dimensions (identity, health, career,
  project_status, biz_revenue, …) gets its own colour; the legend groups them by
  area (Person / Projects / Organization / Business).
- **Entity type** — Concept, Product, Person, Organization, Place, Project:
  covers every graph node.
- **Channel** — where things were *talked about* (see below).
- **Centrality** — a cool→hot gradient by PageRank importance.

Colours are assigned by **golden-angle hue rotation** — every distinct facet
value gets a maximally-separated, stable colour, no matter how many values there
are. Options grey out automatically when the dataset has no data for them.

## The channel facet

The channel facet is **generic by design** — Logica Mind doesn't hardcode any
channel list. Whatever your application writes in `metadata.channel`
(`whatsapp`, `telegram`, `voice`, `sessions`, `slack`, `email`, …) becomes a
facet value:

```python
mind.log("user", "assistant: deploy approved, shipping tonight",
         metadata={"channel": "whatsapp"})
```

or over REST:

```bash
curl -X POST http://127.0.0.1:8420/api/log \
  -d '{"namespace":"astro","text":"…","channel":"telegram"}'
```

Each channel-tagged memory **votes its channel onto every graph entity it
mentions** (word-boundary n-gram matching, same mechanism as life-area
dimensions); the majority wins. The result: switch the graph to *colour by
channel* + *Orbits*, and you get one hub per channel with the people, agents and
topics that actually participated there orbiting it — entities never mentioned
in any tagged conversation sit on the outer rim.

The same voting machinery (`store.tagged(namespace, key)` +
`LogicaMind._entity_facets`) accepts other metadata keys (`project`, `squad`,
`skill`, `source`), so new facets are one tag away.

## Facet filters (keep only what you want)

Whenever a categorical facet is active (namespace, life-area, entity type or
channel), a row of **filter chips** appears — one per value, with its node
count. Chips are **multi-select toggles**: click `voice` and `sessions` off and
the graph keeps **only telegram + whatsapp**, links to hidden nodes included.
A *show all* chip restores everything; switching facet or namespace resets the
filter. Chips and graph share the same colours, so the filter reads like the
legend.

## Spotlight (click interactions)

- **Click a node** → its detail panel opens *and* the canvas spotlights it:
  the node + its direct neighbours stay lit, everything else goes translucent.
- **Click a facet hub** (the labelled disc in Orbits/Rings) → the whole group
  is spotlighted: only that channel's/agent's/area's participants stay visible;
  intra-group links light up. Click the hub again — or empty space — to clear.
- **Hover a node** → an instant preview card with its top memories (served by a
  fast SQL pre-filter, no full-store scan).
- **Path mode** → ask *"how is A related to B?"* and the chain lights up while
  the rest dims.

## Performance notes

The explorer stays smooth at thousands of nodes: a level-of-detail renderer
batches edges by colour while the simulation is hot, labels are viewport-culled,
an idle-suspend loop drops repaints to ~0% CPU when nothing changes, and the
hover/click data paths use an indexed SQL mention pre-filter plus a lazy
unlinked-mentions fetch so opening a busy entity is instant.
