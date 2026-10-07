mountPage(() => {
  const API = "/makezip/api", info = ref(null), excluded = ref([]);
  const needed = computed(() => new Set(info.value ? info.value.needed : []));
  let filesFor = null;
  function show(i){
    info.value = i;
    if(!i){ filesFor = null; return; }
    // Keep the ticks made on this page when the same project's details are read again (after a run)
    const key = i.path + "\n" + i.files.join("\n") + "\n" + i.needed.join("\n");
    if(key === filesFor) return;
    filesFor = key;
    excluded.value = [...i.excluded];
  }
  const download = z => `${API}/download?project=${encodeURIComponent(info.value.path)}&name=${encodeURIComponent(z.name)}`;
  // the new zip appears once the run ends (@finished)
  return {info, excluded, needed, show, download,
          start: () => post(`${API}/start`, {project: info.value.path, exclude: excluded.value})};
});
