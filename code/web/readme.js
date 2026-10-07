mountPage(() => {
  const c = ref({defaults: {}});
  (async () => { try{ c.value = await getJSON("/api/config"); }catch(e){} })();
  return {c};
});
