# K-08 · smoke test of the bench with a real account, from the computer of whoever tests (PowerShell).
# It asks for the password without showing it, signs in with the client argos-tests and calls the API
# as that account would; it prints only status codes, counts and the claims that matter, never the
# password or the token. With the tunnel open (tunnel.sh), or without it once the firewall opens:
#
#   powershell -ExecutionPolicy Bypass -File platform/k8s/bench/smoke.ps1 -User auditor.test
#
param([Parameter(Mandatory = $true)][string]$User)

$Api = "https://api.34-134-21-66.sslip.io"
$Realm = "https://id.34-134-21-66.sslip.io/realms/argos"
# Until Let's Encrypt can reach port 80 the certificate is the one of Traefik: -k accepts it.
$Insecure = "-k"

$secure = Read-Host "Password of $User (not shown)" -AsSecureString
$plain = [Runtime.InteropServices.Marshal]::PtrToStringAuto(
    [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure))
# The form goes on the standard input of curl, never on its command line (the list of processes).
$form = "grant_type=password&client_id=argos-tests&scope=openid&username=" +
    [uri]::EscapeDataString($User) + "&password=" + [uri]::EscapeDataString($plain)
$plain = $null
$answer = $form | curl.exe -s $Insecure --data "@-" "$Realm/protocol/openid-connect/token"
$form = $null
if (-not $answer) {
    Write-Host "no answer from $Realm : is the tunnel open in another window (tunnel.sh)?"
    exit 1
}
$tokens = $answer | ConvertFrom-Json
if (-not $tokens.access_token) {
    Write-Host "sign-in refused: $($tokens.error_description)"
    exit 1
}
$token = $tokens.access_token
$payload = $token.Split(".")[1].Replace("-", "+").Replace("_", "/")
$payload += "=" * ((4 - $payload.Length % 4) % 4)
$claims = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($payload)) | ConvertFrom-Json
Write-Host "sign-in: ok"
Write-Host "  issuer:   $($claims.iss)"
Write-Host "  audience: $($claims.aud -join ', ')"
Write-Host "  roles:    $(($claims.realm_access.roles | Where-Object { $_ -notlike 'default-roles*' -and $_ -ne 'offline_access' -and $_ -ne 'uma_authorization' }) -join ', ')"

# The token goes to curl in a file of headers, not on its command line, and the file goes at the end.
$headerFile = [IO.Path]::GetTempFileName()
Set-Content -Path $headerFile -Value "Authorization: Bearer $token" -NoNewline -Encoding ascii

function Call([string]$Method, [string]$Path, [string]$Body = $null) {
    $headers = @("-H", "@$headerFile")
    $extra = @()
    $bodyFile = $null
    if ($Body) {
        # PowerShell 5.1 strips the quotes of a JSON argument to a native program: a file keeps it.
        $bodyFile = [IO.Path]::GetTempFileName()
        Set-Content -Path $bodyFile -Value $Body -NoNewline -Encoding ascii
        $extra = @("-H", "Content-Type: application/json", "--data-binary", "@$bodyFile")
    }
    $out = [IO.Path]::GetTempFileName()
    $code = curl.exe -s $Insecure -o $out -w "%{http_code}" -X $Method @headers @extra "$Api$Path"
    $text = Get-Content $out -Raw
    Remove-Item $out
    if ($bodyFile) { Remove-Item $bodyFile }
    $count = ""
    try {
        $json = $text | ConvertFrom-Json
        if ($json.items) { $count = "  ($(@($json.items).Count) items)" }
        elseif ($json.title) { $count = "  ($($json.title))" }
    } catch { }
    Write-Host ("  {0,-6} {1,-40} {2}{3}" -f $Method, $Path, $code, $count)
}

Write-Host "reads:"
foreach ($path in "/api/v1/systems", "/api/v1/inventory/coverage", "/api/v1/inventory/review-queue",
                  "/api/v1/campaigns", "/api/v1/findings", "/api/v1/approvals",
                  "/api/v1/operations/status", "/api/v1/operations/capacity",
                  "/api/v1/security/events", "/api/v1/webhooks") {
    Call "GET" $path
}
# Only with a read-only account: with any other, this would create a campaign.
if (@($claims.realm_access.roles) -contains "read_only_auditor") {
    Write-Host "a write a read-only account must not do (403 expected):"
    Call "POST" "/api/v1/campaigns" '{"name": "smoke"}'
}
Remove-Item $headerFile
$token = $null
