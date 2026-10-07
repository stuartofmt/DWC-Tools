// Shared by every page: Vue 3 and Vuetify 4 (in vendor, loaded by base.html), the page frame, the job panel and
// the folder browser. Each page's script calls mountPage() and its <name>.html is the page's Vue template.
const { createApp, reactive, ref, computed, onMounted } = Vue;

// For every component on the page: an error to show, and whether the server has been closed
const ui = reactive({error: "", closed: false});

async function getJSON(url){ return (await fetch(url)).json(); }
async function post(url, body){
  const r = await fetch(url, {method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify(body||{})});
  const j = await r.json(); if(!r.ok) ui.error = j.error; return j;
}
// Tell the app this tab is open, and whether it is hidden. It shuts itself down once every one of its tabs has been
// closed. A hidden tab (minimized, another tab or app in front) may be slowed, frozen or discarded by the browser, so
// the app does not expect to hear from it until it is shown again; closing it still sends "closing".
const TAB_ID = Math.random().toString(36).slice(2) + Date.now().toString(36);
let tabSeq = 0;   // numbers the messages, so the app can ignore one that arrives after a newer one
function tabPing(closing){
  if(ui.closed) return;
  const body = JSON.stringify({id: TAB_ID, seq: ++tabSeq, closing, hidden: document.visibilityState === "hidden"});
  // A beacon is still sent while the page is being hidden or closed (and may be frozen straight after)
  if(closing || document.visibilityState === "hidden") navigator.sendBeacon("/api/tab", new Blob([body], {type: "application/json"}));
  else fetch("/api/tab", {method: "POST", headers: {"Content-Type": "application/json"}, body}).catch(() => {});
}
tabPing(false);
setInterval(() => tabPing(false), 15000);
addEventListener("visibilitychange", () => tabPing(false));
addEventListener("freeze", () => tabPing(false));   // Chrome: about to be frozen (it is hidden by then)
addEventListener("pagehide", () => tabPing(true));
addEventListener("pageshow", e => { if(e.persisted) tabPing(false); });   // back to a page the browser kept in memory

// ---------- page frame: app bar with the links and Exit, the page's title and content, errors ----------
const LINKS = [
  {href:"/", text:"Home", icon:"mdi-home"},
  {href:"/createplugin", text:"Create a Plugin", icon:"mdi-puzzle"},
  {href:"/dwcversion", text:"Create DWC Version", icon:"mdi-source-branch"},
  {href:"/readme", text:"Instructions", icon:"mdi-book-open-variant"},
  {href:"/settings", text:"Settings", icon:"mdi-cog"},
];
const PageFrame = {
  props: {title: String},
  setup(){
    const exitAsk = ref(false);
    const { lgAndUp, xs } = Vuetify.useDisplay();
    async function exit(){
      exitAsk.value = false;
      ui.closed = true;
      await post("/api/exit");
    }
    return {ui, links: LINKS, here: location.pathname, exitAsk, exit, lgAndUp, xs};
  },
  template: `
  <v-app>
    <v-app-bar color="primary" density="comfortable" flat>
      <v-app-bar-title v-if="!xs">DWC tools</v-app-bar-title>   <!-- a phone only has room for the buttons -->
      <template #append>
        <template v-for="l in links" :key="l.href">
          <v-btn v-if="lgAndUp" :href="l.href" :prepend-icon="l.icon" :active="l.href === here" variant="text">{{ l.text }}</v-btn>
          <v-btn v-else :href="l.href" :icon="l.icon" :active="l.href === here" :title="l.text"></v-btn>
        </template>
        <v-btn icon="mdi-power" title="Exit: stop any running jobs and shut down this server" :disabled="ui.closed" @click="exitAsk = true"></v-btn>
      </template>
    </v-app-bar>
    <v-main>
      <v-container class="page">
        <v-alert v-if="ui.closed" type="info" variant="tonal" text="Server closed. You can close this tab."></v-alert>
        <template v-else>
          <h1 class="text-h5 mb-4">{{ title }}</h1>
          <slot></slot>
        </template>
      </v-container>
    </v-main>
    <v-dialog v-model="exitAsk" max-width="420">
      <v-card title="Exit" text="Stop any running jobs and shut down this server?">
        <v-card-actions>
          <v-spacer></v-spacer>
          <v-btn @click="exitAsk = false">Cancel</v-btn>
          <v-btn color="error" variant="flat" @click="exit">Exit</v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>
    <v-snackbar :model-value="!!ui.error" @update:model-value="v => v || (ui.error = '')" color="error" timeout="10000">
      {{ ui.error }}
      <template #actions><v-btn variant="text" @click="ui.error = ''">Close</v-btn></template>
    </v-snackbar>
  </v-app>`,
};

