"""Project routing and registry tests using fresh disposable HOME directories."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import test_workspace  # Establish the isolated suite HOME before app imports.
import projects
import storage
from config import DEFAULT_PROFILE, PLATFORMS


class ProjectStorageTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='geo-radar-project-storage-')
        self.addCleanup(temporary.cleanup)
        self.home = Path(temporary.name).resolve()
        self.home_patch = patch.object(projects, 'HOME', self.home)
        self.home_patch.start()
        self.addCleanup(self.home_patch.stop)
        self.scope = projects.project_scope('default')
        self.scope.__enter__()
        self.addCleanup(self.scope.__exit__, None, None, None)

    def test_legacy_init_only_creates_legacy_database_not_registry(self):
        storage.init()
        self.assertEqual(projects.project_home(), self.home)
        self.assertTrue((self.home / 'workspace.sqlite3').is_file())
        self.assertFalse((self.home / 'projects.sqlite3').exists())
        self.assertFalse((self.home / 'projects').exists())

    def test_registering_default_preserves_existing_profile_tasks_materials_and_plans(self):
        storage.init()
        profile = {**DEFAULT_PROFILE, 'brand_name': '既有测试品牌', 'business': '既有测试业务'}
        storage.set_meta('profile', profile)
        with storage.db() as connection:
            connection.execute("INSERT INTO tasks(id,batch_id,platform,channel,mode,keyword,prompt,status,answer,reviewed,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                               ('legacy-task', 'fixture', 'deepseek', 'web', 'visibility', '原问题', '原提示词', 'completed', '原回答', 1, storage.now(), storage.now()))
            connection.execute('INSERT INTO schedules VALUES(?,?,?,?,?,?,?,?)',
                               ('legacy-schedule', '09:00', '[]', '["deepseek"]', 'visibility', 0, '', storage.now()))
            connection.execute('INSERT INTO platform_schedules VALUES(?,?,?,?,?,?,?,?,?)',
                               ('legacy-platform-schedule', '10:00', '[]', 'visibility', 'fresh', 0, '', storage.now(), storage.now()))
        before = {table: storage.records(table) for table in ('tasks', 'documents', 'keywords', 'schedules')}
        listing = projects.list_projects(profile['brand_name'])
        self.assertEqual(listing[0]['title'], profile['brand_name'])
        self.assertEqual(listing[0]['id'], 'default')
        self.assertEqual(storage.get_meta('profile'), profile)
        self.assertEqual({table: storage.records(table) for table in before}, before)
        with storage.db() as connection:
            self.assertEqual(connection.execute('SELECT count(*) FROM platform_schedules').fetchone()[0], 1)
        self.assertFalse((self.home / 'projects').exists())

    def test_default_title_can_be_inferred_once_without_overwriting_supplied_title(self):
        self.assertEqual(projects.list_projects()[0]['title'], '默认项目')
        self.assertEqual(projects.list_projects('原品牌')[0]['title'], '原品牌')
        self.assertEqual(projects.list_projects('后来传入的标题')[0]['title'], '原品牌')

    def test_blank_project_has_no_original_business_materials_keywords_or_plans(self):
        storage.init()
        project = projects.new_project('新品牌')
        self.assertRegex(project['id'], r'^[a-f0-9]{32}$')
        self.assertFalse(project['is_default'])
        self.assertFalse(project['is_active'])
        with projects.project_scope(project['id']):
            self.assertEqual(storage.get_meta('profile'), projects.blank_profile())
            self.assertEqual(projects.project_home(), self.home / 'projects' / project['id'])
            for table in ('tasks', 'documents', 'keywords', 'schedules'):
                self.assertEqual(storage.records(table), [], table)
            with storage.db() as connection:
                for table in ('batches', 'platform_keywords', 'platform_schedules', 'keyword_candidates', 'keyword_generation_runs', 'platform_keyword_generation_runs'):
                    self.assertEqual(connection.execute('SELECT count(*) FROM ' + table).fetchone()[0], 0, table)
            self.assertFalse(storage.get_meta('keyword_plan')['enabled'])
            for pid in PLATFORMS:
                platform = storage.get_meta('platform:' + pid)
                self.assertFalse(platform['ready'])
                self.assertEqual(platform['model'], '')
                self.assertEqual(platform['send_button'], '')
            storage.init()  # Reopening must never inject the legacy demonstration.
            self.assertEqual(storage.get_meta('profile'), projects.blank_profile())
            self.assertEqual(storage.records('documents'), [])
        self.assertEqual(storage.get_meta('profile'), DEFAULT_PROFILE)

    def test_supplied_new_profile_is_independent_and_isolated(self):
        supplied = {'company_name': '新企业', 'brand_name': '新品牌', 'brand_aliases': ['新别名']}
        project = projects.new_project('项目乙', supplied)
        supplied['brand_aliases'].append('调用方后改的别名')
        with projects.project_scope(project['id']):
            saved = storage.get_meta('profile')
            self.assertEqual(saved['brand_aliases'], ['新别名'])
            self.assertEqual(saved['company_name'], '新企业')
            self.assertEqual(saved['domain'], '')
            self.assertEqual(saved['public_intro'], '')
            self.assertEqual(storage.records('documents'), [])

    def test_active_selection_persists_without_changing_context_routing(self):
        storage.init()
        project = projects.new_project('项目乙')
        self.assertEqual(projects.read_active(), 'default')
        self.assertTrue(projects.set_active(project['id'])['is_active'])
        self.assertEqual(projects.read_active(), project['id'])
        self.assertEqual(projects.current_project_id(), 'default')
        self.assertEqual(storage.get_meta('profile'), DEFAULT_PROFILE)
        with closing(sqlite3.connect(self.home / 'projects.sqlite3')) as connection:
            self.assertEqual(connection.execute("SELECT value FROM project_state WHERE key='active'").fetchone()[0], project['id'])
        self.assertTrue(projects.read_project(project['id'])['is_active'])
        with projects.project_scope(project['id']):
            self.assertEqual(storage.get_meta('profile'), projects.blank_profile())

    def test_nested_scopes_restore_context_after_an_exception(self):
        first = 'a' * 32
        second = 'b' * 32
        with projects.project_scope(first):
            with self.assertRaises(RuntimeError):
                with projects.project_scope(second):
                    self.assertEqual(projects.current_project_id(), second)
                    raise RuntimeError('fixture')
            self.assertEqual(projects.current_project_id(), first)
        self.assertEqual(projects.current_project_id(), 'default')

    def test_invalid_project_ids_cannot_escape_home_or_create_files(self):
        for pid in ('../default', '../../outside', '/tmp/other', r'C:\other', 'DEFAULT', 'A' * 32, 'a' * 31, '', None, 123):
            with self.subTest(pid=pid):
                with self.assertRaises(ValueError):
                    with projects.project_scope(pid):
                        pass
        self.assertEqual(list(self.home.iterdir()), [])
        with projects.project_scope('a' * 32):
            self.assertEqual(projects.project_home(), self.home / 'projects' / ('a' * 32))
        self.assertEqual(list(self.home.iterdir()), [])

    def test_project_junction_cannot_resolve_to_a_different_project(self):
        # Exercise Path.resolve's junction result without requiring Windows
        # symlink privileges. A -> B must fail even though B is inside HOME.
        first = self.home / 'projects' / ('a' * 32)
        second = self.home / 'projects' / ('b' * 32)
        original_resolve = Path.resolve

        def resolve(path, *args, **kwargs):
            return second if path == first else original_resolve(path, *args, **kwargs)

        with patch.object(Path, 'resolve', resolve):
            with self.assertRaises(ValueError):
                projects.project_home('a' * 32)
        self.assertEqual(list(self.home.iterdir()), [])

    def test_unknown_registered_or_missing_project_does_not_change_active(self):
        projects.list_projects()
        missing = 'a' * 32
        with self.assertRaises(KeyError):
            projects.set_active(missing)
        with self.assertRaises(KeyError):
            projects.read_project(missing)
        self.assertEqual(projects.read_active(), 'default')
        self.assertFalse((self.home / 'projects').exists())

    def test_initialization_failure_removes_only_new_directory_and_does_not_register(self):
        projects.list_projects('原项目')
        known = 'a' * 32

        def fail_init(**kwargs):
            self.assertEqual(projects.current_project_id(), known)
            self.assertEqual(kwargs, {'profile': projects.blank_profile(), 'seed': False})
            (projects.project_home() / 'workspace.sqlite3').write_bytes(b'partial fixture')
            raise RuntimeError('fixture init failure')

        with patch.object(projects.uuid, 'uuid4', return_value=SimpleNamespace(hex=known)), patch.object(storage, 'init', side_effect=fail_init):
            with self.assertRaisesRegex(RuntimeError, 'fixture init failure'):
                projects.new_project('创建失败的项目')
        self.assertFalse((self.home / 'projects' / known).exists())
        self.assertEqual([row['id'] for row in projects.list_projects()], ['default'])
        self.assertEqual(projects.current_project_id(), 'default')

    def test_registration_failure_rolls_back_and_removes_initialized_directory(self):
        projects.list_projects()
        known = 'a' * 32
        with patch.object(projects.uuid, 'uuid4', return_value=SimpleNamespace(hex=known)), patch.object(projects, '_view', side_effect=RuntimeError('fixture registry failure')):
            with self.assertRaisesRegex(RuntimeError, 'fixture registry failure'):
                projects.new_project('登记失败的项目')
        self.assertFalse((self.home / 'projects' / known).exists())
        self.assertEqual([row['id'] for row in projects.list_projects()], ['default'])

    def test_directory_creation_failure_does_not_register_project(self):
        projects.list_projects()
        known = 'a' * 32
        target = self.home / 'projects' / known
        original_mkdir = Path.mkdir

        def mkdir(path, *args, **kwargs):
            if path == target:
                raise PermissionError('fixture mkdir denied')
            return original_mkdir(path, *args, **kwargs)

        with patch.object(projects.uuid, 'uuid4', return_value=SimpleNamespace(hex=known)), patch.object(Path, 'mkdir', mkdir):
            with self.assertRaises(PermissionError):
                projects.new_project('目录失败的项目')
        self.assertFalse(target.exists())
        self.assertEqual([row['id'] for row in projects.list_projects()], ['default'])

    def test_existing_directory_is_never_reused_or_removed_on_uuid_collision(self):
        known = 'a' * 32
        target = self.home / 'projects' / known
        target.mkdir(parents=True)
        marker = target / 'keep.txt'
        marker.write_text('unrelated fixture', encoding='utf-8')
        with patch.object(projects.uuid, 'uuid4', return_value=SimpleNamespace(hex=known)):
            with self.assertRaises(FileExistsError):
                projects.new_project('碰撞项目')
        self.assertEqual(marker.read_text(encoding='utf-8'), 'unrelated fixture')
        self.assertEqual([row['id'] for row in projects.list_projects()], ['default'])

    def test_parallel_project_creation_registers_only_complete_independent_databases(self):
        with ThreadPoolExecutor(max_workers=4) as executor:
            created = list(executor.map(lambda number: projects.new_project('并发项目' + str(number)), range(8)))
        self.assertEqual(len({row['id'] for row in created}), 8)
        self.assertEqual(len(projects.list_projects()), 9)
        self.assertEqual(projects.read_active(), 'default')
        for row in created:
            with projects.project_scope(row['id']):
                self.assertEqual(storage.get_meta('profile'), projects.blank_profile())
        self.assertEqual(projects.current_project_id(), 'default')

    def test_thread_contexts_write_to_their_own_databases(self):
        first = projects.new_project('线程甲')
        second = projects.new_project('线程乙')

        def worker(item):
            project, marker = item
            self.assertEqual(projects.current_project_id(), 'default')
            with projects.project_scope(project['id']):
                storage.set_meta('thread-marker', marker)
                result = (projects.current_project_id(), storage.get_meta('thread-marker'))
            self.assertEqual(projects.current_project_id(), 'default')
            return result

        with ThreadPoolExecutor(max_workers=2) as executor:
            actual = list(executor.map(worker, [(first, '甲'), (second, '乙')]))
        self.assertEqual(actual, [(first['id'], '甲'), (second['id'], '乙')])
        for row, expected in ((first, '甲'), (second, '乙')):
            with projects.project_scope(row['id']):
                self.assertEqual(storage.get_meta('thread-marker'), expected)

    def test_async_contexts_do_not_follow_other_requests_or_active_selection(self):
        first = projects.new_project('异步甲')
        second = projects.new_project('异步乙')

        async def scenario():
            gate = asyncio.Event()
            arrived = []

            async def worker(project, marker):
                with projects.project_scope(project['id']):
                    arrived.append(marker)
                    if len(arrived) == 2:
                        gate.set()
                    await gate.wait()
                    storage.set_meta('async-marker', marker)
                    await asyncio.sleep(0)
                    self.assertEqual(projects.current_project_id(), project['id'])
                    self.assertEqual(storage.get_meta('async-marker'), marker)

            await asyncio.gather(worker(first, '甲'), worker(second, '乙'))

        projects.set_active(second['id'])
        asyncio.run(scenario())
        self.assertEqual(projects.current_project_id(), 'default')


if __name__ == '__main__':
    unittest.main()
