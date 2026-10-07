mountPage(() => {
  const s = reactive({createplugin:false, dwcversion:false, dev_url:""});
  async function status(){
    if(ui.closed) return;
    try{ Object.assign(s, await getJSON("/api/status")); }catch(e){}
    setTimeout(status, 2000);
  }
  status();
  return {s};
});
