#Requires -Version 5.1
<#
.SYNOPSIS
    OmniCapital v1.0 - Monitor de Algoritmo en Vivo
.DESCRIPTION
    Script de PowerShell para monitorear la ejecución del algoritmo de trading
    en tiempo real con actualizaciones periódicas.
.PARAMETER Mode
    Modo de ejecución: Dashboard, Analysis, Monitor, Backtest
.PARAMETER Interval
    Intervalo de actualización en segundos (solo modo Monitor)
.PARAMETER Symbols
    Lista de símbolos separados por coma
.EXAMPLE
    .\LiveMonitor.ps1 -Mode Dashboard
    .\LiveMonitor.ps1 -Mode Monitor -Interval 60
    .\LiveMonitor.ps1 -Mode Analysis -Symbols "AAPL,MSFT,GOOGL"
#>

[CmdletBinding()]
param(
    [Parameter()]
    [ValidateSet("Dashboard", "Analysis", "Monitor", "Backtest", "Menu")]
    [string]$Mode = "Menu",
    
    [Parameter()]
    [int]$Interval = 60,
    
    [Parameter()]
    [string]$Symbols = ""
)

# Configuración
$script:Version = "1.0.0"
$script:BasePath = $PSScriptRoot
$script:LogPath = Join-Path $script:BasePath "logs"
$script:ReportsPath = Join-Path $script:BasePath "reports"

# Crear directorios necesarios
function Initialize-Directories {
    @("logs", "data", "reports", "backtests") | ForEach-Object {
        $dir = Join-Path $script:BasePath $_
        if (!(Test-Path $dir)) {
            New-Item -ItemType Directory -Path $dir -Force | Out-Null
        }
    }
}

# Verificar Python
function Test-PythonInstallation {
    try {
        $pythonVersion = python --version 2>&1
        if ($pythonVersion -match "Python (") {
            Write-Host "    [✓] Python detectado: $pythonVersion" -ForegroundColor Green
            return $true
        }
    }
    catch {
        Write-Host "    [✗] Python no está instalado o no está en el PATH" -ForegroundColor Red
        Write-Host "    Por favor instala Python 3.11+ desde https://python.org" -ForegroundColor Yellow
        return $false
    }
    return $false
}

# Mostrar banner
function Show-Banner {
    Clear-Host
    Write-Host ""
    Write-Host "    ██████╗ ███╗   ███╗███╗   ██╗██╗ ██████╗ █████╗ ██████╗ ██╗████████╗ █████╗ ██╗     " -ForegroundColor Cyan
    Write-Host "    ██╔═══██╗████╗ ████║████╗  ██║██║██╔════╝██╔══██╗██╔══██╗██║╚══██╔══╝██╔══██╗██║     " -ForegroundColor Cyan
    Write-Host "    ██║   ██║██╔████╔██║██╔██╗ ██║██║██║     ███████║██████╔╝██║   ██║   ███████║██║     " -ForegroundColor Cyan
    Write-Host "    ██║   ██║██║╚██╔╝██║██║╚██╗██║██║██║     ██╔══██║██╔══██╗██║   ██║   ██╔══██║██║     " -ForegroundColor Cyan
    Write-Host "    ╚██████╔╝██║ ╚═╝ ██║██║ ╚████║██║╚██████╗██║  ██║██║  ██║██║   ██║   ██║  ██║███████╗" -ForegroundColor Cyan
    Write-Host "     ╚═════╝ ╚═╝     ╚═╝╚═╝  ╚═══╝╚═╝ ╚═════╝╚═╝  ╚═╝╚═╝  ╚═╝╚═╝   ╚═╝   ╚═╝  ╚═╝╚══════╝" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "    ═══════════════════════════════════════════════════════════════════════════════════" -ForegroundColor White
    Write-Host "    ALPHAMAX OMNICAPITAL v$script:Version - Sistema de Trading" -ForegroundColor Yellow
    Write-Host "    ═══════════════════════════════════════════════════════════════════════════════════" -ForegroundColor White
    Write-Host ""
}

