<template>
  <div class="toast-host">
    <transition-group name="toast">
      <div v-for="t in toasts" :key="t.id" :class="['toast', `toast-${t.type}`]">
        {{ t.message }}
      </div>
    </transition-group>
  </div>
</template>

<script setup>
import { useToasts } from "../stores/useToast";
const toasts = useToasts();
</script>

<style scoped>
.toast-host {
  position: fixed;
  top: 16px;
  right: 16px;
  z-index: 300;
  display: flex;
  flex-direction: column;
  gap: 8px;
  pointer-events: none;
}

.toast {
  background: #fff;
  border: 1px solid #cbd5e1;
  border-left: 4px solid #2563eb;
  border-radius: 4px;
  padding: 10px 14px;
  font-size: 13px;
  color: #1e293b;
  box-shadow: 0 4px 12px rgba(15, 23, 42, 0.12);
  min-width: 240px;
  max-width: 420px;
  pointer-events: auto;
}

.toast-success {
  border-left-color: #16a34a;
}

.toast-error {
  border-left-color: #dc2626;
  background: #fef2f2;
  color: #991b1b;
}

.toast-warning {
  border-left-color: #ea580c;
}

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
