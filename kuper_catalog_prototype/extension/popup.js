const $=id=>document.getElementById(id);
const settings=await chrome.storage.local.get(["token","state"]);
$("token").value=settings.token||"";
const tabs=await chrome.tabs.query({url:["https://web.kuper.ru/*","https://fix-price.com/*"]});
for(const tab of tabs){
  const label=document.createElement("label"),input=document.createElement("input");
  input.type="checkbox";input.checked=true;input.value=tab.id;
  label.append(input,document.createTextNode(" "+(tab.title||tab.url)));$("tabs").append(label);
}
function status(state){
  if(!state)return;
  $("status").textContent=[state.status,state.error,state.job?`Этап ${state.index+1}/${state.plan.length}: ${state.job.kind} · ${state.job.site}`:"",state.job?.pack?.stats?`Обработано ${state.job.pack.stats.processed}, найдено ${state.job.pack.stats.found}, осталось ${state.job.pack.remaining?.length||0}`:"",state.updated?`Обновлено: ${new Date(state.updated).toLocaleTimeString()}`:""].filter(Boolean).join("\n");
  for(const id of ["start","nutrition","resume"])$(id).disabled=["Выполняется","Останавливается"].includes(state.status);
}
status(settings.state);
chrome.storage.onChanged.addListener(changes=>{if(changes.state)status(changes.state.newValue);});
for(const action of ["connect","start","nutrition","resume","stop"]){
  $(action).onclick=async()=>{
    $(action).disabled=true;
    try{
      const token=$("token").value.trim();if(!token)throw new Error("Вставьте ключ локального помощника");
      await chrome.storage.local.set({token});
      const tabIds=[...$("tabs").querySelectorAll("input:checked")].map(input=>Number(input.value));
      const result=await chrome.runtime.sendMessage({action,tabIds,slata:$("slata").checked,refresh:$("refresh").checked});
      if(result?.error)throw new Error(result.error);
      if(action==="connect")$("status").textContent="Подключено. Папка: "+result.output;
    }catch(error){$("status").textContent=error.message;}
    finally{$(action).disabled=false;}
  };
}
