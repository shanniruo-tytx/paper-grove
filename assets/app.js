/* 个人知识库 / 文献管理平台 — 前端逻辑 */
var STATE = { entries: [], categories: [], preview: null, colw: null, expanded: {}, page: 1, pageSize: 10, _full: [] };
var BACKEND = false;
var mini = null;
var hasMini = false;
var view = "library";
var sel = { cat: null, tag: null, type: "__ALL__", q: "", year: null };
var sort = { key: "created", dir: "desc" };
var KIND_LABEL = { paper: "论文", analysis: "拆解", note: "笔记", resource: "知识资料" };

function esc(s){ return (s==null?"":String(s)).replace(/[&<>"]/g,function(c){return {"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c];}); }
function uniq(a){ return a.filter(function(v,i){return a.indexOf(v)===i;}); }
function papers(){ return STATE.entries.filter(function(e){return e.kind==="paper";}); }
function resources(){ return STATE.entries.filter(function(e){return e.kind==="resource";}); }
function analyses(){ return STATE.entries.filter(function(e){return e.kind==="analysis";}); }
function notes(){ return STATE.entries.filter(function(e){return e.kind==="note";}); }
function topEntries(){ return STATE.entries.filter(function(e){return e.kind==="paper"||e.kind==="resource";}); }
function bySlug(s){ for(var i=0;i<STATE.entries.length;i++){ if(STATE.entries[i].slug===s) return STATE.entries[i]; } return null; }
function normTags(t){ if(Array.isArray(t)) return t; if(typeof t==="string") return t.split(",").map(function(s){return s.trim();}).filter(Boolean); return []; }
function attachmentsOf(s){ return STATE.entries.filter(function(e){return e.parent_paper===s;}); }
function catMap(){ var m={}; STATE.categories.forEach(function(c){m[c.id]=c;}); return m; }
function isAncestor(descId, ancId){
  var m=catMap(); var cur=descId; var g=0;
  while(cur && g<12){ if(cur===ancId) return true; cur = m[cur]?m[cur].parent:null; g++; }
  return false;
}
function catPaperCount(id){ return topEntries().filter(function(e){return isAncestor(e.category, id);}).length; }
function catPath(id){
  var m=catMap(); if(m[id]){ var ch=[]; var cur=m[id]; var g=0;
    while(cur && g<12){ ch.unshift(cur.name); cur=m[cur.parent]||null; g++; } return ch.join(" / "); }
  return id;
}

async function loadData(){
  try{
    var r = await fetch("/api/state");
    if(r.ok){ var d = await r.json(); STATE.entries = d.entries||[]; STATE.categories = d.categories||[]; STATE.version = d.version; BACKEND = true; }
    else throw 0;
  }catch(e){
    try{ var r2 = await fetch("index.json"); var d2 = await r2.json(); STATE.entries = d2.entries||[]; STATE.categories = d2.categories||[]; STATE.version = d2.version; BACKEND=false; }
    catch(e2){ document.getElementById("main").innerHTML='<p class="placeholder">加载数据失败：请通过本地/云端 http 服务访问（不要用 file:// 直接打开）。</p>'; return; }
  }
  if(!STATE.colw) STATE.colw = JSON.parse(localStorage.getItem("kb_colw")||"null");
  // 统一规整：部分旧条目 frontmatter 里 tags 是逗号字符串而非列表，下游 .map/.join 会崩，这里一次性归一化为数组
  STATE.entries.forEach(function(e){ e.tags = normTags(e.tags); });
  if (typeof MiniSearch !== "undefined") {
    mini = new MiniSearch({ fields:["title","text","tags","journal","catName","summary","一句话概括"],
      storeFields:["title","type","kind","category","catName","catPath","tags","date","source","journal","summary","一句话概括","path","text","html","parent_paper"] });
    mini.addAll(STATE.entries);
    hasMini = true;
  } else { hasMini = false; }
  applySavedWidths();
  renderAll();
  initGutters();
}

function applySavedWidths(){
  // 校验并清理被污染的存储值，避免侧栏塌缩成一个字
  var sw = parseFloat(localStorage.getItem("kb_side_w"));
  var pw = parseFloat(localStorage.getItem("kb_prev_w"));
  if(sw && isFinite(sw) && sw>=140 && sw<=440){ document.documentElement.style.setProperty("--side-w", sw+"px"); }
  else { localStorage.removeItem("kb_side_w"); } // 无效则丢弃，回退到 CSS 默认(210px)
  if(pw && isFinite(pw) && pw>=300 && pw<=Math.max(300, window.innerWidth*0.82)){ document.documentElement.style.setProperty("--prev-w", pw+"px"); }
  else { localStorage.removeItem("kb_prev_w"); }
}

function applyFilter(list){
  return list.filter(function(e){
    if(sel.type!=="__ALL__" && e.type!==sel.type) return false;
    if(sel.cat && !(e.kind==="paper" && isAncestor(e.category, sel.cat))) return false;
    if(sel.tag && !(e.tags||[]).includes(sel.tag)) return false;
    if(sel.year && (e.date||"").slice(0,4)!==sel.year) return false;
    return true;
  });
}
function haystack(e){
  return (e.title+" "+(e.text||"")+" "+normTags(e.tags).join(" ")+" "+(e.journal||"")+" "+(e.summary||"")+" "+(e.catName||"")+" "+(e.catPath||"")).toLowerCase();
}
function searchList(list){
  if(!sel.q.trim()) return list;
  if(hasMini){
    var ids = mini.search(sel.q.trim(),{prefix:true,fuzzy:0.2,combineWith:"AND"}).map(function(r){return r.id;});
    return list.filter(function(e){ return ids.indexOf(e.slug)>=0 || ids.indexOf(e.title)>=0; });
  }
  var toks = sel.q.trim().toLowerCase().split(/\s+/);
  return list.filter(function(e){ var h=haystack(e); return toks.every(function(t){ return h.indexOf(t)>=0; }); });
}
function retrieve(q, n){
  if(hasMini) return mini.search(q,{prefix:true,fuzzy:0.2,combineWith:"AND"}).slice(0,n);
  var toks=q.toLowerCase().split(/\s+/);
  return STATE.entries.filter(function(e){ var h=haystack(e); return toks.every(function(t){ return h.indexOf(t)>=0; }); }).slice(0,n);
}

function renderAll(){
  renderBeacon();
  renderSidebar();
  render();
}
function renderBeacon(){
  var el = document.getElementById("beacon");
  if(!el) return;
  el.className = "beacon " + (BACKEND?"on":"off");
  el.textContent = BACKEND ? "本地后端已连接" : "只读模式（运行 server.py 启用管理）";
}

function renderSidebar(){
  var h = "";
  h += '<h3>文献</h3><ul class="nav">';
  h += navItem("__ALL__", "全部文献 ("+papers().length+")", !sel.cat && sel.type==="__ALL__" && !sel.year && view!=="knowledge");
  h += navItem("resource", "知识资料 ("+resources().length+")", view==="knowledge" && !sel.cat);
  h += '</ul>';
  h += '<h3>分类</h3>';
  h += treeHtml(STATE.categories.filter(function(c){return !c.parent;}), 0);
  var yrs = {}; topEntries().forEach(function(e){ var y=(e.date||"未知").slice(0,4); yrs[y]=(yrs[y]||0)+1; });
  h += '<h3>按年份</h3><ul class="nav">';
  Object.keys(yrs).sort().reverse().forEach(function(y){
    h += '<li class="'+(sel.year===y?"on":"")+'" onclick="setYear(\''+esc(y)+'\')"><span>'+esc(y||"未知")+'</span><span class="c">'+yrs[y]+'</span></li>';
  });
  h += "</ul>";
  document.getElementById("sidebar").innerHTML = h;
}
function navItem(key, label, on){
  var act = key==="resource" ? "setType('resource')" : "setAll()";
  return '<li class="'+(on?"on":"")+'" onclick="'+act+'"><span>'+label+'</span></li>';
}
function treeHtml(nodes, depth){
  var m=catMap();
  var html = '<ul class="'+(depth===0?"nav":"tree")+'">';
  nodes.forEach(function(n){
    var kids = STATE.categories.filter(function(c){return c.parent===n.id;});
    var hasKids = kids.length>0;
    var collapsed = !!catCollapsed[n.id];
    var cnt = catPaperCount(n.id);
    var on = sel.cat===n.id;
    html += '<li class="tnode'+(on?" on":"")+'" onclick="setCat(\''+esc(n.id)+'\')" data-id="'+esc(n.id)+'" ondragover="onDropOver(event,this)" ondragleave="onDropLeave(this)" ondrop="onDrop(event,\''+esc(n.id)+'\')">';
    if(hasKids){
      html += '<span class="tw'+(collapsed?'':' exp')+'" title="'+(collapsed?'展开':'折叠')+'" onclick="event.stopPropagation();toggleCat(\''+esc(n.id)+'\')"></span>';
    } else {
      html += '<span class="tw leaf"></span>';
    }
    var pad = "\u00A0\u00A0".repeat(depth);  // 每低一级 2 个不换行空格缩进
    html += '<span class="nm" title="'+esc(n.name)+'">'+esc(pad + n.name)+'</span>';
    if(BACKEND){
      html += '<span class="acts">'
        + '<button class="btn sm ghost" onclick="event.stopPropagation();addChild(\''+esc(n.id)+'\')">+子</button>'
        + '<button class="btn sm ghost" onclick="event.stopPropagation();editCat(\''+esc(n.id)+'\')">编辑</button>'
        + (n.id!=="uncat"?'<button class="btn sm danger" onclick="event.stopPropagation();deleteCat(\''+esc(n.id)+'\')">删</button>':'')
        + '</span>';
    }
    html += '<span class="c">'+cnt+'</span></li>';
    if(hasKids && !collapsed){
      html += treeHtml(kids, depth+1);
    }
  });
  html += "</ul>";
  return html;
}
var catCollapsed = {};
function toggleCat(id){
  catCollapsed[id] = !catCollapsed[id];
  renderAll();
}

function setAll(){ sel.cat=null; sel.type="__ALL__"; sel.year=null; sel.tag=null; STATE.page=1; switchTab("library"); }
function setType(t){ sel.type=t; view=(t==="resource"?"knowledge":"library"); STATE.page=1; renderAll(); }
function setCat(id){ sel.cat = id||null; if(view==="knowledge") view="library"; STATE.page=1; renderAll(); }
function setYear(y){ sel.year = y||null; STATE.page=1; renderAll(); }
function setFTag(t){ sel.tag = t||null; STATE.page=1; renderAll(); }
// 标签 chip 点击：切换（再点一次同一标签即取消），且不切换视图
function setTag(t){ if(!t || t===sel.tag){ sel.tag=null; } else { sel.tag=t; } STATE.page=1; renderAll(); }
function doSearch(v){ sel.q=v; STATE.page=1; render(); }
function clearFilters(){ sel.cat=null; sel.tag=null; sel.type="__ALL__"; sel.year=null; sel.q=""; STATE.page=1; renderAll(); }

function switchTab(v){
  view=v;
  document.querySelectorAll(".tabs button").forEach(function(b){ b.classList.toggle("on", b.dataset.v===v); });
  render();
}

