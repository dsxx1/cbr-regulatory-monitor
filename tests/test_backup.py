import json
import sqlite3
import tempfile
import unittest
import zipfile
from pathlib import Path
from runtime_backup import create_backup


class BackupTests(unittest.TestCase):
    def test_backup_restores_database_and_excludes_secrets(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)/'data';root.mkdir()
            db=sqlite3.connect(root/'service.sqlite');db.execute('create table sample(value text)');db.execute("insert into sample values('retained')");db.commit();db.close()
            (root/'monitor-settings.json').write_text('{}')
            (root/'owner.key').write_text('private');(root/'secrets.txt').write_text('private')
            result=create_backup(root)
            with zipfile.ZipFile(result['file']) as archive:
                self.assertNotIn('owner.key',archive.namelist());self.assertNotIn('secrets.txt',archive.namelist())
                restored=Path(directory)/'restored';archive.extractall(restored)
            db=sqlite3.connect(restored/'service.sqlite')
            self.assertEqual(db.execute('select value from sample').fetchone()[0],'retained')
            self.assertEqual(db.execute('pragma integrity_check').fetchone()[0],'ok');db.close()
