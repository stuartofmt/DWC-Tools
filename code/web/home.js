
wireExit();
async function status(){
  if(closed) return;
  try{
    const s = await (await fetch("/api/status")).json();
    $("s-createplugin").textContent = s.createplugin ? "● running" : "";
    $("s-dwcversion").textContent = !s.dwcversion ? "" : s.dev_url ? "● dev server running at " + s.dev_url : "● running";
  }catch(e){}
  setTimeout(status, 2000);
}
status();
