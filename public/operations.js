'use strict';
const checkButton=el('button','button primary','Проверить новости');
$('.topbar').append(checkButton);
const checkDialog=el('dialog','check-modal');
checkDialog.setAttribute('aria-label','Запуск проверки новостей');
checkDialog.append(el('h2','','Проверить новости сейчас'),el('p','','Проверка работает в облаке. Пока серверный обработчик не развёрнут, запуск подтверждается в GitHub: войдите в свой аккаунт и нажмите Run workflow. Компьютер можно выключить после запуска.'));
checkDialog.append(link('Открыть запуск в GitHub ↗','https://github.com/dsxx1/cbr-regulatory-monitor/actions/workflows/check-news.yml','button primary'));
const closeCheck=el('button','button','Закрыть');closeCheck.onclick=()=>checkDialog.close();checkDialog.append(closeCheck);document.body.append(checkDialog);checkButton.onclick=()=>checkDialog.showModal();
const criteria=el('details','criteria');criteria.append(el('summary','','Как определяется важность'));
const criteriaList=el('ul');
for(const text of ['Важно — существенное изменение обязанностей, сроков, платежей, отчётности или риска остановки работы. В карточке должны быть основания и условия применимости.','Подготовиться — возможное изменение процесса или проект, требующий внимания; это ещё не действующая обязанность.','Учесть — небольшое организационное изменение.','Для сведения — статистика, мероприятия и материалы без изменения требований.','Не оценено — разбор не готов. Это не означает, что новость неважная.'])criteriaList.append(el('li','',text));
criteria.append(criteriaList);$('#feedView').prepend(criteria);
for(const p of ['high','medium','low','news']){const b=$(`#priorityFilters [data-priority="${p}"]`);b.replaceChildren(el('span','dot '+p),document.createTextNode(priorities[p]));}
$('.footnote').textContent='Важность определяется по последствиям и основаниям в полном тексте. Применимость к компании и срок исполнения проверяются отдельно. Неготовый разбор не считается проверенной новостью.';
const previousQuality=qualityView;
qualityView=function(){previousQuality();const h=data.llmHealth||{};const p=panel('Бесплатные LLM: фактические попытки',h.attempts?`${h.attempts} попыток: ${h.responses} ответов, ${h.failures} отказов. Ответ API ещё не означает качественный разбор.`:'Новый журнал ещё не накопил попыток. Данных для оценки стабильности пока нет.');p.classList.add('transport-log');p.append(el('p','',h.window||'Журнал начинается с включения измерений; прежние ошибки не восстановлены.'));for(const e of (h.events||[]).slice(-12).reverse()){const row=el('div','source-row');row.append(el('strong','',e.route),el('span','',`${e.status==='response'?'Ответ получен':'Неудачная попытка'} · ${(e.ms/1000).toFixed(1)} с · ${formatDate(e.at,true)}`));if(e.reason)row.append(el('small','',({rate_limit:'Лимит провайдера',timeout:'Истекло время ожидания',truncated:'Ответ обрезан',cost:'Цена не нулевая',provider_error:'Ошибка провайдера'})[e.reason]||'Ошибка'));p.append(row);}$('#qualityView').prepend(p);};
