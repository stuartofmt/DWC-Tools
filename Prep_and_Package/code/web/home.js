
wireExit();
(async () => {
  try{
    const j = await (await fetch("/api/project")).json();
    $("lastproj").textContent = j.project ? "Current project: " + j.project : "No project chosen yet";
  }catch(e){}
})();
async function status(){
  if(closed) return;
  try{
    const s = await (await fetch("/api/status")).json();
    $("s-makezip").textContent = s.makezip ? "● running" : "";
    $("s-prepare").textContent = s.prepare ? "● running" : "";
  }catch(e){}
  setTimeout(status, 2000);
}
status();
