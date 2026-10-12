import json
from pathlib import Path
from tempfile import TemporaryDirectory
from catalog_export import build_catalog_files
from fixprice_parser import page_count_from_html, products_from_html, products_from_html_text, products_from_htmls
from kuper_parser import category_priority, products_from_hars, walk_products, save, read_existing
from nutrition_enrichment import (
    PARSER_VERSION,
    import_nutrition_results,
    nutrition_issue,
    prepare_nutrition_queues,
)
from slata_parser import catalog_from_html, normalize_product, packaging, unpack_nuxt


def test_extract_and_preserve_notes():
    sample = {"categories": [{"category_name": "Молочные продукты", "items": [
        {"id": 42, "name": "Творог 5% 200 г", "price": {"amount": 99}, "brand": "Пример"},
        {"id": 43, "name": "Молоко 1 л", "price": 120},
    ]}]}
    items = list(walk_products(sample))
    assert len(items) == 2
    assert {x["категория"] for x in items} == {"Молочные продукты"}
    assert items[0]["цена_руб"] == "120" or items[1]["цена_руб"] == "120"
    with TemporaryDirectory() as d:
        path = Path(d) / "catalog.csv"
        save(path, [], items)
        rows = read_existing(path)
        rows[0]["заметка"] = "для завтрака"
        rows[0]["белки"] = "17"
        save(path, rows, [{"id": rows[0]["id"], "цена_руб": "109", "название": rows[0]["название"]}])
        updated = next(r for r in read_existing(path) if r["id"] == rows[0]["id"])
        assert updated["заметка"] == "для завтрака"
        assert updated["белки"] == "17"
        assert updated["цена_руб"] == "109"


def test_extract_har_entities_and_deduplicate():
    request = {
        "store_id": "70307",
        "category_permalink": "catalog/meat",
        "page": "1",
        "per_page": "24",
    }
    product = {
        "id": "42",
        "name": "Филе цыплёнка",
        "price": 349.99,
        "human_volume": "800 г",
        "available": True,
        "canonical_url": "https://example.test/products/42",
    }
    har = {"log": {"entries": [
        {
            "request": {"url": "https://web.kuper.ru/api/v3/stores/70307/categories"},
            "response": {"status": 200, "content": {"text": json.dumps({"categories": [{"slug": "meat", "name": "Мясо"}]}, ensure_ascii=False)}},
        },
        {
            "request": {"url": "https://web.kuper.ru/api/v3/entities", "postData": {"text": json.dumps(request)}},
            "response": {"status": 200, "content": {"text": json.dumps({
                "entities": [{"product": product}, {"product": product}],
                "meta": {"current_page": "1", "total_pages": "2"},
            }, ensure_ascii=False)}},
        },
    ]}}
    with TemporaryDirectory() as d:
        path = Path(d) / "hleb&sol.complete.har"
        path.write_text(json.dumps(har, ensure_ascii=False), encoding="utf-8")
        items, stats = products_from_hars([path])
    assert len(items) == 1
    assert items[0]["id"] == "42"
    assert items[0]["категория"] == "Мясо"
    assert items[0]["фасовка"] == "800 г"
    assert items[0]["цена_руб"] == "349.99"
    assert stats["observed"] == 2
    assert stats["unique"] == 1
    assert stats["incomplete_categories"][0]["missing_pages"] == [2]
    assert stats["complete_capture"] is False


def test_real_category_beats_promotion():
    assert category_priority("katalog-fs2/myaso-ptitsa-40ebce3", {}) > category_priority("bez-natsenki-na-brend-copy", {})


