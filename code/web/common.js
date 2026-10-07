// Shared by every page: Vue 3 and Vuetify 4 (in vendor, loaded by base.html), the page frame, the project chooser
// and the job panel. Each page's script calls mountPage() and its <name>.html is the page's Vue template.
const { createApp, reactive, ref, computed, onMounted } = Vue;

// For every component on the page: an error to show, and whether the server has been closed
const ui = reactive({error: "", closed: false});

async function getJSON(url){ return (await fetch(url)).json(); }
async function post(url, body){
  const r = await fetch(url, {method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify(body||{})});
  const j = await r.json(); if(!r.ok) ui.error = j.error; return j;
}
// Tell the app this page is open, every few seconds, and when it closes: the app stops once every page has gone
const pageId = Math.random().toString(36).slice(2) + Date.now().toString(36);
function alive(){
  if(!ui.closed) fetch("/api/alive", {method:"POST", headers:{"Content-Type":"application/json"},
                                      body:JSON.stringify({page:pageId})}).catch(() => {});
}
alive();
setInterval(alive, 5000);
addEventListener("pagehide", () => navigator.sendBeacon("/api/bye", JSON.stringify({page:pageId})));
addEventListener("pageshow", e => { if(e.persisted) alive(); });   // back again from the browser's back/forward cache

