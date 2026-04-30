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

const route = useRoute();
</script>
