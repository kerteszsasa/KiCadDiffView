"""Durable local history and job states in the writable data mount."""
from contextlib import contextmanager
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3


def now():
    return datetime.now(timezone.utc).isoformat()


class Store:
    def __init__(self, data):
        self.data = Path(data).resolve()
        self.data.mkdir(parents=True, exist_ok=True)
        with self.connection() as db:
            db.execute('CREATE TABLE IF NOT EXISTS repos (path TEXT PRIMARY KEY, used TEXT NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS jobs (id TEXT PRIMARY KEY, payload TEXT NOT NULL, status TEXT NOT NULL, progress TEXT NOT NULL, error TEXT, created TEXT NOT NULL, updated TEXT NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS remotes (id TEXT PRIMARY KEY, url TEXT NOT NULL, path TEXT NOT NULL, status TEXT NOT NULL, progress TEXT NOT NULL, error TEXT, created TEXT NOT NULL, updated TEXT NOT NULL, last_refreshed TEXT, usable INTEGER NOT NULL DEFAULT 0)')
            db.execute("UPDATE remotes SET status='error', error='Repository operation was interrupted. Refresh to try again.', updated=? WHERE status IN ('queued','running')", (now(),))
            db.execute("UPDATE jobs SET status='error', error='Processing was interrupted. Run the comparison again.' WHERE status IN ('queued','running')")

    @contextmanager
    def connection(self):
        db = sqlite3.connect(self.data/'history.sqlite3', timeout=30)
        db.row_factory = sqlite3.Row
        try:
            yield db
            db.commit()
        finally:
            db.close()

    def remember(self, repo):
        with self.connection() as db:
            db.execute('INSERT OR REPLACE INTO repos VALUES (?,?)', (str(repo), now()))

    def repos(self):
        with self.connection() as db:
            return [dict(row) for row in db.execute('SELECT * FROM repos ORDER BY used DESC')]

    def jobs(self):
        with self.connection() as db:
            return [self.decode(row) for row in db.execute('SELECT * FROM jobs ORDER BY created DESC')]

    @staticmethod
    def decode(row):
        if row is None:
            return None
        record = dict(row)
        record['input'] = json.loads(record.pop('payload'))
        return record

    def job(self, identifier):
        with self.connection() as db:
            return self.decode(db.execute('SELECT * FROM jobs WHERE id=?', (identifier,)).fetchone())

    def create(self, identifier, payload):
        with self.connection() as db:
            stamp = now()
            db.execute('INSERT OR REPLACE INTO jobs VALUES (?,?,?,?,?,?,?)',
                       (identifier, json.dumps(payload), 'queued', 'Waiting', None, stamp, stamp))

    def update(self, identifier, status, progress='', error=None):
        with self.connection() as db:
            db.execute('UPDATE jobs SET status=?, progress=?, error=?, updated=? WHERE id=?',
                       (status, progress, error, now(), identifier))

    def delete(self, identifier):
        with self.connection() as db:
            db.execute('DELETE FROM jobs WHERE id=?', (identifier,))

    def forget(self, path):
        with self.connection() as db:
            db.execute('DELETE FROM repos WHERE path=?', (str(path),))

    @staticmethod
    def decode_remote(row):
        if row is None:
            return None
        record = dict(row)
        record['usable'] = bool(record['usable'])
        return record

    def remote(self, identifier):
        with self.connection() as db:
            return self.decode_remote(db.execute('SELECT * FROM remotes WHERE id=?', (identifier,)).fetchone())

    def remotes(self):
        with self.connection() as db:
            return [self.decode_remote(row) for row in db.execute('SELECT * FROM remotes ORDER BY created DESC, id')]

    def save_remote(self, record):
        fields = ('id', 'url', 'path', 'status', 'progress', 'error', 'created', 'updated', 'last_refreshed', 'usable')
        with self.connection() as db:
            db.execute('INSERT OR REPLACE INTO remotes VALUES (?,?,?,?,?,?,?,?,?,?)',
                       tuple(record.get(field, False if field == 'usable' else None) for field in fields))

    def delete_remote(self, identifier):
        with self.connection() as db:
            db.execute('DELETE FROM remotes WHERE id=?', (identifier,))
