# OpenJev HTTPS tunnel

Verified endpoint: **https://0e3afafa81da.ngrok.app**. The eight-hour session
expires **September 27, 2026, 05:15:56 EDT** (`09:15:56 UTC`).
[Saved proof](../artifacts/jev-openjev-ngrok-proof.json) records unauthenticated
and wrong-password requests returning 401, authenticated health returning 200,
invalid JSON payload validation returning 422, and one actual local decision
returning 200 in 750 ms. This used synthetic facts; no robot was actuated.

HTTP Basic authentication uses username **`relay`** and a generated password in
the ignored/private `.state/ngrok-openjev/client-credentials.json`, whose ACL
permits only the current Windows user and SYSTEM. Do not print,
commit or place that password in frontend code, URLs or browser storage. Use
server-to-server HTTPS requests. `GET /health` reports worker status;
`POST /decide` accepts JSON. The existing browser `Origin` rejection remains.

## Client examples

From the repository root, read credentials into memory without displaying them:

```powershell
$ngrokUrl = 'https://0e3afafa81da.ngrok.app'
$ngrokSecret = Get-Content -LiteralPath .state/ngrok-openjev/client-credentials.json -Raw | ConvertFrom-Json
$ngrokPair = 'relay:' + $ngrokSecret.password
$ngrokHeaders = @{ Authorization = 'Basic ' + [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($ngrokPair)) }
Invoke-RestMethod -Uri "$ngrokUrl/health" -Headers $ngrokHeaders -MaximumRedirection 0 -TimeoutSec 10
```

Optional: one inference on simulated dry controller facts (no automatic retry):

```powershell
$ngrokState = @{ health='fresh'; local_alarm=$false; water_threshold_exceeded=$false; simulated=$true; actuation_enabled=$false } | ConvertTo-Json -Compress
$ngrokBody = @{
    state=$ngrokState
    choices=@('hold', 'request_evidence', 'escalate_gemini', 'continue_monitoring')
    operation_id=('remote-' + [guid]::NewGuid().ToString('N'))
    timeout_seconds=5.0
} | ConvertTo-Json -Compress
Invoke-RestMethod -Method Post -Uri "$ngrokUrl/decide" -Headers $ngrokHeaders -ContentType application/json -Body $ngrokBody -MaximumRedirection 0 -TimeoutSec 10
Remove-Variable ngrokSecret, ngrokPair, ngrokHeaders
```

If only checking health, run the final `Remove-Variable` line afterward. Do not
log authorization headers. A timeout does not cancel GPU work; inspect health
before deciding whether to submit another distinct operation. The worker allows
one inference at a time and retains its existing 100-attempt session limit.

## Stop this tunnel

The supervisor stops its own ngrok child at expiry. To stop it earlier, validate
the saved PID, exact executable, parent supervisor, script and creation window:

```powershell
$ngrokSession = Get-Content -LiteralPath .state/ngrok-openjev/session.json -Raw | ConvertFrom-Json
$ngrokChild = Get-CimInstance Win32_Process -Filter "ProcessId = $([int]$ngrokSession.ngrok_pid)"
$ngrokSupervisor = Get-CimInstance Win32_Process -Filter "ProcessId = $([int]$ngrokSession.supervisor_pid)"
if (-not $ngrokChild -or -not $ngrokSupervisor) { throw 'Recorded tunnel process is absent; nothing stopped.' }
$ngrokStart = [datetimeoffset]::Parse($ngrokSession.started_at).UtcDateTime
$ngrokCreationDelta = ($ngrokChild.CreationDate.ToUniversalTime() - $ngrokStart).TotalSeconds
$ngrokRunner = (Resolve-Path -LiteralPath .state/ngrok-openjev/run-tunnel.py).Path
$ngrokRunnerPattern = '(?:^|\s)"?(?:' + [regex]::Escape($ngrokRunner) + '|\.state[\\/]ngrok-openjev[\\/]run-tunnel\.py)"?(?:\s|$)'
if ($ngrokChild.ExecutablePath -ine 'C:\ProgramData\chocolatey\lib\ngrok\tools\ngrok.exe' -or
    $ngrokChild.ParentProcessId -ne [int]$ngrokSession.supervisor_pid -or
    $ngrokCreationDelta -lt 0 -or $ngrokCreationDelta -gt 30 -or
    $ngrokSupervisor.CommandLine -notmatch $ngrokRunnerPattern) {
    throw 'Process identity did not match this tunnel; nothing stopped.'
}
Stop-Process -Id ([int]$ngrokSession.ngrok_pid)
```

This stops only the tunnel. The local OpenJev worker at `127.0.0.1:8770` remains
running; its separate stop instructions are in [the local guide](jev-openjev.md).
Restart deliberately through `.venv\Scripts\python.exe .state/ngrok-openjev/run-tunnel.py`.
Its preflight verifies the local worker and refuses an occupied agent port 4041
before reserving funds. A new session receives its own expiry and reservation.

## Cost and capture scope

The canonical spending ledger holds **USD 1.00** for this session under
`ngrok-openjev-20260927T011556Z`; actual billed cost remains unverified. Stopping
does not reconcile or release that hold. No plan was purchased or changed, and
the reported existing Pro subscription was not independently verified.

Installed ngrok **3.8.0** works here with config version 2 and legacy
`basic_auth`. Local request inspection is disabled. This does **not** establish
that account-wide cloud Full Capture is disabled; those settings were not
inspected. Treat tunneled content as passing through ngrok infrastructure.
