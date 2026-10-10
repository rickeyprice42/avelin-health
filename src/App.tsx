import {
  Activity, Apple, ArrowDownRight, BedDouble, ChevronRight, Dumbbell,
  Flame, HeartPulse, LayoutDashboard, MessageCircle, Moon, Scale,
  Sparkles, Utensils, Waves, Database, ShieldCheck, AlertTriangle,
  Info, CheckCircle2, Clock3,
  TrendingUp, Save, Target, Salad,
  UserRound, Ruler, Clock, Store, ShieldAlert,
  Search, ShoppingBasket, Send, Bot, LoaderCircle, PackageCheck,
} from "lucide-react";
import { useEffect, useState } from "react";
import logo from "./assets/avelin-health-logo.png";

type Summary = {
  importedAt: string;
  period: { start: string; end: string };
  totals: { records: number; workouts: number; sources: number };
  latest: { weightKg?: number; bodyFatPercent?: number; restingHeartRate?: number };
  recent: { steps7d?: number; activeEnergy7d?: number; sleepHours7d?: number };
  quality?: {
    selectedRecords: number; exactDuplicates: number;
    metrics: { metric: string; records: number; sources: number; start: string; end: string }[];
    sources: { name: string; records: number; metrics: number; start: string; end: string }[];
    issues: { severity: "warning" | "info" | "good"; title: string; detail: string }[];
  };
  aggregation?: {
    days: number; rows: number; resolvedOverlaps: number;
    priorities: { metric: string; source: string; priority: number; reason: string }[];
  };
  series?: Record<string, { day: string; value: number; unit: string; source: string }[]>;
  latestNutrition?: { day?: string; energy?: {value:number;unit:string}; protein?: {value:number;unit:string}; fat?: {value:number;unit:string}; carbs?: {value:number;unit:string} };
  profile?: { heightCm?: number; goal?: string; calorieTarget?: number; proteinTarget?: number };
};

const fallback: Summary = {
  importedAt: "",
  period: { start: "", end: "" },
  totals: { records: 0, workouts: 0, sources: 0 },
  latest: {},
  recent: {},
};

const nav = [
  ["Сегодня", LayoutDashboard], ["Тело", Scale], ["Активность", Activity],
  ["Сон", Moon], ["Питание", Utensils], ["Каталог", ShoppingBasket], ["Тренировки", Dumbbell],
  ["Тренды", Waves], ["Качество данных", ShieldCheck], ["Профиль", UserRound], ["Спросить Avelin", MessageCircle],
] as const;

const metricNames: Record<string, string> = {
  "energy.basal": "Базальная энергия", "activity.steps": "Шаги", "activity.distance": "Дистанция",
  "energy.active": "Активная энергия", "heart.rate": "Пульс", "nutrition.energy": "Питание · калории",
  "nutrition.protein": "Питание · белок", "nutrition.fat": "Питание · жиры", "nutrition.carbs": "Питание · углеводы",
  "sleep.stage": "Сон", "body.weight": "Вес", "body.fat_percentage": "Процент жира",
  "body.lean_mass": "Безжировая масса", "body.bmi": "BMI",
};

function fmt(value: number | undefined, unit: string, empty = "—") {
  return value == null ? empty : `${new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 1 }).format(value)}${unit}`;
}

