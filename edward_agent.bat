@echo off
chcp 65001 >nul
echo ==========================================
echo Запуск Edward Voice Assistant
echo ==========================================

:: Переход в папку со скриптом
cd /d "O:\Project\VOICE\edward-agent\openWakeWord"
echo Папка проекта: %CD%

:: Проверка наличия venv (на уровень выше!)
if not exist "..\venv\Scripts\python.exe" (
    echo ОШИБКА: venv не найден в O:\Project\VOICE\edward-agent\venv
    pause
    exit /b 1
)

:: Проверка наличия модели Vosk
if not exist "vosk-model-small-ru-0.22" (
    echo ОШИБКА: Модель Vosk не найдена!
    pause
    exit /b 1
)

:: Запуск Python из venv (на уровень выше)
echo Запуск Эдварда...
"..\venv\Scripts\python.exe" -u edward_agent.py

:: Если что-то пошло не так
echo.
echo ==========================================
echo Эдвард завершился!
echo ==========================================
pause