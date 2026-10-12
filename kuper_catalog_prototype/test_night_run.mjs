import vm from "node:vm";
import fs from "node:fs";
import assert from "node:assert/strict";
const source=fs.readFileSync(new URL("./nutrition_bookmarklet.js",import.meta.url),"utf8");
async function run({stopAt=0,blocked=false}={}){
  let result,checkpoints=0;
  const entries=Array.from({length:261},(_,i)=>({url:`https://kuper.ru/products/${i}-milk`,refs:[{id:String(i),магазин_id:"test"}]}));
  const options={pack:{format:"nutrition-queue-v1",site:"kuper",entries},onCheckpoint:async pack=>{checkpoints++;if(stopAt&&pack.stats.processed>=stopAt)options.stopped=true;},onResult:async pack=>{result=pack;},onError:error=>{throw new Error(error);}};
  const element=()=>({style:{},textContent:"",innerHTML:"",remove(){},querySelector(){return element();}});
  const data={protein:3,fat:2.5,carbs:4.7,kcal:53};
  const context=vm.createContext({
    window:{__AVELIN_COLLECTOR__:options},location:{hostname:"kuper.ru"},URL,AbortSignal,console,
    document:{createElement:element,body:{appendChild(){}}},
    DOMParser:class{parseFromString(){return {body:{innerText:"Пищевая ценность на 100 мл",childNodes:[]},querySelectorAll:query=>query==="script"?[{type:"application/ld+json",textContent:JSON.stringify(data)}]:[]};}},
    fetch:async()=>({status:blocked?403:200,ok:!blocked,text:async()=>"<html>"+" ".repeat(1500)+"</html>"}),
    setTimeout:callback=>{queueMicrotask(callback);return 0;},clearTimeout(){},alert:message=>{throw new Error("Unexpected prompt: "+message);}
  });
  await vm.runInContext(source,context);
  return {result,checkpoints};
}
const all=await run();
assert.equal(all.result.stats.processed,261);assert.equal(all.result.results.length,261);assert.equal(all.result.remaining.length,0);
assert.ok(all.checkpoints>=261,"Progress must be checkpointed while collecting");
const stopped=await run({stopAt:10});
assert.equal(stopped.result.stats.processed,10);assert.equal(stopped.result.remaining.length,251);assert.equal(stopped.result.stats.stopped,true);
const blocked=await run({blocked:true});
assert.equal(blocked.result.stats.processed,1);assert.equal(blocked.result.remaining.length,261);assert.equal(blocked.result.stats.blocked,true);
console.log("OK: 261-card overnight run, checkpoints, stop and access-check interruption");
