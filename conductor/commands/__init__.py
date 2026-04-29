"""Click command group exported to bench via hooks.py."""

import click

from conductor.commands.cancel import cancel_command
from conductor.commands.depth import depth_command
from conductor.commands.dlq import dlq_group
from conductor.commands.doctor import doctor_command
from conductor.commands.schedule import schedule_group
from conductor.commands.scheduler import scheduler_command
from conductor.commands.worker import worker_command
from conductor.commands.workflow import workflow_group


@click.group("conductor")
def conductor_group():
    """Conductor — reliability-first background jobs."""


conductor_group.add_command(worker_command)
conductor_group.add_command(doctor_command)
conductor_group.add_command(cancel_command)
conductor_group.add_command(scheduler_command)
conductor_group.add_command(schedule_group)
conductor_group.add_command(workflow_group)
conductor_group.add_command(depth_command)
conductor_group.add_command(dlq_group)


commands = [conductor_group]