export function App() {
  const [data, setData] = useState(fallback);
  const [page, setPage] = useState<"today" | "quality" | "trends" | "nutrition" | "profile" | "catalog" | "chat">("today");
  useEffect(() => {
    fetch("/data/health-summary.json").then((r) => r.ok ? r.json() : Promise.reject()).then(setData).catch(() => undefined);
  }, []);

  const cards = [
    { label: "Вес", value: fmt(data.latest.weightKg, " кг"), note: "последнее измерение", icon: Scale, tone: "mint" },
    { label: "Шаги", value: fmt(data.recent.steps7d, "", "Нет данных"), note: "среднее за 7 дней", icon: Activity, tone: "blue" },
    { label: "Активность", value: fmt(data.recent.activeEnergy7d, " ккал"), note: "среднее за 7 дней", icon: Flame, tone: "orange" },
    { label: "Сон", value: fmt(data.recent.sleepHours7d, " ч"), note: "среднее за 7 дней", icon: BedDouble, tone: "violet" },
  ];

  return <div className="shell">
    <aside>
      <div className="brand"><img src={logo} /><div><strong>Avelin</strong><span>Health</span></div></div>
      <nav>{nav.map(([label, Icon], i) => { const target = label === "Качество данных" ? "quality" : label === "Сегодня" ? "today" : label === "Тренды" ? "trends" : label === "Питание" ? "nutrition" : label === "Профиль" ? "profile" : label === "Каталог" ? "catalog" : label === "Спросить Avelin" ? "chat" : null; return <button onClick={() => target && setPage(target)} className={target === page ? "active" : ""} key={label}><Icon size={18}/><span>{label}</span>{i === 10 && <ChevronRight size={15}/>}</button> })}</nav>
      <div className="privacy"><HeartPulse size={18}/><div><b>Данные остаются здесь</b><span>Локальное хранение на этом компьютере</span></div></div>
    </aside>
    <main>{page === "today" ? <>
      <header><div><p className="eyebrow">4 ОКТЯБРЯ · ВОСКРЕСЕНЬЕ</p><h1>Добрый день.</h1><p className="subtitle">Вот что известно о твоём состоянии сейчас.</p></div><button className="import"><Apple size={18}/> Импортировать Health</button></header>
      <section className="metrics">{cards.map(({label,value,note,icon:Icon,tone}) => <article className="metric" key={label}><div className={`icon ${tone}`}><Icon size={20}/></div><p>{label}</p><h2>{value}</h2><span>{note}</span></article>)}</section>
      <section className="grid">
        <article className="insight panel"><div className="panel-title"><span><Sparkles size={17}/> Наблюдение Avelin</span><small>ЛОКАЛЬНЫЙ АНАЛИЗ</small></div><h2>История уже готова к исследованию.</h2><p>В Apple Health найдено <b>{data.totals.records.toLocaleString("ru-RU")}</b> записей из <b>{data.totals.sources}</b> источников. Следующий шаг — аккуратно разрешить пересечения источников и построить твои персональные базовые уровни.</p><button onClick={() => setPage("quality")}>Посмотреть качество данных <ChevronRight size={16}/></button></article>
        <article className="status panel"><div className="panel-title"><span>Сводка импорта</span><small className="ready">● ГОТОВО</small></div><div className="status-row"><span>Период данных</span><b>{data.period.start.slice(0,4)}—{data.period.end.slice(0,4)}</b></div><div className="status-row"><span>Тренировки</span><b>{data.totals.workouts}</b></div><div className="status-row"><span>Источники</span><b>{data.totals.sources}</b></div><div className="status-row"><span>Последний импорт</span><b>{data.importedAt ? "Сегодня" : "Демо"}</b></div></article>
      </section>
      <section className="bottom-grid">
        <article className="chart panel"><div className="panel-title"><span>Вес · динамика</span><small>30 ДНЕЙ</small></div><div className="chart-empty"><div className="fake-line"><i/><i/><i/><i/><i/><i/></div><span><ArrowDownRight size={18}/> График появится после нормализации измерений</span></div></article>
        <article className="ask"><Sparkles size={22}/><div><span>AVELIN</span><h3>Что ты хочешь узнать о своих данных?</h3></div><button><ChevronRight/></button></article>
      </section>
      </> : page === "quality" ? <QualityScreen data={data} onBack={() => setPage("today")}/> : page === "trends" ? <TrendsScreen data={data}/> : page === "nutrition" ? <NutritionScreen data={data}/> : page === "profile" ? <ProfileScreen/> : page === "catalog" ? <CatalogScreen/> : <ChatScreen/>}</main>
  </div>;
}

function LineChart({points, color="#59dfbd"}: {points: {value:number}[]; color?: string}) {
  if (!points.length) return <div className="no-data">Недостаточно данных</div>;
  const values=points.map(p=>p.value), min=Math.min(...values), max=Math.max(...values), span=max-min||1;
  const coords=points.map((p,i)=>`${(i/(Math.max(1,points.length-1)))*100},${86-((p.value-min)/span)*68}`).join(" ");
  return <svg className="line-chart" viewBox="0 0 100 100" preserveAspectRatio="none"><defs><linearGradient id={`fill-${color.slice(1)}`} x1="0" y1="0" x2="0" y2="1"><stop offset="0" stopColor={color} stopOpacity=".28"/><stop offset="1" stopColor={color} stopOpacity="0"/></linearGradient></defs><polygon points={`0,100 ${coords} 100,100`} fill={`url(#fill-${color.slice(1)})`}/><polyline points={coords} fill="none" stroke={color} strokeWidth="2" vectorEffect="non-scaling-stroke"/></svg>;
}

