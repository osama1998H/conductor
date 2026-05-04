<template>
  <Sidebar collapsible="icon">
    <SidebarHeader>
      <div class="flex items-center gap-2 px-2 py-2">
        <img
          :src="logoUrl"
          alt="Conductor"
          class="h-8 w-8 rounded-md object-contain"
        />
        <span class="font-semibold group-data-[collapsible=icon]:hidden">Conductor</span>
      </div>
    </SidebarHeader>
    <SidebarContent>
      <SidebarGroup>
        <SidebarGroupLabel>Operations</SidebarGroupLabel>
        <SidebarGroupContent>
          <SidebarMenu>
            <SidebarMenuItem v-for="link in NAV_LINKS" :key="link.path">
              <SidebarMenuButton as-child :is-active="matchPrefix(route.path, link.path)" :tooltip="link.label">
                <RouterLink :to="link.path">
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
import { NAV_LINKS, matchPrefix } from "@/lib/nav";

// Served by Frappe from `conductor/public/images/`. Bound (not a literal `src`)
// so Vite doesn't try to resolve `/assets/...` against the dashboard build.
const logoUrl = "/assets/conductor/images/logo.png";

const route = useRoute();
</script>
