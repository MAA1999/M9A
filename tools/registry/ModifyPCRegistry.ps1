<#
modify_resolution.ps1
Safe helper to backup a registry key and update a Resolution-like value to "WIDTH * HEIGHT" or a custom string.
- Preserves the original registry value kind when possible (REG_BINARY/REG_SZ/REG_DWORD/etc).
- Backs up the whole key with `reg export` before modifying.
- Offers a `-Restore` switch to import the backup.
- Automatically sets game defaults (fullscreen mode=3, language=en/ja, etc.) for all resolutions unless -NoGameDefaults is used.
- Bilingual UI: every prompt is shown in both Chinese and English.

Usage examples:
# Backup & set to 1920 x 1080 (will also set game defaults)
pwsh .\modify_resolution.ps1 -KeyPath 'HKCU:\Software\bluepoch' -ValueName 'ResolutionRatio_h997442698' -Width 1920 -Height 1080 -BackupFile '.\bluepoch_backup.reg'

# Set to a custom string (will also set game defaults)
pwsh .\modify_resolution.ps1 -KeyPath 'HKCU:\Software\bluepoch' -ValueName 'ResolutionRatio_h997442698' -NewValue '1280 * 720'

# Set resolution without game defaults
pwsh .\modify_resolution.ps1 -Width 1280 -Height 720 -NoGameDefaults

# Restore from backup
pwsh .\modify_resolution.ps1 -KeyPath 'HKCU:\Software\bluepoch' -BackupFile '.\bluepoch_backup.reg' -Restore
#>

param(
    [string]$KeyPath,
    [string]$ValueName = 'ResolutionRatio_h997442698',
    [ValidateSet('1','2','3','4','5','6')]
    [string]$Preset,
    [ValidateSet('EN','JP')]
    [string]$Server = 'EN',
    [int]$Width,
    [int]$Height,
    [string]$NewValue,
    [string]$BackupFile = '.\bluepoch_registry_backup.reg',
    [switch]$Restore,
    [switch]$Force,
    [switch]$NoGameDefaults
)

# Set default KeyPath based on server if not explicitly provided
$keyPathExplicit = $PSBoundParameters.ContainsKey('KeyPath')
if (-not $keyPathExplicit) {
    $KeyPath = if ($Server -eq 'JP') {
        'HKCU:\Software\bluepoch\リバース：1999'
    } else {
        'HKCU:\Software\bluepoch\Reverse: 1999'
    }
}

# Centralized resolution presets
$resolutionPresets = @(
    @{ Label = 'a'; Number = '1'; Width = 3840; Height = 2160; Description = '3840 * 2160' },
    @{ Label = 'b'; Number = '2'; Width = 2560; Height = 1440; Description = '2560 * 1440' },
    @{ Label = 'c'; Number = '3'; Width = 1920; Height = 1080; Description = '1920 * 1080' },
    @{ Label = 'd'; Number = '4'; Width = 1600; Height = 900; Description = '1600 * 900' },
    @{ Label = 'e'; Number = '5'; Width = 1366; Height = 768; Description = '1366 * 768' },
    @{ Label = 'f'; Number = '6'; Width = 1280; Height = 720; Description = '1280 * 720' }
)

function Write-ErrAndExit($msg) {
    Write-Error $msg
    exit 1
}

# Function to safely set a registry value, preserving its type
function Set-RegistryValueSafe($regKey, $valueName, $newValue, $preferredKind) {
    try {
        # Try to get existing value kind
        try {
            $existingKind = $regKey.GetValueKind($valueName)
        } catch {
            # Value doesn't exist, use preferred kind or default to String
            $existingKind = if ($preferredKind) { $preferredKind } else { [Microsoft.Win32.RegistryValueKind]::String }
        }

        switch ($existingKind) {
            'Binary' {
                if ($newValue -is [byte[]]) {
                    $regKey.SetValue($valueName, $newValue, [Microsoft.Win32.RegistryValueKind]::Binary)
                } else {
                    # Convert string to bytes (UTF-8 for WindowsTitle, ASCII for SdkLanguage)
                    $bytes = [System.Text.Encoding]::UTF8.GetBytes($newValue + "`0")
                    $regKey.SetValue($valueName, $bytes, [Microsoft.Win32.RegistryValueKind]::Binary)
                }
            }
            'DWord' {
                $intValue = if ($newValue -is [int]) { $newValue } else { [int]$newValue }
                $regKey.SetValue($valueName, $intValue, [Microsoft.Win32.RegistryValueKind]::DWord)
            }
            'String' {
                $regKey.SetValue($valueName, $newValue, [Microsoft.Win32.RegistryValueKind]::String)
            }
            default {
                $regKey.SetValue($valueName, $newValue, [Microsoft.Win32.RegistryValueKind]::String)
            }
        }
        Write-Host "  已设置 / Set $valueName = $newValue (type: $existingKind)"
        return $true
    } catch {
        Write-Warning "  设置失败 / Failed to set $valueName : $_"
        return $false
    }
}