def test_slata_nuxt_and_normalization():
    # Minimal devalue payload: root -> wrapper -> catalogue -> product list.
    values = [
        ["ShallowReactive", 1],
        {"data": 2},
        {"products": 3, "pageCount": 4, "count": 5},
        [6],
        1,
        1,
        {"vendorCode": 7, "title": 8, "price": 9, "weight": 10, "unit": 11, "brand": 12},
        "42",
        "Молоко 1 л",
        89.99,
        1.0,
        "шт",
        "Ферма",
    ]
    encoded = json.dumps(values, ensure_ascii=False)
    html = f'<script id="__NUXT_DATA__" type="application/json">{encoded}</script>'
    catalogue = catalog_from_html(html)
    assert catalogue["pageCount"] == 1
    product = catalogue["products"][0]
    assert packaging(product) == "1 л"
    row = normalize_product(product, "moloko-syr-yaytsa", "Молоко, сыр, яйца", "2026-09-29T00:00:00+00:00")
    assert row["магазин"] == "Слата"
    assert row["id"] == "42"
    assert row["цена_руб"] == "89.99"
    assert row["фасовка"] == "1 л"


def test_replace_store_preserves_manual_fields():
    with TemporaryDirectory() as folder:
        output = Path(folder)
        original = [
            {"магазин": "Слата", "магазин_id": "slata-online", "id": "1", "название": "Молоко", "цена_руб": "80", "заметка": "любимое"},
            {"магазин": "Слата", "магазин_id": "slata-online", "id": "2", "название": "Старый товар", "цена_руб": "10"},
            {"магазин": "Хлеб&Соль", "магазин_id": "70307", "id": "1", "название": "Хлеб", "цена_руб": "50"},
        ]
        build_catalog_files(original, output)
        build_catalog_files([
            {"магазин": "Слата", "магазин_id": "slata-online", "id": "1", "название": "Молоко", "цена_руб": "85"},
        ], output, replace_stores=True)
        slata_rows = read_existing(output / "Слата.csv")
        combined_rows = read_existing(output / "Все магазины.csv")
        assert len(slata_rows) == 1
        assert slata_rows[0]["заметка"] == "любимое"
        assert slata_rows[0]["цена_руб"] == "85"
        assert {row["магазин"] for row in combined_rows} == {"Слата", "Хлеб&Соль"}


def test_fixprice_html_adapter():
    html = """
    <html><head><link rel="canonical" href="https://fix-price.com/catalog/produkty-i-napitki?page=2"></head>
    <body>
      <script type="application/ld+json">
        {"@type":"ItemList","itemListElement":[
          {"@type":"Product","sku":"1660028","name":"Сахар белый, 1 кг",
           "url":"/catalog/produkty-i-napitki/p-1660028-sahar-belyy-1-kg",
           "brand":{"name":"Русский сахар"},"offers":{"price":"79.00"}}
        ]}
      </script>
      <a href="/catalog/produkty-i-napitki/p-1660029-chay-25-paketikov">Чай чёрный, 25 пакетиков</a>
    </body></html>
    """
    with TemporaryDirectory() as folder:
        path = Path(folder) / "fix.html"
        path.write_text(html, encoding="utf-8")
        rows = products_from_html(path)
    assert {row["id"] for row in rows} == {"1660028", "1660029"}
    sugar = next(row for row in rows if row["id"] == "1660028")
    assert sugar["цена_руб"] == "79"
    assert sugar["бренд"] == "Русский сахар"
    assert sugar["фасовка"] == "1 кг"


def test_fixprice_nuxt2_prices():
    html = r'''<html><head><link rel="canonical" href="https://fix-price.com/catalog/produkty-i-napitki"></head>
    <body><a href="/catalog/produkty-i-napitki/p-1660028-sahar">Сахар, 1 кг</a>
    <script>window.__NUXT__=(function(a){return {products:[
      {id:1660028,title:"Сахар, 1 кг",sku:"1660028",url:"produkty-i-napitki\u002Fp-1660028-sahar",brand:{id:1,title:"Русский сахар"},specialPrice:{price:a},price:"100.00"},
      {id:1950692,title:"Печенье, 360 г",sku:"1950692",url:"produkty-i-napitki\u002Fp-1950692-pechene",brand:{id:2,title:"Orion"},price:"149.99"}
    ]}}}(null));</script></body></html>'''
    with TemporaryDirectory() as folder:
        path = Path(folder) / "fix-nuxt2.html"
        path.write_text(html, encoding="utf-8")
        rows = products_from_html(path)
    assert len(rows) == 2
    assert {row["id"]: row["цена_руб"] for row in rows} == {"1660028": "100", "1950692": "149.99"}
    assert next(row for row in rows if row["id"] == "1660028")["бренд"] == "Русский сахар"
    assert next(row for row in rows if row["id"] == "1660028")["ссылка"].startswith("https://fix-price.com/catalog/")


