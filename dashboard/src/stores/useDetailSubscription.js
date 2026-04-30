import { ref, onBeforeUnmount, watch } from "vue";
import { subscribeDoc } from "../realtime";

/**
 * Subscribe to per-entity realtime events for the open detail view.
 *
 *   const { data, refetch, unsubscribe } = useDetailSubscription(
 *     "Conductor Job",          // doctype — joins room doc:Conductor Job/{id}
 *     "conductor:job",          // event-name prefix; full event = `${prefix}:${id}`
 *     jobIdRef,
 *     () => api.getJob(jobIdRef.value),
 *   );
 *
 * `data` is reactive and reflects the most recent realtime delta merged
 * over the most recent full fetch. See spec §8.6.1 for why doctype is
 * required (event= alone broadcasts site-wide).
 */
export function useDetailSubscription(doctype, eventPrefix, idRef, fetcher) {
  const data = ref(null);
  let unsub = () => {};

  async function refetch() {
    if (!idRef.value) return;
    data.value = await fetcher();
  }

  function attach() {
    unsub();
    if (!idRef.value) {
      unsub = () => {};
      return;
    }
    const eventName = `${eventPrefix}:${idRef.value}`;
    unsub = subscribeDoc(doctype, idRef.value, eventName, (delta) => {
      if (data.value) data.value = { ...data.value, ...delta };
      // Re-fetch full record on terminal-state transitions to load traceback.
      if (["FAILED", "DLQ", "SUCCEEDED", "TIMED_OUT", "CANCELLED"].includes(delta?.status)) {
        refetch();
      }
    });
  }

  watch(idRef, async (newId, oldId) => {
    if (newId !== oldId) {
      data.value = null;
      attach();
      await refetch();
    }
  }, { immediate: true });

  onBeforeUnmount(() => unsub());

  return { data, refetch, unsubscribe: () => unsub() };
}