# Function to set game default values
function Set-GameDefaults($regKey, $server) {
    Write-Host "正在设置游戏默认项 ($server) / Setting game default values ($server)..."

    # Screenmanager Fullscreen mode = 3 (windowed mode)
    try {
        $regKey.SetValue('Screenmanager Fullscreen mode_h3630240806', 3, [Microsoft.Win32.RegistryValueKind]::DWord)
        Write-Host "  Screenmanager Fullscreen mode_h3630240806 = 3 (DWord)"
    } catch {
        Write-Warning "  设置 Screenmanager Fullscreen mode 失败 / Failed to set Screenmanager Fullscreen mode: $_"
    }

    # SdkLanguage based on server
    $sdkLang = if ($server -eq 'JP') { 'ja' } else { 'en' }
    try {
        $sdkBytes = [System.Text.Encoding]::ASCII.GetBytes($sdkLang + "`0")
        $regKey.SetValue('SdkLanguage_h2445173579', $sdkBytes, [Microsoft.Win32.RegistryValueKind]::Binary)
        Write-Host "  SdkLanguage_h2445173579 = $sdkLang (Binary, ASCII)"
    } catch {
        Write-Warning "  设置 SdkLanguage 失败 / Failed to set SdkLanguage: $_"
    }

    # CurLanguageType = 1 (DWord)
    try {
        $regKey.SetValue('CurLanguageType_h2647185547', 1, [Microsoft.Win32.RegistryValueKind]::DWord)
        Write-Host "  CurLanguageType_h2647185547 = 1 (DWord)"
    } catch {
        Write-Warning "  设置 CurLanguageType 失败 / Failed to set CurLanguageType: $_"
    }

    Write-Host "游戏默认项已设置完成 / Game defaults set."
}

# Normalize KeyPath
if ($KeyPath -notmatch '^(HKCU|HKLM|HKCR|HKU|HKCC):\\') {
    Write-ErrAndExit "KeyPath 必须以 HKCU:/HKLM:/HKCR:/HKU:/HKCC: 之一开头 / KeyPath must start with one of HKCU:/HKLM:/HKCR:/HKU:/HKCC:. Example: 'HKCU:\\Software\\bluepoch'"
}

