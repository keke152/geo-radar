"""Project registry and explicit per-context storage routing.

The legacy project always stays in HOME/workspace.sqlite3. Registry operations
use only HOME/projects.sqlite3; entering a scope does not open a database or
change the active project. Callers must select a registered ID before exposing
it to a request or worker. New projects are registered only after initialization
has succeeded, without holding the registry lock during project initialization.
"""
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
from pathlib import Path
import json
import re
import shutil
import sqlite3
import uuid

from config import HOME


DEFAULT_PROJECT_ID = 'default'
DEFAULT_PROJECT_TITLE = '默认项目'
_current_project = ContextVar('geo_radar_project', default=DEFAULT_PROJECT_ID)


def validate_project_id(pid):
    if not isinstance(pid, str) or not re.fullmatch(r'default|[a-f0-9]{32}', pid):
        raise ValueError('项目编号无效')
    return pid


def current_project_id():
    return _current_project.get()


@contextmanager
def project_scope(pid):
    """Route storage in this context, restoring its previous value on exit.

    This validates the ID format only, with no registry or filesystem I/O.
    A well-formed, unregistered ID does not create a directory or database.
    """
    token = _current_project.set(validate_project_id(pid))
    try:
        yield pid
    finally:
        _current_project.reset(token)


def project_home(pid=None):
    pid = validate_project_id(current_project_id() if pid is None else pid)
    base = Path(HOME).resolve()
    if pid == DEFAULT_PROJECT_ID:
        return base
    expected = base / 'projects' / pid
    target = expected.resolve()
    # A UUID directory must not be a symlink/junction to another project, even
    # when the resolved destination is still underneath the same HOME.
    if target != expected or not target.is_relative_to(base):
        raise ValueError('项目目录不能通过链接指向其他位置')
    return target


def blank_profile():
    """Return independent empty values, with no legacy business information."""
    return {
        'company_name': '', 'domain': '', 'aliases': [], 'business': '',
        'audience': '', 'public_intro': '', 'audience_confirmed': False,
        'brand_name': '', 'brand_aliases': [], 'brand_relation': '',
    }


def _title(value):
    if not isinstance(value, str) or not 1 <= len(value.strip()) <= 100:
        raise ValueError('项目名称需为1至100字')
    return value.strip()


def _initial_profile(profile):
    value = blank_profile()
    if profile is None:
        return value
    if not isinstance(profile, dict) or not set(profile) <= set(value):
        raise ValueError('项目资料格式无效')
    for key, item in profile.items():
        if key in ('aliases', 'brand_aliases'):
            if not isinstance(item, list) or any(not isinstance(alias, str) for alias in item):
                raise ValueError('项目别名应为文字列表')
        elif key == 'audience_confirmed':
            if not isinstance(item, bool):
                raise ValueError('项目资料确认状态无效')
        elif not isinstance(item, str):
            raise ValueError('项目资料应为文字')
        value[key] = item
    # Copy nested lists so the persisted initial configuration is independent
    # of caller-owned objects, and reject unserializable data before mkdir.
    return json.loads(json.dumps(value, ensure_ascii=False))


