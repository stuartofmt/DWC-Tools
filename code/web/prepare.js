const API = "/prepare/api";
const picker = setupPicker(info => {
  $("state").textContent = !info ? "" :
    "Now: " + [info.requirements ? info.requirements : "no requirements.txt yet",
               info.venv ? "venv made" : "no venv yet",
               info.launcher ? info.launcher : "no launcher"].join(", ");
});
$("go").onclick = () => post(`${API}/start`, {project: picker.current().path});
$("stop").onclick = () => post(`${API}/stop`);
wireExit();
startPolling(API, () => !!picker.current(), () => picker.refresh());   // show the new state once the run ends
