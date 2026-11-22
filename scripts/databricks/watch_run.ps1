# Wait for a Databricks job run to finish, then print each task's state and error.
# Usage: powershell -File scripts\databricks\watch_run.ps1 -RunId <id> [-Profile datathon]
param([Parameter(Mandatory = $true)][string]$RunId, [string]$Profile = "datathon", [int]$MaxMinutes = 90)
$db = (Get-Command databricks -ErrorAction SilentlyContinue).Source
if (-not $db) { $db = Get-ChildItem "$env:LOCALAPPDATA\Microsoft\WinGet\Packages" -Recurse -Filter databricks.exe | Select-Object -First 1 -ExpandProperty FullName }
$deadline = (Get-Date).AddMinutes($MaxMinutes)
do {
    $run = & $db jobs get-run $RunId --profile $Profile -o json | ConvertFrom-Json
    $life = $run.state.life_cycle_state
    if ($life -in @("TERMINATED", "SKIPPED", "INTERNAL_ERROR")) { break }
    Start-Sleep -Seconds 30
} while ((Get-Date) -lt $deadline)

"Run $RunId : $($run.state.life_cycle_state) / $($run.state.result_state)  $($run.run_page_url)"
foreach ($t in $run.tasks) {
    $secs = [math]::Round(($t.end_time - $t.start_time) / 1000)
    "{0,-6} {1,-12} {2,5}s" -f $t.task_key, ($t.state.result_state + $t.state.life_cycle_state.Substring(0, 0)), $secs
    if ($t.state.result_state -and $t.state.result_state -ne "SUCCESS") {
        $out = & $db jobs get-run-output $t.run_id --profile $Profile -o json 2>$null | ConvertFrom-Json
        if ($out.error) { "    error: " + ($out.error -replace "\s+", " ").Substring(0, [math]::Min(600, $out.error.Length)) }
        if ($out.error_trace) { "    trace (last lines):"; ($out.error_trace -split "`n" | Select-Object -Last 12) | ForEach-Object { "      $_" } }
        if ($t.state.state_message) { "    message: $($t.state.state_message)" }
    }
}
