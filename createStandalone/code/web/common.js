
const $ = id => document.getElementById(id);
let closed = false;
async function post(url, body){
  const r = await fetch(url, {method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify(body||{})});
  const j = await r.json(); if(!r.ok) alert(j.error); return j;
}
// Tell the app this page is open, every few seconds, and when it closes: the app stops once every page has gone
const pageId = Math.random().toString(36).slice(2) + Date.now().toString(36);
function alive(){
  if(!closed) fetch("/api/alive", {method:"POST", headers:{"Content-Type":"application/json"},
                                   body:JSON.stringify({page:pageId})}).catch(() => {});
}
alive();
setInterval(alive, 5000);
addEventListener("pagehide", () => navigator.sendBeacon("/api/bye", JSON.stringify({page:pageId})));
addEventListener("pageshow", e => { if(e.persisted) alive(); });   // back again from the browser's back/forward cache
function wireExit(){
  $("exit").onclick = async () => {
    if(!confirm("Stop any running jobs and shut down this server?")) return;
    closed = true;
    await post("/api/exit");
    document.body.innerHTML = "<p>Server closed. You can close this tab.</p>";
  };
}
// Polls <api>/log and keeps the log box, status text and Start button up to date.
// canStart() says whether the page's selections allow a run at all.
function startPolling(api, canStart, onFinished){
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
      $("status").textContent = j.running ? "● running" : "idle";
      $("go").disabled = j.running || !canStart();
      if(wasRunning && !j.running && onFinished) onFinished();
      wasRunning = j.running;
    }catch(e){ if(!closed) $("status").textContent = "server unreachable"; }
    setTimeout(poll, 700);
  }
  poll();
}