// ---------- page frame: app bar with the links and Exit, the page's title and content, errors ----------
const LINKS = [
  {href:"/", text:"Home", icon:"mdi-home"},
  {href:"/prepare", text:"Prepare", icon:"mdi-package-variant-closed"},
  {href:"/makezip", text:"Make Zip", icon:"mdi-folder-zip"},
  {href:"/readme", text:"Instructions", icon:"mdi-book-open-variant"},
  {href:"/settings", text:"Settings", icon:"mdi-cog"},
];
const PageFrame = {
  props: {title: String},
  setup(){
    const exitAsk = ref(false);
    const { mdAndUp } = Vuetify.useDisplay();
    async function exit(){
      exitAsk.value = false;
      ui.closed = true;
      await post("/api/exit");
    }
    return {ui, links: LINKS, here: location.pathname, exitAsk, exit, mdAndUp};
  },
  template: `
  <v-app>
    <v-app-bar color="primary" density="comfortable" flat>
      <v-app-bar-title>Prep and Package</v-app-bar-title>
      <template #append>
        <template v-for="l in links" :key="l.href">
          <v-btn v-if="mdAndUp" :href="l.href" :prepend-icon="l.icon" :active="l.href === here" variant="text">{{ l.text }}</v-btn>
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
// page's selections allow a run at all. The default slot goes between the buttons and the log.
const JobPanel = {
  props: {api: String, label: String, icon: String, canStart: Boolean},
  emits: ["start", "finished"],
  setup(props, {emit}){
    const log = ref(null), running = ref(false), reachable = ref(true);
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
      }catch(e){ if(!ui.closed) reachable.value = false; }
      setTimeout(poll, 700);
    }
    onMounted(poll);
    return {log, running, reachable, stop: () => post(`${props.api}/stop`)};
  },
  template: `
    <div class="d-flex align-center ga-2 flex-wrap my-4">
      <v-btn color="primary" :prepend-icon="icon" :disabled="running || !canStart" @click="$emit('start')">{{ label }}</v-btn>
      <v-btn prepend-icon="mdi-stop" :disabled="!running" @click="stop">Stop</v-btn>
      <v-chip v-if="!reachable" color="error" variant="tonal">server unreachable</v-chip>
      <v-chip v-else-if="running" color="primary" variant="tonal">
        <v-progress-circular indeterminate size="14" width="2" class="mr-2"></v-progress-circular>running
      </v-chip>
      <v-chip v-else variant="tonal">idle</v-chip>
    </div>
    <slot></slot>
    <pre class="log mt-4" ref="log"></pre>`,
};

// ---------- project chooser (shared by the tool pages) ----------
// A path box that suggests folders as you type, a folder browser dialog and the project's options.
// Emits "project" with the details of the chosen project (null while there is no usable one).
// refresh() reads the details again.
const baseName = p => p.replace(/[\\/]+$/, "").split(/[\\/]/).pop() || p;
const ProjectPicker = {
  emits: ["project"],
  setup(props, {emit}){
    const path = ref(""), recent = ref([]), view = ref(null), optsOpen = ref([]), menu = ref(false);
    const note = reactive({text:"", kind:""}), optNote = reactive({text:"", kind:""});
    const options = reactive({main:"", site:false});
    const { smAndUp, xs } = Vuetify.useDisplay();
    let seq = 0, typing = null, remembered = null;

    const current = () => (path.value || "").trim();
    const isProject = computed(() => !!(view.value && view.value.exists && view.value.is_project));
    const versionText = computed(() => !options.main || !view.value ? "" :
                                       view.value.version ? "version " + view.value.version : "no version set");
    const installPy = computed(() => view.value ? "/api/project/installpy?path=" + encodeURIComponent(view.value.path) : "");

    function show(j){
      let info = null;
      view.value = j;
      if(!j.exists){ note.kind = "bad"; note.text = j.error; }
      else if(!j.is_project){ note.kind = "bad"; note.text = `${j.path} has no .py file in it or below it`; }
      else{
        const o = j.options;
        options.main = o.main;
        options.site = o.site_packages;
        if(!o.main){
          optsOpen.value = ["opts"];
          note.kind = "bad"; note.text = `Project "${j.name}": choose its main program in the options below`;
        }else{
          info = j;
          note.kind = "good";
          note.text = `Project "${j.name}" - runs ${o.main}, ` +
            (j.requirements ? `pip installs ${j.requirements}` : "no requirements.txt yet (Prepare makes one)") +
            (j.has_readme ? "" : " (no README.md)");
        }
      }
      emit("project", info);
    }
    async function check(p, remember){
      const my = ++seq;
      const j = p ? await getJSON("/api/project?path=" + encodeURIComponent(p))
                  : {exists:false, error:"Choose the project folder: type its full path or press Browse"};
      if(my !== seq) return;   // a newer choice has already replaced this one
      show(j);
      if(remember && j.exists && j.is_project && j.path !== remembered){
        remembered = j.path;
        post("/api/project", {path:j.path});
      }
    }

    // ----- suggestions while typing: the sub-folders of the folder typed so far that start with the rest -----
    const suggestions = ref([]);
    let sugSeq = 0, sugTimer = null, listed = {dir: null, j: null};
    function split(t){
      const i = Math.max(t.lastIndexOf("/"), t.lastIndexOf("\\"));
      return i < 0 ? null : [t.slice(0, i + 1), t.slice(i + 1)];
    }
    async function suggest(t){
      const parts = split(t), my = ++sugSeq;
      if(!parts){ suggestions.value = []; return; }
      const [dir, rest] = parts;
      if(listed.dir !== dir) listed = {dir, j: await getJSON("/api/browse?exact=1&path=" + encodeURIComponent(dir))};
      if(my !== sugSeq) return;
      const j = listed.j, start = rest.toLowerCase();
      // a project is complete as it is; any other folder gets a separator, so its own sub-folders come next
      suggestions.value = j.dirs.filter(d => d.name.toLowerCase().startsWith(start)).slice(0, 50)
        .map(d => ({value: d.is_project ? d.path : d.path + j.sep, name: d.name, project: d.is_project}));
    }
    // What the box offers: the recent projects, or once a path is being typed, the folders that fit it
    const items = computed(() => {
      const t = current().toLowerCase();
      const rec = recent.value.map(p => ({value: p, name: p, recent: true}));
      if(!t || recent.value.includes(current())) return rec;
      const found = new Set(suggestions.value.map(s => s.value));
      return [...suggestions.value, ...rec.filter(r => r.value.toLowerCase().includes(t) && !found.has(r.value))];
    });
    // Tab completes the folder name as far as the suggestions agree
    function complete(e){
      const parts = split(current());
      if(!parts || !suggestions.value.length) return;
      const names = suggestions.value.map(s => s.name);
      let common = names[0];
      for(const n of names) while(!n.toLowerCase().startsWith(common.toLowerCase())) common = common.slice(0, -1);
      const one = suggestions.value.length === 1 ? suggestions.value[0].value : null;
      const next = one || parts[0] + common;
      if(next.length > current().length){
        e.preventDefault();
        path.value = next;
        typed();
      }
    }
    // The box changes with every key: check the folder once typing pauses, and remember it (so the other tool
    // starts with it) when it is picked from the list, or on Enter or leaving the box
    function typed(){
      const t = current();
      const picked = suggestions.value.find(s => s.value === t);
      clearTimeout(typing);
      clearTimeout(sugTimer);
      sugTimer = setTimeout(() => suggest(t), 120);
      if(recent.value.includes(t) || (picked && picked.project)) check(t, true);
      else typing = setTimeout(() => check(t, false), 400);
      if(picked && !picked.project) Vue.nextTick(() => menu.value = true);   // carry on into that folder
    }
    function commit(){ clearTimeout(typing); check(current(), true); }
    async function saveOptions(){
      const r = await fetch("/api/project/options", {method:"POST", headers:{"Content-Type":"application/json"},
        body: JSON.stringify({path: current(), main: options.main || "", site_packages: options.site})});
      const j = await r.json();
      optNote.kind = r.ok ? "" : "bad";
      optNote.text = r.ok ? "Saved" : j.error;
      if(r.ok){ seq++; show(j); }
    }
    function choose(p){
      path.value = p;
      dlg.open = false;
      menu.value = false;
      clearTimeout(typing);
      check(p, true);
    }

    // ----- the folder browser dialog -----
    const dlg = reactive({open:false, cwd:"", crumbs:[], dirs:[], isProject:false, filter:"", sel:0, loading:false});
    const filterBox = ref(null), dirList = ref(null);
    const shown = computed(() => {
      const f = (dlg.filter || "").toLowerCase();
      return dlg.dirs.filter(d => d.name.toLowerCase().includes(f));
    });
    Vue.watch(() => dlg.filter, () => dlg.sel = 0);
    // Opens folder p in the dialog, with the sub-folder called mark (if any) highlighted
    async function browse(p, mark){
      dlg.loading = true;
      try{
        const j = await getJSON("/api/browse?path=" + encodeURIComponent(p || ""));
        Object.assign(dlg, {cwd: j.path, crumbs: j.crumbs, dirs: j.dirs, isProject: j.is_project, filter: "", sel: 0});
        if(dirList.value) dirList.value.$el.scrollTop = 0;   // the card text is what scrolls
        if(mark) moveTo(shown.value.findIndex(d => d.name === mark));
      }finally{ dlg.loading = false; }
      if(filterBox.value) filterBox.value.focus();
    }
    // Starts next to the chosen project (highlighted), else in the folder typed, else where the app suggests
    function openBrowser(){
      dlg.open = true;
      const p = isProject.value ? view.value.path : "";
      const up = p.slice(0, Math.max(p.lastIndexOf("/"), p.lastIndexOf("\\")) + 1);   // keeps / and C:\ whole
      if(up && up !== p) browse(up, baseName(p));
      else browse(current());
    }
    function moveTo(i){
      dlg.sel = Math.max(0, Math.min(i, shown.value.length - 1));
      Vue.nextTick(() => { const e = document.getElementById("dir-" + dlg.sel); if(e) e.scrollIntoView({block:"nearest"}); });
    }
    function open(d){ d.is_project ? choose(d.path) : browse(d.path); }
    function onKey(e){
      if(e.key === "ArrowDown"){ e.preventDefault(); moveTo(dlg.sel + 1); }
      else if(e.key === "ArrowUp"){ e.preventDefault(); moveTo(dlg.sel - 1); }
      else if(e.key === "Enter"){ const d = shown.value[dlg.sel]; if(d){ e.preventDefault(); open(d); } }
      else if(e.key === "Backspace" && !dlg.filter && dlg.crumbs.length > 1){
        e.preventDefault();
        browse(dlg.crumbs[dlg.crumbs.length - 2].path);
      }
    }

    onMounted(async () => {
      const j = await getJSON("/api/project");
      recent.value = j.recent;
      path.value = remembered = j.project || "";
      check(current(), false);
    });
    return {path, recent, view, optsOpen, menu, note, optNote, options, isProject, versionText, installPy, smAndUp, xs,
            items, typed, commit, complete, saveOptions, choose, baseName,
            dlg, shown, filterBox, dirList, browse, openBrowser, open, onKey,
            refresh: () => check(current(), false)};
  },
  template: `
  <div>
    <v-combobox v-model="path" v-model:menu="menu" :items="items" item-title="value" item-value="value" :return-object="false"
                no-filter label="Project folder" placeholder="Full path, or press Browse" autocomplete="off" hide-details
                @update:model-value="typed" @blur="commit" @keydown.enter="commit" @keydown.tab="complete">
      <template #item="{ item, props: ip }">
        <v-list-item v-bind="ip" :title="item.name" :prepend-icon="item.recent ? 'mdi-history' : item.project ? 'mdi-folder-star' : 'mdi-folder'">
          <template v-if="item.project" #append><v-chip size="x-small" color="primary">project</v-chip></template>
        </v-list-item>
      </template>
      <template #append>
        <v-btn v-if="smAndUp" prepend-icon="mdi-folder-search-outline" @click="openBrowser">Browse…</v-btn>
        <v-btn v-else icon="mdi-folder-search-outline" title="Browse" @click="openBrowser"></v-btn>
      </template>
    </v-combobox>
    <div class="note">Any folder with a .py file in it or below it. Tab completes a folder name.</div>
    <div :class="['note', note.kind]">{{ note.text }}</div>

    <v-dialog v-model="dlg.open" max-width="700" :fullscreen="xs" scrollable @after-enter="filterBox && filterBox.focus()">
      <v-card>
        <v-card-title class="d-flex align-center">
          Choose project folder<v-spacer></v-spacer>
          <v-btn icon="mdi-close" variant="text" size="small" title="Close" @click="dlg.open = false"></v-btn>
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
        <div v-if="smAndUp" class="note px-4">↑ ↓ move · Enter opens a folder or selects a project · Backspace goes up</div>
        <v-progress-linear :active="dlg.loading" indeterminate class="mt-2"></v-progress-linear>
        <v-divider></v-divider>
        <v-card-text ref="dirList" class="pa-0 dlg-list">
          <v-list density="compact" class="dirs" color="primary">
            <v-list-item v-if="!shown.length" :subtitle="dlg.dirs.length ? '(no folders match)' : '(no sub-folders)'"></v-list-item>
            <v-list-item v-for="(d, i) in shown" :key="d.path" :id="'dir-' + i" :active="i === dlg.sel" :class="{project: d.is_project}"
                         :prepend-icon="d.is_project ? 'mdi-folder-star' : 'mdi-folder'" @click="open(d)" @mouseenter="dlg.sel = i">
              <v-list-item-title>{{ d.name }}</v-list-item-title>
              <template #append>
                <template v-if="d.is_project">
                  <v-chip size="x-small" color="primary" class="mr-2">project</v-chip>
                  <v-btn size="small" color="primary" @click.stop="choose(d.path)">Select</v-btn>
                </template>
                <v-icon v-else icon="mdi-chevron-right" class="text-medium-emphasis"></v-icon>
              </template>
            </v-list-item>
          </v-list>
        </v-card-text>
        <v-divider></v-divider>
        <div v-if="recent.length" class="d-flex align-center ga-2 flex-wrap px-4 pt-3">
          <span class="text-body-2 text-medium-emphasis">Recent:</span>
          <v-chip v-for="p in recent" :key="p" size="small" prepend-icon="mdi-history" :title="p" @click="choose(p)">{{ baseName(p) }}</v-chip>
        </div>
        <v-card-actions class="px-4">
          <span v-if="!dlg.isProject" class="text-body-2 text-medium-emphasis">This folder is not a project</span>
          <v-spacer></v-spacer>
          <v-btn @click="dlg.open = false">Cancel</v-btn>
          <v-btn color="primary" variant="flat" :disabled="!dlg.isProject" @click="choose(dlg.cwd)">Use this folder</v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>

    <v-expansion-panels v-if="isProject" v-model="optsOpen" multiple class="mt-3">
      <v-expansion-panel value="opts" title="Project options">
        <v-expansion-panel-text>
          <div class="d-flex align-center ga-4 flex-wrap">
            <v-select v-model="options.main" :items="view.programs" label="Main program" placeholder="(choose)"
                      persistent-placeholder hide-details class="main-select" @update:model-value="saveOptions"></v-select>
            <span>{{ versionText }}</span>
          </div>
          <v-checkbox v-model="options.site" hide-details @update:model-value="saveOptions"
                      label="The venv can also use Python packages already installed on the system (--system-site-packages)"></v-checkbox>
          <div :class="['note', optNote.kind]">{{ optNote.text }}</div>
          <div class="note">Saved as soon as you change them, and used by both tools. Packages are installed into the venv with pip, from the project's requirements.txt.
            A change to the system packages option takes effect at the next Prepare, which then makes a new venv.
            <a v-if="options.main" :href="installPy" target="_blank">See the install.py these make</a><span v-if="options.main"> (it goes into the zip).</span></div>
        </v-expansion-panel-text>
      </v-expansion-panel>
    </v-expansion-panels>
  </div>`,
};

// Mounts the page: its template is the page's <name>.html (in base.html), setup() gives it its data.
function mountPage(setup){
  const app = createApp({template: "#page", setup});
  app.component("page-frame", PageFrame);
  app.component("job-panel", JobPanel);
  app.component("project-picker", ProjectPicker);
  app.use(Vuetify.createVuetify({theme: {defaultTheme: "system"}}));
  app.mount("#app");
}
