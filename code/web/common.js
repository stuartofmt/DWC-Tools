
const $ = id => document.getElementById(id);
let closed = false;
async function post(url, body){
  const r = await fetch(url, {method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify(body||{})});
  const j = await r.json(); if(!r.ok) alert(j.error); return j;
}
function wireExit(){
  $("exit").onclick = async () => {
    if(!confirm("Stop any running jobs and shut down this server?")) return;
    closed = true;
    await post("/api/exit");
    document.body.innerHTML = "<p>Server closed. You can close this tab.</p>";
  };
}
// Polls <api>/log and keeps the log box, status text and Start button up to date.
function startPolling(api, onFinished){
  let run = 0, n = 0, wasRunning = false;
  const logEl = $("log");
  async function poll(){
    if(closed) return;
    try{
      const j = await (await fetch(`${api}/log?run=${run}&from=${n}`)).json();
      if(j.run !== run){ run = j.run; logEl.textContent = ""; }
      if(j.lines.length){
        const atBottom = logEl.scrollTop + logEl.clientHeight >= logEl.scrollHeight - 20;
        logEl.textContent += j.lines.join("\n") + "\n";
        if(atBottom) logEl.scrollTop = logEl.scrollHeight;
      }
      n = j.total;
      $("status").textContent = j.running ? "● running"
                              : j.service ? "● dev server running at " + j.service : "idle";
      $("go").disabled = j.running || !!j.service;
      if(wasRunning && !j.running && onFinished) onFinished();
      wasRunning = j.running;
    }catch(e){ if(!closed) $("status").textContent = "server unreachable"; }
    setTimeout(poll, 700);
  }
  poll();
}
