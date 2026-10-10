"""Local Avelin API and production static server. Standard library only."""
from __future__ import annotations

import json
import mimetypes
import os
import sqlite3
import sys
import urllib.error
import urllib.request
from contextlib import contextmanager
from datetime import datetime
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT=Path(__file__).resolve().parents[1]
DB=ROOT/"data"/"avelin-health.db"
DIST=ROOT/"dist"
sys.path.insert(0,str(ROOT/"scripts"))
from agent_tools import TOOLS, TOOL_SCHEMAS, get_health_summary, get_nutrition_gap, search_store_products

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

@contextmanager
def connect():
    conn=sqlite3.connect(DB)
    conn.row_factory=sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()

def ensure_profile_schema():
    with connect() as conn:
        columns={r[1] for r in conn.execute("PRAGMA table_info(user_profile)")}
        additions={"lunch_time":"TEXT","cooking_minutes":"INTEGER","allergies":"TEXT","preferred_stores":"TEXT"}
        for name,kind in additions.items():
            if name not in columns: conn.execute(f"ALTER TABLE user_profile ADD COLUMN {name} {kind}")
        conn.execute("INSERT OR IGNORE INTO user_profile(id) VALUES(1)")

def profile_get():
    with connect() as conn:
        row=conn.execute("SELECT * FROM user_profile WHERE id=1").fetchone()
        latest={r["kind"]:r["value"] for r in conn.execute("""SELECT b.kind,b.value FROM body_measurements b JOIN
          (SELECT kind,MAX(measured_at) measured_at FROM body_measurements GROUP BY kind) x
          ON b.kind=x.kind AND b.measured_at=x.measured_at""")}
    return {"height":row["height_cm"] or "","waist":latest.get("waist_cm","") ,"biceps":latest.get("biceps_cm","") ,
      "goal":row["goal"] or "","lunchTime":row["lunch_time"] or "13:00","cookMinutes":row["cooking_minutes"] or 20,
      "allergies":row["allergies"] or "","stores":json.loads(row["preferred_stores"] or "[]"),"updatedAt":row["updated_at"]}

def positive(value):
    try:
        n=float(value); return n if n>0 else None
    except (TypeError,ValueError): return None

def profile_put(data):
    height=positive(data.get("height")); now=datetime.now().astimezone().isoformat(timespec="seconds")
    stores=[s for s in data.get("stores",[]) if s in {"Пятёрочка","Слата","Хлеб&Соль","Fix Price"}]
    with connect() as conn:
        conn.execute("""UPDATE user_profile SET height_cm=?,goal=?,lunch_time=?,cooking_minutes=?,allergies=?,preferred_stores=?,updated_at=? WHERE id=1""",
          (height,str(data.get("goal",""))[:80],str(data.get("lunchTime","13:00"))[:5],int(positive(data.get("cookMinutes")) or 20),str(data.get("allergies",""))[:2000],json.dumps(stores,ensure_ascii=False),now))
        for kind,key in (("waist_cm","waist"),("biceps_cm","biceps")):
            value=positive(data.get(key))
            if value:
                last=conn.execute("SELECT value FROM body_measurements WHERE kind=? ORDER BY measured_at DESC LIMIT 1",(kind,)).fetchone()
                if not last or abs(last[0]-value)>.001: conn.execute("INSERT INTO body_measurements(measured_at,kind,value,source) VALUES(?,?,?,'manual')",(now,kind,value))
    return profile_get()

