const BASE="http://127.0.0.1:8767";
let serial=Promise.resolve();
async function api(path,payload){
  const {token}=await chrome.storage.local.get("token");
  const response=await fetch(BASE+path,{method:payload?"POST":"GET",headers:{"X-Avelin-Token":token||"",...(payload?{"Content-Type":"application/json"}:{})},...(payload?{body:JSON.stringify(payload)}:{}),signal:AbortSignal.timeout(120000)});
  const result=await response.json();if(!response.ok)throw new Error(result.error||"Локальный помощник недоступен");return result;
}
async function save(state){state.updated=Date.now();await chrome.storage.local.set({state});}
async function fail(error){const {state}=await chrome.storage.local.get("state");if(state?.job){state.status="Требуется продолжение";state.error=String(error.message||error);await save(state);}}
const siteFor=url=>new URL(url).hostname==="web.kuper.ru"?"kuper":"fixprice";

async function launch(state){
  if(state.index>=state.plan.length){state.job=null;state.status=Object.values(state.packs||{}).some(pack=>pack.remaining?.length)?"Завершено; часть карточек без КБЖУ":"Завершено";await save(state);return;}
  const task=state.plan[state.index];
  if(task.kind==="nutrition"&&!task.pack){const queues=await api("/queues"+(state.refresh?"?refresh=1":""));task.pack=queues[task.site];}
  const pack=state.job?.kind==="nutrition"&&state.job.site===task.site?state.job.pack:task.pack;
  const entries=pack?.remaining||pack?.entries||[];
  if(task.kind==="nutrition"&&!entries.length){state.index++;state.job=null;await launch(state);return;}
  let tab;
  if(task.kind==="nutrition"){
    const url=entries[0].url;
    const parsed=new URL(url);
    if(parsed.protocol!=="https:"||!["kuper.ru","fix-price.com"].includes(parsed.hostname))throw new Error("Неподдерживаемая карточка");
    try{if(state.job?.tabId)tab=await chrome.tabs.get(state.job.tabId);}catch{}
    if(tab)await chrome.tabs.update(tab.id,{url});
    else tab=await chrome.tabs.create({url,active:false});
  }else if(task.site==="slata"){
    tab=await chrome.tabs.create({url:"https://shop.slata.com/catalog",active:false});
  }else{
    tab=await chrome.tabs.get(task.tabId);
    if(task.site==="fixprice"&&!tab.url.includes("/catalog/produkty-i-napitki")){await chrome.tabs.update(tab.id,{url:"https://fix-price.com/catalog/produkty-i-napitki"});}
  }
  state.job={...task,pack,id:crypto.randomUUID(),tabId:tab.id};state.status="Выполняется";state.error="";await save(state);
  const current=await chrome.tabs.get(tab.id);
  if(current.status==="complete")await inject(state.job);
}

async function inject(job){
  const {state}=await chrome.storage.local.get("state");
  if(!state||state.job?.id!==job.id||state.status!=="Выполняется"||state.job.injected)return;
  state.job.injected=true;await save(state);
  if(job.kind==="nutrition"){
    await chrome.scripting.executeScript({target:{tabId:job.tabId},world:"ISOLATED",func:(id,pack)=>{
      window.__AVELIN_COLLECTOR__={pack,automatic:true,
        onCheckpoint:async payload=>{if(payload.stats.processed%10===0){const result=await chrome.runtime.sendMessage({event:"checkpoint",id,payload});if(result?.error)throw new Error(result.error);}},
        onResult:payload=>chrome.runtime.sendMessage({event:"result",id,payload}),
        onError:error=>chrome.runtime.sendMessage({event:"error",id,error})};
    },args:[job.id,job.pack]});
    chrome.scripting.executeScript({target:{tabId:job.tabId},files:["collectors/nutrition_bookmarklet.js"]}).catch(fail);
  }else{
    // Only catalog captures cross this bridge; the pairing key stays isolated.
    await chrome.scripting.executeScript({target:{tabId:job.tabId},world:"ISOLATED",func:id=>{
      if(window.__avelinBridge)window.removeEventListener("message",window.__avelinBridge);
      window.__avelinBridge=event=>{
        const value=event.data;if(event.source!==window||value?.channel!=="avelin-catalog"||value.id!==id||!["result","error"].includes(value.event))return;
        chrome.runtime.sendMessage({event:value.event,id,payload:value.payload,error:value.error});
      };window.addEventListener("message",window.__avelinBridge);
    },args:[job.id]});
    await chrome.scripting.executeScript({target:{tabId:job.tabId},world:"MAIN",func:(id,storeName)=>{
      window.__AVELIN_COLLECTOR__={automatic:true,storeName,
        onResult:payload=>window.postMessage({channel:"avelin-catalog",id,event:"result",payload},location.origin),
        onError:error=>window.postMessage({channel:"avelin-catalog",id,event:"error",error},location.origin)};
    },args:[job.id,job.storeName||""]});
    chrome.scripting.executeScript({target:{tabId:job.tabId},world:"MAIN",files:[`collectors/${job.site}_bookmarklet.js`]}).catch(fail);
  }
}

