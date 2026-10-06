
const API = "/makezip/api";
function showZips(info){
  const zips = info ? info.zips : [];
  $("zipbox").hidden = !zips.length;
  $("zipcount").textContent = `Zips in dist (${zips.length})`;
  const body = $("ziplist");
  body.innerHTML = "";
  zips.forEach(z => {
    const tr = body.insertRow(), a = document.createElement("a");
    a.textContent = z.name;   // text, so file names are never treated as HTML
    a.href = `${API}/download?project=${encodeURIComponent(info.path)}&name=${encodeURIComponent(z.name)}`;
    tr.insertCell().append(a);
    const size = tr.insertCell(); size.className = "n"; size.textContent = (z.size / 1024).toFixed(1) + " KB";
    tr.insertCell().textContent = z.when;
  });
}
function selected(){
  return [...document.querySelectorAll("#exlist input:checked")].map(c => c.value);
}
function updateCount(){ $("excount").textContent = `Exclude files (${selected().length})`; }
let filesFor = null;
function showFiles(info){
  $("exbox").hidden = !info;
  if(!info){ filesFor = null; return; }
  // Keep the ticks made on this page when the same project's details are read again (after a run)
  const key = info.path + "\n" + info.files.join("\n") + "\n" + info.needed.join("\n");
  if(key === filesFor) return;
  filesFor = key;
  const on = new Set(info.excluded), needed = new Set(info.needed), box = $("exlist");
  box.innerHTML = "";
  const hint = document.createElement("small");
  hint.textContent = "Ticked files are left out of the zip. The ticks are remembered for this project when you press Make Zip. " +
    "Nothing is ticked until you tick it: check for files that belong to this computer, such as a settings file. " +
    "Always left out: venv, __pycache__ and .git folders, *.pyc files.";
  box.append(hint);
  if(info.files_truncated){
    const more = document.createElement("small");
    more.className = "bad";
    more.textContent = `Only the first ${info.files.length} files are listed.`;
    box.append(more);
  }
  info.files.forEach(f => {
    const l = document.createElement("label"), c = document.createElement("input");
    c.type = "checkbox"; c.value = f; c.checked = on.has(f); c.onchange = updateCount;
    c.disabled = needed.has(f);
    l.append(c, " " + f + (needed.has(f) ? "  (needed by install.py)" : ""));   // text node, never treated as HTML
    box.append(l);
  });
  updateCount();
}
const picker = setupPicker(info => { showZips(info); showFiles(info); });
$("go").onclick = () => post(`${API}/start`, {project: picker.current().path, exclude: selected()});
$("stop").onclick = () => post(`${API}/stop`);
wireExit();
startPolling(API, () => !!(picker.current() && picker.current().requirements), () => picker.refresh());   // the new zip appears once the run ends
