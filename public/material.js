'use strict';
const importanceMeaning={unknown:'Анализ не выполнен. Важность не определена.',high:'Приоритетная проверка влияния на операции ломбарда. Не означает автоматического изменения регламентов.',medium:'Нужно оценить и подготовить изменения; немедленное исполнение не установлено.',low:'Низкое ожидаемое влияние. Достаточно планового наблюдения.',news:'Информационный материал. Практические действия по источнику не выявлены.'};
const eventNames={инициатива:'Инициатива',проект:'Проект',принятый_акт:'Принятый акт',разъяснение:'Разъяснение',новость:'Новость',неясно:'Статус требует проверки'};
const originalReader=readerRender;
const originalMarkdown=markdown;
const baseFiltered=filtered;
filtered=function(){const list=baseFiltered();if($('#sort').value==='priority'){const rank={high:0,medium:1,low:2,news:3,unknown:4};list.sort((a,b)=>(rank[a.priority]??4)-(rank[b.priority]??4)||dateValue(b.date)-dateValue(a.date));}return list;};
markdown=function(n){
 if(!n.brief)return originalMarkdown(n);
 const b=n.brief;
 const md=['# '+n.title,'',`${n.source} · ${formatDate(n.date)}`,'',`[Источник](${n.url})`,'','## Кратко','',b.summary,'','## Статус изменения','',eventNames[b.event_status]||b.event_status,'','## Важность и её основание','',priorities[n.priority]+'. '+b.priority_reason,'',importanceMeaning[n.priority],'','## Влияние на работу ломбарда','',b.impact,'','## Сроки','',b.timing,'','## Рекомендуемые действия','',...b.actions.map(x=>'- '+x),'','## Что ещё проверить','',...b.uncertainties.map(x=>'- '+x),'','## Основания из публикации',''];
 for(const x of b.evidence)md.push(x.claim,'','> '+x.citation,'');
 if(n.verification?.context_note)md.push('## Проверка нормативного контекста','',n.verification.context_note,'');
 for(const ref of n.verification?.references||[])md.push(`[${ref.title}](${urlSafe(ref.url)})`,'');
 md.push('---','Дата разбора: '+formatDate(n.checked,true)+' ЕКБ. '+(n.verification?.note||'Цитаты сверены, выводы проверены отдельным запросом модели.'),'Юридическая применимость требует подтверждения специалистом.');return md.join('\n');
};
function headingText(parent,title,text){parent.append(el('h2','',title),el('p','',text));}
function bulletSection(parent,title,items){parent.append(el('h2','',title));const ul=el('ul');for(const item of items)ul.append(el('li','',item));parent.append(ul);}
readerRender=function(){
 originalReader();const n=current,b=n.brief;
 const ready=Boolean(b);
 $('#download').disabled=false;$('#copy').disabled=false;
 $('#download').textContent=ready?'↓ Разбор .md':n.body?'↓ Исходник .md':'↓ Карточка .md';
 $('#download').title=ready?'Скачать содержательный разбор':'Скачать материал с явной отметкой, что анализ ещё не завершён';
 const root=$('#readerContent');
 if(!ready){
   if(readerTab==='markdown'){root.replaceChildren(el('p','callout','Загружаем Markdown…'));readServerMarkdown(n).then(text=>{if(current?.id===n.id&&readerTab==='markdown')root.replaceChildren(el('pre','',text));}).catch(()=>root.replaceChildren(el('pre','',markdown(n))));}
   else if(readerTab==='summary'){
     root.replaceChildren();const info=el('div','importance-box');info.append(el('strong','',n.body?'Текст загружен · ожидает разбора':'Материал ожидает извлечения текста'),el('p','',n.processingText||'Поставлен в очередь автоматической обработки.'));
     if(n.processing?.retry_at)info.append(el('small','','Повторная попытка не раньше '+formatDate(n.processing.retry_at,true)+' ЕКБ'));
     root.append(info,el('h2','','Содержание источника'),el('p','',n.body?n.body.slice(0,6000):'Вложение или страница пока не распознаны. Оригинал доступен по ссылке; причина показана в очереди обработки.'));
     if(n.body?.length>6000)root.append(el('p','review-note','Полный доступный текст — во вкладке «Текст источника» и в MD-файле.'));
     if(n.processing?.error)root.append(el('p','review-note','Последняя попытка: '+failureText(n.processing.error)));
   }
   return;
 }
 if(readerTab!=='summary')return;
 root.replaceChildren();
 const intro=el('div','brief-intro');intro.append(pill(eventNames[b.event_status]||b.event_status),el('p','lead',b.summary));root.append(intro);
 const importance=el('div','importance-box '+n.priority);importance.append(el('strong','',({high:'Высокая важность',medium:'Средняя важность',low:'Низкая важность',news:'Информационный материал',unknown:'Нужна оценка'})[n.priority]),el('p','',b.priority_reason),el('small','',importanceMeaning[n.priority]));root.append(importance);
 headingText(root,'Что меняется для ломбарда',b.impact);
 headingText(root,'Когда и на каком основании',b.timing);
 bulletSection(root,'Что стоит сделать',b.actions);
 bulletSection(root,'Что пока не подтверждено',b.uncertainties);
 if(n.verification?.context_note){headingText(root,'Проверка нормативного контекста',n.verification.context_note);for(const ref of n.verification.references||[])root.append(link(ref.title+' ↗',ref.url,'reference-link'));}
 const details=el('details','evidence');details.append(el('summary','','Цитаты и основания · '+b.evidence.length));for(const x of b.evidence){details.append(el('p','',x.claim),el('blockquote','',x.citation));}root.append(details);
 root.append(el('p','review-note',n.verification?.note||'Дословные цитаты проверены автоматически. Отдельный запрос LLM проверил выводы. Актуальность и применимость нормы подтверждает специалист.'));
};
const unknownFilter=el('button','chip','Не оценено');unknownFilter.dataset.priority='unknown';unknownFilter.onclick=()=>{priority='unknown';shown=24;$('#priorityFilters').querySelectorAll('button').forEach(b=>b.classList.toggle('selected',b===unknownFilter));renderFeed();};$('#priorityFilters').append(unknownFilter);
$('.eyebrow').textContent='РЕГУЛЯТОРНЫЙ МОНИТОРИНГ';
$('.footnote').textContent='Важность появляется только после содержательного разбора и сопровождается объяснением. Материалы без разбора отмечены «Не оценено».';
$('.sitefooter span').textContent='Регулятор · материалы и основания';

