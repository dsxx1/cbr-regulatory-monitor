'use strict';
let serviceState=null;
document.documentElement.dataset.role='viewer';
document.documentElement.dataset.theme='light';
const restricted=new Set(['quality','settings']);
const originalSwitch=switchView;
switchView=function(next){return originalSwitch(restricted.has(next)&&!serviceState?.owner?'feed':next);};
const statusLine=el('div','service-line');statusLine.setAttribute('role','status');$('.page-heading').after(statusLine);
const adminControls=el('div','owner-controls owner-only');$('.topbar').append(adminControls);
const runButton=el('button','button primary','Проверить новости');
const menu=el('details','control-menu');menu.append(el('summary','','Управление'));
const scheduleButton=el('button','button','Расписание');
const stopButton=el('button','button','Остановить процесс');
menu.append(scheduleButton,stopButton);adminControls.append(runButton,menu);
async function post(path,body={}){const r=await fetch(path,{method:'POST',headers:{'Content-Type':'application/json','X-Monitor-Token':serviceState?.token||''},body:JSON.stringify(body)});const v=await r.json();if(!r.ok)throw Error(v.error||'Не удалось выполнить действие');return v;}
runButton.onclick=async()=>{try{await post('/api/check');await refreshService();}catch(e){toast(e.message);}};
scheduleButton.onclick=async()=>{try{await post('/api/schedule',{enabled:serviceState.schedule!=='on'});await refreshService();}catch(e){toast(e.message);}};
stopButton.onclick=async()=>{if(!confirm('Остановить процесс? Для повторного запуска откройте ЗАПУСТИТЬ.cmd.'))return;try{await post('/api/stop');statusLine.textContent='Мониторинг остановлен';}catch(e){toast(e.message);}};
const taskButton=el('button','button owner-only','Создать задачу в Б24');$('.reader-actions').append(taskButton);
taskButton.onclick=async()=>{if(!current?.brief)return toast('Сначала нужен готовый разбор');if(!confirm('Создать задачу на владельца вебхука Б24? Срок исполнения автоматически не назначается.'))return;try{taskButton.disabled=true;const r=await post('/api/task',{id:current.id});toast('Создана задача №'+r.taskId+'. Ссылка отправляется ботом.');}catch(e){toast(e.message);}finally{taskButton.disabled=false;}};
const criteria=el('details','criteria');criteria.append(el('summary','','Что означают цвета'));
const descriptions={high:'Важно — существенные обязанности, сроки или риск для работы.',medium:'Подготовиться — ожидаемое изменение или вопрос, требующий проверки.',low:'Учесть — небольшое изменение процесса.',news:'Для сведения — информация без изменения требований.',unknown:'Не оценено — разбор ещё не готов; это не означает низкую важность.'};
for(const [key,text] of Object.entries(descriptions))criteria.append(el('p','criterion '+key,text));$('#feedView').prepend(criteria);
for(const key of ['high','medium','low','news']){const b=$(`#priorityFilters [data-priority="${key}"]`);b.replaceChildren(el('span','dot '+key),document.createTextNode(priorities[key]));}
$('.footnote').textContent='Выводы сопровождаются источниками. Применимость требований к компании нужно подтвердить отдельно.';
$('.sidebar-bottom').replaceChildren(el('span','access-label','Просмотр для сотрудников'));
const localOwnerHint=el('p','owner-hint','Владельцу: откройте ВХОД-ВЛАДЕЛЬЦА.cmd на этом компьютере.');
if(['localhost','127.0.0.1'].includes(location.hostname))$('.sidebar-bottom').append(localOwnerHint);
let lastCompleted=null;
async function refreshService(){try{const r=await fetch('/api/status',{cache:'no-store'});if(!r.ok)throw Error();serviceState=await r.json();document.documentElement.dataset.role=serviceState.owner?'owner':'viewer';$('.access-label').textContent=serviceState.owner?'Режим владельца':'Просмотр для сотрудников';if(!serviceState.owner){statusLine.textContent='';if(restricted.has(view))switchView('feed');return;}const j=serviceState.job;statusLine.textContent=(j?.stage||'Готов к проверке')+(j?.error?' · '+j.error:'');scheduleButton.textContent=serviceState.schedule==='on'?'Каждый час · выключить':'Расписание выключено · включить';runButton.textContent=j?.state==='running'?'Проверка идёт…':'Проверить новости';if(data){data.llmHealth=serviceState.health;data.settings=serviceState.settings;if(view==='quality')qualityView();}if(j?.state==='done'&&lastCompleted!==j.id){lastCompleted=j.id;await load();}}catch{statusLine.textContent='Сервер недоступен. Показаны ранее загруженные материалы.';document.documentElement.dataset.role='viewer';serviceState=null;}}
const oldSources=sourcesView;
sourcesView=function(){oldSources();const root=$('#sourcesView');const first=root.firstElementChild;if(first)first.replaceChildren(el('h2','','Проверка источников'),el('p','','Последнее обновление: '+formatDate(data.status.checked,true)+' ЕКБ'));if(!serviceState?.owner){const panels=[...root.children];for(const p of panels)if(p.textContent.includes('Сообщения в рабочий чат'))p.remove();}};
qualityView=function(){if(!serviceState?.owner)return;const root=$('#qualityView');root.replaceChildren();const h=serviceState.health||{};root.append(panel('Работа бесплатных моделей',`${h.attempts||0} попыток · ${h.responses||0} ответов · ${h.failures||0} отказов. Полученный ответ ещё не означает, что разбор прошёл проверку.`));const history=panel('Последние проверки');for(const j of serviceState.history||[])history.append(el('p','',`№${j.id} · ${j.stage} · ${formatDate(j.started,true)}${j.error?' · '+j.error:''}`));root.append(history);const events=panel('Последние обращения к моделям');for(const e of (h.events||[]).slice(-12).reverse())events.append(el('p','',`${e.route} · ${e.status==='response'?'Ответ получен':'Отказ'} · ${(e.ms/1000).toFixed(1)} с`));root.append(events);};
settingsView=function(){if(!serviceState?.owner)return;const root=$('#settingsView');root.replaceChildren();const p=panel('Настройки анализа','Изменения применяются со следующего запуска. Используются только бесплатные маршруты.');const config=serviceState.settings;for(const [key,label] of [['generator','Генератор'],['reviewer','Проверяющий']]){const row=el('label','setting',label);const s=el('select');s.id='setting-'+key;for(const name of data.models){const o=el('option','',name);o.value=name;s.append(o);}s.value=config[key];row.append(s);p.append(row);}const row=el('label','setting','Материалов за проверку');const limit=el('select');limit.id='setting-max';for(let i=1;i<=5;i++){const o=el('option','',String(i));o.value=i;limit.append(o);}limit.value=config.max_calls;row.append(limit);p.append(row);const save=el('button','button primary','Сохранить');save.onclick=async()=>{try{serviceState.settings=await post('/api/settings',draftSettings());toast('Настройки сохранены');}catch(e){toast(e.message);}};p.append(save);root.append(p);};
async function initializeAccess(){const match=location.hash.match(/^#owner=([A-Za-z0-9_-]+)$/);if(match){history.replaceState(null,'',location.pathname+'#feed');try{await post('/api/login',{key:match[1]});location.reload();return;}catch(e){toast(e.message);}}await refreshService();}
initializeAccess();setInterval(refreshService,10000);
