import { computed } from "vue";
import { userRoles } from "../api";

export function useUserRoles() {
  const roles = userRoles();
  return {
    roles,
    isSysMgr: computed(() => roles.includes("System Manager")),
    isOperator: computed(() =>
      roles.includes("Conductor Operator") || roles.includes("System Manager")
    ),
  };
}
