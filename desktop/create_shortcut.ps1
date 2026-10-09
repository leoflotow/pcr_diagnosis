$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path $PSScriptRoot -Parent
$python = Join-Path $projectRoot '.venv\Scripts\pythonw.exe'
if (-not (Test-Path -LiteralPath $python)) { throw 'Project Python environment not found.' }
$desktopPath = [Environment]::GetFolderPath('Desktop')
$shell = New-Object -ComObject WScript.Shell
# 使用 Unicode 码点，兼容 Windows PowerShell 对无 BOM 脚本的读取。
$productName = -join ([char[]](0x751F,0x7269,0x5B9E,0x9A8C,0x667A,0x5B66,0x5E73,0x53F0))
$shortcutPath = Join-Path $desktopPath ($productName + '.lnk')
if (Test-Path -LiteralPath $shortcutPath) {
    $existing = $shell.CreateShortcut($shortcutPath)
    if ($existing.TargetPath -ne $python) {
        $shortcutPath = Join-Path $desktopPath ($productName + ' (' + 'project' + ').lnk')
    }
}
# 清理同一程序的旧版本桌面名称，其他项目的快捷方式保留。
$legacyName = -join ([char[]](0x751F,0x7269,0x5B9E,0x9A8C,0x667A,0x6790,0x52A9,0x624B))
foreach ($legacySuffix in @('.lnk','（安装版）.lnk',' (project).lnk')) {
    $legacyLink = Join-Path ([Environment]::GetFolderPath('Desktop')) ($legacyName + $legacySuffix)
    if (Test-Path -LiteralPath $legacyLink) {
        $legacyShortcut = $shell.CreateShortcut($legacyLink)
        if ($legacyShortcut.TargetPath -eq $python) { Remove-Item -LiteralPath $legacyLink }
    }
}
$shortcut = $shell.CreateShortcut($shortcutPath)
$shortcut.TargetPath = $python
$shortcut.Arguments = '"' + (Join-Path $projectRoot 'streamlit_launcher.py') + '"'
$shortcut.WorkingDirectory = $projectRoot
$shortcut.Description = $productName
$shortcut.IconLocation = $python + ',0'
$shortcut.Save()
Write-Output ('Created: ' + $shortcutPath)
