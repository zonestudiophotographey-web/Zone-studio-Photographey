$ErrorActionPreference = 'Stop'
$root = (Resolve-Path $PSScriptRoot).Path
$listener = [System.Net.HttpListener]::new()
$listener.Prefixes.Add('http://127.0.0.1:8001/')
$listener.Start()
Write-Output 'ZONE STUDIO frontend: http://127.0.0.1:8001'
while ($listener.IsListening) {
    $context = $listener.GetContext()
    try {
        $relative = [Uri]::UnescapeDataString($context.Request.Url.AbsolutePath.TrimStart('/'))
        if ([string]::IsNullOrWhiteSpace($relative)) { $relative = 'index.html' }
        $candidate = [System.IO.Path]::GetFullPath((Join-Path $root $relative))
        if (-not $candidate.StartsWith($root, [System.StringComparison]::OrdinalIgnoreCase) -or -not (Test-Path -LiteralPath $candidate -PathType Leaf)) {
            $context.Response.StatusCode = 404
            $context.Response.Close()
            continue
        }
        $types = @{ '.html'='text/html; charset=utf-8'; '.css'='text/css; charset=utf-8'; '.js'='text/javascript; charset=utf-8'; '.json'='application/json; charset=utf-8'; '.webmanifest'='application/manifest+json'; '.svg'='image/svg+xml' }
        $extension = [System.IO.Path]::GetExtension($candidate).ToLowerInvariant()
        if ($types.ContainsKey($extension)) { $context.Response.ContentType = $types[$extension] }
        $bytes = [System.IO.File]::ReadAllBytes($candidate)
        $context.Response.ContentLength64 = $bytes.Length
        $context.Response.OutputStream.Write($bytes, 0, $bytes.Length)
        $context.Response.Close()
    } catch {
        try { $context.Response.StatusCode = 500; $context.Response.Close() } catch { }
    }
}
