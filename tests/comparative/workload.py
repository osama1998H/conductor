"""Shim that re-exports the KPI workload functions from `conductor.kpi_workload`.

The functions themselves live inside the `conductor` package so both
Conductor's `bench conductor worker` and the RQ launcher can import them
via the standard worker bootstrap path. This module exists so the harness
side keeps a stable `tests.comparative.workload.X` import surface.
"""

from conductor.kpi_workload import (  # noqa: F401
    COUNTER_KEY,
    always_fail,
    echo,
    get_counter,
    increment_only,
    reset_counter,
    slow_then_count,
    transient_failure,
)

WORKLOAD_MODULE = "conductor.kpi_workload"
