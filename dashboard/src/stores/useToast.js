import { ref } from "vue";

// Singleton toast queue. ToastHost.vue (mounted in App.vue) renders all
// active toasts; each auto-dismisses after `timeout` ms.
const toasts = ref([]);
let nextId = 1;

export function toast(message, type = "info", timeout = 3500) {
  const id = nextId++;
  toasts.value.push({ id, message, type });
  setTimeout(() => {
    toasts.value = toasts.value.filter((t) => t.id !== id);
  }, timeout);
}

export function useToasts() {
  return toasts;
}
