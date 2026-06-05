import { createContext, useContext } from "react";
import type { Memory } from "./api";

// global "open this memory as a note" opener, so any MemoryCard can open the
// Obsidian-style detail pane without prop-threading through every view.
export const MemoryOpenCtx = createContext<(m: Memory) => void>(() => {});
export const useOpenMemory = () => useContext(MemoryOpenCtx);
