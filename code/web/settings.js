mountPage(() => {
  const folders = [
    {key: "dwc_versions_dir", label: "DWC versions folder", count: "dwc_count", what: "DWC version folder(s)"},
    {key: "plugins_dir", label: "Plugins folder", count: "plugin_count", what: "plugin(s)"},
  ];
  const c = ref({}), vals = reactive({dwc_versions_dir: "", plugins_dir: "", output_dir: ""}), pp = ref(""), ls = ref("network");
  const msg = reactive({text:"", kind:""}), br = reactive({open:false, key:"", label:"", start:""});
  const { smAndUp } = Vuetify.useDisplay();
  // The folder in use, which is the install folder until changed, and what was found in it
  const inUse = f => !c.value[f.key] ? "" : c.value[f.count] === null ? `In use: ${c.value[f.key]} - folder not found`
                                                                      : `In use: ${c.value[f.key]} - ${c.value[f.count]} ${f.what} found`;
  function show(j){
    c.value = j;
    vals.dwc_versions_dir = j.dwc_versions_dir;
    vals.plugins_dir = j.plugins_dir;
    vals.output_dir = j.output_dir;
    pp.value = String(j.preferred_port);
    ls.value = j.listen;
  }
  async function send(values, okText){
    const r = await fetch("/api/config", {method:"POST", headers:{"Content-Type":"application/json"},
                                          body: JSON.stringify(values)});
    const j = await r.json();
    msg.kind = r.ok ? "" : "bad";
    msg.text = r.ok ? okText : j.error;
    if(r.ok) show(j);
  }
  // Browse: starts at the folder in the box (or the default) and puts the chosen one back in it
  function openBrowser(f){
    Object.assign(br, {open: true, key: f.key, label: f.label, start: (vals[f.key] || "").trim() || c.value.defaults[f.key]});
  }
  function chosen(path){
    vals[br.key] = path;
    msg.kind = "";
    msg.text = "Press Save to keep the change";
  }
  (async () => show(await getJSON("/api/config")))();
  return {folders, c, vals, pp, ls, msg, br, smAndUp, inUse, openBrowser, chosen,
          save: () => send({dwc_versions_dir: vals.dwc_versions_dir || "", plugins_dir: vals.plugins_dir || "",
                            output_dir: vals.output_dir || "", preferred_port: pp.value || "", listen: ls.value}, "Saved"),
          reset: () => send({dwc_versions_dir: "", plugins_dir: "", output_dir: "", preferred_port: 0, listen: "network"}, "Reset to defaults")};
});
