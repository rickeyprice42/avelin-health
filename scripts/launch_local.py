"""One-click local web development launcher. No third-party Python dependencies."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import queue
import shutil
import socket
import sqlite3
import subprocess
import sys
import threading
import time
import urllib.request
import webbrowser

ROOT = Path(__file__).resolve().parents[1]
LOCAL = ROOT / ".local"
URL = "http://127.0.0.1:4173"
API = "http://127.0.0.1:8765"
HTTP = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def read_url(url):
    with HTTP.open(url, timeout=5) as response:
        return response.read().decode("utf-8")


def api_ready():
    try:
        status = json.loads(read_url(API + "/api/status"))
        return status.get("ok") is True and status.get("app") == "avelin-health"
    except (OSError, ValueError):
        return False


def web_ready():
    try:
        return "<title>Avelin Health</title>" in read_url(URL) and "/@vite/client" in read_url(URL)
    except (OSError, ValueError):
        return False


def listening(port):
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.3):
            return True
    except OSError:
        return False


def runtime_paths():
    path = LOCAL / "launcher.json"
    config = json.loads(path.read_text(encoding="utf-8-sig")) if path.exists() else {}
    python = Path(config.get("python") or sys.executable)
    if python.name.lower() == "pythonw.exe":
        python = python.with_name("python.exe")
    node = config.get("node") or shutil.which("node")
    if not python.is_file() or not node or not Path(node).is_file():
        raise RuntimeError("Python или Node.js не найден. Повтори scripts/install_launcher.ps1.")
    return str(python), str(node)


class SessionLock:
    """OS lock is released automatically even if the launcher crashes."""
    def __init__(self):
        self.handle = None

    def acquire(self):
        LOCAL.mkdir(exist_ok=True)
        self.handle = (LOCAL / "launcher.lock").open("a+b")
        self.handle.seek(0, 2)
        if self.handle.tell() == 0:
            self.handle.write(b"0")
            self.handle.flush()
        self.handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(self.handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.handle.close()
            self.handle = None
            return False
        return True

    def close(self):
        if self.handle:
            self.handle.close()
            self.handle = None


class Services:
    def __init__(self):
        self.processes = []
        self.logs = []
        self.cancel = threading.Event()
        self.reused = False

    def validate(self):
        python, node = runtime_paths()
        if not (ROOT / "node_modules/vite/bin/vite.js").is_file():
            raise RuntimeError("Нет зависимостей frontend. Выполни pnpm install --frozen-lockfile.")
        db = ROOT / "data/avelin-health.db"
        if not db.is_file() or not (ROOT / "public/data/health-summary.json").is_file():
            raise RuntimeError("Сначала импортируй данные Apple Health и каталог по инструкции README.")
        with sqlite3.connect(db.as_uri() + "?mode=ro", uri=True) as conn:
            tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        required = {"samples", "daily_metrics", "user_profile", "body_measurements", "catalog_products"}
        if not required.issubset(tables):
            raise RuntimeError("База не подготовлена. Повтори импорт Health и каталога по README.")
        return python, node

    def spawn(self, name, args, env):
        logdir = LOCAL / "logs"
        logdir.mkdir(parents=True, exist_ok=True)
        # Append preserves the preceding crash when the user restarts the app.
        log = (logdir / (name + ".log")).open("ab", buffering=0)
        log.write(("\n--- " + time.strftime("%Y-%m-%d %H:%M:%S") + " ---\n").encode())
        self.logs.append(log)
        flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        process = subprocess.Popen(
            args, cwd=ROOT, env=env, stdin=subprocess.DEVNULL,
            stdout=log, stderr=subprocess.STDOUT, creationflags=flags,
        )
        self.processes.append(process)

    def wait_ready(self, ready, label):
        deadline = time.monotonic() + 40
        while time.monotonic() < deadline:
            if self.cancel.is_set():
                raise RuntimeError("Запуск отменён.")
            if any(p.poll() is not None for p in self.processes):
                raise RuntimeError(label + ": процесс завершился. Подробности в логах.")
            if ready():
                return
            self.cancel.wait(0.25)
        raise RuntimeError(label + ": время ожидания истекло. Подробности в логах.")

    def start(self):
        self.reused = False
        python, node = self.validate()
        occupied = [port for port in (8765, 4173) if listening(port)]
        if occupied:
            if len(occupied) == 2 and api_ready() and web_ready():
                self.reused = True
                return
            raise RuntimeError(
                "Порт " + ", ".join(map(str, occupied)) +
                " уже занят. Закрой прежний сервер или приложение, занявшее порт, и повтори запуск."
            )
        env = os.environ.copy()
        env["AVELIN_PORT"] = "8765"
        env["PYTHONUTF8"] = "1"
        env["PYTHONUNBUFFERED"] = "1"
        env["PATH"] = str(Path(node).parent) + os.pathsep + env.get("PATH", "")
        try:
            self.spawn("backend", [python, "-u", str(ROOT / "scripts/local_server.py")], env)
            self.wait_ready(api_ready, "Backend")
            self.spawn("frontend", [
                node, str(ROOT / "node_modules/vite/bin/vite.js"),
                "--host", "127.0.0.1", "--port", "4173", "--strictPort",
            ], env)
            self.wait_ready(web_ready, "Frontend")
        except BaseException:
            self.stop()
            raise

    def stop(self):
        # Only Popen handles created by this launcher are stopped; never kill by port or name.
        for process in reversed(self.processes):
            if process.poll() is None:
                process.terminate()
        for process in reversed(self.processes):
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
        self.processes.clear()
        for log in self.logs:
            log.close()
        self.logs.clear()


def gui(services):
    import tkinter as tk
    from tkinter import messagebox

    app = tk.Tk()
    app.title("Avelin Health — локальный запуск")
    app.geometry("570x310")
    app.resizable(False, False)
    app.configure(bg="#101b1a")
    status = tk.StringVar(value="Подготовка к запуску…")
    note = tk.StringVar(value=URL)
    events = queue.Queue()
    state = {"busy": False, "running": False, "closing": False}
    tk.Label(app, text="Avelin Health", font=("Segoe UI", 22, "bold"),
             bg="#101b1a", fg="#7ce1bc").pack(pady=(20, 8))
    tk.Label(app, textvariable=status, font=("Segoe UI", 11), wraplength=525,
             bg="#101b1a", fg="white").pack(pady=8)
    tk.Label(app, textvariable=note, wraplength=525,
             bg="#101b1a", fg="#b0c7c1").pack(pady=5)
    buttons = tk.Frame(app, bg="#101b1a")
    buttons.pack(pady=14)

    def start():
        if state["busy"] or state["running"]:
            return
        state["busy"] = True
        services.cancel.clear()
        status.set("Запускаю backend и интерфейс…")
        start_button.config(state="disabled")
        def worker():
            try:
                services.start()
                events.put(("ready", ""))
            except Exception as exc:
                events.put(("error", str(exc)))
        threading.Thread(target=worker, daemon=True).start()

    def stop():
        if state["busy"]:
            services.cancel.set()
            return
        services.stop()
        state["running"] = False
        status.set("Сайт остановлен." if not services.reused else "Внешний сервер продолжает работать.")
        note.set("Можно запустить снова или закрыть это окно.")
        start_button.config(state="normal")
        open_button.config(state="disabled")

    def logs():
        folder = LOCAL / "logs"
        folder.mkdir(parents=True, exist_ok=True)
        os.startfile(str(folder))

    def close():
        state["closing"] = True
        services.cancel.set()

    start_button = tk.Button(buttons, text="Запустить", command=start, width=12)
    start_button.grid(row=0, column=0, padx=4)
    open_button = tk.Button(buttons, text="Открыть сайт", command=lambda: webbrowser.open(URL),
                            width=13, state="disabled")
    open_button.grid(row=0, column=1, padx=4)
    tk.Button(buttons, text="Логи", command=logs, width=8).grid(row=0, column=2, padx=4)
    tk.Button(buttons, text="Остановить", command=stop, width=12).grid(row=0, column=3, padx=4)
    tk.Label(app, text="Изменения интерфейса видны без пересборки.\n"
             "Закрытие окна останавливает запущенные им серверы.",
             bg="#101b1a", fg="#b0c7c1").pack(pady=6)

    def tick():
        while not events.empty():
            kind, text = events.get_nowait()
            state["busy"] = False
            if kind == "ready":
                state["running"] = True
                status.set("Сайт работает — можно тестировать.")
                try:
                    cloud = json.loads(read_url(API + "/api/status")).get("llmConfigured")
                except (OSError, ValueError):
                    cloud = False
                mode = "Облачный ИИ настроен" if cloud else "Чат: локальный режим без API-ключа"
                note.set(mode + ("\nСервер запущен отдельно и не будет остановлен этим окном."
                                  if services.reused else "\n" + URL))
                open_button.config(state="normal")
                if not state["closing"]:
                    webbrowser.open(URL)
            else:
                status.set(text)
                note.set("Кнопка «Логи» открывает подробности запуска.")
                start_button.config(state="normal")
        if state["closing"] and not state["busy"]:
            services.stop()
            app.destroy()
            return
        if state["running"] and any(p.poll() is not None for p in services.processes):
            services.stop()
            state["running"] = False
            status.set("Один из серверов завершился. Открой логи и повтори запуск.")
            start_button.config(state="normal")
            open_button.config(state="disabled")
        app.after(300, tick)

    app.protocol("WM_DELETE_WINDOW", close)
    app.after(100, start)
    app.after(300, tick)
    try:
        app.mainloop()
    finally:
        services.cancel.set()
        services.stop()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true",
                        help="Start, verify HTTP readiness and stop without a GUI or browser.")
    args = parser.parse_args()
    lock = SessionLock()
    if not lock.acquire():
        if args.check:
            raise SystemExit("Launcher already running.")
        if api_ready() and web_ready():
            webbrowser.open(URL)
        else:
            from tkinter import messagebox
            messagebox.showinfo("Avelin Health", "Окно запуска уже открыто. Дождись завершения запуска в нём.")
        return
    services = Services()
    try:
        if args.check:
            services.start()
            services.wait_ready(api_ready, "Backend verification")
            services.wait_ready(web_ready, "Frontend verification")
            print(json.dumps({"api": True, "web": True, "reused": services.reused}))
        else:
            gui(services)
    finally:
        services.stop()
        lock.close()


if __name__ == "__main__":
    main()
