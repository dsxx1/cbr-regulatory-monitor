<#
    Прототип наблюдателя за разъяснениями Банка России (ломбарды).

    Что делает за один прогон:
      1. читает дерево категорий и фиксирует появление новых подкатегорий;
      2. забирает разъяснения по наблюдаемым категориям;
      3. считает хеш нормализованного текста и сравнивает с прошлым прогоном;
      4. различает «новое», «изменилось», «без изменений»;
      5. отличает отказ источника от отсутствия изменений;
      6. сохраняет состояние и рисует отчёт.

    Прогон идемпотентен: повторный запуск на тех же данных даёт ноль новых.
    Зависимостей нет, только PowerShell 5.1.
#>

[CmdletBinding()]
param(
    [string] $StateFile  = "$PSScriptRoot\state.json",
    [string] $ReportFile = "$PSScriptRoot\report.html",
    [int[]]  $Categories = @(774, 378),
    [int]    $RootCategory = 426,
    [int]    $TimeoutSec = 30
)

$ErrorActionPreference = 'Stop'
$ApiBase = 'https://www.cbr.ru/ExplainApi/v1'
$RunAt   = Get-Date

# ---------------------------------------------------------------- вспомогательное

function Get-NormalizedText {
    # Хеш должен меняться от смысла, а не от вёрстки: снимаем теги,
    # разворачиваем сущности, схлопываем пробелы.
    param([string] $Html)
    if ([string]::IsNullOrEmpty($Html)) { return '' }
    $t = $Html -replace '<[^>]+>', ' '
    $t = $t -replace '&nbsp;', ' ' -replace '&laquo;', '"' -replace '&raquo;', '"'
    $t = $t -replace '&mdash;', '-' -replace '&ndash;', '-' -replace '&amp;', '&'
    $t = $t -replace '&quot;', '"' -replace '&lt;', '<' -replace '&gt;', '>'
    $t = $t -replace '[\s ]+', ' '
    return $t.Trim()
}

function Get-Sha16 {
    param([string] $Text)
    $sha = [System.Security.Cryptography.SHA256]::Create()
    try {
        $bytes = [System.Text.Encoding]::UTF8.GetBytes($Text)
        $hash  = $sha.ComputeHash($bytes)
        return -join ($hash[0..7] | ForEach-Object { $_.ToString('x2') })
    } finally { $sha.Dispose() }
}

function ConvertTo-HtmlSafe {
    param([string] $Text)
    if ($null -eq $Text) { return '' }
    return $Text.Replace('&','&amp;').Replace('<','&lt;').Replace('>','&gt;').Replace('"','&quot;')
}

function Get-Excerpt {
    param([string] $Text, [int] $Max = 220)
    if ($Text.Length -le $Max) { return $Text }
    return $Text.Substring(0, $Max).TrimEnd() + '…'
}

# ---------------------------------------------------------------- состояние

if (Test-Path $StateFile) {
    $raw   = Get-Content $StateFile -Raw -Encoding UTF8
    $state = $raw | ConvertFrom-Json
    $isFirstRun = $false
} else {
    $state = [PSCustomObject]@{ lastRun = $null; runCount = 0; items = [PSCustomObject]@{}; subCategories = @() }
    $isFirstRun = $true
}

# PSCustomObject неудобен для поиска — переносим в хеш-таблицу на время прогона.
$known = @{}
if ($state.items) {
    foreach ($p in $state.items.PSObject.Properties) { $known[$p.Name] = $p.Value }
}

$sourceLog = @()   # журнал источников: отказ обязан отличаться от «изменений нет»
$new       = @()
$changed   = @()
$unchanged = 0

# ---------------------------------------------------------------- дерево категорий

$subCatsNow = @()
try {
    $tree = Invoke-RestMethod -Uri "$ApiBase/categories/$RootCategory" -TimeoutSec $TimeoutSec
    foreach ($c in @($tree)) { $subCatsNow += [int]$c.id }
    $sourceLog += [PSCustomObject]@{ name = "Дерево категорий $RootCategory"; status = 'ok'; detail = "подкатегорий: $($subCatsNow.Count)" }
} catch {
    $sourceLog += [PSCustomObject]@{ name = "Дерево категорий $RootCategory"; status = 'ошибка'; detail = $_.Exception.Message }
}

$knownSubs = @()
if ($state.subCategories) { $knownSubs = @($state.subCategories | ForEach-Object { [int]$_ }) }
$newSubs = @($subCatsNow | Where-Object { $knownSubs -notcontains $_ })
if ($isFirstRun) { $newSubs = @() }   # на первом прогоне всё «новое», это не сигнал

# ---------------------------------------------------------------- разъяснения

