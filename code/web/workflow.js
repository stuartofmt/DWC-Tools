mountPage(() => {
  const API = "/workflow/api";
  const ACTIONS = {
    new:     {text: "added", color: "success"},
    replace: {text: "replaced", color: "warning"},
    update:  {text: "line added", color: "info"},
    same:    {text: "already the same", color: undefined},
    keep:    {text: "kept (the plugin's own)", color: "info"},
    blocked: {text: "blocked: not a file", color: "error"},
  };
  const path = ref(""), recent = ref([]), view = ref(null), replaceSettings = ref(false);
  const copying = ref(false), result = ref(null);
  const { smAndUp, xs } = Vuetify.useDisplay();
  let seq = 0, typing = null;

  const current = () => (path.value || "").trim();
  // Copy is possible for a usable folder with something to copy
  const toCopy = computed(() => view.value && view.value.exists ? view.value.plan.filter(f => ["new", "replace", "update"].includes(f.action)) : []);
  const canCopy = computed(() => !!(view.value && view.value.exists && !view.value.problems.length && toCopy.value.length));
  const summary = computed(() => {
    if(!view.value || !view.value.exists || view.value.problems.length) return "";
    const n = toCopy.value.length;
    return n ? `${n} file${n === 1 ? "" : "s"} to copy` : "Nothing to copy: the workflow is already up to date here";
  });

  async function check(keepResult){
    clearTimeout(typing);
    const p = current(), my = ++seq;
    if(!keepResult) result.value = null;
    if(!p){ view.value = null; return; }
    const j = await getJSON(`${API}/target?path=${encodeURIComponent(p)}&replace_settings=${replaceSettings.value ? 1 : 0}`);
    if(my === seq) view.value = j;
  }
  function typed(){
    clearTimeout(typing);
    result.value = null;
    typing = setTimeout(() => check(false), 400);
  }
  async function copy(){
    copying.value = true;
    try{
      const j = await post(`${API}/copy`, {path: view.value.path, replace_settings: replaceSettings.value});
      if(j.done){
        result.value = j;
        view.value = j.view;
        if(!recent.value.includes(j.view.path)) recent.value = [j.view.path, ...recent.value];
      }
    }finally{ copying.value = false; }
  }

  // ----- the folder browser dialog (marks folders holding a plugin.json) -----
  const dlg = reactive({open:false, cwd:"", crumbs:[], dirs:[], isProject:false, filter:"", loading:false});
  const filterBox = ref(null);
  const shown = computed(() => {
    const f = (dlg.filter || "").toLowerCase();
    return dlg.dirs.filter(d => d.name.toLowerCase().includes(f));
  });
  async function browse(p){
    dlg.loading = true;
    try{
      const j = await getJSON("/api/browse?kind=plugin&path=" + encodeURIComponent(p || ""));
      Object.assign(dlg, {cwd: j.path, crumbs: j.crumbs, dirs: j.dirs, isProject: j.is_project, filter: ""});
    }finally{ dlg.loading = false; }
    if(filterBox.value) filterBox.value.focus();
  }
  function openBrowser(){
    dlg.open = true;
    const p = view.value && view.value.exists ? view.value.path : current();
    const up = p.slice(0, Math.max(p.lastIndexOf("/"), p.lastIndexOf("\\")) + 1);   // keeps / and C:\ whole
    browse(up && up !== p ? up : p);
  }
  function choose(p){
    path.value = p;
    dlg.open = false;
    check(false);
  }

  onMounted(async () => {
    const j = await getJSON(`${API}/target`);
    recent.value = j.recent;
    path.value = j.target || "";
    check(false);
  });
  return {ACTIONS, path, recent, view, replaceSettings, copying, result, canCopy, summary, smAndUp, xs,
          check, typed, copy, dlg, filterBox, shown, browse, openBrowser, choose, baseName};
});
