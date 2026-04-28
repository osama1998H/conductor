<template>
  <div class="dlq-page">
    <div class="master">
      <div class="filters">
        <select v-model="filters.status">
          <option value="">All statuses</option>
          <option value="PENDING_REVIEW">Pending review</option>
          <option value="RETRIED">Retried</option>
          <option value="DISCARDED">Discarded</option>
        </select>
        <input v-model="filters.queue" placeholder="queue" />
        <button @click="reload">Refresh</button>
      </div>

      <div v-if="selected.size > 0" class="bulk-bar">
        <span>{{ selected.size }} selected</span>
        <button @click="onRetry" :disabled="!isOperator">Retry</button>
        <button v-if="isSysMgr" @click="onDiscard">Discard</button>
        <button v-if="isSysMgr && selected.size === 1 && currentSafe" @click="onOpenEdit">Edit &amp; retry…</button>
        <button @click="clearSelection">Clear</button>
      </div>

      <table class="dlq-list">
        <thead>
          <tr>
            <th></th>
            <th>Queue</th>
            <th>Status</th>
            <th>Attempts</th>
            <th>Last error</th>
            <th>Moved at</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in rows" :key="row.name" :class="{ active: row.name === entry_name }">
            <td><input type="checkbox" :checked="selected.has(row.name)" @change="toggleSelect(row.name)" /></td>
            <td @click="open(row.name)">{{ row.queue }}</td>
            <td @click="open(row.name)">
              <StatusBadge :status="row.status" />
            </td>
            <td @click="open(row.name)">{{ row.attempts }}</td>
            <td @click="open(row.name)" class="mono">{{ row.last_error_type }}</td>
            <td @click="open(row.name)" class="ts">{{ row.moved_at }}</td>
          </tr>
        </tbody>
      </table>
      <div v-if="!rows.length" class="empty">No DLQ entries match.</div>
    </div>

    <div class="detail" v-if="entry_name">
      <div v-if="!detailEntry" class="empty">Loading…</div>
      <div v-else>
        <header>
          <StatusBadge :status="detailEntry.status" />
          <span>· queue {{ detailEntry.queue }}</span>
          <span>· attempts {{ detailEntry.attempts }}</span>
          <span class="ts">{{ detailEntry.moved_at }}</span>
        </header>

        <section>
          <h4>Last error</h4>
          <p class="error">{{ detailEntry.last_error_type }}: {{ detailEntry.last_error_message }}</p>
          <details v-if="detailEntry.last_traceback">
            <summary>Traceback</summary>
            <pre class="tb">{{ detailEntry.last_traceback }}</pre>
          </details>
        </section>

        <section>
          <h4>
            Original payload
            <span :class="['safety', detailEntry.is_json_safe ? 'safe' : 'unsafe']">
              {{ detailEntry.is_json_safe ? "JSON-safe ✓" : "non-JSON types — edit-and-retry not available" }}
            </span>
          </h4>
          <h5>args</h5>
          <JsonViewer :value="detailEntry.payload_decoded?.args" />
          <h5>kwargs</h5>
          <JsonViewer :value="detailEntry.payload_decoded?.kwargs" />
        </section>

        <section v-if="detailEntry.job">
          <h4>Linked job</h4>
          <router-link :to="`/jobs/${detailEntry.job}`">{{ detailEntry.job }}</router-link>
        </section>

        <section v-if="detailEntry.reviewed_by">
          <h4>Review</h4>
          <p>by <code>{{ detailEntry.reviewed_by }}</code> at <span class="ts">{{ detailEntry.reviewed_at }}</span></p>
          <p v-if="detailEntry.review_notes">{{ detailEntry.review_notes }}</p>
        </section>

        <div class="actions">
          <button @click="onRetrySingle" :disabled="!isOperator">Retry as-is</button>
          <button v-if="isSysMgr" @click="onDiscardSingle">Discard</button>
          <button v-if="isSysMgr && detailEntry.is_json_safe" @click="onOpenEditSingle">Edit &amp; retry…</button>
        </div>
      </div>
    </div>

    <EditAndRetryModal v-if="editing" :entryName="editing.name" :initialArgs="editing.args"
      :initialKwargs="editing.kwargs" @cancel="editing = null" @saved="onEditSaved" />
  </div>
</template>

<script setup>
import { ref, reactive, computed, watch, toRefs } from "vue";
import { useRouter } from "vue-router";
import { api, getList, userRoles } from "../api";
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

