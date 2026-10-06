
const API = "/createplugin/api";
let opts = {dwc: [], plugins: []};
function fill(sel, items){
  sel.innerHTML = "";
  items.forEach(x => sel.add(new Option(x, x)));
}
function selected(){
  return [...document.querySelectorAll("#exlist input:checked")].map(c => c.value);
}
function updateCount(){ $("excount").textContent = `Exclude files (${selected().length})`; }
let loadSeq = 0;
async function loadFiles(){
  const my = ++loadSeq, enc = encodeURIComponent;
  const q = `dwc=${enc($("dwc").value)}&plugin=${enc($("pl").value)}&version=${enc($("pv").value)}`;
  const data = await (await fetch(`${API}/files?` + q)).json();
  if(my !== loadSeq) return;   // a newer selection has already replaced this one
  const files = data.files, on = new Set(data.selected);
  const box = $("exlist");
  box.innerHTML = "";
  const hint = document.createElement("small");
  hint.textContent = "Ticks are remembered for this DWC version + plugin + version. " +
    "Paths start at the Code folder. Zip-only builds: left out of the zip. " +
    "Real builds: moved out of Code during the build, then put back. " +
    "Always excluded: __pycache__, venv, *.log, *.pyc";
  box.append(hint);
  if(data.truncated){
    const more = document.createElement("small");
    more.className = "bad";
    more.textContent = `Only the first ${files.length} files are listed: the Code folder holds more than that.`;
    box.append(more);
  }
  files.forEach(f => {
    const l = document.createElement("label"), c = document.createElement("input");
    c.type = "checkbox"; c.value = f; c.checked = on.has(f); c.onchange = updateCount;
    l.append(c, " " + f);   // text node, so file names are never treated as HTML
    box.append(l);
  });
  updateCount();
}
function syncVersions(pick){
  const p = opts.plugins.find(p => p.name === $("pl").value);
  const versions = p ? p.versions : [];
  fill($("pv"), versions);
  if(pick && versions.includes(pick)) $("pv").value = pick;
  loadFiles();
}
async function loadOpts(){
  opts = await (await fetch(`${API}/options`)).json();
  fill($("dwc"), opts.dwc);
  fill($("pl"), opts.plugins.map(p => p.name));
  // Start from what was used last time, as far as those folders still exist
  const last = opts.last || {};
  if(opts.dwc.includes(last.dwc)) $("dwc").value = last.dwc;
  if(opts.plugins.some(p => p.name === last.plugin)) $("pl").value = last.plugin;
  syncVersions(last.plugin_version);
}
$("dwc").onchange = loadFiles;
$("pl").onchange = () => syncVersions();
$("pv").onchange = loadFiles;
$("go").onclick = () => post(`${API}/start`, {
  dwc: $("dwc").value, plugin: $("pl").value, plugin_version: $("pv").value, exclude: selected()});
$("stop").onclick = () => post(`${API}/stop`);
wireExit();
loadOpts();
startPolling(API);
