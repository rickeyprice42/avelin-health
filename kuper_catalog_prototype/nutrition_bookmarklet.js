(async()=>{
  const QUEUE="nutrition-queue-v1",BATCH="nutrition-batch-v1";
  const sleep=ms=>new Promise(r=>setTimeout(r,ms));
  const host=location.hostname.toLowerCase().replace(/^www\./,"");
  const kuperCatalog=host==="web.kuper.ru";
  const site=host==="kuper.ru"||host==="sbermarket.ru"||kuperCatalog?"kuper":host==="fix-price.com"?"fixprice":"";
  if(!site){alert("Откройте обычную страницу web.kuper.ru, kuper.ru или fix-price.com и снова нажмите закладку «Собрать КБЖУ».");return;}

  const input=document.createElement("input");
  input.type="file";input.accept=".json,application/json";input.style.display="none";
  document.body.appendChild(input);input.click();
  const file=await new Promise(resolve=>{input.onchange=()=>resolve(input.files&&input.files[0]);setTimeout(()=>resolve(null),120000);});
  input.remove();if(!file)return;

  let pack;
  try{pack=JSON.parse(await file.text());}catch(e){alert("Не удалось прочитать JSON: "+e.message);return;}
  if(!pack||![QUEUE,BATCH].includes(pack.format)||pack.site!==site){
    alert("Выбран не тот файл очереди. Для этой вкладки нужен пакет «"+(site==="kuper"?"Kuper":"Fix Price")+"».");return;
  }
  let remaining=(pack.format===QUEUE?pack.entries:pack.remaining)||[];
  const prior=pack.format===BATCH&&Array.isArray(pack.results)?pack.results:[];
  if(!remaining.length){alert("В этом пакете больше нет необработанных карточек.");return;}
  if(kuperCatalog){
    const target=remaining.find(item=>item&&/^https:\/\/kuper\.ru\/products\//i.test(item.url));
    if(!target){alert("В выбранной очереди нет подходящих карточек Kuper.");return;}
    alert("Сейчас откроется публичная карточка товара на kuper.ru. Когда она загрузится, ещё раз нажмите закладку «Собрать КБЖУ» и выберите этот же файл очереди.");
    location.href=target.url;
    return;
  }
  const raw=prompt("Сколько карточек обработать сейчас? Сначала скрипт проверит 8 карточек и сам остановится, если КБЖУ не читаются.",String(Math.min(50,remaining.length)));
  if(raw===null)return;
  const limit=Math.max(1,Math.min(250,parseInt(raw,10)||50,remaining.length));

  const overlay=document.createElement("div");
  overlay.style="position:fixed;z-index:2147483647;right:18px;bottom:18px;width:390px;padding:18px 20px;border-radius:14px;background:#17212bf2;color:white;font:15px/1.45 system-ui;box-shadow:0 12px 42px #0008";
  overlay.innerHTML="<b style='font-size:18px'>Сбор КБЖУ</b><div id='kbju-progress' style='margin-top:8px'>Подготовка…</div><div style='height:8px;background:#ffffff25;border-radius:9px;margin-top:12px;overflow:hidden'><div id='kbju-bar' style='height:100%;width:0;background:#28d17c'></div></div>";
  document.body.appendChild(overlay);
  const progress=overlay.querySelector("#kbju-progress"),bar=overlay.querySelector("#kbju-bar");
  let done=0,ok=0;
  const update=()=>{progress.textContent=`Обработано ${done} из ${limit} · найдено ${ok}`;bar.style.width=`${Math.round(done/limit*100)}%`;};
  update();

  const clean=s=>String(s||"").replace(/\u00a0/g," ").replace(/[ \t]+/g," ").replace(/\n\s+/g,"\n").trim();
  const nodeText=node=>{
    if(!node)return "";
    const rendered=typeof node.innerText==="string"?node.innerText:"";
    if(rendered.trim())return rendered;
    const blocks=new Set(["ADDRESS","ARTICLE","ASIDE","BLOCKQUOTE","DD","DIV","DL","DT","FIELDSET","FIGCAPTION","FIGURE","FOOTER","FORM","H1","H2","H3","H4","H5","H6","HEADER","HR","LI","MAIN","NAV","OL","P","PRE","SECTION","TABLE","TBODY","TD","TFOOT","TH","THEAD","TR","UL"]),skip=new Set(["SCRIPT","STYLE","TEMPLATE","SVG","NOSCRIPT"]),parts=[];
    const walk=current=>{
      if(current.nodeType===3){parts.push(current.nodeValue||"");return;}
      if(current.nodeType!==1)return;
      const tag=current.tagName||"";if(skip.has(tag))return;
      if(tag==="BR"){parts.push("\n");return;}
      if(blocks.has(tag))parts.push("\n");
      for(const child of current.childNodes)walk(child);
      if(blocks.has(tag))parts.push("\n");
    };
    walk(node);return parts.join("").replace(/\r/g,"").replace(/[ \t]+/g," ").replace(/ *\n */g,"\n").replace(/\n{3,}/g,"\n\n").trim();
  };
  const tokenText=node=>{
    if(!node)return "";
    const skip=new Set(["SCRIPT","STYLE","TEMPLATE","SVG","NOSCRIPT"]),parts=[];
    const walk=current=>{
      if(current.nodeType===3){const value=clean(current.nodeValue);if(value)parts.push(value);return;}
      if(current.nodeType!==1||skip.has(current.tagName||""))return;
      for(const child of current.childNodes)walk(child);
    };
    walk(node);return parts.join("\n");
  };
  const inspectHtml=(html,url,stage)=>{
    try{
      const doc=new DOMParser().parseFromString(html,"text/html");
      const body=tokenText(doc.body);
      const heading=body.search(/пищевая\s+ценность/i);
      const start=heading>=0?Math.max(0,heading-120):0;
      return {
        url,stage,html_length:String(html||"").length,title:clean(doc.title).slice(0,180),
        has_nutrition_heading:heading>=0,has_protein:/белк/i.test(body),has_fat:/жир/i.test(body),
        has_carbohydrate:/углевод/i.test(body),has_kcal:/(ккал|калор)/i.test(body),
        text_sample:body.slice(start,start+1200)
      };
    }catch(_){return {url,stage,html_length:String(html||"").length,diagnostic_error:"Не удалось разобрать HTML"};}
  };
  const num=v=>{
    if(v&&typeof v==="object")v=v.value??v.amount??v.per100g??v.per100ml;
    if(typeof v==="number")return Number.isFinite(v)?v:null;
    const m=String(v??"").replace(",",".").match(/-?\d+(?:\.\d+)?/);return m?Number(m[0]):null;
  };
  const validationIssue=d=>{
    if(!d||!["белки","жиры","углеводы","ккал"].every(k=>typeof d[k]==="number"&&Number.isFinite(d[k])))return "неполный комплект КБЖУ";
    if(Math.min(d.белки,d.жиры,d.углеводы,d.ккал)<0)return "отрицательное значение";
    if(Math.max(d.белки,d.жиры,d.углеводы)>100)return "макронутриент больше 100 г";
    if(d.белки+d.жиры+d.углеводы>105)return "сумма БЖУ больше 105 г";
    if(d.ккал>1000)return "калорийность больше 1000 ккал";
    const expected=4*d.белки+9*d.жиры+4*d.углеводы;
    if(expected<=12&&d.ккал<=12)return "";
    if(expected<=0)return "калорийность не подтверждается макронутриентами";
    const ratio=d.ккал/expected;
    if(ratio>=3.7&&ratio<=4.6)return "похоже на кДж вместо ккал";
    if(Math.abs(d.ккал-expected)>Math.max(25,expected*.30))return "калорийность не согласуется с БЖУ";
    return "";
  };
  const valid=d=>!validationIssue(d);
  const normKey=k=>String(k).toLowerCase().replace(/[^a-zа-яё0-9]/g,"");
  const aliases={
    белки:["protein","proteins","protein100g","proteins100g","proteincontent","белки","белок"],
    жиры:["fat","fats","fat100g","fats100g","fatcontent","жиры","жир"],
    углеводы:["carbohydrate","carbohydrates","carbohydrate100g","carbohydrates100g","carbs","carbs100g","углеводы"],
    ккал:["kcal","calories","calorie","calories100g","energykcal100g","energykcal","caloricvalue","калории","калорийность","ккал"]
  };
  const fromObject=root=>{
    const stack=[root],seen=new Set();let visited=0;
    while(stack.length&&visited++<80000){
      const obj=stack.pop();if(!obj||typeof obj!=="object"||seen.has(obj))continue;seen.add(obj);
      if(!Array.isArray(obj)){
        const values={};
        for(const [key,value] of Object.entries(obj)){
          const nk=normKey(key);
          for(const [target,names] of Object.entries(aliases))if(names.includes(nk)&&values[target]===undefined)values[target]=num(value);
        }
        if(valid(values))return values;
      }
      for(const value of Object.values(obj))if(value&&typeof value==="object")stack.push(value);
    }
    return null;
  };
  const extractJson=doc=>{
    for(const script of doc.querySelectorAll("script")){
      const text=script.textContent.trim();if(!text||text.length>15000000)continue;
      if(script.type==="application/ld+json"||text[0]==="{"||text[0]==="["){
        try{const found=fromObject(JSON.parse(text));if(found)return found;}catch(_){ }
      }
    }
    return null;
  };
  const labelKind=line=>/^\s*(?:ккал|калор)/i.test(line)?"ккал":/^\s*белк/i.test(line)?"белки":/^\s*жир/i.test(line)?"жиры":/^\s*углевод/i.test(line)?"углеводы":"";
  const numericValue=line=>{
    const m=String(line||"").replace(",",".").match(/(?:^|\s)(\d+(?:\.\d+)?)(?:\s*(?:г|ккал|кдж|kj))?(?:\s|$)/i);
    return m?Number(m[1]):null;
  };
  const parseNutritionSection=text=>{
    const source=String(text||"").replace(/\r/g,"");
    const heading=source.search(/пищевая\s+ценность/i);if(heading<0)return null;
    let section=source.slice(heading,heading+1400);
    const afterHeading=section.search(/\n\s*(?:бренд|артикул|состав|общая информация|характеристики|описание|адрес производителя|все характеристики)\b/i);
    if(afterHeading>20)section=section.slice(0,afterHeading);
    const lines=section.split(/\n+/).map(clean).filter(Boolean);
    const labels=[];
    lines.forEach((line,index)=>{const kind=labelKind(line);if(kind&&!labels.some(x=>x.kind===kind))labels.push({kind,index,line});});
    if(labels.length<3||!labels.some(x=>x.kind==="ккал"))return null;

    const candidate=values=>{
      const missing=["белки","жиры","углеводы"].filter(key=>typeof values[key]!=="number");
      if(missing.length===1&&typeof values.ккал==="number"){
        const inferred={...values,[missing[0]]:0};
        if(valid(inferred))return {...inferred,кбжу_на:/100\s*мл/i.test(section)?"100 мл":"100 г",кбжу_ноль_восстановлен:missing[0]};
      }
      if(["белки","жиры","углеводы","ккал"].every(key=>typeof values[key]==="number"))return {...values,кбжу_на:/100\s*мл/i.test(section)?"100 мл":"100 г"};
      return null;
    };

    const paired={};
    for(const label of labels){
      const inline=numericValue(label.line.replace(/.*?(?:ккал|калорийность|белки?|жиры?|углеводы?)/i,""));
      if(inline!==null){paired[label.kind]=inline;continue;}
      for(let i=label.index+1;i<Math.min(lines.length,label.index+4);i++){
        if(labelKind(lines[i]))break;
        const value=numericValue(lines[i]);if(value!==null){paired[label.kind]=value;break;}
      }
    }
    const pairedCandidate=candidate(paired);if(pairedCandidate)return pairedCandidate;

    if(labels.length<4)return null;
    const lastLabel=Math.max(...labels.map(x=>x.index));
    const values=[];
    for(const line of lines.slice(lastLabel+1)){
      if(labelKind(line))continue;
      const value=numericValue(line);if(value!==null)values.push(value);
      if(values.length===4)break;
    }
    if(values.length<4)return null;
    const grouped={};labels.slice(0,4).forEach((label,index)=>{grouped[label.kind]=values[index];});
    return candidate(grouped);
  };
  const fromText=(doc)=>{
    const nodes=[...doc.querySelectorAll("body *")].filter(el=>{
      if(["SCRIPT","STYLE","TEMPLATE","SVG","NOSCRIPT"].includes(el.tagName))return false;
      const t=el.textContent||"";return t.length>=20&&t.length<12000&&/пищевая\s+ценность/i.test(t)&&/белк/i.test(t)&&/углевод/i.test(t)&&/(ккал|калор)/i.test(t);
    }).sort((a,b)=>(a.textContent||"").length-(b.textContent||"").length);
    for(const el of nodes.slice(0,60)){const found=parseNutritionSection(tokenText(el));if(found)return found;}
    const whole=parseNutritionSection(tokenText(doc.body));if(whole)return whole;
    return null;
  };
  const composition=doc=>{
    const nodes=[...doc.querySelectorAll("body *")].filter(el=>{if(["SCRIPT","STYLE","TEMPLATE","SVG","NOSCRIPT"].includes(el.tagName))return false;const t=el.textContent||"";return t.length>7&&t.length<12000&&/состав/i.test(t);}).sort((a,b)=>(a.textContent||"").length-(b.textContent||"").length);
    for(const el of nodes.slice(0,30)){
      let t=clean(nodeText(el)),m=t.match(/(?:^|\n)\s*состав\s*[:\n]\s*([\s\S]+)/i);if(!m)continue;
      t=m[1].split(/\n\s*(?:общая информация|характеристики|производитель|адрес производителя|все характеристики|условия хранения)\b/i)[0].trim();
      if(t.length>=3)return t.slice(0,4000);
    }
    return "";
  };
  const parseHtml=(html,url)=>{
    const doc=new DOMParser().parseFromString(html,"text/html");
    let d=fromText(doc)||extractJson(doc);const issue=validationIssue(d);if(issue)throw new Error("КБЖУ отклонены: "+issue);
    const body=clean(nodeText(doc.body)),basis=d.кбжу_на||(/100\s*мл/i.test(body)?"100 мл":"100 г");
    return {...d,кбжу_на:basis,источник_кбжу:site==="kuper"?"карточка Kuper":"карточка Fix Price",кбжу_статус:"проверено автоматически",кбжу_парсер:"nutrition-v2",состав:composition(doc),ссылка_источника:url};
  };
  const frameCard=url=>new Promise((resolve,reject)=>{
    let settled=false;
    const frame=document.createElement("iframe");
    frame.style="position:fixed;left:-10000px;top:-10000px;width:1200px;height:900px;opacity:0;pointer-events:none";
    const finish=(error,value)=>{if(settled)return;settled=true;clearTimeout(timer);frame.remove();error?reject(error):resolve(value);};
    const timer=setTimeout(()=>finish(new Error("карточка не загрузилась за 45 секунд")),45000);
    frame.onload=async()=>{
      try{
        await sleep(2200);
        const doc=frame.contentDocument;
        if(!doc||!doc.documentElement)throw new Error("страница карточки недоступна во фрейме");
        const html=doc.documentElement.outerHTML;
        try{finish(null,parseHtml(html,url));}
        catch(e){e.diagnostic=inspectHtml(html,url,"iframe");finish(e);}
      }catch(e){finish(e);}
    };
    frame.onerror=()=>finish(new Error("ошибка открытия карточки"));
    document.body.appendChild(frame);frame.src=url;
  });
  const fetchCard=async url=>{
    let last="",lastDiagnostic=null;
    for(let attempt=1;attempt<=3;attempt++){
      let html="";
      try{
        const response=await fetch(url,{credentials:"include",cache:"no-store",headers:{Accept:"text/html,application/xhtml+xml"}});
        if(!response.ok)throw new Error("HTTP "+response.status);
        html=await response.text();if(html.length<1000)throw new Error("пустой ответ");
        return parseHtml(html,url);
      }catch(e){last=e.message||String(e);if(html)lastDiagnostic=inspectHtml(html,url,"fetch");if(attempt<3)await sleep(900*attempt);}
    }
    try{return await frameCard(url);}catch(e){const error=new Error((last?last+"; ":"")+(e.message||"карточка недоступна"));error.diagnostic=e.diagnostic||lastDiagnostic;throw error;}
  };

  const batch=remaining.slice(0,limit),later=remaining.slice(limit),success=[],failed=[];
  const diagnostics=[];
  const processEntries=async entries=>{
    let cursor=0;
    const worker=async()=>{
      while(true){
        const index=cursor++;if(index>=entries.length)return;
        const entry=entries[index];
        try{const data=await fetchCard(entry.url);success.push({...entry,status:"ok",captured_at:new Date().toISOString(),data});ok++;}
        catch(e){
          failed.push({...entry,попыток:Number(entry.попыток||0)+1,последняя_ошибка:String(e&&e.message||e||"неизвестная ошибка").slice(0,300)});
          if(e&&e.diagnostic&&diagnostics.length<8)diagnostics.push({...e.diagnostic,name:entry.name||entry.название||"",error:String(e.message||e).slice(0,300)});
        }
        done++;update();await sleep(250);
      }
    };
    await Promise.all(Array.from({length:Math.min(2,entries.length)},worker));
  };
  const probeSize=Math.min(8,batch.length);
  await processEntries(batch.slice(0,probeSize));
  const probeFailed=ok===0&&!diagnostics.some(item=>item&&item.has_nutrition_heading);
  if(!probeFailed)await processEntries(batch.slice(probeSize));
  const untouched=probeFailed?batch.slice(probeSize):[];
  remaining=[...untouched,...later,...failed];
  const output={format:BATCH,parser_version:"nutrition-v2",site,created_at:new Date().toISOString(),results:[...prior,...success],remaining,diagnostics,stats:{processed:done,found:ok,failed:failed.length,total_results:prior.length+success.length,remaining:remaining.length,probe_stopped:probeFailed}};
  const blob=new Blob([JSON.stringify(output,null,2)],{type:"application/json;charset=utf-8"}),a=document.createElement("a");
  a.href=URL.createObjectURL(blob);a.download=`${probeFailed?"КБЖУ диагностика":"КБЖУ пакет"} ${site==="kuper"?"Kuper":"Fix Price"} ${new Date().toISOString().slice(0,10)}.json`;a.click();setTimeout(()=>URL.revokeObjectURL(a.href),30000);
  progress.textContent=probeFailed?`Остановлено после проверки ${probeSize} карточек: найдено 0. Диагностика скачана.`:`Готово: найдено ${ok}, осталось ${remaining.length}. Файл скачан.`;bar.style.width="100%";
  setTimeout(()=>overlay.remove(),15000);
  if(probeFailed){alert(`Сбор автоматически остановлен после ${probeSize} карточек: КБЖУ не найдены ни в одной. Скачан файл «КБЖУ диагностика …json». Ничего импортировать не нужно — передайте этот файл мне для исправления.`);return;}
  alert(remaining.length?`Пакет скачан. Найдено новых карточек: ${ok}. Осталось: ${remaining.length}.\n\nЧтобы продолжить, снова нажмите закладку и выберите только что скачанный пакет.`:`Все карточки обработаны. Пакет скачан — импортируйте его в программу.`);
})().catch(e=>alert("Сбор КБЖУ остановлен: "+(e&&e.message?e.message:e)));
