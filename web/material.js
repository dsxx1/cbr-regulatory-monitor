'use strict';
const importanceMeaning={unknown:'Анализ не выполнен. Важность не определена.',high:'Приоритетная проверка влияния на операции ломбарда. Не означает автоматического изменения регламентов.',medium:'Нужно оценить и подготовить изменения; немедленное исполнение не установлено.',low:'Низкое ожидаемое влияние. Достаточно планового наблюдения.',news:'Информационный материал. Практические действия по источнику не выявлены.'};
const eventNames={инициатива:'Инициатива',проект:'Проект',принятый_акт:'Принятый акт',новость:'Новость',неясно:'Статус требует проверки'};
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
 $('#download').disabled=!ready;$('#copy').disabled=!ready;
 $('#download').textContent=ready?'↓ Разбор .md':'MD-разбор не готов';
 $('#download').title=ready?'Скачать содержательный разбор':'Для экспорта разбора требуется полный текст и проверенный анализ';
 const root=$('#readerContent');
 if(!ready){
   if(readerTab==='markdown'){root.replaceChildren(el('p','callout','MD-разбор ещё не создан. Доступны только реквизиты или исходный текст. Важность не определена.'));}
   else if(readerTab==='summary'){const info=el('div','importance-box');info.append(el('strong','','Важность не определена'),el('p','','Цвет не назначается по заголовку. Сначала нужно получить полный текст и разобрать влияние на работу.'));root.prepend(info);}
   return;
 }
 if(readerTab!=='summary')return;
 root.replaceChildren();
 const intro=el('div','brief-intro');intro.append(pill(eventNames[b.event_status]||b.event_status),el('p','lead',b.summary));root.append(intro);
 const importance=el('div','importance-box '+n.priority);importance.append(el('strong','',priorities[n.priority]+' важность'),el('p','',b.priority_reason),el('small','',importanceMeaning[n.priority]));root.append(importance);
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
renderStats=function(){baseStats();const cells=$('#stats').children;if(cells[1]){cells[1].querySelector('label').textContent='Важных после разбора';cells[1].querySelector('small').textContent='С объяснением влияния';}if(cells[3]){cells[3].querySelector('label').textContent='Проверено разделов';cells[3].querySelector('small').textContent='Данные успешно загружены';}};
