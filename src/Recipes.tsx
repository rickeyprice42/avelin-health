import { useEffect, useState } from "react";
import { ArrowLeft, Check, ChefHat, Clock3, LoaderCircle, ShoppingBasket } from "lucide-react";
import five from "./assets/stores/pyaterochka.png";
import fix from "./assets/stores/fixprice.png";
import slata from "./assets/stores/slata.png";
import hlebsol from "./assets/stores/hlebsol.png";
import "./recipes.css";

type Ingredient = { name: string; store_name: string; amount: string; packs: number; package?: string; price_rub: number | null; url?: string };
export type Recipe = { id: string; title: string; servings: number; minutes: number; ingredients: Ingredient[]; steps: string[]; macros: Record<"calories" | "protein" | "fat" | "carbs", [number, number] | null>; total_rub: number | null; checked?: number[]; created_at?: string };
const money = (value: number | null) => value === null ? "Цена не указана" : `${value.toLocaleString("ru-RU", { maximumFractionDigits: 2 })} ₽`;
const safeLink = (url?: string) => { try { const parsed = new URL(url || ""); return ["https:", "http:"].includes(parsed.protocol) ? parsed.href : undefined; } catch { return undefined; } };

export function recipeParts(content: string) {
  const marker = /```avelin-recipe\s*\n/g;
  const cards: unknown[] = [];
  let output = "", position = 0, match: RegExpExecArray | null;
  while ((match = marker.exec(content))) {
    output += content.slice(position, match.index);
    const end = content.indexOf("```", marker.lastIndex);
    if (end < 0) return { text: output, cards };
    try { cards.push(JSON.parse(content.slice(marker.lastIndex, end))); }
    catch { output += "\nНе удалось прочитать карточку рецепта. Попроси Avelin сформировать её ещё раз.\n"; }
    position = end + 3;
    marker.lastIndex = position;
  }
  // Hide even a partial opening marker during streaming.
  return { text: (output + content.slice(position)).replace(/(?:^|\n)```(?:a|av|ave|avel|aveli|avelin|avelin-|avelin-r|avelin-re|avelin-rec|avelin-reci|avelin-recip|avelin-recipe)\s*$/, ""), cards };
}

function StoreBadge({ name }: { name: string }) {
  const logo = name === "Пятёрочка" ? five : name === "Fix Price" ? fix : name === "Слата" ? slata : ["Хлеб&Соль", "ХлебСоль", "Хлеб-Соль"].includes(name) ? hlebsol : undefined;
  return <span className="recipe-store">{logo && <img src={logo} alt=""/>}{name}</span>;
}

export function RecipeCard({ recipe, action, children }: { recipe: Recipe; action?: React.ReactNode; children?: React.ReactNode }) {
  return <section className="recipe-card">
    <div className="recipe-heading"><div><span className="recipe-kicker">AVELIN · РЕЦЕПТ ИЗ КАТАЛОГА</span><h2>{recipe.title}</h2></div><ChefHat size={24}/></div>
    <div className="recipe-meta"><span><Clock3 size={14}/>{recipe.minutes} мин</span><span>{recipe.servings} порц.</span></div>
    <div className="recipe-macros">{([["calories", "ккал"], ["protein", "белки, г"], ["fat", "жиры, г"], ["carbs", "углеводы, г"]] as const).map(([key, label]) => <div key={key}><b>{recipe.macros[key] ? `~${recipe.macros[key]![0]}${recipe.macros[key]![0] === recipe.macros[key]![1] ? "" : `–${recipe.macros[key]![1]}`}` : "—"}</b><span>{label}</span></div>)}</div>
    <p className="recipe-note">На одну порцию · ~ примерная оценка. Значения на упаковке точнее.</p>
    <h3>Ингредиенты</h3>
    <div className="recipe-ingredients">{recipe.ingredients.map((item, index) => <div className="recipe-ingredient" key={index}><div><b>{item.name}</b><span className="recipe-amount">В рецепт: {item.amount}</span><StoreBadge name={item.store_name}/><span className="recipe-package">{item.package || "Упаковка"} · купить {item.packs} шт.</span></div><div className="recipe-price"><b>{money(item.price_rub)}</b><span>за упаковку</span>{safeLink(item.url) && <a href={safeLink(item.url)} target="_blank" rel="noopener noreferrer">Товар ↗</a>}</div></div>)}</div>
    <div className="recipe-total"><div><b>Стоимость покупки</b><span>Все упаковки для {recipe.servings} порц.</span></div><strong>{money(recipe.total_rub)}</strong></div>
    <p className="recipe-note">Цены из загруженного каталога; в магазине они могут измениться.</p>
    {children}{action}
  </section>;
}

export function ChatRecipe({ data, onOpen }: { data: unknown; onOpen: (id: string) => void }) {
  const serialized = JSON.stringify(data);
  const [recipe, setRecipe] = useState<Recipe | null>(null);
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  useEffect(() => {
    const abort = new AbortController();
    setRecipe(null); setError(""); setSaved(false);
    fetch("/api/recipes/preview", { method: "POST", headers: { "Content-Type": "application/json" }, body: serialized, signal: abort.signal }).then(async response => { const result = await response.json(); if (!response.ok) throw new Error(result.error || "Карточка недоступна"); return result as Recipe; }).then(result => { if (!abort.signal.aborted) setRecipe(result); }).catch(reason => { if (!abort.signal.aborted) setError(String(reason.message)); });
    return () => abort.abort();
  }, [serialized]);
  async function save() {
    if (!recipe || saving) return;
    setSaving(true); setError("");
    try {
      const response = await fetch("/api/recipes", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(recipe) });
      const result = await response.json();
      if (!response.ok) throw new Error(result.error || "Не удалось сохранить рецепт");
      setSaved(true);
      onOpen(result.id);
    } catch (reason) { setError(reason instanceof Error ? reason.message : "Не удалось сохранить рецепт"); }
    finally { setSaving(false); }
  }
  if (!recipe) return <p className={error ? "chat-error" : "recipe-note"} role={error ? "alert" : "status"}>{error || "Проверяю товары и цены…"}</p>;
  return <RecipeCard recipe={recipe} action={<><button className="recipe-action" disabled={saving} onClick={saved ? () => onOpen(recipe.id) : save}>{saving ? <LoaderCircle size={17} className="spin"/> : saved ? <Check size={17}/> : <ShoppingBasket size={17}/>} {saving ? "Сохраняю…" : saved ? "Открыть в «Моих рецептах»" : "Сформировать список"}</button>{saved && <p className="recipe-note" role="status">Рецепт и список продуктов сохранены.</p>}{error && <p className="chat-error" role="alert">{error}</p>}</>}/>;
}

export function RecipesScreen({ onChat, initialSelected }: { onChat: () => void; initialSelected?: string | null }) {
  const [recipes, setRecipes] = useState<Recipe[]>([]);
  const [selected, setSelected] = useState<string | null>(initialSelected || null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [tab, setTab] = useState<"shopping" | "steps">("shopping");
  async function load() {
    setLoading(true); setError("");
    try { const response = await fetch("/api/recipes"); if (!response.ok) throw new Error("Не удалось загрузить рецепты"); const result = await response.json(); setRecipes(result.recipes); }
    catch { setError("Не удалось загрузить рецепты. Попробуй ещё раз."); }
    finally { setLoading(false); }
  }
  useEffect(() => { load(); }, []);
  const recipe = recipes.find(item => item.id === selected);
  async function toggle(index: number) {
    if (!recipe || busy) return;
    const checked = recipe.checked || [];
    const next = checked.includes(index) ? checked.filter(i => i !== index) : [...checked, index];
    setBusy(true); setError("");
    try {
      const response = await fetch(`/api/recipes/${recipe.id}`, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ checked: next }) });
      if (!response.ok) throw new Error();
      setRecipes(previous => previous.map(item => item.id === recipe.id ? { ...item, checked: next } : item));
    } catch { setError("Не удалось сохранить отметку. Попробуй ещё раз."); }
    finally { setBusy(false); }
  }
  return <div className="recipes-page"><header><div><p className="eyebrow">ТВОЯ КУЛИНАРНАЯ КОЛЛЕКЦИЯ</p><h1>Мои рецепты</h1><p className="subtitle">Список покупок и приготовление — всегда под рукой</p></div></header>
    {error && <p className="chat-error" role="alert">{error} {!recipe && <button onClick={load}>Повторить</button>}</p>}
    {loading ? <p role="status">Загружаю рецепты…</p> : recipe ? <><button className="recipe-back" onClick={() => setSelected(null)}><ArrowLeft size={16}/> Все рецепты</button><RecipeCard recipe={recipe}><div className="recipe-tabs" role="tablist" aria-label="Рецепт"><button role="tab" aria-selected={tab === "shopping"} onClick={() => setTab("shopping")}>Список покупок</button><button role="tab" aria-selected={tab === "steps"} onClick={() => setTab("steps")}>Приготовление</button></div>{tab === "shopping" ? <div role="tabpanel" className="shopping-list">{[...new Set(recipe.ingredients.map(i => i.store_name))].map(store => <section key={store}><h3><StoreBadge name={store}/></h3>{recipe.ingredients.map((item, i) => item.store_name === store && <label key={i} className={(recipe.checked || []).includes(i) ? "bought" : ""}><input type="checkbox" disabled={busy} checked={(recipe.checked || []).includes(i)} onChange={() => toggle(i)}/><span><b>{item.name}</b><small>{item.packs} уп. · {item.package || "Размер не указан"}</small></span><strong>{money(item.price_rub === null ? null : item.price_rub * item.packs)}</strong></label>)}</section>)}<p className="recipe-note">Куплено {recipe.checked?.length || 0} из {recipe.ingredients.length}</p></div> : <ol role="tabpanel" className="recipe-steps">{recipe.steps.map((step, i) => <li key={i}>{step}</li>)}</ol>}</RecipeCard></> : recipes.length ? <div className="saved-recipe-grid">{recipes.map(item => <button className="saved-recipe" key={item.id} onClick={() => { setSelected(item.id); setTab("shopping"); }}><ChefHat size={26}/><h2>{item.title}</h2><p>{item.minutes} мин · {item.servings} порц. · {item.ingredients.length} продуктов</p><div>{[...new Set(item.ingredients.map(i => i.store_name))].map(name => <StoreBadge key={name} name={name}/>)}</div><strong>{money(item.total_rub)}</strong><span>Открыть рецепт →</span></button>)}</div> : !error && <section className="recipes-empty panel"><ChefHat size={42}/><h2>Здесь будут твои рецепты</h2><p>Попроси Avelin подобрать блюдо из каталога и нажми «Сформировать список» под карточкой.</p><button className="recipe-action" onClick={onChat}>Подобрать рецепт с Avelin</button></section>}
  </div>;
}
