"""Owned, anonymous HTTPS Git clones; job scheduling belongs to the engine."""
import hashlib
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import tempfile
import threading
from urllib.parse import unquote, urlsplit, urlunsplit


class ManagedRepos:
    def __init__(self, data, env):
        self.data = Path(data).absolute()
        self.root = self.data/'repos'
        self.env = {key: value for key, value in env.items() if not key.startswith('GIT_')}
        self.env.update(GIT_TERMINAL_PROMPT='0', GIT_CONFIG_NOSYSTEM='1',
                        GIT_CONFIG_GLOBAL='/dev/null', GIT_ALLOW_PROTOCOL='https',
                        GIT_LFS_SKIP_SMUDGE='1')
        self._lock = threading.Lock()
        self._processes = set()
        self._closed = False
        if self.data.resolve() != self.data:
            raise ValueError('Managed data directory must not contain symlinks.')
        self._check_root()
        self.root.mkdir(parents=True, exist_ok=True)
        self.home = self.data/'.anonymous-git-home'
        if self.home.is_symlink() or self.home.resolve() != self.home:
            raise ValueError('Anonymous Git home must not contain symlinks.')
        self.home.mkdir(exist_ok=True)
        self.env['HOME'] = str(self.home)

    @staticmethod
    def normalize_url(value):
        if not isinstance(value, str):
            raise ValueError('Enter a public HTTPS Git URL.')
        # Reject controls before stripping surrounding ordinary spaces.
        if any(ord(char) < 32 or ord(char) == 127 for char in unquote(value)):
            raise ValueError('Git URL must not contain control characters.')
        value = value.strip(' ')
        try:
            parts = urlsplit(value)
            if (parts.scheme.lower() != 'https' or not parts.hostname or parts.username is not None
                    or parts.password is not None or '?' in value or '#' in value
                    or '\\' in value or any(char.isspace() for char in value)):
                raise ValueError()
            host = parts.hostname.encode('idna').decode('ascii').lower()
            if not re.fullmatch(r'[a-z0-9.-]+', host) or host.startswith(('.', '-')) or '..' in host:
                raise ValueError()
            port = parts.port
            if port is not None and not 1 <= port <= 65535:
                raise ValueError()
            authority = host + (f':{port}' if port is not None and port != 443 else '')
            return urlunsplit(('https', authority, parts.path or '/', '', ''))
        except (ValueError, UnicodeError):
            raise ValueError('Enter an anonymous HTTPS Git URL without credentials, query, or fragment.') from None

    @staticmethod
    def identifier(url):
        return hashlib.sha256(url.encode('utf-8')).hexdigest()[:24]

    def _check_root(self):
        if self.data.resolve() != self.data or self.root.is_symlink() or self.root.resolve() != self.root:
            raise ValueError('Managed repository directory must not contain symlinks.')

    def path(self, identifier):
        if not isinstance(identifier, str) or not re.fullmatch('[0-9a-f]{24}', identifier):
            raise ValueError('Invalid managed repository identifier.')
        self._check_root()
        return self._owned(self.root/identifier)

    def _owned(self, target):
        self._check_root()
        if target.is_symlink() or target.resolve() != target:
            raise ValueError('Managed repository must not be a symlink.')
        git_dir = target/'.git'
        if git_dir.is_symlink() or (git_dir.exists() and not git_dir.is_dir()):
            raise ValueError('Managed Git directory must be an owned directory.')
        return target

    @staticmethod
    def _terminate(process):
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass

    def _git(self, args, cwd=None, _recovery=False):
        if _recovery and (not args or args[0] not in {'update-ref', 'symbolic-ref', 'reset'}):
            raise ValueError('Recovery only permits local checkout restoration.')
        environment = self.env if not _recovery else dict(self.env, GIT_ALLOW_PROTOCOL='', GIT_NO_LAZY_FETCH='1')
        https_policy = 'never' if _recovery else 'always'
        command = ['git', '-c', 'protocol.allow=never', '-c', f'protocol.https.allow={https_policy}',
                   '-c', 'credential.helper=', '-c', 'core.hooksPath=/dev/null',
                   '-c', 'core.fsmonitor=false', '-c', 'http.sslVerify=true',
                   '-c', 'http.followRedirects=false', '-c', 'submodule.recurse=false',
                   '-c', 'filter.lfs.smudge=', '-c', 'filter.lfs.required=false', *args]
        # Output goes to a temporary file so a noisy remote cannot exhaust RAM.
        with tempfile.TemporaryFile(mode='w+b') as errors:
            with self._lock:
                if self._closed and not _recovery:
                    raise ValueError('Managed repository service is closed.')
                try:
                    process = subprocess.Popen(command, cwd=cwd, env=environment, stdout=subprocess.PIPE,
                                               stderr=errors, text=True, start_new_session=True)
                except OSError as exc:
                    raise ValueError(f'Unable to run Git: {exc}') from None
                self._processes.add(process)
            try:
                try:
                    output, _ = process.communicate(timeout=900)
                except subprocess.TimeoutExpired:
                    self._terminate(process)
                    process.communicate()
                    raise ValueError('Git operation timed out after 900 seconds.') from None
                if process.returncode:
                    errors.seek(0, os.SEEK_END)
                    errors.seek(max(0, errors.tell() - 4096))
                    detail = errors.read().decode('utf-8', errors='replace').strip()
                    raise ValueError(f'Git operation failed: {detail or "remote unavailable"}')
                return output
            finally:
                with self._lock:
                    self._processes.discard(process)

    def _record(self, record):
        url = self.normalize_url(record['url'])
        if self.identifier(url) != record['id']:
            raise ValueError('Managed repository URL does not match its identifier.')
        return url, self._owned(self.path(record['id']))

    def clone(self, record):
        url, target = self._record(record)
        if target.exists():
            # Publication is atomic; a crash before the registry update can leave a
            # complete clone here. Reusing it must never contact the remote.
            try:
                if not (target/'.git').is_dir():
                    raise ValueError('Missing Git directory.')
                top = self._git(['rev-parse', '--show-toplevel'], cwd=target).strip()
                if Path(top).resolve() != target:
                    raise ValueError('Git repository root does not match the managed directory.')
            except ValueError as exc:
                raise ValueError(f'Existing managed repository is incomplete or invalid; delete it and retry. {exc}') from None
            return
        staging = self._owned(self.root/f'.staging-{record["id"]}')
        if staging.exists():
            shutil.rmtree(staging)
        try:
            self._git(['clone', '--no-recurse-submodules', '--origin', 'origin', '--', url, str(staging)])
            self._owned(staging)
            staging.rename(target)
        except (OSError, ValueError) as exc:
            if staging.exists() and not staging.is_symlink():
                shutil.rmtree(staging)
            raise ValueError(str(exc)) from None

    def refresh(self, record):
        url, target = self._record(record)
        if not (target/'.git').is_dir():
            raise ValueError('Managed repository is missing.')
        previous_head = self._git(['rev-parse', 'HEAD'], cwd=target).strip()
        previous_branch = self._git(['symbolic-ref', '-q', 'HEAD'], cwd=target).strip()
        previous_default = self._git(['symbolic-ref', 'refs/remotes/origin/HEAD'], cwd=target).strip()
        changed_branch = None
        old_branch_commit = None
        try:
            self._git(['fetch', '--prune', '--tags', '--no-recurse-submodules', '--', url,
                       '+refs/heads/*:refs/remotes/origin/*'], cwd=target)
            remote_head = self._git(['ls-remote', '--symref', '--', url, 'HEAD'], cwd=target)
            match = re.search(r'^ref: refs/heads/(.+)\tHEAD$', remote_head, re.MULTILINE)
            if not match:
                raise ValueError('Remote repository has no default branch.')
            branch = match.group(1)
            self._git(['check-ref-format', f'refs/heads/{branch}'], cwd=target)
            changed_branch = f'refs/heads/{branch}'
            try:
                old_branch_commit = self._git(['rev-parse', '--verify', changed_branch], cwd=target).strip()
            except ValueError:
                pass
            self._git(['checkout', '-B', branch, f'refs/remotes/origin/{branch}', '--'], cwd=target)
            self._git(['symbolic-ref', 'refs/remotes/origin/HEAD', f'refs/remotes/origin/{branch}'], cwd=target)
        except (OSError, ValueError) as exc:
            # A failed fetch may update refs; the previously usable checkout stays available.
            if self._closed or 'timed out' in str(exc):
                # The worker owns this clone and the interrupted Git process has
                # exited. Remove its checkout/ref locks before local restoration.
                refs = [previous_branch, previous_default, changed_branch]
                locks = [target/'.git/index.lock', target/'.git/HEAD.lock',
                         target/'.git/refs/remotes/origin/HEAD.lock']
                locks += [target/'.git'/f'{ref}.lock' for ref in refs if ref]
                for lock in locks:
                    if lock.parent.resolve().is_relative_to((target/'.git').resolve()):
                        lock.unlink(missing_ok=True)
            if changed_branch:
                if old_branch_commit:
                    self._git(['update-ref', changed_branch, old_branch_commit], cwd=target, _recovery=True)
                elif changed_branch != previous_branch:
                    self._git(['update-ref', '-d', changed_branch], cwd=target, _recovery=True)
            self._git(['symbolic-ref', 'HEAD', previous_branch], cwd=target, _recovery=True)
            self._git(['reset', '--hard', previous_head], cwd=target, _recovery=True)
            self._git(['symbolic-ref', 'refs/remotes/origin/HEAD', previous_default], cwd=target, _recovery=True)
            raise ValueError(str(exc)) from None

    def remove(self, identifier):
        target = self._owned(self.path(identifier))
        staging = self._owned(self.root/f'.staging-{identifier}')
        for directory in (target, staging):
            if directory.exists():
                shutil.rmtree(directory)

    def size(self, identifier):
        target = self.path(identifier)
        staging = self._owned(self.root/f'.staging-{identifier}')
        total = 0
        for owned in (target, staging):
            for directory, _, files in os.walk(owned, followlinks=False):
                for filename in files:
                    item = Path(directory)/filename
                    if not item.is_symlink():
                        try:
                            total += item.stat(follow_symlinks=False).st_size
                        except FileNotFoundError:
                            pass
        return total

    def close(self):
        with self._lock:
            self._closed = True
            for process in self._processes:
                self._terminate(process)
