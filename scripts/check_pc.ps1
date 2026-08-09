# TeacherFlow 실행 사양 진단 — 교사 PC에서 그대로 실행 (관리자 권한 불필요)
# 판정: E2B(기본팩) / E4B(고품질팩) 실행 가능 여부 + 배포 형태 권고
$ErrorActionPreference = "SilentlyContinue"

$cs   = Get-CimInstance Win32_ComputerSystem
$cpu  = Get-CimInstance Win32_Processor | Select-Object -First 1
$os   = Get-CimInstance Win32_OperatingSystem
$gpus = @(Get-CimInstance Win32_VideoController)
$sys  = Get-CimInstance Win32_LogicalDisk -Filter "DeviceID='C:'"

$ramGB   = [math]::Round($cs.TotalPhysicalMemory / 1GB, 1)
$freeGB  = [math]::Round($sys.FreeSpace / 1GB, 1)
$cores   = $cpu.NumberOfCores
$threads = $cpu.NumberOfLogicalProcessors

# 외장 GPU 판정 — 내장(UHD/Iris/Vega/Radeon Graphics)은 제외
$dgpu = $gpus | Where-Object {
  $_.Name -notmatch "UHD|HD Graphics|Iris|Radeon\(TM\) Graphics|Vega|Microsoft Basic|Meta|Virtual"
} | Select-Object -First 1
# VRAM: Win32_VideoController.AdapterRAM은 32비트라 4GB에서 잘린다 →
# 레지스트리 qwMemorySize(64비트)를 우선 사용
$vramGB = 0
if ($dgpu) {
  $vramGB = [math]::Round($dgpu.AdapterRAM / 1GB, 1)
  $keys = Get-ChildItem "HKLM:\SYSTEM\CurrentControlSet\Control\Class\{4d36e968-e325-11ce-bfc1-08002be10318}" -ErrorAction SilentlyContinue
  foreach ($k in $keys) {
    $qw = (Get-ItemProperty $k.PSPath -Name "HardwareInformation.qwMemorySize" -ErrorAction SilentlyContinue)."HardwareInformation.qwMemorySize"
    if ($qw) {
      $cand = [math]::Round($qw / 1GB, 1)
      if ($cand -gt $vramGB) { $vramGB = $cand }
    }
  }
}

Write-Output "=== TeacherFlow 실행 사양 진단 ==="
Write-Output ("기기      : {0} {1}" -f $cs.Manufacturer, $cs.Model)
Write-Output ("OS        : {0}" -f $os.Caption)
Write-Output ("CPU       : {0} ({1}C/{2}T)" -f $cpu.Name.Trim(), $cores, $threads)
Write-Output ("RAM       : {0} GB" -f $ramGB)
Write-Output ("C: 여유   : {0} GB" -f $freeGB)
if ($dgpu) { Write-Output ("외장 GPU  : {0} (VRAM {1} GB)" -f $dgpu.Name, $vramGB) }
else       { Write-Output ("외장 GPU  : 없음 (내장 그래픽 → CPU 추론)") }

# 한/글 설치 여부 (라이브 문서 제어 전제)
$hwp = @(Get-ChildItem "C:\Program Files (x86)\Hnc","C:\Program Files\Hnc" -Filter Hwp.exe -Recurse -ErrorAction SilentlyContinue | Select-Object -First 1)
Write-Output ("한/글     : {0}" -f $(if ($hwp.Count -gt 0) { "설치됨" } else { "미확인 (라이브 편집 불가 가능)" }))

Write-Output ""
Write-Output "=== 판정 ==="
# E2B: 모델 3GB + 엔진 → RAM 8GB·여유 6GB 이상 권장
if ($ramGB -ge 8 -and $freeGB -ge 6) {
  $spd = if ($vramGB -ge 4) { "빠름 (GPU 가속)" } elseif ($cores -ge 6) { "보통 (CPU)" } else { "느림 (저사양 CPU)" }
  Write-Output ("E2B 기본팩 : 사용 가능 — 예상 속도 {0}" -f $spd)
} else {
  Write-Output ("E2B 기본팩 : 부족 (RAM 8GB·여유 6GB 필요, 현재 {0}GB·{1}GB)" -f $ramGB, $freeGB)
}
# E4B: 모델 4.5GB → RAM 16GB·여유 8GB 이상 권장
if ($ramGB -ge 16 -and $freeGB -ge 8) {
  $spd4 = if ($vramGB -ge 6) { "쾌적" } else { "느림 (공문 1건 2~4분)" }
  Write-Output ("E4B 고품질 : 사용 가능 — {0}" -f $spd4)
} else {
  Write-Output ("E4B 고품질 : 비권장 (RAM 16GB·여유 8GB 필요)")
}
Write-Output ""
if ($freeGB -lt 6) {
  Write-Output "권고: 디스크 여유 부족 → NSIS 설치본(92MB)도 모델 내려받을 공간이 필요합니다."
} elseif ($ramGB -lt 8) {
  Write-Output "권고: 로컬 모델 대신 API 모드 사용(설정에서 전환) 또는 서버 공유 방식 검토."
} else {
  Write-Output "권고: NSIS 설치본 + E2B 모델팩. 백신(V3 등) 예외 등록 또는 코드서명본 필요."
}
