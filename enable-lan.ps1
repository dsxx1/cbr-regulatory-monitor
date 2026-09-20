$ErrorActionPreference = 'Stop'
$name = 'Regulatory Monitor LAN 8787'
$resultPath = Join-Path $PSScriptRoot 'out\lan-access-status.json'
try {
    if (-not (Get-NetFirewallRule -DisplayName $name -ErrorAction SilentlyContinue)) {
        New-NetFirewallRule -DisplayName $name -Direction Inbound -Action Allow -Protocol TCP -LocalPort 8787 -RemoteAddress LocalSubnet -Profile Domain,Private | Out-Null
    }
    $rule = Get-NetFirewallRule -DisplayName $name -ErrorAction Stop
    @{ok=$true;enabled=[string]$rule.Enabled;profile=[string]$rule.Profile;checked=(Get-Date).ToString('o')} | ConvertTo-Json | Set-Content -LiteralPath $resultPath -Encoding UTF8
} catch {
    @{ok=$false;error=$_.Exception.Message;checked=(Get-Date).ToString('o')} | ConvertTo-Json | Set-Content -LiteralPath $resultPath -Encoding UTF8
    exit 1
}
