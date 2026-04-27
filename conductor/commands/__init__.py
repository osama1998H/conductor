"""Click command group exported to bench via hooks.py."""

import click

from conductor.commands.worker import worker_command


@click.group("conductor")
def conductor_group():
    """Conductor — reliability-first background jobs."""


conductor_group.add_command(worker_command)


commands = [conductor_group]