function filterActive(){
  return !!(sel.cat || sel.tag || (sel.type && sel.type!=="__ALL__") || sel.year || (sel.q&&sel.q.trim()));
}
function allTagsCount(){
  var tc={};
  STATE.entries.forEach(function(e){ (e.tags||[]).forEach(function(t){ tc[t]=(tc[t]||0)+1; }); });
  return tc;
}
// 文献库 / 知识资料 / 时间线 顶部的筛选工具条：类型 / 分类 / 年份 / 标签 + 清除筛选
function renderFilterBar(){
  function catOpts(sel0){
    var out='<option value="">全部分类</option>';
    function walk(nodes, d){
      nodes.forEach(function(n){
        var kids = STATE.categories.filter(function(c){return c.parent===n.id;});
        var pre = "  ".repeat(d);
        out += '<option value="'+esc(n.id)+'"'+(sel0===n.id?" selected":"")+'>'+esc(pre+n.name)+'</option>';
        if(kids.length) walk(kids, d+1);
      });
    }
    walk(STATE.categories.filter(function(c){return !c.parent;}),0);
    return out;
  }
  var tc = allTagsCount();
  var tags = Object.keys(tc).sort(function(a,b){return tc[b]-tc[a];});
  var tagOpts = '<option value="">全部标签</option>' + tags.map(function(t){ return '<option value="'+esc(t)+'"'+(sel.tag===t?" selected":"")+'>'+esc(t)+' ('+tc[t]+')</option>'; }).join("");
  var yrs={}; topEntries().forEach(function(e){ var y=(e.date||"未知").slice(0,4); yrs[y]=(yrs[y]||0)+1; });
  var yearOpts='<option value="">全部年份</option>'+Object.keys(yrs).sort().reverse().map(function(y){return '<option value="'+esc(y)+'"'+(sel.year===y?" selected":"")+'>'+esc(y||"未知")+' ('+yrs[y]+')</option>';}).join("");
  var typeVal = (view==="knowledge")?"resource":(sel.type==="paper"?"paper":"__ALL__");
  var typeOpts='<option value="__ALL__"'+(typeVal==="__ALL__"?" selected":"")+'>全部类型</option>'
    +'<option value="paper"'+(typeVal==="paper"?" selected":"")+'>论文</option>'
    +'<option value="resource"'+(typeVal==="resource"?" selected":"")+'>知识资料</option>';
  var h='<div class="filters">'
    +'<label class="fl">类型<select onchange="setType(this.value)">'+typeOpts+'</select></label>'
    +'<label class="fl">分类<select onchange="setCat(this.value)">'+catOpts(sel.cat)+'</select></label>'
    +'<label class="fl">年份<select onchange="setYear(this.value)">'+yearOpts+'</select></label>'
    +'<label class="fl">标签<select onchange="setFTag(this.value)">'+tagOpts+'</select></label>'
    + (filterActive()?'<button class="btn sm ghost" onclick="clearFilters()">✕ 清除筛选</button>':'')
    +'</div>';
  if(filterActive()){
    var chips='<div class="factive">';
    if(sel.type && sel.type!=="__ALL__") chips+='<span class="chip on" onclick="setType(\'__ALL__\')">类型：'+(sel.type==="resource"?"知识资料":"论文")+' ✕</span>';
    if(sel.cat) chips+='<span class="chip on" onclick="setCat(\'\')">分类：'+esc((catMap()[sel.cat]||{}).name||sel.cat)+' ✕</span>';
    if(sel.year) chips+='<span class="chip on" onclick="setYear(\'\')">年份：'+esc(sel.year)+' ✕</span>';
    if(sel.tag) chips+='<span class="chip on" onclick="setTag(\'\')">标签：'+esc(sel.tag)+' ✕</span>';
    if(sel.q && sel.q.trim()) chips+='<span class="chip on" onclick="doSearch(\'\');var s=document.getElementById(\'search\');if(s)s.value=\'\'">搜索：'+esc(sel.q.trim())+' ✕</span>';
    chips+='</div>';
    h+=chips;
  }
  return h;
}
function render(){
  var main = document.getElementById("main");
  if(view==="manage"){ main.innerHTML = renderManage(); bindManage(); return; }
  if(view==="stats"){ main.innerHTML = renderStats(); return; }
  if(view==="export"){ main.innerHTML = renderExport(); return; }
  if(view==="ai"){ main.innerHTML = renderAI(); return; }
  if(view==="skills"){ main.innerHTML = renderSkills(); return; }
  var scope = (view==="knowledge") ? resources() : papers();
  var list = applyFilter(scope);
  list = searchList(list);
  list = sortList(list);          // 先按当前排序规则排序，再分页（否则排序仅作用于单页内）
  STATE._full = list;
  var paged = paginate(list);
  var h = '<div class="bar"><input id="search" placeholder="全文搜索标题 / 正文 / 标签 / 期刊 / 分类…" value="'+esc(sel.q)+'" oninput="doSearch(this.value)"/>'
    + '<span class="cnt">'+list.length+' 条</span>'
    + '<button class="btn sm ghost" onclick="refreshData(this)" title="刷新数据：读取 AI 新导入的文献，无需刷新整页">⟳ 刷新</button>'
    + '<button class="btn sm primary" onclick="newEntry(\'paper\')">+ 新建论文</button>'
    + '<button class="btn sm ghost" onclick="newEntry(\'note\')">+ 新建笔记</button></div>';
  if(view==="library"||view==="knowledge"||view==="timeline"){
    h += renderFilterBar();
  }
  if(view==="timeline"){
    var g={}; list.forEach(function(e){ var y=(e.date||"未知").slice(0,7); (g[y]=g[y]||[]).push(e); });
    Object.keys(g).sort().reverse().forEach(function(y){ h+='<h2 class="tl">'+esc(y)+'</h2>'+g[y].map(card).join(""); });
  } else if(view==="tags"){
    var tc={}; topEntries().forEach(function(e){ (e.tags||[]).forEach(function(t){tc[t]=(tc[t]||0)+1;}); });
    var tags=Object.keys(tc).sort(function(a,b){return tc[b]-tc[a];});
    h += '<div class="ctags" style="margin-bottom:12px">'+tags.map(function(t){return '<span class="chip" onclick="setTag(\''+esc(t)+'\')">'+esc(t)+' ('+tc[t]+')</span>';}).join("")+'</div>';
    if(sel.tag) h += '<h2>标签：'+esc(sel.tag)+'</h2>'+paged.map(card).join("");
  } else if(view==="library"){
    h += libTable(paged);
  } else {
    h += paged.map(card).join("");
  }
  // 分页控件（timeline 按时间分组不分页；其余列表/表格视图均分页）
  if(view!=="timeline"){
    h += renderPager(list.length);
  }
  main.innerHTML = h;
  if(STATE.preview) renderPreview();
}

function card(e){
  var badge = '<span class="badge '+e.kind+'">'+KIND_LABEL[e.kind]+'</span>';
  var att = attachmentsOf(e.slug).length;
  return '<div class="card'+(e.slug===STATE.preview?" active":"")+'" onclick="openPreview(\''+esc(e.slug)+'\')">'
    + '<div class="ct">'+esc(e.title)+badge+(att?' <span class="atc">📎'+att+'</span>':'')+'</div>'
    + (e["一句话概括"]?'<div class="cl"><span class="cl-l">一句话概括</span>'+esc(e["一句话概括"])+'</div>':'')
    + '<div class="cm">'+esc(e.kind==="paper"?(e.catPath||e.category):("知识资料 · "+(e.doc_type||"资料")))+' &middot; '+esc(e.journal||"")+' &middot; '+esc(e.created||"")+'</div>'
    + (e.tags&&e.tags.length?'<div class="ctags">'+e.tags.map(function(t){return '<span class="chip" onclick="event.stopPropagation();setTag(\''+esc(t)+'\')">'+esc(t)+'</span>';}).join("")+'</div>':'')
    + (e.summary?'<div class="cs">'+esc(e.summary)+'</div>':'')
    + '</div>';
}

function sortArrow(key){ if(sort.key!==key) return ""; return '<span class="ar">'+(sort.dir==="asc"?"▲":"▼")+'</span>'; }
function sortList(list){
  var dir = sort.dir, key = sort.key;
  var arr = list.slice().sort(function(a,b){
    var va=(a[key]||"").toString().toLowerCase(), vb=(b[key]||"").toString().toLowerCase();
    if(va<vb) return dir==="asc"?-1:1;
    if(va>vb) return dir==="asc"?1:-1;
    return 0;
  });
  return arr;
}
var COLDEF = {title:"26%",catPath:"12%",journal:"12%",created:"9%",date:"9%",pdf:"9%",source:"9%",kind:"6%",tags:"8%",ops:"96px"};
function colDef(k){ return COLDEF[k] || "auto"; }
function colW(k){
  if(STATE.colw && STATE.colw[k]) return STATE.colw[k];
  return colDef(k);
}
function libTable(list){
  var th = function(k,label,sortable){ return '<th data-k="'+k+'" style="width:'+colW(k)+'"'+(sortable?' onclick="sortBy(\''+k+'\')"':'')+'>'+label+sortArrow(k)+'<div class="rs" onmousedown="colResize(event,this)" ondblclick="colReset(event,this)" title="拖动调宽 · 双击恢复默认"></div></th>'; };
  var pdfCell = function(e){ return (e.pdf && e.pdf!=="无") ? '<a class="lnk" href="'+esc(e.pdf)+'" target="_blank" rel="noopener">'+esc(e.pdf)+'</a>' : "无"; };
  var srcCell = function(e){ return (e.source) ? '<a class="lnk" href="'+esc(e.source)+'" target="_blank" rel="noopener" title="'+esc(e.source)+'">'+esc(e.source)+'</a>' : "无"; };
  var rows = list.map(function(e){
    var tags = (e.tags||[]).map(function(t){return '<span class="chip" onclick="event.stopPropagation();setTag(\''+esc(t)+'\')">'+esc(t)+'</span>';}).join(" ");
    var attList = attachmentsOf(e.slug);
    var att = attList.length;
    var open = !!(STATE.expanded||{})[e.slug];
    var main = '<tr class="'+(e.slug===STATE.preview?"sel":"")+'" onclick="openPreview(\''+esc(e.slug)+'\')">'
      + '<td><span class="tw'+(att?(open?' exp':''):' hide')+'" id="tog-'+esc(e.slug)+'" onclick="toggleAtt(\''+esc(e.slug)+'\',event)"></span> <a class="t" onclick="event.stopPropagation();openPreview(\''+esc(e.slug)+'\')">'+esc(e.title)+'</a>'+(att?' <span class="atc">📎'+att+'</span>':'')+(e["一句话概括"]?'<div class="cl">'+esc(e["一句话概括"])+'</div>':'')+'</td>'
      + '<td class="catpath">'+esc(e.catPath||e.category)+'</td>'
      + '<td>'+esc(e.journal||"—")+'</td>'
      + '<td>'+esc(e.created||"—")+'</td>'
      + '<td>'+esc(e.date||"—")+'</td>'
      + '<td class="pdf">'+pdfCell(e)+'</td>'
      + '<td class="src">'+srcCell(e)+'</td>'
      + '<td>'+(e.kind==="resource"?'<span class="badge resource">资料</span>':'<span class="badge paper">论文</span>')+'</td>'
      + '<td class="tags">'+tags+'</td>'
      + '<td class="ops" onclick="event.stopPropagation()">'
      + (e.kind==="paper" ? '<button class="row-btn" title="添加笔记" onclick="addNoteTo(\''+esc(e.slug)+'\')">➕</button>' : '')
      + '<button class="row-btn" title="编辑" onclick="enterEdit(\''+esc(e.slug)+'\')">✏️</button>'
      + '<button class="row-btn danger" title="删除" onclick="deleteEntry(\''+esc(e.slug)+'\',\''+esc(e.title)+'\')">🗑</button>'
      + '</td>'
      + '</tr>';
    var sub = att ? '<tr class="att-row" id="att-'+esc(e.slug)+'" style="display:'+(open?'':'none')+'"><td colspan="10"><div class="att-list">'+attList.map(attItem).join("")+'</div></td></tr>' : "";
    return main + sub;
  }).join("");
  return '<table class="lib"><thead><tr>'
    + th("title","标题",true) + th("catPath","分类",true) + th("journal","期刊",true)
    + th("created","创建时间",true) + th("date","发表时间",true) + th("pdf","本地PDF",false) + th("source","原文地址",false)
    + th("kind","类型",false) + '<th data-k="tags" style="width:'+colW("tags")+'">标签<div class="rs" onmousedown="colResize(event,this)"></div></th>'
    + '<th data-k="ops" style="width:'+colW("ops")+'">操作</th>'
    + '</tr></thead><tbody>'+rows+'</tbody></table>';
}
function attItem(a){
  var badge = a.kind==="analysis" ? '<span class="badge analysis">拆解</span>' : (a.kind==="resource"?'<span class="badge resource">资料</span>':'<span class="badge note">笔记</span>');
  return '<div class="att-item" onclick="event.stopPropagation();openPreview(\''+esc(a.slug)+'\')" title="'+esc(a.title)+'">'
    + badge
    + '<span class="att-t">'+esc(a.title)+'</span>'
    + '<span class="att-btns">'
    + '<button class="row-btn" title="编辑" onclick="event.stopPropagation();enterEdit(\''+esc(a.slug)+'\')">✏️</button>'
    + '<button class="row-btn danger" title="删除" onclick="event.stopPropagation();deleteEntry(\''+esc(a.slug)+'\',\''+esc(a.title)+'\')">🗑</button>'
    + '</span>'
    + '</div>';
}
function toggleAtt(slug, ev){
  ev.stopPropagation();
  STATE.expanded = STATE.expanded || {};
  STATE.expanded[slug] = !STATE.expanded[slug];
  var row = document.getElementById("att-"+slug);
  var tog = document.getElementById("tog-"+slug);
  if(row) row.style.display = STATE.expanded[slug] ? "" : "none";
  if(tog) tog.classList.toggle("exp", STATE.expanded[slug]);
}
function sortBy(k){ if(sort.key===k) sort.dir = sort.dir==="asc"?"desc":"asc"; else { sort.key=k; sort.dir="asc"; } STATE.page=1; render(); }

