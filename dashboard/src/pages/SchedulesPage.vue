<template>
  <div class="flex gap-4 h-[calc(100vh-100px)]">
    <div class="flex-1 min-w-0 flex flex-col">
      <div class="flex gap-2 mb-3">
        <input
          v-model="filters.q"
          placeholder="search name…"
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
      <table class="w-full border-collapse text-xs">
        <thead>
          <tr>
            <th class="text-left px-2 py-1.5 border-b border-slate-200">Name</th>
            <th class="text-left px-2 py-1.5 border-b border-slate-200">Cron</th>
            <th class="text-left px-2 py-1.5 border-b border-slate-200">TZ</th>
            <th class="text-left px-2 py-1.5 border-b border-slate-200">Enabled</th>
            <th class="text-left px-2 py-1.5 border-b border-slate-200">Next run</th>
            <th class="text-left px-2 py-1.5 border-b border-slate-200">Last status</th>
            <th class="text-left px-2 py-1.5 border-b border-slate-200">Actions</th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="row in rows"
            :key="row.name"
            :class="row.name === name && 'bg-indigo-100'"
          >
            <td class="px-2 py-1.5 border-b border-slate-200 cursor-pointer font-mono" @click="open(row.name)">{{ row.name }}</td>
            <td class="px-2 py-1.5 border-b border-slate-200 cursor-pointer font-mono" @click="open(row.name)">{{ row.cron_expression }}</td>
            <td class="px-2 py-1.5 border-b border-slate-200 cursor-pointer" @click="open(row.name)">{{ row.timezone }}</td>
            <td class="px-2 py-1.5 border-b border-slate-200">
              <input type="checkbox" :checked="!!row.enabled" :disabled="!isSysMgr" @change="onToggleEnabled(row)" />
            </td>
            <td class="px-2 py-1.5 border-b border-slate-200 cursor-pointer text-2xs text-slate-500" @click="open(row.name)">{{ row.next_run_at }}</td>
            <td class="px-2 py-1.5 border-b border-slate-200 cursor-pointer" @click="open(row.name)">
              <StatusBadge v-if="row.last_status" :status="row.last_status" />
            </td>
            <td class="px-2 py-1.5 border-b border-slate-200">
              <button
                :disabled="!isOperator"
                @click="onRunNow(row.name)"
                title="Dispatches now; cron cadence is unaffected."
                class="px-2 py-0.5 bg-primary text-white border-0 rounded text-2xs cursor-pointer
                       disabled:bg-slate-300 disabled:cursor-not-allowed"
              >Run now</button>
            </td>
          </tr>
        </tbody>
      </table>
      <div v-if="!rows.length" class="text-slate-400 p-3 text-center">No schedules.</div>
    </div>

    <div class="flex-1 min-w-0 border-l border-slate-300 pl-4 overflow-auto" v-if="name">
      <div v-if="!schedule" class="text-slate-400 p-3 text-center">Loading…</div>
      <div v-else>
        <header class="flex gap-3 items-center mb-4 flex-wrap">
          <h3>{{ schedule.name }}</h3>
          <code class="font-mono">{{ schedule.cron_expression }}</code>
          <span>· {{ schedule.timezone }}</span>
          <input type="checkbox" :checked="!!schedule.enabled" :disabled="!isSysMgr"
            @change="onToggleEnabled(schedule)" />
        </header>

        <section class="mt-4">
          <h4 class="mb-2">Last dispatch</h4>
          <p v-if="schedule.last_status">
            <StatusBadge :status="schedule.last_status" /> at <span class="text-2xs text-slate-500">{{ schedule.last_run_at }}</span>
          </p>
          <p v-else>(never dispatched)</p>
        </section>

        <section v-if="schedule.last_job" class="mt-4">
          <h4 class="mb-2">Last job</h4>
          <p>
            <router-link :to="`/jobs/${schedule.last_job}`">{{ schedule.last_job }}</router-link>
            <StatusBadge v-if="lastJobStatus" :status="lastJobStatus" />
          </p>
        </section>

        <section class="mt-4">
          <h4 class="mb-2">Next 10 fires</h4>
          <ul class="list-none p-0 m-0 text-xs">
            <li v-for="f in nextFires" :key="f" class="py-0.5 text-2xs text-slate-500">{{ f }}</li>
          </ul>
        </section>

        <section class="mt-4">
          <h4 class="mb-2">Calendar</h4>
          <MiniCalendar :fires="nextFires" />
        </section>

        <section class="mt-4">
          <h4 class="mb-2">Recent runs (heuristic by method)</h4>
          <table class="w-full border-collapse text-xs">
            <thead>
              <tr>
                <th class="text-left px-2 py-1 border-b border-slate-200">Job ID</th>
                <th class="text-left px-2 py-1 border-b border-slate-200">Status</th>
                <th class="text-left px-2 py-1 border-b border-slate-200">Enqueued</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="r in recentRuns" :key="r.job_id">
                <td class="px-2 py-1 border-b border-slate-200">
                  <router-link :to="`/jobs/${r.job_id}`" class="font-mono">{{ r.job_id.slice(0, 8) }}…</router-link>
                </td>
                <td class="px-2 py-1 border-b border-slate-200">
                  <StatusBadge :status="r.status" />
                </td>
                <td class="px-2 py-1 border-b border-slate-200 text-2xs text-slate-500">{{ r.enqueued_at }}</td>
              </tr>
            </tbody>
          </table>
        </section>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, reactive, watch, toRefs } from "vue";