function TrendsScreen({data}: {data: Summary}) {
  const weight=data.series?.["body.weight"] ?? [], steps=data.series?.["activity.steps"] ?? [], energy=data.series?.["energy.active"] ?? [];
  const last=(a:{value:number}[])=>a.at(-1)?.value;
  return <div><header><div><p className="eyebrow">НОРМАЛИЗОВАННЫЕ ДАННЫЕ</p><h1>Тренды</h1><p className="subtitle">Каждая точка построена после разрешения пересечений источников.</p></div><span className="verified"><ShieldCheck size={16}/> Проверено правилами</span></header>
    <section className="trend-grid"><article className="trend-card panel"><div className="trend-title"><span>Вес</span><b>{fmt(last(weight)," кг")}</b></div><LineChart points={weight}/><small>{weight.length} измерений · последний источник: {weight.at(-1)?.source ?? "—"}</small></article><article className="trend-card panel"><div className="trend-title"><span>Шаги</span><b>{fmt(last(steps),"")}</b></div><LineChart points={steps} color="#78aef6"/><small>Последние {steps.length} дней · без двойного счёта</small></article></section>
    <section className="trend-card wide panel"><div className="trend-title"><span>Активная энергия</span><b>{fmt(last(energy)," ккал")}</b></div><LineChart points={energy} color="#f0a361"/><small>Последние {energy.length} дней · выбранный источник указан для каждой точки</small></section>
  </div>;
}

function NutritionScreen({data}: {data: Summary}) {
  const stored=JSON.parse(localStorage.getItem("avelin.nutritionTargets") || "null") as {calories:number;protein:number}|null;
  const [calories,setCalories]=useState(String(stored?.calories ?? data.profile?.calorieTarget ?? ""));
  const [protein,setProtein]=useState(String(stored?.protein ?? data.profile?.proteinTarget ?? ""));
  const [saved,setSaved]=useState(!!stored);
  const n=data.latestNutrition, energy=n?.energy?.value, proteinValue=n?.protein?.value;
  const calTarget=Number(calories)||0, proteinTarget=Number(protein)||0;
  const save=()=>{if(calTarget>0&&proteinTarget>0){localStorage.setItem("avelin.nutritionTargets",JSON.stringify({calories:calTarget,protein:proteinTarget}));setSaved(true)}};
  const gap=(target:number,value:number|undefined)=>target ? Math.max(0,target-(value??0)) : null;
  return <div><header><div><p className="eyebrow">FATSECRET · APPLE HEALTH</p><h1>Питание</h1><p className="subtitle">Фактические значения за {n?.day ?? "последний доступный день"}.</p></div><span className="verified"><Salad size={16}/> Источник: FatSecret</span></header>
    <section className="nutrition-grid"><article className="panel today-food"><div className="panel-title"><span>Итоги дня</span><small>{n?.day ?? "НЕТ ДАННЫХ"}</small></div><div className="macro-main"><span>Калории</span><b>{fmt(energy," ккал")}</b>{calTarget>0&&<em>{gap(calTarget,energy) ? `Осталось ${fmt(gap(calTarget,energy)!," ккал")}` : "Цель достигнута"}</em>}</div><div className="macro-row"><div><span>Белок</span><b>{fmt(proteinValue," г")}</b></div><div><span>Жиры</span><b>{fmt(n?.fat?.value," г")}</b></div><div><span>Углеводы</span><b>{fmt(n?.carbs?.value," г")}</b></div></div>{proteinTarget>0&&<div className="protein-gap"><Target/><div><span>До цели по белку</span><b>{fmt(gap(proteinTarget,proteinValue)!," г")}</b></div></div>}</article>
      <article className="panel target-form"><div className="panel-title"><span>Твои цели</span><small>{saved?"СОХРАНЕНО ЛОКАЛЬНО":"НУЖНЫ ДАННЫЕ"}</small></div><p>Мы не назначаем норму автоматически. Введи цели, которые выбрал сам или согласовал со специалистом.</p><label>Калории в день<input type="number" min="1" value={calories} onChange={e=>{setCalories(e.target.value);setSaved(false)}} placeholder="например, 2300"/></label><label>Белок в день, г<input type="number" min="1" value={protein} onChange={e=>{setProtein(e.target.value);setSaved(false)}} placeholder="например, 160"/></label><button onClick={save} disabled={!calTarget||!proteinTarget}><Save size={15}/> Сохранить цели</button></article></section>
    <article className="panel nutrition-note"><Sparkles/><div><b>Основа для будущего подбора ужина</b><p>Nutrition gap будет передан инструменту каталога вместе с аллергиями, временем готовки и доступными магазинами — не напрямую в свободный prompt.</p></div></article>
  </div>;
}

