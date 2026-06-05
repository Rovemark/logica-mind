import { LayoutGrid, BarChart3, Layers, Network, List, CalendarDays, MessagesSquare, Sparkles, Telescope, Users, History, FolderGit2, Moon, Boxes } from "lucide-react";
import type { ComponentType } from "react";

export type ViewKey = "overview" | "analytics" | "context" | "graph" | "memories" | "calendar" | "sessions" | "user" | "profile" | "peers" | "observations" | "changes" | "insights" | "workspace" | "dreams" | "settings";
export type CatKey = "explore" | "memory" | "intelligence" | "system";

export interface ViewDef { key: ViewKey; label: string; Icon: ComponentType<{ size?: number; strokeWidth?: number }>; cat: CatKey; }

export const VIEWS: ViewDef[] = [
  // explore
  { key: "overview", label: "Overview", Icon: LayoutGrid, cat: "explore" },
  { key: "analytics", label: "Analytics", Icon: BarChart3, cat: "explore" },
  { key: "context", label: "Context", Icon: Layers, cat: "explore" },
  { key: "graph", label: "Graph", Icon: Network, cat: "explore" },
  // memory
  { key: "memories", label: "Memories", Icon: List, cat: "memory" },
  { key: "calendar", label: "Calendar", Icon: CalendarDays, cat: "memory" },
  { key: "sessions", label: "Sessions", Icon: MessagesSquare, cat: "memory" },
  { key: "changes", label: "Changes", Icon: History, cat: "memory" },
  // intelligence
  { key: "profile", label: "Profile", Icon: Boxes, cat: "intelligence" },
  { key: "observations", label: "Observations", Icon: Telescope, cat: "intelligence" },
  { key: "insights", label: "Insights", Icon: Sparkles, cat: "intelligence" },
  { key: "peers", label: "Peers", Icon: Users, cat: "intelligence" },
  // system
  { key: "workspace", label: "Workspace", Icon: FolderGit2, cat: "system" },
  { key: "dreams", label: "Dreams", Icon: Moon, cat: "system" },
];

// category order + i18n key for the section label
export const CATS: { key: CatKey; tkey: string }[] = [
  { key: "explore", tkey: "cat_explore" },
  { key: "memory", tkey: "cat_memory" },
  { key: "intelligence", tkey: "cat_intelligence" },
  { key: "system", tkey: "cat_system" },
];
