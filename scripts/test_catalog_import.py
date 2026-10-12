import csv
import sqlite3
import tempfile
import unittest
from pathlib import Path
from contextlib import closing

from import_product_catalog import import_catalog

class CatalogImportTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.csv = Path(self.temp.name) / "catalog.csv"
        self.db = Path(self.temp.name) / "catalog.db"
        self.row = {"магазин": "Слата", "магазин_id": "slata", "id": "1", "название": "Молоко", "доступность": "да", "цена_руб": "90", "белки": "3", "жиры": "2.5", "углеводы": "4.7", "ккал": "53", "кбжу_на": "100 мл", "источник_кбжу": "карточка Kuper", "кбжу_парсер": "nutrition-v2"}

    def tearDown(self): self.temp.cleanup()
    def write(self, rows):
        with self.csv.open("w", encoding="utf-8-sig", newline="") as stream:
            writer=csv.DictWriter(stream, fieldnames=self.row, delimiter=";")
            writer.writeheader();writer.writerows(rows)
    def product(self):
        with closing(sqlite3.connect(self.db)) as conn:
            return conn.execute("SELECT protein,calories,nutrition_source,recommendation_ready FROM catalog_products WHERE product_id='1'").fetchone()
    def test_accepts_verified_current_parser(self):
        self.write([self.row]);import_catalog(self.csv,self.db)
        self.assertEqual(self.product(), (3,53,"карточка Kuper",1))
    def test_rejects_old_parser_and_impossible_nutrition(self):
        for changes in [{"кбжу_парсер":"nutrition-v1"},{"ккал":"223.4"},{"белки":"nan"},{"источник_кбжу":""}]:
            self.write([{**self.row,**changes}]);import_catalog(self.csv,self.db)
            self.assertEqual(self.product(),(None,None,None,1))
    def test_complete_snapshot_disables_vanished_products(self):
        self.write([self.row,{**self.row,"id":"2"}]);import_catalog(self.csv,self.db)
        self.write([self.row]);import_catalog(self.csv,self.db,replace_stores=False)
        with closing(sqlite3.connect(self.db)) as conn:
            self.assertEqual(conn.execute("SELECT available FROM catalog_products WHERE product_id='2'").fetchone()[0],1)
        import_catalog(self.csv,self.db,replace_stores=True)
        with closing(sqlite3.connect(self.db)) as conn:
            self.assertEqual(conn.execute("SELECT available,recommendation_ready FROM catalog_products WHERE product_id='2'").fetchone(),(0,0))

if __name__ == "__main__": unittest.main()
