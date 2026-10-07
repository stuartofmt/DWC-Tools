mountPage(() => {
  const project = ref(""), running = reactive({makezip:false, prepare:false});
  (async () => {
    try{
      const j = await getJSON("/api/project");
      project.value = j.project ? "Current project: " + j.project : "No project chosen yet";
    }catch(e){}
  })();
  async function status(){
    if(ui.closed) return;
    try{ Object.assign(running, await getJSON("/api/status")); }catch(e){}
    setTimeout(status, 2000);
  }
  status();
  return {project, running};
});
