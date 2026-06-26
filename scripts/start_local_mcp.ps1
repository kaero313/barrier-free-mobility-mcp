param(
    [ValidateSet("mock", "live")]
    [string]$AppMode = "mock",

    [ValidateSet("memory", "redis")]
    [string]$CacheBackend = "memory",

    [switch]$AuthEnabled
)

$env:APP_MODE = $AppMode
$env:CACHE_BACKEND = $CacheBackend

if ($AuthEnabled) {
    $env:MCP_AUTH_ENABLED = "true"
} else {
    $env:MCP_AUTH_ENABLED = "false"
}

uv run python -m app.main