if ($Restore) {
    if (-not (Test-Path $BackupFile)) {
        Write-ErrAndExit "未找到备份文件 / Backup file not found: $BackupFile"
    }

    Write-Host "正在从以下路径导入备份 / Importing backup from: $BackupFile"
    $imp = Start-Process -FilePath reg -ArgumentList "import `"$BackupFile`"" -NoNewWindow -Wait -PassThru
    if ($imp.ExitCode -ne 0) {
        Write-ErrAndExit "reg import 失败 (退出码 $($imp.ExitCode)) / reg import failed (exit code $($imp.ExitCode))"
    }
    Write-Host "恢复完成 / Restore completed."
    exit 0
}

# Determine desired value string
# If no resolution parameters provided, run an interactive main menu
$hasResolutionParams = $PSBoundParameters.ContainsKey('Width') -or $PSBoundParameters.ContainsKey('Height') -or $PSBoundParameters.ContainsKey('NewValue') -or $PSBoundParameters.ContainsKey('Preset') -or $Restore
if (-not $hasResolutionParams) {
    while ($true) {
        Clear-Host
        Write-Host "================ 主菜单 / Main Menu ================"
        Write-Host "当前游戏服务器 / Current server: $Server"
        Write-Host "注册表路径 / KeyPath: $KeyPath"
        Write-Host ""
        Write-Host "请选择操作 / Select an action:"
        Write-Host "1) 从预设分辨率中选择 / Set resolution from preset"
        Write-Host "2) 从备份恢复（导入 .reg 文件） / Restore from backup (import .reg)"
        Write-Host "3) 切换游戏服务器（当前: $Server） / Switch server (currently: $Server)"
        Write-Host "4) 退出 / Exit"
        Write-Host "==================================================="
        $action = Read-Host "请输入选项 / Enter choice (1-4)"

        switch ($action) {
            '1' {
                :presetLoop while ($true) {
                    Clear-Host
                    $langLabel = if ($Server -eq 'JP') { 'ja' } else { 'en' }
                    Write-Host "预设分辨率（同时设置游戏默认项：窗口模式、$langLabel 语言） / Presets (will also set game defaults: windowed mode, $langLabel language):"
                    foreach ($res in $resolutionPresets) {
                        Write-Host "  $($res.Label): $($res.Description)"
                    }
                    Write-Host "  q) 返回主菜单 / Return to main menu"
                    $presetLabels = ($resolutionPresets | ForEach-Object { $_.Label }) -join ', '
                    $p = Read-Host "请选择预设 ($presetLabels) 或输入 'q' 返回 / Choose preset ($presetLabels) or 'q' to return"

                    if ($p -eq 'q' -or $p -eq 'Q') {
                        Write-Host "正在返回主菜单 / Returning to main menu..."
                        Start-Sleep -Seconds 1
                        break  # Break inner loop to return to main menu
                    }

                    $selectedPreset = $resolutionPresets | Where-Object { $_.Label -eq $p.ToLower() }
                    if ($selectedPreset) {
                        $Width = $selectedPreset.Width
                        $Height = $selectedPreset.Height
                        $valueToSet = "{0} * {1}" -f $Width, $Height
                        # Interactive confirm: N goes back to preset loop, Y proceeds
                        if (-not $Force) {
                            Clear-Host
                            Write-Host "即将修改注册表项 / About to modify registry key: $KeyPath, value: $ValueName"
                            Write-Host "服务器 / Server: $Server"
                            Write-Host "新值 / New value: $valueToSet"
                            if (-not $NoGameDefaults) {
                                Write-Host "提示 / Note: 还会同时设置游戏默认项（窗口模式、语言等） / This will also set game defaults (windowed mode, language, etc.)"
                            }
                            $ok = Read-Host "是否继续？(y/N，输入 N 返回重新选择) / Proceed? (y/N, enter N to go back)"
                            if ($ok.ToLower() -ne 'y') {
                                $valueToSet = $null
                                continue presetLoop
                            }
                        }
                        break  # Exit preset selection loop after valid choice
                    } else {
                        Write-Host "无效的预设选项 / Invalid preset choice."; Start-Sleep -Seconds 1
                    }
                }
                if ($valueToSet) { break }  # Exit main menu loop if a resolution was chosen
            }
            '2' {
                # Restore flow
                $bk = Read-Host "请输入要导入的备份 .reg 路径（留空使用默认 $BackupFile） / Enter backup .reg path to import (or press Enter to use default $BackupFile)"
                if ($bk -ne '') { $BackupFile = $bk }
                if (-not (Test-Path $BackupFile)) { Write-Host "未找到备份文件 / Backup file not found: $BackupFile"; Start-Sleep -Seconds 2; continue }
                Write-Host "正在从以下路径导入备份 / Importing backup from: $BackupFile"
                Start-Process -FilePath reg -ArgumentList "import `"$BackupFile`"" -NoNewWindow -Wait
                Write-Host "恢复完成 / Restore completed."
                $confirmExit = Read-Host "是否退出 / Exit? (y/N)"
                if ($confirmExit.ToLower() -eq 'y') { Write-Host "已退出 / Exiting."; exit 0 }
                Start-Sleep -Seconds 2
            }
            '3' {
                # Switch server (cycle: EN -> JP -> EN)
                $Server = if ($Server -eq 'EN') { 'JP' } else { 'EN' }
                if (-not $keyPathExplicit) {
                    $KeyPath = if ($Server -eq 'JP') {
                        'HKCU:\Software\bluepoch\リバース：1999'
                    } else {
                        'HKCU:\Software\bluepoch\Reverse: 1999'
                    }
                }
                Write-Host "已切换到游戏服务器 / Switched to server: $Server"
                Start-Sleep -Seconds 1
            }
            '4' { Write-Host "已退出 / Exiting."; exit 0 }
            default { Write-Host "无效的选项 / Invalid choice."; Start-Sleep -Seconds 1 }
        }
        # If a resolution was selected, exit the main loop to proceed with modification
        if ($valueToSet) { break }
    }
} else {
    if ($PSBoundParameters.ContainsKey('NewValue')) {
        $valueToSet = $NewValue
    } elseif ($PSBoundParameters.ContainsKey('Width') -and $PSBoundParameters.ContainsKey('Height')) {
        $valueToSet = "{0} * {1}" -f $Width, $Height
    } elseif ($PSBoundParameters.ContainsKey('Preset')) {
        $selectedPreset = $resolutionPresets | Where-Object { $_.Number -eq $Preset }
        if ($selectedPreset) {
            $Width = $selectedPreset.Width
            $Height = $selectedPreset.Height
            $valueToSet = "{0} * {1}" -f $Width, $Height
        } else {
            Write-ErrAndExit "Invalid Preset value."
        }
    } else {
        Write-ErrAndExit "Either supply -NewValue or both -Width and -Height (or run interactively without parameters)."
    }
}

