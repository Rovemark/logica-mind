import os
import sqlite3
import tempfile

import pytest

from logica_mind.stores.sqlite import SQLiteStore


def test_close_releases_both_connections_and_the_native_file_handle():
    with tempfile.TemporaryDirectory(prefix="mind-close-") as directory:
        original = os.path.join(directory, "fixture.db")
        store = SQLiteStore(original)
        reader, writer = store._rconn, store._conn
        assert reader is not writer
        store.close()
        for connection in (reader, writer):
            with pytest.raises(sqlite3.ProgrammingError):
                connection.execute("SELECT 1")
        # Unix permits unlinking an open database; NTFS exposes that leak here.
        moved = os.path.join(directory, "moved.db")
        os.replace(original, moved)
        os.unlink(moved)
        store.close()  # lifecycle shutdown may be requested twice


def test_in_memory_shared_connection_is_closed_once_and_shutdown_is_idempotent():
    store = SQLiteStore(":memory:")
    assert store._rconn is store._conn
    store.close()
    store.close()
    with pytest.raises(sqlite3.ProgrammingError):
        store._conn.execute("SELECT 1")