const roles = userRoles();
const isOperator = roles.includes("Conductor Operator") || roles.includes("System Manager");
const isSysMgr = roles.includes("System Manager");

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
  if (!confirm(`Retry ${names.length} entries?`)) return;
  await api.dlqRetry(names);
  clearSelection();
  reload();
  if (entry_name.value) detailEntry.value = await api.getDlqEntry(entry_name.value);
}

async function onDiscard() {
  const names = [...selected.value];
  if (!confirm(`Discard ${names.length} entries? This cannot be undone.`)) return;
  await api.dlqDiscard(names);
  clearSelection();
  reload();
}

async function onOpenEdit() {
  const [name] = selected.value;
  const entry = await api.getDlqEntry(name);
  if (!entry.is_json_safe) {
    alert("Payload is not JSON-safe; edit-and-retry not available.");
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
  if (!confirm(`Retry ${entry_name.value}?`)) return;
  await api.dlqRetry([entry_name.value]);
  reload();
  detailEntry.value = await api.getDlqEntry(entry_name.value);
}

async function onDiscardSingle() {
  if (!confirm(`Discard ${entry_name.value}? This cannot be undone.`)) return;
  await api.dlqDiscard([entry_name.value]);
  reload();
  router.push({ path: "/dlq" });
}

async function onOpenEditSingle() {
  if (!detailEntry.value?.is_json_safe) {
    alert("Payload is not JSON-safe; edit-and-retry not available.");
    return;
  }
  editing.value = {
    name: entry_name.value,
    args: detailEntry.value.payload_decoded?.args || [],
    kwargs: detailEntry.value.payload_decoded?.kwargs || {},
  };
}

async function onEditSaved(newId) {
  alert(`Re-enqueued as ${newId}`);
  editing.value = null;
  clearSelection();
  reload();
}
</script>

<style scoped>
.dlq-page {
  display: flex;
  gap: 16px;
  height: calc(100vh - 100px);
}

.master {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
}

.detail {
  flex: 1;
  min-width: 0;
  border-left: 1px solid #ddd;
  padding-left: 16px;
  overflow: auto;
}

.filters {
  display: flex;
  gap: 8px;
  margin-bottom: 12px;
}

.filters select,
.filters input {
  padding: 4px 8px;
  border: 1px solid #ccc;
  border-radius: 4px;
  font-size: 13px;
}

.bulk-bar {
  display: flex;
  gap: 8px;
  align-items: center;
  padding: 8px;
  background: #f1f5f9;
  border-radius: 4px;
  margin-bottom: 8px;
  font-size: 13px;
}

.bulk-bar button {
  padding: 4px 10px;
  background: #2563eb;
  color: white;
  border: 0;
  border-radius: 4px;
  cursor: pointer;
  font-size: 12px;
}

.bulk-bar button:disabled {
  background: #cbd5e1;
  cursor: not-allowed;
}

.dlq-list {
  width: 100%;
  border-collapse: collapse;
  font-size: 12px;
}

.dlq-list th,
.dlq-list td {
  text-align: left;
  padding: 6px 8px;
  border-bottom: 1px solid #eee;
}

.dlq-list tbody tr.active {
  background: #e0e7ff;
}

.dlq-list tbody td {
  cursor: pointer;
}

.mono {
  font-family: ui-monospace, SFMono-Regular, monospace;
}

.ts {
  font-size: 11px;
  color: #64748b;
}

.empty {
  color: #94a3b8;
  padding: 12px;
  text-align: center;
}

header {
  display: flex;
  gap: 8px;
  align-items: center;
  margin-bottom: 12px;
  flex-wrap: wrap;
}

.error {
  color: #991b1b;
}

.tb {
  font-family: ui-monospace, monospace;
  font-size: 11px;
  background: #fee;
  padding: 8px;
  border-radius: 4px;
  max-height: 400px;
  overflow: auto;
}

.safety {
  font-size: 11px;
  padding: 2px 6px;
  border-radius: 4px;
  margin-left: 8px;
}

.safety.safe {
  background: #dcfce7;
  color: #166534;
}

.safety.unsafe {
  background: #fef3c7;
  color: #854d0e;
}

section {
  margin-top: 16px;
}

section h4 {
  margin-bottom: 8px;
}

section h5 {
  margin: 8px 0 4px;
  font-size: 12px;
  color: #64748b;
}

.actions {
  margin-top: 16px;
  display: flex;
  gap: 8px;
}

.actions button {
  padding: 6px 14px;
  background: #2563eb;
  color: white;
  border: 0;
  border-radius: 4px;
  cursor: pointer;
}

.actions button:disabled {
  background: #cbd5e1;
  cursor: not-allowed;
}
</style>
