<template>
  <div
    v-if="state.open"
    class="fixed inset-0 bg-slate-900/45 flex items-center justify-center z-[200] confirm-fade-in"
    @click.self="onCancel"
  >
    <div class="bg-white rounded-lg px-6 pt-5 pb-4 min-w-[360px] max-w-[520px]
                shadow-[0_20px_48px_rgba(15,23,42,0.25)] confirm-pop-in">
      <h3 v-if="state.title" class="m-0 mb-2 text-[15px] font-semibold text-slate-900">{{ state.title }}</h3>
      <p class="m-0 mb-4 text-sm text-slate-700 leading-relaxed">{{ state.message }}</p>
      <div class="flex justify-end gap-2">
        <button
          class="px-4 py-1.5 text-sm rounded font-medium bg-white border border-slate-300 text-slate-600
                 hover:bg-slate-50 hover:border-slate-400
                 transition-colors duration-100 cursor-pointer"
          @click="onCancel"
        >{{ state.cancelText }}</button>
        <button
          :class="[
            'px-4 py-1.5 text-sm rounded font-medium border text-white cursor-pointer',
            'transition-colors duration-100',
            state.danger
              ? 'bg-danger border-danger hover:bg-red-700'
              : 'bg-primary border-primary hover:bg-primary-hover',
          ]"
          @click="onOk"
        >
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

function handleKey(e) {
  if (!state.value.open) return;
  if (e.key === "Escape") onCancel();
  if (e.key === "Enter") onOk();
}
onMounted(() => window.addEventListener("keydown", handleKey));
onBeforeUnmount(() => window.removeEventListener("keydown", handleKey));
</script>

<style scoped>
.confirm-fade-in {
  animation: fade-in 0.12s ease;
}

.confirm-pop-in {
  animation: pop-in 0.14s ease;
}

@keyframes fade-in {
  from { opacity: 0; }
  to   { opacity: 1; }
}

@keyframes pop-in {
  from { opacity: 0; transform: scale(0.96); }
  to   { opacity: 1; transform: scale(1); }
}
</style>
