(async()=>{
  const options=window.__AVELIN_COLLECTOR__||{};
  const categories=["ovoschi-frukty-griby-zelen","moloko-syr-yaytsa","myaso-ptitsa-delikatesy","hleb-i-vypechka","bakaleya","soki-vody-napitki","sladosti-i-sneki","gotovaya-eda","ryba-i-moreprodukty","zamorozhennye-produkty","kofe-chay-kakao"];
  const sleep=ms=>new Promise(resolve=>setTimeout(resolve,ms));
  if(location.hostname!=="shop.slata.com")throw new Error("Откройте shop.slata.com/catalog");
  const pages=[];
  function unpack(values){
    const cache=new Map();
    const ref=index=>{if(typeof index!=="number")return index;if(index<0)return null;if(cache.has(index))return cache.get(index);cache.set(index,null);const value=hydrate(values[index]);cache.set(index,value);return value;};
    const hydrate=value=>Array.isArray(value)?["ShallowReactive","Reactive","Ref","ShallowRef","EmptyRef"].includes(value[0])?ref(value[1]):value.map(ref):value&&typeof value==="object"?Object.fromEntries(Object.entries(value).map(([key,index])=>[key,ref(index)])):value;
    return ref(0);
  }
  function find(value){if(!value||typeof value!=="object")return null;if(Array.isArray(value.products)&&"pageCount"in value&&"count"in value)return value;for(const child of Object.values(value)){const found=find(child);if(found)return found;}return null;}
  async function get(category,page){
    const url=new URL("/catalog/"+category,location.origin);if(page>1)url.searchParams.set("page",page);
    for(let attempt=1;attempt<=3;attempt++){
      if(options.stopped)throw new Error("Сбор остановлен пользователем");
      const response=await fetch(url,{credentials:"include",cache:"no-store",signal:AbortSignal.timeout(60000)});
      if([401,403,429].includes(response.status))throw new Error("Слата: HTTP "+response.status+" — требуется проверка сайта");
      if(!response.ok){if(attempt===3)throw new Error("Слата: HTTP "+response.status);await sleep(2000*attempt);continue;}
      const doc=new DOMParser().parseFromString(await response.text(),"text/html"),script=doc.querySelector("#__NUXT_DATA__");
      if(!script)throw new Error("Слата: нет данных каталога; проверьте рабочую вкладку");
      const data=find(unpack(JSON.parse(script.textContent)));if(!data)throw new Error("Слата изменила формат каталога");
      pages.push({category,page,url:url.href,html:script.outerHTML});return data;
    }
  }
  for(const category of categories){const first=await get(category,1),count=Number(first.pageCount);if(!Number.isInteger(count)||count<1||count>10000)throw new Error("Слата: некорректное количество страниц");for(let page=2;page<=count;page++){await sleep(700);await get(category,page);}}
  await options.onResult({kind:"slata",data:{format:"slata-pages-v1",pages}});
})().catch(error=>{const options=window.__AVELIN_COLLECTOR__||{};if(options.onError)options.onError(error.message);else alert(error.message);});
