import frappe
from frappe.model.document import Document


class ConductorQueue(Document):
    def validate(self):
        if self.concurrency is not None and self.concurrency < 1:
            frappe.throw("Concurrency must be ≥ 1")
        if self.default_max_attempts is not None and self.default_max_attempts < 1:
            frappe.throw("default_max_attempts must be ≥ 1")
