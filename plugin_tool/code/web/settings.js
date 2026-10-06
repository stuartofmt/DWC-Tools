
function show(c){
  $("dv").value = c.dwc_versions_dir;   // always the folder in use, which is the install folder until changed
  $("pd").value = c.plugins_dir;
  $("cp").value = c.code_path === c.defaults.code_path ? "" : c.code_path;
  $("cp").placeholder = c.defaults.code_path || "(the plugin version folder itself)";
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
                                code_path: $("cp").value, preferred_port: $("pp").value,
                                listen: $("ls").value}, "Saved");
$("reset").onclick = () => save({dwc_versions_dir: "", plugins_dir: "", code_path: "", preferred_port: 0,
                                 listen: "network"}, "Reset to defaults");
(async () => show(await (await fetch("/api/config")).json()))();
