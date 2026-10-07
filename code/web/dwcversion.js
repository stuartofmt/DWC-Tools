mountPage(() => {
  const API = "/dwcversion/api";
  const list = ref([]), sel = ref("__new"), typed = ref(""), confirmAsk = ref(false);
  const lastVersion = ref("");   // the version of the run on this page
  const items = computed(() => [...list.value, {title: "New version…", value: "__new"}]);
  const isNew = computed(() => sel.value === "__new");
  const version = computed(() => isNew.value ? typed.value.trim() : sel.value);
  async function loadOpts(keep){
    const data = await getJSON(`${API}/options`);
    list.value = data.dwc;
    const want = keep || (data.last || {}).version || "";   // this run's version, else last time's
    if(want && data.dwc.includes(want)) sel.value = want;
    else if(want){ sel.value = "__new"; typed.value = want; }   // not cloned (yet): keep what was typed
    else if(!data.dwc.length) sel.value = "__new";
    else sel.value = data.dwc[0];
  }
  function start(){
    confirmAsk.value = false;
    lastVersion.value = version.value;
    post(`${API}/start`, {version: version.value});
  }
  // An existing version is deleted and downloaded again, so ask first
  function ask(){
    if(!version.value) return;
    if(isNew.value) start();
    else confirmAsk.value = true;
  }
  loadOpts();
  // a newly cloned version appears once the run ends (@finished)
  return {sel, typed, items, version, confirmAsk, ask, start, loadOpts, lastVersion};
});