foreach ($cat in $Categories) {
    try {
        # Invoke-RestMethod в PS 5.1 отдаёт JSON-массив ОДНИМ объектом, поэтому
        # @(вызов) заворачивает его вместо разворачивания. Сначала в переменную.
        $resp  = Invoke-RestMethod -Uri "$ApiBase/categories/$cat/explains" -TimeoutSec $TimeoutSec
        $items = @($resp)
        $sourceLog += [PSCustomObject]@{ name = "Разъяснения, категория $cat"; status = 'ok'; detail = "записей: $($items.Count)" }
    } catch {
        # Ключевое правило: источник не ответил — это событие, а не тишина.
        $sourceLog += [PSCustomObject]@{ name = "Разъяснения, категория $cat"; status = 'ошибка'; detail = $_.Exception.Message }
        continue
    }

    foreach ($it in $items) {
        $key  = "$cat`:$($it.id)"
        $q    = Get-NormalizedText $it.questionHtml
        $a    = Get-NormalizedText $it.answerHtml
        $hash = Get-Sha16 "$q`n$a"

        $record = [PSCustomObject]@{
            key          = $key
            id           = $it.id
            categoryId   = $cat
            question     = $q
            answer       = $a
            hash         = $hash
            modification = $it.modification
        }

        if (-not $known.ContainsKey($key)) {
            $known[$key] = [PSCustomObject]@{
                hash = $hash; modification = $it.modification
                firstSeen = $RunAt.ToString('o'); lastSeen = $RunAt.ToString('o')
                question = (Get-Excerpt $q 300)
            }
            if (-not $isFirstRun) { $new += $record } else { $unchanged++ }
        }
        elseif ($known[$key].hash -ne $hash) {
            # Содержание поменялось — это повод для пересмотра карточки.
            $record | Add-Member -NotePropertyName oldHash -NotePropertyValue $known[$key].hash
            $record | Add-Member -NotePropertyName oldModification -NotePropertyValue $known[$key].modification
            $changed += $record
            $known[$key].hash = $hash
            $known[$key].modification = $it.modification
            $known[$key].lastSeen = $RunAt.ToString('o')
            $known[$key].question = (Get-Excerpt $q 300)
        }
        else {
            $unchanged++
            $known[$key].lastSeen = $RunAt.ToString('o')
        }
    }
}

# ---------------------------------------------------------------- сохранение состояния

$itemsOut = [PSCustomObject]@{}
foreach ($k in ($known.Keys | Sort-Object)) {
    $itemsOut | Add-Member -NotePropertyName $k -NotePropertyValue $known[$k]
}

$runCount = 1
if ($state.runCount) { $runCount = [int]$state.runCount + 1 }

$newState = [PSCustomObject]@{
    lastRun       = $RunAt.ToString('o')
    runCount      = $runCount
    subCategories = $subCatsNow
    items         = $itemsOut
}
$newState | ConvertTo-Json -Depth 6 | Set-Content -Path $StateFile -Encoding UTF8

# ---------------------------------------------------------------- отчёт

$failed = @($sourceLog | Where-Object { $_.status -ne 'ok' })

$cards = ''
foreach ($r in $new) {
    $cards += @"
      <article class="card new">
        <div class="tag">Новое</div>
        <h3>$(ConvertTo-HtmlSafe (Get-Excerpt $r.question 200))</h3>
        <p>$(ConvertTo-HtmlSafe (Get-Excerpt $r.answer 320))</p>
        <footer>категория $($r.categoryId) · id $($r.id) · изменено $($r.modification) · хеш $($r.hash)</footer>
      </article>
"@
}
foreach ($r in $changed) {
    $cards += @"
      <article class="card changed">
        <div class="tag">Изменилось</div>
        <h3>$(ConvertTo-HtmlSafe (Get-Excerpt $r.question 200))</h3>
        <p>$(ConvertTo-HtmlSafe (Get-Excerpt $r.answer 320))</p>
        <footer>категория $($r.categoryId) · id $($r.id) · хеш $($r.oldHash) &rarr; $($r.hash) · изменено $($r.oldModification) &rarr; $($r.modification)</footer>
      </article>
"@
}
if ($cards -eq '') {
    if ($failed.Count -gt 0) {
        $cards = '<div class="empty warn">Изменений не обнаружено, но часть источников не ответила. Это не то же самое, что «изменений нет».</div>'
    } elseif ($isFirstRun) {
        $cards = '<div class="empty">Первый прогон: база наполнена, всё записано как исходное состояние. Сигналы начнутся со следующего запуска.</div>'
    } else {
        $cards = '<div class="empty">Изменений нет. Все источники ответили.</div>'
    }
}

$srcRows = ''
foreach ($s in $sourceLog) {
    $cls = 'ok'
    if ($s.status -ne 'ok') { $cls = 'err' }
    $srcRows += "<tr><td>$(ConvertTo-HtmlSafe $s.name)</td><td class=""$cls"">$(ConvertTo-HtmlSafe $s.status)</td><td>$(ConvertTo-HtmlSafe $s.detail)</td></tr>`n"
}

$subsNote = ''
if ($newSubs.Count -gt 0) {
    $subsNote = "<div class=""empty warn"">Появились новые подкатегории: $($newSubs -join ', '). Их нужно добавить в наблюдение.</div>"
}