def catalog_get(query):
    q=query.get("q",[""])[0].strip(); store=query.get("store",[""])[0].strip()
    try: limit=min(60,max(1,int(query.get("limit",[24])[0])))
    except ValueError: limit=24
    where=["recommendation_ready=1"]; params=[]
    if q: where.append("(name LIKE ? OR brand LIKE ? OR category LIKE ?)"); params += [f"%{q}%"]*3
    if store: where.append("store_name=?"); params.append(store)
    food_case="""CASE WHEN category IN ('Дом, кухня','Товары для животных','Алкоголь','Мелочи возле кассы')
      OR COALESCE(name,'') LIKE '%корм%'
      OR COALESCE(name,'') LIKE '%Корм%'
      OR COALESCE(name,'') LIKE '%КОРМ%'
      OR lower(COALESCE(name,'')) LIKE '%аперитив%'
      OR COALESCE(name,'') LIKE '%Аперитив%'
      OR lower(COALESCE(name,'')) LIKE '%водка%'
      OR COALESCE(name,'') LIKE '%Водка%'
      OR lower(COALESCE(name,'')) LIKE '%вино%'
      OR COALESCE(name,'') LIKE '%Вино%'
      OR lower(COALESCE(name,'')) LIKE '%коньяк%'
      OR COALESCE(name,'') LIKE '%Коньяк%'
      OR lower(COALESCE(name,'')) LIKE '%ликер%'
      OR lower(COALESCE(name,'')) LIKE '%ликёр%'
      THEN 0 ELSE 1 END"""
    sql=f"SELECT store_name,name,brand,category,package,price_rub,protein,fat,carbs,calories,nutrition_basis,url,{food_case} is_food FROM catalog_products WHERE {' AND '.join(where)} ORDER BY is_food DESC,store_name,name LIMIT ?"
    params.append(limit)
    with connect() as conn:
        rows=[dict(r) for r in conn.execute(sql,params)]
        stores=[r[0] for r in conn.execute("SELECT DISTINCT store_name FROM catalog_products ORDER BY store_name")]
        ready=conn.execute("SELECT COUNT(*) FROM catalog_products WHERE recommendation_ready=1").fetchone()[0]
    return {"items":rows,"stores":stores,"ready":ready}

def offline_chat(message):
    profile=profile_get(); text=message.casefold()
    with connect() as conn: day=conn.execute("SELECT MAX(day) FROM daily_metrics WHERE metric='nutrition.energy'").fetchone()[0]
    if any(w in text for w in ("ужин","белок","съесть","еда","перекус")):
        if not profile.get("stores"): return "Чтобы подобрать реальные товары, выбери доступные магазины в профиле. После этого я смогу искать только среди их актуального каталога."
        if not day: return "В базе пока нет дневных данных о питании. Импортируй свежий экспорт Apple Health."
        with connect() as conn: vals={r[0]:r[1] for r in conn.execute("SELECT metric,value FROM daily_metrics WHERE day=? AND metric LIKE 'nutrition.%'",(day,))}
        products=search_store_products(profile["stores"],"",5)
        names=", ".join(p["name"] for p in products[:3]) or "подходящие товары пока не найдены"
        return f"За {day} записано {vals.get('nutrition.protein',0):.1f} г белка. Цель по белку ещё нужно сохранить в разделе «Питание». В выбранных магазинах вижу варианты: {names}. Это локальный предварительный ответ без облачной модели."
    summary=get_health_summary(7)
    return f"Я могу прочитать профиль, нормализованные показатели здоровья и каталог товаров. Сейчас работаю в локальном режиме без API-ключа. За последние {summary['periodDays']} дней доступно {len(summary['metrics'])} групп показателей. Спроси, например, что можно съесть на ужин."

