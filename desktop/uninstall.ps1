$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Windows.Forms
$expected = [IO.Path]::GetFullPath((Join-Path ([Environment]::GetFolderPath('LocalApplicationData')) 'Programs\BioLabReview'))
$actual = [IO.Path]::GetFullPath((Split-Path (Split-Path $PSScriptRoot -Parent) -Parent))
if ($actual -ne $expected) { throw '安装路径不符合预期，停止卸载。' }
if ((Get-Item -LiteralPath $actual).Attributes -band [IO.FileAttributes]::ReparsePoint) { throw '安装路径不能是目录链接。' }
if ([Windows.Forms.MessageBox]::Show('卸载软件将保留个人数据、图片和配置。是否继续？', '卸载生物实验智析助手', 'YesNo') -ne 'Yes') { exit }
$running = @(Get-CimInstance Win32_Process | Where-Object { $_.ExecutablePath -and $_.ExecutablePath.StartsWith($actual + '\', [StringComparison]::OrdinalIgnoreCase) })
if ($running.Count) { [Windows.Forms.MessageBox]::Show('请先在启动窗口点击“退出系统”。', '请先退出') | Out-Null; exit 1 }
$shell = New-Object -ComObject WScript.Shell
foreach ($name in @('生物实验智析助手.lnk','生物实验智析助手（安装版）.lnk')) {
    $link = Join-Path ([Environment]::GetFolderPath('Desktop')) $name
    if (Test-Path -LiteralPath $link) {
        if ($shell.CreateShortcut($link).TargetPath -eq (Join-Path $actual 'python\pythonw.exe')) { Remove-Item -LiteralPath $link }
    }
}
$menu = Join-Path ([Environment]::GetFolderPath('Programs')) '生物实验智析助手'
if (Test-Path -LiteralPath $menu) { Remove-Item -LiteralPath $menu -Recurse }
Remove-Item -LiteralPath 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\BioLabReview' -Recurse -ErrorAction SilentlyContinue
# 仅删除已核对的程序目录；用户数据位于另一个目录，不参加删除。
Remove-Item -LiteralPath $actual -Recurse
[Windows.Forms.MessageBox]::Show('软件已卸载。个人数据仍保留在 %LOCALAPPDATA%\BioLabReview。', '卸载完成') | Out-Null