# Menú principal
function Show-Menu {
    Show-Banner
    Write-Host "    Selecciona una opción:" -ForegroundColor White
    Write-Host ""
    Write-Host "    [1] 📊 Dashboard de Monitoreo (Interfaz Web)" -ForegroundColor Green
    Write-Host "    [2] 🔍 Análisis de Mercado en Vivo" -ForegroundColor Cyan
    Write-Host "    [3] 📡 Monitor Continuo (Actualización periódica)" -ForegroundColor Magenta
    Write-Host "    [4] 📈 Trading en Vivo / Simulado" -ForegroundColor Yellow
    Write-Host "    [5] 📉 Backtest Histórico" -ForegroundColor Blue
    Write-Host "    [6] 📋 Ver Reportes Generados" -ForegroundColor White
    Write-Host "    [7] ⚙️  Ver Logs de Ejecución" -ForegroundColor Gray
    Write-Host "    [8] ❌ Salir" -ForegroundColor Red
    Write-Host ""
    Write-Host "    ═══════════════════════════════════════════════════════════════════════════════════" -ForegroundColor White
    
    $choice = Read-Host "    Opción"
    
    switch ($choice) {
        "1" { Start-Dashboard }
        "2" { Start-Analysis }
        "3" { Start-Monitor }
        "4" { Start-Trading }
        "5" { Start-Backtest }
        "6" { Show-Reports }
        "7" { Show-Logs }
        "8" { Exit-Application }
        default { 
            Write-Host "    Opción inválida. Presiona Enter para continuar..." -ForegroundColor Red
            Read-Host
            Show-Menu 
        }
    }
}

# Modo Dashboard
function Start-Dashboard {
    Show-Banner
    Write-Host "    ═══════════════════════════════════════════════════════════════════════════════════" -ForegroundColor White
    Write-Host "    📊 LANZANDO DASHBOARD DE MONITOREO" -ForegroundColor Green
    Write-Host "    ═══════════════════════════════════════════════════════════════════════════════════" -ForegroundColor White
    Write-Host ""
    Write-Host "    El dashboard se abrirá en tu navegador web." -ForegroundColor Yellow
    Write-Host "    URL: http://localhost:8501" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "    Para detener el dashboard, presiona Ctrl+C en esta ventana." -ForegroundColor Gray
    Write-Host ""
    Write-Host "    ═══════════════════════════════════════════════════════════════════════════════════" -ForegroundColor White
    Write-Host ""
    
    try {
        python -m streamlit run dashboard.py
    }
    catch {
        Write-Host "    [✗] Error al lanzar el dashboard: $_" -ForegroundColor Red
        Write-Host "    Asegúrate de tener streamlit instalado: pip install streamlit" -ForegroundColor Yellow
    }
    
    Write-Host ""
    Read-Host "    Presiona Enter para volver al menú"
    Show-Menu
}

# Modo Análisis
function Start-Analysis {
    Show-Banner
    Write-Host "    ═══════════════════════════════════════════════════════════════════════════════════" -ForegroundColor White
    Write-Host "    🔍 ANÁLISIS DE MERCADO EN VIVO" -ForegroundColor Cyan
    Write-Host "    ═══════════════════════════════════════════════════════════════════════════════════" -ForegroundColor White
    Write-Host ""
    
    $timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
    $logFile = Join-Path $script:LogPath "analisis_$timestamp.log"
    
    Write-Host "    Ejecutando análisis completo de oportunidades de inversión..." -ForegroundColor Yellow
    Write-Host "    Log: $logFile" -ForegroundColor Gray
    Write-Host ""
    
    try {
        python omnicapital_v1_live.py 2>&1 | Tee-Object -FilePath $logFile
        
        Write-Host ""
        Write-Host "    ═══════════════════════════════════════════════════════════════════════════════════" -ForegroundColor White
        Write-Host "    [✓] ANÁLISIS COMPLETADO EXITOSAMENTE" -ForegroundColor Green
        Write-Host "    ═══════════════════════════════════════════════════════════════════════════════════" -ForegroundColor White
        Write-Host ""
        Write-Host "    Los resultados se han guardado en la carpeta 'reports'" -ForegroundColor Yellow
        Write-Host "    Log guardado en: $logFile" -ForegroundColor Gray
    }
    catch {
        Write-Host ""
        Write-Host "    ═══════════════════════════════════════════════════════════════════════════════════" -ForegroundColor White
        Write-Host "    [✗] ERROR: El análisis falló" -ForegroundColor Red
        Write-Host "    ═══════════════════════════════════════════════════════════════════════════════════" -ForegroundColor White
        Write-Host ""
        Write-Host "    Error: $_" -ForegroundColor Red
        Write-Host "    Revisa el log: $logFile" -ForegroundColor Yellow
    }
    
    Write-Host ""
    Read-Host "    Presiona Enter para volver al menú"
    Show-Menu
}

