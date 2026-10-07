
function show(c){
  $("pd").value = c.projects_dir;
  $("pd").placeholder = c.defaults.projects_dir;
  $("pdn").className = c.projects_dir_found ? "note" : "note bad";
  $("pdn").textContent = `In use: ${c.projects_dir}` + (c.projects_dir_found ? "" : " - folder not found");
  $("pp").value = c.preferred_port;
  $("ppd").textContent = `0 means no preference: the first free port from ${c.defaults.start_port} is used. Otherwise use a port from 1024 to 65535. ` +
    `If your preferred port is already in use, the first free port from ${c.defaults.start_port} is used instead. A change takes effect the next time the app starts.`;
  $("ls").value = c.listen;
  $("ppn").textContent = c.url ? "This tool is running at " + c.url : "";
  $("python").textContent = "Project scripts are run with " + c.python;
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
$("save").onclick = () => save({projects_dir: $("pd").value, preferred_port: $("pp").value, listen: $("ls").value}, "Saved");
$("reset").onclick = () => save({projects_dir: "", preferred_port: 0, listen: "network"}, "Reset to defaults");
(async () => show(await (await fetch("/api/config")).json()))();
