param([string]$Destination = '', [switch]$NoShortcut, [switch]$NoStart)
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Windows.Forms
try {
    $localRoot = [Environment]::GetFolderPath('LocalApplicationData')
    $installRoot = if ($Destination) { [IO.Path]::GetFullPath($Destination) } else { Join-Path $localRoot 'Programs\BioLabReview' }
    $parent = Split-Path $installRoot -Parent
    New-Item -ItemType Directory -Force -Path $parent | Out-Null
    $running = @(Get-CimInstance Win32_Process | Where-Object { $_.ExecutablePath -and $_.ExecutablePath.StartsWith($installRoot + '\', [StringComparison]::OrdinalIgnoreCase) })
    if ($running.Count) { throw '请先在启动窗口点击“退出系统”，再安装或更新。' }
    $stage = Join-Path $parent ('BioLabReview-staging-' + [Guid]::NewGuid().ToString('N'))
    Expand-Archive -LiteralPath (Join-Path $PSScriptRoot 'payload.zip') -DestinationPath $stage
    if (-not (Test-Path -LiteralPath (Join-Path $stage 'python\pythonw.exe'))) { throw '安装文件不完整。' }
    if (Test-Path -LiteralPath $installRoot) {
        $backup = $installRoot + '-previous-' + (Get-Date -Format 'yyyyMMddHHmmssfff')
        Move-Item -LiteralPath $installRoot -Destination $backup
    }
    Move-Item -LiteralPath $stage -Destination $installRoot
    $python = Join-Path $installRoot 'python\pythonw.exe'
    $appRoot = Join-Path $installRoot 'app'
    $launcher = Join-Path $appRoot 'streamlit_launcher.py'
    if (-not $NoShortcut) {
        $shell = New-Object -ComObject WScript.Shell
        $desktop = [Environment]::GetFolderPath('Desktop')
        $shortcutPath = Join-Path $desktop '生物实验智学助手.lnk'
        if (Test-Path -LiteralPath $shortcutPath) {
            $old = $shell.CreateShortcut($shortcutPath)
            if ($old.TargetPath -ne $python) { $shortcutPath = Join-Path $desktop '生物实验智学助手（安装版）.lnk' }
        }
        # 清理同一程序的旧版本桌面名称，其他项目的快捷方式保留。
        $legacyNames = @(
            (-join ([char[]](0x751F,0x7269,0x5B9E,0x9A8C,0x667A,0x6790,0x52A9,0x624B))),
            (-join ([char[]](0x751F,0x7269,0x5B9E,0x9A8C,0x667A,0x5B66,0x5E73,0x53F0)))
        )
        foreach ($legacyName in $legacyNames) {
        foreach ($legacySuffix in @('.lnk','（安装版）.lnk',' (project).lnk')) {
            $legacyLink = Join-Path ([Environment]::GetFolderPath('Desktop')) ($legacyName + $legacySuffix)
            if (Test-Path -LiteralPath $legacyLink) {
                $legacyShortcut = $shell.CreateShortcut($legacyLink)
                if ($legacyShortcut.TargetPath -eq $python) { Remove-Item -LiteralPath $legacyLink }
            }
        }
        }
        $shortcut = $shell.CreateShortcut($shortcutPath)
        $shortcut.TargetPath = $python
        $shortcut.Arguments = '"' + $launcher + '"'
        $shortcut.WorkingDirectory = $appRoot
        $shortcut.Description = '生物实验智学助手'
        $shortcut.IconLocation = (Join-Path $appRoot 'desktop\app.ico') + ',0'
        $shortcut.Save()
        $menu = Join-Path ([Environment]::GetFolderPath('Programs')) '生物实验智学助手'
        New-Item -ItemType Directory -Force -Path $menu | Out-Null
        Copy-Item -LiteralPath $shortcutPath -Destination (Join-Path $menu '生物实验智学助手.lnk')
        $uninstall = Join-Path $installRoot 'app\desktop\uninstall.ps1'
        $link = $shell.CreateShortcut((Join-Path $menu '卸载.lnk'))
        $link.TargetPath = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
        $link.Arguments = '-NoProfile -ExecutionPolicy Bypass -File "' + $uninstall + '"'
        $link.WindowStyle = 7
        $link.Save()
        # 升级后仅移除指向本安装目录的旧开始菜单入口。
        foreach ($legacyName in $legacyNames) {
            $legacyMenu = Join-Path ([Environment]::GetFolderPath('Programs')) $legacyName
            foreach ($entry in @(($legacyName + '.lnk'), '卸载.lnk')) {
                $legacyLink = Join-Path $legacyMenu $entry
                if (Test-Path -LiteralPath $legacyLink) {
                    $old = $shell.CreateShortcut($legacyLink)
                    if (($old.TargetPath -eq $python) -or (($entry -eq '卸载.lnk') -and $old.Arguments.Contains($uninstall))) {
                        Remove-Item -LiteralPath $legacyLink
                    }
                }
            }
            if ((Test-Path -LiteralPath $legacyMenu) -and -not (Get-ChildItem -LiteralPath $legacyMenu -Force)) {
                Remove-Item -LiteralPath $legacyMenu
            }
        }
        $reg = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\BioLabReview'
        New-Item -Path $reg -Force | Out-Null
        New-ItemProperty -Path $reg -Name DisplayName -Value '生物实验智学助手' -Force | Out-Null
        New-ItemProperty -Path $reg -Name DisplayVersion -Value '2026.10.09' -Force | Out-Null
        New-ItemProperty -Path $reg -Name DisplayIcon -Value ((Join-Path $appRoot 'desktop\app.ico') + ',0') -Force | Out-Null
        New-ItemProperty -Path $reg -Name InstallLocation -Value $installRoot -Force | Out-Null
        New-ItemProperty -Path $reg -Name UninstallString -Value ('powershell.exe -NoProfile -ExecutionPolicy Bypass -File "' + $uninstall + '"') -Force | Out-Null
        [Windows.Forms.MessageBox]::Show('安装完成。请双击桌面上的“生物实验智学助手”。首次进入可设置教师访问码及 DeepSeek API Key。', '生物实验智学助手') | Out-Null
    }
    if (-not $NoStart) { Start-Process -FilePath $python -ArgumentList ('"' + $launcher + '"') -WorkingDirectory $appRoot -WindowStyle Hidden }
    Write-Output ('Installed: ' + $installRoot)
} catch {
    if (-not $NoShortcut) { [Windows.Forms.MessageBox]::Show($_.Exception.Message, '安装未完成') | Out-Null }
    throw
}