// ---------- job panel: Start and Stop buttons, the status and the log ----------
// Polls <api>/log and keeps the log, the status and the Start button up to date. canStart says whether the
// page's selections allow a run at all. A job can leave a service running (the DWC dev server): Start stays
// off and Stop on until it ends. The default slot goes between the buttons and the log.
const JobPanel = {
  props: {api: String, label: String, icon: String, canStart: Boolean},
  emits: ["start", "finished"],
  setup(props, {emit}){
    const log = ref(null), running = ref(false), service = ref(""), reachable = ref(true);
    let run = 0, n = 0;
    async function poll(){
      if(ui.closed) return;
      try{
        const j = await getJSON(`${props.api}/log?run=${run}&from=${n}`);
        const el = log.value;
        if(j.run !== run){ run = j.run; el.textContent = ""; }
        if(j.lines.length){
          const atBottom = el.scrollTop + el.clientHeight >= el.scrollHeight - 20;
          el.textContent += j.lines.join("\n") + "\n";
          if(atBottom) el.scrollTop = el.scrollHeight;
        }
        n = j.total;
        reachable.value = true;
        if(running.value && !j.running) emit("finished");
        running.value = j.running;
        service.value = j.service || "";
      }catch(e){ if(!ui.closed) reachable.value = false; }
      setTimeout(poll, 700);
    }
    onMounted(poll);
    return {log, running, service, reachable, stop: () => post(`${props.api}/stop`)};
  },
  template: `
    <div class="d-flex align-center ga-2 flex-wrap my-4">
      <v-btn color="primary" :prepend-icon="icon" :disabled="running || !!service || !canStart" @click="$emit('start')">{{ label }}</v-btn>
      <v-btn prepend-icon="mdi-stop" :disabled="!running && !service" @click="stop">Stop</v-btn>
      <v-chip v-if="!reachable" color="error" variant="tonal">server unreachable</v-chip>
      <v-chip v-else-if="running" color="primary" variant="tonal">
        <v-progress-circular indeterminate size="14" width="2" class="mr-2"></v-progress-circular>running
      </v-chip>
      <v-chip v-else-if="service" color="success" variant="tonal" prepend-icon="mdi-check-circle" :href="service" target="_blank">
        dev server running at {{ service }}
      </v-chip>
      <v-chip v-else variant="tonal">idle</v-chip>
    </div>
    <slot></slot>
    <pre class="log mt-4" ref="log"></pre>`,
};

