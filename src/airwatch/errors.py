"""Errors whose message is safe to log in full (#56).

Errors are reported by type: a message from someone else's code can quote a cell, a bucket key
or a URL. A `ReportableError`'s message is ours, built only from dates, our own paths, rule names
and counts, so a failure line may print it.
"""


class ReportableError(RuntimeError):
    """An error raised by our code, with a message that holds no data value."""
