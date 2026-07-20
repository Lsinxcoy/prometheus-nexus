# register Ultra 9200 scheduled tasks via PowerShell (ASCII-only XML)
$ErrorActionPreference = "Stop"

$startupXml = @'
<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo><Date>2026-07-17T00:00:00</Date><Author>41228</Author>
    <Description>Ultra API 9200 startup on logon</Description></RegistrationInfo>
  <Triggers><LogonTrigger><Enabled>true</Enabled></LogonTrigger></Triggers>
  <Principals><Principal id="Author"><LogonType>InteractiveToken</LogonType>
    <RunLevel>LeastPrivilege</RunLevel></Principal></Principals>
  <Settings><MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <AllowHardTerminate>true</AllowHardTerminate>
    <StartWhenAvailable>true</StartWhenAvailable>
    <Enabled>true</Enabled><Hidden>false</Hidden>
    <RunOnlyIfIdle>false</RunOnlyIfIdle><WakeToRun>false</WakeToRun>
    <ExecutionTimeLimit>PT0S</ExecutionTimeLimit><Priority>7</Priority></Settings>
  <Actions Context="Author"><Exec>
    <Command>E:\Prometheus-Ultra-MultiTypeKB\ultra_start.bat</Command>
  </Exec></Actions>
</Task>
'@

$keepaliveXml = @'
<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo><Date>2026-07-17T00:00:00</Date><Author>41228</Author>
    <Description>Ultra API 9200 keepalive every 5 min</Description></RegistrationInfo>
  <Triggers><TimeTrigger><Repetition><Interval>PT5M</Interval>
    <Duration>PT24H</Duration><StopAtDurationEnd>false</StopAtDurationEnd></Repetition>
    <StartBoundary>2026-07-17T00:00:00</StartBoundary><Enabled>true</Enabled></TimeTrigger></Triggers>
  <Principals><Principal id="Author"><LogonType>InteractiveToken</LogonType>
    <RunLevel>LeastPrivilege</RunLevel></Principal></Principals>
  <Settings><MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <AllowHardTerminate>true</AllowHardTerminate>
    <StartWhenAvailable>true</StartWhenAvailable>
    <Enabled>true</Enabled><Hidden>false</Hidden>
    <RunOnlyIfIdle>false</RunOnlyIfIdle><WakeToRun>false</WakeToRun>
    <ExecutionTimeLimit>PT1M</ExecutionTimeLimit><Priority>7</Priority></Settings>
  <Actions Context="Author"><Exec>
    <Command>E:\Prometheus-Ultra-MultiTypeKB\.venv\Scripts\python.exe</Command>
    <Arguments>E:\Prometheus-Ultra-MultiTypeKB\scripts\ultra_keepalive.py --once</Arguments>
  </Exec></Actions>
</Task>
'@

$startupXml | Out-File -FilePath "$env:TEMP\ultra_startup_task.xml" -Encoding unicode
$keepaliveXml | Out-File -FilePath "$env:TEMP\ultra_keepalive_task.xml" -Encoding unicode

Register-ScheduledTask -TaskName "Ultra_API_9200_Startup" -Xml (Get-Content "$env:TEMP\ultra_startup_task.xml" -Raw) -Force
Register-ScheduledTask -TaskName "Ultra_API_9200_Keepalive" -Xml (Get-Content "$env:TEMP\ultra_keepalive_task.xml" -Raw) -Force
Write-Host "REGISTERED OK"
