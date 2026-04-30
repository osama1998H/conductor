<template>
  <div class="flex gap-4 h-[calc(100vh-100px)]">
    <div class="flex-1 min-w-0 flex flex-col gap-3">
      <DlqDataTable
        :rows="rows"
        :filters="filters"
        :selected="selected"
        :selected-id="entry_name || ''"
        @select="open"
        @toggle-select="toggleSelect"
        @refresh="reload"
        @filters-change="onFiltersChange"
      />

      <Card v-if="selected.size > 0" class="p-3">
        <div class="flex gap-2 items-center text-sm">
          <span>{{ selected.size }} selected</span>
          <Button size="sm" :disabled="!isOperator" @click="onRetry">Retry</Button>
          <Button v-if="isSysMgr" size="sm" variant="destructive" @click="onDiscard">Discard</Button>
          <Button v-if="isSysMgr && selected.size === 1 && currentSafe" size="sm" variant="outline" @click="onOpenEdit">
            Edit &amp; retry…
          </Button>
          <Button size="sm" variant="ghost" @click="clearSelection">Clear</Button>
        </div>
      </Card>
    </div>

    <div v-if="entry_name" class="flex-1 min-w-0 overflow-auto">
      <Card v-if="!detailEntry">
        <CardContent class="p-6 text-center text-muted-foreground">Loading…</CardContent>
      </Card>
      <Card v-else>
        <CardHeader class="flex flex-row items-center gap-2 flex-wrap">
          <StatusBadge :status="detailEntry.status" />
          <span class="text-xs text-muted-foreground">· queue {{ detailEntry.queue }}</span>
          <span class="text-xs text-muted-foreground">· attempts {{ detailEntry.attempts }}</span>
          <span class="text-2xs text-muted-foreground">{{ detailEntry.moved_at }}</span>
        </CardHeader>
        <CardContent class="space-y-4">
          <section>
            <h4 class="text-sm font-medium mb-2">Last error</h4>
            <p class="text-destructive text-sm">{{ detailEntry.last_error_type }}: {{ detailEntry.last_error_message }}</p>
            <details v-if="detailEntry.last_traceback">
              <summary class="cursor-pointer text-sm">Traceback</summary>
              <pre class="font-mono text-2xs bg-muted p-2 rounded max-h-96 overflow-auto mt-2">{{ detailEntry.last_traceback }}</pre>
            </details>
          </section>

          <section>
            <h4 class="text-sm font-medium mb-2 flex items-center gap-2">
              Original payload
              <Badge :variant="detailEntry.is_json_safe ? 'default' : 'secondary'">
                {{ detailEntry.is_json_safe ? "JSON-safe" : "non-JSON types" }}
              </Badge>
            </h4>
            <h5 class="text-2xs text-muted-foreground mt-2 mb-1">args</h5>
            <JsonViewer :value="detailEntry.payload_decoded?.args" />
            <h5 class="text-2xs text-muted-foreground mt-2 mb-1">kwargs</h5>
            <JsonViewer :value="detailEntry.payload_decoded?.kwargs" />
          </section>

          <section v-if="detailEntry.job">
            <h4 class="text-sm font-medium mb-2">Linked job</h4>
            <RouterLink :to="`/jobs/${detailEntry.job}`" class="text-primary hover:underline">{{ detailEntry.job }}</RouterLink>
          </section>

          <section v-if="detailEntry.reviewed_by">
            <h4 class="text-sm font-medium mb-2">Review</h4>
            <p class="text-sm">
              by <code class="font-mono">{{ detailEntry.reviewed_by }}</code> at
              <span class="text-2xs text-muted-foreground">{{ detailEntry.reviewed_at }}</span>
            </p>
            <p v-if="detailEntry.review_notes" class="text-sm">{{ detailEntry.review_notes }}</p>
          </section>

          <div class="flex gap-2">
            <Button :disabled="!isOperator" @click="onRetrySingle">Retry as-is</Button>
            <Button v-if="isSysMgr" variant="destructive" @click="onDiscardSingle">Discard</Button>
            <Button v-if="isSysMgr && detailEntry.is_json_safe" variant="outline" @click="onOpenEditSingle">
              Edit &amp; retry…
            </Button>
          </div>
        </CardContent>
      </Card>
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
import { useRouter, RouterLink } from "vue-router";
import { api, getList } from "@/api";
import { useUserRoles } from "@/stores/useUserRoles";
import { confirm } from "@/stores/useConfirm";
import { toast } from "@/stores/useToast";
import StatusBadge from "@/components/StatusBadge.vue";
import JsonViewer from "@/components/JsonViewer.vue";
import EditAndRetryModal from "@/components/EditAndRetryModal.vue";
import DlqDataTable from "@/components/DlqDataTable.vue";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";

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

function onFiltersChange(next) {
  Object.assign(filters, next);
}

watch(entry_name, async (id) => {
  detailEntry.value = null;
  if (!id) return;
  detailEntry.value = await api.getDlqEntry(id);
}, { immediate: true });

const currentSafe = computed(() => {
  if (selected.value.size !== 1) return false;
  const [name] = selected.value;
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
