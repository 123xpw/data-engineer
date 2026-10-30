"""从数据库容器消费边界验证共享配置隔离，全部凭据均为固定假值。"""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from q2_sql_analysis import mysql_runtime as runtime


class MysqlEnvironmentCases(unittest.TestCase):
    def test_only_four_database_keys_reach_temporary_file_and_source_unchanged(self):
        with tempfile.TemporaryDirectory() as folder:
            config=Path(folder)/'.env'
            original='MYSQL_USER=fixture\nMYSQL_PASSWORD=fixture-db\nMYSQL_DATABASE=fixture\nMYSQL_ROOT_PASSWORD=fixture-root\nDEEPSEEK_API_KEY=fixture-model-do-not-send\nQ4_LIVE=1\n'
            config.write_text(original)
            with patch.object(runtime,'CONFIG',config):
                with runtime.mysql_env_file() as name:
                    target=Path(name);text=target.read_text()
                    self.assertEqual({line.split('=',1)[0] for line in text.splitlines()},{'MYSQL_USER','MYSQL_PASSWORD','MYSQL_DATABASE','MYSQL_ROOT_PASSWORD'})
                    self.assertNotIn('fixture-model-do-not-send',text);self.assertEqual(target.stat().st_mode&0o777,0o600)
                self.assertFalse(target.exists());self.assertEqual(config.read_text(),original)
                with self.assertRaises(RuntimeError):
                    with runtime.mysql_env_file() as name:
                        target=Path(name);raise RuntimeError('固定中断')
                self.assertFalse(target.exists())


if __name__=='__main__':unittest.main()
