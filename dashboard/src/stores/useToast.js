import { toast as sonner } from "vue-sonner";

const TYPE_TO_FN = {
  success: sonner.success,
  error: sonner.error,
  warning: sonner.warning,
  info: sonner,
};

export function toast(message, type = "info") {
  const fn = TYPE_TO_FN[type] || sonner;
  fn(message);
}
