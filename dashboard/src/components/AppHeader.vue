<template>
  <header class="flex h-14 shrink-0 items-center gap-2 border-b px-4">
    <SidebarTrigger />
    <Separator orientation="vertical" class="mr-2 h-4" />
    <Breadcrumb>
      <BreadcrumbList>
        <BreadcrumbItem>
          <BreadcrumbPage>{{ pageTitle }}</BreadcrumbPage>
        </BreadcrumbItem>
      </BreadcrumbList>
    </Breadcrumb>
    <div class="ml-auto">
      <ModeToggle />
    </div>
  </header>
</template>

<script setup>
import { computed } from "vue";
import { useRoute } from "vue-router";
import { SidebarTrigger } from "@/components/ui/sidebar";
import { Separator } from "@/components/ui/separator";
import {
  Breadcrumb,
  BreadcrumbItem,
  BreadcrumbList,
  BreadcrumbPage,
} from "@/components/ui/breadcrumb";
import ModeToggle from "@/components/ModeToggle.vue";

const route = useRoute();

const TITLES = {
  "/overview": "Overview",
  "/feed": "Live Feed",
  "/jobs": "Jobs",
  "/dlq": "DLQ",
  "/schedules": "Schedules",
  "/workers": "Workers",
  "/workflows": "Workflows",
};

const pageTitle = computed(() => {
  const match = Object.keys(TITLES).find(p => route.path === p || route.path.startsWith(p + "/"));
  return match ? TITLES[match] : "Conductor";
});
</script>
