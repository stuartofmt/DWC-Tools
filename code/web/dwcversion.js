
const API = "/dwcversion/api";
let lastVersion = "";
function syncUI(){ $("v").hidden = $("dwc").value !== "__new"; }
async function loadOpts(keep){
  const data = await (await fetch(`${API}/options`)).json();
  const list = data.dwc, sel = $("dwc");
  const want = keep || (data.last || {}).version || "";   // this run's version, else last time's
  sel.innerHTML = "";
  list.forEach(x => sel.add(new Option(x, x)));
  sel.add(new Option("New version…", "__new"));
  if(want && list.includes(want)) sel.value = want;
  else if(want){ sel.value = "__new"; $("v").value = want; }   // not cloned (yet): keep what was typed
  else if(!list.length) sel.value = "__new";
  syncUI();
}
$("dwc").onchange = syncUI;
$("go").onclick = () => {
  const isNew = $("dwc").value === "__new";
  const version = isNew ? $("v").value.trim() : $("dwc").value;
  if(!isNew && !confirm(`This deletes and re-downloads the existing ${version} folder. Continue?`)) return;
  lastVersion = version;
  post(`${API}/start`, {version});
};
$("stop").onclick = () => post(`${API}/stop`);
wireExit();
loadOpts();
startPolling(API, () => loadOpts(lastVersion));   // a newly cloned version appears once the run ends
