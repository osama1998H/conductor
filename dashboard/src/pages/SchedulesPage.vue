<template>
  <div class="schedules-page">
    <div class="master">
      <div class="filters">
        <input v-model="filters.q" placeholder="search name…" />
        <button @click="reload">Refresh</button>
      </div>
      <table class="schedule-list">
        <thead>
          <tr>
            <th>Name</th>
            <th>Cron</th>
            <th>TZ</th>
            <th>Enabled</th>
            <th>Next run</th>
            <th>Last status</th>
            <th>Actions</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in rows" :key="row.name" :class="{ active: row.name === name }">
            <td @click="open(row.name)" class="mono">{{ row.name }}</td>
            <td @click="open(row.name)" class="mono">{{ row.cron_expression }}</td>
            <td @click="open(row.name)">{{ row.timezone }}</td>
            <td>
              <input type="checkbox" :checked="!!row.enabled" :disabled="!isSysMgr" @change="onToggleEnabled(row)" />
            </td>
            <td @click="open(row.name)" class="ts">{{ row.next_run_at }}</td>
            <td @click="open(row.name)">
              <StatusBadge v-if="row.last_status" :status="row.last_status" />
            </td>
            <td>
              <button :disabled="!isOperator" @click="onRunNow(row.name)"
                title="Dispatches now; cron cadence is unaffected.">Run now</button>
            </td>
          </tr>
        </tbody>
      </table>
      <div v-if="!rows.length" class="empty">No schedules.</div>
    </div>

    <div class="detail" v-if="name">
      <div v-if="!schedule" class="empty">Loading…</div>
      <div v-else>
        <header>
          <h3>{{ schedule.name }}</h3>
          <code>{{ schedule.cron_expression }}</code>
          <span>· {{ schedule.timezone }}</span>
          <input type="checkbox" :checked="!!schedule.enabled" :disabled="!isSysMgr"
            @change="onToggleEnabled(schedule)" />
        </header>

        <section>
          <h4>Last dispatch</h4>
          <p v-if="schedule.last_status">
            <StatusBadge :status="schedule.last_status" /> at <span class="ts">{{ schedule.last_run_at }}</span>
          </p>
          <p v-else>(never dispatched)</p>
        </section>

        <section v-if="schedule.last_job">
          <h4>Last job</h4>
          <p>
            <router-link :to="`/jobs/${schedule.last_job}`">{{ schedule.last_job }}</router-link>
            <StatusBadge v-if="lastJobStatus" :status="lastJobStatus" />
          </p>
        </section>

        <section>
          <h4>Next 10 fires</h4>
          <ul class="fires">
            <li v-for="f in nextFires" :key="f" class="ts">{{ f }}</li>
          </ul>
        </section>

        <section>
          <h4>Calendar</h4>
          <MiniCalendar :fires="nextFires" />
        </section>

        <section>
          <h4>Recent runs (heuristic by method)</h4>
          <table class="runs">
            <thead>
              <tr>
                <th>Job ID</th>
                <th>Status</th>
                <th>Enqueued</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="r in recentRuns" :key="r.job_id">
                <td><router-link :to="`/jobs/${r.job_id}`" class="mono">{{ r.job_id.slice(0, 8) }}…</router-link></td>
                <td>
                  <StatusBadge :status="r.status" />
                </td>
                <td class="ts">{{ r.enqueued_at }}</td>
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
  if (!confirm(`Run ${n} now?`)) return;
  const newId = await api.scheduleRunNow(n);
  alert(`Dispatched as ${newId}`);
  reload();
  if (name.value === n) loadDetail(n);
}

async function onToggleEnabled(row) {
  const next = !row.enabled;
  await api.scheduleSetEnabled(row.name, next);
  reload();
  if (name.value === row.name) loadDetail(row.name);
}
</script>

<style scoped>
.schedules-page {
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

.filters input {
  padding: 4px 8px;
  border: 1px solid #ccc;
  border-radius: 4px;
  font-size: 13px;
}

.schedule-list {
  width: 100%;
  border-collapse: collapse;
  font-size: 12px;
}

.schedule-list th,
.schedule-list td {
  text-align: left;
  padding: 6px 8px;
  border-bottom: 1px solid #eee;
}

.schedule-list tbody tr.active {
  background: #e0e7ff;
}

.schedule-list tbody td:not(:first-child) {
  cursor: pointer;
}

.schedule-list button {
  padding: 3px 8px;
  background: #2563eb;
  color: white;
  border: 0;
  border-radius: 4px;
  font-size: 11px;
  cursor: pointer;
}

.schedule-list button:disabled {
  background: #cbd5e1;
  cursor: not-allowed;
}

.mono,
code {
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
  gap: 12px;
  align-items: center;
  margin-bottom: 16px;
  flex-wrap: wrap;
}

section {
  margin-top: 16px;
}

section h4 {
  margin-bottom: 8px;
}

.fires {
  list-style: none;
  padding: 0;
  margin: 0;
  font-size: 12px;
}

.fires li {
  padding: 2px 0;
}

.runs {
  width: 100%;
  border-collapse: collapse;
  font-size: 12px;
}

.runs th,
.runs td {
  text-align: left;
  padding: 4px 8px;
  border-bottom: 1px solid #eee;
}
</style>
