
function show(c){
  $("dv").value = c.dwc_versions_dir;   // always the folder in use, which is the install folder until changed
  $("pd").value = c.plugins_dir;
  $("dv").placeholder = c.defaults.dwc_versions_dir;
  $("pd").placeholder = c.defaults.plugins_dir;
  const note = (el, path, count, what) => {
    el.className = count === null ? "note bad" : "note";
    el.textContent = count === null ? `In use: ${path} - folder not found`
                                    : `In use: ${path} - ${count} ${what} found`;
  };
  note($("dvn"), c.dwc_versions_dir, c.dwc_count, "DWC version folder(s)");
  note($("pdn"), c.plugins_dir, c.plugin_count, "plugin(s)");
  $("pp").value = c.preferred_port;
  $("ls").value = c.listen;
  $("ppn").textContent = c.url ? "This tool is running at " + c.url : "";
  $("file").textContent = "Stored in " + c.settings_file;
}
async function save(values, okText){
  const r = await fetch("/api/config", {method:"POST", headers:{"Content-Type":"application/json"},
                                        body: JSON.stringify(values)});
  const j = await r.json();
  $("msg").className = r.ok ? "" : "bad";
  $("msg").textContent = r.ok ? okText : j.error;
  if(r.ok) show(j);
}
$("save").onclick = () => save({dwc_versions_dir: $("dv").value, plugins_dir: $("pd").value,
                                preferred_port: $("pp").value,
                                listen: $("ls").value}, "Saved");
$("reset").onclick = () => save({dwc_versions_dir: "", plugins_dir: "", preferred_port: 0,
                                 listen: "network"}, "Reset to defaults");
(async () => show(await (await fetch("/api/config")).json()))();

// Browse: a folder picker that lists the folders on the computer running this app (the page may be open on another one)
let browseFor = null, browseAt = null;
async function browse(path){
  const r = await fetch("/api/browse?path=" + encodeURIComponent(path));
  const j = await r.json();
  if(!r.ok){ $("brnote").textContent = j.error || "Could not list that folder"; return; }
  browseAt = j;
  $("brpath").value = j.path;
  $("brup").disabled = j.parent === null;
  $("brok").disabled = !j.path;   // the Windows list of drives is not a folder
  $("brnote").className = j.readable ? "note" : "note bad";
  $("brnote").textContent = !j.readable ? "This folder cannot be read"
                          : j.dirs.length ? "" : "No sub-folders";
  $("brlist").replaceChildren(...j.dirs.map(d => {
    const b = document.createElement("button");
    b.type = "button";
    b.textContent = "\u{1F4C1} " + d.name;
    b.onclick = () => browse(d.path);
    return b;
  }));
  $("brlist").scrollTop = 0;
}
document.querySelectorAll("[data-browse]").forEach(btn => btn.onclick = () => {
  browseFor = $(btn.dataset.browse);
  $("brtitle").textContent = "Choose the " + btn.closest(".field").querySelector("label b").textContent;
  browse(browseFor.value.trim() || browseFor.placeholder);
  $("browser").showModal();
});
$("brup").onclick = () => browse(browseAt.parent);
$("brgo").onclick = () => browse($("brpath").value.trim());
$("brpath").onkeydown = e => { if(e.key === "Enter"){ e.preventDefault(); $("brgo").click(); } };
$("brcancel").onclick = () => $("browser").close();
$("brok").onclick = () => {
  browseFor.value = browseAt.path;
  $("browser").close();
  $("msg").className = "";
  $("msg").textContent = "Press Save to keep the change";
};
