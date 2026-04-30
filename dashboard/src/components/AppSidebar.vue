<template>
  <Sidebar collapsible="icon">
    <SidebarHeader>
      <div class="flex items-center gap-2 px-2 py-2">
        <div class="flex h-8 w-8 items-center justify-center rounded-md bg-primary text-primary-foreground font-bold">
          C
        </div>
        <span class="font-semibold group-data-[collapsible=icon]:hidden">Conductor</span>
      </div>
    </SidebarHeader>
    <SidebarContent>
      <SidebarGroup>
        <SidebarGroupLabel>Operations</SidebarGroupLabel>
        <SidebarGroupContent>
          <SidebarMenu>
            <SidebarMenuItem v-for="link in navLinks" :key="link.to">
              <SidebarMenuButton as-child :is-active="isActive(link.to)" :tooltip="link.label">
                <RouterLink :to="link.to">
                  <component :is="link.icon" />
                  <span>{{ link.label }}</span>
                </RouterLink>
              </SidebarMenuButton>
            </SidebarMenuItem>
          </SidebarMenu>
        </SidebarGroupContent>
      </SidebarGroup>
    </SidebarContent>
  </Sidebar>
</template>

<script setup>
import { useRoute, RouterLink } from "vue-router";
import {
  LayoutDashboard, Activity, ListChecks, AlertTriangle,
  CalendarClock, Users, GitBranch,
} from "lucide-vue-next";
import {
  Sidebar,
  SidebarContent,
  SidebarGroup,
  SidebarGroupContent,
  SidebarGroupLabel,
  SidebarHeader,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
} from "@/components/ui/sidebar";

const route = useRoute();

const navLinks = [
  { to: "/overview",  label: "Overview",   icon: LayoutDashboard },
  { to: "/feed",      label: "Live Feed",  icon: Activity },
  { to: "/jobs",      label: "Jobs",       icon: ListChecks },
  { to: "/dlq",       label: "DLQ",        icon: AlertTriangle },
  { to: "/schedules", label: "Schedules",  icon: CalendarClock },
  { to: "/workers",   label: "Workers",    icon: Users },
  { to: "/workflows", label: "Workflows",  icon: GitBranch },
];

function isActive(prefix) {
  return route.path === prefix || route.path.startsWith(prefix + "/");
}
</script>
