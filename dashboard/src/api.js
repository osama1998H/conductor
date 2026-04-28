const DASHBOARD_PREFIX = "conductor.api.dashboard";

async function callMethod(method, params = {}, httpMethod = "GET") {
  const url = `/api/method/${method}`;
  const opts = {
    method: httpMethod,
    credentials: "include",
    headers: {
      "X-Frappe-CSRF-Token": window.frappe?.csrf_token || "token",
    },
  };
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
