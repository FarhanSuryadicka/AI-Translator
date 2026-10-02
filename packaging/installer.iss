; Inno Setup script: installer offline lengkap (aplikasi + model + llama.cpp).
; Dipanggil dari packaging\build.ps1 dengan /DDistDir=... /DOutDir=...

#define AppName "AI Translator"
#define AppVersion "1.0.0"
#define Root ".."

#ifndef DistDir
  #define DistDir Root + "\build\dist\AI Translator"
#endif
#ifndef OutDir
  #define OutDir Root + "\build\installer"
#endif

[Setup]
AppId={{6B0E8E52-2F6B-4D7A-9E3C-7A1F4C2B9D11}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=AI Translator
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
OutputDir={#OutDir}
OutputBaseFilename=AI-Translator-Setup-{#AppVersion}
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
; Admin wajib: VB-CABLE (driver) dan pengaturan virtual mic dipasang bersama aplikasi.
PrivilegesRequired=admin
WizardStyle=modern
; Installer > 2 GB wajib dipecah: Setup.exe + Setup-1.bin, Setup-2.bin, ... (simpan dalam satu folder).
DiskSpanning=yes
DiskSliceSize=max
Compression=lzma2/fast
SolidCompression=no
LicenseFile={#Root}\packaging\NOTICE.txt
UninstallDisplayName={#AppName}
UninstallDisplayIcon={app}\{#AppName}.exe
SetupIconFile={#Root}\app\assets\icon.ico

[Languages]
Name: "en"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"
Name: "vbcable"; Description: "Pasang virtual mic untuk fitur Bicara: VB-CABLE oleh VB-Audio (donationware, vb-cable.com). Butuh restart."; GroupDescription: "Virtual mic:"; Check: not IsVBCableInstalled

[Files]
Source: "{#DistDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "{#Root}\vendor\llama\*"; DestDir: "{app}\vendor\llama"; Flags: ignoreversion recursesubdirs createallsubdirs
; Bobot model hampir tidak bisa dikompres -> nocompression agar build jauh lebih cepat.
Source: "{#Root}\models\*"; DestDir: "{app}\models"; Flags: ignoreversion recursesubdirs createallsubdirs nocompression; Excludes: "*.lock,.locks\*"
; Paket resmi VB-CABLE, tidak diubah. Hanya disalin ke folder sementara untuk dipasang.
Source: "{#Root}\vendor\vbcable\*"; DestDir: "{tmp}\vbcable"; Flags: ignoreversion deleteafterinstall; Tasks: vbcable
Source: "{#Root}\packaging\NOTICE.txt"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#Root}\README.md"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppName}.exe"
Name: "{group}\Uninstall {#AppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppName}.exe"; Tasks: desktopicon

[Run]
Filename: "{tmp}\vbcable\VBCABLE_Setup_x64.exe"; Parameters: "-i -h"; WorkingDir: "{tmp}\vbcable"; StatusMsg: "Memasang VB-CABLE (virtual mic)..."; Flags: waituntilterminated; Tasks: vbcable
; Ganti nama "CABLE Output" -> "AI Translator Mic", sembunyikan "CABLE In 16ch". Jika driver baru aktif
; setelah restart, aplikasi menawarkan langkah ini lagi (tombol "Rapikan perangkat VB-CABLE").
Filename: "{app}\{#AppName}.exe"; Parameters: "--setup-audio"; StatusMsg: "Mengatur virtual mic..."; Flags: runhidden waituntilterminated
Filename: "{app}\{#AppName}.exe"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent

[Code]
function IsVBCableInstalled: Boolean;
begin
  Result := RegKeyExists(HKLM, 'SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\VB:VBCABLE {87459874-1236-4469}');
end;

function NeedRestart: Boolean;
begin
  Result := WizardIsTaskSelected('vbcable');
end;
