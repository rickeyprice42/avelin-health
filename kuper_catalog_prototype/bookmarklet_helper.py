"""Create a local drag-to-bookmarks installer for a JavaScript collector."""
from __future__ import annotations

import html
from pathlib import Path


def create_installer(script_path, output_path, title, steps):
    source = Path(script_path).read_text(encoding="utf-8")
    # Bookmark URLs must be a single line. Chromium-based browsers may silently
    # truncate a multi-line javascript: URL or let a // comment hide its tail.
    script = " ".join(
        line.strip()
        for line in source.splitlines()
        if line.strip() and not line.lstrip().startswith("//")
    )
    href = html.escape("javascript:" + script, quote=True)
    steps_html = "\n".join(f"<li>{html.escape(step)}</li>" for step in steps)
    document = f'''<!doctype html>
<html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(title)}</title><style>
body{{max-width:820px;margin:55px auto;padding:0 24px;font:18px/1.55 system-ui;color:#17212b}}
h1{{font-size:34px;margin-bottom:8px}}.button{{display:inline-block;margin:20px 0;padding:15px 24px;border-radius:12px;
background:#16a05d;color:white;font-weight:750;text-decoration:none;box-shadow:0 8px 24px #168b5140}}
.note{{padding:16px 20px;border-radius:12px;background:#f1f5f7}}
</style></head><body><h1>{html.escape(title)}</h1>
<p>Перетащите зелёную кнопку мышью на панель закладок браузера:</p>
<a class="button" href="{href}">{html.escape(title)}</a>
<ol>{steps_html}</ol>
<p class="note">Сбор выполняется внутри текущей вкладки. Cookies и служебные токены в скачиваемый файл не записываются.</p>
</body></html>'''
    output = Path(output_path)
    output.write_text(document, encoding="utf-8")
    return output
