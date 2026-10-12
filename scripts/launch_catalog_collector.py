"""Start the loopback collector with a Python runtime that has Excel support."""
import argparse
import html
import json
import secrets
import subprocess
import sys
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def runtime():
    bundled = Path.home() / ".cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe"
    candidates = [ROOT / ".venv/Scripts/python.exe", Path(sys.executable), bundled]
    for candidate in candidates:
        if candidate.is_file() and subprocess.run([str(candidate), "-c", "import openpyxl"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0:
            return candidate
    raise RuntimeError("Установите зависимости: python -m pip install -r kuper_catalog_prototype/requirements.txt")

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=ROOT / "Каталоги магазинов")
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    python = runtime()
    if args.dry_run:
        print(f"Python: {python}\nКаталоги: {args.output.resolve()}")
        return
    local = ROOT / ".local"
    local.mkdir(exist_ok=True)
    config_path = local / "catalog-collector.json"
    config = json.loads(config_path.read_text(encoding="utf-8")) if config_path.exists() else {"token": secrets.token_urlsafe(32)}
    config_path.write_text(json.dumps(config), encoding="utf-8")
    extension = ROOT / "kuper_catalog_prototype/extension"
    setup = local / "Ночной сбор каталога.html"
    setup.write_text(f'''<!doctype html><meta charset="utf-8"><title>Ночной сбор Avelin</title>
<style>body{{max-width:800px;margin:50px auto;font:17px/1.7 system-ui;padding:20px}}code{{overflow-wrap:anywhere;background:#edf6ef;padding:5px}}h1{{color:#23734d}}</style>
<h1>Ночной сбор Avelin</h1><ol><li>В Opera GX откройте <code>opera://extensions</code>, включите режим разработчика и выберите «Загрузить распакованное расширение».</li>
<li>Выберите папку <code>{html.escape(str(extension))}</code>.</li>
<li>Откройте окно расширения, вставьте ключ ниже и нажмите «Проверить подключение».</li>
<li>Откройте выбранные магазины Kuper и Fix Price, проверьте адрес доставки. Отметьте вкладки в расширении и нажмите «Обновить товары → собрать КБЖУ».</li></ol>
<p>Ключ только для локального помощника (не публикуйте):</p><code>{html.escape(config['token'])}</code>
<p>Результаты: <code>{html.escape(str(args.output.resolve()))}</code></p>
<p>Оставьте браузер, рабочие вкладки и окно помощника открытыми; компьютер не должен уйти в сон. После остановки используйте «Продолжить сохранённый сбор». КБЖУ Слаты пока не доступны в её каталожном источнике.</p>''', encoding="utf-8")
    subprocess.run([str(python), str(ROOT / "kuper_catalog_prototype/build_extension.py")], check=True)
    if not args.no_browser: webbrowser.open(setup.as_uri())
    subprocess.run([str(python), str(ROOT / "kuper_catalog_prototype/catalog_companion.py"), "--output", str(args.output)], check=True)

if __name__ == "__main__": main()
