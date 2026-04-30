__version__ = "1.0.0"

from conductor.api import RetryPolicy, cancel, context, enqueue, job  # noqa: E402,F401
from conductor.workflow import run_workflow, cancel_workflow_run  # noqa: E402,F401

__all__ = ["enqueue", "context", "job", "RetryPolicy", "cancel", "run_workflow", "cancel_workflow_run", "__version__"]


# Bootstrap the in-process frappe.enqueue patch when the bench flag is set.
# This must be the LAST statement at module load so all other conductor
# symbols are bound before any patched dispatch can run.
from conductor.frappe_compat import maybe_install_inprocess_patch as _bootstrap  # noqa: E402

_bootstrap()
