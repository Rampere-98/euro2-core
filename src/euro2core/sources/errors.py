"""Errors a source raises when it cannot serve now but will later."""


class SourcePaused(Exception):
    """The source is temporarily unavailable (quota, maintenance). The job keeps its cursor and
    the scheduler retries later; no traceback is worth logging."""