# Confirm for parameter mode (interactive mode is confirmed inside the preset loop)
if ($hasResolutionParams -and -not $Force) {
    Write-Host "即将修改注册表项 / About to modify registry key: $KeyPath, value: $ValueName"
    Write-Host "服务器 / Server: $Server"
    Write-Host "新值 / New value: $valueToSet"
    if (-not $NoGameDefaults) {
        Write-Host "提示 / Note: 还会同时设置游戏默认项（窗口模式、语言等） / This will also set game defaults (windowed mode, language, etc.)"
    }
    $ok = Read-Host "是否继续 / Proceed? (y/N)"
    if ($ok.ToLower() -ne 'y') { Write-Host "已取消 / Aborted."; exit 0 }
}

# Export backup
Write-Host "正在导出注册表项到 / Exporting registry key to: $BackupFile"
$exportTarget = $KeyPath

# Convert PowerShell provider path (HKCU:\...) to reg.exe path (HKCU\...)
function Convert-ToRegKey([string]$psKey) {
    if ($psKey -match '^(HKCU|HKLM|HKCR|HKU|HKCC):\\(.+)$') {
        return "$($matches[1])\$($matches[2])"
    }
    return $psKey
}

$regExportTarget = Convert-ToRegKey $exportTarget
$export = Start-Process -FilePath reg -ArgumentList "export `"$regExportTarget`" `"$BackupFile`" /y" -NoNewWindow -Wait -PassThru
if ($export.ExitCode -ne 0) {
    Write-Host "reg export 失败 (键: '$exportTarget', 退出码 $($export.ExitCode))。尝试导出父键 / reg export failed for key '$exportTarget' (exit code $($export.ExitCode)). Trying parent key export..."
    # Try exporting parent key if child key name contains characters unsupported by reg.exe (eg. colon)
    try {
        $lastSlash = $KeyPath.LastIndexOf('\')
        if ($lastSlash -gt 0) {
            $parentKey = $KeyPath.Substring(0, $lastSlash)
            Write-Host "正在尝试导出父键 / Attempting to export parent key: $parentKey"
            $regParent = Convert-ToRegKey $parentKey
            $export = Start-Process -FilePath reg -ArgumentList "export `"$regParent`" `"$BackupFile`" /y" -NoNewWindow -Wait -PassThru
            if ($export.ExitCode -ne 0) {
                Write-ErrAndExit "reg export 父键失败 ('$parentKey', 退出码 $($export.ExitCode))。中止 / reg export failed for parent key '$parentKey' (exit code $($export.ExitCode)). Aborting."
            } else {
                Write-Host "父键已导出到 $BackupFile。注意: 备份包含父键而非精确子键路径 / Parent key exported to $BackupFile. Note: backup contains parent key, not the exact subkey path."
                $exportTarget = $parentKey
            }
        } else {
            Write-ErrAndExit "reg export 失败且无父键可用。中止 / reg export failed and no parent key available. Aborting."
        }
    } catch {
        Write-ErrAndExit "reg export 失败且父键导出报错 / reg export failed and parent export attempt raised error: $_"
    }
} else {
    Write-Host "备份已导出 / Backup exported."
}

# Parse hive and subkey
if ($KeyPath -match '^(HKCU|HKLM|HKCR|HKU|HKCC):\\(.+)$') {
    $hive = $matches[1]
    $sub = $matches[2]
} else {
    Write-ErrAndExit "Invalid KeyPath format"
}

# Map hive to base key
switch ($hive) {
    'HKCU' { $base = [Microsoft.Win32.Registry]::CurrentUser }
    'HKLM' { $base = [Microsoft.Win32.Registry]::LocalMachine }
    'HKCR' { $base = [Microsoft.Win32.Registry]::ClassesRoot }
    'HKU'  { $base = [Microsoft.Win32.Registry]::Users }
    'HKCC' { $base = [Microsoft.Win32.Registry]::CurrentConfig }
    default { Write-ErrAndExit "Unsupported hive: $hive" }
}

# Open key for read/write
try {
    $key = $base.OpenSubKey($sub, $true)
} catch {
    Write-ErrAndExit "打开注册表项失败 / Failed to open registry key: $KeyPath. $_"
}
if (-not $key) { Write-ErrAndExit "未找到注册表项 / Registry key not found: $KeyPath" }

# Read existing value and kind
try {
    $currentValue = $key.GetValue($ValueName, $null)
    $currentKind = $key.GetValueKind($ValueName)
} catch {
    # If value does not exist GetValueKind throws. We'll treat as string by default.
    $currentValue = $null
    $currentKind = [Microsoft.Win32.RegistryValueKind]::String
}

Write-Host "当前值类型 / Current value kind: $currentKind"
if ($null -ne $currentValue) { Write-Host "当前值 (原始) / Current value (raw): $currentValue" } else { Write-Host "值原本不存在；将根据默认类型创建为 string 或 binary / Value did not exist previously; will create as string or binary based on default." }

# Attempt set
try {
    switch ($currentKind) {
        'Binary' {
            # Convert ASCII string to bytes
            $bytes = [System.Text.Encoding]::ASCII.GetBytes($valueToSet)
            $key.SetValue($ValueName, $bytes, [Microsoft.Win32.RegistryValueKind]::Binary)
        }
        'DWord' {
            # Try to parse integer from provided string
            $num = 0
            if ([int]::TryParse($valueToSet, [ref]$num)) {
                $key.SetValue($ValueName, $num, [Microsoft.Win32.RegistryValueKind]::DWord)
            } else {
                Write-Host "提供的值不是整数；改为按 string 写入（已备份原值） / Provided value is not an integer; writing as string instead (preserving original as backup)."
                $key.SetValue($ValueName, $valueToSet, [Microsoft.Win32.RegistryValueKind]::String)
            }
        }
        'ExpandString' {
            $key.SetValue($ValueName, $valueToSet, [Microsoft.Win32.RegistryValueKind]::String)
        }
        'MultiString' {
            $key.SetValue($ValueName, $valueToSet, [Microsoft.Win32.RegistryValueKind]::String)
        }
        'String' {
            $key.SetValue($ValueName, $valueToSet, [Microsoft.Win32.RegistryValueKind]::String)
        }
        default {
            # default to string
            $key.SetValue($ValueName, $valueToSet, [Microsoft.Win32.RegistryValueKind]::String)
        }
    }

    Write-Host "值已写入。正在校验 / Value written. Verifying..."
    $new = $key.GetValue($ValueName)
    $newKind = $key.GetValueKind($ValueName)
    Write-Host "回读类型 / Read back kind: $newKind"
    if ($newKind -eq [Microsoft.Win32.RegistryValueKind]::Binary) {
        # show as ASCII if printable
        try {
            $astext = [System.Text.Encoding]::ASCII.GetString($new)
            Write-Host "回读 (ASCII) / Read back (as ASCII): $astext"
        } catch { Write-Host "回读 (binary) / Read back (binary): $new" }
    } else { Write-Host "回读 / Read back: $new" }

    # If not disabled, set game defaults for all resolutions
    if (-not $NoGameDefaults) {
        Write-Host ""
        Set-GameDefaults -regKey $key -server $Server
    }

} catch {
    Write-Error "写入注册表值失败 / Failed to write registry value: $_"
    Write-Host "正在尝试从备份恢复 / Attempting to restore from backup: $BackupFile"
    if (Test-Path $BackupFile) {
        Start-Process -FilePath reg -ArgumentList "import `"$BackupFile`"" -NoNewWindow -Wait
        Write-Host "已尝试恢复 / Restore attempted."
    }
    exit 1
}

Write-Host "完成 / Done."