"""Read-only source access; revision archives are written only below data."""
from pathlib import Path, PurePosixPath
import os
import subprocess
import tarfile


COMMIT_FORMAT = '%H%x00%aI%x00%an%x00%s%x00%B'


def _decode_commits(raw):
    # NUL separates fields and records without splitting multiline messages.
    fields = raw.decode('utf-8', 'replace').split('\0')
    result = []
    for index in range(0, len(fields)-4, 5):
        commit = dict(zip(('sha', 'date', 'author', 'subject', 'message'), fields[index:index+5]))
        commit['message'] = commit['message'].rstrip('\n')
        result.append(commit)
    return result


class Repositories:
    def __init__(self, roots, data):
        self.roots = [Path(root).expanduser().resolve() for root in roots]
        self.data = Path(data).resolve()
        self.managed_roots = lambda: []
        for directory in ('tmp', 'home', 'config', 'cache'):
            (self.data/directory).mkdir(parents=True, exist_ok=True)
        self.env = {**os.environ, 'HOME': str(self.data/'home'),
                    'TMPDIR': str(self.data/'tmp'), 'XDG_CONFIG_HOME': str(self.data/'config'),
                    'XDG_CACHE_HOME': str(self.data/'cache'), 'GIT_OPTIONAL_LOCKS': '0',
                    'GIT_CONFIG_GLOBAL': '/dev/null', 'GIT_CONFIG_NOSYSTEM': '1',
                    'LC_ALL': 'C.UTF-8'}

    def allowed(self, value):
        candidate = Path(os.path.abspath(Path(value).expanduser()))
        path = candidate.resolve()
        if candidate.is_relative_to(self.data) and not path.is_relative_to(self.data):
            raise ValueError('Managed repository paths must remain inside the data directory.')
        if path.is_relative_to(self.data):
            if any(path.is_relative_to(root) for root in self.managed_roots()):
                return path
            raise ValueError('The data directory cannot be used as a source.')
        if not any(path.is_relative_to(root) for root in self.roots):
            raise ValueError('The directory is outside the allowed repository roots.')
        return path

    def git(self, repo, *args):
        repo = self.allowed(repo)
        command = ['git', '--no-optional-locks', '-c', f'safe.directory={repo}', '-C', str(repo), *args]
        result = subprocess.run(command, env=self.env, capture_output=True)
        if result.returncode:
            raise ValueError(result.stderr.decode('utf-8', 'replace').strip() or 'Git error')
        return result.stdout

    def repository(self, value):
        path = self.allowed(value)
        root = self.git(path, 'rev-parse', '--show-toplevel').decode().strip()
        return self.allowed(root)

    @staticmethod
    def project(value):
        path = PurePosixPath(value)
        if path.is_absolute() or '..' in path.parts or path.suffix != '.kicad_pro':
            raise ValueError('The project must be a .kicad_pro path inside the repository.')
        return path.as_posix()

    def browse(self, value=None):
        path = self.allowed(value or self.roots[0])
        if not path.is_dir():
            raise ValueError('Directory not found.')
        directories = []
        for item in sorted(path.iterdir(), key=lambda p: p.name.casefold()):
            if item.name.startswith('.'):
                continue
            try:
                resolved = self.allowed(item)
                if resolved.is_dir():
                    directories.append({'name': item.name, 'path': str(resolved),
                                        'is_repo': (resolved/'.git').exists()})
            except (ValueError, OSError):
                continue
        parent = str(path.parent) if any(path.parent.is_relative_to(r) for r in self.roots) else None
        try:
            repo = str(self.repository(path))
        except ValueError:
            repo = None
        return {'path': str(path), 'parent': parent, 'directories': directories, 'repo': repo}

    def projects(self, value):
        repo = self.repository(value)
        names = self.git(repo, 'ls-files', '-z', '--', '*.kicad_pro').decode().split('\0')
        return [{'path': name, 'name': Path(name).stem} for name in names
                if name and not any('backup' in part.lower() for part in Path(name).parts)]

    def resolve(self, repo, ref):
        if not isinstance(ref, str) or not ref.strip():
            raise ValueError('Two commits are required.')
        return self.git(repo, 'rev-parse', '--verify', '--end-of-options', ref.strip()+'^{commit}').decode().strip()

    def commit(self, value, ref):
        repo = self.repository(value)
        sha = self.resolve(repo, ref)
        return _decode_commits(self.git(repo, 'show', '-s', '-z', '--format='+COMMIT_FORMAT, sha))[0]

    def commits(self, value, project, all_commits=False, query='', offset=0, limit=80):
        repo = self.repository(value)
        project = self.project(project)
        offset = max(0, int(offset))
        args = ['log', '--all', '-z', f'--skip={offset}', f'-n{limit+1}', '--date=iso-strict',
                '--format='+COMMIT_FORMAT]
        if query:
            args += ['--fixed-strings', '--regexp-ignore-case', f'--grep={query}']
        args += ['--']
        if not all_commits:
            directory = str(PurePosixPath(project).parent)
            if directory != '.':
                args.append(directory+'/')
        result = _decode_commits(self.git(repo, *args))
        return {'commits': result[:limit], 'more': len(result) > limit}

    def snapshot(self, value, sha, destination):
        repo = self.repository(value)
        destination = Path(destination).resolve()
        if not destination.is_relative_to(self.data):
            raise ValueError('Revision snapshots can only be created inside the data directory.')
        destination.mkdir(parents=True, exist_ok=True)
        command = ['git', '--no-optional-locks', '-c', f'safe.directory={repo}', '-C', str(repo),
                   'archive', '--format=tar', sha]
        with subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=self.env) as process:
            try:
                with tarfile.open(fileobj=process.stdout, mode='r|') as archive:
                    archive.extractall(destination, filter='data')
                stderr = process.stderr.read()
                if process.wait():
                    raise ValueError(stderr.decode('utf-8', 'replace'))
            except BaseException:
                process.kill()
                process.wait()
                raise