/* ---------- 分页 ---------- */
function paginate(list){
  var ps = STATE.pageSize || 10;
  var total = Math.max(1, Math.ceil(list.length / ps));
  if(STATE.page > total) STATE.page = total;
  if(STATE.page < 1) STATE.page = 1;
  var start = (STATE.page - 1) * ps;
  return list.slice(start, start + ps);
}
// 构建连续页码窗口（当前页 ±2，并始终含首页/尾页）
function pagerWindow(cur, pages){
  var win = [];
  var lo = Math.max(1, cur - 2);
  var hi = Math.min(pages, cur + 2);
  // 扩展窗口保持至少 5 个，但不超过总页数
  while(hi - lo < 4 && hi < pages){ hi++; }
  while(hi - lo < 4 && lo > 1){ lo--; }
  for(var i=lo; i<=hi; i++) win.push(i);
  return win;
}
function renderPager(total){
  var ps = STATE.pageSize || 10;
  var pages = Math.max(1, Math.ceil(total / ps));
  var cur = STATE.page || 1;
  if(cur > pages) cur = pages;
  if(cur < 1) cur = 1;
  var from = total === 0 ? 0 : (cur - 1) * ps + 1;
  var to = Math.min(total, cur * ps);
  var sizeOpts = [10, 20, 50, 100].map(function(n){
    return '<option value="'+n+'"'+(n===ps?" selected":"")+'>'+n+' 条/页</option>';
  }).join("");
  var win = pagerWindow(cur, pages);
  var pageBtns = "";
  var prevWin = 0;
  win.forEach(function(p){
    if(prevWin && p - prevWin > 1) pageBtns += '<span class="pg-ell">…</span>';
    pageBtns += '<button class="pg-num'+(p===cur?" on":"")+'" onclick="goPage('+p+')">'+p+'</button>';
    prevWin = p;
  });
  var h = '<div class="pager">'
    + '<div class="pg-left">共 '+total+' 条 · 第 '+from+'-'+to+' 条</div>'
    + '<div class="pg-mid">'
    + '<button class="pg-btn" onclick="goPage(1)"'+(cur<=1?" disabled":"")+'>« 首页</button>'
    + '<button class="pg-btn" onclick="goPage('+(cur-1)+')"'+(cur<=1?" disabled":"")+'>‹ 上一页</button>'
    + pageBtns
    + '<button class="pg-btn" onclick="goPage('+(cur+1)+')"'+(cur>=pages?" disabled":"")+'>下一页 ›</button>'
    + '<button class="pg-btn" onclick="goPage('+pages+')"'+(cur>=pages?" disabled":"")+'>尾页 »</button>'
    + '</div>'
    + '<div class="pg-right">'
    + '<label class="pg-sz">每页<select onchange="setPageSize(this.value)">'+sizeOpts+'</select></label>'
    + '<label class="pg-jump">跳至<input id="pgJump" type="number" min="1" max="'+pages+'" value="'+cur+'" onkeydown="if(event.key===\'Enter\')doJump()">页<button class="pg-btn" onclick="doJump()">跳转</button></label>'
    + '</div>'
    + '</div>';
  return h;
}
function goPage(p){ var pages=Math.max(1, Math.ceil((STATE._full||STATE.entries).length/(STATE.pageSize||10))); p=Math.max(1, Math.min(pages, p|0)); STATE.page=p; render(); }
function setPageSize(v){ STATE.pageSize = parseInt(v,10)||10; STATE.page=1; render(); }
function doJump(){ var inp=document.getElementById("pgJump"); if(!inp) return; goPage(parseInt(inp.value,10)||1); }

/* ---------- 右侧预览面板 ---------- */
function openPreview(slug){
  STATE.preview = slug;
  document.getElementById("preview").classList.add("show");
  var gp=document.getElementById("gutterPrev"); if(gp) gp.style.display="block";
  renderPreview();
  document.querySelectorAll(".card").forEach(function(el){ el.classList.remove("active"); });
  document.querySelectorAll("table.lib tr").forEach(function(el){ el.classList.remove("sel"); });
  render();
}
function closePreview(){ STATE.preview=null; document.getElementById("preview").classList.remove("show"); var gp=document.getElementById("gutterPrev"); if(gp) gp.style.display="none"; }
function metaRow(k,v){ return '<div class="m"><b>'+k+'</b><span>'+v+'</span></div>'; }
function previewMeta(e){
  var parts=[];
  // 笔记不展示论文专属元信息（分类/类型/期刊/发表时间/PDF/原文地址/DOI）
  if(e.kind==="paper"){
    parts.push(metaRow("分类", esc(e.catPath||e.category)));
    parts.push(metaRow("类型", KIND_LABEL[e.kind]||e.kind));
    if(e.journal) parts.push(metaRow("期刊", esc(e.journal)));
    if(e.created) parts.push(metaRow("创建时间", esc(e.created)));
    if(e.date) parts.push(metaRow("发表时间", esc(e.date)));
    if(e.authors&&e.authors.length) parts.push(metaRow("作者", esc(e.authors.join(", "))));
    var pdf = e.pdf||"无";
    parts.push(metaRow("本地PDF", pdf==="无"? "无" : '<a href="'+esc(pdf)+'" target="_blank">打开 / 下载</a>'));
    var src=e.source||"";
    parts.push(metaRow("原文地址", src? '<a href="'+esc(src)+'" target="_blank">'+esc(src)+'</a>' : "无"));
    if(e.doi) parts.push(metaRow("DOI", esc(e.doi)));
  }
  // 标签：论文与笔记都展示（笔记不展示论文专属元信息，但标签适用两者）
  if(normTags(e.tags).length){
    parts.push('<div class="m"><b>标签</b><span class="ctags">'+normTags(e.tags).map(function(t){return '<span class="chip" onclick="setTag(\''+esc(t)+'\')">'+esc(t)+'</span>';}).join("")+'</span></div>');
  }
  return parts.join("");
}
function renderPreview(){
  var el=document.getElementById("preview");
  var e = bySlug(STATE.preview);
  if(!e){ el.classList.remove("show"); return; }
  // 内联编辑态：直接在预览窗内编辑，不弹窗
  if(STATE.editing===e.slug && STATE._edit && STATE._edit.slug===e.slug){
    renderPreviewEdit(el, e);
    var tb=document.getElementById("tocBox"); if(tb) tb.remove();
    return;
  }
  var att = (e.kind==="paper") ? attachmentsOf(e.slug) : [];
  var attHtml = att.length ? '<div class="pv-attach"><div class="h">附属内容（拆解 / 笔记）</div>'+att.map(function(a){
    return '<div class="ai-item'+(a.slug===STATE.preview?" on":"")+'" onclick="openPreview(\''+esc(a.slug)+'\')"><span class="badge '+a.kind+'">'+KIND_LABEL[a.kind]+'</span>'+esc(a.title)+'</div>';
  }).join("")+'</div>' : '';
  var summaryHtml = e.summary ? '<div class="pv-summary"><div class="pv-sub">摘要</div><div class="pv-summary-body">'+esc(e.summary)+'</div></div>' : '';
  el.innerHTML = '<div class="pv-head"><div class="pv-title">'+esc(e.title)+'</div><button class="pv-close" onclick="closePreview()">×</button></div>'
    + (e["一句话概括"]?'<div class="pv-oneliner"><span class="pv-ol-l">一句话概括</span>'+esc(e["一句话概括"])+'</div>':'')
    + '<div class="pv-meta">'+previewMeta(e)+'</div>'
    + attHtml
    + summaryHtml
    + '<div class="pv-sub pv-body-label">正文</div>'
    + '<div class="pv-body">'+(e.html||"<p class=\"placeholder\">无正文</p>")+'</div>'
    + '<div class="pv-actions"><button class="btn sm primary" onclick="enterEdit(\''+esc(e.slug)+'\')">编辑</button>'
    + '<a class="btn sm ghost" href="'+esc(e.path)+'" target="_blank">在新标签打开</a>'
    + (e.kind==="paper"?'<button class="btn sm ghost" onclick="jumpPreviewToFirstAtt(\''+esc(e.slug)+'\')">打开首个附件</button>':'')
    + '<button class="btn sm danger" onclick="deleteEntry(\''+esc(e.slug)+'\',\''+esc(e.title)+'\')">删除</button>'
    + '<button class="btn sm ghost" onclick="closePreview()">关闭</button></div>';
  buildTocBox(e);
}
function jumpPreviewToFirstAtt(slug){ var a=attachmentsOf(slug); if(a.length) openPreview(a[0].slug); }

/* ---------- 编辑条目：富文本编辑器（正文 contenteditable 所见即所得；保存自动转回 MD 源码） ---------- */
async function enterEdit(slug){
  var e = bySlug(slug);
  if(!e) return;
  var meta = {};
  ["journal","date","created","pdf","source","doi","summary","一句话概括","tags","parent_paper","category"].forEach(function(k){ if(e[k]!=null) meta[k]=e[k]; });
  var body = e.text || "";
  if(!body){
    try{
      var r = await fetch("/api/entry/raw?slug="+encodeURIComponent(slug));
      var d = await r.json();
      var fm = parseFrontmatter(d.raw);
      body = fm.body; meta = fm.meta;
      meta.tags = normTags(meta.tags);
    }catch(_){}
  }
  STATE._edit = {slug:slug, title:e.title, body:body, meta:meta};
  STATE.editing = slug;
  STATE.preview = slug;
  document.getElementById("preview").classList.add("show");
  var gp=document.getElementById("gutterPrev"); if(gp) gp.style.display="block";
  renderPreview();
}
function parseFrontmatter(raw){
  if(!raw || !raw.startsWith("---")) return {title:"", meta:{}, body:raw||""};
  var parts = raw.split("---");
  if(parts.length < 3) return {title:"", meta:{}, body:raw};
  var meta = {};
  parts[1].split("\n").forEach(function(line){
    var mm = line.match(/^([A-Za-z\u4e00-\u9fff_\-]+):\s?(.*)$/);
    if(mm) meta[mm[1]] = mm[2].trim();
  });
  return {title:meta.title||"", meta:meta, body:parts.slice(2).join("---").replace(/^\n/,"")};
}
function cancelEdit(){ STATE.editing=null; STATE._edit=null; renderPreview(); }
async function saveInline(slug){
  var e = bySlug(slug);
  if(!e) return;
  var title = document.getElementById("ie-title").value.trim();
  var bodyHtml = document.getElementById("ie-body").innerHTML;
  var body = htmlToMd(bodyHtml);
  var tagsRaw = document.getElementById("ie-tags").value;
  var tags = tagsRaw.split(",").map(function(s){return s.trim();}).filter(Boolean);
  var meta = STATE._edit ? (STATE._edit.meta||{}) : {};
  meta.tags = tags;
  if(e.kind==="paper"){
    meta.journal = document.getElementById("ie-journal").value;
    meta.date = document.getElementById("ie-date").value;
    meta.created = document.getElementById("ie-created").value;
    meta.pdf = document.getElementById("ie-pdf").value;
    meta.source = document.getElementById("ie-source").value;
    meta.doi = document.getElementById("ie-doi").value;
    meta.summary = document.getElementById("ie-summary").value;
    meta["一句话概括"] = document.getElementById("ie-oneliner").value.trim();
    meta.category = document.getElementById("ie-category").value || "uncat";
  } else {
    meta.parent_paper = document.getElementById("ie-parent") ? document.getElementById("ie-parent").value || null : (meta.parent_paper||null);
  }
  if(!title){ var m=document.getElementById("editMsg"); if(m) m.textContent="标题不能为空"; return; }
  var btn = document.querySelector("#preview .btn.primary");
  if(btn) btn.disabled = true;
  try{
    var r = await fetch("/api/entry/update", {method:"POST", headers:{"Content-Type":"application/json"}, body: JSON.stringify({slug:slug, title:title, body:body, meta:meta})});
    var d = await r.json();
    if(d.error){ if(btn) btn.disabled=false; var m=document.getElementById("editMsg"); if(m) m.textContent="保存失败："+d.error; return; }
    Object.assign(STATE, d);
    STATE.editing=null; STATE._edit=null;
    renderAll(); openPreview(slug);
  }catch(err){ if(btn) btn.disabled=false; var m=document.getElementById("editMsg"); if(m) m.textContent="保存出错："+err; }
}

