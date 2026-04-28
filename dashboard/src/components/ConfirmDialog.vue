<template>
  <div v-if="state.open" class="confirm-backdrop" @click.self="onCancel">
    <div class="confirm-modal" :class="{ danger: state.danger }">
      <h3 v-if="state.title" class="title">{{ state.title }}</h3>
      <p class="message">{{ state.message }}</p>
      <div class="actions">
        <button class="btn-cancel" @click="onCancel">{{ state.cancelText }}</button>
        <button class="btn-ok" :class="{ danger: state.danger }" @click="onOk">
          {{ state.confirmText }}
        </button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { onMounted, onBeforeUnmount } from "vue";
import { useConfirmState, _resolve } from "../stores/useConfirm";

const state = useConfirmState();

function onOk() {
  _resolve(true);
}
function onCancel() {
  _resolve(false);
}

// Allow Esc and Enter shortcuts when dialog is open
function handleKey(e) {
  if (!state.value.open) return;
  if (e.key === "Escape") onCancel();
  if (e.key === "Enter") onOk();
}
onMounted(() => window.addEventListener("keydown", handleKey));
onBeforeUnmount(() => window.removeEventListener("keydown", handleKey));
</script>

<style scoped>
.confirm-backdrop {
  position: fixed;
  inset: 0;
  background: rgba(15, 23, 42, 0.45);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 200;
  animation: fade-in 0.12s ease;
}

.confirm-modal {
  background: #fff;
  border-radius: 8px;
  padding: 20px 24px 16px;
  min-width: 360px;
  max-width: 520px;
  box-shadow: 0 20px 48px rgba(15, 23, 42, 0.25);
  animation: pop-in 0.14s ease;
}

.title {
  margin: 0 0 8px;
  font-size: 15px;
  font-weight: 600;
  color: #0f172a;
}

.message {
  margin: 0 0 18px;
  font-size: 14px;
  color: #334155;
  line-height: 1.5;
}

.actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
}

.actions button {
  padding: 6px 16px;
  font-size: 13px;
  border-radius: 4px;
  cursor: pointer;
  font-weight: 500;
  border: 1px solid transparent;
  transition: background 0.12s, border-color 0.12s;
}

.btn-cancel {
  background: #fff;
  border-color: #cbd5e1;
  color: #475569;
}

.btn-cancel:hover {
  background: #f8fafc;
  border-color: #94a3b8;
}

.btn-ok {
  background: #2563eb;
  color: #fff;
  border-color: #2563eb;
}

.btn-ok:hover {
  background: #1d4ed8;
}

.btn-ok.danger {
  background: #dc2626;
  border-color: #dc2626;
}

.btn-ok.danger:hover {
  background: #b91c1c;
}

@keyframes fade-in {
  from {
    opacity: 0;
  }

  to {
    opacity: 1;
  }
}

@keyframes pop-in {
  from {
    opacity: 0;
    transform: scale(0.96);
  }

  to {
    opacity: 1;
    transform: scale(1);
  }
}
</style>