# Modo Monitor Continuo
function Start-Monitor {
    Show-Banner
    Write-Host "    ═══════════════════════════════════════════════════════════════════════════════════" -ForegroundColor White
    Write-Host "    📡 MONITOR CONTINUO EN TIEMPO REAL" -ForegroundColor Magenta
    Write-Host "    ═══════════════════════════════════════════════════════════════════════════════════" -ForegroundColor White
    Write-Host ""
    
    $intervalInput = Read-Host "    Intervalo de actualización en segundos (default: 60)"
    if ([string]::IsNullOrWhiteSpace($intervalInput)) {
        $intervalInput = 60
    }
    
    $symbolsInput = Read-Host "    Símbolos específicos (opcional, separados por coma)"
    
    $args = @("--interval", $intervalInput)
    if (![string]::IsNullOrWhiteSpace($symbolsInput)) {
        $symbolsArray = $symbolsInput -split ","
        $args += "--symbols"
        $args += $symbolsArray
    }
    
    Write-Host ""
    Write-Host "    Iniciando monitor con intervalo de $intervalInput segundos..." -ForegroundColor Yellow
    Write-Host "    Presiona Ctrl+C para detener" -ForegroundColor Gray
    Write-Host ""
    
    try {
        python live_monitor.py @args
    }
    catch {
        Write-Host ""
        Write-Host "    Monitor detenido." -ForegroundColor Yellow
    }
    
    Write-Host ""
    Read-Host "    Presiona Enter para volver al menú"
    Show-Menu
}

# Modo Trading
function Start-Trading {
    Show-Banner
    Write-Host "    ═══════════════════════════════════════════════════════════════════════════════════" -ForegroundColor White
    Write-Host "    📈 TRADING EN VIVO / SIMULADO" -ForegroundColor Yellow
    Write-Host "    ═══════════════════════════════════════════════════════════════════════════════════" -ForegroundColor White
    Write-Host ""
    Write-Host "    ⚠️  ADVERTENCIA: Este modo ejecutará el algoritmo de trading." -ForegroundColor Red
    Write-Host ""
    Write-Host "    [1] Análisis simulado (sin ejecución de trades)" -ForegroundColor Green
    Write-Host "    [2] Trading en vivo (requiere configuración de broker)" -ForegroundColor Red
    Write-Host "    [3] Volver al menú" -ForegroundColor Gray
    Write-Host ""
    
    $choice = Read-Host "    Opción"
    
    switch ($choice) {
        "1" {
            Write-Host ""
            Write-Host "    Ejecutando trading simulado..." -ForegroundColor Yellow
            python src/main.py --mode live
            Write-Host ""
            Write-Host "    [✓] Trading simulado completado." -ForegroundColor Green
        }
        "2" {
            Write-Host ""
            Write-Host "    ⚠️  MODO TRADING EN VIVO" -ForegroundColor Red
            Write-Host "    Esta función requiere configuración adicional del broker." -ForegroundColor Yellow
            Write-Host "    Por favor revisa la documentación en OMNICAPITAL_v1.0_README.md" -ForegroundColor Gray
        }
    }
    
    Write-Host ""
    Read-Host "    Presiona Enter para volver al menú"
    Show-Menu
}

# Modo Backtest
function Start-Backtest {
    Show-Banner
    Write-Host "    ═══════════════════════════════════════════════════════════════════════════════════" -ForegroundColor White
    Write-Host "    📉 BACKTEST HISTÓRICO" -ForegroundColor Blue
    Write-Host "    ═══════════════════════════════════════════════════════════════════════════════════" -ForegroundColor White
    Write-Host ""
    
    $startDate = Read-Host "    Fecha inicio (YYYY-MM-DD)"
    $endDate = Read-Host "    Fecha fin (YYYY-MM-DD)"
    
    if ([string]::IsNullOrWhiteSpace($startDate)) {
        $startDate = (Get-Date).AddYears(-2).ToString("yyyy-MM-dd")
    }
    if ([string]::IsNullOrWhiteSpace($endDate)) {
        $endDate = Get-Date -Format "yyyy-MM-dd"
    }
    
    Write-Host ""
    Write-Host "    Ejecutando backtest desde $startDate hasta $endDate..." -ForegroundColor Yellow
    Write-Host ""
    
    try {
        python src/main.py --mode backtest --start-date $startDate --end-date $endDate
        
        Write-Host ""
        Write-Host "    [✓] Backtest completado." -ForegroundColor Green
        Write-Host "    Los resultados se han guardado en la carpeta 'backtests'" -ForegroundColor Yellow
    }
    catch {
        Write-Host ""
        Write-Host "    [✗] Error en el backtest: $_" -ForegroundColor Red
    }
    
    Write-Host ""
    Read-Host "    Presiona Enter para volver al menú"
    Show-Menu
}

