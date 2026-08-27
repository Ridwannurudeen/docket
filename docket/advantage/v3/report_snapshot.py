"""One process-pinned v3 report resolution shared by every public representation."""

from . import report as report_module

_report: dict | None = None
_report_error: Exception | None = None


def get_report() -> dict:
    global _report, _report_error
    if _report_error is not None:
        raise _report_error
    if _report is None:
        try:
            _report = report_module.report()
        except Exception as exc:
            _report_error = exc
            raise
    return _report


def _reset_for_testing() -> None:
    global _report, _report_error
    _report = None
    _report_error = None
