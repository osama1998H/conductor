import { useColorMode as vueUseColorMode } from "@vueuse/core";

export function useColorMode() {
  return vueUseColorMode({
    selector: "html",
    attribute: "class",
    modes: { light: "light", dark: "dark" },
    storageKey: "conductor-color-mode",
    initialValue: "system",
  });
}
