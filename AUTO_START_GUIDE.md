# Flask Dashboard 자동 시작 설정 가이드

## 🎯 목표
서버 재시작 시 Flask Dashboard가 자동으로 실행되고, 필요 시 시작/중지가 가능하도록 설정

---

## 방법 선택

### ⭐ 방법 1: Task Scheduler (추천 - 설정 간단)
- **장점**: Windows 기본 기능, 추가 프로그램 불필요
- **단점**: GUI 중지 시 프로세스 수동 종료 필요
- **적합**: 대부분의 경우

### 방법 2: NSSM (고급 - 서비스 관리 우수)
- **장점**: 완벽한 Windows 서비스, 로그 자동 관리
- **단점**: NSSM 프로그램 필요 (오프라인 다운로드)
- **적합**: 서비스 수준 관리가 필요한 경우

---

## 📋 방법 1: Task Scheduler 설정 (추천)

### 1단계: 서버에서 설정 스크립트 실행

```powershell
# 관리자 권한 PowerShell에서 실행
cd C:\FlaskDashboard
.\setup_task_scheduler.ps1
```

### 2단계: 확인

서버 재시작 후 자동으로 Flask가 실행됩니다.

```powershell
# 상태 확인
Get-ScheduledTask -TaskName FlaskDashboard
```

### 3단계: 수동 제어

```powershell
# 시작
Start-ScheduledTask -TaskName FlaskDashboard

# 중지 (작업만 중지, 프로세스는 별도 종료)
Stop-ScheduledTask -TaskName FlaskDashboard
Get-Process python | Where-Object {$_.Path -like "*FlaskDashboard*"} | Stop-Process -Force

# 완전 삭제
Unregister-ScheduledTask -TaskName FlaskDashboard -Confirm:$false
```

### GUI 관리
1. `Win + R` → `taskschd.msc` 입력
2. 작업 스케줄러 라이브러리에서 "FlaskDashboard" 찾기
3. 우클릭 → 실행/중지/속성

---

## 📋 방법 2: NSSM 서비스 설정

### 1단계: NSSM 다운로드 (인터넷 연결된 PC)

1. https://nssm.cc/release/nssm-2.24.zip 다운로드
2. 압축 해제 후 `win64\nssm.exe` 파일 복사
3. USB로 서버에 전송 → `C:\FlaskDashboard\nssm.exe`에 저장

### 2단계: 서비스 설치

```powershell
# 관리자 권한 PowerShell에서 실행
cd C:\FlaskDashboard
.\setup_windows_service.ps1
```

### 3단계: 서비스 제어

```powershell
# 시작
net start FlaskDashboard

# 중지
net stop FlaskDashboard

# 재시작
net stop FlaskDashboard
net start FlaskDashboard

# 상태 확인
Get-Service FlaskDashboard

# 서비스 삭제
C:\FlaskDashboard\nssm.exe remove FlaskDashboard confirm
```

### GUI 관리
1. `Win + R` → `services.msc` 입력
2. "FlaskDashboard" 서비스 찾기
3. 우클릭 → 시작/중지/속성

---

## 🛠️ 방법 3: 수동 제어 스크립트 사용

Task Scheduler나 NSSM 설정 후에도 사용 가능한 편리한 제어 스크립트:

```powershell
cd C:\FlaskDashboard

# 시작
.\flask_service.ps1 start

# 중지
.\flask_service.ps1 stop

# 재시작
.\flask_service.ps1 restart

# 상태 확인
.\flask_service.ps1 status
```

---

## 🔍 문제 해결

### Flask가 시작되지 않는 경우

1. **로그 확인**
```powershell
# Task Scheduler 로그
Get-Content C:\FlaskDashboard\logs\task_output.log

# NSSM 로그
Get-Content C:\FlaskDashboard\logs\service_output.log
Get-Content C:\FlaskDashboard\logs\service_error.log
```

2. **수동 실행 테스트**
```powershell
cd C:\FlaskDashboard\app
C:\FlaskDashboard\venv\Scripts\python.exe app.py
```

3. **방화벽 확인**
```powershell
Get-NetFirewallRule -DisplayName "Flask Dashboard"
```

### 포트 충돌 확인

```powershell
# 포트 8060 사용 중인 프로세스 확인
netstat -ano | findstr :8060
```

---

## 📝 권장 설정

1. **Task Scheduler 방식으로 자동 시작 설정**
```powershell
cd C:\FlaskDashboard
.\setup_task_scheduler.ps1
```

2. **제어 스크립트를 바탕화면 바로가기로 생성**

바탕화면에 `FlaskDashboard_Start.bat` 생성:
```batch
@echo off
powershell -ExecutionPolicy Bypass -File "C:\FlaskDashboard\flask_service.ps1" start
pause
```

바탕화면에 `FlaskDashboard_Stop.bat` 생성:
```batch
@echo off
powershell -ExecutionPolicy Bypass -File "C:\FlaskDashboard\flask_service.ps1" stop
pause
```

바탕화면에 `FlaskDashboard_Status.bat` 생성:
```batch
@echo off
powershell -ExecutionPolicy Bypass -File "C:\FlaskDashboard\flask_service.ps1" status
pause
```

---

## ✅ 설정 완료 후 확인사항

- [ ] 서버 재시작 테스트
- [ ] `http://10.173.135.202:8060` 접속 확인
- [ ] 수동 중지/시작 테스트
- [ ] 로그 파일 생성 확인

---

## 🔗 접속 주소

- **서버 로컬**: http://127.0.0.1:8060
- **서버 IP**: http://10.173.135.202:8060
- **랩탑 (hosts 설정 시)**: http://shit.kor:8060
