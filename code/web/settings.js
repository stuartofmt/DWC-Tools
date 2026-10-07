mountPage(() => {
  const c = ref({}), pd = ref(""), pp = ref(""), ls = ref("network"), msg = reactive({text:"", kind:""});
  function show(j){
    c.value = j;
    pd.value = j.projects_dir;
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
  (async () => show(await getJSON("/api/config")))();
  return {c, pd, pp, ls, msg,
          save: () => send({projects_dir: pd.value || "", preferred_port: pp.value || "", listen: ls.value}, "Saved"),
          reset: () => send({projects_dir: "", preferred_port: 0, listen: "network"}, "Reset to defaults")};
});