# Mostrar reportes
function Show-Reports {
    Show-Banner
    Write-Host "    ═══════════════════════════════════════════════════════════════════════════════════" -ForegroundColor White
    Write-Host "    📋 REPORTES GENERADOS" -ForegroundColor White
    Write-Host "    ═══════════════════════════════════════════════════════════════════════════════════" -ForegroundColor White
    Write-Host ""
    
    $reports = Get-ChildItem -Path $script:ReportsPath -File | Sort-Object LastWriteTime -Descending
    
    if ($reports.Count -eq 0) {
        Write-Host "    No hay reportes generados." -ForegroundColor Yellow
    }
    else {
        Write-Host "    Archivos en $($script:ReportsPath):" -ForegroundColor Cyan
        Write-Host ""
        
        $index = 1
        $reports | Select-Object -First 20 | ForEach-Object {
            Write-Host "    [$index] $($_.Name) - $($_.LastWriteTime)" -ForegroundColor White
            $index++
        }
        
        Write-Host ""
        $fileName = Read-Host "    Escribe el nombre del archivo para abrir (o Enter para volver)"
        
        if (![string]::IsNullOrWhiteSpace($fileName)) {
            $filePath = Join-Path $script:ReportsPath $fileName
            if (Test-Path $filePath) {
                Invoke-Item $filePath
            }
            else {
                Write-Host "    [✗] Archivo no encontrado" -ForegroundColor Red
                Start-Sleep -Seconds 2
            }
        }
    }
    
    Show-Menu
}

# Mostrar logs
function Show-Logs {
    Show-Banner
    Write-Host "    ═══════════════════════════════════════════════════════════════════════════════════" -ForegroundColor White
    Write-Host "    ⚙️  LOGS DE EJECUCIÓN" -ForegroundColor Gray
    Write-Host "    ═══════════════════════════════════════════════════════════════════════════════════" -ForegroundColor White
    Write-Host ""
    
    $logs = Get-ChildItem -Path $script:LogPath -File | Sort-Object LastWriteTime -Descending
    
    if ($logs.Count -eq 0) {
        Write-Host "    No hay logs disponibles." -ForegroundColor Yellow
    }
    else {
        Write-Host "    Archivos en $($script:LogPath):" -ForegroundColor Cyan
        Write-Host ""
        
        $index = 1
        $logs | Select-Object -First 20 | ForEach-Object {
            Write-Host "    [$index] $($_.Name) - $($_.LastWriteTime)" -ForegroundColor White
            $index++
        }
        
        Write-Host ""
        $fileName = Read-Host "    Escribe el nombre del archivo para ver (o Enter para volver)"
        
        if (![string]::IsNullOrWhiteSpace($fileName)) {
            $filePath = Join-Path $script:LogPath $fileName
            if (Test-Path $filePath) {
                Get-Content $filePath | More
            }
            else {
                Write-Host "    [✗] Archivo no encontrado" -ForegroundColor Red
                Start-Sleep -Seconds 2
            }
        }
    }
    
    Show-Menu
}

# Salir
function Exit-Application {
    Show-Banner
    Write-Host "    ═══════════════════════════════════════════════════════════════════════════════════" -ForegroundColor White
    Write-Host "    ¡Gracias por usar OmniCapital v$script:Version!" -ForegroundColor Green
    Write-Host "    ═══════════════════════════════════════════════════════════════════════════════════" -ForegroundColor White
    Write-Host ""
    Start-Sleep -Seconds 2
    exit
}

# Ejecución principal
function Main {
    Initialize-Directories
    
    if (!(Test-PythonInstallation)) {
        Read-Host "    Presiona Enter para salir"
        exit 1
    }
    
    switch ($Mode) {
        "Dashboard" { Start-Dashboard }
        "Analysis" { Start-Analysis }
        "Monitor" { 
            $args = @("--interval", $Interval)
            if (![string]::IsNullOrWhiteSpace($Symbols)) {
                $symbolsArray = $Symbols -split ","
                $args += "--symbols"
                $args += $symbolsArray
            }
            python live_monitor.py @args
        }
        "Backtest" { Start-Backtest }
        default { Show-Menu }
    }
}

# Ejecutar
Main
