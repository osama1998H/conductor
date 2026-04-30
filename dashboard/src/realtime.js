// Spec §8.6.1: per-doc events ride the doc:{Doctype}/{name} room. The
// page must call doc_subscribe to join the room AND on(event_name) to
// match the Socket.IO event-name label. Both are required.

function _rt() {
  if (!window.frappe?.realtime) {
    console.warn("frappe.realtime not available; running outside Desk?");
    return null;
  }
  return window.frappe.realtime;
}

export function subscribeDoc(doctype, docname, eventName, callback) {
  const rt = _rt();
  if (!rt) return () => {};
  rt.doc_subscribe(doctype, docname);
  rt.on(eventName, callback);
  return () => {
    rt.off(eventName, callback);
    rt.doc_unsubscribe(doctype, docname);
  };
}

// Generic event-only subscription (no doc room) — for site-wide events
// like "list_update". Use sparingly; prefer subscribeDoc for per-entity.
export function subscribe(eventName, callback) {
  const rt = _rt();
  if (!rt) return () => {};
  rt.on(eventName, callback);
  return () => rt.off(eventName, callback);
}
