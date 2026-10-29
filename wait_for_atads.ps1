param([int]$Port = 8765)
$url = "http://127.0.0.1:$Port/api/health"
for ($attempt = 0; $attempt -lt 90; $attempt++) {
    try {
        $response = Invoke-RestMethod -Uri $url -TimeoutSec 1
        if ($response.status -eq "ok") {
            Start-Process "http://127.0.0.1:$Port"
            exit 0
        }
    } catch {
        Start-Sleep -Seconds 1
    }
}
