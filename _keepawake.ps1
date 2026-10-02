# Mantem o sistema acordado (sem hibernacao/standby/sleep) enquanto este processo correr.
$sig = @'
[DllImport("kernel32.dll")]public static extern uint SetThreadExecutionState(uint es);
'@
Add-Type -MemberDefinition $sig -Name System -Namespace Win32
while ($true) {
    # ES_CONTINUOUS | ES_SYSTEM_REQUIRED | ES_AWAYMODE_REQUIRED | ES_DISPLAY_REQUIRED
    [void][Win32.System]::SetThreadExecutionState(0x8000000B)
    Start-Sleep -Seconds 30
}
