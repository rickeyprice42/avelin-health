import vm from "node:vm";
import fs from "node:fs";
import assert from "node:assert/strict";
import { webcrypto } from "node:crypto";

let stored={token:"local-test-token"};
let receiver;let startup;let nextId=10;
const tabs=new Map([[1,{id:1,url:"https://web.kuper.ru/pyaterochka/c?sid=123",status:"complete"}]]);
const requests=[],scripts=[];
const chrome={
  storage:{local:{async get(keys){const selected={};for(const key of Array.isArray(keys)?keys:[keys])selected[key]=structuredClone(stored[key]);return selected;},async set(value){Object.assign(stored,structuredClone(value));}}},
  tabs:{async get(id){if(!tabs.has(id))throw new Error("Closed tab");return tabs.get(id);},async create(value){const tab={...value,id:nextId++,status:"complete"};tabs.set(tab.id,tab);return tab;},async update(id,value){Object.assign(tabs.get(id),value);return tabs.get(id);},async remove(id){tabs.delete(id);},onUpdated:{addListener(){}},onRemoved:{addListener(){}}},
  scripting:{async executeScript(value){scripts.push(value);return [];}},
  runtime:{onMessage:{addListener(value){receiver=value;}},onStartup:{addListener(value){startup=value;}},onInstalled:{addListener(){}}}
};
const entry={url:"https://kuper.ru/products/1-milk",refs:[{id:"1",магазин_id:"123"}]};
const context=vm.createContext({chrome,URL,crypto:webcrypto,AbortSignal,Date,console,fetch:async(url,options)=>{
  requests.push({url,options});
  assert.equal(options.headers["X-Avelin-Token"],"local-test-token");
  return {ok:true,json:async()=>url.endsWith("/queues")?{kuper:{format:"nutrition-queue-v1",site:"kuper",entries:[entry]},fixprice:{entries:[]}}:{ok:true,output:"test-folder"}};
}});
vm.runInContext(fs.readFileSync(new URL("./extension/background.js",import.meta.url),"utf8"),context);
const message=(value,sender={})=>new Promise(resolve=>receiver(value,sender,resolve));
assert.equal((await message({action:"start",tabIds:[1]})).ok,true);
assert.equal(stored.state.job.kind,"catalog");assert.equal(stored.state.plan.length,2);
assert.equal((await message({action:"start",tabIds:[1]})).error,"Сбор уже выполняется");
let job=stored.state.job;
await message({event:"result",id:job.id,payload:{kind:"kuper",data:{log:{entries:[]}}}},{tab:{id:999}});
assert.equal(stored.state.index,0,"Wrong sender must not change the run");
await message({event:"result",id:job.id,payload:{kind:"kuper",data:{log:{entries:[]}}}},{tab:{id:job.tabId}});
assert.equal(stored.state.job.kind,"nutrition");
job=stored.state.job;
const pack={format:"nutrition-batch-v1",site:"kuper",parser_version:"nutrition-v2",results:[],remaining:[entry],stats:{processed:10,found:0}};
await message({event:"checkpoint",id:job.id,payload:pack},{tab:{id:job.tabId}});
assert.equal(stored.state.job.pack.stats.processed,10);
assert.equal(requests.filter(request=>request.url.endsWith("/nutrition")).length,0);
await message({event:"result",id:job.id,payload:{...pack,stats:{...pack.stats,blocked:true}}},{tab:{id:job.tabId}});
assert.equal(stored.state.status,"Требуется продолжение");
await message({action:"resume"});
job=stored.state.job;
assert.equal(job.pack.remaining.length,1,"Resume must retain unprocessed cards");
await message({event:"result",id:job.id,payload:{...pack,remaining:[],stats:{processed:1,found:1}}},{tab:{id:job.tabId}});
assert.equal(stored.state.status,"Завершено");assert.equal(stored.state.job,null);
assert.equal(requests.filter(request=>request.url.endsWith("/capture")).length,1);
assert.ok(!scripts.some(script=>(script.args||[]).includes("local-test-token")),"Pairing key must never be injected into a store page");
assert.equal((await message({action:"start",tabIds:[1]},{tab:{id:1}})).error,"Команда доступна только из окна расширения");
console.log("OK: extension queue, authenticated bridge, pause/resume and sender checks");