type ProfileForm = {height:string;waist:string;biceps:string;goal:string;lunchTime:string;cookMinutes:string;allergies:string;stores:string[];updatedAt?:string};
const emptyProfile: ProfileForm={height:"",waist:"",biceps:"",goal:"",lunchTime:"13:00",cookMinutes:"20",allergies:"",stores:[]};

function ProfileScreen() {
  const [form,setForm]=useState<ProfileForm>(emptyProfile);
  const [saved,setSaved]=useState(false);
  const [loading,setLoading]=useState(true);
  useEffect(()=>{fetch("/api/profile").then(r=>r.json()).then(p=>{setForm({...emptyProfile,...p,height:String(p.height??""),waist:String(p.waist??""),biceps:String(p.biceps??""),cookMinutes:String(p.cookMinutes??20)});setSaved(Boolean(p.updatedAt))}).finally(()=>setLoading(false))},[]);
  const update=(key:keyof ProfileForm,value:string|string[])=>{setForm({...form,[key]:value});setSaved(false)};
  const toggleStore=(store:string)=>update("stores",form.stores.includes(store)?form.stores.filter(s=>s!==store):[...form.stores,store]);
  const save=async()=>{const response=await fetch("/api/profile",{method:"PUT",headers:{"Content-Type":"application/json"},body:JSON.stringify(form)});if(response.ok){const next=await response.json();setForm({...form,...next,height:String(next.height??""),waist:String(next.waist??""),biceps:String(next.biceps??"")});setSaved(true)}};
  return <div><header><div><p className="eyebrow">УПРАВЛЯЕМАЯ ПАМЯТЬ</p><h1>Профиль</h1><p className="subtitle">Только ты задаёшь факты, ограничения и цели. Avelin не изменяет их самостоятельно.</p></div><span className="verified"><ShieldAlert size={16}/> Редактируется пользователем</span></header>
    <section className="profile-layout"><article className="panel profile-card"><div className="panel-title"><span><Ruler size={16}/> Тело и цель</span><small>РУЧНЫЕ ДАННЫЕ</small></div><div className="profile-fields"><label>Рост, см<input type="number" value={form.height} onChange={e=>update("height",e.target.value)} placeholder="—"/></label><label>Талия, см<input type="number" value={form.waist} onChange={e=>update("waist",e.target.value)} placeholder="—"/></label><label>Бицепс, см<input type="number" value={form.biceps} onChange={e=>update("biceps",e.target.value)} placeholder="—"/></label></div><label className="full-label">Текущая цель<select value={form.goal} onChange={e=>update("goal",e.target.value)}><option value="">Не выбрана</option><option value="lose_weight">Снижение веса</option><option value="maintain">Поддержание формы</option><option value="gain_muscle">Набор мышечной массы</option><option value="wellbeing">Самочувствие и режим</option></select></label><p className="field-note">Талия и бицепс будут храниться как датированные измерения, чтобы видеть динамику.</p></article>
      <article className="panel profile-card"><div className="panel-title"><span><Clock size={16}/> Режим и предпочтения</span><small>КОНТЕКСТ АГЕНТА</small></div><div className="profile-fields two"><label>Обычно обедаю<input type="time" value={form.lunchTime} onChange={e=>update("lunchTime",e.target.value)}/></label><label>Готовка, максимум минут<input type="number" value={form.cookMinutes} onChange={e=>update("cookMinutes",e.target.value)}/></label></div><label className="full-label">Аллергии и строгие ограничения<textarea value={form.allergies} onChange={e=>update("allergies",e.target.value)} placeholder="Например: арахис. Оставь пустым, если ограничений нет."/></label></article></section>
    <article className="panel stores-card"><div className="panel-title"><span><Store size={16}/> Доступные магазины</span><small>ДЛЯ ПОДБОРА ПРОДУКТОВ</small></div><div className="store-options">{["Пятёрочка","Слата","Хлеб&Соль","Fix Price"].map(store=><button className={form.stores.includes(store)?"selected":""} onClick={()=>toggleStore(store)} key={store}>{form.stores.includes(store)&&<CheckCircle2 size={15}/>} {store}</button>)}</div></article>
    <div className="profile-save"><div>{loading?<>Загрузка профиля…</>:saved?<><CheckCircle2/> Профиль сохранён в SQLite</>:<>Изменения ещё не сохранены</>}</div><button onClick={save} disabled={loading}><Save size={15}/> Сохранить профиль</button></div>
  </div>;
}