/* ---------- 富文本编辑器工具栏 ---------- */
function execRte(cmd, arg){
  document.getElementById("ie-body").focus();
  if(cmd==="h1"||cmd==="h2"||cmd==="h3"){
    document.execCommand("formatBlock", false, "<"+cmd+">");
  } else if(cmd==="ul"){
    document.execCommand("insertUnorderedList", false, null);
  } else if(cmd==="ol"){
    document.execCommand("insertOrderedList", false, null);
  } else if(cmd==="link"){
    var url = prompt("输入链接地址：", "https://");
    if(url) document.execCommand("createLink", false, url);
  } else if(cmd==="code"){
    var sel = window.getSelection();
    if(sel.rangeCount && !sel.isCollapsed){
      var node = document.createElement("code");
      node.textContent = sel.toString();
      sel.getRangeAt(0).deleteContents();
      sel.getRangeAt(0).insertNode(node);
    } else {
      document.execCommand("insertHTML", false, "<code>code</code>");
    }
  } else if(cmd==="pre"){
    var sel = window.getSelection();
    if(sel.rangeCount && !sel.isCollapsed){
      document.execCommand("insertHTML", false, "<pre><code>"+sel.toString()+"</code></pre>");
    } else {
      document.execCommand("insertHTML", false, "<pre><code>code block</code></pre>");
    }
  } else if(cmd==="quote"){
    document.execCommand("formatBlock", false, "<blockquote>");
  } else {
    document.execCommand(cmd, false, arg||null);
  }
}

/* ---------- HTML → Markdown 转换器（从 contenteditable 的 innerHTML 还原为纯 MD） ---------- */
function htmlToMd(html){
  var div = document.createElement("div");
  div.innerHTML = html;
  // 规范化：把 div/p 里直接包含的裸文本和非块级元素包进 <p>
  wrapInlineText(div);
  return blocksToMd(div).trim().replace(/\n{3,}/g, "\n\n");
}
function wrapInlineText(el){
  var INLINE = {"SPAN":1,"STRONG":1,"B":1,"EM":1,"I":1,"A":1,"CODE":1,"BR":1,"U":1,"S":1,"DEL":1,"MARK":1,"SUB":1,"SUP":1};
  var children = Array.prototype.slice.call(el.childNodes);
  var buf = [], hasBlock = false;
  children.forEach(function(c){
    if(c.nodeType===3){
      var t = c.textContent.replace(/\u00A0/g," ").replace(/\u200B/g,"");
      if(!/^\s*$/.test(t)) buf.push(document.createTextNode(t));
      else buf.push(c.cloneNode());
    } else if(c.nodeType===1){
      if(INLINE[c.tagName]){
        buf.push(c.cloneNode(true));
      } else {
        if(buf.length){ var p=document.createElement("p"); buf.forEach(function(x){p.appendChild(x);}); el.insertBefore(p,c); buf=[]; }
        hasBlock = true;
      }
    }
  });
  if(buf.length && hasBlock){
    var p = document.createElement("p");
    buf.forEach(function(x){p.appendChild(x);});
    el.appendChild(p);
  }
}
function blocksToMd(el){
  var out = [];
  var children = Array.prototype.slice.call(el.childNodes);
  var prevTag = null;
  children.forEach(function(c){
    if(c.nodeType===3){ var t=c.textContent.replace(/\u00A0/g," "); if(t.trim()) out.push(t); return; }
    if(c.nodeType!==1) return;
    var tag = c.tagName.toUpperCase();
    if(tag==="BR"){ out.push(""); return; }
    var inner = inlineToMd(c);
    var innerBlock = (tag==="PRE"||tag==="BLOCKQUOTE") ? blockInnerMd(c) : blocksToMd(c).trim();
    if(tag==="H1") out.push("# "+inner,"");
    else if(tag==="H2") out.push("## "+inner,"");
    else if(tag==="H3") out.push("### "+inner,"");
    else if(tag==="H4") out.push("#### "+inner,"");
    else if(tag==="H5") out.push("##### "+inner,"");
    else if(tag==="H6") out.push("###### "+inner,"");
    else if(tag==="P"||tag==="DIV"){
      var blockContent = blocksToMd(c).trim() || innerBlock || inner;
      if(blockContent) out.push(blockContent,"");
    }
    else if(tag==="UL") out.push(listToMd(c, "-"),"");
    else if(tag==="OL") out.push(listToMd(c, "1."),"");
    else if(tag==="PRE"){ var lang=""; var cc=c.querySelector("code"); var txt=(cc?cc.textContent:c.textContent)||""; if(cc&&cc.className){ var lm=cc.className.match(/language-(\w+)/); if(lm) lang=lm[1]; } out.push("```"+lang+"\n"+txt.trim()+"\n```",""); }
    else if(tag==="BLOCKQUOTE"){
      innerBlock.split("\n").forEach(function(l){ out.push("> "+(l||"")); });
      out.push("");
    }
    else if(tag==="HR") out.push("---","");
    else if(tag==="TABLE") out.push(tableToMd(c),"");
    else if(tag==="IMG"){ var alt=c.getAttribute("alt")||""; var src=c.getAttribute("src")||""; out.push("!["+alt+"]("+src+")",""); }
    else {
      var fallback = blocksToMd(c).trim();
      if(fallback) out.push(fallback,"");
    }
    prevTag = tag;
  });
  // merge consecutive empty strings
  var result = [];
  for(var i=0;i<out.length;i++){
    if(out[i]==="" && i>0 && out[i-1]==="") continue;
    result.push(out[i]);
  }
  return result.join("\n");
}
function inlineToMd(el){
  var out = "";
  var children = Array.prototype.slice.call(el.childNodes);
  children.forEach(function(c){
    if(c.nodeType===3){ out += c.textContent.replace(/\u00A0/g," ").replace(/\u200B/g,""); return; }
    if(c.nodeType!==1) return;
    var tag = c.tagName.toUpperCase();
    var inner = inlineToMd(c);
    if(tag==="STRONG"||tag==="B") out += "**"+inner+"**";
    else if(tag==="EM"||tag==="I") out += "*"+inner+"*";
    else if(tag==="A"){ var href=c.getAttribute("href")||""; out += "["+inner+"]("+href+")"; }
    else if(tag==="CODE") out += "`"+inner+"`";
    else if(tag==="S"||tag==="DEL") out += "~~"+inner+"~~";
    else if(tag==="BR") out += "\n";
    else if(tag==="IMG"){ var alt=c.getAttribute("alt")||""; var src=c.getAttribute("src")||""; out += "!["+alt+"]("+src+")"; }
    else out += inner;
  });
  return out;
}
function blockInnerMd(el){
  var pre = el.querySelector("pre");
  if(pre) return (pre.querySelector("code")||pre).textContent||"";
  return el.textContent||"";
}
function listToMd(el, marker){
  var out = [];
  var items = el.querySelectorAll(":scope > li");
  var idx = 1;
  items.forEach(function(li){
    var m = marker==="1." ? (idx+". ") : "- ";
    var text = "";
    var children = Array.prototype.slice.call(li.childNodes);
    children.forEach(function(c){
      if(c.nodeType===3){ text += c.textContent.replace(/\u00A0/g," ").replace(/\u200B/g,""); return; }
      if(c.nodeType!==1) return;
      var tag = c.tagName.toUpperCase();
      if(tag==="UL"||tag==="OL"){
        text += "\n" + listToMd(c, tag==="OL"?"1.":"-").split("\n").map(function(l){return "  "+l;}).join("\n");
      } else {
        text += inlineToMd(c);
      }
    });
    out.push(m + text.trim());
    idx++;
  });
  return out.join("\n");
}
function tableToMd(table){
  var rows = table.querySelectorAll("tr");
  if(!rows.length) return "";
  var out = [];
  var isHeader = false;
  for(var r=0;r<rows.length;r++){
    var cells = rows[r].querySelectorAll("th,td");
    var row = [];
    cells.forEach(function(c){ row.push(c.textContent.trim().replace(/\|/g,"\\|")); });
    out.push("| "+row.join(" | ")+" |");
    if(r===0 && rows[r].querySelector("th")){
      var sep = row.map(function(){return "---";}).join(" | ");
      out.push("| "+sep+" |");
      isHeader = true;
    }
  }
  return out.join("\n");
}

