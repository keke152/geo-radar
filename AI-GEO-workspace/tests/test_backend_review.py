"""Regression checks for local HTTP access and well-formed Excel exports."""
import io
import unittest
import zipfile
from xml.etree import ElementTree as E

import test_workspace
from fastapi.testclient import TestClient
import app
from config import DEFAULT_PROFILE
from record_export import build_xlsx,NS
from storage import db,init,records

HEADERS={'X-Workspace-Request':'junhe-local'}

class BackendReviewTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  cls.context=TestClient(app.app,base_url='http://127.0.0.1:8020')
  cls.client=cls.context.__enter__()
 @classmethod
 def tearDownClass(cls):cls.context.__exit__(None,None,None)
 def setUp(self):
  with db() as c:
   for table in ('tasks','batches','schedules','documents','keywords','meta','record_delete_previews'):c.execute('DELETE FROM '+table)
  init()
 task=test_workspace.InsightsTests.task
 def test_foreign_hosts_cannot_read_or_mutate_local_workspace(self):
  before=records('keywords')
  for host in ('rebind.example:8020','localhost.evil.example:8020','127.0.0.1.evil.example','testserver'):
   with self.subTest(host=host):
    self.assertEqual(self.client.get('/api/bootstrap',headers={'Host':host}).status_code,403)
    response=self.client.post('/api/keywords',json={'text':'must-not-be-saved'},headers={**HEADERS,'Host':host,'Origin':'http://'+host})
    self.assertEqual(response.status_code,403,response.text)
  self.assertEqual(records('keywords'),before)
 def test_local_hosts_and_matching_origins_remain_usable(self):
  for host in ('127.0.0.1:8020','localhost:8020','[::1]:8020','localhost','127.0.0.1'):
   with self.subTest(host=host):
    self.assertEqual(self.client.get('/api/health',headers={'Host':host}).status_code,200)
    response=self.client.post('/api/keywords',json={'text':'local '+host},headers={**HEADERS,'Host':host,'Origin':'http://'+host})
    self.assertEqual(response.status_code,200,response.text)
 def test_invalid_and_duplicate_host_headers_are_rejected(self):
  for host in ('localhost:0','localhost:65536','localhost:bad','user@localhost','localhost.',''):
   with self.subTest(host=host):self.assertEqual(self.client.get('/api/health',headers={'Host':host}).status_code,403)
  self.assertEqual(self.client.get('/api/health',headers=[('Host','localhost'),('Host','rebind.example')]).status_code,403)
 def test_local_host_does_not_bypass_origin_or_mutation_header(self):
  self.assertEqual(self.client.post('/api/keywords',json={'text':'blocked'}).status_code,403)
  response=self.client.post('/api/keywords',json={'text':'blocked'},headers={**HEADERS,'Origin':'https://evil.example'})
  self.assertEqual(response.status_code,403)
 def test_forbidden_xml_characters_cannot_corrupt_excel_export(self):
  task=self.task(prompt='问题\ufffe\uffff\x00\t继续',answer='回答\ufffe\uffff\x01\n完整🧪')
  exported=build_xlsx([task],DEFAULT_PROFILE)
  with zipfile.ZipFile(io.BytesIO(exported)) as archive:
   sheets=[E.fromstring(archive.read(f'xl/worksheets/sheet{number}.xml')) for number in (1,2)]
  text=''.join(sheets[1].itertext())
  self.assertIn('问题\t继续',text);self.assertIn('回答\n完整🧪',text)
  for char in ('\ufffe','\uffff','\x00','\x01'):self.assertNotIn(char,text)
  order=[element.tag.removeprefix('{'+NS+'}') for element in sheets[0]]
  self.assertLess(order.index('autoFilter'),order.index('mergeCells'))
  self.assertLess(order.index('mergeCells'),order.index('hyperlinks'))

if __name__=='__main__':unittest.main()