def test_fixprice_page_count_and_in_memory_parser():
    html = r'''<html><body><a href="?page=2">2</a><a href="?page=41">41</a>
    <script>window.__NUXT__=(function(){return {productsCount:"975",products:[
      {title:"Сок, 1 л",sku:"7",url:"produkty-i-napitki\u002Fp-7-sok",price:"99.00"}
    ]}}());</script></body></html>'''
    rows = products_from_html_text(html)
    pages, product_count = page_count_from_html(html, products_on_page=24)
    assert len(rows) == 1
    assert rows[0]["цена_руб"] == "99"
    assert pages == 41
    assert product_count == 975


def test_fixprice_browser_bundle():
    state = r'''<script>window.__NUXT__=(function(){return {products:[
      {title:"Чай, 25 пак.",sku:"77",url:"produkty-i-napitki\u002Fp-77-chay",price:"55.00"}
    ]}}());</script>'''
    bundle = {
        "format": "fixprice-pages-v1",
        "total_pages": 1,
        "pages": [{"url": "https://fix-price.com/catalog/produkty-i-napitki", "html": state}],
    }
    with TemporaryDirectory() as folder:
        path = Path(folder) / "fixprice.json"
        path.write_text(json.dumps(bundle, ensure_ascii=False), encoding="utf-8")
        rows, stats = products_from_htmls([path])
    assert len(rows) == 1
    assert rows[0]["id"] == "77"
    assert rows[0]["цена_руб"] == "55"
    assert stats["complete_capture"] is True
    assert stats["pages"] == 1


def test_nutrition_queue_import_and_cache():
    with TemporaryDirectory() as folder:
        output = Path(folder)
        build_catalog_files([
            {
                "магазин": "Хлеб&Соль", "магазин_id": "70307", "id": "1", "название": "Йогурт",
                "ссылка": "https://sbermarket.ru/products/123-yogurt", "цена_руб": "99",
            },
            {
                "магазин": "Fix Price", "магазин_id": "fix-price", "id": "2", "название": "Печенье",
                "ссылка": "https://fix-price.com/catalog/produkty/p-2-pechene", "цена_руб": "79",
            },
            {
                "магазин": "Слата", "магазин_id": "slata-online", "id": "3", "название": "Молоко",
                "ссылка": "https://shop.slata.com/catalog/moloko", "цена_руб": "89",
            },
        ], output)
        prepared = prepare_nutrition_queues(output)
        assert prepared["queues"] == {"kuper": 1, "fixprice": 1}
        assert prepared["unsupported"] == 1

        queue = json.loads(prepared["queue_paths"]["kuper"].read_text(encoding="utf-8"))
        entry = queue["entries"][0]
        package = {
            "format": "nutrition-batch-v1",
            "site": "kuper",
            "results": [{
                **entry,
                "status": "ok",
                "captured_at": "2026-10-03T12:00:00+00:00",
                "data": {
                    "белки": 4.2, "жиры": 3.1, "углеводы": 9.5, "ккал": 83,
                    "кбжу_на": "100 г", "источник_кбжу": "карточка Kuper",
                    "кбжу_статус": "проверено автоматически", "кбжу_парсер": PARSER_VERSION,
                    "состав": "Молоко, закваска",
                },
            }],
            "remaining": [],
        }
        package_path = output / "package.json"
        package_path.write_text(json.dumps(package, ensure_ascii=False), encoding="utf-8")
        imported = import_nutrition_results([package_path], output)
        assert imported["rows_updated"] == 1
        row = next(row for row in read_existing(output / "Все магазины.csv") if row["id"] == "1")
        assert row["белки"] == "4.2"
        assert row["ккал"] == "83"
        assert row["состав"] == "Молоко, закваска"
        assert row["источник_кбжу"] == "карточка Kuper"
        assert row["кбжу_парсер"] == PARSER_VERSION
        assert (output / "КБЖУ кэш.json").exists()

        prepared_again = prepare_nutrition_queues(output)
        assert prepared_again["queues"]["kuper"] == 0
        assert prepared_again["queues"]["fixprice"] == 1


