Add-Type -AssemblyName System.Drawing
Add-Type @'
using System;
using System.Runtime.InteropServices;
public static class NebulaCapture {
  [StructLayout(LayoutKind.Sequential)] public struct RECT { public int Left, Top, Right, Bottom; }
  [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr hWnd, out RECT rect);
  [DllImport("user32.dll")] public static extern bool PrintWindow(IntPtr hWnd, IntPtr hdc, uint flags);
}
'@
$process = Get-Process python | Where-Object MainWindowTitle -EQ 'Nebula 1.25.0' | Select-Object -First 1
if (-not $process) { throw 'Janela da Nebula não encontrada.' }
$rect = New-Object NebulaCapture+RECT
[NebulaCapture]::GetWindowRect($process.MainWindowHandle, [ref]$rect) | Out-Null
$bitmap = New-Object System.Drawing.Bitmap ($rect.Right-$rect.Left), ($rect.Bottom-$rect.Top)
$graphics = [System.Drawing.Graphics]::FromImage($bitmap)
$hdc = $graphics.GetHdc()
[NebulaCapture]::PrintWindow($process.MainWindowHandle, $hdc, 2) | Out-Null
$graphics.ReleaseHdc($hdc)
$graphics.Dispose()
$bitmap.Save((Join-Path $PSScriptRoot 'nebula-final-preview.png'), [System.Drawing.Imaging.ImageFormat]::Png)
$bitmap.Dispose()
