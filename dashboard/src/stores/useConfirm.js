import { ref } from "vue";

// Singleton dialog state. Pages call confirm() and await a boolean.
// ConfirmDialog.vue (mounted once in App.vue) renders the modal and
// resolves the promise via _resolve() when the user picks an action.
const state = ref({ open: false });
let resolver = null;

export function confirm(message, opts = {}) {
  return new Promise((resolve) => {
    state.value = {
      open: true,
      message,
      title: opts.title || "Confirm",
      confirmText: opts.confirmText || "OK",
      cancelText: opts.cancelText || "Cancel",
      danger: !!opts.danger,
    };
    resolver = resolve;
  });
}

export function _resolve(value) {
  if (resolver) resolver(value);
  resolver = null;
  state.value = { open: false };
}

export function useConfirmState() {
  return state;
}
