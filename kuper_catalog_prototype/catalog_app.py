"""Small Windows interface for importing store HAR files and exporting catalogues."""
from __future__ import annotations

import asyncio
import os
import queue
import threading
import webbrowser
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from bookmarklet_helper import create_installer
from catalog_export import build_catalog_files
from fixprice_parser import products_from_htmls
from kuper_parser import products_from_hars
from nutrition_enrichment import import_nutrition_results, prepare_nutrition_queues
from slata_parser import collect_slata_products


STORE_URLS = {
    "Kuper": "https://web.kuper.ru/",
    "Бристоль": "https://bristol.ru/catalog",
    "Слата": "https://shop.slata.com/catalog",
    "Красное&Белое": "https://krasnoeibeloe.ru/catalog/",
    "Fix Price": "https://fix-price.com/catalog",
}


class CatalogApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Каталоги магазинов")
        self.geometry("1040x680")
        self.minsize(760, 540)
        self.har_paths = []
        self.events = queue.Queue()
        self.output_dir = tk.StringVar(value=str(Path.home() / "Desktop" / "Каталоги магазинов"))
        self.status = tk.StringVar(value="Добавьте HAR-файлы и нажмите «Импортировать».")
        self._build_ui()
        self.after(150, self._poll_events)

    def _build_ui(self):
        root = ttk.Frame(self, padding=18)
        root.pack(fill="both", expand=True)
        ttk.Label(root, text="Каталоги магазинов", font=("Segoe UI", 18, "bold")).pack(anchor="w")
        ttk.Label(root, text="Сбор каталогов, точных КБЖУ из карточек и выгрузка CSV/XLSX по магазинам.").pack(anchor="w", pady=(2, 14))

        files_box = ttk.LabelFrame(root, text="HAR-файлы", padding=10)
        files_box.pack(fill="both", expand=True)
        self.listbox = tk.Listbox(files_box, height=12, selectmode=tk.EXTENDED)
        self.listbox.pack(side="left", fill="both", expand=True)
        scrollbar = ttk.Scrollbar(files_box, orient="vertical", command=self.listbox.yview)
        scrollbar.pack(side="left", fill="y")
        self.listbox.configure(yscrollcommand=scrollbar.set)
        buttons = ttk.Frame(files_box)
        buttons.pack(side="left", fill="y", padx=(10, 0))
        ttk.Button(buttons, text="Добавить HAR", command=self.add_files).pack(fill="x", pady=(0, 6))
        ttk.Button(buttons, text="Добавить папку", command=self.add_folder).pack(fill="x", pady=6)
        ttk.Button(buttons, text="Удалить выбранное", command=self.remove_selected).pack(fill="x", pady=6)
        ttk.Button(buttons, text="Очистить", command=self.clear_files).pack(fill="x", pady=6)

        output_box = ttk.LabelFrame(root, text="Папка результатов", padding=10)
        output_box.pack(fill="x", pady=12)
        ttk.Entry(output_box, textvariable=self.output_dir).pack(side="left", fill="x", expand=True)
        ttk.Button(output_box, text="Выбрать", command=self.choose_output).pack(side="left", padx=(8, 0))
        ttk.Button(output_box, text="Открыть", command=self.open_output).pack(side="left", padx=(8, 0))

        actions = ttk.Frame(root)
        actions.pack(fill="x")
        action_buttons = ttk.Frame(actions)
        action_buttons.pack(fill="x")
        self.import_button = ttk.Button(action_buttons, text="Импортировать HAR", command=self.start_import)
        self.import_button.pack(side="left")
        self.kuper_auto_button = ttk.Button(
            action_buttons, text="Настроить автосбор Kuper", command=self.start_kuper_auto
        )
        self.kuper_auto_button.pack(side="left", padx=(8, 0))
        self.slata_button = ttk.Button(action_buttons, text="Обновить Слату автоматически", command=self.start_slata)
        self.slata_button.pack(side="left", padx=(8, 0))
        fix_buttons = ttk.Frame(actions)
        fix_buttons.pack(fill="x", pady=(8, 0))
        self.fixprice_auto_button = ttk.Button(
            fix_buttons, text="Настроить автосбор Fix Price", command=self.start_fixprice_auto
        )
        self.fixprice_auto_button.pack(side="left")
        self.fixprice_button = ttk.Button(fix_buttons, text="Импорт Fix Price", command=self.start_fixprice)
        self.fixprice_button.pack(side="left", padx=(8, 0))
        nutrition_buttons = ttk.Frame(actions)
        nutrition_buttons.pack(fill="x", pady=(8, 0))
        self.nutrition_prepare_button = ttk.Button(
            nutrition_buttons, text="Подготовить сбор КБЖУ", command=self.start_nutrition_prepare
        )
        self.nutrition_prepare_button.pack(side="left")
        self.nutrition_import_button = ttk.Button(
            nutrition_buttons, text="Импорт КБЖУ", command=self.start_nutrition_import
        )
        self.nutrition_import_button.pack(side="left", padx=(8, 0))
        progress_row = ttk.Frame(actions)
        progress_row.pack(fill="x", pady=(8, 0))
        self.progress = ttk.Progressbar(progress_row, mode="indeterminate", length=220)
        self.progress.pack(side="left")
        ttk.Label(progress_row, textvariable=self.status).pack(side="left", fill="x", expand=True, padx=(12, 0))

        sites = ttk.LabelFrame(root, text="Открыть каталог", padding=10)
        sites.pack(fill="x", pady=(12, 0))
        for name, url in STORE_URLS.items():
            ttk.Button(sites, text=name, command=lambda target=url: webbrowser.open(target)).pack(side="left", padx=(0, 8))

    def add_files(self):
        paths = filedialog.askopenfilenames(title="Выберите HAR", filetypes=[("HAR", "*.har"), ("Все файлы", "*.*")])
        self._add_paths(paths)

    def add_folder(self):
        folder = filedialog.askdirectory(title="Папка с HAR")
        if folder:
            self._add_paths(sorted(str(x) for x in Path(folder).glob("*.har")))

    def _add_paths(self, paths):
        existing = {str(x).casefold() for x in self.har_paths}
        for value in paths:
            path = Path(value)
            if path.suffix.casefold() == ".har" and str(path).casefold() not in existing:
                self.har_paths.append(path)
                self.listbox.insert(tk.END, str(path))
                existing.add(str(path).casefold())
        self.status.set(f"Выбрано HAR-файлов: {len(self.har_paths)}")

    def remove_selected(self):
        for index in reversed(self.listbox.curselection()):
            self.listbox.delete(index)
            del self.har_paths[index]
        self.status.set(f"Выбрано HAR-файлов: {len(self.har_paths)}")

    def clear_files(self):
        self.har_paths.clear()
        self.listbox.delete(0, tk.END)
        self.status.set("Список очищен.")

    def choose_output(self):
        folder = filedialog.askdirectory(title="Папка результатов", initialdir=self.output_dir.get())
        if folder:
            self.output_dir.set(folder)

    def open_output(self):
        path = Path(self.output_dir.get())
        path.mkdir(parents=True, exist_ok=True)
        os.startfile(path)

    def start_import(self):
        if not self.har_paths:
            messagebox.showwarning("Нет файлов", "Сначала добавьте хотя бы один HAR-файл.")
            return
        self._set_busy(True)
        self.progress.start(10)
        self.status.set("Читаю HAR. Большие файлы могут обрабатываться несколько минут…")
        threading.Thread(target=self._import_worker, daemon=True).start()

    def start_kuper_auto(self):
        helper = Path(__file__).with_name("Kuper — автосбор.html")
        create_installer(
            Path(__file__).with_name("kuper_bookmarklet.js"),
            helper,
            "Собрать Kuper",
            [
                "Откройте в обычном браузере Пятёрочку или Хлеб&Соль на web.kuper.ru и проверьте адрес.",
                "Нажмите закладку, затем один раз выберите любую продуктовую категорию в левом меню.",
                "Дождитесь скачивания файла с окончанием .complete.har.",
                "Добавьте этот HAR в программу и нажмите «Импортировать HAR».",
            ],
        )
        webbrowser.open(helper.resolve().as_uri())
        self.status.set("Открыта установка закладки автосбора Kuper.")
        messagebox.showinfo(
            "Автосбор Kuper",
            "Перетащите зелёную кнопку на панель закладок браузера. Закладка подходит и для Пятёрочки, "
            "и для Хлеб&Соли. Подробные шаги показаны на открывшейся странице.",
        )

    def start_slata(self):
        self._set_busy(True)
        self.progress.start(10)
        self.status.set("Запускаю автоматический сбор «Слаты». Это может занять несколько минут…")
        threading.Thread(target=self._slata_worker, daemon=True).start()

    def start_fixprice(self):
        paths = filedialog.askopenfilenames(
            title="Выберите сохранённые страницы Fix Price",
            filetypes=[("Fix Price", "*.json *.html *.htm"), ("Все файлы", "*.*")],
        )
        if not paths:
            return
        self._set_busy(True)
        self.progress.start(10)
        self.status.set(f"Читаю данные Fix Price: {len(paths)} файл(а/ов)…")
        threading.Thread(target=self._fixprice_worker, args=(paths,), daemon=True).start()

    def start_fixprice_auto(self):
        helper = Path(__file__).with_name("Fix Price — автосбор.html")
        webbrowser.open(helper.resolve().as_uri())
        self.status.set("Открыта установка закладки автосбора Fix Price.")
        messagebox.showinfo(
            "Автосбор Fix Price",
            "Открыта страница-помощник. Перетащите зелёную кнопку в панель закладок Opera GX.\n\n"
            "Затем откройте каталог Fix Price и нажмите эту закладку. Браузер сам соберёт страницы и "
            "скачает один JSON-файл; импортируйте его кнопкой «Импорт Fix Price».",
        )

    def start_nutrition_prepare(self):
        self._set_busy(True)
        self.progress.start(10)
        self.status.set("Готовлю очереди карточек Kuper и Fix Price…")
        threading.Thread(target=self._nutrition_prepare_worker, daemon=True).start()

    def start_nutrition_import(self):
        paths = filedialog.askopenfilenames(
            title="Выберите накопленные пакеты КБЖУ",
            filetypes=[("Пакеты КБЖУ", "*.json"), ("Все файлы", "*.*")],
        )
        if not paths:
            return
        self._set_busy(True)
        self.progress.start(10)
        self.status.set(f"Импортирую КБЖУ из {len(paths)} пакет(а/ов)…")
        threading.Thread(target=self._nutrition_import_worker, args=(paths,), daemon=True).start()

    def _set_busy(self, busy):
        state = "disabled" if busy else "normal"
        self.import_button.configure(state=state)
        self.kuper_auto_button.configure(state=state)
        self.slata_button.configure(state=state)
        self.fixprice_auto_button.configure(state=state)
        self.fixprice_button.configure(state=state)
        self.nutrition_prepare_button.configure(state=state)
        self.nutrition_import_button.configure(state=state)

    def _nutrition_prepare_worker(self):
        try:
            output_dir = Path(self.output_dir.get())
            stats = prepare_nutrition_queues(output_dir)
            helper = Path(__file__).with_name("КБЖУ — автосбор.html")
            create_installer(
                Path(__file__).with_name("nutrition_bookmarklet.js"),
                helper,
                "Собрать КБЖУ",
                [
                    "Перетащите зелёную кнопку на панель закладок обычного браузера.",
                    "Для Kuper откройте обычный каталог web.kuper.ru, нажмите закладку и выберите очередь Kuper.",
                    "Закладка откроет публичную карточку kuper.ru; на ней нажмите закладку ещё раз и повторно выберите ту же очередь.",
                    "Для Fix Price откройте fix-price.com, нажмите закладку и выберите очередь Fix Price.",
                    "Сначала закладка проверит 8 карточек. Если КБЖУ не читаются, она остановится сама и скачает диагностический JSON.",
                    "Если проверка успешна, дождитесь скачивания пакета, не закрывая вкладку.",
                    "Если в пакете остались карточки, снова нажмите закладку и выберите уже скачанный пакет — результаты накопятся.",
                    "Готовый пакет загрузите кнопкой «Импорт КБЖУ» в программе.",
                ],
            )
            report_lines = [
                "Подготовка сбора КБЖУ",
                f"Товаров в общем каталоге: {stats['rows']}",
                f"Уже заполнено: {stats['already_filled']}",
                f"Заполнено из локального кэша: {stats['cached_applied']}",
                f"Карточек в очереди Kuper: {stats['queues']['kuper']}",
                f"Карточек в очереди Fix Price: {stats['queues']['fixprice']}",
                f"Пока без поддерживаемой карточки: {stats['unsupported']}",
                f"Старых КБЖУ перенесено в карантин: {stats['quarantine']['rows']}",
                f"Удалено записей старого кэша: {stats['quarantine']['cache_removed']}",
                "",
                f"Kuper: {stats['queue_paths']['kuper']}",
                f"Fix Price: {stats['queue_paths']['fixprice']}",
            ]
            output_dir.mkdir(parents=True, exist_ok=True)
            (output_dir / "Отчёт КБЖУ.txt").write_text("\n".join(report_lines), encoding="utf-8-sig")
            self.events.put(("nutrition_prepared", stats, helper))
        except Exception as exc:
            self.events.put(("error", str(exc)))

    def _nutrition_import_worker(self, paths):
        try:
            output_dir = Path(self.output_dir.get())
            stats = import_nutrition_results(paths, output_dir)
            report_lines = [
                "Импорт КБЖУ",
                f"Успешных карточек в пакетах: {stats['cards']}",
                f"Строк каталога обновлено: {stats['rows_updated']}",
                f"Пропущено записей: {stats['skipped']}",
                f"Отклонено проверкой безопасности: {stats['rejected']}",
                f"Осталось карточек в выбранных пакетах: {stats['remaining']}",
                f"Кэш: {stats['cache']}",
            ]
            (output_dir / "Отчёт КБЖУ.txt").write_text("\n".join(report_lines), encoding="utf-8-sig")
            self.events.put(("nutrition_done", stats))
        except Exception as exc:
            self.events.put(("error", str(exc)))

    def _slata_worker(self):
        try:
            items, stats = asyncio.run(collect_slata_products(
                progress=lambda message: self.events.put(("progress", message))
            ))
            if not items:
                raise ValueError("«Слата» не вернула товары.")
            output_dir = Path(self.output_dir.get())
            files = build_catalog_files(items, output_dir, replace_stores=True)
            report_lines = [
                "Автоматический сбор «Слаты»",
                f"Категорий: {stats['categories']}",
                f"Страниц: {stats['pages']}",
                f"Товарных записей: {stats['observed']}",
                f"Уникальных товаров: {stats['unique']}",
                f"Дубликатов между категориями: {stats['duplicates']}",
            ]
            (output_dir / "Отчёт Слата.txt").write_text("\n".join(report_lines), encoding="utf-8-sig")
            self.events.put(("slata_done", stats, files))
        except Exception as exc:
            self.events.put(("error", str(exc)))

    def _fixprice_worker(self, paths):
        try:
            items, stats = products_from_htmls(paths)
            if not items:
                raise ValueError(
                    "В HTML не найдены карточки Fix Price. Сохраните полностью загруженную страницу каталога из обычного Edge."
                )
            output_dir = Path(self.output_dir.get())
            files = build_catalog_files(items, output_dir, replace_stores=stats.get("complete_capture", False))
            report_lines = [
                "Импорт Fix Price",
                f"Файлов: {stats['files']}",
                f"Страниц: {stats['pages']}",
                f"Уникальных товаров: {stats['unique']}",
                f"Товаров с ценой: {stats['priced']}",
                f"Товаров без цены: {stats['missing_prices']}",
                f"Дубликатов: {stats['duplicates']}",
                "",
                "Файлы:",
            ]
            report_lines.extend(f"- {item['path']}: {item['products']}" for item in stats["loaded"])
            (output_dir / "Отчёт Fix Price.txt").write_text("\n".join(report_lines), encoding="utf-8-sig")
            self.events.put(("fixprice_done", stats, files))
        except Exception as exc:
            self.events.put(("error", str(exc)))

    def _import_worker(self):
        try:
            items, stats = products_from_hars(list(self.har_paths))
            if not items:
                raise ValueError("В выбранных HAR не найдены поддерживаемые ответы каталога Kuper.")
            output_dir = Path(self.output_dir.get())
            files = build_catalog_files(items, output_dir, replace_stores=stats.get("complete_capture", False))
            report_lines = [
                f"HAR-файлов: {stats['files']}",
                f"Уникальных товаров: {stats['unique']}",
                f"Полный автосбор: {'да' if stats.get('complete_capture') else 'нет'}",
                "",
                "Магазины:",
            ]
            report_lines.extend(f"- {store}: {count}" for store, count in sorted(stats["stores"].items()))
            report_lines.append("")
            report_lines.append("Неполные категории:")
            if stats["incomplete_categories"]:
                for warning in stats["incomplete_categories"]:
                    pages = ", ".join(str(x) for x in warning["missing_pages"])
                    report_lines.append(f"- {warning['store']} — {warning['category']}: нет страниц {pages} из {warning['total_pages']}")
            else:
                report_lines.append("- не обнаружены")
            (output_dir / "Отчёт импорта.txt").write_text("\n".join(report_lines), encoding="utf-8-sig")
            self.events.put(("done", stats, files))
        except Exception as exc:
            self.events.put(("error", str(exc)))

    def _poll_events(self):
        try:
            event = self.events.get_nowait()
        except queue.Empty:
            self.after(150, self._poll_events)
            return
        if event[0] == "progress":
            self.status.set(event[1])
            self.after(150, self._poll_events)
            return
        self.progress.stop()
        self._set_busy(False)
        if event[0] == "error":
            self.status.set("Операция не выполнена.")
            messagebox.showerror("Ошибка импорта", event[1])
        elif event[0] == "slata_done":
            _, stats, files = event
            text = (
                f"Готово: {stats['unique']} уникальных товаров «Слаты».\n"
                f"Загружено страниц: {stats['pages']}.\n"
                f"Общий каталог: {files['combined']['rows']} товаров."
            )
            self.status.set(f"Слата обновлена: {stats['unique']} товаров.")
            messagebox.showinfo("Слата обновлена", text)
        elif event[0] == "fixprice_done":
            _, stats, files = event
            text = (
                f"Готово: {stats['unique']} уникальных товаров Fix Price.\n"
                f"С ценой: {stats['priced']}; без цены: {stats['missing_prices']}.\n"
                f"Файлов: {stats['files']}; страниц: {stats['pages']}.\n"
                f"Общий каталог: {files['combined']['rows']} товаров."
            )
            self.status.set(f"Fix Price импортирован: {stats['unique']} товаров.")
            messagebox.showinfo("Fix Price импортирован", text)
        elif event[0] == "nutrition_prepared":
            _, stats, helper = event
            webbrowser.open(helper.resolve().as_uri())
            text = (
                f"Очереди готовы.\n\n"
                f"Kuper: {stats['queues']['kuper']} карточек.\n"
                f"Fix Price: {stats['queues']['fixprice']} карточек.\n"
                f"Из кэша заполнено: {stats['cached_applied']}.\n\n"
                f"Старых КБЖУ перенесено в карантин: {stats['quarantine']['rows']}.\n"
                "Открыта страница установки обновлённой зелёной закладки «Собрать КБЖУ». "
                "Файлы очередей лежат в папке результатов."
            )
            self.status.set("Очереди КБЖУ готовы; открыта установка закладки.")
            messagebox.showinfo("Сбор КБЖУ подготовлен", text)
        elif event[0] == "nutrition_done":
            _, stats = event
            text = (
                f"КБЖУ добавлены в {stats['rows_updated']} строк каталога.\n"
                f"Успешных карточек: {stats['cards']}.\n"
                f"Отклонено строгой проверкой: {stats['rejected']}.\n"
                f"Осталось в пакетах: {stats['remaining']}.\n\n"
                "CSV и Excel обновлены; точные значения сохранены в локальном кэше."
            )
            self.status.set(f"КБЖУ обновлены: {stats['rows_updated']} товаров.")
            messagebox.showinfo("КБЖУ импортированы", text)
        else:
            _, stats, files = event
            lines = [f"Готово: {files['combined']['rows']} товаров."]
            for store, info in files["stores"].items():
                lines.append(f"{store}: {info['rows']}")
            if stats["incomplete_categories"]:
                lines.append(f"Предупреждений о неполных категориях: {len(stats['incomplete_categories'])}")
            text = "\n".join(lines)
            self.status.set(lines[0])
            messagebox.showinfo("Импорт завершён", text)
        self.after(150, self._poll_events)


if __name__ == "__main__":
    CatalogApp().mainloop()