def openai_chat(messages):
    key=os.getenv("OPENAI_API_KEY")
    if not key: return {"text":offline_chat(messages[-1].get("content","")),"mode":"local"}
    model=os.getenv("AVELIN_OPENAI_MODEL","gpt-6-luna")
    instructions="""Ты Avelin Health, спокойный персональный помощник. Отвечай по-русски. Используй инструменты для фактов о здоровье, профиле и товарах. Не ставь диагнозы. Не выдумывай показатели здоровья, аллергии, цели или наличие товара. Для товаров без КБЖУ можешь оценивать калории и макронутриенты по названию и типичному составу, но всегда давай диапазон, помечай его как примерную оценку и напоминай, что фактическое значение из упаковки или FatSecret имеет приоритет. Не представляй оценку как измеренный факт. Для подбора еды учитывай подтверждённые ограничения пользователя."""
    payload={"model":model,"instructions":instructions,"input":messages[-12:],"tools":TOOL_SCHEMAS,"parallel_tool_calls":False}
    for _ in range(5):
        req=urllib.request.Request("https://api.openai.com/v1/responses",data=json.dumps(payload).encode(),headers={"Authorization":f"Bearer {key}","Content-Type":"application/json"},method="POST")
        try:
            with urllib.request.urlopen(req,timeout=90) as response: result=json.load(response)
        except urllib.error.HTTPError as exc: raise RuntimeError(exc.read().decode("utf-8","replace")[:500]) from exc
        calls=[item for item in result.get("output",[]) if item.get("type")=="function_call"]
        if not calls:
            texts=[]
            for item in result.get("output",[]):
                for part in item.get("content",[]):
                    if part.get("type")=="output_text": texts.append(part.get("text",""))
            return {"text":"\n".join(texts) or "Не удалось сформировать ответ.","mode":"openai","model":model}
        outputs=[]
        for call in calls:
            name=call.get("name"); args=json.loads(call.get("arguments") or "{}")
            if name not in TOOLS: value={"error":"unknown_tool"}
            else:
                try: value=TOOLS[name]["call"](**args)
                except Exception as exc: value={"error":str(exc)[:200]}
            outputs.append({"type":"function_call_output","call_id":call["call_id"],"output":json.dumps(value,ensure_ascii=False)})
        payload={"model":model,"previous_response_id":result["id"],"input":outputs,"tools":TOOL_SCHEMAS,"parallel_tool_calls":False}
    return {"text":"Превышен лимит последовательных обращений к данным.","mode":"error"}

class Handler(SimpleHTTPRequestHandler):
    def json_response(self,data,status=200):
        raw=json.dumps(data,ensure_ascii=False).encode(); self.send_response(status); self.send_header("Content-Type","application/json; charset=utf-8"); self.send_header("Content-Length",str(len(raw))); self.send_header("Cache-Control","no-store"); self.end_headers(); self.wfile.write(raw)
    def read_json(self):
        length=min(int(self.headers.get("Content-Length","0")),1_000_000); return json.loads(self.rfile.read(length) or b"{}")
    def do_GET(self):
        parsed=urlparse(self.path)
        if parsed.path=="/api/profile": return self.json_response(profile_get())
        if parsed.path=="/api/catalog": return self.json_response(catalog_get(parse_qs(parsed.query)))
        if parsed.path=="/api/status": return self.json_response({"ok":True,"llmConfigured":bool(os.getenv("OPENAI_API_KEY"))})
        path=(DIST/(parsed.path.lstrip("/") or "index.html")).resolve()
        if DIST.resolve() not in path.parents and path!=DIST.resolve(): return self.send_error(403)
        if not path.is_file(): path=DIST/"index.html"
        raw=path.read_bytes(); self.send_response(200); self.send_header("Content-Type",mimetypes.guess_type(path.name)[0] or "application/octet-stream"); self.send_header("Content-Length",str(len(raw))); self.end_headers(); self.wfile.write(raw)
    def do_PUT(self):
        if self.path=="/api/profile":
            try:return self.json_response(profile_put(self.read_json()))
            except Exception as exc:return self.json_response({"error":str(exc)},400)
        self.send_error(404)
    def do_POST(self):
        if self.path=="/api/chat":
            try:
                data=self.read_json(); messages=data.get("messages",[])
                if not messages:return self.json_response({"error":"messages required"},400)
                return self.json_response(openai_chat(messages))
            except Exception as exc:return self.json_response({"error":str(exc)},502)
        self.send_error(404)
    def log_message(self,format,*args): print(f"[Avelin] {format%args}")

if __name__=="__main__":
    ensure_profile_schema(); port=int(os.getenv("AVELIN_PORT","8765")); print(f"Avelin API: http://127.0.0.1:{port}"); ThreadingHTTPServer(("127.0.0.1",port),Handler).serve_forever()
