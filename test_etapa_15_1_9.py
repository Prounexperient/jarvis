import tempfile
from pathlib import Path
from unittest.mock import patch
import unittest
import developer_workspace as workspace
import workspace_operations as ops
import workspace_session as session

class Tests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.config = {'security':{'confirm_writes':True},'paths':{'allowed_roots':[str(self.base)]}}
        self.state = self.base/'state.json'; self.backups = self.base/'backups'
        a=patch.object(session,'STATE',self.state);b=patch.object(session,'BACKUP_DIR',self.backups)
        a.start();b.start();self.addCleanup(a.stop);self.addCleanup(b.stop)
        self.root = self.base/'proj'
    def test_create_add_rename_delete_undo(self):
        r=workspace.create_project_structured(str(self.root),[{'path':'a.txt','content':'A'}],self.config)
        self.assertTrue(r['success'],r)
        r=workspace.add_project_files(str(self.root),[{'path':'b.json','content':'{}'}],self.config)
        self.assertTrue(r['success'],r)
        self.assertEqual(session.resolve_reference(self.root,'ultimo'),'b.json')
        self.assertEqual(session.resolve_reference(self.root,'penultimo'),'a.txt')
        r=ops.rename_file('ultimo','config.json',self.config)
        self.assertTrue(r['success'],r)
        self.assertFalse((self.root/'b.json').exists())
        self.assertEqual(session.resolve_reference(self.root,'ultimo'),'config.json')
        r=ops.delete_file('ultimo',self.config)
        self.assertTrue(r['success'],r)
        self.assertFalse((self.root/'config.json').exists())
        r=ops.undo(self.config)
        self.assertTrue(r['success'],r)
        self.assertEqual((self.root/'config.json').read_text(),'{}')
    def test_collision_and_traversal(self):
        workspace.create_project_structured(str(self.root),[{'path':'a.txt','content':'A'},{'path':'b.txt','content':'B'}],self.config)
        self.assertIn('error',ops.rename_file('a.txt','b.txt',self.config))
        with self.assertRaises(ValueError): ops.delete_file('../outside.txt',self.config)
        self.assertEqual((self.root/'a.txt').read_text(),'A')
    def test_edit_no_confirmation(self):
        workspace.create_project_structured(str(self.root),[{'path':'a.py','content':'x = 1\n'}],self.config)
        r=workspace.replace_file(str(self.root/'a.py'),'x = 2\n',self.config)
        self.assertTrue(r['success'],r)
        self.assertEqual((self.root/'a.py').read_text(),'x = 2\n')

if __name__=='__main__': unittest.main()
