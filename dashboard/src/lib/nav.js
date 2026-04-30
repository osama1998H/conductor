import {
  LayoutDashboard, Activity, ListChecks, AlertTriangle,
  CalendarClock, Users, GitBranch,
} from "lucide-vue-next";

export const NAV_LINKS = [
  { path: "/overview",  label: "Overview",   icon: LayoutDashboard },
  { path: "/feed",      label: "Live Feed",  icon: Activity },
  { path: "/jobs",      label: "Jobs",       icon: ListChecks },
  { path: "/dlq",       label: "DLQ",        icon: AlertTriangle },
  { path: "/schedules", label: "Schedules",  icon: CalendarClock },
  { path: "/workers",   label: "Workers",    icon: Users },
  { path: "/workflows", label: "Workflows",  icon: GitBranch },
];

export function matchPrefix(currentPath, prefix) {
  return currentPath === prefix || currentPath.startsWith(prefix + "/");
}

export function findNavTitle(currentPath) {
  const link = NAV_LINKS.find(l => matchPrefix(currentPath, l.path));
  return link ? link.label : "Conductor";
}