function renderPreviewEdit(el, e){
  var ed = STATE._edit;
  var isPaper = (e.kind==="paper");
  var metaHtml = "";
  if(isPaper){
    var catOpts = '<option value="uncat">（待归类）</option>';
    function catOptWalk(nodes, depth){
      nodes.forEach(function(c){
        catOpts += '<option value="'+esc(c.id)+'"'+(ed.meta.category===c.id?" selected":"")+'>'+("　".repeat(depth))+esc(c.name)+'</option>';
        var kids = STATE.categories.filter(function(x){return x.parent===c.id;});
        if(kids.length) catOptWalk(kids, depth+1);
      });
    }
    catOptWalk(STATE.categories.filter(function(c){return !c.parent;}), 0);
    metaHtml = '<div class="eflds">'
      + '<label class="efld"><span>所属类别</span><select id="ie-category">'+catOpts+'</select></label>'
      + '<label class="efld"><span>期刊</span><input id="ie-journal" type="text" value="'+esc(ed.meta.journal||"")+'"></label>'
      + '<label class="efld"><span>发表时间</span><input id="ie-date" type="text" value="'+esc(ed.meta.date||"")+'"></label>'
      + '<label class="efld"><span>创建时间</span><input id="ie-created" type="text" value="'+esc(ed.meta.created||"")+'"></label>'
      + '<label class="efld"><span>本地PDF</span><input id="ie-pdf" type="text" value="'+esc(ed.meta.pdf||"")+'"></label>'
      + '<label class="efld"><span>原文地址</span><input id="ie-source" type="text" value="'+esc(ed.meta.source||"")+'"></label>'
      + '<label class="efld"><span>DOI</span><input id="ie-doi" type="text" value="'+esc(ed.meta.doi||"")+'"></label>'
      + '</div>'
      + '<label class="efld blk"><span>摘要（独立于正文）</span><textarea id="ie-summary" class="edit-raw" spellcheck="false">'+esc(ed.meta.summary||"")+'</textarea></label>'
      + '<label class="efld blk"><span>一句话概括（尽可能短而不省略，概括文章做了一个什么东西）</span><input id="ie-oneliner" type="text" value="'+esc(ed.meta["一句话概括"]||"")+'"></label>';
  }
  var tagVal = normTags(ed.meta.tags).join(", ");
  var ppHtml = "";
  if(!isPaper){
    var ppOpts = '<option value="">（不关联 / 独立笔记）</option>';
    STATE.entries.filter(function(x){return x.kind==="paper";}).forEach(function(p){
      ppOpts += '<option value="'+esc(p.slug)+'"'+(ed.meta.parent_paper===p.slug?" selected":"")+'>'+esc(p.title)+'</option>';
    });
    ppHtml = '<label class="efld blk"><span>关联论文（作为该论文的附属笔记，将在表格中展开显示）</span><select id="ie-parent">'+ppOpts+'</select></label>';
  }
  var bodyHtml = "";
  try { bodyHtml = (typeof marked!=="undefined") ? marked.parse(ed.body||"") : (ed.body||"").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/\n/g,"<br>"); } catch(_){ bodyHtml = esc(ed.body||""); }
  el.innerHTML = '<div class="pv-head"><div class="pv-title"><input id="ie-title" class="ie-title" type="text" value="'+esc(ed.title||"")+'"></div><button class="pv-close" onclick="cancelEdit()">×</button></div>'
    + metaHtml
    + '<label class="efld blk"><span>标签（逗号分隔，可多个）</span><input id="ie-tags" type="text" value="'+esc(tagVal)+'"></label>'
    + ppHtml
    + '<div class="pv-sub pv-body-label">正文</div>'
    + '<div class="rte-toolbar">'
    + '<button class="rte-btn" onclick="execRte(\'bold\')" title="粗体"><b>B</b></button>'
    + '<button class="rte-btn" onclick="execRte(\'italic\')" title="斜体"><i>I</i></button>'
    + '<span class="rte-sep"></span>'
    + '<button class="rte-btn" onclick="execRte(\'h2\')" title="二级标题">H2</button>'
    + '<button class="rte-btn" onclick="execRte(\'h3\')" title="三级标题">H3</button>'
    + '<span class="rte-sep"></span>'
    + '<button class="rte-btn" onclick="execRte(\'ul\')" title="无序列表">•</button>'
    + '<button class="rte-btn" onclick="execRte(\'ol\')" title="有序列表">1.</button>'
    + '<span class="rte-sep"></span>'
    + '<button class="rte-btn" onclick="execRte(\'link\')" title="插入链接">🔗</button>'
    + '<button class="rte-btn" onclick="execRte(\'code\')" title="行内代码">&lt;&gt;</button>'
    + '<button class="rte-btn" onclick="execRte(\'pre\')" title="代码块">▣</button>'
    + '<button class="rte-btn" onclick="execRte(\'quote\')" title="引用">❝</button>'
    + '</div>'
    + '<div id="ie-body" class="rte-body" contenteditable="true" spellcheck="false">'+bodyHtml+'</div>'
    + '<div class="pv-actions"><span id="editMsg" class="edit-msg"></span>'
    + '<button class="btn sm ghost" onclick="cancelEdit()">取消</button>'
    + '<button class="btn sm primary" onclick="saveInline(\''+esc(e.slug)+'\')">保存</button></div>';
}
function buildTocBox(e){
  var prev = document.getElementById("preview");
  var box = document.getElementById("tocBox");
  if(!e.html){ if(box) box.remove(); return; }
  var body = prev.querySelector(".pv-body");
  if(!body) return;
  // 将 ## #0. 原始论文识别与基本信息 区域中的松散键值对转成表格显示
  convertSection0ToTable(body);
  var heads = body.querySelectorAll("h2, h3");
  if(!heads.length){ if(box) box.remove(); return; }
  heads.forEach(function(h, i){ if(!h.id) h.id = "pvh"+i; });
  var items = Array.prototype.map.call(heads, function(h){
    var lvl = h.tagName==="H2" ? "l2" : "l3";
    return '<a class="toc-it '+lvl+'" data-id="'+h.id+'" onclick="tocJump(\''+esc(h.id)+'\')">'+esc(h.textContent)+'</a>';
  }).join("");
  if(!box){
    box = document.createElement("div");
    box.id = "tocBox"; box.className = "toc-box min";
    prev.appendChild(box);
  }
  box.innerHTML = '<div class="toc-bar" onmousedown="tocDrag(event)"><span>目录</span><span class="toc-min">▾</span></div>'
    + '<div class="toc-body" id="tocBody">'+items+'</div>'
    + '<div class="toc-rs" onmousedown="tocResize(event)"></div>';
}
/* 将 ## #0. 原始论文识别与基本信息 后面的松散 <p> 键值对转为表格显示 */
function convertSection0ToTable(body){
  var h2s = body.querySelectorAll("h2");
  var target = null;
  for(var i=0; i<h2s.length; i++){
    if(h2s[i].textContent.indexOf("#0.")===0 || h2s[i].textContent.indexOf("原始论文识别")>=0){
      target = h2s[i]; break;
    }
  }
  if(!target) return;
  // 收集 h2 后面、下一个 h2 之前的 <p> 元素
  var paras = [];
  var el = target.nextElementSibling;
  while(el && el.tagName!=="H2"){
    if(el.tagName==="P") paras.push(el);
    el = el.nextElementSibling;
  }
  if(paras.length < 4) return;
  // 跳过表头行（"项目/内容"、"字段/内容"、"属性/值"等变体）
  var pairs = [];
  var start = 0;
  var h1t = paras[0].textContent.trim();
  var h2t = paras[1].textContent.trim();
  if((h1t==="项目"||h1t==="字段"||h1t==="属性") && (h2t==="内容"||h2t==="值"||h2t==="详情")) start = 2;
  // 取第0个 <p> 的实际文本作为表格左列表头
  var leftHeader = paras[0].textContent.trim() || "项目";
  for(var j=start; j+1<paras.length; j+=2){
    var key = paras[j].textContent.trim();
    var val = paras[j+1].innerHTML;
    if(key && val) pairs.push([key, val]);
  }
  if(!pairs.length) return;
  // 构建表格
  var tbl = '<table class="info-table"><thead><tr><th>'+esc(leftHeader)+'</th><th>内容</th></tr></thead><tbody>';
  for(var k=0; k<pairs.length; k++){
    tbl += '<tr><td>'+esc(pairs[k][0])+'</td><td>'+pairs[k][1]+'</td></tr>';
  }
  tbl += '</tbody></table>';
  // 替换所有 <p> 为表格
  var wrapper = document.createElement("div");
  wrapper.innerHTML = tbl;
  var tableEl = wrapper.firstChild;
  // 先隐藏旧的 <p>，再插入表格
  for(var p=0; p<paras.length; p++){ paras[p].style.display = "none"; }
  target.parentNode.insertBefore(tableEl, paras[0]);
}
function tocJump(id){ var el=document.getElementById(id); if(el) el.scrollIntoView({behavior:"smooth", block:"start"}); }
function tocDrag(ev){
  ev.preventDefault(); ev.stopPropagation();
  var box=document.getElementById("tocBox"); if(!box) return;
  var sx=ev.clientX, sy=ev.clientY;
  var ox=box.offsetLeft, oy=box.offsetTop;
  var moved=false;
  function mv(e){
    var dx=e.clientX-sx, dy=e.clientY-sy;
    if(Math.abs(dx)>3 || Math.abs(dy)>3) moved=true;
    box.style.left=(ox+dx)+"px";
    box.style.top=(oy+dy)+"px";
    box.style.right="auto";
  }
  function up(){
    document.removeEventListener("mousemove",mv);
    document.removeEventListener("mouseup",up);
    if(!moved) box.classList.toggle("min");
  }
  document.addEventListener("mousemove",mv);
  document.addEventListener("mouseup",up);
}
function tocResize(ev){
  ev.preventDefault(); ev.stopPropagation();
  var box=document.getElementById("tocBox"); if(!box) return;
  var sx=ev.clientX, sy=ev.clientY, sw=box.offsetWidth, sh=box.offsetHeight;
  function mv(e){
    box.style.width = Math.max(170, sw+(e.clientX-sx))+"px";
    box.style.height = Math.max(120, sh+(e.clientY-sy))+"px";
  }
  function up(){ document.removeEventListener("mousemove",mv); document.removeEventListener("mouseup",up); }
  document.addEventListener("mousemove",mv); document.addEventListener("mouseup",up);
}
async function newEntry(kind){
  try{
    var r = await apiPost("/api/entry/create", {kind:kind, title:(kind==="paper"?"未命名论文":"未命名笔记"), body:"", meta:{}});
    Object.assign(STATE, r);
    STATE.editing = r.slug;
    STATE._edit = {slug:r.slug, title:(kind==="paper"?"未命名论文":"未命名笔记"), body:"", meta:{}};
    renderAll(); openPreview(r.slug);
  }catch(e){ openInfoModal("新建失败", e.message); }
}
async function addNoteTo(paperSlug){
  var paper = bySlug(paperSlug);
  if(!paper) return;
  try{
    var r = await apiPost("/api/entry/create", {kind:"note", title:"未命名笔记", body:"", meta:{parent_paper:paperSlug}});
    Object.assign(STATE, r);
    STATE.editing = r.slug;
    STATE._edit = {slug:r.slug, title:"未命名笔记", body:"", meta:{parent_paper:paperSlug}};
    renderAll(); openPreview(r.slug);
  }catch(e){ openInfoModal("新建笔记失败", e.message); }
}
async function deleteEntry(slug, title){
  openConfirmModal({
    title:"删除条目",
    message:"确定要删除「"+title+"」吗？\n此操作会物理删除源文件，不可恢复。",
    danger:true,
    confirmText:"删除",
    onConfirm: async function(){
      var r = await apiPost("/api/entry/delete", {slug:slug});
      if(r.error) throw new Error(r.error);
      Object.assign(STATE, r);
      if(STATE.preview===slug){ STATE.preview=null; }
      if(STATE.editing===slug){ STATE.editing=null; STATE._edit=null; }
      renderAll();
    }
  });
}

/* ---------- 拖拽调节宽度 ---------- */
function initGutters(){
  var side=document.getElementById("gutterSide");
  var prev=document.getElementById("gutterPrev");
  if(side) side.addEventListener("mousedown", function(ev){ startResize(ev,"side"); });
  if(prev) prev.addEventListener("mousedown", function(ev){ startResize(ev,"prev"); });
}
function startResize(ev, which){
  ev.preventDefault();
  var startX=ev.clientX;
  var sb=document.getElementById("sidebar");
  var pv=document.getElementById("preview");
  var sideW=sb.getBoundingClientRect().width;
  var prevW=pv.getBoundingClientRect().width;
  function mm(e){
    var dx=e.clientX-startX;
    if(which==="side"){
      var w=Math.min(440, Math.max(140, sideW+dx));
      document.documentElement.style.setProperty("--side-w", w+"px");
      localStorage.setItem("kb_side_w", w);
    } else {
      var w=Math.min(window.innerWidth*0.82, Math.max(300, prevW-dx));
      document.documentElement.style.setProperty("--prev-w", w+"px");
      localStorage.setItem("kb_prev_w", w);
    }
  }
  function mu(){ document.removeEventListener("mousemove",mm); document.removeEventListener("mouseup",mu); document.body.style.cursor=""; document.body.style.userSelect=""; var g=document.getElementById(which==="side"?"gutterSide":"gutterPrev"); if(g) g.classList.remove("drag"); }
  document.addEventListener("mousemove",mm); document.addEventListener("mouseup",mu);
  document.body.style.cursor="col-resize"; document.body.style.userSelect="none";
  var g=document.getElementById(which==="side"?"gutterSide":"gutterPrev"); if(g) g.classList.add("drag");
}
function colResize(ev, handle){
  ev.preventDefault(); ev.stopPropagation();
  var cell = handle.closest ? handle.closest("th") : handle.parentNode; // .rs 手柄的真实 <th>
  if(!cell) return;
  var k = cell.getAttribute("data-k");
  // 右邻居列：拖动本列右边界时，只和它互换宽度，其它列不动（两列之和恒定）
  var next = cell.nextElementSibling;
  while(next && (next.tagName ? next.tagName.toLowerCase() !== "th" : true)) next = next.nextElementSibling;
  var startX = ev.clientX;
  var startW = cell.getBoundingClientRect().width;
  var nextStartW = next ? next.getBoundingClientRect().width : 0;
  var pair = startW + nextStartW; // 恒定：本列 + 右邻居 的总宽
  var MIN = 60;
  var moved = false;
  // 拖拽引导竖线（贯穿整张表、跟随光标）
  var guide = document.getElementById("col-guide");
  if(!guide){ guide = document.createElement("div"); guide.id = "col-guide"; document.body.appendChild(guide); }
  function apply(w, nw){
    cell.style.width = w + "px";
    if(next) next.style.width = nw + "px";
    if(!STATE.colw) STATE.colw = {};
    if(k) STATE.colw[k] = w + "px";
    if(next){ var nk = next.getAttribute("data-k"); if(nk) STATE.colw[nk] = nw + "px"; }
  }
  function mm(e){
    var dx = e.clientX - startX;
    if(Math.abs(dx) > 3) moved = true;
    var w = startW + dx;
    var nw = next ? pair - w : w; // 没有右邻居时单独调整（理论上不会发生，ops 后无列）
    if(w < MIN){ w = MIN; nw = next ? pair - w : w; }
    if(next && nw < MIN){ nw = MIN; w = pair - nw; }
    if(w < MIN) w = MIN;
    if(next && nw < MIN) nw = MIN;
    apply(w, nw);
    var tbl = cell.closest("table");
    if(tbl){
      var r = tbl.getBoundingClientRect();
      guide.style.left = e.clientX + "px";
      guide.style.top = r.top + "px";
      guide.style.height = r.height + "px";
      guide.style.display = "block";
    }
  }
  function mu(){
    document.removeEventListener("mousemove", mm);
    document.removeEventListener("mouseup", mu);
    document.body.style.cursor = "";
    document.body.classList.remove("col-resizing");
    if(handle) handle.classList.remove("drag");
    if(guide) guide.style.display = "none";
    if(STATE.colw) localStorage.setItem("kb_colw", JSON.stringify(STATE.colw)); // 仅松手时落盘
    // 关键：拖拽结束后浏览器会在手柄上补发一次 click 并冒泡到 <th> 的排序处理器，
    // 表现为「调完宽度顺手排了一次序」。在捕获阶段拦掉这一次 click 即可。
    if(moved){
      var cleanup = function(){ document.removeEventListener("click", supp, true); clearTimeout(tm); };
      var supp = function(ce){ ce.stopPropagation(); ce.preventDefault(); cleanup(); };
      var tm = setTimeout(cleanup, 0); // 兜底：本次交互若没产生 click，下一拍也解绑
      document.addEventListener("click", supp, true);
    }
  }
  document.addEventListener("mousemove", mm);
  document.addEventListener("mouseup", mu);
  document.body.style.cursor = "col-resize";
  document.body.classList.add("col-resizing");
  if(handle) handle.classList.add("drag");
}

