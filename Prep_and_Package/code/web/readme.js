
(async () => {
  try{
    const c = await (await fetch("/api/config")).json();
    $("cur-projects").textContent = c.projects_dir;
    $("cur-python").textContent = c.python;
    $("cur-file").textContent = c.settings_file;
    $("cur-url").textContent = c.url;
    $("first-run").hidden = !c.first_run;
  }catch(e){}
})();
