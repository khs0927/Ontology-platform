param([string[]]$Servers = @('sketchup','sketchup-mcp2','claude:sketchup','claude:sketchup-mcp2','codex:sketchup2','hueflow-sketchup','revit-mcp','horizun-revit','multiCAD-mcp','autocad-mcp','power-cad','codex:power-cad','xicad-headless','freecad-mcp','rhino-ai','grasshopper-ai','korean-law','korean-land','kordoc','jev'), [int]$Timeout = 60000)
$ErrorActionPreference = 'Continue'
$node = 'C:\Program Files\nodejs\node.exe'
$dir = Join-Path $PSScriptRoot 'test-results'
New-Item -ItemType Directory -Force $dir | Out-Null
foreach ($s in $Servers) {
  $safe = $s -replace '[:\\/]', '_'
  $sw = [Diagnostics.Stopwatch]::StartNew()
  $outText = & $node (Join-Path $PSScriptRoot 'mcp-call.mjs') tools $s --timeout $Timeout 2>&1 | Out-String
  $code = $LASTEXITCODE
  $sw.Stop()
  [System.IO.File]::WriteAllText((Join-Path $dir "$safe.json"), $outText, (New-Object System.Text.UTF8Encoding($false)))
  "{0} exit={1} ms={2}" -f $s, $code, $sw.ElapsedMilliseconds
}
