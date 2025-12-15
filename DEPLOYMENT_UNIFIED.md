# Flask Dashboard 배포 가이드

## 개요

이 문서는 로컬 개발 환경에서 운영 서버로 Flask Dashboard를 배포하는 방법을 설명합니다.

## 폴더 구조 (통합됨)

### Before (기존 - 문제 상황)
```
로컬: D:\0_Download\flask_dashboard_project\
├── app.py
├── local_rag.py
├── swrn_indexer.py
├── data/
│   ├── SKH_tool_information_fixed.csv
│   ├── Issues Tracking.csv
│   └── ...
└── templates/

서버: C:\FlaskDashboard\
├── app/                          ★ Flask가 여기서 실행됨
│   ├── app.py
│   ├── local_rag.py
│   ├── data/                     ★ data 폴더가 app 하위에 있어야 함
│   └── templates/
├── venv/
├── data/                         ✗ Flask가 여기를 참조하지 않음
└── START_DASHBOARD.bat
```

**문제점:**
1. 서버에서 `C:\FlaskDashboard\app\`에서 Flask가 실행됨
2. 상대 경로 `data/`가 `C:\FlaskDashboard\app\data\`를 참조
3. 하드코딩된 경로들이 환경마다 달라야 함

### After (개선 - 통합 구조)
```
로컬: D:\0_Download\flask_dashboard_project\
├── config.py                     ★ 환경 자동 감지 설정
├── deploy.ps1                    ★ 원클릭 배포 스크립트
├── app.py
├── local_rag.py
├── swrn_indexer.py
├── data/
│   ├── SKH_tool_information_fixed.csv
│   ├── Issues Tracking.csv
│   ├── swrn_index.db
│   └── ...
├── static/
├── templates/
└── requirements.txt

서버: C:\FlaskDashboard\          ★ 로컬과 동일한 구조
├── config.py
├── app.py
├── local_rag.py
├── swrn_indexer.py
├── data/                         ★ 루트에 data 폴더
│   ├── SKH_tool_information_fixed.csv
│   └── ...
├── static/
├── templates/
├── venv/
└── START_DASHBOARD.bat
```

## 핵심 변경사항

### 1. config.py - 환경 자동 감지

```python
from config import Config

# 파일 경로 사용
csv_path = Config.get_tool_info_csv()  # data/SKH_tool_information_fixed.csv
db_path = Config.get_swrn_db()          # data/swrn_index.db

# 환경 확인
print(Config.IS_SERVER)  # True/False
print(Config.BASE_DIR)   # 현재 실행 위치
```

### 2. 하드코딩 제거

**Before:**
```python
# app.py에 하드코딩된 경로들
csv_paths = [
    'data/Issues Tracking.csv',
    'C:\\FlaskDashboard\\app\\data\\Issues Tracking.csv'  # 서버용 fallback
]
```

**After:**
```python
# Config 사용
csv_path = Config.get_issues_tracking_csv()
```

## 배포 방법

### 방법 1: PowerShell 스크립트 (권장)

```powershell
# 로컬에서 실행
cd D:\0_Download\flask_dashboard_project

# 코드만 배포
.\deploy.ps1

# 코드 + 데이터 배포
.\deploy.ps1 -SyncData

# 미리보기 (실제 복사 안함)
.\deploy.ps1 -DryRun
```

### 방법 2: 수동 배포

```powershell
# 1. 핵심 파일 복사
$local = "D:\0_Download\flask_dashboard_project"
$server = "\\10.173.135.202\c$\FlaskDashboard"

Copy-Item "$local\app.py" "$server\"
Copy-Item "$local\config.py" "$server\"
Copy-Item "$local\local_rag.py" "$server\"
Copy-Item "$local\swrn_indexer.py" "$server\"

# 2. 템플릿/정적 파일
Copy-Item "$local\templates\*" "$server\templates\" -Recurse
Copy-Item "$local\static\*" "$server\static\" -Recurse

# 3. 캐시 삭제
Remove-Item "$server\__pycache__" -Recurse -Force

# 4. 서버에서 Flask 재시작 (원격 데스크톱 또는 PsExec)
```

### 방법 3: 서버에서 직접 실행

```batch
:: 서버에서 실행 (C:\FlaskDashboard\)
START_DASHBOARD.bat
```

## Flask 재시작

배포 후 반드시 Flask를 재시작해야 새 코드가 적용됩니다.

```batch
:: 서버에서 실행
cd C:\FlaskDashboard
taskkill /F /IM python.exe
rd /s /q __pycache__
venv\Scripts\python.exe app.py
```

## 확인 사항

### 배포 전 체크리스트
- [ ] 로컬에서 테스트 완료
- [ ] config.py 생성/업데이트
- [ ] 서버 연결 확인 (ping 10.173.135.202)

### 배포 후 체크리스트
- [ ] http://10.173.135.202:8060 접속 확인
- [ ] K-Bot 검색 테스트 ("bias rf" 검색)
- [ ] 데이터 테이블 로드 확인

## 문제 해결

### 파일을 찾을 수 없음
```
FileNotFoundError: data/SKH_tool_information_fixed.csv
```
→ `Config.print_config()`로 BASE_DIR 확인
→ data 폴더가 올바른 위치에 있는지 확인

### 서버에서 변경사항 미반영
→ Flask 재시작 필요
→ `__pycache__` 폴더 삭제

### 권한 문제
→ 네트워크 드라이브 접근 권한 확인
→ 관리자 권한으로 PowerShell 실행

## 연락처

문제 발생 시 개발팀에 문의하세요.
