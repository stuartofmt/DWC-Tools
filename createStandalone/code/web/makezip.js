
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
const picker = setupPicker(showZips);
$("go").onclick = () => post(`${API}/start`, {project: picker.current().path});
$("stop").onclick = () => post(`${API}/stop`);
wireExit();
startPolling(API, () => !!(picker.current() && picker.current().requirements), () => picker.refresh());   // the new zip appears once the run ends