// ---------- folder browser: a dialog listing the folders on the computer running this app ----------
// The page may be open on another computer, so the browser's own folder picker (which shows that computer's
// folders) is no use. Opens at start when shown; emits "choose" with the folder picked.
const FolderBrowser = {
  props: {modelValue: Boolean, title: String, start: String},
  emits: ["update:modelValue", "choose"],
  setup(props, {emit}){
    const { smAndUp, xs } = Vuetify.useDisplay();
    const dlg = reactive({cwd:"", crumbs:[], dirs:[], readable:true, filter:"", sel:0, loading:false});
    const filterBox = ref(null), dirList = ref(null);
    const shown = computed(() => {
      const f = (dlg.filter || "").toLowerCase();
      return dlg.dirs.filter(d => d.name.toLowerCase().includes(f));
    });
    Vue.watch(() => dlg.filter, () => dlg.sel = 0);
    async function browse(p){
      dlg.loading = true;
      try{
        const j = await getJSON("/api/browse?path=" + encodeURIComponent(p || ""));
        Object.assign(dlg, {cwd: j.path, crumbs: j.crumbs, dirs: j.dirs, readable: j.readable, filter: "", sel: 0});
        if(dirList.value) dirList.value.$el.scrollTop = 0;   // the card text is what scrolls
      }finally{ dlg.loading = false; }
      if(filterBox.value) filterBox.value.focus();
    }
    Vue.watch(() => props.modelValue, open => { if(open) browse(props.start); });
    const close = () => emit("update:modelValue", false);
    function choose(){
      emit("choose", dlg.cwd);
      close();
    }
    function moveTo(i){
      dlg.sel = Math.max(0, Math.min(i, shown.value.length - 1));
      Vue.nextTick(() => { const e = document.getElementById("dir-" + dlg.sel); if(e) e.scrollIntoView({block:"nearest"}); });
    }
    function onKey(e){
      if(e.key === "ArrowDown"){ e.preventDefault(); moveTo(dlg.sel + 1); }
      else if(e.key === "ArrowUp"){ e.preventDefault(); moveTo(dlg.sel - 1); }
      else if(e.key === "Enter"){ const d = shown.value[dlg.sel]; if(d){ e.preventDefault(); browse(d.path); } }
      else if(e.key === "Backspace" && !dlg.filter && dlg.crumbs.length > 1){
        e.preventDefault();
        browse(dlg.crumbs[dlg.crumbs.length - 2].path);
      }
    }
    return {smAndUp, xs, dlg, shown, filterBox, dirList, browse, close, choose, onKey};
  },
  template: `
    <v-dialog :model-value="modelValue" @update:model-value="v => v || close()" max-width="700" :fullscreen="xs" scrollable
              @after-enter="filterBox && filterBox.focus()">
      <v-card>
        <v-card-title class="d-flex align-center">
          {{ title }}<v-spacer></v-spacer>
          <v-btn icon="mdi-close" variant="text" size="small" title="Close" @click="close"></v-btn>
        </v-card-title>
        <div class="crumbs px-3">
          <template v-for="(c, i) in dlg.crumbs" :key="c.path">
            <v-icon v-if="i" icon="mdi-chevron-right" size="small" class="text-medium-emphasis"></v-icon>
            <v-btn size="small" variant="text" :class="{'font-weight-bold': i === dlg.crumbs.length - 1}"
                   @click="i < dlg.crumbs.length - 1 && browse(c.path)">{{ c.name }}</v-btn>
          </template>
        </div>
        <div class="d-flex align-center ga-4 px-4 pt-2 flex-wrap">
          <v-text-field ref="filterBox" v-model="dlg.filter" prepend-inner-icon="mdi-magnify" placeholder="Filter folders…"
                        density="compact" variant="outlined" hide-details clearable class="filter" @keydown="onKey"></v-text-field>
        </div>
        <div v-if="smAndUp" class="note px-4">↑ ↓ move · Enter opens a folder · Backspace goes up</div>
        <v-progress-linear :active="dlg.loading" indeterminate class="mt-2"></v-progress-linear>
        <v-divider></v-divider>
        <v-card-text ref="dirList" class="pa-0 dlg-list">
          <v-list density="compact" class="dirs" color="primary">
            <v-list-item v-if="!dlg.readable" class="bad" subtitle="This folder cannot be read"></v-list-item>
            <v-list-item v-else-if="!shown.length" :subtitle="dlg.dirs.length ? '(no folders match)' : '(no sub-folders)'"></v-list-item>
            <v-list-item v-for="(d, i) in shown" :key="d.path" :id="'dir-' + i" :active="i === dlg.sel"
                         prepend-icon="mdi-folder" @click="browse(d.path)" @mouseenter="dlg.sel = i">
              <v-list-item-title>{{ d.name }}</v-list-item-title>
              <template #append><v-icon icon="mdi-chevron-right" class="text-medium-emphasis"></v-icon></template>
            </v-list-item>
          </v-list>
        </v-card-text>
        <v-divider></v-divider>
        <v-card-actions class="px-4">
          <v-spacer></v-spacer>
          <v-btn @click="close">Cancel</v-btn>
          <v-btn color="primary" variant="flat" :disabled="!dlg.cwd" @click="choose">Choose this folder</v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>`,
};

// Mounts the page: its template is the page's <name>.html (in base.html), setup() gives it its data.
function mountPage(setup){
  const app = createApp({template: "#page", setup});
  app.component("page-frame", PageFrame);
  app.component("job-panel", JobPanel);
  app.component("folder-browser", FolderBrowser);
  app.use(Vuetify.createVuetify({theme: {defaultTheme: "system"}}));
  app.mount("#app");
}