/* 双击分隔条：本列 + 右邻居 复位为默认宽度 */
function colReset(ev, handle){
  ev.preventDefault(); ev.stopPropagation();
  var cell = handle.closest ? handle.closest("th") : handle.parentNode;
  if(!cell) return;
  var next = cell.nextElementSibling;
  while(next && (next.tagName ? next.tagName.toLowerCase() !== "th" : true)) next = next.nextElementSibling;
  function reset(c){
    if(!c) return;
    var kk = c.getAttribute("data-k");
    if(STATE.colw && STATE.colw[kk]) delete STATE.colw[kk];
    c.style.width = colDef(kk);
  }
  reset(cell); reset(next);
  localStorage.setItem("kb_colw", JSON.stringify(STATE.colw || {}));
}

/* ---------- 分类管理 ---------- */
function renderManage(){
  if(!BACKEND){
    return '<div class="notice">当前为<strong>只读模式</strong>：分类树的增删改、拖拽归档需要运行本地后端 <code>server.py</code>（<code>python server.py</code> 后访问 http://localhost:8766）。静态托管下可浏览但无法持久化修改。</div>'
      + '<div class="manage"><div class="panel"><h2>分类树（只读）</h2>'+treeHtml(STATE.categories.filter(function(c){return !c.parent;}),0)+'</div>'
      + '<div class="panel"><h2>文献（'+papers().length+'）</h2>'+papers().map(function(e){return '<div class="pitem"><div class="pt"><div class="t">'+esc(e.title)+'</div><div class="catpath">'+esc(e.catPath)+'</div></div></div>';}).join("")+'</div></div>';
  }
  var h = '<div class="manage">';
  h += '<div class="panel"><h2>分类树<span class="panel-acts">'
    + '<button class="btn sm" onclick="importRDF()">⬇ 从 Zotero RDF 导入（重建分类树）</button>'
    + '<button class="btn sm ghost" onclick="addTopCat()">+ 新建顶级分类</button>'
    + '</span></h2>';
  h += treeHtml(STATE.categories.filter(function(c){return !c.parent;}),0);
  h += '</div>';
  h += '<div class="panel"><h2>文献归档（'+papers().length+'）</h2>';
  h += '<p class="placeholder" style="padding:6px 0;text-align:left;color:var(--sub)">拖拽文献到左侧分类，或用下拉框改分类。</p>';
  h += '<div class="papers-list">';
  papers().forEach(function(e){
    var opts = STATE.categories.map(function(c){ return '<option value="'+esc(c.id)+'"'+(c.id===e.category?" selected":"")+'>'+esc(catPath(c.id))+'</option>'; }).join("");
    h += '<div class="pitem" draggable="true" ondragstart="onDragStart(event,\''+esc(e.slug)+'\')">'
      + '<div class="pt"><div class="t">'+esc(e.title)+'</div><div class="catpath">现属：'+esc(e.catPath)+'</div></div>'
      + '<select onchange="reassign(\''+esc(e.slug)+'\',this.value)">'+opts+'</select></div>';
  });
  h += '</div></div></div>';
  return h;
}
function bindManage(){}
function onDragStart(e, slug){ e.dataTransfer.setData("text/plain", slug); }
function onDropOver(e, el){ e.preventDefault(); el.classList.add("drop"); }
function onDropLeave(el){ el.classList.remove("drop"); }
function onDrop(e, catId){ e.preventDefault(); var slug=e.dataTransfer.getData("text/plain"); el=document.querySelector('.tnode.drop'); if(el) el.classList.remove("drop"); if(slug) reassign(slug, catId); }

async function apiPost(path, payload){
  var r = await fetch(path, { method:"POST", headers:{"Content-Type":"application/json"}, body: JSON.stringify(payload) });
  if(!r.ok){
    var msg = "api "+r.status;
    try { var j = await r.json(); if(j && j.error) msg = j.error; } catch(_){}
    throw new Error(msg);
  }
  return r.json();
}
async function reload(){ var r = await fetch("/api/state"); STATE = await r.json(); renderAll(); }
// 局部刷新：仅重新拉取文献/分类数据并重渲染，保留当前视图、筛选、排序、分页
async function refreshData(btn){
  if(btn){ btn.disabled = true; btn.innerHTML = "⟳ 刷新中…"; }
  try{
    var r = await fetch("/api/state");
    if(r.ok){ var d = await r.json(); STATE.entries = d.entries||[]; STATE.categories = d.categories||[]; STATE.version = d.version; BACKEND = true; }
    else throw 0;
  }catch(e){
    try{ var r2 = await fetch("index.json?t=" + (+new Date())); var d2 = await r2.json(); STATE.entries = d2.entries||[]; STATE.categories = d2.categories||[]; STATE.version = d2.version; BACKEND = false; }
    catch(e2){ if(btn){ btn.disabled = false; btn.innerHTML = "⟳ 刷新"; } renderBeacon(); return; }
  }
  STATE.entries.forEach(function(en){ en.tags = normTags(en.tags); });
  if(hasMini && typeof MiniSearch !== "undefined"){
    mini = new MiniSearch({ fields:["title","text","tags","journal","catName","summary","一句话概括"],
      storeFields:["title","type","kind","category","catName","catPath","tags","date","source","journal","summary","一句话概括","path","text","html","parent_paper"] });
    mini.addAll(STATE.entries);
  }
  renderAll();
}
function addTopCat(){ openCatModal("create", null); }
function importRDF(){
  openConfirmModal({
    title:"导入 Zotero RDF",
    message:"从工作目录的 Zotero RDF 重建分类树并导入文献/笔记？\n现有 zotero_* 自动导入条目会被覆盖（你手动写的深度解析与概念卡保留）。",
    confirmText:"导入",
    onConfirm:function(){
      return apiPost("/api/import-rdf", {}).then(function(r){
        openInfoModal("导入完成", "共导入 " + (r.entries?r.entries.length:0) + " 条文献/笔记，分类 " + (r.categories?r.categories.length:0) + " 个。");
        reload();
      });
    }
  });
}
function addChild(id){ openCatModal("create", id); }
function isDescendant(cid, ancestorId){
  var cur = catMap()[cid];
  while(cur && cur.parent){
    if(cur.parent===ancestorId) return true;
    cur = catMap()[cur.parent];
  }
  return false;
}
function openCatModal(mode, id){
  // mode: 'create'（新建，可指定父级 id） | 'update'（编辑已有 id）
  var m = id ? (catMap()[id]||{}) : {};
  var title = mode==="update" ? "编辑分类" : "新建分类";
  var nameVal = mode==="update" ? (m.name||"") : "";
  var parentVal = mode==="update" ? (m.parent||"") : (id||"");
  var opts = '<option value="">（顶级分类 · 无上级）</option>';
  STATE.categories.forEach(function(c){
    if(mode==="update" && c.id===id) return;
    if(mode==="update" && isDescendant(c.id, id)) return;
    opts += '<option value="'+esc(c.id)+'"'+(c.id===parentVal?" selected":"")+'>'+esc(catPath(c.id))+'</option>';
  });
  var html = '<div class="modal-box" style="width:min(520px,94vw)">'
    + '<div class="modal-head"><span>'+title+'</span><button class="modal-x" onclick="closeCat()">×</button></div>'
    + '<div class="modal-body">'
    + '<label class="efld blk"><span>名称</span><input id="cf-name" type="text" value="'+esc(nameVal)+'"></label>'
    + '<label class="efld blk"><span>上级分类（调整层级）</span><select id="cf-parent">'+opts+'</select></label>'
    + (mode==="update"
        ? '<p class="placeholder" style="padding:2px 0 0;color:var(--muted);text-align:left">留空表示设为顶级分类；选择某分类则将其变为该分类的子级。分类树本身可随时调整，仅在你自动解析新文献时不会被 AI 擅自改动。</p>'
        : '<p class="placeholder" style="padding:2px 0 0;color:var(--muted);text-align:left">新建分类将归入下方所选父级（留空则为顶级分类）。保存后可在分类管理页再次编辑调整层级。</p>')
    + '</div>'
    + '<div class="modal-foot"><span id="catMsg" class="edit-msg"></span>'
    + '<button class="btn sm ghost" onclick="closeCat()">取消</button>'
    + '<button class="btn sm primary" onclick="saveCat()">保存</button></div>';
  var modal = document.getElementById("catModal");
  if(!modal){
    modal = document.createElement("div");
    modal.id = "catModal";
    modal.className = "modal";
    modal.onclick = function(ev){ if(ev.target===modal) closeCat(); };
    document.body.appendChild(modal);
  }
  modal.setAttribute("data-mode", mode);
  if(mode==="update") modal.setAttribute("data-id", id); else modal.removeAttribute("data-id");
  modal.innerHTML = html;
  modal.classList.add("show");
  setTimeout(function(){ var n=document.getElementById("cf-name"); if(n){ n.focus(); } }, 30);
}
function editCat(id){ openCatModal("update", id); }
function closeCat(){ var m=document.getElementById("catModal"); if(m) m.classList.remove("show"); }
async function saveCat(){
  var modal = document.getElementById("catModal");
  var mode = modal ? (modal.getAttribute("data-mode")||"create") : "create";
  var id = modal ? modal.getAttribute("data-id") : null;
  var name = (document.getElementById("cf-name").value||"").trim();
  var parent = document.getElementById("cf-parent").value || null;
  if(!name){ document.getElementById("catMsg").textContent="名称不能为空"; return; }
  var btn = document.querySelector("#catModal .btn.primary");
  if(btn) btn.disabled = true;
  try{
    var payload = {name:name, parent:parent};
    if(mode==="update"){ payload.action="update"; payload.id=id; }
    else { payload.action="create"; }
    var r = await apiPost("/api/category", payload);
    STATE = r;
    closeCat();
    renderAll();
  }catch(e){ if(btn) btn.disabled=false; document.getElementById("catMsg").textContent="失败："+e.message; }
}
/* 通用确认框（替代浏览器的 confirm / alert） */
var _confirmCb = null;
function openConfirmModal(opts){
  var html = '<div class="modal-box" style="width:min(460px,94vw)">'
    + '<div class="modal-head"><span>'+esc(opts.title||"确认操作")+'</span><button class="modal-x" onclick="closeConfirm()">×</button></div>'
    + '<div class="modal-body"><p style="margin:0;line-height:1.75;color:#334155;white-space:pre-line">'+esc(opts.message||"")+'</p></div>'
    + '<div class="modal-foot"><span id="confirmMsg" class="edit-msg"></span>'
    + '<button class="btn sm ghost" onclick="closeConfirm()">取消</button>'
    + '<button class="btn sm '+(opts.danger?"danger":"primary")+'" id="confirmOk" onclick="doConfirm()">'+esc(opts.confirmText||"确定")+'</button></div>';
  var modal = document.getElementById("confirmModal");
  if(!modal){
    modal = document.createElement("div");
    modal.id = "confirmModal";
    modal.className = "modal";
    modal.onclick = function(ev){ if(ev.target===modal) closeConfirm(); };
    document.body.appendChild(modal);
  }
  modal.innerHTML = html;
  _confirmCb = opts.onConfirm || null;
  modal.classList.add("show");
}
function closeConfirm(){ var m=document.getElementById("confirmModal"); if(m){ m.classList.remove("show"); _confirmCb=null; } }
function doConfirm(){
  var ok = document.getElementById("confirmOk");
  if(ok) ok.disabled = true;
  var cb = _confirmCb;
  if(!cb){ return closeConfirm(); }
  var res = cb();
  if(res && res.then){
    res.then(function(){ closeConfirm(); }).catch(function(e){
      if(ok) ok.disabled = false;
      var m = document.getElementById("confirmMsg"); if(m) m.textContent = "失败：" + e.message;
    });
  } else { closeConfirm(); }
}
function openInfoModal(title, message){
  var html = '<div class="modal-box" style="width:min(460px,94vw)">'
    + '<div class="modal-head"><span>'+esc(title||"提示")+'</span><button class="modal-x" onclick="closeInfo()">×</button></div>'
    + '<div class="modal-body"><p style="margin:0;line-height:1.75;color:#334155;white-space:pre-line">'+esc(message||"")+'</p></div>'
    + '<div class="modal-foot"><button class="btn sm primary" onclick="closeInfo()">好的</button></div>';
  var modal = document.getElementById("infoModal");
  if(!modal){
    modal = document.createElement("div");
    modal.id = "infoModal";
    modal.className = "modal";
    modal.onclick = function(ev){ if(ev.target===modal) closeInfo(); };
    document.body.appendChild(modal);
  }
  modal.innerHTML = html;
  modal.classList.add("show");
}
function closeInfo(){ var m=document.getElementById("infoModal"); if(m) m.classList.remove("show"); }
function deleteCat(id){
  openConfirmModal({
    title:"删除分类",
    message:"删除该分类？其下文献将移入上级（无上级则归入「待归类」），子分类也会上提。",
    confirmText:"删除",
    danger:true,
    onConfirm:function(){ return apiPost("/api/category",{action:"delete",id:id}).then(reload); }
  });
}
function reassign(slug, catId){ apiPost("/api/entry/category",{slug:slug,category:catId}).then(reload).catch(function(e){ openInfoModal("操作失败", e.message); }); }

