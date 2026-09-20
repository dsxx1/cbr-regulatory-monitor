'use strict';
let serviceState=null;
document.documentElement.dataset.role='viewer';
document.documentElement.dataset.theme='light';
document.title='РегКонтроль · новости и требования для ломбардов';
$('.brand>span:last-child').textContent='РегКонтроль';$('.brandmark').textContent='РК';
$('.sitefooter span').textContent='РегКонтроль · источники и проверяемые выводы';
const restricted=new Set(['quality','settings','lab']);
titles.lab=['Проверка моделей','Отдельный запрос к бесплатной модели, без отправки в Б24.'];
const labSection=el('section','owner-only');labSection.id='labView';labSection.hidden=true;$('#main').append(labSection);
const labNavigation=el('button','nav','Проверка LLM');labNavigation.dataset.view='lab';labNavigation.onclick=()=>{if(!serviceState?.owner)return openLogin();if(data)switchView('lab');};$('.sidebar nav').append(labNavigation);
const originalSwitch=switchView;
switchView=function(next){return originalSwitch(restricted.has(next)&&!serviceState?.owner?'feed':next);};
const statusLine=el('div','service-line');statusLine.setAttribute('role','status');$('.page-heading').after(statusLine);
function openLogin(){toast('Управление доступно на компьютере с мониторингом: http://localhost:8787');}
const adminControls=el('div','owner-controls owner-only');$('.topbar').append(adminControls);
const runButton=el('button','button primary','Проверить новости');
const menu=el('details','control-menu');menu.append(el('summary','','Управление'));
const scheduleButton=el('button','button','Расписание');
const stopButton=el('button','button','Остановить процесс');
menu.append(scheduleButton,stopButton);adminControls.append(runButton,menu);
const backupButton=el('button','button','Резервная копия');menu.append(backupButton);
backupButton.onclick=async()=>{backupButton.disabled=true;try{const result=await post('/api/backup');statusLine.textContent='Копия создана и проверена: '+result.file;}catch(e){toast(e.message);}finally{backupButton.disabled=false;}};
async function post(path,body={}){const r=await fetch(path,{method:'POST',headers:{'Content-Type':'application/json','X-Monitor-Token':serviceState?.token||''},body:JSON.stringify(body)});const v=await r.json();if(!r.ok)throw Error(v.error||'Не удалось выполнить действие');return v;}
runButton.onclick=async()=>{try{await post('/api/check');await refreshService();}catch(e){toast(e.message);}};
scheduleButton.onclick=async()=>{try{await post('/api/schedule',{enabled:serviceState.schedule!=='on'});await refreshService();}catch(e){toast(e.message);}};
stopButton.onclick=async()=>{if(!confirm('Остановить процесс? Для повторного запуска откройте ЗАПУСТИТЬ.cmd.'))return;try{await post('/api/stop');statusLine.textContent='Мониторинг остановлен';}catch(e){toast(e.message);}};
const taskButton=el('button','button owner-only','Создать задачу в Б24');$('.reader-actions').append(taskButton);
taskButton.onclick=async()=>{if(!current?.brief)return toast('Сначала нужен готовый разбор');if(!confirm('Создать задачу на владельца вебхука Б24? Срок исполнения автоматически не назначается.'))return;try{taskButton.disabled=true;const r=await post('/api/task',{id:current.id});toast('Создана задача №'+r.taskId+'. Ссылка отправляется ботом.');}catch(e){toast(e.message);}finally{taskButton.disabled=false;}};
const criteria=el('details','criteria');criteria.append(el('summary','','Что означают цвета'));
const descriptions={high:'Важно — существенные обязанности, сроки или риск для работы.',medium:'Подготовиться — ожидаемое изменение или вопрос, требующий проверки.',low:'Учесть — небольшое изменение процесса.',news:'Для сведения — информация без изменения требований.',unknown:'Не оценено — разбор ещё не готов; это не означает низкую важность.'};
for(const [key,text] of Object.entries(descriptions))criteria.append(el('p','criterion '+key,text));$('.page-heading').append(criteria);
titles.feed=['Новости и изменения',''];
titles.sources=['Источники',''];
const advanced=el('details','advanced-filters');advanced.append(el('summary','','Фильтры'));
const advancedBody=el('div','advanced-body');for(const selector of ['#sourceFilter','#typeFilter','#sort','#stageFilter'])advancedBody.append($(selector));
const archiveOption=$('.list-info label');if(archiveOption)advancedBody.append(archiveOption);advancedBody.append(criteria);advanced.append(advancedBody);$('.toolbar').append(advanced);
const originalFeed=renderFeed;renderFeed=function(){originalFeed();const list=filtered();$('#resultCount').textContent=`${list.length} материалов · ${list.filter(n=>n.brief).length} с готовым разбором`;};
for(const key of ['high','medium','low','news']){const b=$(`#priorityFilters [data-priority="${key}"]`);b.replaceChildren(el('span','dot '+key),document.createTextNode(priorities[key]));}
$('.footnote').textContent='Выводы сопровождаются источниками. Применимость требований к компании нужно подтвердить отдельно.';
$('.sidebar-bottom').replaceChildren();$('.sidebar-bottom').hidden=true;
let lastCompleted=null;
async function refreshService(){
 try{
  const previouslyOwner=!!serviceState?.owner;
  const response=await fetch('/api/status',{cache:'no-store'});
  if(!response.ok)throw Error();
  serviceState=await response.json();
  document.documentElement.dataset.role=serviceState.owner?'owner':'viewer';
  if(!serviceState.owner){statusLine.textContent='';if(restricted.has(view))switchView('feed');return;}
  const job=serviceState.job;
  statusLine.textContent=(job?.stage||'Готов к проверке')+(job?.error?' · '+job.error:'');
  scheduleButton.textContent=serviceState.schedule==='on'?'Каждый час · выключить':'Расписание выключено · включить';
  runButton.textContent=job?.state==='running'?'Проверка идёт…':'Проверить новости';
  if(data){
   data.llmHealth=serviceState.health;data.settings=serviceState.settings;
   if(view==='quality')qualityView();
   if(!previouslyOwner&&view==='sources')sourcesView();
  }
  if(job?.state==='done'&&lastCompleted!==job.id){lastCompleted=job.id;await load();}
 }catch{
  statusLine.textContent='Сервер недоступен. Показаны ранее загруженные материалы.';
  document.documentElement.dataset.role='viewer';serviceState=null;
 }
}
sourcesView=async function(){
 const root=$('#sourcesView');root.replaceChildren();
 const grid=el('div','source-sites');root.append(grid);
 const logs=data.status.sources||[];
 function sourceCard(name,url,rows,kind){const card=el('article','source-site');card.append(el('h2','',name),link(new URL(url).hostname+' ↗',url,'source-domain'));const checked=rows.length;const failed=rows.filter(r=>r.status!=='ok').length;card.append(el('p',failed?'warn':'',checked?(failed?`Не удалось проверить разделов: ${failed}`:`Проверено разделов: ${checked}`):'Ещё не проверен'),el('small','',kind));if(rows.length){const details=el('details');details.append(el('summary','','Результаты проверки'));for(const row of rows)details.append(el('p','',`${sourceName(row.name)} — ${row.status==='ok'?'данные получены':'ошибка загрузки'}`));card.append(details);}grid.append(card);}
 sourceCard('Банк России','https://www.cbr.ru/',logs.filter(s=>/ЦБ|RSS:|категор|Дерево/i.test(s.name)),'Правовые акты, разъяснения и RSS');
 sourceCard('СРО ломбардов','https://sro-lombard.ru/news.html',logs.filter(s=>s.name==='СРО'),'Отраслевая лента');
 sourceCard('Лига ломбардов','https://www.ligalomb.ru/index-text.htm',logs.filter(s=>s.name==='Лига ломбардов'),'Новости и открытый архив');
 const stamp=el('p','source-updated','Последний сбор: '+formatDate(data.status.checked,true)+' ЕКБ');root.append(stamp);
 try{const response=await fetch('/api/sources',{cache:'no-store'});if(!response.ok)throw Error();const registry=await response.json();for(const s of registry.sources)sourceCard(s.name,s.url,logs.filter(r=>r.url===s.url),s.kind==='rss'?'RSS · до 20 материалов за проверку':'Изменения веб-страницы · не лента отдельных новостей');}catch{root.append(el('p','warn','Не удалось загрузить дополнительные источники.'));}
 if(!serviceState?.owner)return;
 const details=el('details','add-source owner-only');details.append(el('summary','','Добавить источник'));
 const form=el('form','source-form');
 const name=el('input');name.required=true;name.maxLength=100;name.placeholder='Название сайта';name.setAttribute('aria-label','Название нового источника');
 const url=el('input');url.required=true;url.type='url';url.placeholder='https://example.ru/rss';url.setAttribute('aria-label','Адрес нового источника');
 const kind=el('select');kind.setAttribute('aria-label','Тип нового источника');for(const [value,text] of [['rss','RSS — отдельные публикации'],['page','Веб-страница — изменения текста']]){const o=el('option','',text);o.value=value;kind.append(o);}
 const button=el('button','button primary','Добавить');button.type='submit';const result=el('p');result.setAttribute('role','status');form.append(name,url,kind,el('p','lab-note','RSS: поддерживается RSS 2.0, ссылки на статьи того же сайта. Веб-страница: сохраняются изменения её текста; сайты с JavaScript и авторизацией могут потребовать отдельного обработчика.'),button,result);
 form.onsubmit=async e=>{e.preventDefault();button.disabled=true;try{await post('/api/sources',{name:name.value,url:url.value,kind:kind.value});await sourcesView();toast('Источник добавлен. Он будет обработан при следующей проверке.');}catch(error){result.textContent=error.message;button.disabled=false;}};
 details.append(form);root.prepend(details);
};
qualityView=function(){if(!serviceState?.owner)return;const root=$('#qualityView');root.replaceChildren();const h=serviceState.health||{};root.append(panel('Работа бесплатных моделей',`${h.attempts||0} попыток · ${h.responses||0} ответов · ${h.failures||0} отказов. Полученный ответ ещё не означает, что разбор прошёл проверку.`));const history=panel('Последние проверки');for(const j of serviceState.history||[])history.append(el('p','',`№${j.id} · ${j.stage} · ${formatDate(j.started,true)}${j.error?' · '+j.error:''}`));root.append(history);const events=panel('Последние обращения к моделям');for(const e of (h.events||[]).slice(-12).reverse())events.append(el('p','',`${e.route} · ${e.status==='response'?'Ответ получен':'Отказ'} · ${(e.ms/1000).toFixed(1)} с`));root.append(events);};
settingsView=function(){if(!serviceState?.owner)return;const root=$('#settingsView');root.replaceChildren();const p=panel('Настройки анализа','Изменения применяются со следующего запуска. Используются только бесплатные маршруты.');const config=serviceState.settings;for(const [key,label] of [['generator','Генератор'],['reviewer','Проверяющий']]){const row=el('label','setting',label);const s=el('select');s.id='setting-'+key;for(const name of data.models){const o=el('option','',name);o.value=name;s.append(o);}s.value=config[key];row.append(s);p.append(row);}const row=el('label','setting','Материалов за проверку');const limit=el('select');limit.id='setting-max';for(let i=1;i<=5;i++){const o=el('option','',String(i));o.value=i;limit.append(o);}limit.value=config.max_calls;row.append(limit);p.append(row);const save=el('button','button primary','Сохранить');save.onclick=async()=>{try{serviceState.settings=await post('/api/settings',draftSettings());toast('Настройки сохранены');}catch(e){toast(e.message);}};p.append(save);root.append(p);};
async function initializeAccess(){const desired=location.hash.slice(1);await refreshService();if(serviceState?.owner&&data&&restricted.has(desired))switchView(desired);}
initializeAccess();setInterval(refreshService,10000);

