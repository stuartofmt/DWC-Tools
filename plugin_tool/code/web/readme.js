
(async () => {
  try{
    const c = await (await fetch("/api/config")).json();
    $("cur-dwc").textContent = c.dwc_versions_dir;
    $("cur-plugins").textContent = c.plugins_dir;
    $("cur-file").textContent = c.settings_file;
    $("cur-url").textContent = c.url;
    $("cur-script").textContent = c.defaults.dwc_versions_dir;   // the default folder = where this app is installed
    $("first-run").hidden = !c.first_run;
  }catch(e){}
})();