def test_nutrition_validation_and_legacy_quarantine():
    assert nutrition_issue({"белки": 20, "жиры": 5.1, "углеводы": 6.9, "ккал": 151.8}) == ""
    assert nutrition_issue({"белки": 90, "жиры": 1, "углеводы": 60, "ккал": 1})
    assert "кДж" in nutrition_issue({"белки": 3, "жиры": 2.5, "углеводы": 4.7, "ккал": 223.4})

    with TemporaryDirectory() as folder:
        output = Path(folder)
        build_catalog_files([
            {
                "магазин": "Fix Price", "магазин_id": "fix-price", "id": "tea", "название": "Чай",
                "ссылка": "https://fix-price.com/catalog/produkty/p-tea", "белки": "90", "жиры": "1",
                "углеводы": "60", "ккал": "1", "источник_кбжу": "карточка Fix Price",
            },
            {
                "магазин": "Пятёрочка", "магазин_id": "5ka", "id": "milk", "название": "Молоко",
                "ссылка": "https://sbermarket.ru/products/milk", "белки": "3", "жиры": "2.5",
                "углеводы": "4.7", "ккал": "53", "источник_кбжу": "карточка Kuper",
            },
        ], output)
        prepared = prepare_nutrition_queues(output)
        assert prepared["quarantine"]["rows"] == 2
        assert prepared["quarantine"]["backup"].exists()
        assert prepared["quarantine"]["report"].exists()
        assert prepared["queues"] == {"kuper": 1, "fixprice": 1}
        rows = read_existing(output / "Все магазины.csv")
        assert all(row["белки"] == "" and row["ккал"] == "" for row in rows)
        assert all(row["кбжу_статус"].startswith("карантин:") for row in rows)


def test_old_nutrition_package_is_rejected():
    with TemporaryDirectory() as folder:
        output = Path(folder)
        build_catalog_files([{
            "магазин": "Fix Price", "магазин_id": "fix-price", "id": "1", "название": "Чай",
            "ссылка": "https://fix-price.com/catalog/produkty/p-1-chay",
        }], output)
        package = {
            "format": "nutrition-batch-v1", "site": "fixprice", "remaining": [],
            "results": [{
                "url": "https://fix-price.com/catalog/produkty/p-1-chay", "status": "ok",
                "refs": [{"магазин_id": "fix-price", "id": "1"}],
                "data": {"белки": 20, "жиры": 5.1, "углеводы": 6.9, "ккал": 151.8},
            }],
        }
        path = output / "old-package.json"
        path.write_text(json.dumps(package, ensure_ascii=False), encoding="utf-8")
        try:
            import_nutrition_results([path], output)
        except ValueError as exc:
            assert "Старые пакеты" in str(exc)
        else:
            raise AssertionError("Старый пакет КБЖУ был принят")


if __name__ == "__main__":
    test_extract_and_preserve_notes()
    test_extract_har_entities_and_deduplicate()
    test_real_category_beats_promotion()
    test_slata_nuxt_and_normalization()
    test_replace_store_preserves_manual_fields()
    test_fixprice_html_adapter()
    test_fixprice_nuxt2_prices()
    test_fixprice_page_count_and_in_memory_parser()
    test_fixprice_browser_bundle()
    test_nutrition_queue_import_and_cache()
    test_nutrition_validation_and_legacy_quarantine()
    test_old_nutrition_package_is_rejected()
    print("OK: извлечение и сохранение ручных полей")
