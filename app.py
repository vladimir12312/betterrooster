#!/usr/bin/env python3
"""RUG (University of Groningen) timetable viewer - WSGI version.

Same single-file app as rug_schedule_web.py, adapted for hosting on a generic
WSGI server (e.g. Render, PythonAnywhere, a VPS). Exposes a WSGI `application`
callable.

Pure Python standard library - no pip installs needed.

Local run (for testing):
    python3 app.py
then open http://127.0.0.1:8000 in your browser.

On a WSGI host, point the server at the `application` callable in this file
(e.g. on Render: `gunicorn app:application`).
"""

import json
import os
from urllib import request as urlrequest
from urllib.error import HTTPError

BASE_URL = "https://rooster.rug.nl"
ACADEMIC_YEAR = "2026-2027"
PORT = int(os.environ.get("PORT", "8000"))

# Activity types that are taught in small student groups. Only these are filtered
# by the selected group; lectures/exams are always shown for the whole class.
GROUPED_TYPES = {
    "Tutorial", "Practical", "Computer practical",
    "Workgroup", "Werkgroep", "Practicum",
}

# ---------------------------------------------------------------------------
# RUG API client
# ---------------------------------------------------------------------------

def rug_post(path, payload):
    url = BASE_URL + path
    req = urlrequest.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlrequest.urlopen(req, timeout=30) as resp:
            return json.load(resp)
    except HTTPError as e:
        body = e.read().decode("utf-8", "replace")
        raise RuntimeError(f"RUG API error {e.code} on {path}: {body[:300]}") from e


def search(kind, term, limit=50):
    key = {
        "programme": "programme-offerings",
        "course": "course-offerings",
        "group": "student-groups",
    }[kind]
    if not term.strip():
        return []
    data = rug_post(
        f"/maat/api/{ACADEMIC_YEAR}/{key}/search",
        {"searchText": term, "academicYear": ACADEMIC_YEAR, "limit": limit},
    )
    out = []
    for r in data.get("results", []):
        item = {"id": r["id"], "name": r.get("displayNameEn") or r.get("displayNameNl", "")}
        if key == "programme-offerings":
            item["code"] = r.get("code", "")
            item["info"] = f"Y{r.get('yearOfStudy')} {r.get('specialisation') or ''}".strip()
        elif key == "course-offerings":
            item["code"] = r.get("code", "")
            item["info"] = (r.get("term") or "")
        else:
            item["code"] = ""
            item["info"] = ""
        out.append(item)
    return out


def generate_schedule(object_ids, course_codes):
    data = rug_post(
        f"/maat/api/{ACADEMIC_YEAR}/schedule/generate",
        {"objects": object_ids, "courseOfferingCodes": course_codes},
    )
    activities = []
    for r in data.get("results", []):
        s, e = r["start"], r["end"]
        atype = (r.get("activityType") or {}).get("displayNameEn") or ""
        desc = r.get("description") or ""
        rooms = [
            {
                "code": x.get("code") or "",
                "name": x.get("displayNameEn") or x.get("displayNameNl", ""),
                "map": x.get("urlMap") or "",
            }
            for x in r.get("rooms", []) or []
        ]
        activities.append({
            "id": r["id"],
            "start": {"y": s[0], "m": s[1], "d": s[2], "H": s[3], "M": s[4]},
            "end": {"y": e[0], "m": e[1], "d": e[2], "H": e[3], "M": e[4]},
            "type": atype or desc,
            "comment": r.get("comment") or "",
            "courses": ", ".join(c.get("displayNameEn", "") for c in r.get("courseOfferings", [])),
            "programmes": ", ".join(p.get("displayNameEn", "") for p in r.get("programmeOfferings", [])),
            "programmeIds": [p.get("id") for p in r.get("programmeOfferings", []) if p.get("id")],
            "groups": [
                {"id": x["id"], "name": x.get("displayNameEn") or x.get("displayNameNl", "")}
                for x in r.get("studentGroups", [])
            ],
            "rooms": rooms,
        })
    activities.sort(key=lambda a: (a["start"]["y"], a["start"]["m"], a["start"]["d"],
                                   a["start"]["H"], a["start"]["M"]))
    return activities


def course_groups(course_codes):
    """All student groups that actually have activities for the given courses."""
    acts = generate_schedule([], list(course_codes))
    seen = {}
    for a in acts:
        for g in a.get("groups", []):
            seen.setdefault(g["id"], g["name"])
    out = [{"id": i, "name": n} for i, n in seen.items()]
    out.sort(key=lambda x: x["name"].lower())
    return out