$html = @"
<!doctype html>
<html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Мониторинг разъяснений Банка России — ломбарды</title>
<style>
  :root { --bg:#fbfbfa; --fg:#1a1a18; --mut:#6b6b66; --line:#e3e3df; --card:#fff;
          --new:#1f7a4d; --chg:#9a6700; --err:#b42318; }
  @media (prefers-color-scheme: dark) {
    :root { --bg:#16161a; --fg:#e8e8e4; --mut:#9a9a94; --line:#2c2c32; --card:#1e1e24;
            --new:#4ac585; --chg:#e0a72b; --err:#f2776a; }
  }
  * { box-sizing:border-box }
  body { margin:0; padding:2rem 1.25rem; background:var(--bg); color:var(--fg);
         font:15px/1.6 -apple-system,Segoe UI,Roboto,sans-serif }
  .wrap { max-width:940px; margin:0 auto }
  h1 { font-size:1.45rem; margin:0 0 .35rem }
  .sub { color:var(--mut); margin:0 0 1.75rem; font-size:.9rem }
  .stats { display:flex; flex-wrap:wrap; gap:.75rem; margin-bottom:1.75rem }
  .stat { flex:1 1 130px; background:var(--card); border:1px solid var(--line);
          border-radius:10px; padding:.85rem 1rem }
  .stat b { display:block; font-size:1.6rem; line-height:1.2 }
  .stat span { color:var(--mut); font-size:.8rem }
  h2 { font-size:1rem; text-transform:uppercase; letter-spacing:.06em;
       color:var(--mut); margin:2rem 0 .85rem; font-weight:600 }
  .card { background:var(--card); border:1px solid var(--line); border-left-width:3px;
          border-radius:8px; padding:1rem 1.15rem; margin-bottom:.75rem }
  .card.new { border-left-color:var(--new) }
  .card.changed { border-left-color:var(--chg) }
  .tag { font-size:.7rem; text-transform:uppercase; letter-spacing:.08em; font-weight:700 }
  .new .tag { color:var(--new) } .changed .tag { color:var(--chg) }
  .card h3 { font-size:.98rem; margin:.4rem 0 .5rem; font-weight:600 }
  .card p { margin:0 0 .6rem; color:var(--fg); opacity:.85; font-size:.9rem }
  .card footer { font-size:.75rem; color:var(--mut); font-family:ui-monospace,Consolas,monospace }
  .empty { background:var(--card); border:1px dashed var(--line); border-radius:8px;
           padding:1.1rem 1.15rem; color:var(--mut) }
  .empty.warn { border-color:var(--chg); color:var(--chg) }
  table { width:100%; border-collapse:collapse; font-size:.85rem }
  th,td { text-align:left; padding:.55rem .6rem; border-bottom:1px solid var(--line) }
  th { color:var(--mut); font-weight:600; font-size:.75rem; text-transform:uppercase; letter-spacing:.05em }
  td.ok { color:var(--new) } td.err { color:var(--err); font-weight:600 }
  .foot { margin-top:2.5rem; padding-top:1rem; border-top:1px solid var(--line);
          color:var(--mut); font-size:.8rem }
</style></head><body><div class="wrap">

<h1>Мониторинг разъяснений Банка России</h1>
<p class="sub">Периметр: ломбарды. Прогон №$runCount от $($RunAt.ToString('dd.MM.yyyy HH:mm:ss'))</p>

<div class="stats">
  <div class="stat"><b>$($new.Count)</b><span>новых</span></div>
  <div class="stat"><b>$($changed.Count)</b><span>изменилось</span></div>
  <div class="stat"><b>$unchanged</b><span>без изменений</span></div>
  <div class="stat"><b>$($known.Count)</b><span>под наблюдением</span></div>
  <div class="stat"><b>$($failed.Count)</b><span>отказов источников</span></div>
</div>

$subsNote

<h2>Сигналы этого прогона</h2>
$cards

<h2>Состояние источников</h2>
<table><thead><tr><th>Источник</th><th>Статус</th><th>Подробности</th></tr></thead>
<tbody>
$srcRows
</tbody></table>

<div class="foot">
  Прототип решающего контура. Отслеживается хеш нормализованного текста, а не вёрстка,
  поэтому переформатирование страницы сигналом не считается.
  Поле <code>modification</code> — время правки разъяснения, а не дата вступления требования в силу;
  дату вступления подтверждает человек.
  Состояние: <code>$StateFile</code>
</div>

</div></body></html>
"@

$html | Set-Content -Path $ReportFile -Encoding UTF8

# ---------------------------------------------------------------- итог в консоль

Write-Host ""
Write-Host "Прогон №$runCount завершён в $($RunAt.ToString('HH:mm:ss'))" -ForegroundColor Cyan
Write-Host "  новых:            $($new.Count)"
Write-Host "  изменилось:       $($changed.Count)"
Write-Host "  без изменений:    $unchanged"
Write-Host "  под наблюдением:  $($known.Count)"
if ($failed.Count -gt 0) {
    Write-Host "  ОТКАЗОВ ИСТОЧНИКОВ: $($failed.Count)" -ForegroundColor Red
    foreach ($f in $failed) { Write-Host "    - $($f.name): $($f.detail)" -ForegroundColor Red }
}
Write-Host "  отчёт:            $ReportFile"
Write-Host ""
