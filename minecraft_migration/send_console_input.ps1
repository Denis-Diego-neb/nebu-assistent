param(
    [Parameter(Mandatory = $true)][int]$TargetProcessId,
    [string[]]$Commands,
    [string]$CommandFile
)

$ErrorActionPreference = "Stop"

Add-Type -TypeDefinition @'
using System;
using System.ComponentModel;
using System.Runtime.InteropServices;

public static class ConsoleInputSender
{
    private const int STD_INPUT_HANDLE = -10;
    private const ushort KEY_EVENT = 0x0001;

    [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
    private struct KEY_EVENT_RECORD
    {
        [MarshalAs(UnmanagedType.Bool)] public bool KeyDown;
        public ushort RepeatCount;
        public ushort VirtualKeyCode;
        public ushort VirtualScanCode;
        public char UnicodeChar;
        public uint ControlKeyState;
    }

    [StructLayout(LayoutKind.Explicit, CharSet = CharSet.Unicode)]
    private struct INPUT_RECORD
    {
        [FieldOffset(0)] public ushort EventType;
        [FieldOffset(4)] public KEY_EVENT_RECORD KeyEvent;
    }

    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern bool FreeConsole();

    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern bool AttachConsole(uint processId);

    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern IntPtr GetStdHandle(int standardHandle);

    [DllImport("kernel32.dll", SetLastError = true, CharSet = CharSet.Unicode)]
    private static extern bool WriteConsoleInputW(IntPtr input, INPUT_RECORD[] buffer, uint length, out uint written);

    public static void Send(int processId, string command)
    {
        FreeConsole();
        if (!AttachConsole((uint)processId))
            throw new Win32Exception(Marshal.GetLastWin32Error(), "Nao foi possivel anexar ao console do servidor");

        IntPtr input = GetStdHandle(STD_INPUT_HANDLE);
        string text = command + "\r";
        INPUT_RECORD[] records = new INPUT_RECORD[text.Length * 2];
        int index = 0;
        foreach (char character in text)
        {
            records[index++] = CreateRecord(character, true);
            records[index++] = CreateRecord(character, false);
        }
        uint written;
        if (!WriteConsoleInputW(input, records, (uint)records.Length, out written))
            throw new Win32Exception(Marshal.GetLastWin32Error(), "Nao foi possivel escrever no console do servidor");
    }

    private static INPUT_RECORD CreateRecord(char character, bool keyDown)
    {
        INPUT_RECORD record = new INPUT_RECORD();
        record.EventType = KEY_EVENT;
        record.KeyEvent.KeyDown = keyDown;
        record.KeyEvent.RepeatCount = 1;
        record.KeyEvent.UnicodeChar = character;
        record.KeyEvent.VirtualKeyCode = character == '\r' ? (ushort)13 : (ushort)0;
        return record;
    }
}
'@

if ($CommandFile) {
    $Commands = Get-Content -LiteralPath $CommandFile | Where-Object { $_.Trim() }
}
if (-not $Commands -or $Commands.Count -eq 0) {
    throw "Nenhum comando foi informado."
}

foreach ($command in $Commands) {
    [ConsoleInputSender]::Send($TargetProcessId, $command)
    Start-Sleep -Milliseconds 500
}