type Product={store_name:string;name:string;brand?:string;category?:string;package?:string;price_rub?:number;protein?:number;fat?:number;carbs?:number;calories?:number;nutrition_basis?:string;url?:string;is_food?:number};
function CatalogScreen(){
  const [items,setItems]=useState<Product[]>([]),[stores,setStores]=useState<string[]>([]),[ready,setReady]=useState(0),[q,setQ]=useState(""),[store,setStore]=useState(""),[loading,setLoading]=useState(true);
  const load=()=>{setLoading(true);const p=new URLSearchParams({q,store,limit:"30"});fetch(`/api/catalog?${p}`).then(r=>r.json()).then(d=>{setItems(d.items||[]);setStores(d.stores||[]);setReady(d.ready||0)}).finally(()=>setLoading(false))};
  useEffect(load,[]);
  return <div><header><div><p className="eyebrow">4 МАГАЗИНА · ВСЕ ДОСТУПНЫЕ ТОВАРЫ</p><h1>Каталог продуктов</h1><p className="subtitle">КБЖУ временно оценивает Avelin диапазоном. Данные упаковки и FatSecret всегда приоритетнее.</p></div><span className="verified"><PackageCheck size={16}/> {ready.toLocaleString("ru-RU")} товаров доступно</span></header><section className="catalog-filters panel"><div className="searchbox"><Search size={16}/><input value={q} onChange={e=>setQ(e.target.value)} onKeyDown={e=>e.key==="Enter"&&load()} placeholder="Название, бренд или категория"/></div><select value={store} onChange={e=>setStore(e.target.value)}><option value="">Все магазины</option>{stores.map(s=><option key={s}>{s}</option>)}</select><div className="estimate-badge"><Sparkles size={14}/><span>КБЖУ оценит агент</span></div><button onClick={load}><Search size={15}/> Найти</button></section>{loading?<div className="catalog-loading"><LoaderCircle/> Загружаю каталог…</div>:<section className="product-grid">{items.map((p,i)=><article className="product-card" key={`${p.store_name}-${p.name}-${i}`}><div><span>{p.store_name}</span><small>{p.category}</small></div><h3>{p.name}</h3><p>{[p.brand,p.package].filter(Boolean).join(" · ")}</p>{p.is_food?<div className="product-macros unknown"><Sparkles size={15}/><b>Примерная оценка по запросу<small>не является фактическим КБЖУ</small></b></div>:<div className="product-macros unknown"><PackageCheck size={15}/><b>Непищевой товар<small>не участвует в подборе рациона</small></b></div>}<footer><strong>{p.price_rub?`${p.price_rub.toLocaleString("ru-RU")} ₽`:"Цена не указана"}</strong>{p.url&&<a href={p.url} target="_blank" rel="noreferrer">Карточка <ChevronRight size={13}/></a>}</footer></article>)}</section>}</div>
}

type ChatMessage={role:"user"|"assistant";content:string;mode?:string};
function ChatScreen(){
  const [messages,setMessages]=useState<ChatMessage[]>([{role:"assistant",content:"Привет. Я могу связать твой профиль, данные здоровья и каталог продуктов. Что хочешь узнать?"}]);
  const [input,setInput]=useState(""),[busy,setBusy]=useState(false);
  const send=async(text=input)=>{if(!text.trim()||busy)return;const next=[...messages,{role:"user" as const,content:text.trim()}];setMessages(next);setInput("");setBusy(true);try{const r=await fetch("/api/chat",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({messages:next.map(({role,content})=>({role,content}))})});const d=await r.json();setMessages([...next,{role:"assistant",content:d.text||d.error||"Не удалось получить ответ.",mode:d.mode}])}catch{setMessages([...next,{role:"assistant",content:"Локальный сервер Avelin недоступен."}])}finally{setBusy(false)}};
  return <div className="chat-page"><header><div><p className="eyebrow">ПЕРСОНАЛЬНЫЙ КОНТЕКСТ</p><h1>Спросить Avelin</h1><p className="subtitle">Ответы основаны на доступных данных и всегда показывают границы уверенности.</p></div><span className="verified"><Bot size={16}/> Tool calling</span></header><section className="chat-panel panel"><div className="messages">{messages.map((m,i)=><div className={`message ${m.role}`} key={i}>{m.role==="assistant"&&<div className="avatar"><Sparkles size={15}/></div>}<div><p>{m.content}</p>{m.mode==="local"&&<small>Локальный режим · OpenAI API не настроен</small>}</div></div>)}{busy&&<div className="message assistant"><div className="avatar"><LoaderCircle className="spin" size={15}/></div><div><p>Сопоставляю данные…</p></div></div>}</div><div className="suggestions">{["Что можно съесть на ужин?","Как выглядела моя активность за неделю?","Каких данных мне не хватает?"].map(s=><button onClick={()=>send(s)} key={s}>{s}</button>)}</div><div className="composer"><input value={input} onChange={e=>setInput(e.target.value)} onKeyDown={e=>e.key==="Enter"&&send()} placeholder="Спроси о здоровье, питании или товарах…"/><button onClick={()=>send()} disabled={busy||!input.trim()}><Send size={18}/></button></div></section></div>
}