/* ---------- 统计 ---------- */
function renderStats(){
  var np = papers().length, nr = resources().length, na = analyses().length, nn = notes().length;
  var byCat = {}; STATE.categories.forEach(function(c){ byCat[c.id] = catPaperCount(c.id); });
  var byYear = {}; topEntries().forEach(function(e){ var y=(e.date||"未知").slice(0,4); byYear[y]=(byYear[y]||0)+1; });
  var byType = { "论文":np, "知识资料":nr, "拆解":na, "笔记":nn };
  var tc={}; topEntries().forEach(function(e){ (e.tags||[]).forEach(function(t){tc[t]=(tc[t]||0)+1;}); });
  var topTags = Object.keys(tc).sort(function(a,b){return tc[b]-tc[a];}).slice(0,12);
  var maxCat = Math.max(1, Math.max.apply(null, STATE.categories.map(function(c){return byCat[c.id];})));
  var maxYear = Math.max(1, Math.max.apply(null, Object.values(byYear)));
  var h = '<div class="stat-grid">'
    + statBox(np,"论文") + statBox(nr,"知识资料") + statBox(na,"拆解") + statBox(nn,"笔记")
    + statBox(STATE.categories.length,"分类数") + '</div>';
  h += '<div class="panel" style="margin-bottom:16px"><h2>按分类（含子分类，论文+资料）</h2>';
  STATE.categories.forEach(function(c){ var v=byCat[c.id]; h += barRow(catPath(c.id), v, maxCat); });
  h += '</div>';
  h += '<div style="display:grid;grid-template-columns:1fr 1fr;gap:16px">';
  h += '<div class="panel"><h2>按年份</h2>'+Object.keys(byYear).sort().reverse().map(function(y){return barRow(y,byYear[y],maxYear);}).join("")+'</div>';
  h += '<div class="panel"><h2>按类型</h2>'+barRow("论文",np,Math.max(np,nn,nr,na))+barRow("知识资料",nr,Math.max(np,nn,nr,na))+barRow("拆解",na,Math.max(np,nn,nr,na))+barRow("笔记",nn,Math.max(np,nn,nr,na))+'</div>';
  h += '</div>';
  h += '<div class="panel" style="margin-top:16px"><h2>高频标签</h2><div class="ctags">'+topTags.map(function(t){return '<span class="chip" onclick="setTag(\''+esc(t)+'\')">'+esc(t)+' ('+tc[t]+')</span>';}).join("")+'</div></div>';
  return h;
}
function statBox(n,l){ return '<div class="stat-box"><div class="n">'+n+'</div><div class="l">'+l+'</div></div>'; }
function barRow(lab,v,max){ var pct=Math.round(100*v/max); return '<div class="bar-row"><span class="lab" title="'+esc(lab)+'">'+esc(lab)+'</span><span class="track"><span class="fill" style="width:'+pct+'%"></span></span><span class="v">'+v+'</span></div>'; }

/* ---------- AI 问答（占位，不接真实 API） ---------- */
function renderAI(){
  return '<div class="ai"><h2>AI 问答</h2>'
    + '<p class="placeholder" style="text-align:left;padding:0;color:var(--warn)">本面板为<strong>完整 UI 占位</strong>：知识库检索已可用，但真实模型调用（API key 接入）按计划暂未实现。把问题发到 WorkBuddy 对话即可获得基于本知识库的真实回答。</p>'
    + '<textarea id="aiq" placeholder="输入你的问题，例如：哪些论文用 foundation model 做单细胞？"></textarea>'
    + '<div class="row">'
    + '<input class="k" id="aikey" type="password" placeholder="API key（暂不启用）" style="width:230px">'
    + '<select id="aimodel"><option>GPT-4o</option><option>Claude 3.5 Sonnet</option><option>通义千问 Max</option><option>GLM-4</option><option>自定义…</option></select>'
    + '<label style="font-size:13px;color:var(--sub)"><input type="checkbox" id="airet" checked> 检索本知识库作为上下文</label>'
    + '<button class="btn" onclick="sendAI()">发送</button></div>'
    + '<div id="aictx"></div><div id="aians"></div>'
    + '<div class="addbox"><h3>导入文献</h3><div class="row"><input id="addurl" placeholder="粘贴论文链接 / 公众号 / arXiv…"/>'
    + '<button class="btn ghost" onclick="copyImport()">复制并提示</button></div>'
    + '<p class="placeholder" style="text-align:left;padding:4px 0">自动导入由 WorkBuddy 对话触发：把链接发到对话框，paper-reader 会自动解析并导入本平台。</p></div></div>';
}
function sendAI(){
  var q = document.getElementById("aiq").value.trim();
  var ctxEl = document.getElementById("aictx");
  var ansEl = document.getElementById("aians");
  if(!q){ ansEl.innerHTML='<div class="answer">请先输入问题。</div>'; return; }
  var res = [];
  if(document.getElementById("airet").checked){ res = retrieve(q, 5); }
  if(res.length){
    ctxEl.innerHTML = '<div class="ctx"><div class="ch">将作为上下文发送给模型（检索到 '+res.length+' 条）</div>'
      + res.map(function(r){ var e=r; var snip=(e.text||e.summary||"").replace(/\n+/g," ").slice(0,160);
        return '<div class="ci"><div class="h">'+esc(e.title)+'</div><div class="s">'+esc(snip)+'…</div></div>'; }).join("") + '</div>';
  } else {
    ctxEl.innerHTML = '<div class="ctx"><div class="ch">未检索到相关条目</div></div>';
  }
  ansEl.innerHTML = '<div class="answer">（占位）AI 回答后端未接入，未发起真实模型调用。以上为从本知识库检索到的相关上下文；在 WorkBuddy 对话中 @ 本知识库 提问，即可获得真实回答。'
    + (document.getElementById("aikey").value ? '（注：粘贴的 API key 在当前版本不会被执行调用。）' : '') + '</div>';
}
function copyImport(){
  var u = document.getElementById("addurl").value.trim();
  if(!u){ alert("请先粘贴链接。"); return; }
  if(navigator.clipboard) navigator.clipboard.writeText(u);
  alert("已复制链接：\n"+u+"\n\n请在 WorkBuddy 对话中发送该链接，我将自动解析并导入本平台。");
}