async function handle(message,sender){
  if(message.event){
    const {state}=await chrome.storage.local.get("state");
    if(!state||state.job?.id!==message.id||sender.tab?.id!==state.job.tabId)return;
    if(message.event==="error"){await fail(message.error);return;}
    if(state.job.kind==="nutrition"){
      state.job.pack=message.payload;state.packs[state.job.site]=message.payload;await save(state);
      if(message.event==="checkpoint"){
        if(message.payload.stats.processed%50===0)await api("/nutrition",message.payload);
        return {ok:true};
      }
      await api("/nutrition",message.payload);
      if(message.payload.stats.blocked||message.payload.stats.stopped||message.payload.stats.probe_stopped){state.status="Требуется продолжение";state.error="Сбор приостановлен. Проверьте рабочую вкладку; прогресс сохранён.";state.job.injected=false;await save(state);return;}
    }else{await api("/capture",message.payload);}
    const completedTab=state.job.kind==="nutrition"||state.job.site==="slata"?state.job.tabId:null;
    state.index++;state.job=null;await save(state);
    if(completedTab)await chrome.tabs.remove(completedTab).catch(()=>{});
    await launch(state);return {ok:true};
  }
  if(sender.tab)throw new Error("Команда доступна только из окна расширения");
  if(message.action==="connect")return api("/status");
  const {state:previous}=await chrome.storage.local.get("state");
  if(message.action==="stop"){
    if(previous?.job){
      await chrome.scripting.executeScript({target:{tabId:previous.job.tabId},world:previous.job.kind==="nutrition"?"ISOLATED":"MAIN",func:()=>{if(window.__AVELIN_COLLECTOR__)window.__AVELIN_COLLECTOR__.stopped=true;}});
      previous.status="Останавливается";await save(previous);
    }return {ok:true};
  }
  if(previous?.status==="Выполняется"||previous?.status==="Останавливается")throw new Error("Сбор уже выполняется");
  await api("/status");
  if(message.action==="resume"){
    if(!previous)throw new Error("Нет сохранённого сбора");
    if(previous.job){previous.job.injected=false;await launch(previous);}
    else{
      const plan=Object.entries(previous.packs||{}).filter(([,pack])=>pack.remaining?.length).map(([site,pack])=>({kind:"nutrition",site,pack}));
      if(!plan.length)throw new Error("Необработанных карточек нет");
      await launch({plan,index:0,packs:previous.packs,job:null});
    }return {ok:true};
  }
  let plan=[];
  if(message.action==="start"){
    for(const id of message.tabIds||[]){
      const tab=await chrome.tabs.get(id),site=siteFor(tab.url),url=new URL(tab.url);
      if(!["web.kuper.ru","fix-price.com"].includes(url.hostname))throw new Error("Неподдерживаемая вкладка");
      if(site==="kuper"&&!/^\d+$/.test(url.searchParams.get("sid")||""))throw new Error("В Kuper сначала выберите магазин и адрес доставки");
      const storeName=/hleb|sol/i.test(url.pathname)?"Хлеб&Соль":/pyat|5ka|five/i.test(url.pathname)?"Пятёрочка":"";
      if(site==="kuper"&&!storeName)throw new Error("Выберите вкладку Пятёрочки или Хлеб&Соли");
      plan.push({kind:"catalog",site,tabId:id,storeName});
    }
    if(message.slata)plan.push({kind:"catalog",site:"slata"});
    if(!plan.length)throw new Error("Откройте и отметьте вкладки магазинов");
    const sites=[...new Set(plan.map(task=>task.site).filter(site=>site!=="slata"))];plan.push(...sites.map(site=>({kind:"nutrition",site})));
  }else if(message.action==="nutrition"){plan=[{kind:"nutrition",site:"kuper"},{kind:"nutrition",site:"fixprice"}];}
  else throw new Error("Неизвестная команда");
  await launch({plan,index:0,packs:{},job:null,refresh:!!message.refresh});return {ok:true};
}

chrome.runtime.onMessage.addListener((message,sender,respond)=>{
  serial=serial.catch(()=>{}).then(()=>handle(message,sender));
  serial.then(value=>respond(value||{ok:true}),async error=>{await fail(error);respond({error:error.message});});return true;
});
chrome.tabs.onUpdated.addListener((tabId,change)=>{
  if(change.status!=="complete")return;
  serial=serial.catch(()=>{}).then(async()=>{const {state}=await chrome.storage.local.get("state");if(state?.job?.tabId===tabId&&state.status==="Выполняется")await inject(state.job);}).catch(fail);
});
chrome.tabs.onRemoved.addListener(tabId=>{
  serial=serial.catch(()=>{}).then(async()=>{const {state}=await chrome.storage.local.get("state");if(state?.job?.tabId===tabId&&state.status==="Выполняется")await fail("Рабочая вкладка закрыта. Нажмите «Продолжить».");});
});
chrome.runtime.onStartup.addListener(()=>{fail("Браузер перезапущен. Нажмите «Продолжить», чтобы возобновить сохранённый сбор.");});
chrome.runtime.onInstalled.addListener(()=>{fail("Расширение перезагружено. Нажмите «Продолжить», чтобы возобновить сохранённый сбор.");});
