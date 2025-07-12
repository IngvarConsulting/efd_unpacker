# Скрипт для проверки и настройки WiX Toolset
param(
    [switch]$Verbose
)

Write-Host "=== Проверка WiX Toolset ===" -ForegroundColor Cyan

# Функция для вывода отладочной информации
function Write-Debug {
    param([string]$Message)
    if ($Verbose) {
        Write-Host "DEBUG: $Message" -ForegroundColor Yellow
    }
}

# Проверяем WiX в PATH
Write-Host "1. Проверяем WiX в PATH..." -ForegroundColor Green
$candleInPath = Get-Command candle -ErrorAction SilentlyContinue
$lightInPath = Get-Command light -ErrorAction SilentlyContinue

if ($candleInPath) {
    Write-Host "✓ candle найден в PATH: $($candleInPath.Source)" -ForegroundColor Green
} else {
    Write-Host "✗ candle не найден в PATH" -ForegroundColor Red
}

if ($lightInPath) {
    Write-Host "✓ light найден в PATH: $($lightInPath.Source)" -ForegroundColor Green
} else {
    Write-Host "✗ light не найден в PATH" -ForegroundColor Red
}

# Если WiX не найден в PATH, пробуем обновить PATH
if (-not $candleInPath -or -not $lightInPath) {
    Write-Host "2. Обновляем PATH..." -ForegroundColor Green
    try {
        $machinePath = [System.Environment]::GetEnvironmentVariable("PATH", "Machine")
        $userPath = [System.Environment]::GetEnvironmentVariable("PATH", "User")
        $env:PATH = "$machinePath;$userPath"
        Write-Host "✓ PATH обновлен" -ForegroundColor Green
        
        # Проверяем снова
        $candleInPath = Get-Command candle -ErrorAction SilentlyContinue
        $lightInPath = Get-Command light -ErrorAction SilentlyContinue
        
        if ($candleInPath) {
            Write-Host "✓ candle найден после обновления PATH: $($candleInPath.Source)" -ForegroundColor Green
        }
        if ($lightInPath) {
            Write-Host "✓ light найден после обновления PATH: $($lightInPath.Source)" -ForegroundColor Green
        }
    } catch {
        Write-Host "✗ Ошибка обновления PATH: $($_.Exception.Message)" -ForegroundColor Red
    }
}

# Проверяем стандартные пути установки
Write-Host "3. Проверяем стандартные пути установки..." -ForegroundColor Green
$wixPaths = @(
    "C:\Program Files (x86)\WiX Toolset v3.11\bin",
    "C:\Program Files\WiX Toolset v3.14\bin", 
    "C:\Program Files\WiX Toolset v3.15\bin",
    "C:\Program Files\WiX Toolset v3.11\bin",
    "C:\Program Files\WiX Toolset\bin"
)

$foundPaths = @()
foreach ($path in $wixPaths) {
    if (Test-Path $path) {
        $foundPaths += $path
        Write-Host "✓ Найден путь: $path" -ForegroundColor Green
    } else {
        Write-Debug "Путь не найден: $path"
    }
}

# Тестируем WiX команды
Write-Host "4. Тестируем WiX команды..." -ForegroundColor Green
$wixWorking = $false

if ($candleInPath -and $lightInPath) {
    try {
        $candleOutput = & $candleInPath.Source -version 2>&1
        if ($LASTEXITCODE -eq 0) {
            Write-Host "✓ candle.exe работает" -ForegroundColor Green
            Write-Debug "Версия candle: $candleOutput"
            
            $lightOutput = & $lightInPath.Source -version 2>&1
            if ($LASTEXITCODE -eq 0) {
                Write-Host "✓ light.exe работает" -ForegroundColor Green
                Write-Debug "Версия light: $lightOutput"
                $wixWorking = $true
            } else {
                Write-Host "✗ light.exe не работает" -ForegroundColor Red
            }
        } else {
            Write-Host "✗ candle.exe не работает" -ForegroundColor Red
        }
    } catch {
        Write-Host "✗ Ошибка тестирования WiX: $($_.Exception.Message)" -ForegroundColor Red
    }
} else {
    Write-Host "✗ WiX команды не найдены в PATH" -ForegroundColor Red
}

# Выводим итоговую информацию
Write-Host "=== Результат проверки ===" -ForegroundColor Cyan
if ($wixWorking) {
    Write-Host "✓ WiX Toolset готов к использованию" -ForegroundColor Green
    Write-Host "candle: $($candleInPath.Source)" -ForegroundColor White
    Write-Host "light: $($lightInPath.Source)" -ForegroundColor White
    exit 0
} else {
    Write-Host "✗ WiX Toolset не готов к использованию" -ForegroundColor Red
    Write-Host "Найденные пути: $($foundPaths -join ', ')" -ForegroundColor Yellow
    exit 1
} 