@contextmanager
def _registry(default_title=None):
    inferred = _title(default_title) if default_title is not None else None
    base = Path(HOME).resolve()
    base.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(base / 'projects.sqlite3', timeout=20, isolation_level=None)
    connection.row_factory = sqlite3.Row
    try:
        # The tiny registry is serialized with BEGIN IMMEDIATE. Avoid changing
        # journal mode here: concurrent first-open WAL pragmas can raise BUSY
        # before SQLite's normal write-transaction busy timeout is applied.
        connection.execute('BEGIN IMMEDIATE')
        connection.execute('CREATE TABLE IF NOT EXISTS projects(id TEXT PRIMARY KEY,title TEXT NOT NULL,created_at TEXT NOT NULL)')
        connection.execute('CREATE TABLE IF NOT EXISTS project_state(key TEXT PRIMARY KEY,value TEXT NOT NULL)')
        stamp = datetime.now(timezone.utc).isoformat(timespec='seconds')
        connection.execute('INSERT OR IGNORE INTO projects VALUES(?,?,?)',
                           (DEFAULT_PROJECT_ID, inferred or DEFAULT_PROJECT_TITLE, stamp))
        if inferred:
            connection.execute('UPDATE projects SET title=? WHERE id=? AND title=?',
                               (inferred, DEFAULT_PROJECT_ID, DEFAULT_PROJECT_TITLE))
        connection.execute('INSERT OR IGNORE INTO project_state VALUES(?,?)', ('active', DEFAULT_PROJECT_ID))
        active = connection.execute('SELECT value FROM project_state WHERE key=?', ('active',)).fetchone()['value']
        if not connection.execute('SELECT 1 FROM projects WHERE id=?', (active,)).fetchone():
            connection.execute('UPDATE project_state SET value=? WHERE key=?', (DEFAULT_PROJECT_ID, 'active'))
        yield connection
        connection.commit()
    except BaseException:
        connection.rollback()
        raise
    finally:
        connection.close()


def _active(connection):
    return connection.execute('SELECT value FROM project_state WHERE key=?', ('active',)).fetchone()['value']


def _view(row, active):
    return {**dict(row), 'is_default': row['id'] == DEFAULT_PROJECT_ID, 'is_active': row['id'] == active}


def list_projects(default_title=None):
    with _registry(default_title) as connection:
        active = _active(connection)
        rows = connection.execute('SELECT * FROM projects ORDER BY CASE WHEN id=? THEN 0 ELSE 1 END,created_at,id',
                                  (DEFAULT_PROJECT_ID,)).fetchall()
        return [_view(row, active) for row in rows]


def read_active():
    with _registry() as connection:
        return _active(connection)


def read_project(pid):
    pid = validate_project_id(pid)
    with _registry() as connection:
        row = connection.execute('SELECT * FROM projects WHERE id=?', (pid,)).fetchone()
        if row is None:
            raise KeyError('项目不存在')
        return _view(row, _active(connection))


def set_active(pid):
    pid = validate_project_id(pid)
    with _registry() as connection:
        row = connection.execute('SELECT * FROM projects WHERE id=?', (pid,)).fetchone()
        if row is None:
            raise KeyError('项目不存在')
        if pid != DEFAULT_PROJECT_ID and not (project_home(pid) / 'workspace.sqlite3').is_file():
            raise ValueError('项目数据库不存在，当前项目未切换')
        connection.execute('UPDATE project_state SET value=? WHERE key=?', (pid, 'active'))
        return _view(row, pid)


def _remove_incomplete(folder):
    # Only our freshly created UUID directory may be removed on failure. Resolve
    # and check the final target before the recursive filesystem operation.
    base = Path(HOME).resolve()
    target = folder.resolve()
    if folder.is_symlink() or target != folder or target.parent != base / 'projects' or not target.is_relative_to(base):
        raise ValueError('拒绝清理工作区之外的项目目录')
    shutil.rmtree(target)


def new_project(title, profile=None):
    title = _title(title)
    initial = _initial_profile(profile)
    pid = uuid.uuid4().hex
    # Resolve UUID paths only after the common parent exists. Windows realpath
    # can otherwise observe that parent being created by another thread.
    (Path(HOME).resolve() / 'projects').mkdir(parents=True, exist_ok=True)
    folder = project_home(pid)
    # Never reuse or clear a pre-existing directory, even on a UUID collision.
    folder.mkdir(exist_ok=False)
    try:
        from storage import init
        with project_scope(pid):
            init(profile=initial, seed=False)
        stamp = datetime.now(timezone.utc).isoformat(timespec='seconds')
        with _registry() as connection:
            connection.execute('INSERT INTO projects VALUES(?,?,?)', (pid, title, stamp))
            return _view({'id': pid, 'title': title, 'created_at': stamp}, _active(connection))
    except BaseException:
        _remove_incomplete(folder)
        raise
