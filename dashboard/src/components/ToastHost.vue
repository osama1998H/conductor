<template>
  <div class="fixed top-4 right-4 z-[300] flex flex-col gap-2 pointer-events-none">
    <transition-group name="toast">
      <div
        v-for="t in toasts"
        :key="t.id"
        :class="[
          'bg-white border border-slate-300 border-l-4 rounded',
          'px-3.5 py-2.5 text-sm text-slate-800',
          'shadow-[0_4px_12px_rgba(15,23,42,0.12)]',
          'min-w-60 max-w-[420px] pointer-events-auto',
          toneClasses(t.type),
        ]"
      >
        {{ t.message }}
      </div>
    </transition-group>
  </div>
</template>

<script setup>
import { useToasts } from "../stores/useToast";
const toasts = useToasts();

function toneClasses(type) {
  switch (type) {
    case "success": return "border-l-green-600";
    case "error":   return "border-l-danger bg-red-50 text-red-800";
    case "warning": return "border-l-orange-600";
    default:        return "border-l-primary";
  }
}
</script>

<style scoped>
.toast-enter-active,
.toast-leave-active {
  transition: transform 0.16s ease, opacity 0.16s ease;
}

.toast-enter-from,
.toast-leave-to {
  opacity: 0;
  transform: translateX(20px);
}
</style>
