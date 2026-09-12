# make_icon.ps1 — generate packaging/icon.ico (PNG-in-ICO, 4-color grid
# matching the web favicon). Run with PowerShell:  powershell -File make_icon.ps1
# Build still works without the icon; the spec only references it when present.

Add-Type -AssemblyName System.Drawing

$bmp = New-Object System.Drawing.Bitmap(32, 32)
$g = [System.Drawing.Graphics]::FromImage($bmp)
$g.SmoothingMode = [System.Drawing.Drawing2D.SmoothingMode]::AntiAlias
$g.Clear([System.Drawing.ColorTranslator]::FromHtml('#F6F1E7'))

$colors = '#F0C94F', '#C9E86C', '#F3C7C1', '#F7D9B3'
for ($i = 0; $i -lt 4; $i++) {
    $x = 4 + ($i % 2) * 14
    $y = 4 + [int]([Math]::Floor($i / 2)) * 14
    $brush = New-Object System.Drawing.SolidBrush(
        [System.Drawing.ColorTranslator]::FromHtml($colors[$i]))
    $g.FillRectangle($brush, $x, $y, 12, 12)
    $brush.Dispose()
}

$ms = New-Object System.IO.MemoryStream
$bmp.Save($ms, [System.Drawing.Imaging.ImageFormat]::Png)
$png = $ms.ToArray()
$ms.Close()
$g.Dispose()
$bmp.Dispose()

# ICO = 6-byte header + 16-byte directory entry + PNG payload
$out = New-Object System.Collections.Generic.List[byte]
$out.AddRange([byte[]](0, 0, 1, 0, 1, 0))                # reserved=0, type=1, count=1
$out.AddRange([byte[]](32, 32, 0, 0, 1, 0, 32, 0))       # 32x32, 0 colors, planes=1, bpp=32
$out.AddRange([BitConverter]::GetBytes([int]$png.Length))  # data size
$out.AddRange([BitConverter]::GetBytes([int]22))           # data offset = 6 + 16
$out.AddRange($png)

$dest = Join-Path $PSScriptRoot 'icon.ico'
[IO.File]::WriteAllBytes($dest, $out.ToArray())
Write-Host "icon.ico written: $dest ($($out.Count) bytes)"