// ---------- project chooser (shared by the tool pages) ----------
// Fills <div id="picker"> with a path box, a list of recent projects, a folder browser and the project's options.
// onChange(info) gets the details of the chosen project (null while there is no usable one).
// Returns {current, refresh}: the current details, and a function that reads them again.
function setupPicker(onChange){
  const box = $("picker");
  box.innerHTML = `
    <label for="proj"><b>Project folder</b> (the one holding the <code>code</code> folder)</label>
    <div class="row"><input id="proj" list="recent" autocomplete="off" placeholder="Full path, or press Browse">
      <button id="browse">Browse…</button></div>
    <datalist id="recent"></datalist>
    <div class="note" id="projnote"></div>
    <div class="browser" id="browser" hidden>
      <div class="where"><button id="up" title="Parent folder">↑ Up</button><code id="cwd"></code>
        <button id="usehere">Use this folder</button><button id="close">Close</button></div>
      <div class="dirs" id="dirs"></div>
    </div>
    <details class="opts" id="opts" hidden>
      <summary>Project options</summary>
      <label>Main program <select id="o-main"></select></label> <span id="o-ver"></span>
      <label class="block"><input type="checkbox" id="o-site"> The venv can also use Python packages already installed on the system (--system-site-packages)</label>
      <div class="note" id="o-note"></div>
      <div class="note">Saved as soon as you change them, and used by both tools. Packages are installed into the venv with pip, from the project's requirements.txt.
        A change to the system packages option takes effect at the next Prepare, which then makes a new venv.
        <a id="o-view" target="_blank">See the install.py these make</a> (it goes into the zip).</div>
    </details>`;
  let info = null, seq = 0, cwd = "", parent = "";

  function usable(j){ return j.exists && j.is_project && j.options.main ? j : null; }
  function show(j){
    const note = $("projnote");
    info = null;
    $("opts").hidden = !(j.exists && j.is_project);
    if(!j.exists){ note.className = "note bad"; note.textContent = j.error; }
    else if(!j.is_project){ note.className = "note bad"; note.textContent = `${j.path} has no code folder with a .py program in it`; }
    else{
      const o = j.options, main = $("o-main");
      main.innerHTML = "";
      if(!o.main) main.add(new Option("(choose)", ""));
      j.programs.forEach(p => main.add(new Option(p, p)));
      main.value = o.main;
      $("o-site").checked = o.site_packages;
      $("o-view").href = "/api/project/installpy?path=" + encodeURIComponent(j.path);
      $("o-ver").textContent = !o.main ? "" : j.version ? "version " + j.version : "no version set";
      if(!o.main){
        $("opts").open = true;
        note.className = "note bad"; note.textContent = `Project "${j.name}": choose its main program in the options below`;
      }else{
        info = j;
        note.className = "note good";
        note.textContent = `Project "${j.name}" - runs code/${o.main}, ` +
          (j.requirements ? `pip installs ${j.requirements}` : "no requirements.txt yet (Prepare makes one)") +
          (j.has_readme ? "" : " (no README.md)");
      }
    }
    onChange(info);
  }
  async function check(path, remember){
    const my = ++seq;
    const j = path.trim() ? await (await fetch("/api/project?path=" + encodeURIComponent(path))).json()
                          : {exists:false, error:"Choose the project folder: type its full path or press Browse"};
    if(my !== seq) return;   // a newer choice has already replaced this one
    show(j);
    if(remember && j.exists && j.is_project)
      fetch("/api/project", {method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify({path:j.path})});
  }
  async function saveOptions(){
    const r = await fetch("/api/project/options", {method:"POST", headers:{"Content-Type":"application/json"},
      body: JSON.stringify({path: $("proj").value, main: $("o-main").value, site_packages: $("o-site").checked})});
    const j = await r.json();
    $("o-note").className = r.ok ? "note" : "note bad";
    $("o-note").textContent = r.ok ? "Saved" : j.error;
    if(r.ok){ seq++; show(j); }
  }
  function choose(path){
    $("proj").value = path;
    $("browser").hidden = true;
    check(path, true);
  }
  async function browse(path){
    const j = await (await fetch("/api/browse?path=" + encodeURIComponent(path || ""))).json();
    cwd = j.path; parent = j.parent;
    $("cwd").textContent = cwd;
    $("up").disabled = !parent;
    $("usehere").disabled = !j.is_project;
    $("usehere").title = j.is_project ? "" : "This folder has no code folder with a .py program in it";
    const list = $("dirs");
    list.innerHTML = "";
    if(!j.dirs.length){
      const e = document.createElement("div"); e.className = "note"; e.textContent = "(no sub-folders)"; list.append(e);
    }
    j.dirs.forEach(d => {
      const row = document.createElement("div"), a = document.createElement("a");
      row.className = "dir" + (d.is_project ? " project" : "");
      a.textContent = "📁 " + d.name;   // text, so folder names are never treated as HTML
      a.title = "Open " + d.path;
      a.onclick = () => browse(d.path);
      row.append(a);
      if(d.is_project){
        const s = document.createElement("span"); s.className = "tag"; s.textContent = "project"; row.append(s);
        const b = document.createElement("button"); b.textContent = "Select"; b.onclick = () => choose(d.path);
        row.append(b);
      }
      list.append(row);
    });
    $("browser").hidden = false;
  }

  $("browse").onclick = () => $("browser").hidden ? browse($("proj").value) : ($("browser").hidden = true);
  $("up").onclick = () => parent && browse(parent);
  $("usehere").onclick = () => choose(cwd);
  $("close").onclick = () => $("browser").hidden = true;
  $("proj").onchange = () => check($("proj").value, true);
  ["o-main", "o-site"].forEach(id => $(id).onchange = saveOptions);
  (async () => {
    const j = await (await fetch("/api/project")).json();
    j.recent.forEach(p => $("recent").append(new Option(p, p)));
    $("proj").value = j.project || "";
    check($("proj").value, false);
  })();
  return {
    current: () => info,
    refresh: () => check($("proj").value, false),
  };
}
