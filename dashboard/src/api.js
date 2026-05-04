const DASHBOARD_PREFIX = "conductor.api.dashboard";

function _csrfToken() {
  // Frappe injects the token via `<script>window.csrf_token = "{{ csrf_token }}"</script>`
  // in dashboard/index.html. During `vite dev` the literal stays unresolved, so we
  // guard against it. Returns null if no real token is available; Frappe accepts
  // GETs without a token, and POSTs will surface a 400 from the server (handled
  // upstream as a toast).
  const t = window.csrf_token;
  if (!t || t === "{{ csrf_token }}") return null;
  return t;
}

async function callMethod(method, params = {}, httpMethod = "GET") {
  const url = `/api/method/${method}`;
  const headers = {};
  const csrf = _csrfToken();
  if (csrf) headers["X-Frappe-CSRF-Token"] = csrf;
  const opts = { method: httpMethod, credentials: "include", headers };
  let finalUrl = url;
  if (httpMethod === "GET") {
    const qs = new URLSearchParams(params).toString();
    if (qs) finalUrl = `${url}?${qs}`;
  } else {
    opts.headers["Content-Type"] = "application/json";
    opts.body = JSON.stringify(params);
  }
  const res = await fetch(finalUrl, opts);
  if (!res.ok) throw new Error(`${method}: ${res.status}`);
  const data = await res.json();
  return data.message;  // Frappe wraps responses in {message: ...}
}

function dashCall(endpoint, params = {}, httpMethod = "GET") {
  return callMethod(`${DASHBOARD_PREFIX}.${endpoint}`, params, httpMethod);
}

export const api = {
  getState: () => dashCall("get_state"),
  getJob: (job_id) => dashCall("get_job", { job_id }),
  retryJob: (job_id) => dashCall("retry_job", { job_id }, "POST"),
  cancelJob: (job_id) => dashCall("cancel_job", { job_id }, "POST"),
  getDlqEntry: (name) => dashCall("get_dlq_entry", { name }),
  dlqRetry: (entry_names) => dashCall("dlq_retry", { entry_names }, "POST"),
  dlqDiscard: (entry_names) => dashCall("dlq_discard", { entry_names }, "POST"),
  dlqEditAndRetry: (name, args_json, kwargs_json) =>
    dashCall("dlq_edit_and_retry", { name, args_json, kwargs_json }, "POST"),
  scheduleRunNow: (name) => dashCall("schedule_run_now", { name }, "POST"),
  scheduleSetEnabled: (name, enabled) => dashCall("schedule_set_enabled", { name, enabled }, "POST"),
  getScheduleNextFires: (name, count = 10) =>
    dashCall("get_schedule_next_fires", { name, count }),
  getWorker: (worker_id) => dashCall("get_worker", { worker_id }),
  getUserRoles: () => dashCall("get_user_roles"),
};

export function getList(doctype, opts = {}) {
  const params = {
    doctype,
    fields: JSON.stringify(opts.fields || ["name"]),
    filters: JSON.stringify(opts.filters || {}),
    order_by: opts.order_by || "modified desc",
    limit_page_length: opts.limit || 50,
    limit_start: opts.start || 0,
  };
  return callMethod("frappe.client.get_list", params);
}

export function userRoles() {
  return window.frappe?.boot?.user?.roles || [];
}

export async function listWorkflows() {
  return await callMethod("conductor.api.workflows.list_workflows");
}

export async function listWorkflowRuns(opts = {}) {
  const params = { limit: opts.limit || 50 };
  if (opts.workflow) params.workflow = opts.workflow;
  if (opts.status) params.status = opts.status;
  if (opts.offset) params.offset = opts.offset;
  return await callMethod("conductor.api.workflows.list_runs", params);
}

export async function getWorkflowRun(run_id) {
  return await callMethod("conductor.api.workflows.get_run", { run_id });
}

export async function cancelWorkflowRun(run_id) {
  return await callMethod("conductor.api.workflows.cancel_run", { run_id }, "POST");
}
