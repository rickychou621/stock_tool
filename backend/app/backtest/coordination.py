"""Acquire before accepting a job; hold the same connection until it finishes."""

from threading import Lock

from sqlalchemy import text

_local_lock = Lock()


class JobLease:
    def __init__(self, connection=None):
        self.connection = connection

    def close(self):
        if self.connection is not None:
            try:
                self.connection.execute(text("SELECT RELEASE_LOCK('stock_tool_backtest')"))
            finally:
                self.connection.close()
        else:
            _local_lock.release()


def acquire(session_factory):
    with session_factory() as db:
        bind = db.get_bind()
    if bind.dialect.name != "mysql":
        return JobLease() if _local_lock.acquire(blocking=False) else None
    connection = bind.connect()
    try:
        if connection.scalar(text("SELECT GET_LOCK('stock_tool_backtest', 0)")) == 1:
            return JobLease(connection)
    except Exception:
        connection.close()
        raise
    connection.close()
    return None
