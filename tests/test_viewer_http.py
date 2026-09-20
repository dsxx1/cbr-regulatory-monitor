import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.request import Request,urlopen
from urllib.error import HTTPError
from http.server import ThreadingHTTPServer
from admin_auth import OwnerAuth
import local_server


class ViewerHttpTests(unittest.TestCase):
    def test_guest_cannot_read_settings_or_mutate(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/'public').mkdir()
            (root/'public/news.json').write_text(json.dumps({'settings':{'generator':'private-choice'},'models':['private-choice'],'news':[]}),encoding='utf-8')
            with patch.object(local_server,'DATA',root),patch.object(local_server,'AUTH',OwnerAuth(root)):
                server=ThreadingHTTPServer(('127.0.0.1',0),local_server.Handler)
                thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
                base='http://127.0.0.1:'+str(server.server_port)
                try:
                    with urlopen(base+'/api/status') as r:
                        value=json.load(r);self.assertFalse(value['owner']);self.assertNotIn('token',value)
                    with urlopen(base+'/news.json') as r:
                        value=json.load(r);self.assertEqual(value['settings'],{});self.assertEqual(value['models'],[])
                    for name in ('settings','schedule','check','stop','task'):
                        with self.assertRaises(HTTPError) as failure:urlopen(Request(base+'/api/'+name,data=b'{}'))
                        self.assertEqual(failure.exception.code,403)
                    for path in ('/status.json','/delivery.json','/../owner.key','/materials/'):
                        with self.assertRaises(HTTPError) as failure:urlopen(base+path)
                        self.assertEqual(failure.exception.code,404)
                finally:
                    server.shutdown();server.server_close();thread.join()
