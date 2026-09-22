"""Uvicorn also logs WebSocket handshake URLs; exclude bearer query values."""
import logging
import re

_TOKEN_QUERY = re.compile(r"(?i)([?&](?:token|access_token)=)[^&\s\"']+")


class RedactTokenQuery(logging.Filter):
    def filter(self, record):
        def redact(value):
            return _TOKEN_QUERY.sub(r"\1<redacted>", value) if isinstance(value, str) else value
        # Uvicorn's access formatter unpacks its five args; preserve their shape.
        record.msg = redact(record.msg)
        if isinstance(record.args, tuple):
            record.args = tuple(redact(value) for value in record.args)
        elif isinstance(record.args, dict):
            record.args = {key: redact(value) for key, value in record.args.items()}
        return True


def install_log_redaction():
    for name in ("uvicorn.error", "uvicorn.access"):
        logger = logging.getLogger(name)
        if not any(isinstance(f, RedactTokenQuery) for f in logger.filters):
            logger.addFilter(RedactTokenQuery())
