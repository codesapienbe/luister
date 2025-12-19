; Luister NSIS Installer Script
; Requires NSIS 3.x

!include "MUI2.nsh"
!include "FileFunc.nsh"

; Application metadata
!define APPNAME "Luister"
!define COMPANYNAME "Luister"
!define DESCRIPTION "Music player with visualization and lyrics"
!define VERSIONMAJOR 0
!define VERSIONMINOR 1
!define VERSIONBUILD 0
!define HELPURL "https://github.com/ymus/luister"
!define UPDATEURL "https://github.com/ymus/luister/releases"
!define ABOUTURL "https://github.com/ymus/luister"

; Installer attributes
Name "${APPNAME}"
OutFile "..\..\dist\Luister-Setup-${VERSIONMAJOR}.${VERSIONMINOR}.${VERSIONBUILD}.exe"
InstallDir "$PROGRAMFILES64\${APPNAME}"
InstallDirRegKey HKLM "Software\${APPNAME}" "InstallDir"
RequestExecutionLevel admin

; Modern UI configuration
!define MUI_ABORTWARNING
!define MUI_ICON "..\..\packaging\icons\luister.ico"
!define MUI_UNICON "..\..\packaging\icons\luister.ico"
!define MUI_WELCOMEFINISHPAGE_BITMAP "${NSISDIR}\Contrib\Graphics\Wizard\modern-wizard.bmp"

; Pages
!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_LICENSE "..\..\LICENSE"
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH

!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES

; Language
!insertmacro MUI_LANGUAGE "English"

; Installer sections
Section "Install"
    SetOutPath $INSTDIR

    ; Copy main executable
    File "..\..\dist\Luister.exe"

    ; Create start menu shortcuts
    CreateDirectory "$SMPROGRAMS\${APPNAME}"
    CreateShortCut "$SMPROGRAMS\${APPNAME}\${APPNAME}.lnk" "$INSTDIR\Luister.exe"
    CreateShortCut "$SMPROGRAMS\${APPNAME}\Uninstall.lnk" "$INSTDIR\Uninstall.exe"

    ; Create desktop shortcut
    CreateShortCut "$DESKTOP\${APPNAME}.lnk" "$INSTDIR\Luister.exe"

    ; Create uninstaller
    WriteUninstaller "$INSTDIR\Uninstall.exe"

    ; Write registry keys for Add/Remove Programs
    WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APPNAME}" "DisplayName" "${APPNAME}"
    WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APPNAME}" "UninstallString" "$\"$INSTDIR\Uninstall.exe$\""
    WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APPNAME}" "QuietUninstallString" "$\"$INSTDIR\Uninstall.exe$\" /S"
    WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APPNAME}" "InstallLocation" "$INSTDIR"
    WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APPNAME}" "DisplayIcon" "$INSTDIR\Luister.exe"
    WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APPNAME}" "Publisher" "${COMPANYNAME}"
    WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APPNAME}" "HelpLink" "${HELPURL}"
    WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APPNAME}" "URLUpdateInfo" "${UPDATEURL}"
    WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APPNAME}" "URLInfoAbout" "${ABOUTURL}"
    WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APPNAME}" "DisplayVersion" "${VERSIONMAJOR}.${VERSIONMINOR}.${VERSIONBUILD}"
    WriteRegDWORD HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APPNAME}" "VersionMajor" ${VERSIONMAJOR}
    WriteRegDWORD HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APPNAME}" "VersionMinor" ${VERSIONMINOR}
    WriteRegDWORD HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APPNAME}" "NoModify" 1
    WriteRegDWORD HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APPNAME}" "NoRepair" 1

    ; Calculate installed size
    ${GetSize} "$INSTDIR" "/S=0K" $0 $1 $2
    IntFmt $0 "0x%08X" $0
    WriteRegDWORD HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APPNAME}" "EstimatedSize" $0

    ; Register file associations
    WriteRegStr HKCR ".mp3\OpenWithProgids" "${APPNAME}.mp3" ""
    WriteRegStr HKCR "${APPNAME}.mp3" "" "MP3 Audio"
    WriteRegStr HKCR "${APPNAME}.mp3\DefaultIcon" "" "$INSTDIR\Luister.exe,0"
    WriteRegStr HKCR "${APPNAME}.mp3\shell\open\command" "" "$\"$INSTDIR\Luister.exe$\" $\"%1$\""

    WriteRegStr HKCR ".m4a\OpenWithProgids" "${APPNAME}.m4a" ""
    WriteRegStr HKCR "${APPNAME}.m4a" "" "M4A Audio"
    WriteRegStr HKCR "${APPNAME}.m4a\DefaultIcon" "" "$INSTDIR\Luister.exe,0"
    WriteRegStr HKCR "${APPNAME}.m4a\shell\open\command" "" "$\"$INSTDIR\Luister.exe$\" $\"%1$\""

    WriteRegStr HKCR ".flac\OpenWithProgids" "${APPNAME}.flac" ""
    WriteRegStr HKCR "${APPNAME}.flac" "" "FLAC Audio"
    WriteRegStr HKCR "${APPNAME}.flac\DefaultIcon" "" "$INSTDIR\Luister.exe,0"
    WriteRegStr HKCR "${APPNAME}.flac\shell\open\command" "" "$\"$INSTDIR\Luister.exe$\" $\"%1$\""

    WriteRegStr HKCR ".wav\OpenWithProgids" "${APPNAME}.wav" ""
    WriteRegStr HKCR "${APPNAME}.wav" "" "WAV Audio"
    WriteRegStr HKCR "${APPNAME}.wav\DefaultIcon" "" "$INSTDIR\Luister.exe,0"
    WriteRegStr HKCR "${APPNAME}.wav\shell\open\command" "" "$\"$INSTDIR\Luister.exe$\" $\"%1$\""

    WriteRegStr HKCR ".ogg\OpenWithProgids" "${APPNAME}.ogg" ""
    WriteRegStr HKCR "${APPNAME}.ogg" "" "OGG Audio"
    WriteRegStr HKCR "${APPNAME}.ogg\DefaultIcon" "" "$INSTDIR\Luister.exe,0"
    WriteRegStr HKCR "${APPNAME}.ogg\shell\open\command" "" "$\"$INSTDIR\Luister.exe$\" $\"%1$\""

    ; Refresh shell icons
    System::Call 'Shell32::SHChangeNotify(i 0x08000000, i 0, p 0, p 0)'
SectionEnd

; Uninstaller section
Section "Uninstall"
    ; Remove files
    Delete "$INSTDIR\Luister.exe"
    Delete "$INSTDIR\Uninstall.exe"
    RMDir "$INSTDIR"

    ; Remove shortcuts
    Delete "$SMPROGRAMS\${APPNAME}\${APPNAME}.lnk"
    Delete "$SMPROGRAMS\${APPNAME}\Uninstall.lnk"
    RMDir "$SMPROGRAMS\${APPNAME}"
    Delete "$DESKTOP\${APPNAME}.lnk"

    ; Remove registry keys
    DeleteRegKey HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APPNAME}"
    DeleteRegKey HKLM "Software\${APPNAME}"

    ; Remove file associations
    DeleteRegKey HKCR "${APPNAME}.mp3"
    DeleteRegKey HKCR "${APPNAME}.m4a"
    DeleteRegKey HKCR "${APPNAME}.flac"
    DeleteRegKey HKCR "${APPNAME}.wav"
    DeleteRegKey HKCR "${APPNAME}.ogg"

    ; Refresh shell icons
    System::Call 'Shell32::SHChangeNotify(i 0x08000000, i 0, p 0, p 0)'
SectionEnd
