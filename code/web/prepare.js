mountPage(() => {
  const API = "/prepare/api", info = ref(null);
  const state = computed(() => !info.value ? "" :
    "Now: " + [info.value.requirements ? info.value.requirements : "no requirements.txt yet",
               info.value.venv ? "venv made" : "no venv yet",
               info.value.launcher ? info.value.launcher : "no launcher"].join(", "));
  // the job panel shows the new state once the run ends (@finished)
  return {info, state, start: () => post(`${API}/start`, {project: info.value.path})};
});