titles.sources=['Источники и расписание','Что удалось загрузить, когда проверяли и что требует внимания.'];
function sourceName(name){return ({'Дерево категорий 426':'ЦБ · список разделов о ломбардах','Разъяснения, категория 774':'ЦБ · залоговые билеты','Разъяснения, категория 378':'ЦБ · отчётность ломбардов'})[name]||name.replace('RSS: ','ЦБ · ').replace('Правовые акты ЦБ: ','ЦБ · ');}
sourcesView=function(){
 const root=$('#sourcesView');root.replaceChildren();
 const timing=panel('Проверяем дважды в рабочий день','11:17 и 15:17 по Екатеринбургу. По выходным плановых проверок нет. Запуск может задерживаться в очереди GitHub.');
 timing.append(el('p','','Последняя проверка: '+formatDate(data.status.checked,true)+' ЕКБ'),el('p','','Ближайшая по расписанию: '+nextRun()+' ЕКБ'));root.append(timing);
 const table=panel('Результат последней проверки','«Загружено» означает, что сайт открылся и публикации получены. Это ещё не означает, что модель разобрала все материалы или подтвердила новые требования.');
 for(const s of data.status.sources||[]){
  const row=el('div','source-row');const info=el('div');info.append(el('strong','',sourceName(s.name)));
  const detail=s.detail||'';const match=detail.match(/(?:записей|документов|Материалов в окне):\s*(\d+)/i);const number=match?Number(match[1]):null;
  const ok=s.status==='ok';const directory=s.name.includes('Дерево категорий');
  const result=ok?(directory?'Список разделов обновлён':number===0?'Публикаций в выдаче нет':number===null?'Данные загружены':`Загружено материалов: ${number}`):'Не удалось загрузить';
  let explanation=ok?(directory?'Проверено, не появились ли новые разделы ЦБ.':number===0?'Источник доступен, но текущая выдача пуста.':'Публикации получены. Статус их анализа указан в ленте.'):'Проверка не завершена. Повторим при следующем запуске; отсутствие данных не означает отсутствие новостей.';
  if(s.name==='Лига ломбардов')explanation='Проверена открытая архивная страница; в мониторинг взято текущее окно публикаций.';
  if(s.name==='СРО')explanation='Проверена доступная лента новостей. Исторический архив охвачен не полностью.';
  if(!ok)explanation='Не удалось получить данные с сайта. Причина и подробности — в журнале запуска.';
  info.append(el('small','',explanation),el('small','','Проверено '+formatDate(data.status.checked,true)+' ЕКБ'));
  row.append(info,el('span',ok?'ok':'warn',result));table.append(row);
 }
 root.append(table);
 root.append(panel('Получено ≠ разобрано',`В последнем запуске модель приняла после проверок: ${data.status.accepted||0}. Ожидают анализа: ${data.status.pending||0}. Нужен полный текст: ${data.status.needs_full_text||0}. Все собранные заголовки не считаются прочитанными моделью.`));
 const delivery=panel('Сообщения в рабочий чат',data.delivery.text);delivery.append(el('p','','Последняя проверка доставки: '+formatDate(data.delivery.verifiedAt,true)),link('Посмотреть журнал запуска ↗','https://github.com/dsxx1/cbr-regulatory-monitor/actions/workflows/cloud.yml','button'));root.append(delivery);
};
const baseStats=renderStats;
renderStats=function(){baseStats();const cells=$('#stats').children;const ready=data.news.filter(n=>n.brief).length;const waiting=data.news.length-ready;
 if(cells[1]){cells[1].querySelector('label').textContent='Важных среди разобранных';cells[1].querySelector('small').textContent=waiting?`Ещё ${waiting} не оценены`:'Все материалы оценены';if(!ready)cells[1].querySelector('strong').textContent='—';}
 if(cells[2]){cells[2].querySelector('label').textContent='Разборы готовы';cells[2].querySelector('strong').textContent=ready;cells[2].querySelector('small').textContent='С выводами, основаниями и MD';}
 if(cells[3]){cells[3].querySelector('label').textContent='Ещё обрабатываются';cells[3].querySelector('strong').textContent=waiting;cells[3].querySelector('small').textContent='Это не «неважные» новости';}
 let progress=$('#backlogProgress');if(!progress){progress=el('div','backlog-progress');progress.id='backlogProgress';$('#stats').after(progress);}
 const counts=data.backlog?.counts||{};
 progress.replaceChildren(el('strong','',`Разобрано ${ready} из ${data.news.length}`),el('span','','Архив обрабатывается в облаке порциями каждый час. '+(data.backlog?.last_finished?'Последняя порция: '+formatDate(data.backlog.last_finished,true)+' ЕКБ. ':'')),el('span','',`Ожидают повтора: ${counts.retry||0}. Нужна проверка причины: ${counts.needs_operator||0}.`));
 const bar=el('progress');bar.max=data.news.length;bar.value=ready;bar.setAttribute('aria-label','Прогресс разбора архива');progress.append(bar);
};
function failureText(raw){if(/429|routes unavailable|provider/i.test(raw))return 'Бесплатная модель временно недоступна или исчерпала лимит; будет повтор.';if(/OCR/i.test(raw))return 'PDF содержит скан и требует распознавания.';if(/too large|exceeds|chunk/i.test(raw))return 'Большой документ требует обработки частями.';if(/rejected|schema|evidence/i.test(raw))return 'Ответ модели не прошёл проверку качества; будет повтор.';return 'Не удалось завершить обработку. Подробности сохранены в журнале.';}
async function readServerMarkdown(n){if(n.markdownUrl&&/^materials\/[a-f0-9]+\.md$/.test(n.markdownUrl)){const r=await fetch(n.markdownUrl,{cache:'no-store'});if(!r.ok)throw Error('MD unavailable');return await r.text();}return markdown(n);}
$('#download').onclick=async()=>{try{downloadFile(await readServerMarkdown(current),'material-'+current.id+'.md');}catch{toast('Не удалось скачать MD. Попробуйте обновить страницу.');}};
$('#copy').onclick=async()=>{try{await navigator.clipboard.writeText(await readServerMarkdown(current));toast('Markdown скопирован');}catch{toast('Не удалось скопировать; используйте скачивание MD.');}};
const baseQualityView=qualityView;
qualityView=function(){baseQualityView();const b=data.backlog||{},c=b.counts||{};const p=panel('Обработка всего архива',`Готово: ${c.verified||0}. Ожидает первого разбора: ${c.pending||0}. Запланирован повтор: ${c.retry||0}. Нужна проверка причины: ${c.needs_operator||0}.`);if(b.last_finished)p.append(el('p','','Последняя завершённая порция: '+formatDate(b.last_finished,true)+' ЕКБ'));for(const n of data.news.filter(n=>n.processing?.error).slice(0,8)){const row=el('div','source-row');row.append(el('strong','',n.title),el('small','',failureText(n.processing.error)));p.append(row);}$('#qualityView').prepend(p);};
