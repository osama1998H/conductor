<template>
  <div class="flex gap-4 h-[calc(100vh-100px)]">
    <div class="flex-1 min-w-0 flex flex-col">
      <div class="flex gap-2 mb-3">
        <select
          v-model="filters.status"
          class="px-2 py-1 border border-slate-300 rounded text-sm"
        >
          <option value="">All statuses</option>
          <option value="PENDING_REVIEW">Pending review</option>
          <option value="RETRIED">Retried</option>
          <option value="DISCARDED">Discarded</option>
        </select>
        <input
          v-model="filters.queue"
          placeholder="queue"
          class="px-2 py-1 border border-slate-300 rounded text-sm"
        />
        <button
          @click="reload"
          class="px-3 py-1 text-sm bg-white text-slate-800 border border-slate-300 rounded
                 hover:border-primary hover:bg-slate-50 active:bg-blue-50
                 disabled:opacity-50 disabled:cursor-not-allowed
                 transition-colors duration-150 cursor-pointer"
        >Refresh</button>
      </div>

      <div v-if="selected.size > 0" class="flex gap-2 items-center p-2 bg-slate-100 rounded mb-2 text-sm">
        <span>{{ selected.size }} selected</span>
        <button
          @click="onRetry"
          :disabled="!isOperator"
          class="px-2.5 py-1 bg-primary text-white border-0 rounded cursor-pointer text-xs
                 disabled:bg-slate-300 disabled:cursor-not-allowed"
        >Retry</button>
        <button
          v-if="isSysMgr"
          @click="onDiscard"
          class="px-2.5 py-1 bg-primary text-white border-0 rounded cursor-pointer text-xs"
        >Discard</button>
        <button
          v-if="isSysMgr && selected.size === 1 && currentSafe"
          @click="onOpenEdit"
          class="px-2.5 py-1 bg-primary text-white border-0 rounded cursor-pointer text-xs"
        >Edit &amp; retry…</button>
        <button
          @click="clearSelection"
          class="px-2.5 py-1 bg-primary text-white border-0 rounded cursor-pointer text-xs"
        >Clear</button>
      </div>

      <table class="w-full border-collapse text-xs">
        <thead>
          <tr>
            <th class="text-left px-2 py-1.5 border-b border-slate-200"></th>
            <th class="text-left px-2 py-1.5 border-b border-slate-200">Queue</th>
            <th class="text-left px-2 py-1.5 border-b border-slate-200">Status</th>
            <th class="text-left px-2 py-1.5 border-b border-slate-200">Attempts</th>
            <th class="text-left px-2 py-1.5 border-b border-slate-200">Last error</th>
            <th class="text-left px-2 py-1.5 border-b border-slate-200">Moved at</th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="row in rows"
            :key="row.name"
            :class="row.name === entry_name && 'bg-indigo-100'"
          >
            <td class="px-2 py-1.5 border-b border-slate-200">
              <input type="checkbox" :checked="selected.has(row.name)" @change="toggleSelect(row.name)" />
            </td>
            <td class="px-2 py-1.5 border-b border-slate-200 cursor-pointer" @click="open(row.name)">{{ row.queue }}</td>
            <td class="px-2 py-1.5 border-b border-slate-200 cursor-pointer" @click="open(row.name)">
              <StatusBadge :status="row.status" />
            </td>
            <td class="px-2 py-1.5 border-b border-slate-200 cursor-pointer" @click="open(row.name)">{{ row.attempts }}</td>
            <td class="px-2 py-1.5 border-b border-slate-200 cursor-pointer font-mono" @click="open(row.name)">{{ row.last_error_type }}</td>
            <td class="px-2 py-1.5 border-b border-slate-200 cursor-pointer text-2xs text-slate-500" @click="open(row.name)">{{ row.moved_at }}</td>
          </tr>
        </tbody>
      </table>
      <div v-if="!rows.length" class="text-slate-400 p-3 text-center">No DLQ entries match.</div>
    </div>

    <div class="flex-1 min-w-0 border-l border-slate-300 pl-4 overflow-auto" v-if="entry_name">
      <div v-if="!detailEntry" class="text-slate-400 p-3 text-center">Loading…</div>
      <div v-else>
        <header class="flex gap-2 items-center mb-3 flex-wrap">
          <StatusBadge :status="detailEntry.status" />
          <span>· queue {{ detailEntry.queue }}</span>
          <span>· attempts {{ detailEntry.attempts }}</span>
          <span class="text-2xs text-slate-500">{{ detailEntry.moved_at }}</span>
        </header>

        <section class="mt-4">
          <h4 class="mb-2">Last error</h4>
          <p class="text-red-800">{{ detailEntry.last_error_type }}: {{ detailEntry.last_error_message }}</p>
          <details v-if="detailEntry.last_traceback">
            <summary>Traceback</summary>
            <pre class="font-mono text-2xs bg-red-50 p-2 rounded max-h-96 overflow-auto">{{ detailEntry.last_traceback }}</pre>
          </details>
        </section>

        <section class="mt-4">
          <h4 class="mb-2">
            Original payload
            <span
              :class="[
                'text-2xs px-1.5 py-0.5 rounded ml-2',
                detailEntry.is_json_safe ? 'bg-green-100 text-green-800' : 'bg-amber-100 text-amber-800',
              ]"
            >
              {{ detailEntry.is_json_safe ? "JSON-safe ✓" : "non-JSON types — edit-and-retry not available" }}
            </span>
          </h4>
          <h5 class="my-2 mb-1 text-xs text-slate-500">args</h5>
          <JsonViewer :value="detailEntry.payload_decoded?.args" />
          <h5 class="my-2 mb-1 text-xs text-slate-500">kwargs</h5>
          <JsonViewer :value="detailEntry.payload_decoded?.kwargs" />
        </section>

        <section v-if="detailEntry.job" class="mt-4">
          <h4 class="mb-2">Linked job</h4>
          <router-link :to="`/jobs/${detailEntry.job}`">{{ detailEntry.job }}</router-link>
        </section>

        <section v-if="detailEntry.reviewed_by" class="mt-4">
          <h4 class="mb-2">Review</h4>
          <p>by <code class="font-mono">{{ detailEntry.reviewed_by }}</code> at <span class="text-2xs text-slate-500">{{ detailEntry.reviewed_at }}</span></p>
          <p v-if="detailEntry.review_notes">{{ detailEntry.review_notes }}</p>
        </section>

        <div class="mt-4 flex gap-2">
          <button
            @click="onRetrySingle"
            :disabled="!isOperator"
            class="px-3.5 py-1.5 bg-primary text-white border-0 rounded cursor-pointer
                   disabled:bg-slate-300 disabled:cursor-not-allowed"
          >Retry as-is</button>
          <button
            v-if="isSysMgr"
            @click="onDiscardSingle"
            class="px-3.5 py-1.5 bg-primary text-white border-0 rounded cursor-pointer"
          >Discard</button>
          <button
            v-if="isSysMgr && detailEntry.is_json_safe"
            @click="onOpenEditSingle"
            class="px-3.5 py-1.5 bg-primary text-white border-0 rounded cursor-pointer"
          >Edit &amp; retry…</button>
        </div>
      </div>
    </div>

    <EditAndRetryModal
      v-if="editing"
      :entryName="editing.name"
      :initialArgs="editing.args"
      :initialKwargs="editing.kwargs"
      @cancel="editing = null"
      @saved="onEditSaved"
    />
  </div>
