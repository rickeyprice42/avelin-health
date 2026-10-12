import json
import sqlite3
from contextlib import closing
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import agent_tools
import recipes


class RecipesTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = Path(self.temp.name) / "recipes.db"
        self.patch = patch.object(agent_tools, "DB", self.db)
        self.patch.start()
        with closing(sqlite3.connect(self.db)) as conn, conn:
            conn.executescript("CREATE TABLE catalog_products(name TEXT,store_name TEXT,package TEXT,price_rub REAL,url TEXT,category TEXT,recommendation_ready INTEGER,brand TEXT,protein REAL,fat REAL,carbs REAL,calories REAL,nutrition_basis TEXT,nutrition_source TEXT);")
            conn.executemany("INSERT INTO catalog_products(name,store_name,package,price_rub,url,category,recommendation_ready,brand) VALUES(?,?,?,?,?,?,1,'')", [
                ("Филе 500 г", "Слата", "500 г", 200, "https://example.org/product", "Мясо"),
                ("Рис", "Пятёрочка", "900 г", 90, None, "Крупы"),
                ("Неизвестная цена", "Слата", None, None, None, "Крупы"),
                ("Корм для кошек", "Слата", None, 30, None, "Товары для животных"),
            ])
        self.data = {"title": "Курица с рисом", "minutes": 25, "servings": 2,
                     "ingredients": [{"name": "Филе 500 г", "store_name": "Слата", "amount": "300 г", "packs": 1},
                                     {"name": "Рис", "store_name": "Пятёрочка", "amount": "150 г", "packs": 2}],
                     "steps": ["Отвари рис.", "Приготовь курицу до полной готовности."],
                     "macros": {"calories": [450, 550], "protein": [35, 45], "fat": [8, 12], "carbs": None}}

    def tearDown(self):
        self.patch.stop()
        self.temp.cleanup()

    def test_catalog_prices_override_model_and_total_is_pack_cost(self):
        self.data["ingredients"][0]["price_rub"] = 1
        self.data["ingredients"][0]["url"] = "javascript:alert(1)"
        card = recipes.build(self.db, **self.data)
        self.assertEqual(card["total_rub"], 380)
        self.assertEqual(card["ingredients"][0]["price_rub"], 200)
        self.assertEqual(card["ingredients"][0]["url"], "https://example.org/product")

    def test_unknown_price_does_not_produce_misleading_total(self):
        self.data["ingredients"][0]["name"] = "Неизвестная цена"
        self.assertIsNone(recipes.build(self.db, **self.data)["total_rub"])

    def test_rejects_missing_and_nonfood_products(self):
        for name in ["Выдуманный товар", "Корм для кошек"]:
            self.data["ingredients"][0]["name"] = name
            with self.assertRaises(ValueError): recipes.build(self.db, **self.data)

    def test_rejects_bad_macros_and_quantities(self):
        for value in [[550, 450], [float("nan"), 500], 500]:
            self.data["macros"]["calories"] = value
            with self.assertRaises(ValueError): recipes.build(self.db, **self.data)
        self.data["macros"]["calories"] = [450, 550]
        for value in [0, -1, True, 1.5]:
            self.data["ingredients"][0]["packs"] = value
            with self.assertRaises(ValueError): recipes.build(self.db, **self.data)

    def test_save_is_idempotent_and_checks_survive_reload(self):
        card = recipes.save(self.db, self.data)
        recipes.check(self.db, card["id"], [1])
        recipes.save(self.db, self.data)
        saved = recipes.list_saved(self.db)
        self.assertEqual(len(saved), 1)
        self.assertEqual(saved[0]["checked"], [1])
        self.assertEqual(saved[0]["steps"], self.data["steps"])
        with self.assertRaises(ValueError): recipes.check(self.db, card["id"], [2])


if __name__ == "__main__": unittest.main()
