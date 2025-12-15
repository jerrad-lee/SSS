"""
Flask Dashboard Configuration
=============================
환경별 자동 감지를 통한 경로 설정
Local과 Server에서 동일한 코드로 동작

사용법:
    from config import Config
    csv_path = Config.DATA_DIR / "SKH_tool_information_fixed.csv"
"""

import os
import socket
from pathlib import Path

class Config:
    """환경 자동 감지 기반 설정"""
    
    # 현재 파일의 디렉토리를 기준으로 BASE_DIR 설정
    BASE_DIR = Path(__file__).parent.resolve()
    
    # 환경 감지
    _hostname = socket.gethostname().lower()
    IS_SERVER = 'server' in _hostname or os.path.exists(r"C:\FlaskDashboard\app")
    
    # 경로 설정 (상대 경로 사용)
    DATA_DIR = BASE_DIR / "data"
    STATIC_DIR = BASE_DIR / "static"
    TEMPLATES_DIR = BASE_DIR / "templates"
    LOCAL_RAG_INDEX_DIR = BASE_DIR / "local_rag_index"
    ARCHIVE_DIR = BASE_DIR / "_archive"
    
    # 데이터 파일 경로
    @classmethod
    def get_data_file(cls, filename: str) -> Path:
        """데이터 파일 경로 반환"""
        return cls.DATA_DIR / filename
    
    # 주요 데이터 파일들
    @classmethod
    def get_tool_info_csv(cls) -> Path:
        return cls.DATA_DIR / "SKH_tool_information_fixed.csv"
    
    @classmethod
    def get_issues_tracking_csv(cls) -> Path:
        return cls.DATA_DIR / "Issues Tracking.csv"
    
    @classmethod
    def get_sw_ib_version_csv(cls) -> Path:
        return cls.DATA_DIR / "SW_IB_Version.csv"
    
    @classmethod
    def get_ticket_details_xlsx(cls) -> Path:
        return cls.DATA_DIR / "Ticket Details.xlsx"
    
    @classmethod
    def get_table_export_csv(cls) -> Path:
        return cls.DATA_DIR / "TableExport.csv"
    
    @classmethod
    def get_upgrade_plan_xlsx(cls) -> Path:
        return cls.DATA_DIR / "FiF Sw Upgrade Plan.xlsx"
    
    @classmethod
    def get_swrn_db(cls) -> Path:
        return cls.DATA_DIR / "swrn_index.db"
    
    @classmethod
    def get_tfidf_cache(cls) -> Path:
        return cls.DATA_DIR / "tfidf_cache.pkl"
    
    @classmethod
    def get_pr_release_notes_json(cls) -> Path:
        return cls.DATA_DIR / "pr_release_notes.json"
    
    @classmethod
    def get_swrn_folder(cls) -> Path:
        return cls.DATA_DIR / "SWRN"
    
    # GGUF 모델 경로 (환경별 다름)
    @classmethod
    def get_gguf_model_path(cls) -> str:
        if cls.IS_SERVER:
            return str(cls.BASE_DIR / "Llama-3.2-3B-Instruct-Q4_K_M.gguf")
        else:
            # 로컬 환경 - 여러 위치 시도
            local_paths = [
                cls.BASE_DIR / "Llama-3.2-3B-Instruct-Q4_K_M.gguf",
                Path(r"C:\Users\leeje3\.ollama\Llama-3.2-3B-Instruct-Q4_K_M.gguf"),
                Path.home() / ".ollama" / "Llama-3.2-3B-Instruct-Q4_K_M.gguf"
            ]
            for path in local_paths:
                if path.exists():
                    return str(path)
            # 기본값 반환
            return str(local_paths[0])
    
    # 디렉토리 생성 유틸리티
    @classmethod
    def ensure_dirs(cls):
        """필요한 디렉토리들 생성"""
        cls.DATA_DIR.mkdir(parents=True, exist_ok=True)
        cls.LOCAL_RAG_INDEX_DIR.mkdir(parents=True, exist_ok=True)
        cls.ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
        
    @classmethod
    def print_config(cls):
        """현재 설정 출력"""
        print("=" * 50)
        print("Flask Dashboard Configuration")
        print("=" * 50)
        print(f"Environment: {'SERVER' if cls.IS_SERVER else 'LOCAL'}")
        print(f"Hostname: {cls._hostname}")
        print(f"BASE_DIR: {cls.BASE_DIR}")
        print(f"DATA_DIR: {cls.DATA_DIR}")
        print(f"DATA_DIR exists: {cls.DATA_DIR.exists()}")
        print("=" * 50)


# 모듈 로드 시 디렉토리 확인
Config.ensure_dirs()

if __name__ == "__main__":
    Config.print_config()
