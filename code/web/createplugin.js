mountPage(() => {
  const API = "/createplugin/api";
  const opts = ref({dwc: [], plugins: []}), loaded = ref(false);
  const dwc = ref(null), pl = ref(null), pv = ref(null), code = ref("");
  const found = ref([]);   // folders holding plugin.json in the chosen plugin version folder, the automatic one first
  const custom = ref(false), codeNote = reactive({text:"", kind:""});
  const files = ref([]), excluded = ref([]), truncated = ref(false);
  const shown = c => c === "" ? "." : c;   // "" is the plugin version folder itself
  const versions = computed(() => {
    const p = opts.value.plugins.find(p => p.name === pl.value);
    return p ? p.versions : [];
  });
  const canStart = computed(() => !!(dwc.value && pl.value && pv.value && code.value && codeNote.kind !== "bad"));
  let loadSeq = 0, lastCode = null;

  // c: the Code folder typed on the page; left out, the remembered or automatic one is used
  async function loadFiles(c){
    const my = ++loadSeq, enc = encodeURIComponent;
    let q = `dwc=${enc(dwc.value || "")}&plugin=${enc(pl.value || "")}&version=${enc(pv.value || "")}`;
    if(c !== undefined && c !== null) q += `&code=${enc(c)}`;
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
    files.value = data.files;
    excluded.value = [...data.selected];
    truncated.value = data.truncated;
  }
  // The Code folder box: check it when it is picked from the list, or on Enter or leaving the box
  function loadCode(){ if((code.value || "") !== lastCode) loadFiles(code.value || ""); }
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
  return {opts, loaded, dwc, pl, pv, code, found, custom, codeNote, files, excluded, truncated, shown, versions, canStart,
          loadFiles, loadCode, syncVersions,
          start: () => post(`${API}/start`, {dwc: dwc.value, plugin: pl.value, plugin_version: pv.value,
                                             code: code.value || "", exclude: excluded.value})};
});
