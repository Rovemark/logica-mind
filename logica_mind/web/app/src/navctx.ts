import { createContext, useContext } from "react";
import type { ViewKey } from "./nav";

export interface MemFilter { dimension?: string; category?: string; label?: string }

// global navigation so any view can make things clickable — jump to another view,
// scope to a namespace, or open the Memories list pre-filtered by a dimension or
// category — without prop-threading through every component.
export const NavCtx = createContext<{
  onView: (v: ViewKey) => void;
  onNs: (ns: string) => void;
  onMemories: (ns: string, filter?: MemFilter) => void;
  onEntity: (ns: string, name: string) => void;   // open an entity in the graph
}>({
  onView: () => {}, onNs: () => {}, onMemories: () => {}, onEntity: () => {},
});
export const useNav = () => useContext(NavCtx);
