mountPage(() => {
  const c = ref({});
  (async () => { try{ c.value = await getJSON("/api/config"); }catch(e){} })();
  return {c};
});
