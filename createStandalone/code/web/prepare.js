
const API = "/install/api";
let shownFor = null;
const picker = setupPicker(info => {
  // Each project remembers its own install folder: show it when the project changes
  const path = info ? info.path : null;
  if(path !== shownFor){
    shownFor = path;
    $("target").value = info ? info.options.install_target : "";
  }
  $("target").placeholder = info ? info.default_target : "";
});
$("go").onclick = () => {
  const info = picker.current(), target = $("target").value.trim();
  if(!confirm(`Install ${info.name} into ${target || info.default_target}?`)) return;
  post(`${API}/start`, {project: info.path, target});
};
$("stop").onclick = () => post(`${API}/stop`);
wireExit();
startPolling(API, () => !!picker.current());
