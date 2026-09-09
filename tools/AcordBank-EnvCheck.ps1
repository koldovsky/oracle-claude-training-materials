#Requires -Version 5.1
<#
    AcordBank - workstation readiness check for the Claude Code + Oracle training.

    This script ONLY reads and tests connectivity. It installs nothing, alters
    no setting, and needs no administrator rights. The single thing it writes
    is its own report file on your Desktop - the file you send back to us.

    Run:
        powershell -ExecutionPolicy Bypass -File .\AcordBank-EnvCheck.ps1

    Optional:
        -Mode cloud   check only the cloud-container variant (nothing installed locally)
        -Mode local   check only the local-installation variant
        -TimeoutSec   per-request timeout, default 10

    Note: all text is deliberately plain ASCII English. Windows PowerShell 5.1
    renders non-ASCII differently depending on the console code page, and a
    garbled report is worse than an English one.
#>

[CmdletBinding()]
param(
    [ValidateSet('cloud','local','all')]
    [string]$Mode = 'all',

    [int]$TimeoutSec = 10,

    [string]$OutFile
)

$ErrorActionPreference = 'Continue'

# Without this, PowerShell 5.1 on some machines still negotiates TLS 1.0 and
# every HTTPS check fails as if the network were blocked.
try {
    [Net.ServicePointManager]::SecurityProtocol =
        [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
} catch { }

$Script:Results = New-Object System.Collections.ArrayList

# Missing Java/SQLcl is only a blocker if the local variant was actually chosen.
# In the default cloud setup nothing is installed on the workstation, so red
# FAIL lines there would alarm the reader over something that is fine.
$Script:SoftMissing = $(if ($Mode -eq 'local') { 'FAIL' } else { 'WARN' })
$Script:NotInstalled = 'not installed'

function Add-Result {
    param($Group, $Name, $Status, $Detail)

    $null = $Script:Results.Add([PSCustomObject]@{
        Group  = $Group
        Name   = $Name
        Status = $Status
        Detail = $Detail
    })

    switch ($Status) {
        'OK'    { $tag = '[ OK ]'; $color = 'Green'  }
        'WARN'  { $tag = '[WARN]'; $color = 'Yellow' }
        'FAIL'  { $tag = '[FAIL]'; $color = 'Red'    }
        default { $tag = '[    ]'; $color = 'Gray'   }
    }
    Write-Host ("  {0} {1,-30} {2}" -f $tag, $Name, $Detail) -ForegroundColor $color
}

function Write-Section {
    param($Title)
    Write-Host ""
    Write-Host $Title -ForegroundColor Cyan
    Write-Host ("-" * 74) -ForegroundColor DarkGray
}

# --- test primitives -------------------------------------------------------

function Test-Https {
    <#  Tests HTTPS rather than a raw TCP socket on purpose. Corporate traffic
        usually goes through a proxy, so a direct TCP connect to :443 fails
        even when the site is perfectly reachable. Invoke-WebRequest honours
        the system proxy, so it answers the real question.
        Any HTTP response - including 401/403/404 - proves connectivity.     #>
    param([string]$Url, [int]$Timeout = 10)

    try {
        $r = Invoke-WebRequest -Uri $Url -Method Head -UseBasicParsing -TimeoutSec $Timeout -ErrorAction Stop
        return @{ Ok = $true; Detail = ("HTTP {0}" -f [int]$r.StatusCode) }
    }
    catch [System.Net.WebException] {
        $ex = $_.Exception

        if ($null -ne $ex.Response) {
            return @{ Ok = $true; Detail = ("HTTP {0}" -f [int]$ex.Response.StatusCode) }
        }

        # A TLS failure still means packets reached the far side. That is a
        # different problem from a blocked port, and worth reporting as such:
        # it usually indicates TLS inspection on the corporate proxy.
        if ($ex.Status -eq [System.Net.WebExceptionStatus]::TrustFailure -or
            $ex.Message -match 'SSL|TLS|trust relationship|secure channel') {
            return @{ Ok = $true; Warn = $true; Detail = "reachable, but TLS error (TLS inspection?)" }
        }

        # Same reasoning as in Test-TcpPort: name the cause, because each one
        # points the network team at a different rule.
        switch ($ex.Status) {
            'NameResolutionFailure' { return @{ Ok = $false; Detail = "DNS: host name does not resolve" } }
            'Timeout'               { return @{ Ok = $false; Detail = "timed out - firewall drops the packets" } }
            'ConnectFailure'        { return @{ Ok = $false; Detail = "cannot connect - port blocked or refused" } }
            'ProxyNameResolutionFailure' { return @{ Ok = $false; Detail = "the configured proxy name does not resolve" } }
            default                 { return @{ Ok = $false; Detail = $ex.Status.ToString() } }
        }
    }
    catch {
        return @{ Ok = $false; Detail = $_.Exception.Message }
    }
}

function Test-TcpPort {
    <#  For port 1522 a proxy does not help - it must be a direct TCP path.

        The three failure modes below need three different fixes on the
        network side, so they are reported separately rather than lumped
        together as "blocked":
          - name does not resolve      -> DNS / split-horizon issue
          - no answer at all           -> firewall silently drops packets
          - actively refused           -> packets DO get through, port shut  #>
    param([string]$HostName, [int]$Port, [int]$TimeoutMs = 6000)

    try {
        $null = [System.Net.Dns]::GetHostAddresses($HostName)
    } catch {
        return @{ Ok = $false; Detail = "DNS: host name does not resolve" }
    }

    $client = New-Object System.Net.Sockets.TcpClient
    try {
        $iar  = $client.BeginConnect($HostName, $Port, $null, $null)
        $done = $iar.AsyncWaitHandle.WaitOne($TimeoutMs, $false)

        if (-not $done) {
            return @{ Ok = $false; Detail = ("no answer in {0}s - firewall drops the packets" -f [int]($TimeoutMs / 1000)) }
        }

        # EndConnect surfaces the real reason instead of a bare "not connected".
        $client.EndConnect($iar)

        if ($client.Connected) {
            return @{ Ok = $true; Detail = "connected" }
        }
        return @{ Ok = $false; Detail = "connection did not complete" }
    }
    catch [System.Net.Sockets.SocketException] {
        switch ($_.Exception.SocketErrorCode) {
            'ConnectionRefused' { return @{ Ok = $false; Detail = "refused - host is reachable, but the port is closed" } }
            'HostNotFound'      { return @{ Ok = $false; Detail = "DNS: host name does not resolve" } }
            'TimedOut'          { return @{ Ok = $false; Detail = "timed out - firewall drops the packets" } }
            'HostUnreachable'   { return @{ Ok = $false; Detail = "host unreachable - no route" } }
            'NetworkUnreachable'{ return @{ Ok = $false; Detail = "network unreachable - no route" } }
            default             { return @{ Ok = $false; Detail = ("socket error: {0}" -f $_.Exception.SocketErrorCode) } }
        }
    }
    catch {
        $inner = $_.Exception.InnerException
        if ($inner -is [System.Net.Sockets.SocketException]) {
            return @{ Ok = $false; Detail = ("socket error: {0}" -f $inner.SocketErrorCode) }
        }
        return @{ Ok = $false; Detail = $_.Exception.Message }
    }
    finally {
        try { $client.Close() } catch { }
    }
}

function Test-WebSocket {
    <#  This is the single most fragile item for the cloud variant, and the
        reason it gets its own check: TLS-inspecting corporate proxies very
        often pass ordinary HTTPS and still kill WebSocket upgrades. A plain
        HEAD request would report "all clear" and the codespace would still
        refuse to open on training day.

        The probe sends a real "Upgrade: websocket" request to a codespace-style
        subdomain that does not exist. GitHub answering its own 404 proves the
        upgrade request crossed the proxy intact and reached GitHub's routing.

        What this does NOT prove: that a full handshake completes. No GitHub
        endpoint completes one without authentication, so that last step can
        only be confirmed by opening a real environment.                      #>
    param([string]$Uri, [int]$TimeoutMs = 8000)

    try {
        $ws = New-Object System.Net.WebSockets.ClientWebSocket
    } catch {
        return @{ Ok = $true; Warn = $true; Detail = "cannot be tested on this machine (.NET too old)" }
    }

    $cts = New-Object System.Threading.CancellationTokenSource
    $cts.CancelAfter($TimeoutMs)

    try {
        $ws.ConnectAsync([Uri]$Uri, $cts.Token).GetAwaiter().GetResult()
        return @{ Ok = $true; Detail = "handshake completed" }
    }
    catch {
        $e = $_.Exception
        while ($e.InnerException) { $e = $e.InnerException }
        $msg = ($e.Message -replace "`r?`n", ' ')

        if ($msg -match '\((\d{3})\)') {
            $code = [int]$Matches[1]
            if ($code -eq 404) {
                return @{ Ok = $true; Detail = "upgrade request reached GitHub (404 = no such codespace, expected)" }
            }
            return @{ Ok = $true; Warn = $true; Detail = ("answered HTTP {0} - possibly a proxy refusing the upgrade" -f $code) }
        }
        if ($msg -match 'could not be resolved') {
            return @{ Ok = $false; Detail = "DNS: codespace subdomains do not resolve" }
        }
        if ($msg -match 'canceled|aborted|timed out') {
            return @{ Ok = $false; Detail = ("no answer in {0}s - WebSocket appears to be blocked" -f [int]($TimeoutMs / 1000)) }
        }
        return @{ Ok = $false; Detail = $msg }
    }
    finally {
        try { $ws.Dispose() }  catch { }
        try { $cts.Dispose() } catch { }
    }
}

function Get-ToolOutput {
    <#  cmd /c is needed because java prints its version to stderr, and
        redirecting a native command's stderr inside PowerShell 5.1 wraps
        each line in an ErrorRecord and breaks the exit code.               #>
    param([string]$CommandLine)
    try {
        $out = & cmd /c "$CommandLine 2>&1"
        return ($out | Out-String).Trim()
    } catch {
        return ""
    }
}

function Test-Tool {
    param(
        [string]$Exe,
        [string]$Label,
        [string]$CommandLine,
        [scriptblock]$Parse,
        [int]$MinMajor = 0,
        [string]$MinNote = ""
    )

    if ($null -eq (Get-Command $Exe -ErrorAction SilentlyContinue)) {
        Add-Result 'Software' $Label $Script:SoftMissing $Script:NotInstalled
        return
    }

    $raw = Get-ToolOutput $CommandLine
    if ([string]::IsNullOrWhiteSpace($raw)) {
        Add-Result 'Software' $Label 'WARN' "found, but version could not be read"
        return
    }

    $parsed = & $Parse $raw
    $ver    = $parsed.Version
    $major  = [int]$parsed.Major

    if ($MinMajor -gt 0 -and $major -gt 0 -and $major -lt $MinMajor) {
        Add-Result 'Software' $Label 'WARN' ("{0}  ({1})" -f $ver, $MinNote)
    } else {
        Add-Result 'Software' $Label 'OK' $ver
    }
}

# --- start -----------------------------------------------------------------

Write-Host ""
Write-Host "  AcordBank - workstation readiness check" -ForegroundColor White
Write-Host "  Claude Code + Oracle training" -ForegroundColor DarkGray
Write-Host ""
Write-Host "  Nothing is installed and no setting is changed." -ForegroundColor DarkGray
Write-Host "  The only file written is the report, saved to your Desktop." -ForegroundColor DarkGray
Write-Host "  This takes about a minute." -ForegroundColor DarkGray

$doCloud = ($Mode -eq 'all' -or $Mode -eq 'cloud')
$doLocal = ($Mode -eq 'all' -or $Mode -eq 'local')

# --- 1. machine ------------------------------------------------------------

Write-Section "1. Workstation"

try {
    $os = Get-CimInstance Win32_OperatingSystem -ErrorAction Stop
    Add-Result 'System' 'Operating system' 'OK' ("{0} ({1})" -f $os.Caption.Trim(), $os.OSArchitecture)
} catch {
    Add-Result 'System' 'Operating system' 'WARN' "could not query WMI"
}

Add-Result 'System' 'PowerShell' 'OK' $PSVersionTable.PSVersion.ToString()

try {
    $probe = "https://github.com"
    $px    = [System.Net.WebRequest]::GetSystemWebProxy().GetProxy($probe)
    if ($null -ne $px -and $px.AbsoluteUri.TrimEnd('/') -ne $probe.TrimEnd('/')) {
        Add-Result 'System' 'HTTP proxy' 'OK' ("in use: {0}" -f $px.Authority)
    } else {
        Add-Result 'System' 'HTTP proxy' 'OK' "none - direct egress"
    }
} catch {
    Add-Result 'System' 'HTTP proxy' 'WARN' "could not determine"
}

# --- 2. network: cloud variant ---------------------------------------------

if ($doCloud) {
    Write-Section "2. Network - cloud container (our recommended setup)"

    $cloudEndpoints = @(
        @{ Url = "https://github.com";     Name = "github.com" }
        @{ Url = "https://api.github.com"; Name = "api.github.com" }
        @{ Url = "https://github.dev";     Name = "github.dev" }
    )

    foreach ($e in $cloudEndpoints) {
        $r = Test-Https -Url $e.Url -Timeout $TimeoutSec
        if ($r.Ok -and $r.Warn) { Add-Result 'Net-Cloud' $e.Name 'WARN' $r.Detail }
        elseif ($r.Ok)          { Add-Result 'Net-Cloud' $e.Name 'OK'   $r.Detail }
        else                    { Add-Result 'Net-Cloud' $e.Name 'FAIL' $r.Detail }
    }

    # The working environment is served from a per-codespace subdomain, not from
    # the apex. Wildcard firewall rules and proxy policies routinely treat the
    # two differently, so the subdomain is probed separately.
    $wsProbe = "wss://acordbank-ws-probe.app.github.dev/"
    $w = Test-WebSocket -Uri $wsProbe -TimeoutMs ($TimeoutSec * 1000)
    if ($w.Ok -and $w.Warn) { Add-Result 'Net-Cloud' '*.app.github.dev (WebSocket)' 'WARN' $w.Detail }
    elseif ($w.Ok)          { Add-Result 'Net-Cloud' '*.app.github.dev (WebSocket)' 'OK'   $w.Detail }
    else                    { Add-Result 'Net-Cloud' '*.app.github.dev (WebSocket)' 'FAIL' $w.Detail }

    Write-Host ""
    Write-Host "  Note on the last line: it sends a genuine WebSocket upgrade request to a" -ForegroundColor DarkGray
    Write-Host "  codespace-style address, so a reply from GitHub proves the request survives" -ForegroundColor DarkGray
    Write-Host "  your proxy. A completed handshake needs a real codespace and login, so the" -ForegroundColor DarkGray
    Write-Host "  final confirmation still happens when we open the environment together." -ForegroundColor DarkGray
}

# --- 3. network: local variant ---------------------------------------------

if ($doLocal) {
    Write-Section "3. Network - local installation (only if you choose that variant)"

    $ora = Test-TcpPort -HostName "adb.eu-frankfurt-1.oraclecloud.com" -Port 1522
    if ($ora.Ok) {
        Add-Result 'Net-Local' 'Oracle DB, port 1522/TCP' 'OK' $ora.Detail
    } else {
        Add-Result 'Net-Local' 'Oracle DB, port 1522/TCP' 'FAIL' $ora.Detail
    }

    $localEndpoints = @(
        @{ Url = "https://objectstorage.eu-frankfurt-1.oraclecloud.com"; Name = "*.oraclecloud.com" }
        @{ Url = "https://api.anthropic.com";         Name = "api.anthropic.com" }
        @{ Url = "https://claude.ai";                 Name = "claude.ai" }
        @{ Url = "https://claude.com";                Name = "claude.com" }
        @{ Url = "https://platform.claude.com";       Name = "platform.claude.com" }
        @{ Url = "https://downloads.claude.ai";       Name = "downloads.claude.ai" }
        @{ Url = "https://storage.googleapis.com";    Name = "storage.googleapis.com" }
        @{ Url = "https://registry.npmjs.org";        Name = "registry.npmjs.org" }
        @{ Url = "https://codeload.github.com";       Name = "codeload.github.com" }
        @{ Url = "https://raw.githubusercontent.com"; Name = "raw.githubusercontent.com" }
    )

    foreach ($e in $localEndpoints) {
        $r = Test-Https -Url $e.Url -Timeout $TimeoutSec
        if ($r.Ok -and $r.Warn) { Add-Result 'Net-Local' $e.Name 'WARN' $r.Detail }
        elseif ($r.Ok)          { Add-Result 'Net-Local' $e.Name 'OK'   $r.Detail }
        else                    { Add-Result 'Net-Local' $e.Name 'FAIL' $r.Detail }
    }
}

# --- 4. installed software -------------------------------------------------

if ($doLocal) {
    Write-Section "4. Installed software (needed only for the local variant)"

    Test-Tool -Exe 'java' -Label 'Java' -CommandLine 'java -version' `
        -MinMajor 17 -MinNote "SQLcl needs 17 or newer" -Parse {
            param($raw)
            $major = 0
            $ver   = (($raw -split "`r?`n") | Where-Object { $_.Trim() } | Select-Object -First 1)
            if ($raw -match 'version\s+"(\d+)(?:\.(\d+))?') {
                $a = [int]$Matches[1]
                if ($a -eq 1 -and $Matches[2]) { $major = [int]$Matches[2] } else { $major = $a }
            }
            @{ Version = "$ver".Trim(); Major = $major }
        }

    Test-Tool -Exe 'node' -Label 'Node.js' -CommandLine 'node --version' `
        -MinMajor 18 -MinNote "Claude Code needs 18 or newer" -Parse {
            param($raw)
            $major = 0
            if ($raw -match 'v?(\d+)\.') { $major = [int]$Matches[1] }
            @{ Version = $raw.Trim(); Major = $major }
        }

    Test-Tool -Exe 'git' -Label 'Git' -CommandLine 'git --version' -Parse {
            param($raw) @{ Version = $raw.Trim(); Major = 0 }
        }

    Test-Tool -Exe 'sql' -Label 'Oracle SQLcl' -CommandLine 'sql -V' -Parse {
            param($raw)
            $line = (($raw -split "`r?`n") | Where-Object { $_ -match '\d+\.\d+' } | Select-Object -First 1)
            if (-not $line) { $line = (($raw -split "`r?`n") | Select-Object -First 1) }
            @{ Version = "$line".Trim(); Major = 0 }
        }

    Test-Tool -Exe 'claude' -Label 'Claude Code' -CommandLine 'claude --version' -Parse {
            param($raw) @{ Version = (($raw -split "`r?`n") | Select-Object -First 1).Trim(); Major = 0 }
        }
}

# --- 5. verdict ------------------------------------------------------------

Write-Section "Summary"

$cloudNet = @($Script:Results | Where-Object { $_.Group -eq 'Net-Cloud' })
$localNet = @($Script:Results | Where-Object { $_.Group -eq 'Net-Local' })
$soft     = @($Script:Results | Where-Object { $_.Group -eq 'Software' })

function Show-Verdict {
    param($Title, $Items, $Note)

    if ($Items.Count -eq 0) { return }

    $bad  = @($Items | Where-Object { $_.Status -eq 'FAIL' })
    $warn = @($Items | Where-Object { $_.Status -eq 'WARN' })

    if ($bad.Count -eq 0) {
        Write-Host ("  {0}: all clear" -f $Title) -ForegroundColor Green
    } else {
        Write-Host ("  {0}: {1} blocked" -f $Title, $bad.Count) -ForegroundColor Red
        foreach ($b in $bad) {
            Write-Host ("      - {0}  ({1})" -f $b.Name, $b.Detail) -ForegroundColor Red
        }
        if ($Note) { Write-Host ("      {0}" -f $Note) -ForegroundColor DarkGray }
    }

    if ($warn.Count -gt 0) {
        Write-Host ("      {0} item(s) need a closer look - see WARN above" -f $warn.Count) -ForegroundColor Yellow
    }
}

if ($doCloud) {
    Show-Verdict "Cloud container" $cloudNet "This is the variant we recommend - these lines are the critical ones."
}

if ($doLocal) {
    Write-Host ""
    Show-Verdict "Local install - network" $localNet

    $missing = @($soft | Where-Object { $_.Detail -eq $Script:NotInstalled })
    $old     = @($soft | Where-Object { $_.Status -eq 'WARN' -and $_.Detail -ne $Script:NotInstalled })

    if ($missing.Count -eq 0 -and $old.Count -eq 0) {
        Write-Host "  Local install - software: all present" -ForegroundColor Green
    } else {
        if ($missing.Count -gt 0) {
            Write-Host ("  Local install - software: not installed - {0}" -f (($missing | ForEach-Object { $_.Name }) -join ', ')) -ForegroundColor Yellow
        }
        if ($old.Count -gt 0) {
            Write-Host ("  Local install - software: too old - {0}" -f (($old | ForEach-Object { $_.Name }) -join ', ')) -ForegroundColor Yellow
        }
        if ($Mode -ne 'local') {
            Write-Host "      Not a problem: the recommended cloud setup installs nothing locally." -ForegroundColor DarkGray
            Write-Host "      This section only matters if you choose the local variant." -ForegroundColor DarkGray
        } else {
            Write-Host "      Expected if you have not installed anything yet - we supply the installer." -ForegroundColor DarkGray
        }
    }
}

# --- 6. report file --------------------------------------------------------

if (-not $OutFile) {
    $dir = [Environment]::GetFolderPath('Desktop')
    if ([string]::IsNullOrWhiteSpace($dir) -or -not (Test-Path $dir)) { $dir = $env:TEMP }
    $OutFile = Join-Path $dir ("AcordBank-EnvCheck_{0}_{1}.txt" -f $env:COMPUTERNAME, (Get-Date -Format 'yyyy-MM-dd_HHmm'))
}

$sb = New-Object System.Text.StringBuilder
$null = $sb.AppendLine("AcordBank - workstation readiness check")
$null = $sb.AppendLine("Date       : " + (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'))
$null = $sb.AppendLine("Computer   : " + $env:COMPUTERNAME)
$null = $sb.AppendLine("User       : " + $env:USERNAME)
$null = $sb.AppendLine("Mode       : " + $Mode)
$null = $sb.AppendLine("PowerShell : " + $PSVersionTable.PSVersion.ToString())
$null = $sb.AppendLine("")
$null = $sb.AppendLine(("{0,-6} {1,-10} {2,-30} {3}" -f "STATE", "SECTION", "CHECK", "DETAIL"))
$null = $sb.AppendLine("-" * 96)
foreach ($r in $Script:Results) {
    $null = $sb.AppendLine(("{0,-6} {1,-10} {2,-30} {3}" -f $r.Status, $r.Group, $r.Name, $r.Detail))
}

try {
    [System.IO.File]::WriteAllText($OutFile, $sb.ToString(), (New-Object System.Text.UTF8Encoding $false))
    Write-Host ""
    Write-Host "  Report saved to:" -ForegroundColor White
    Write-Host ("  {0}" -f $OutFile) -ForegroundColor White
    Write-Host "  Sending us this one file is enough." -ForegroundColor DarkGray
} catch {
    Write-Host ""
    Write-Host ("  Could not save the report: {0}" -f $_.Exception.Message) -ForegroundColor Yellow
    Write-Host "  Please copy the text above instead." -ForegroundColor Yellow
}

Write-Host ""
