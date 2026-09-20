import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import local_server as service


class ContainerTests(unittest.TestCase):
    def test_repeated_click_uses_existing_job(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(service,'DATA',Path(folder)):
            with service.db() as c:
                c.execute('CREATE TABLE jobs(id INTEGER PRIMARY KEY,state TEXT,stage TEXT,started TEXT)')
            with patch.object(service.threading,'Thread') as worker:
                self.assertEqual(service.start_job(), service.start_job())
                worker.assert_called_once()

    def test_task_retry_does_not_create_duplicate(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(service,'DATA',Path(folder)):
            with service.db() as c:
                c.execute('CREATE TABLE tasks(id TEXT PRIMARY KEY,task_id INTEGER,state TEXT,error TEXT)')
                c.execute("INSERT INTO tasks VALUES('a',123,'created','')")
            with patch.object(Path,'read_text',return_value=json.dumps({'news':[{'id':'a','brief':{'summary':'test'}}]})),patch('bot_cloud.call') as api:
                self.assertEqual(service.create_task('a'),123)
                api.assert_not_called()

    def test_uncertain_task_blocks_blind_retry(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(service,'DATA',Path(folder)):
            with service.db() as c:
                c.execute('CREATE TABLE tasks(id TEXT PRIMARY KEY,task_id INTEGER,state TEXT,error TEXT)')
                c.execute("INSERT INTO tasks VALUES('a',NULL,'uncertain','')")
            with patch.object(Path,'read_text',return_value=json.dumps({'news':[{'id':'a','brief':{'summary':'test'}}]})),patch('bot_cloud.call') as api:
                with self.assertRaisesRegex(ValueError,'прошлой попытки'):service.create_task('a')
                api.assert_not_called()