def programme_groups(programme_ids):
    """Small-group (tutorial/practical) groups across all courses in a programme.

    Only groups from GROUPED_TYPES activities are offered, so the group the user
    picks for a programme reliably filters tutorials across every course in it.
    """
    acts = generate_schedule(list(programme_ids), [])
    seen = {}
    for a in acts:
        if a.get("type") not in GROUPED_TYPES:
            continue
        for g in a.get("groups", []):
            seen.setdefault(g["id"], g["name"])
    out = [{"id": i, "name": n} for i, n in seen.items()]
    out.sort(key=lambda x: x["name"].lower())
    return out


# ---------------------------------------------------------------------------
# Embedded front-end
# ---------------------------------------------------------------------------

PAGE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>RUG Schedule</title>
<style>
:root{--red:#cc0000;--light:#f7f7f7;--line:#e0e0e0;--text:#222}
*{box-sizing:border-box}
body{margin:0;font-family:"Segoe UI",system-ui,Arial,sans-serif;background:var(--light);color:var(--text)}
header{background:var(--red);color:#fff;padding:10px 20px;display:flex;align-items:center;gap:12px;flex-wrap:wrap}
header h1{font-size:18px;margin:0}
header .tag{font-size:12px;opacity:.85}
main{padding:16px 20px 40px;max-width:1200px;margin:0 auto}
.row{display:flex;gap:10px;flex-wrap:wrap;align-items:center}
button{background:var(--red);color:#fff;border:0;border-radius:4px;padding:7px 14px;cursor:pointer;font-size:13px}
button:hover{filter:brightness(1.1)}
button.ghost{background:#fff;color:var(--red);border:1px solid var(--red)}
button:disabled{opacity:.5;cursor:default}
button.link{background:none;color:var(--red);border:0;padding:0;font-size:12px;text-decoration:underline}
input[type=text],select{padding:7px;border:1px solid var(--line);border-radius:4px;font-size:13px}
.panel{background:#fff;border:1px solid var(--line);border-radius:6px;padding:14px;margin:14px 0}
.panel h2{font-size:14px;margin:0 0 6px;color:var(--red)}
.panel .hint{font-size:12px;color:#888;margin:0 0 10px}
table{border-collapse:collapse;width:100%;font-size:13px}
th,td{border:1px solid var(--line);padding:6px 8px;text-align:left;vertical-align:top}
th{background:#f0f0f0}
.muted{color:#777;font-size:12px}
.ok{color:#0a0;font-size:13px}
.err{color:var(--red);font-size:13px;white-space:pre-wrap}
.noweek{color:#888;font-size:13px}
/* saved filters */
.filter-item{font-size:13px;padding:8px 10px;margin:4px 0;background:#fafafa;border:1px solid var(--line);border-radius:4px;display:flex;justify-content:space-between;align-items:center;gap:8px}
.filter-item.active{border-color:var(--red);background:#fff5f5}
.filter-item .name{font-weight:bold}
.filter-item .lbl{color:#666;font-size:12px}
.filter-item .acts button{margin-left:6px}
/* pair builder */
.pair{border:1px solid var(--line);border-radius:6px;padding:10px;margin:8px 0;background:#fcfcfc;display:flex;gap:12px;align-items:flex-start;flex-wrap:wrap}
.col{flex:1;min-width:260px}
.col label{font-size:12px;font-weight:600;color:#555;display:block;margin-bottom:4px}
.tt{position:relative}
.tt-input{width:100%}
.tt-drop{position:absolute;left:0;right:0;top:100%;z-index:50;background:#fff;border:1px solid var(--line);border-radius:4px;margin-top:2px;max-height:260px;overflow:auto;display:none;box-shadow:0 4px 12px rgba(0,0,0,.12)}
.tt-item{padding:6px 9px;font-size:13px;cursor:pointer;border-bottom:1px solid #f2f2f2}
.tt-item:hover,.tt-item.hl{background:#fdecec}
.tt-item .scoped{color:#a05;font-size:11px;margin-left:6px}
.delpair{background:#fff;color:var(--red);border:1px solid var(--line);border-radius:4px;font-size:15px;line-height:1;padding:6px 10px;cursor:pointer;margin-top:22px}
.pair .picked{font-size:12.5px;color:#333;background:#fdecec;border:1px solid #f5c6c6;border-radius:4px;padding:4px 8px;margin-top:6px;display:none}
.chip{display:inline-block;background:#fff5f5;border:1px solid var(--line);border-radius:4px;padding:4px 8px;margin:3px 4px 0 0;font-size:12px}
.chip .rm{cursor:pointer;color:var(--red);margin-left:5px}
.savebar{display:flex;gap:8px;align-items:center;margin-top:12px;flex-wrap:wrap}
.week{overflow-x:auto}
.week table{table-layout:fixed;min-width:900px}
.week td{height:52px;width:120px}
.week td.time{width:60px;font-weight:600;font-size:12px;color:#555}
.week .slot{background:#fff5f5;border-radius:3px;padding:3px}
.week .slot b{font-size:12px}
.week .slot .grp{font-size:10px;color:#a05;display:block}
.week .slot .cm{font-size:11px;color:#555;white-space:nowrap}
.week .slot .loc{font-size:11px;color:#063;font-weight:600;white-space:nowrap;display:inline-block;background:#e8f5ec;border-radius:3px;padding:0 4px;margin:2px 0;text-decoration:none}
.future{outline:2px solid var(--red);outline-offset:-2px}
.past{opacity:.4}
.foot{margin:8px auto 24px;max-width:1200px;padding:0 20px;font-size:10.5px;color:#999}
.foot a{color:#999;text-decoration:underline}
.foot p{margin:4px 0 0;font-size:9.5px}
#status{font-size:12px}
.weeknav{display:flex;gap:8px;align-items:center;margin:8px 0;flex-wrap:wrap}
</style>
</head>
<body>
<header>
  <h1>RUG Schedule</h1>
  <span class="tag">academic year 2026-2027 &middot; rooster.rug.nl</span>
</header>
<main>

  <div class="panel">
    <h2>1. Saved filters</h2>
    <div class="hint">Stored in your browser until you delete them. Click a filter to load it.</div>
    <div id="filters"></div>
  </div>

  <div class="panel">
    <h2>2. Build filter &mdash; course + your group</h2>
    <div class="hint">
      For each course, search and pick the course, then pick your student group
      (the group list appears as you type). You'll see all lectures of the course
      but only the tutorials of your group. Leave a group empty to see everything.
    </div>
    <div id="pairs"></div>
    <div id="progs"></div>
    <div class="row" style="margin-top:6px">
      <button id="btnAddCourse" class="ghost">+ Add course</button>
      <button id="btnAddProg" class="ghost">+ Add programme</button>
      <button id="btnClearAll" class="ghost">Clear all</button>
      <span id="status" class="muted"></span>
    </div>
    <div class="savebar">
      <input type="text" id="filterName" placeholder="Filter name, e.g. Semester 1a" size="22">
      <button id="btnSave">Save</button>
      <button id="btnSaveAs" class="ghost">Save as copy</button>
      <span id="saveMsg" class="ok"></span>
    </div>
  </div>

  <div class="panel">
    <h2>3. Schedule</h2>
    <button id="btnGenerate">Generate schedule</button>
    <div class="weeknav">
      <button id="btnPrev" class="ghost">&larr; Prev week</button>
      <b id="weekLabel"></b>
      <button id="btnNext" class="ghost">Next week &rarr;</button>
      <button id="btnToday" class="ghost">This week</button>
    </div>
    <div class="week" id="schedule"><span class="noweek">Pick courses and groups, then generate.</span></div>
  </div>

</main>
<footer class="foot">
  <a href="https://rooster.rug.nl/current" target="_blank" rel="noopener">RUG original timetable</a> &middot;
  <a href="https://github.com/vladimir12312/betterrooster" target="_blank" rel="noopener">Source on GitHub</a>
  <p>Software is provided as-is and uses the RUG rooster.rug.nl website API endpoints.</p>
</footer>
<script>
const $=(s,r=document)=>r.querySelector(s);
function post(url,body){return fetch(url,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(body)}).then(async r=>{if(!r.ok)throw new Error((await r.json()).error||("HTTP "+r.status));return r.json()})}
const API={
  search:async(kind,term)=>(await post("/api/search",{kind,term})).items,
  courseGroups:codes=>post("/api/course-groups",{courseCodes:codes}),
  programmeGroups:ids=>post("/api/programme-groups",{programmeIds:ids}),
  generate:sel=>post("/api/generate",sel),
};
const STORE_KEY="rug_filters_v3";
const state={pairs:[],programmes:[],activities:[],scheduleWeek:null,currentFilterId:null};
const DAYS=["Monday","Tuesday","Wednesday","Thursday","Friday","Saturday","Sunday"];
const SLOTS=[];for(let h=9;h<=21;h+=2)SLOTS.push(h);
const pad=n=>String(n).padStart(2,"0");
function esc(s){return String(s).replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]))}
function today0(){const t=new Date();return new Date(t.getFullYear(),t.getMonth(),t.getDate())}
function mondayOf(d){const x=new Date(d.getFullYear(),d.getMonth(),d.getDate());x.setDate(x.getDate()-((x.getDay()+6)%7));return x}
function mondayPlus7(m){const d=new Date(m);d.setDate(d.getDate()+7);return d}
function fmtShort(d){return d.getFullYear()+"-"+pad(d.getMonth()+1)+"-"+pad(d.getDate())}
function dayStart(d){return new Date(d.getFullYear(),d.getMonth(),d.getDate())}
const MONTHS=["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];

// ---------------- typeahead ----------------
// input: input element; drop: dropdown element; fetch(term)->[{name,meta}]
// onpick(option) called when user picks; option has .pick attached.
function typeahead(input, drop, fetch, onpick){
  let cur=[],timer=null;
  function show(opts){
    cur=opts;
    if(!cur.length){drop.style.display="none";return}
    drop.innerHTML=cur.map((o,i)=>`<div class="tt-item" data-i="${i}"><b>${esc(o.name)}</b>${o.meta?` <span class="muted">${esc(o.meta)}</span>`:""}${o.tag?` <span class="scoped">${esc(o.tag)}</span>`:""}</div>`).join("");
    drop.style.display="block";
  }
  async function run(){
    const t=input.value.trim();
    try{ show(await fetch(t)); }catch(e){ drop.innerHTML='<div class="tt-item err">'+esc(e.message)+'</div>';drop.style.display="block"; }
  }
  input.addEventListener("input",()=>{clearTimeout(timer);timer=setTimeout(run,260)});
  input.addEventListener("focus",()=>{if(!input.value)run();else setTimer()});
  function setTimer(){clearTimeout(timer);timer=setTimeout(run,120)}
  function pick(i){const o=cur[i];if(!o)return;if(o.pick)o.pick();else onpick(o);drop.style.display="none";cur=[]}
  input.addEventListener("keydown",e=>{
    if(e.key==="Enter"){e.preventDefault();const sel=drop.querySelector(".hl")||drop.querySelector(".tt-item");if(sel)pick(+sel.dataset.i);}
    else if(e.key==="Escape"){drop.style.display="none"}
    else if(e.key==="ArrowDown"){move(true);e.preventDefault()}
    else if(e.key==="ArrowUp"){move(false);e.preventDefault()}
  });
  function move(down){
    const items=[...drop.querySelectorAll(".tt-item")];if(!items.length)return;
    let idx=items.findIndex(el=>el.classList.contains("hl"));
    if(down){idx=idx+1>=items.length?0:idx+1}else{idx=idx-1<0?items.length-1:idx-1}
    items.forEach(el=>el.classList.remove("hl"));items[idx].classList.add("hl");
    items[idx].scrollIntoView({block:"nearest"});
  }
  drop.addEventListener("mousedown",e=>{e.preventDefault();const el=e.target.closest(".tt-item");if(el)pick(+el.dataset.i)});
  input.addEventListener("blur",()=>{setTimeout(()=>{drop.style.display="none"},160)});
}

// ---------------- saved filters ----------------
function loadFilters(){try{return JSON.parse(localStorage.getItem(STORE_KEY))||[]}catch(e){return[]}}
function saveFilters(list){localStorage.setItem(STORE_KEY,JSON.stringify(list))}
function newId(){return Date.now().toString(36)+Math.random().toString(36).slice(2,8)}

function filterSummary(f){
  const bits=[];
  if(f.courses&&f.courses.length)bits.push(f.courses.length+" course(s)");
  if(f.programmes&&f.programmes.length)bits.push(f.programmes.length+" programme(s)");
  return bits.join(" &middot; ")||"empty";
}

function renderFilters(){
  const box=$("#filters");
  const list=loadFilters();
  if(!list.length){box.innerHTML='<span class="muted">No saved filters yet.</span>';return}
  box.innerHTML=list.map(f=>`
    <div class="filter-item ${f.id===state.currentFilterId?"active":""}">
      <div><div class="name">${esc(f.name)}</div>
        <div class="lbl">${filterSummary(f)}</div></div>
      <div class="acts">
        <button data-load="${f.id}">${f.id===state.currentFilterId?'<b>&bull; editing</b>':"Use"}</button>
        <button class="ghost" data-del="${f.id}">Delete</button>
      </div>
    </div>`).join("");
  box.querySelectorAll("[data-load]").forEach(b=>b.onclick=()=>applyFilter(b.dataset.load));
  box.querySelectorAll("[data-del]").forEach(b=>b.onclick=()=>deleteFilter(b.dataset.del));
}

function applyFilter(id){
  const f=loadFilters().find(x=>x.id===id);if(!f)return;
  state.currentFilterId=f.id;
  state.pairs=(f.courses||[]).map(c=>({c:{code:c.code,name:c.name,term:c.term||""},g:c.group?{id:c.group.id,name:c.group.name}:null,_groups:[]}));
  state.programmes=(f.programmes||[]).map(p=>({id:p.id,name:p.name,g:p.group?{id:p.group.id,name:p.group.name}:null,_groups:[]}));
  state.activities=[];state.scheduleWeek=null;
  $("#filterName").value=f.name;
  loadAllCourseGroups();
  loadAllProgrammeGroups();
  renderPairs();renderProgs();renderFilters();
  $("#schedule").innerHTML='<span class="noweek">Loaded filter. Press &quot;Generate schedule&quot;.</span>';
}

function deleteFilter(id){
  const list=loadFilters().filter(x=>x.id!==id);
  saveFilters(list);
  if(state.currentFilterId===id){state.currentFilterId=null;state.activities=[];state.scheduleWeek=null;}
  renderFilters();
}

function currentFilter(){
  return {
    courses:state.pairs.map(p=>p.c?({code:p.c.code,name:p.c.name,term:p.c.term,group:p.g?{id:p.g.id,name:p.g.name}:null}):null).filter(Boolean),
    programmes:state.programmes.map(p=>({id:p.id,name:p.name,group:p.g?{id:p.g.id,name:p.g.name}:null})),
  };
}

function saveCurrent(asCopy){
  const name=$("#filterName").value.trim();
  if(!name){alert("Give the filter a name first.");return}
  const data=currentFilter();
  if(!data.courses.length&&!data.programmes.length){alert("Nothing to save - add a course first.");return}
  const list=loadFilters();
  let target;
  if(!asCopy&&state.currentFilterId&&list.find(x=>x.id===state.currentFilterId)){
    target=list.find(x=>x.id===state.currentFilterId);
  }else{
    target={id:newId()};list.push(target);
  }
  target.name=name;target.courses=data.courses;target.programmes=data.programmes;
  state.currentFilterId=target.id;
  saveFilters(list);
  renderFilters();
  const msg=$("#saveMsg");msg.textContent="Saved &quot;"+name+"&quot;.";
  setTimeout(()=>msg.textContent="",2500);
}

// ---------------- pair builder ----------------
function loadCourseGroups(i){
  const p=state.pairs[i];
  p._groups=[];
  if(!p.c||!p.c.code)return Promise.resolve();
  return API.courseGroups([p.c.code]).then(r=>{p._groups=r.groups||[]}).catch(()=>{p._groups=[]});
}
function loadAllCourseGroups(){
  return Promise.all(state.pairs.map((_,i)=>loadCourseGroups(i)));
}

function loadProgGroups(i){
  const p=state.programmes[i];
  p._groups=[];
  if(!p.id)return Promise.resolve();
  return API.programmeGroups([p.id]).then(r=>{p._groups=r.groups||[]}).catch(()=>{p._groups=[]});
}
function loadAllProgrammeGroups(){
  return Promise.all(state.programmes.map((_,i)=>loadProgGroups(i)));
}

function buildPairRow(i){
  const p=state.pairs[i];
  const wrap=document.createElement("div");
  wrap.className="pair";
  wrap.innerHTML=`
    <div class="col">
      <label>Course</label>
      <div class="tt"><input type="text" class="tt-input" placeholder="type a course name or code..." value="${p.c?esc(p.c.name):""}">
        <div class="tt-drop"></div></div>
      <div class="picked"></div>
    </div>
    <div class="col">
      <label>Your group ${p.g?`<button class="link" data-clear="${i}">clear</button>`:""}</label>
      <div class="tt"><input type="text" class="tt-input" placeholder="${p.c?"type or pick your group...":"pick a course first"}" ${p.c?"":"disabled"} value="${p.g?esc(p.g.name):""}">
        <div class="tt-drop"></div></div>
    </div>
    <button class="delpair" data-del="${i}" title="Remove">&times;</button>`;
  const cInp=wrap.querySelectorAll(".tt-input")[0], cDrop=wrap.querySelectorAll(".tt-drop")[0];
  const gInp=wrap.querySelectorAll(".tt-input")[1], gDrop=wrap.querySelectorAll(".tt-drop")[1];

  typeahead(cInp,cDrop,async term=>{
    const opts=(await API.search("course",term)).map(o=>({name:o.name,meta:`${o.code} · ${o.info}`,pick:()=>{
      if(p.c&&p.c.code===o.code)return;
      const code=o.code;
      p.c={code:o.code,name:o.name,term:o.info};p.g=null;
      rebuildPair(i);
      loadCourseGroups(i).then(()=>{
        if(p.c&&p.c.code!==code)return;
        const row=$("#pairs").children[i];
        const gi=row?row.querySelectorAll(".tt-input")[1]:null;
        if(gi){gi.disabled=false;gi.placeholder="type or pick your group...";gi.focus()}
      });
    }}));
    return opts;
  },()=>{});

  typeahead(gInp,gDrop,async term=>{
    const t=term.toLowerCase();
    const courseGroupOpts=(p._groups||[]).filter(g=>!t||g.name.toLowerCase().includes(t))
      .map(g=>({name:g.name,tag:"this course",pick:()=>{p.g={id:g.id,name:g.name};rebuildPair(i)}}));
    if(!state.pairs[i]||!p.c){
      return courseGroupOpts;
    }
    const extra=(await API.search("group",term))
      .filter(o=>!p._groups.some(g=>g.id===o.id))
      .map(o=>({name:o.name,meta:o.info||o.code,pick:()=>{p.g={id:o.id,name:o.name};rebuildPair(i)}}));
    return courseGroupOpts.concat(extra);
  },()=>{});

  if(p.c&&p.g){
    const chip=wrap.querySelector(".picked");
    chip.style.display="block";
    chip.innerHTML=`Course: <b>${esc(p.c.name)}</b> &rarr; group: <b>${esc(p.g.name)}</b>`;
  }
  const clearBtn=wrap.querySelector("[data-clear]");
  if(clearBtn)clearBtn.onclick=e=>{e.stopPropagation();p.g=null;rebuildPair(i)};
  wrap.querySelector("[data-del]").onclick=()=>{state.pairs.splice(i,1);if(!state.pairs.length)state.pairs.push(newPair());renderPairs()};
  return wrap;
}

function newPair(){return {c:null,g:null,_groups:[]}}

function renderPairs(){
  const box=$("#pairs");
  if(!state.pairs.length)state.pairs.push(newPair());
  box.innerHTML="";
  state.pairs.forEach((_,i)=>box.appendChild(buildPairRow(i)));
}

function rebuildPair(i){const box=$("#pairs");box.innerHTML="";state.pairs.forEach((_,j)=>box.appendChild(buildPairRow(j)))}

function buildProgRow(i){
  const p=state.programmes[i];
  const wrap=document.createElement("div");
  wrap.className="pair";
  wrap.innerHTML=`
    <div class="col">
      <label>Programme</label>
      <div class="tt"><input type="text" class="tt-input" placeholder="type a programme name or code..." value="${esc(p.name)}">
        <div class="tt-drop"></div></div>
      <div class="picked" style="display:block"><b>${esc(p.name)}</b></div>
    </div>
    <div class="col">
      <label>Tutorial group ${p.g?`<button class="link" data-clear="${i}">clear</button>`:""}</label>
      <div class="tt"><input type="text" class="tt-input" placeholder="${p.id?"type or pick your group for all courses...":"pick a programme first"}" ${p.id?"":"disabled"} value="${p.g?esc(p.g.name):""}">
        <div class="tt-drop"></div></div>
      <div class="picked"></div>
    </div>
    <button class="delpair" data-del="${i}" title="Remove">&times;</button>`;
  const inp=wrap.querySelector(".tt-input"),drop=wrap.querySelector(".tt-drop");
  const gInp=wrap.querySelectorAll(".tt-input")[1],gDrop=wrap.querySelectorAll(".tt-drop")[1];

  typeahead(inp,drop,async term=>(await API.search("programme",term))
    .map(o=>({name:o.name,meta:o.info||o.code,pick:()=>{
      if(p.id===o.id)return;
      const id=o.id;
      p.id=o.id;p.name=o.name;p.g=null;
      rebuildProg(i);
      loadProgGroups(i).then(()=>{
        if(p.id!==id)return;
        const row=$("#progs").children[i];
        const gi=row?row.querySelectorAll(".tt-input")[1]:null;
        if(gi){gi.disabled=false;gi.placeholder="type or pick your group for all courses...";gi.focus()}
      });
    }})),()=>{});

  typeahead(gInp,gDrop,async term=>{
    const t=term.toLowerCase();
    const progGroupOpts=(p._groups||[]).filter(g=>!t||g.name.toLowerCase().includes(t))
      .map(g=>({name:g.name,tag:"this programme",pick:()=>{p.g={id:g.id,name:g.name};rebuildProg(i)}}));
    if(!state.programmes[i]||!p.id)return progGroupOpts;
    const extra=(await API.search("group",term))
      .filter(o=>!(p._groups||[]).some(g=>g.id===o.id))
      .map(o=>({name:o.name,meta:o.info||o.code,pick:()=>{p.g={id:o.id,name:o.name};rebuildProg(i)}}));
    return progGroupOpts.concat(extra);
  },()=>{});

  if(p.id&&p.g){
    const chip=wrap.querySelectorAll(".picked")[1];
    chip.style.display="block";
    chip.innerHTML=`Programme: <b>${esc(p.name)}</b> &rarr; tutorial group: <b>${esc(p.g.name)}</b>`;
  }
  const clearBtn=wrap.querySelector("[data-clear]");
  if(clearBtn)clearBtn.onclick=e=>{e.stopPropagation();p.g=null;rebuildProg(i)};
  wrap.querySelector("[data-del]").onclick=()=>{state.programmes.splice(i,1);renderProgs()};
  return wrap;
}
function renderProgs(){
  const box=$("#progs");box.innerHTML="";
  state.programmes.forEach((_,i)=>box.appendChild(buildProgRow(i)));
}
function rebuildProg(i){renderProgs()}

function addCourse(){state.pairs.push(newPair());renderPairs()}
function addProg(){state.programmes.push({id:null,name:"",g:null,_groups:[]});renderProgs()}
function clearAll(){state.pairs=[];state.programmes=[];state.activities=[];state.scheduleWeek=null;renderPairs();renderProgs();$("#schedule").innerHTML='<span class="noweek">Pick courses and groups, then generate.</span>'}

// ---------------- group rule ----------------
// Only small-group session types are filtered by the selected group.
// A course's group filters that course's tutorials; a programme's group filters
// the tutorials of every course in that programme. Lectures, exams and any other
// activity type are ALWAYS included, even when the API attaches a cohort-wide
// student group to them (which would otherwise hide a lecture you attend).
const GROUPED_TYPES=new Set(["Tutorial","Practical","Computer practical","Workgroup","Werkgroep","Practicum"]);
function groupFiltered(activities){
  const courseGroupIds=state.pairs.filter(p=>p.g&&p.g.id).map(p=>p.g.id);
  const progs=state.programmes.filter(p=>p.id&&p.g&&p.g.id);
  return activities.filter(a=>{
    if(!GROUPED_TYPES.has(a.type))return true;
    if(!a.groups.length)return true;
    if(a.groups.some(g=>courseGroupIds.includes(g.id)))return true;
    const prog=progs.find(p=>a.programmeIds&&a.programmeIds.includes(p.id));
    if(prog&&a.groups.some(g=>g.id===prog.g.id))return true;
    return false;
  });
}

// ---------------- schedule ----------------
function renderSchedule(){
  const box=$("#schedule"),label=$("#weekLabel");
  if(!state.activities.length){
    box.innerHTML='<span class="noweek">No activities in the selected range.</span>';
    label.textContent="";return;
  }
  const monday=state.scheduleWeek;
  const byDay=Array.from({length:7},()=>({})),seen=new Set();
  const irng=groupFiltered(state.activities).filter(a=>{
    const d=dayStart(new Date(a.start.y,a.start.m-1,a.start.d));
    return d>=monday&&d<mondayPlus7(monday);
  });
  for(const a of irng){
    const sd=dayStart(new Date(a.start.y,a.start.m-1,a.start.d));
    const gname=a.groups.map(g=>g.name).join(",");
    const key=fmtShort(sd)+"|"+a.type+"|"+a.courses+"|"+gname;
    if(seen.has(key))continue;seen.add(key);
    const day=(sd-monday)/86400000;
    const sMin=a.start.H*60+a.start.M, eMin=a.end.H*60+a.end.M;
    for(const sh of SLOTS){
      const s2=sh*60, e2=(sh+2)*60;
      if(sMin<e2 && eMin>s2){
        (byDay[day][sh]=byDay[day][sh]||[]).push(a);
      }
    }
  }
  let head="<table><thead><tr><th class='time'>Time</th>";
  for(let d=0;d<7;d++){const dt=new Date(monday);dt.setDate(dt.getDate()+d);
    head+=`<th>${DAYS[d]}<br>${dt.getDate()} ${MONTHS[dt.getMonth()]}</th>`}
  head+="</tr></thead><tbody>";
  let rows="";
  for(const sh of SLOTS){
    let row=`<tr><td class="time">${sh}:00 &ndash; ${sh+2}:00</td>`;
    for(let d=0;d<7;d++){
      const arr=byDay[d][sh]||[];
      let cells="";
      for(const a of arr){
        const gname=a.groups.map(g=>g.name).join(", ");
        const loc=(a.rooms||[]).map(r=>r.map?`<a class="loc" href="${esc(r.map)}" target="_blank" rel="noopener">${esc(r.code||r.name||"room")}</a>`:`<span class="loc">${esc(r.code||r.name||"room")}</span>`).join(" &middot; ");
        cells+=`<div class="slot"><b>${esc(a.type||"(activity)")}</b><span class="cm">${pad(a.start.H)}:${pad(a.start.M)}-${pad(a.end.H)}:${pad(a.end.M)}</span>${loc?`<div>${loc}</div>`:""}${gname?`<span class="grp">${esc(gname)}</span>`:""}${a.courses?`<div class="cm">${esc(a.courses)}</div>`:""}${a.comment?`<div class="cm">${esc(a.comment)}</div>`:""}</div>`;
      }
      row+=`<td>${cells}</td>`;
    }
    rows+=row+"</tr>";
  }
  box.innerHTML=head+rows+"</tbody></table>";
  const grp=state.pairs.some(p=>p.g&&p.g.id)||state.programmes.some(p=>p.g&&p.g.id);
  label.textContent=`Week of ${fmtShort(monday)}${grp?" (your groups only)":""}`;
}

async function doGenerate(){
  const courses=state.pairs.filter(p=>p.c&&p.c.code);
  if(!courses.length&&!state.programmes.length){alert("Pick at least one course or programme first.");return}
  const g=$("#btnGenerate");g.disabled=true;g.textContent="Generating...";
  try{
    const payload={
      programmeIds:state.programmes.filter(p=>p.id).map(p=>p.id),
      courseCodes:courses.map(p=>p.c.code),
      groupIds:state.pairs.filter(p=>p.g&&p.g.id).map(p=>p.g.id),
    };
    const r=await API.generate(payload);
    state.activities=r.activities;
    if(state.scheduleWeek===null)state.scheduleWeek=mondayOf(new Date());
    renderSchedule();
    const kept=groupFiltered(r.activities);
    $("#status").textContent=`${r.activities.length} activities (${kept.length} for your groups)`;
  }catch(e){$("#schedule").innerHTML=`<span class="err">Generate failed: ${esc(e.message)}</span>`}
  finally{g.disabled=false;g.textContent="Generate schedule"}
}

// ---------------- events ----------------
$("#btnAddCourse").onclick=addCourse;
$("#btnAddProg").onclick=addProg;
$("#btnClearAll").onclick=clearAll;
$("#btnSave").onclick=()=>saveCurrent(false);
$("#btnSaveAs").onclick=()=>{state.currentFilterId=null;saveCurrent(true)};
$("#btnGenerate").onclick=doGenerate;
$("#btnPrev").onclick=()=>{state.scheduleWeek.setDate(state.scheduleWeek.getDate()-7);renderSchedule()};
$("#btnNext").onclick=()=>{state.scheduleWeek.setDate(state.scheduleWeek.getDate()+7);renderSchedule()};
$("#btnToday").onclick=()=>{state.scheduleWeek=mondayOf(new Date());renderSchedule()};
renderFilters();renderPairs();renderProgs();
</script>
</body>
</html>
"""


# ---------------------------------------------------------------------------
# WSGI application (for PythonAnywhere / any WSGI host)
# ---------------------------------------------------------------------------

def _read_body(environ):
    length = int(environ.get("CONTENT_LENGTH") or 0)
    if length:
        raw = environ["wsgi.input"].read(length)
    else:
        raw = b"{}"
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        raise ValueError("Invalid JSON")


def _json_response(start_response, obj, status="200 OK"):
    body = json.dumps(obj).encode("utf-8")
    start_response(
        status,
        [
            ("Content-Type", "application/json; charset=utf-8"),
            ("Content-Length", str(len(body))),
        ],
    )
    return [body]


def _html_response(start_response, body):
    start_response(
        "200 OK",
        [
            ("Content-Type", "text/html; charset=utf-8"),
            ("Content-Length", str(len(body))),
        ],
    )
    return [body]


def application(environ, start_response):
    path = environ.get("PATH_INFO", "")
    method = environ.get("REQUEST_METHOD", "GET")

    if method == "GET" and path in ("/", "/index.html"):
        return _html_response(start_response, PAGE.encode("utf-8"))

    if method == "POST":
        try:
            payload = _read_body(environ)
            if path == "/api/search":
                items = search(payload.get("kind", ""), payload.get("term", ""))
                return _json_response(start_response, {"items": items})
            if path == "/api/course-groups":
                groups = course_groups(payload.get("courseCodes", []))
                return _json_response(start_response, {"groups": groups})
            if path == "/api/programme-groups":
                groups = programme_groups(payload.get("programmeIds", []))
                return _json_response(start_response, {"groups": groups})
            if path == "/api/generate":
                programme_ids = list(payload.get("programmeIds", []))
                course_codes = list(payload.get("courseCodes", []))
                activities = generate_schedule(programme_ids, course_codes)
                return _json_response(start_response, {"activities": activities})
        except ValueError as e:
            return _json_response(start_response, {"error": str(e)}, "400 Bad Request")
        except Exception as e:  # noqa: BLE001
            return _json_response(start_response, {"error": str(e)}, "500 Internal Server Error")

    return _json_response(start_response, {"error": "Not found"}, "404 Not Found")


if __name__ == "__main__":
    from wsgiref.simple_server import make_server

    server = make_server("0.0.0.0", PORT, application)
    print(f"RUG schedule UI running at http://127.0.0.1:{PORT}")
    print("Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")