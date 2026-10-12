import json
import sqlite3
import tempfile
import unittest
import threading
from contextlib import closing
from pathlib import Path
from http.server import ThreadingHTTPServer
from urllib.request import Request, urlopen
from urllib.error import HTTPError

from catalog_companion import Companion, make_handler
from catalog_export import build_catalog_files
from kuper_parser import read_existing

def capture(total=1):
    def entry(path, value, post=None):
        return {"request":{"url":"https://web.kuper.ru"+path,"headers":[{"name":"Cookie","value":"must-not-persist"}],"cookies":["private"],**({"postData":{"text":json.dumps(post)}} if post else {})},"response":{"status":200,"content":{"text":json.dumps(value)}}}
    return {"kind":"kuper","data":{"log":{"entries":[
        entry("/api/v3/stores/123/categories",{"categories":[{"slug":"milk","name":"Молочные","products_count":1}]}),
        entry("/api/v3/mweb/stores/123",{"retailer":{"name":"Пятёрочка"}}),
        entry("/api/v3/entities",{"entities":[{"product":{"id":"1","name":"Молоко","price":90,"available":True,"canonical_url":"https://kuper.ru/products/1-milk"}}],"meta":{"current_page":1,"total_pages":total}}, {"store_id":"123","category_permalink":"milk","page":"1","secret_token":"must-not-persist"})
    ]}}}

class CompanionTest(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.output=Path(self.temp.name)/"catalog"
        self.db=Path(self.temp.name)/"catalog.db"
        self.companion=Companion(self.output,self.db)
        build_catalog_files([{"магазин":"Пятёрочка","магазин_id":"123","id":"gone","название":"Прежний товар","доступность":"да","заметка":"ручная заметка"}],self.output)
        self.companion.sync()
    def tearDown(self): self.temp.cleanup()
    def test_partial_capture_preserves_old_stock(self):
        result=self.companion.capture(capture(total=2))
        self.assertFalse(result["complete"])
        self.assertEqual({row["id"] for row in read_existing(self.output/"Все магазины.csv")},{"1","gone"})
        text=(self.companion.inbox/"kuper.complete.har").read_text(encoding="utf-8")
        self.assertNotIn("must-not-persist",text)
    def test_complete_catalog_queue_nutrition_and_database_pipeline(self):
        self.assertTrue(self.companion.capture(capture())["complete"])
        queues=self.companion.queues()
        self.assertEqual(len(queues["kuper"]["entries"]),1)
        entry=queues["kuper"]["entries"][0]
        result=self.companion.nutrition({"format":"nutrition-batch-v1","site":"kuper","results":[{**entry,"status":"ok","data":{"белки":3,"жиры":2.5,"углеводы":4.7,"ккал":53,"кбжу_на":"100 мл","кбжу_парсер":"nutrition-v2","источник_кбжу":"карточка Kuper"}}],"remaining":[]})
        self.assertEqual(result["rows_updated"],1)
        with closing(sqlite3.connect(self.db)) as conn:
            self.assertEqual(conn.execute("SELECT protein,calories FROM catalog_products WHERE product_id='1'").fetchone(),(3,53))
            self.assertEqual(conn.execute("SELECT recommendation_ready FROM catalog_products WHERE product_id='gone'").fetchone()[0],0)
        self.assertEqual(len(self.companion.queues()["kuper"]["entries"]),0)
        self.assertEqual(len(self.companion.queues(refresh=True)["kuper"]["entries"]),1)
    def test_loopback_endpoint_requires_pairing_key(self):
        server=ThreadingHTTPServer(("127.0.0.1",0),make_handler(self.companion,"test-key"))
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            url=f"http://127.0.0.1:{server.server_port}/status"
            with self.assertRaises(HTTPError) as error: urlopen(url)
            self.assertEqual(error.exception.code,401)
            with urlopen(Request(url,headers={"X-Avelin-Token":"test-key"})) as response:
                self.assertTrue(json.load(response)["ok"])
        finally:server.shutdown();server.server_close();thread.join()

if __name__ == "__main__": unittest.main()
