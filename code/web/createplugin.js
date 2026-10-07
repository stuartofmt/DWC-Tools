mountPage(() => {
  const API = "/createplugin/api";
  const opts = ref({dwc: [], plugins: []}), loaded = ref(false);
  const dwc = ref(null), pl = ref(null), pv = ref(null), code = ref("");
  const found = ref([]);   // folders holding plugin.json in the chosen plugin version folder, the automatic one first
  const custom = ref(false), codeNote = reactive({text:"", kind:""});
  const files = ref([]), excluded = ref([]), truncated = ref(false);
  // The Build output folder (relative, "" = no copy) and what it means for the chosen plugin version
  const output = ref(""), outputDefault = ref(""), outputNote = reactive({text:"", kind:""});
  const shown = c => c === "" ? "." : c;   // "" is the plugin version folder itself
  const versions = computed(() => {
    const p = opts.value.plugins.find(p => p.name === pl.value);
    return p ? p.versions : [];
  });
  const canStart = computed(() => !!(dwc.value && pl.value && pv.value && code.value && codeNote.kind !== "bad" && outputNote.kind !== "bad"));
  let loadSeq = 0, lastCode = null, lastOutput = null;

  // c: the Code folder typed on the page; left out, the remembered or automatic one is used.
  // o: the Build output folder typed on the page; left out, the plugin's own or the Settings one is used.
  async function loadFiles(c, o){
    const my = ++loadSeq, enc = encodeURIComponent;
    let q = `dwc=${enc(dwc.value || "")}&plugin=${enc(pl.value || "")}&version=${enc(pv.value || "")}`;
    if(c !== undefined && c !== null) q += `&code=${enc(c)}`;
    if(o !== undefined && o !== null) q += `&output=${enc(o)}`;
    const data = await getJSON(`${API}/files?` + q);
    if(my !== loadSeq) return;   // a newer selection has already replaced this one
    found.value = data.found;
    if(data.code !== null) code.value = shown(data.code);
    lastCode = code.value;
    custom.value = data.custom;
    codeNote.kind = data.error ? "bad" : "";
    codeNote.text = !pv.value ? "" : data.error ? data.error
      : (data.custom ? "Changed by you, and remembered for this plugin version" + (data.found.length ? `. Automatic: ${shown(data.found[0])}` : "")
                     : "Found automatically") +
        (data.found.length > 1 ? `. plugin.json is also in: ${data.found.filter(f => f !== data.code).map(shown).join(", ")}` : "");
    outputDefault.value = data.output_default;
    if(!data.output_error) output.value = data.output;   // a bad one stays in the box, to be corrected
    lastOutput = output.value;
    outputNote.kind = data.output_error ? "bad" : "";
    outputNote.text = !pv.value ? "" : data.output_error ? "Build output folder: " + data.output_error
      : "The zip goes to " + (data.output_folder || "the plugin version folder") +
        (data.output === data.output_saved ? ". Remembered for this plugin"
         : data.output_saved === null && data.output === data.output_default ? ". From the Settings page, as this plugin has not been built yet"
         : ". Remembered for this plugin when you press Build");
    files.value = data.files;
    excluded.value = [...data.selected];
    truncated.value = data.truncated;
  }
  // The Code folder box: check it when it is picked from the list, or on Enter or leaving the box
  function loadCode(){ if((code.value || "") !== lastCode) loadFiles(code.value || "", output.value); }
  // The Build output folder box: check it on Enter or leaving the box. It belongs to the plugin, so it is
  // kept while the DWC version or plugin version changes, and read again for another plugin.
  function loadOutput(){ if((output.value || "") !== lastOutput) loadFiles(code.value || "", output.value || ""); }
  function syncVersions(pick){
    pv.value = pick && versions.value.includes(pick) ? pick : versions.value[0] || null;
    if(!pv.value) code.value = "";
    loadFiles();
  }
  (async () => {
    opts.value = await getJSON(`${API}/options`);
    loaded.value = true;
    // Start from what was used last time, as far as those folders still exist
    const last = opts.value.last || {};
    dwc.value = opts.value.dwc.includes(last.dwc) ? last.dwc : opts.value.dwc[0] || null;
    pl.value = opts.value.plugins.some(p => p.name === last.plugin) ? last.plugin
             : opts.value.plugins.length ? opts.value.plugins[0].name : null;
    syncVersions(last.plugin_version);
  })();
  return {opts, loaded, dwc, pl, pv, code, found, custom, codeNote, files, excluded, truncated,
          output, outputDefault, outputNote, shown, versions, canStart,
          loadFiles, loadCode, loadOutput, syncVersions,
          start: () => post(`${API}/start`, {dwc: dwc.value, plugin: pl.value, plugin_version: pv.value,
                                             code: code.value || "", output: output.value || "", exclude: excluded.value})};
});
