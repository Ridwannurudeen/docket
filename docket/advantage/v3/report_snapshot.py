"""One process-pinned v3 report shared by every public representation."""

from . import report as report_module

_report: dict | None = None


def get_report() -> dict:
    global _report
    if _report is None:
        _report = report_module.report()
    return _report


def _reset_for_testing() -> None:
    global _report
    _report = None
