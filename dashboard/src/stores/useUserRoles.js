import { ref, computed } from "vue";
import { api } from "../api";

// Module-scoped singleton: one fetch per page load, shared across components.
// `roles` and `user` start empty; flag refs are reactive so v-if / :disabled
// bindings update once the API roundtrip lands.
const roles = ref([]);
const user = ref("");
let fetchPromise = null;

function fetchOnce() {
  if (fetchPromise) return fetchPromise;
  fetchPromise = api.getUserRoles().then(
    (r) => {
      roles.value = Array.isArray(r?.roles) ? r.roles : [];
      user.value = r?.user || "";
    },
    (e) => {
      console.warn("get_user_roles failed", e);
      roles.value = [];
      user.value = "";
    },
  );
  return fetchPromise;
}

export function useUserRoles() {
  fetchOnce();
  // The literal Administrator user is treated as full access regardless of
  // role assignments, mirroring Frappe's own permission semantics.
  const isAdministrator = computed(() => user.value === "Administrator");
  const isSysMgr = computed(
    () => isAdministrator.value || roles.value.includes("System Manager"),
  );
  const isOperator = computed(
    () => isSysMgr.value || roles.value.includes("Conductor Operator"),
  );
  return { user, roles, isAdministrator, isSysMgr, isOperator };
}
