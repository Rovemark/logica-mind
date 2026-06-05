import { LayoutGrid, BarChart3, Layers, Network, List, CalendarDays, MessagesSquare, UserRound, Sparkles, Telescope, Users, History, FolderGit2, Moon } from "lucide-react";
import type { ComponentType } from "react";

export type ViewKey = "overview" | "analytics" | "context" | "graph" | "memories" | "calendar" | "sessions" | "user" | "peers" | "observations" | "changes" | "insights" | "workspace" | "dreams";

export interface ViewDef { key: ViewKey; label: string; Icon: ComponentType<{ size?: number; strokeWidth?: number }>; }

export const VIEWS: ViewDef[] = [
  { key: "overview", label: "Overview", Icon: LayoutGrid },
  { key: "analytics", label: "Analytics", Icon: BarChart3 },
  { key: "context", label: "Context", Icon: Layers },
  { key: "graph", label: "Graph", Icon: Network },
  { key: "memories", label: "Memories", Icon: List },
  { key: "calendar", label: "Calendar", Icon: CalendarDays },
  { key: "sessions", label: "Sessions", Icon: MessagesSquare },
  { key: "user", label: "User", Icon: UserRound },
  { key: "peers", label: "Peers", Icon: Users },
  { key: "observations", label: "Observations", Icon: Telescope },
  { key: "changes", label: "Changes", Icon: History },
  { key: "insights", label: "Insights", Icon: Sparkles },
  { key: "workspace", label: "Workspace", Icon: FolderGit2 },
  { key: "dreams", label: "Dreams", Icon: Moon },
];
