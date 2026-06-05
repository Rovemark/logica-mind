import { createContext, useContext } from "react";
import type { ViewKey } from "./nav";

// global navigation so any view can make things clickable — jump to another view
// or scope to a namespace — without prop-threading through every component.
export const NavCtx = createContext<{ onView: (v: ViewKey) => void; onNs: (ns: string) => void }>({
  onView: () => {}, onNs: () => {},
});
export const useNav = () => useContext(NavCtx);