</template>

<script setup>
import { ref, reactive, computed, watch, toRefs } from "vue";
import { useRouter } from "vue-router";
import { api, getList } from "../api";
import { useUserRoles } from "../stores/useUserRoles";
import { confirm } from "../stores/useConfirm";
import { toast } from "../stores/useToast";
import StatusBadge from "../components/StatusBadge.vue";
import JsonViewer from "../components/JsonViewer.vue";
import EditAndRetryModal from "../components/EditAndRetryModal.vue";

const props = defineProps({ entry_name: String });
const router = useRouter();
const { entry_name } = toRefs(props);

const filters = reactive({ status: "PENDING_REVIEW", queue: "" });
const rows = ref([]);
const selected = ref(new Set());
const detailEntry = ref(null);
const editing = ref(null);

const { isOperator, isSysMgr } = useUserRoles();

async function reload() {
  const f = {};
  if (filters.status) f.status = filters.status;
  if (filters.queue) f.queue = filters.queue;
  rows.value = await getList("Conductor DLQ Entry", {
    fields: ["name", "queue", "status", "attempts", "last_error_type", "last_error_message", "moved_at"],
    filters: f,
    order_by: "moved_at desc",
    limit: 50,
  });
}

watch(filters, reload, { deep: true, immediate: true });

