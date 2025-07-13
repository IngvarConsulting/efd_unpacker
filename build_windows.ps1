# PowerShell script for building EFD Unpacker for Windows

Write-Host "Building EFD Unpacker for Windows..." -ForegroundColor Green

# Read version from file
if (Test-Path "version.txt") {
    $VERSION = (Get-Content "version.txt").Trim()
    Write-Host "Version from version.txt: $VERSION" -ForegroundColor Green
} else {
    Write-Host "Error: version.txt not found." -ForegroundColor Red
    Write-Host "This file should be created automatically by GitHub Actions from the git tag." -ForegroundColor Yellow
    Write-Host "For local builds, please create version.txt with the version number." -ForegroundColor Yellow
    Write-Host "Example: '1.0.0' | Out-File -FilePath 'version.txt' -Encoding UTF8" -ForegroundColor Yellow
    exit 1
}

# Check if Python is installed
try {
    $pythonVersion = python --version 2>&1
    Write-Host "Found Python: $pythonVersion" -ForegroundColor Green
} catch {
    Write-Host "Error: Python not found. Please install Python 3." -ForegroundColor Red
    exit 1
}

# Check if PyInstaller is installed
try {
    python -c "import PyInstaller" 2>$null
    Write-Host "PyInstaller found" -ForegroundColor Green
} catch {
    Write-Host "Installing PyInstaller..." -ForegroundColor Yellow
    pip install pyinstaller
}

# Check WiX Toolset using dedicated script
Write-Host "Checking WiX Toolset..." -ForegroundColor Yellow
$wixAvailable = $false
$candle = $null
$light = $null

if (Test-Path "scripts\check_wix.ps1") {
    & "scripts\check_wix.ps1"
    $wixAvailable = $LASTEXITCODE -eq 0
    
    if ($wixAvailable) {
        # Get paths from successful check
        $candleInPath = Get-Command candle -ErrorAction SilentlyContinue
        $lightInPath = Get-Command light -ErrorAction SilentlyContinue
        if ($candleInPath -and $lightInPath) {
            $candle = $candleInPath.Source
            $light = $lightInPath.Source
        }
    }
} else {
    Write-Host "Warning: check_wix.ps1 not found, using fallback detection" -ForegroundColor Yellow
}

# Fallback WiX detection if script failed or not found
if (-not $wixAvailable) {
    Write-Host "Using fallback WiX detection..." -ForegroundColor Yellow
    
    $wixPaths = @(
        "C:\Program Files (x86)\WiX Toolset v3.11\bin",
        "C:\Program Files\WiX Toolset v3.14\bin", 
        "C:\Program Files\WiX Toolset v3.15\bin",
        "C:\Program Files\WiX Toolset v3.11\bin",
        "C:\Program Files\WiX Toolset\bin"
    )
    
    $candleInPath = Get-Command candle -ErrorAction SilentlyContinue
    $lightInPath = Get-Command light -ErrorAction SilentlyContinue
    
    if ($candleInPath -and $lightInPath) {
        $candle = $candleInPath.Source
        $light = $lightInPath.Source
        $wixAvailable = $true
    } else {
        $wixBin = $wixPaths | Where-Object { Test-Path $_ } | Select-Object -First 1
        if ($wixBin) {
            $candle = Join-Path $wixBin "candle.exe"
            $light = Join-Path $wixBin "light.exe"
            $wixAvailable = Test-Path $candle -and Test-Path $light
        }
    }
}

if ($wixAvailable) {
    Write-Host "WiX Toolset is available" -ForegroundColor Green
    Write-Host "candle: $candle" -ForegroundColor White
    Write-Host "light: $light" -ForegroundColor White
} else {
    Write-Host "Warning: WiX Toolset not found. MSI installer will not be created." -ForegroundColor Yellow
    Write-Host "Download from: https://wixtoolset.org/releases/" -ForegroundColor Yellow
    Write-Host "Or install via Chocolatey: choco install wixtoolset" -ForegroundColor Yellow
}

# Check for icon
$iconOption = ""
if (Test-Path "resources\icon.ico") {
    $iconOption = "--icon=resources\icon.ico"
    Write-Host "Using custom icon: resources\icon.ico" -ForegroundColor Green
} else {
    Write-Host "Warning: resources\icon.ico not found. Using default icon." -ForegroundColor Yellow
}