import { useRouter } from "vue-router";
import { api, getList } from "../api";
import { useUserRoles } from "../stores/useUserRoles";
import { confirm } from "../stores/useConfirm";
import { toast } from "../stores/useToast";
import StatusBadge from "../components/StatusBadge.vue";
import MiniCalendar from "../components/MiniCalendar.vue";

const props = defineProps({ name: String });
const router = useRouter();
const { name } = toRefs(props);

const filters = reactive({ q: "" });
const rows = ref([]);
const schedule = ref(null);
const nextFires = ref([]);
const recentRuns = ref([]);
const lastJobStatus = ref("");

const { isOperator, isSysMgr } = useUserRoles();

async function reload() {
  const f = {};
  if (filters.q) f.name = ["like", `%${filters.q}%`];
  rows.value = await getList("Conductor Schedule", {
    fields: ["name", "cron_expression", "timezone", "enabled", "next_run_at", "last_status", "last_run_at", "method", "last_job"],
    filters: f,
    order_by: "name asc",
    limit: 100,
  });
}

watch(filters, reload, { deep: true, immediate: true });

function open(n) { router.push({ path: `/schedules/${n}` }); }

async function loadDetail(n) {
  if (!n) { schedule.value = null; return; }
  const list = await getList("Conductor Schedule", {
    fields: ["name", "cron_expression", "timezone", "method", "queue", "enabled",
      "next_run_at", "last_status", "last_run_at", "last_job"],
    filters: { name: n },
    limit: 1,
  });
  schedule.value = list[0] || null;
  if (!schedule.value) return;

  const [fires, runs] = await Promise.all([
    api.getScheduleNextFires(n, 10),
    schedule.value.method ? getList("Conductor Job", {
      fields: ["job_id", "status", "enqueued_at"],
      filters: { method: schedule.value.method },
      order_by: "enqueued_at desc",
      limit: 20,
    }) : [],
  ]);
  nextFires.value = fires || [];
  recentRuns.value = runs || [];

  if (schedule.value.last_job) {
    try {
      const j = await api.getJob(schedule.value.last_job);
      lastJobStatus.value = j.status;
    } catch {
      lastJobStatus.value = "";
    }
  } else {
    lastJobStatus.value = "";
  }
}

watch(name, loadDetail, { immediate: true });

async function onRunNow(n) {
  if (!(await confirm(`Run schedule "${n}" now? This dispatches immediately and does not affect the cron cadence.`,
                       { title: "Run schedule now", confirmText: "Dispatch" }))) return;
  try {
    const newId = await api.scheduleRunNow(n);
    toast(`Dispatched as ${newId.slice(0, 8)}…`, "success");
    reload();
    if (name.value === n) loadDetail(n);
  } catch (e) {
    toast(`Run-now failed: ${e.message}`, "error");
  }
}

async function onToggleEnabled(row) {
  const next = !row.enabled;
  await api.scheduleSetEnabled(row.name, next);
  reload();
  if (name.value === row.name) loadDetail(row.name);
}
</script>