function open(name) { router.push({ path: `/dlq/${name}` }); }

function toggleSelect(name) {
  const next = new Set(selected.value);
  if (next.has(name)) next.delete(name);
  else next.add(name);
  selected.value = next;
}

function clearSelection() { selected.value = new Set(); }

watch(entry_name, async (id) => {
  detailEntry.value = null;
  if (!id) return;
  detailEntry.value = await api.getDlqEntry(id);
}, { immediate: true });

const currentSafe = computed(() => {
  if (selected.value.size !== 1) return false;
  const [name] = selected.value;
  // Require the detail pane to be loaded for the selected entry — be conservative.
  if (detailEntry.value && detailEntry.value.name === name) return detailEntry.value.is_json_safe;
  return false;
});

async function onRetry() {
  const names = [...selected.value];
  if (!(await confirm(`Retry ${names.length} ${names.length === 1 ? "entry" : "entries"} as-is?`,
                       { title: "Retry DLQ entries", confirmText: "Retry" }))) return;
  try {
    await api.dlqRetry(names);
    toast(`${names.length} ${names.length === 1 ? "entry" : "entries"} retried`, "success");
  } catch (e) {
    toast(`Retry failed: ${e.message}`, "error");
    return;
  }
  clearSelection();
  reload();
  if (entry_name.value) detailEntry.value = await api.getDlqEntry(entry_name.value);
}

async function onDiscard() {
  const names = [...selected.value];
  if (!(await confirm(`Discard ${names.length} ${names.length === 1 ? "entry" : "entries"}? This cannot be undone.`,
                       { title: "Discard DLQ entries", confirmText: "Discard", danger: true }))) return;
  try {
    await api.dlqDiscard(names);
    toast(`${names.length} ${names.length === 1 ? "entry" : "entries"} discarded`, "success");
  } catch (e) {
    toast(`Discard failed: ${e.message}`, "error");
    return;
  }
  clearSelection();
  reload();
}

async function onOpenEdit() {
  const [name] = selected.value;
  const entry = await api.getDlqEntry(name);
  if (!entry.is_json_safe) {
    toast("Payload is not JSON-safe; edit-and-retry not available.", "warning");
    return;
  }
  editing.value = {
    name,
    args: entry.payload_decoded?.args || [],
    kwargs: entry.payload_decoded?.kwargs || {},
  };
}

// Single-entry actions from the detail pane

async function onRetrySingle() {
  if (!(await confirm(`Retry this entry as-is?`,
                       { title: "Retry DLQ entry", confirmText: "Retry" }))) return;
  try {
    await api.dlqRetry([entry_name.value]);
    toast("Entry retried", "success");
  } catch (e) {
    toast(`Retry failed: ${e.message}`, "error");
    return;
  }
  reload();
  detailEntry.value = await api.getDlqEntry(entry_name.value);
}

async function onDiscardSingle() {
  if (!(await confirm(`Discard this entry? This cannot be undone.`,
                       { title: "Discard DLQ entry", confirmText: "Discard", danger: true }))) return;
  try {
    await api.dlqDiscard([entry_name.value]);
    toast("Entry discarded", "success");
  } catch (e) {
    toast(`Discard failed: ${e.message}`, "error");
    return;
  }
  reload();
  router.push({ path: "/dlq" });
}

async function onOpenEditSingle() {
  if (!detailEntry.value?.is_json_safe) {
    toast("Payload is not JSON-safe; edit-and-retry not available.", "warning");
    return;
  }
  editing.value = {
    name: entry_name.value,
    args: detailEntry.value.payload_decoded?.args || [],
    kwargs: detailEntry.value.payload_decoded?.kwargs || {},
  };
}

async function onEditSaved(newId) {
  toast(`Re-enqueued as ${String(newId).slice(0, 8)}…`, "success");
  editing.value = null;
  clearSelection();
  reload();
}
</script>
