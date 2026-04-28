const BASE = "/api/method/conductor.api.dashboard";

async function call(endpoint, params = {}, method = "GET") {
  const url = `${BASE}.${endpoint}`;
  const opts = {
    method,
    credentials: "include",
    headers: {
      "X-Frappe-CSRF-Token": window.frappe?.csrf_token || "token",
    },
  };
  let finalUrl = url;
  if (method === "GET") {
    const qs = new URLSearchParams(params).toString();
    if (qs) finalUrl = `${url}?${qs}`;
  } else {
    opts.headers["Content-Type"] = "application/json";
    opts.body = JSON.stringify(params);
  }
  const res = await fetch(finalUrl, opts);
  if (!res.ok) throw new Error(`${endpoint}: ${res.status}`);
  const data = await res.json();
  return data.message;  // Frappe wraps responses in {message: ...}
}

export const api = {
  getState:        () => call("get_state"),
  getJob:          (job_id) => call("get_job", { job_id }),
  retryJob:        (job_id) => call("retry_job", { job_id }, "POST"),
  cancelJob:       (job_id) => call("cancel_job", { job_id }, "POST"),
  getDlqEntry:     (name) => call("get_dlq_entry", { name }),
  dlqRetry:        (entry_names) => call("dlq_retry", { entry_names }, "POST"),
  dlqDiscard:      (entry_names) => call("dlq_discard", { entry_names }, "POST"),
  dlqEditAndRetry: (name, args_json, kwargs_json) =>
    call("dlq_edit_and_retry", { name, args_json, kwargs_json }, "POST"),
  scheduleRunNow:     (name) => call("schedule_run_now", { name }, "POST"),
  scheduleSetEnabled: (name, enabled) => call("schedule_set_enabled", { name, enabled }, "POST"),
  getScheduleNextFires: (name, count = 10) =>
    call("get_schedule_next_fires", { name, count }),
  getWorker: (worker_id) => call("get_worker", { worker_id }),
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
  return call("../frappe.client.get_list", params);
}

export function userRoles() {
  return window.frappe?.boot?.user?.roles || [];
}
