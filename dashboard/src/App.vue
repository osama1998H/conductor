<template>
  <SidebarProvider>
    <AppSidebar />
    <SidebarInset>
      <AppHeader />
      <main class="flex-1 p-4 overflow-auto">
        <RouterView />
      </main>
    </SidebarInset>
    <ConfirmDialog />
    <Toaster />
  </SidebarProvider>
</template>

<script setup>
import { RouterView } from "vue-router";
import AppSidebar from "@/components/AppSidebar.vue";
import AppHeader from "@/components/AppHeader.vue";
import ConfirmDialog from "@/components/ConfirmDialog.vue";
import { SidebarProvider, SidebarInset } from "@/components/ui/sidebar";
import { Toaster } from "@/components/ui/sonner";
</script>
