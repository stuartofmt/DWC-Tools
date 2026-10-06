
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
let found = [];   // folders holding plugin.json in the chosen plugin version folder, the automatic one first
const shown = code => code === "" ? "." : code;   // "" is the plugin version folder itself
// code: the Code folder typed on the page; left out, the remembered or automatic one is used
async function loadFiles(code){
  const my = ++loadSeq, enc = encodeURIComponent;
  let q = `dwc=${enc($("dwc").value)}&plugin=${enc($("pl").value)}&version=${enc($("pv").value)}`;
  if(code !== undefined) q += `&code=${enc(code)}`;
  const data = await (await fetch(`${API}/files?` + q)).json();
  if(my !== loadSeq) return;   // a newer selection has already replaced this one
  found = data.found;
  $("codelist").replaceChildren(...found.map(f => new Option(shown(f))));
  if(data.code !== null) $("code").value = shown(data.code);
  $("codeauto").disabled = !data.custom || !found.length;
  $("coden").className = data.error ? "note bad" : "note";
  $("coden").textContent = data.error ? data.error
    : (data.custom ? "Changed by you, and remembered for this plugin version" + (found.length ? `. Automatic: ${shown(found[0])}` : "")
                   : "Found automatically") +
      (found.length > 1 ? `. plugin.json is also in: ${found.filter(f => f !== data.code).map(shown).join(", ")}` : "");
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
  if(!versions.length){ $("code").value = ""; $("coden").textContent = ""; }
  loadFiles();
}
async function loadOpts(){
  opts = await (await fetch(`${API}/options`)).json();
  fill($("dwc"), opts.dwc);
  fill($("pl"), opts.plugins.map(p => p.name));
  $("noplugins").hidden = opts.plugins.length > 0;
  $("noplugins").textContent = `No plugins found in ${opts.plugins_dir}: a plugin is a folder there with at least one ` +
    `sub-folder holding plugin.json (in it, or up to 3 folders below it). Check the Plugins folder on the Settings page.`;
  // Start from what was used last time, as far as those folders still exist
  const last = opts.last || {};
  if(opts.dwc.includes(last.dwc)) $("dwc").value = last.dwc;
  if(opts.plugins.some(p => p.name === last.plugin)) $("pl").value = last.plugin;
  syncVersions(last.plugin_version);
}
$("dwc").onchange = () => loadFiles($("code").value);
$("pl").onchange = () => syncVersions();
$("pv").onchange = () => loadFiles();
$("code").onchange = () => loadFiles($("code").value);
$("codeauto").onclick = () => loadFiles(found[0]);
$("go").onclick = () => post(`${API}/start`, {
  dwc: $("dwc").value, plugin: $("pl").value, plugin_version: $("pv").value, code: $("code").value, exclude: selected()});
$("stop").onclick = () => post(`${API}/stop`);
wireExit();
loadOpts();
startPolling(API);
