param()
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
python make_english.py
foreach ($edition in @(@('sr_b20a_gui.py','SR-B20A-Remote-ZH'), @('sr_b20a_gui_en.py','SR-B20A-Remote-EN'))) {
  python -m PyInstaller --noconfirm --onefile --windowed --name $edition[1] --collect-all bleak --collect-submodules winrt --distpath "$PSScriptRoot\dist" --workpath "$env:TEMP\srb20a-release-build" --specpath "$env:TEMP\srb20a-release-build" $edition[0]
  if ($LASTEXITCODE -ne 0) { throw "Build failed: $($edition[1])" }
}
