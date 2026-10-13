@echo off
rem Alternativa al cloud: pubblica dal tuo PC (deve essere acceso). Controlla ogni 30 minuti.
schtasks /Create /SC MINUTE /MO 30 /TN "SDB-Instagram" /TR "cmd /c cd /d %~dp0 && python -m mkt publish --live >> publish.log 2>&1" /F
echo Attivita pianificata creata. Per toglierla: schtasks /Delete /TN "SDB-Instagram" /F
pause