function QualityScreen({data, onBack}: {data: Summary; onBack: () => void}) {
  const q = data.quality;
  const fmtInt = (n: number | undefined) => (n ?? 0).toLocaleString("ru-RU");
  return <div className="quality-page">
    <header><div><p className="eyebrow">APPLE HEALTH · ДИАГНОСТИКА</p><h1>Качество данных</h1><p className="subtitle">Понимаем, чему можно доверять до того, как Avelin начнёт давать советы.</p></div><button className="back" onClick={onBack}>Вернуться к сводке</button></header>
    <section className="quality-kpis">
      <article><Database/><div><b>{fmtInt(q?.selectedRecords)}</b><span>полезных записей</span></div></article>
      <article><ShieldCheck/><div><b>{data.totals.sources}</b><span>источников сохранено</span></div></article>
      <article><Clock3/><div><b>{data.period.end}</b><span>последняя дата</span></div></article>
      <article><AlertTriangle/><div><b>{q?.issues.filter(x=>x.severity==="warning").length ?? 0}</b><span>требуют внимания</span></div></article>
    </section>
    <section className="quality-layout">
      <article className="panel issues"><div className="panel-title"><span>Что мы обнаружили</span><small>АВТОМАТИЧЕСКАЯ ПРОВЕРКА</small></div><div className="issue-list">{q?.issues.map((issue) => {const Icon=issue.severity === "good" ? CheckCircle2 : issue.severity === "warning" ? AlertTriangle : Info; return <div className={`issue ${issue.severity}`} key={issue.title}><Icon size={18}/><div><b>{issue.title}</b><p>{issue.detail}</p></div></div>}) ?? <p className="muted">Повторите импорт, чтобы рассчитать диагностику.</p>}</div></article>
      <article className="panel trust"><div className="panel-title"><span>Политика источников</span><small className="ready">● АКТИВНА</small></div><h3>Не складываем одинаковые сигналы</h3><p>Avelin выбирает один источник на каждый день и показатель. Исходные записи остаются неизменными, а результат можно пересчитать.</p><div className="priority"><span>1</span><b>Выбранный источник</b><small>шаги и энергия</small></div><div className="aggregation-result"><b>{data.aggregation?.resolvedOverlaps ?? 0}</b><span>дневных пересечений разрешено</span></div></article>
    </section>
    <section className="panel data-table"><div className="panel-title"><span>Покрытие показателей</span><small>{q?.metrics.length ?? 0} ТИПОВ</small></div><div className="table-head"><span>Показатель</span><span>Записи</span><span>Источники</span><span>Период</span></div>{(q?.metrics ?? []).map(m => <div className="table-row" key={m.metric}><span><i/>{metricNames[m.metric] ?? m.metric}</span><b>{fmtInt(m.records)}</b><b>{m.sources}</b><small>{m.start.slice(0,4)}—{m.end.slice(0,4)}</small></div>)}</section>
    <section className="panel source-table"><div className="panel-title"><span>Источники данных</span><small>PROVENANCE</small></div><div className="source-grid">{(q?.sources ?? []).map(s => <div key={s.name}><span>{s.name}</span><b>{fmtInt(s.records)}</b><small>{s.metrics} показателей · до {s.end}</small></div>)}</div></section>
  </div>
}