/* ---------- Skill管理 ---------- */
function renderSkills(){
  var skills = [
    {name:"paper-locator", title:"论文定位与提取", desc:"从公众号文章、B站视频、论文链接、其他资料中提取论文名称并精确定位原始论文，供下一步拆解使用。", path:"kb-site/.workbuddy/skills/paper-locator/SKILL.md"},
    {name:"paper-reader", title:"论文深度拆解", desc:"以生物医学、生物信息学与 AI4Science 研究者视角，深度拆解单篇论文。输出 #0-#9 结构，#0 严格表格形式，不写标题概述。", path:".workbuddy/skills/paper-reader/SKILL.md"},
    {name:"article-summarizer", title:"文章总结器（统一入口）", desc:"收到文章链接/文本后先判定「论文 or 非论文」，再走对应路线：论文→paper-reader 拆解并作为 paper+note 导入；非论文→按 summary-format 总结并作为 kind:resource 独立导入「知识资料」。两路线物理隔离，build 硬闸兜底。", path:"kb-site/.workbuddy/skills/article-summarizer/SKILL.md"}
  ];
  var h = '<div class="panel" style="max-width:820px"><h2>Skill 管理</h2>';
  h += '<p class="placeholder" style="text-align:left;padding:0 0 12px;color:var(--sub)">以下三个 Skill 构成文章处理流水线：<b>定位 → 拆解 → 总结导入</b>。其中「文章总结器」会先判定论文/非论文再分流。点击编辑可直接修改 SKILL.md，修改后即时生效。</p>';
  h += '<div class="pipeline"><div class="pipe-step"><span class="pipe-num">①</span><b>定位</b><br><small>论文提取</small></div><span class="pipe-arr">→</span><div class="pipe-step"><span class="pipe-num">②</span><b>拆解</b><br><small>深度分析</small></div><span class="pipe-arr">→</span><div class="pipe-step"><span class="pipe-num">③</span><b>总结导入</b><br><small>入库平台</small></div></div>';
  skills.forEach(function(s){
    h += '<div class="skill-card"><div class="skill-head"><span class="skill-badge">'+esc(s.name)+'</span><strong>'+esc(s.title)+'</strong></div>';
    h += '<div class="skill-desc">'+esc(s.desc)+'</div>';
    h += '<div class="skill-acts"><button class="btn sm primary" onclick="openSkillEdit(\''+esc(s.name)+'\')">编辑</button>';
    h += '<button class="btn sm ghost" onclick="downloadSkill(\''+esc(s.name)+'\')">导出</button></div></div>';
  });
  h += '<div style="margin-top:14px;display:flex;gap:10px;flex-wrap:wrap">';
  h += '<button class="btn primary" onclick="downloadPipeline()">导出完整流水线（pipeline.md）</button>';
  h += '<button class="btn ghost" onclick="downloadAllSkills()">导出全部 3 个 Skill（zip）</button>';
  h += '</div>';
  h += '<div style="margin-top:18px;padding:12px;background:#f0fdf4;border-radius:8px;border:1px solid #bbf7d0;font-size:13px;color:#166534">';
  h += '<b>使用方式：</b>在 WorkBuddy 对话中直接说"拆解并导入这篇论文 [链接]"即可自动完成。<br>';
  h += '如需给其他大模型使用，点击「导出」下载 pipeline.md 作为 System Prompt 注入。';
  h += '</div></div>';
  return h;
}
async function downloadSkill(name){
  try{
    var r = await fetch("/api/skill/raw?name="+encodeURIComponent(name));
    var d = await r.json();
    if(d.error){ openInfoModal("导出失败", d.error); return; }
    downloadFile(name+".md", d.content);
  }catch(err){ openInfoModal("导出失败", err.message); }
}
function downloadFile(filename, content){
  var blob = new Blob([content], {type:"text/markdown;charset=utf-8"});
  var a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = filename;
  a.click();
  URL.revokeObjectURL(a.href);
}
async function downloadPipeline(){
  var h = '# 论文定位 → 拆解 → 导入 自动化流水线\n\n';
  h += '将以下 System Prompt 注入任意大模型，然后输入论文链接即可自动完成全流程。\n\n---\n\n';
  var names = ["paper-locator","paper-reader","article-summarizer"];
  for(var i=0; i<names.length; i++){
    try{
      var r = await fetch("/api/skill/raw?name="+encodeURIComponent(names[i]));
      var d = await r.json();
      if(!d.error) h += '## '+(i+1)+'. '+names[i]+'\n\n'+d.content+'\n\n---\n\n';
    }catch(_){}
  }
  h += '\n## 使用方式\n\n将以上内容作为 System Prompt，然后输入论文链接：\n\n> "按照 pipeline，拆解并导入这篇论文：[链接]"\n';
  downloadFile("article-pipeline.md", h);
}
async function downloadAllSkills(){
  var names = {"paper-locator":"SKILL.md","paper-reader":"SKILL.md","article-summarizer":"SKILL.md"};
  var files = {};
  for(var k in names){
    try{
      var r = await fetch("/api/skill/raw?name="+k);
      var d = await r.json();
      if(!d.error) files[k+"/"+names[k]] = d.content;
    }catch(_){}
  }
  // Simple zip-like: a tar or just a single combined file
  var h = "";
  for(var f in files){ h += "=== "+f+" ===\n"+files[f]+"\n\n"; }
  downloadFile("paper-skills.txt", h);
}
async function openSkillEdit(name){
  try{
    var r = await fetch("/api/skill/raw?name="+encodeURIComponent(name));
    var d = await r.json();
    if(d.error){ openInfoModal("加载失败", d.error); return; }
    var modal = document.getElementById("skillModal");
    if(!modal){ modal = document.createElement("div"); modal.id = "skillModal"; modal.className = "modal"; modal.onclick = function(ev){ if(ev.target===modal) closeSkillEdit(); }; document.body.appendChild(modal); }
    modal.innerHTML = '<div class="modal-box" style="max-width:900px"><div class="modal-head"><span>编辑 Skill · '+esc(name)+'</span><button class="modal-x" onclick="closeSkillEdit()">×</button></div>'
      + '<div class="modal-body"><textarea id="sk-body" class="edit-raw" spellcheck="false">'+esc(d.content)+'</textarea></div>'
      + '<div class="modal-foot"><span id="skMsg" class="edit-msg"></span>'
      + '<button class="btn sm ghost" onclick="closeSkillEdit()">取消</button>'
      + '<button class="btn sm primary" onclick="saveSkill(\''+esc(name)+'\')">保存</button></div></div>';
    modal.classList.add("show");
  }catch(err){ openInfoModal("加载失败", err.message); }
}
function closeSkillEdit(){ var m=document.getElementById("skillModal"); if(m) m.classList.remove("show"); }
async function saveSkill(name){
  var body = document.getElementById("sk-body").value;
  var btn = document.querySelector("#skillModal .btn.primary");
  if(btn) btn.disabled = true;
  try{
    var r = await fetch("/api/skill/update", {method:"POST", headers:{"Content-Type":"application/json"}, body: JSON.stringify({name:name, content:body})});
    var d = await r.json();
    if(d.error){ if(btn) btn.disabled=false; var m=document.getElementById("skMsg"); if(m) m.textContent="保存失败："+d.error; return; }
    closeSkillEdit();
    openInfoModal("保存成功", "Skill '"+name+"' 已更新，修改即时生效。");
  }catch(err){ if(btn) btn.disabled=false; var m=document.getElementById("skMsg"); if(m) m.textContent="保存出错："+err; }
}

/* ---------- 导出回 Zotero ---------- */
function xesc(s){ return (s==null?"":String(s)).replace(/[&<>"']/g,function(c){return {"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&apos;"}[c];}); }
function slugUUID(slug){
  var h=2166136261>>>0;
  for(var i=0;i<slug.length;i++){ h^=slug.charCodeAt(i); h=Math.imul(h,16777619)>>>0; }
  var a=h.toString(16).padStart(8,"0"); var b=(""+slug.length).padStart(8,"0");
  return "urn:uuid:"+(a+a).slice(0,16)+(b+b).slice(0,16);
}
function download(name, content, type){
  var blob=new Blob([content],{type:type+";charset=utf-8"});
  var a=document.createElement("a"); a.href=URL.createObjectURL(blob); a.download=name;
  document.body.appendChild(a); a.click();
  setTimeout(function(){ URL.revokeObjectURL(a.href); a.remove(); }, 1000);
}
function csvCell(v){ v=(v==null?"":String(v)); if(/[",\n\r]/.test(v)) v='"'+v.replace(/"/g,'""')+'"'; return v; }
function parseAuthor(s){ s=(s||"").trim(); var i=s.indexOf(","); if(i<0) return {family:s, given:""}; return {family:s.slice(0,i).trim(), given:s.slice(i+1).trim()}; }
function mapType(e){ return "article-journal"; }

function exportRDF(){
  var catURI={}; STATE.categories.forEach(function(c){ catURI[c.id]=slugUUID("cat_"+c.id); });
  var L=[];
  L.push('<?xml version="1.0" encoding="UTF-8"?>');
  L.push('<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#" xmlns:z="http://www.zotero.org/namespaces/export#" xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:dcterms="http://purl.org/dc/terms/" xmlns:bib="http://purl.org/net/biblio/" xmlns:prism="http://prismstandard.org/namespaces/1.2/">');
  STATE.categories.forEach(function(c){
    L.push('  <rdf:Description rdf:about="'+catURI[c.id]+'">');
    L.push('    <rdf:type rdf:resource="http://www.zotero.org/namespaces/export#Collection"/>');
    L.push('    <dc:title>'+xesc(c.name)+'</dc:title>');
    if(c.parent && catURI[c.parent]) L.push('    <z:collection rdf:resource="'+catURI[c.parent]+'"/>');
    L.push('  </rdf:Description>');
  });
  STATE.entries.forEach(function(e){
    var uri=slugUUID(e.slug);
    L.push('  <rdf:Description rdf:about="'+uri+'">');
    if(e.kind==="note" || e.kind==="analysis"){
      L.push('    <z:itemType>note</z:itemType>');
      L.push('    <z:note>'+xesc(e.text||e.title)+'</z:note>');
    } else {
      L.push('    <z:itemType>journalArticle</z:itemType>');
      L.push('    <dc:title>'+xesc(e.title)+'</dc:title>');
      if(e.authors && e.authors.length) L.push('    <dc:creator><rdf:Seq>'+e.authors.map(function(a){return '<rdf:li>'+xesc(a)+'</rdf:li>';}).join("")+'</rdf:Seq></dc:creator>');
      if(e.date) L.push('    <dc:date>'+xesc(e.date)+'</dc:date>');
      if(e.journal) L.push('    <z:publicationTitle>'+xesc(e.journal)+'</z:publicationTitle>');
      if(e.source) L.push('    <dc:identifier>'+xesc(e.source)+'</dc:identifier>');
      (e.tags||[]).forEach(function(t){ L.push('    <dc:subject>'+xesc(t)+'</dc:subject>'); });
      if(e.category && e.category!=="uncat" && catURI[e.category]) L.push('    <z:collection rdf:resource="'+catURI[e.category]+'"/>');
      if(e.text) L.push('    <z:note>'+xesc(e.text)+'</z:note>');
    }
    L.push('  </rdf:Description>');
  });
  L.push('</rdf:RDF>');
  download("knowledge-library.rdf", L.join("\n"), "application/rdf+xml");
}
function exportCSV(){
  var rows=[["Key","Item Type","Author","Title","Publication Title","DOI","Url","Date","Manual Tags","Notes","Collections"]];
  STATE.entries.forEach(function(e){
    if(e.kind==="note"||e.kind==="analysis"){ rows.push(["","note","",e.title,"","","","","",(e.text||"").replace(/\n+/g," "),""]); return; }
    var doi=(e.source&&e.source.indexOf("doi.org/")>=0)?e.source.split("doi.org/")[1]:"";
    rows.push([ e.slug, "journalArticle", (e.authors||[]).join("; "), e.title, e.journal||"", doi, e.source||"", e.date||"", (e.tags||[]).join("; "), (e.text||"").replace(/\n+/g," ").slice(0,3000), (e.category&&e.category!=="uncat")?catPath(e.category):"" ]);
  });
  var csv="\uFEFF"+rows.map(function(r){ return r.map(csvCell).join(","); }).join("\r\n");
  download("knowledge-library.csv", csv, "text/csv");
}
function exportJSON(){
  var items=STATE.entries.filter(function(e){return e.kind==="paper"||e.kind==="resource";}).map(function(e){
    var o={ "title":e.title, "type":mapType(e), "URL":e.source||"" };
    if(e.authors&&e.authors.length) o.author=e.authors.map(parseAuthor);
    if(e.date) o.issued={ "date-parts":[[ parseInt(e.date.slice(0,4))||null ]] };
    if(e.journal) o["container-title"]=e.journal;
    var doi=(e.source&&e.source.indexOf("doi.org/")>=0)?e.source.split("doi.org/")[1]:"";
    if(doi) o.DOI=doi;
    if(e.tags&&e.tags.length) o.keywords=e.tags;
    if(e.category&&e.category!=="uncat") o.categories=[catPath(e.category)];
    if(e.text) o.note=e.text;
    return o;
  });
  download("knowledge-library.json", JSON.stringify(items,null,2), "application/json");
}
function renderExport(){
  var n=STATE.entries.length;
  var np=papers().length, nr=resources().length, na=analyses().length, nn=notes().length;
  return '<div class="panel" style="max-width:780px"><h2>导出回 Zotero</h2>'
    +'<p class="placeholder" style="text-align:left;padding:0;color:var(--sub)">将当前文献库（论文 '+np+' / 资料 '+nr+' / 拆解 '+na+' / 笔记 '+nn+'，共 '+n+' 条，'+STATE.categories.length+' 个分类）导出，便于回灌 Zotero。推荐 <strong>Zotero RDF</strong>：可完整保留分类树与笔记，在 Zotero 中「文件 › 导入」选择该 .rdf 即可还原 collections 与 notes。</p>'
    +'<div class="row" style="margin-top:14px">'
    +'<button class="btn" onclick="exportRDF()">导出 Zotero RDF（含分类+笔记）</button>'
    +'<button class="btn ghost" onclick="exportCSV()">导出 CSV</button>'
    +'<button class="btn ghost" onclick="exportJSON()">导出 CSL JSON</button>'
    +'</div>'
    +'<div class="stat-grid" style="margin-top:18px">'+statBox(n,"总条目")+statBox(np,"论文")+statBox(nr,"知识资料")+statBox(STATE.categories.length,"分类")+'</div>'
    +'<p class="placeholder" style="text-align:left;padding:8px 0 0;color:var(--muted)">注：本 CSV 导出不含收藏目录列（Zotero CSV 格式限制），完整还原请用 RDF。</p>'
    +'</div>';
}

window.addEventListener("DOMContentLoaded", loadData);