function labView(){
 if(!serviceState?.owner||labSection.children.length)return;
 const form=el('form','lab-form');
 const label=el('label','','Модель');label.htmlFor='labModel';
 const model=el('select');model.id='labModel';
 for(const [id,title] of [['kilo-auto/free','Автоматический бесплатный маршрут'],['inclusionai/ling-3.0-flash-vl:free','Ling 3.0 Flash'],['poolside/laguna-s-2.1:free','Poolside Laguna S 2.1']]){const o=el('option','',title);o.value=id;model.append(o);}
 const inputLabel=el('label','','Ваше сообщение');inputLabel.htmlFor='labMessage';
 const input=el('textarea');input.id='labMessage';input.maxLength=4000;input.rows=6;input.placeholder='Напишите вопрос или вставьте небольшой публичный фрагмент для проверки…';input.required=true;
 const warning=el('p','lab-note','Текст будет отправлен внешнему бесплатному провайдеру. Не вводите вебхуки, пароли и закрытые данные. Переписка не сохраняется на сервере и не отправляется в Б24.');
 const actions=el('div','lab-actions');const submit=el('button','button primary','Отправить модели');submit.type='submit';const sample=el('button','button','Подставить контрольный вопрос');sample.type='button';sample.onclick=()=>{input.value='Сколько будет 17 + 25? Ответь числом, затем одной короткой фразой по-русски.';input.focus();};actions.append(submit,sample);
 const status=el('p','lab-status');status.setAttribute('role','status');
 const result=el('section','lab-result');result.hidden=true;const heading=el('h2','','Ответ модели');const meta=el('p','lab-note');const answer=el('div','lab-answer');result.append(heading,meta,answer);
 form.append(label,model,inputLabel,input,warning,actions,status);labSection.append(form,result);
 form.onsubmit=async e=>{e.preventDefault();if(!input.value.trim())return;submit.disabled=true;model.disabled=true;sample.disabled=true;result.hidden=true;const started=Date.now();status.textContent='Отправляем запрос…';const timer=setInterval(()=>{status.textContent=`Ожидаем ответ · ${Math.floor((Date.now()-started)/1000)} с`;},1000);
 try{const r=await post('/api/model-test',{model:model.value,message:input.value});heading.textContent='Ответ получен';meta.textContent=`Фактическая модель: ${r.actualModel} · ${r.seconds} с · Токены: ${r.tokens??'не сообщены'} · Стоимость: ${r.cost==null?'не сообщена провайдером':'$'+r.cost} · Резервных попыток: ${r.fallbacks}`;answer.textContent=r.answer;result.hidden=false;status.textContent='Технический тест пройден. Правильность содержания ответа проверяйте отдельно.';}
 catch(error){status.textContent=error.message||'Запрос не выполнен. Попробуйте позднее.';}
 finally{clearInterval(timer);submit.disabled=false;model.disabled=false;sample.disabled=false;}
 };
}
