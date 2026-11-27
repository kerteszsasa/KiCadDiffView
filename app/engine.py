"""One queued worker, immutable source snapshots, persistent review results."""
from concurrent.futures import ThreadPoolExecutor
import fcntl
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import threading

from .components import extract_components, compare_components
from .rendering import Exporter
from .repositories import Repositories
from .remotes import ManagedRepos
from .storage import Store, now

VERSION = '0.1.0'
PIPELINE_VERSION = 'svg-components-4'


class Application:
    def __init__(self, roots, data):
        self.data = Path(data).resolve()
        self.data.mkdir(parents=True,exist_ok=True)
        self.data_lock = (self.data/'.application.lock').open('a+')
        try:
            fcntl.flock(self.data_lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError as error:
            self.data_lock.close()
            raise ValueError('This data directory is already in use by another instance.') from error
        self.repositories = Repositories(roots, self.data)
        self.store = Store(self.data)
        self.remotes = ManagedRepos(self.data, self.repositories.env)
        self.repositories.managed_roots = self._managed_roots
        self.closing = False
        self.worker = ThreadPoolExecutor(max_workers=1, thread_name_prefix='kicad-export')
        self.lock = threading.RLock()
        self.cli = shutil.which('kicad-cli')
        if self.cli:
            result = subprocess.run([self.cli, 'version'], env=self.repositories.env, capture_output=True, text=True)
            self.kicad_version = result.stdout.strip() if result.returncode == 0 else 'unavailable'
        else:
            self.kicad_version = 'unavailable'

    def _managed_roots(self):
        roots = []
        for row in self.store.remotes():
            if row['usable']:
                try:
                    path = self.remotes.path(row['id'])
                    if path.is_dir():
                        roots.append(path)
                except (ValueError, OSError):
                    continue
        return roots

    def source_metadata(self, value):
        path = Path(value).expanduser().resolve()
        for row in self.store.remotes():
            if path.is_relative_to(self.data/'repos'/row['id']):
                return {'remote_repo_id': row['id'], 'source_url': row['url']}
        return {}

    def _source_available(self, value):
        metadata = self.source_metadata(value)
        if metadata:
            row = self.store.remote(metadata['remote_repo_id'])
            if not row['usable'] or row['status'] in ('queued', 'running'):
                raise ValueError('The repository is being prepared. Try again when it finishes.')

    def _remote_jobs(self, identifier):
        return [job for job in self.store.jobs() if job['input'].get('remote_repo_id') == identifier]

    def _remote(self, identifier):
        self.identifier(identifier)
        row = self.store.remote(identifier)
        if row is None:
            raise FileNotFoundError('Downloaded repository not found.')
        return row

    def _artifact_path(self, group, identifier):
        self.identifier(identifier)
        parent = self.data/group
        if parent.resolve() != parent:
            raise ValueError("Artifact directory must not contain symlinks.")
        return parent/identifier

    @staticmethod
    def _disk_size(path):
        try:
            if path.is_symlink() or not path.exists():
                return 0
            if path.is_file():
                return path.stat().st_size
            return sum(Application._disk_size(item) for item in path.iterdir())
        except FileNotFoundError:
            # The worker may finish and remove temporary exports during a size scan.
            return 0

    def remote_record(self, identifier):
        row = self._remote(identifier)
        jobs = self._remote_jobs(identifier)
        size = self.remotes.size(identifier)
        artifacts = sum(self._disk_size(self._artifact_path(group, job['id']))
                        for job in jobs for group in ('results', 'work'))
        return {**row, 'size_bytes': size, 'comparison_count': len(jobs),
                'delete_bytes': size + artifacts,
                'busy': row['status'] in ('queued', 'running') or
                        any(job['status'] in ('queued', 'running') for job in jobs)}

    def import_remote(self, url):
        url = self.remotes.normalize_url(url)
        identifier = self.remotes.identifier(url)
        with self.lock:
            if self.closing:
                raise ValueError('The server is stopping.')
            row = self.store.remote(identifier)
            if row and (row['usable'] or row['status'] in ('queued', 'running')):
                return self.remote_record(identifier)
            stamp = now()
            row = row or {'id': identifier, 'url': url, 'path': str(self.remotes.path(identifier)),
                          'created': stamp, 'usable': False, 'last_refreshed': None}
            row.update(status='queued', progress='Waiting to clone', error=None, updated=stamp)
            self.store.save_remote(row)
            self.worker.submit(self._process_remote, identifier, False)
            return self.remote_record(identifier)

    def refresh_remote(self, identifier):
        with self.lock:
            row = self._remote(identifier)
            if self.closing:
                raise ValueError('The server is stopping.')
            if row['status'] in ('queued', 'running'):
                return self.remote_record(identifier)
            if any(job['status'] in ('queued', 'running') for job in self._remote_jobs(identifier)):
                raise ValueError('Wait for this repository’s queued or running comparison to finish.')
            if not row['usable']:
                return self.import_remote(row['url'])
            row.update(status='queued', progress='Waiting to refresh', error=None, updated=now())
            self.store.save_remote(row)
            self.worker.submit(self._process_remote, identifier, True)
            return self.remote_record(identifier)

    def _process_remote(self, identifier, refresh):
        with self.lock:
            row = self._remote(identifier)
            if self.closing:
                row.update(status='error', error='The server stopped before processing.', updated=now())
                self.store.save_remote(row)
                return
            row.update(status='running', progress='Refreshing repository' if refresh else 'Cloning repository', updated=now())
            self.store.save_remote(row)
        try:
            (self.remotes.refresh if refresh else self.remotes.clone)(row)
            with self.lock:
                row.update(status='ready', usable=True, error=None, progress='Repository ready',
                           updated=now(), last_refreshed=now())
                self.store.save_remote(row)
                self.store.remember(row['path'])
        except Exception as error:
            with self.lock:
                row.update(status='error', progress='Refresh failed' if refresh else 'Clone failed',
                           error=str(error), updated=now())
                self.store.save_remote(row)

    def delete_remote(self, identifier):
        with self.lock:
            row = self._remote(identifier)
            record = self.remote_record(identifier)
            if record['busy']:
                raise ValueError('Wait for the repository operation or comparison to finish before deleting it.')
            # Paths derive exclusively from IDs; local checkout origins are irrelevant.
            self.remotes.remove(identifier)
            for job in self._remote_jobs(identifier):
                self.delete(job['id'])
            self.store.forget(row['path'])
            self.store.delete_remote(identifier)

    @staticmethod
    def identifier(value):
        if not re.fullmatch(r'[a-f0-9]{24}', value):
            raise ValueError('Invalid comparison ID.')
        return value

    def job(self, identifier):
        self.identifier(identifier)
        record = self.store.job(identifier)
        if record is None:
            raise FileNotFoundError('Comparison not found.')
        if record['status'] == 'ready':
            manifest = self.data/'results'/identifier/'manifest.json'
            record['result'] = json.loads(manifest.read_text())
            if 'revisions' not in record['result']:
                record['result']['revisions'] = self._revision_details(record['result'])
        return record

    def _revision_details(self, payload):
        revisions = {}
        for side in ('base','head'):
            try:
                revisions[side] = self.repositories.commit(payload['repo'], payload[side])
            except (ValueError, OSError):
                # Saved graphics remain usable if their source is unavailable.
                continue
        return revisions

    def create(self, payload):
        with self.lock:
            return self._create(payload)

    def _create(self, payload):
        if self.closing:
            raise ValueError('The server is stopping.')
        self._source_available(payload.get("repo", ""))
        repo = str(self.repositories.repository(payload.get('repo', '')))
        project = self.repositories.project(payload.get('project', ''))
        base = self.repositories.resolve(repo, payload.get('base'))
        head = self.repositories.resolve(repo, payload.get('head'))
        if self.kicad_version == 'unavailable':
            raise ValueError('kicad-cli is unavailable. Install KiCad 9 or run the application in Docker.')
        resolved = {'repo': repo, 'project': project, 'base': base, 'head': head}
        resolved.update(self.source_metadata(repo))
        key = {**resolved, 'pipeline': PIPELINE_VERSION, 'kicad': self.kicad_version}
        identifier = hashlib.sha256(json.dumps(key, sort_keys=True).encode()).hexdigest()[:24]
        with self.lock:
            existing = self.store.job(identifier)
            if existing and existing['status'] in ('queued','running','ready'):
                return existing
            self.store.remember(repo)
            self.store.create(identifier, resolved)
            self.worker.submit(self.process, identifier, resolved)
        return self.store.job(identifier)

    def process(self, identifier, payload):
        work = self.data/'work'/identifier
        output = self.data/'results'/identifier
        def progress(message):
            self.store.update(identifier, 'running', message)
        try:
            progress('Preparing revisions')
            for path in (work, output):
                if path.is_symlink():
                    path.unlink()
                elif path.exists():
                    shutil.rmtree(path)
            snapshots = {side: work/side for side in ('before','after')}
            for side, ref in (('before',payload['base']),('after',payload['head'])):
                self.repositories.snapshot(payload['repo'], ref, snapshots[side])
            component_diffs = {}
            for kind in ('sch','pcb'):
                progress(f'Comparing components: {kind}')
                before = extract_components(snapshots['before'], payload['project'], kind)
                after = extract_components(snapshots['after'], payload['project'], kind)
                component_diffs[kind] = compare_components(before, after)
            # Component traversal validates every subsheet's containment and
            # hierarchy before KiCad is allowed to resolve any sheet paths.
            exporter = Exporter(self.repositories.env, progress, self.cli)
            files = exporter.export(snapshots, payload['project'], output)
            manifest = {'id': identifier, **payload, 'created': now(), 'version': VERSION, 'pipeline': PIPELINE_VERSION,
                        'kicad': self.kicad_version, 'files': files, 'components': component_diffs,
                        'revisions': self._revision_details(payload)}
            output.mkdir(parents=True, exist_ok=True)
            temporary = output/'manifest.json.tmp'
            temporary.write_text(json.dumps(manifest, ensure_ascii=False))
            temporary.replace(output/'manifest.json')
            shutil.rmtree(work)
            self.store.update(identifier, 'ready', 'Comparison ready')
        except Exception as error:
            self.store.update(identifier, 'error', 'Processing failed', str(error))

    def delete(self, identifier):
        self.identifier(identifier)
        with self.lock:
            record = self.store.job(identifier)
            if record is None:
                raise FileNotFoundError('Comparison not found.')
            if record['status'] in ('queued','running'):
                raise ValueError('A queued or running comparison cannot be deleted.')
            for group in ('results','work'):
                path = self._artifact_path(group, identifier)
                if path.is_symlink():
                    path.unlink()
                elif path.exists():
                    shutil.rmtree(path)
            self.store.delete(identifier)

    def asset(self, identifier, relative):
        self.identifier(identifier)
        root = (self.data/'results'/identifier).resolve()
        path = (root/relative).resolve()
        if not path.is_relative_to(root) or path.suffix.lower() not in ('.svg','.png') or not path.is_file():
            raise FileNotFoundError('Image not found.')
        return path

    def dispatch(self, method, path, query, body=None):
        with self.lock:
            return self._dispatch(method, path, query, body)

    def _dispatch(self, method, path, query, body=None):
        body = body or {}
        def arg(name, default=''):
            return query.get(name, [default])[0]
        if method == 'GET' and path == '/api/config':
            return {'roots': [str(p) for p in self.repositories.roots], 'version': VERSION,
                    'kicad': self.kicad_version}
        if method == 'GET' and path == '/api/browse':
            return self.repositories.browse(arg('path') or None)
        if path == '/api/remote-repos':
            if method == 'GET':
                return {'repos': [self.remote_record(row['id']) for row in self.store.remotes()]}
            if method == 'POST':
                return self.import_remote(body.get('url', ''))
        if path.startswith('/api/remote-repos/'):
            identifier = path.removeprefix('/api/remote-repos/')
            if method == 'POST' and identifier.endswith('/refresh'):
                return self.refresh_remote(identifier.removesuffix('/refresh'))
            if method == 'DELETE':
                self.delete_remote(identifier)
                return {'deleted': True}
        if path == '/api/repos':
            if method == 'GET':
                return {'repos': [{**row, **self.source_metadata(row['path'])} for row in self.store.repos()]}
            if method == 'POST':
                self._source_available(body.get('path',''))
                repo = self.repositories.repository(body.get('path',''))
                projects = self.repositories.projects(repo)
                self.store.remember(repo)
                return {'path': str(repo), 'projects': projects, **self.source_metadata(repo)}
        if method == 'GET' and path in ('/api/projects','/api/commits'):
            self._source_available(arg('repo'))
        if method == 'GET' and path == '/api/projects':
            return {'projects': self.repositories.projects(arg('repo'))}
        if method == 'GET' and path == '/api/commits':
            return self.repositories.commits(arg('repo'), arg('project'), arg('all') == '1', arg('q'), int(arg('offset','0')))
        if path == '/api/comparisons':
            if method == 'GET':
                return {'comparisons': self.store.jobs()}
            if method == 'POST':
                return self.create(body)
        if path.startswith('/api/comparisons/'):
            identifier = path.removeprefix('/api/comparisons/')
            if method == 'GET':
                return self.job(identifier)
            if method == 'DELETE':
                self.delete(identifier)
                return {'deleted': True}
        raise FileNotFoundError('API endpoint not found.')

    def close(self):
        with self.lock:
            self.closing = True
            self.remotes.close()
        self.worker.shutdown(wait=True)
        if not self.data_lock.closed:
            fcntl.flock(self.data_lock,fcntl.LOCK_UN)
            self.data_lock.close()
