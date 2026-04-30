import { ref, onMounted, onBeforeUnmount } from "vue";
import { api } from "../api";

let _instance = null;

export function useDashboardState() {
  if (_instance) return _instance;

  const state = ref(null);
  const error = ref(null);
  let timer = null;
  let refCount = 0;

  async function tick() {
    try {
      const snapshot = await api.getState();
      state.value = snapshot;
      error.value = null;
      const nextMs = snapshot.config?.poll_interval_ms || 2000;
      timer = setTimeout(tick, nextMs);
    } catch (e) {
      error.value = e;
      timer = setTimeout(tick, 5000); // backoff on error
    }
  }

  function start() {
    refCount += 1;
    if (refCount === 1) tick();
  }

  function stop() {
    refCount = Math.max(0, refCount - 1);
    if (refCount === 0 && timer) {
      clearTimeout(timer);
      timer = null;
    }
  }

  _instance = { state, error, start, stop };
  return _instance;
}

export function useAutoPolling() {
  const store = useDashboardState();
  onMounted(store.start);
  onBeforeUnmount(store.stop);
  return store;
}