# Clean previous builds
Write-Host "Cleaning previous builds..." -ForegroundColor Yellow
if (Test-Path "build") {
    Remove-Item -Recurse -Force "build"
}
if (Test-Path "dist") {
    Remove-Item -Recurse -Force "dist"
}

# Build executable
Write-Host "Building executable..." -ForegroundColor Yellow
pyinstaller --noconfirm --onefile --windowed $iconOption --name=EFDUnpacker main.py

if ($LASTEXITCODE -ne 0) {
    Write-Host "Error: PyInstaller build failed." -ForegroundColor Red
    exit 1
}

Write-Host "Executable created successfully" -ForegroundColor Green

# Check if executable was created
if (-not (Test-Path "dist\EFDUnpacker.exe")) {
    Write-Host "Error: EFDUnpacker.exe not found in dist directory." -ForegroundColor Red
    exit 1
}

# Create installer if WiX is available
if ($wixAvailable) {
    Write-Host "Creating MSI installer..." -ForegroundColor Yellow
    
    # Replace version placeholder in installer.wxs
    Write-Host "Updating version in installer.wxs..." -ForegroundColor Yellow
    $wxsContent = Get-Content "installer.wxs" -Raw
    $wxsContent = $wxsContent -replace "VERSION_PLACEHOLDER", $VERSION
    Set-Content "installer.wxs" $wxsContent -NoNewline
    
    # Compile WiX source
    & $candle installer.wxs -out installer.wixobj
    if ($LASTEXITCODE -ne 0) {
        Write-Host "Error: WiX compilation failed." -ForegroundColor Red
        exit 1
    }
    
    # Link WiX object with both localizations (multi-language MSI)
    & $light installer.wixobj -out dist\efd-unpacker-$VERSION-windows.msi -cultures:en-us,ru-ru
    if ($LASTEXITCODE -ne 0) {
        Write-Host "Error: WiX linking failed." -ForegroundColor Red
        exit 1
    }
    
    # Clean up WiX files
    Remove-Item "installer.wixobj" -ErrorAction SilentlyContinue
    
    # Restore original installer.wxs
    git checkout installer.wxs
}

# Create ZIP archive (portable)
Write-Host "Creating ZIP archive..." -ForegroundColor Yellow
$portableFiles = @("dist\EFDUnpacker.exe")
Compress-Archive -Path $portableFiles -DestinationPath "dist\efd-unpacker-$VERSION-windows-portable.zip" -Force

# Show results
Write-Host ""
Write-Host "Build completed successfully!" -ForegroundColor Green
Write-Host "Files created:" -ForegroundColor White
Write-Host "  - dist\EFDUnpacker.exe (executable)"
if (Test-Path "dist\efd-unpacker-$VERSION-windows.msi") {
    Write-Host "  - dist\efd-unpacker-$VERSION-windows.msi (installer)"
}
Write-Host "  - dist\efd-unpacker-$VERSION-windows-portable.zip (portable version)"

# Show file sizes
Write-Host ""
Write-Host "File sizes:" -ForegroundColor White
if (Test-Path "dist\EFDUnpacker.exe") {
    $exeSize = (Get-Item "dist\EFDUnpacker.exe").Length / 1MB
    Write-Host "  Executable: $([math]::Round($exeSize, 1))MB"
}
if (Test-Path "dist\efd-unpacker-$VERSION-windows.msi") {
    $msiSize = (Get-Item "dist\efd-unpacker-$VERSION-windows.msi").Length / 1MB
    Write-Host "  MSI installer: $([math]::Round($msiSize, 1))MB"
}
if (Test-Path "dist\efd-unpacker-$VERSION-windows-portable.zip") {
    $zipSize = (Get-Item "dist\efd-unpacker-$VERSION-windows-portable.zip").Length / 1MB
    Write-Host "  ZIP archive: $([math]::Round($zipSize, 1))MB"
}

Write-Host ""
Write-Host "You can now distribute:" -ForegroundColor White
if (Test-Path "dist\efd-unpacker-$VERSION-windows.msi") {
    Write-Host "  - efd-unpacker-$VERSION-windows.msi for easy installation"
}
Write-Host "  - efd-unpacker-$VERSION-windows-portable.zip for portable use"
Write-Host ""
Write-Host "File association features:" -ForegroundColor White
Write-Host "  - .efd files will be associated with EFD Unpacker"
Write-Host "  - Double-clicking .efd files will open them in the app"
Write-Host "  - Files will be automatically selected for unpacking" 