"""
SWRN (Software Release Notes) SQLite FTS5 Indexer
PDF 문서를 인덱싱하여 빠른 PR 검색 지원

사용법:
    python swrn_indexer.py --build      # 인덱스 구축 (최초 1회)
    python swrn_indexer.py --search "PR-195121"  # PR 검색
    python swrn_indexer.py --update     # 새 파일만 추가 인덱싱
"""

import os
import re
import sqlite3
import json
import time
from pathlib import Path
from typing import Optional, List, Dict, Tuple
from datetime import datetime

# PyMuPDF
try:
    import fitz  # PyMuPDF
    PYMUPDF_AVAILABLE = True
except ImportError:
    PYMUPDF_AVAILABLE = False
    print("⚠️ PyMuPDF not installed. Run: pip install PyMuPDF")

# 하이브리드 검색 엔진
try:
    from similar_pr_engine import HybridPRSearchEngine, get_hybrid_search_engine
    HYBRID_SEARCH_AVAILABLE = True
except ImportError:
    HYBRID_SEARCH_AVAILABLE = False
    HybridPRSearchEngine = None


def parse_sw_version(version_str: str) -> Tuple[int, int, int, int, int]:
    """
    SW 버전 문자열을 정렬 가능한 튜플로 변환
    예: "1.8.4-SP28-HF11-Release" -> (1, 8, 4, 28, 11)
        "1.8.4-SP28-Release" -> (1, 8, 4, 28, 0)
        "1.8.4-SP27-B2-Release" -> (1, 8, 4, 27, -2)  # B 빌드는 HF보다 낮음
    
    정렬 우선순위: 높은 버전이 먼저 (내림차순)
    """
    if not version_str:
        return (0, 0, 0, 0, 0)
    
    # 버전 문자열 정규화
    v = version_str.upper()
    
    # 메인 버전 추출 (예: 1.8.4)
    main_match = re.search(r'(\d+)\.(\d+)\.(\d+)', v)
    major, minor, patch = (0, 0, 0)
    if main_match:
        major = int(main_match.group(1))
        minor = int(main_match.group(2))
        patch = int(main_match.group(3))
    
    # SP 번호 추출
    sp_match = re.search(r'SP(\d+)', v)
    sp_num = int(sp_match.group(1)) if sp_match else 0
    
    # HF 번호 추출 (Hotfix가 있으면 Release보다 높음)
    hf_match = re.search(r'HF(\d+)', v)
    if hf_match:
        hf_num = int(hf_match.group(1))  # HF11 = 11
    else:
        # B 빌드 확인 (HF보다 낮음)
        b_match = re.search(r'-B(\d+)-', v)
        if b_match:
            hf_num = -int(b_match.group(1))  # B2 = -2 (HF0보다 낮음)
        else:
            # HF 없음 = 기본 Release = 0
            hf_num = 0
    
    return (major, minor, patch, sp_num, hf_num)


class SWRNIndexer:
    """SWRN PDF 문서 인덱서 - SQLite FTS5 기반"""
    
    def __init__(self, swrn_folder: str = None, db_path: str = None):
        self.base_dir = Path(__file__).parent
        self.swrn_folder = Path(swrn_folder) if swrn_folder else self.base_dir / "data" / "SWRN"
        self.db_path = Path(db_path) if db_path else self.base_dir / "data" / "swrn_index.db"
        
        # DB 디렉토리 생성
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        
        # 하이브리드 검색 엔진 (지연 초기화)
        self._hybrid_engine = None
        
    def _create_tables(self, conn: sqlite3.Connection):
        """데이터베이스 테이블 생성"""
        cursor = conn.cursor()
        
        # 파일 정보 테이블
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS pdf_files (
                id INTEGER PRIMARY KEY,
                filename TEXT UNIQUE,
                filepath TEXT,
                sw_version TEXT,
                file_size INTEGER,
                page_count INTEGER,
                indexed_at TEXT
            )
        """)
        
        # 페이지별 텍스트 테이블 (FTS5 가상 테이블)
        cursor.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS page_content USING fts5(
                file_id,
                page_num,
                content,
                tokenize='unicode61'
            )
        """)
        
        # PR 인덱스 테이블 (빠른 PR 검색용)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS pr_index (
                pr_number TEXT,
                file_id INTEGER,
                page_num INTEGER,
                context TEXT,
                pr_type TEXT DEFAULT 'unknown',
                PRIMARY KEY (pr_number, file_id, page_num),
                FOREIGN KEY (file_id) REFERENCES pdf_files(id)
            )
        """)
        
        # pr_type 컬럼이 없으면 추가 (기존 DB 마이그레이션)
        try:
            cursor.execute("ALTER TABLE pr_index ADD COLUMN pr_type TEXT DEFAULT 'unknown'")
            conn.commit()
        except sqlite3.OperationalError:
            pass  # 이미 컬럼이 존재함
        
        # PR 번호 인덱스
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_pr_number ON pr_index(pr_number)
        """)
        
        conn.commit()
    
    def _extract_version_from_filename(self, filename: str) -> str:
        """파일명에서 SW 버전 추출"""
        # Version_1.8.4-SP34-Release_ReleaseNotes.pdf -> 1.8.4-SP34-Release
        match = re.search(r'Version[_-]?([\d.]+[-\w]*)', filename, re.IGNORECASE)
        if match:
            return match.group(1)
        return "Unknown"
    
    def _detect_pr_type(self, text: str, pr_position: int) -> str:
        """PR이 New Feature인지 Issue Fix인지 감지
        
        문서 구조:
        - 'New and Enhanced Features' 섹션 → 'new_feature'
        - 'Problem Report and Escalations' 섹션 → 'issue_fix'
        
        Args:
            text: 페이지 전체 텍스트
            pr_position: PR 번호가 나온 위치
            
        Returns:
            'new_feature' 또는 'issue_fix' 또는 'unknown'
        """
        # PR 위치 이전의 텍스트에서 섹션 헤더 찾기
        text_before_pr = text[:pr_position].lower()
        
        # 가장 마지막에 나온 섹션 헤더 찾기
        new_feature_pos = -1
        issue_fix_pos = -1
        
        # New and Enhanced Features 섹션 패턴
        new_feature_patterns = [
            'new and enhanced features',
            'new features',
            'enhanced features',
            'ald features',  # ALD Features from 1.8.4-SP35
            'features from'
        ]
        
        # Problem Report and Escalations 섹션 패턴  
        issue_fix_patterns = [
            'problem report and escalations',
            'problem reports',
            'escalations',
            'defect fixes',
            'bug fixes'
        ]
        
        for pattern in new_feature_patterns:
            pos = text_before_pr.rfind(pattern)
            if pos > new_feature_pos:
                new_feature_pos = pos
                
        for pattern in issue_fix_patterns:
            pos = text_before_pr.rfind(pattern)
            if pos > issue_fix_pos:
                issue_fix_pos = pos
        
        # 더 최근에 나온 섹션 헤더로 판단
        if new_feature_pos > issue_fix_pos:
            return 'new_feature'
        elif issue_fix_pos > new_feature_pos:
            return 'issue_fix'
        else:
            # 헤더를 못 찾은 경우, 키워드로 추론
            text_around = text[max(0, pr_position-500):pr_position+500].lower()
            if 'description' in text_around and 'benefit' in text_around:
                return 'new_feature'
            elif 'issue description' in text_around or 'root cause' in text_around or 'solution' in text_around:
                return 'issue_fix'
            return 'unknown'
    
    def _extract_pr_numbers(self, text: str) -> List[Tuple[str, str, str]]:
        """텍스트에서 PR 번호, 주변 컨텍스트, PR 유형 추출
        
        PDF 문서에서 실제 PR 항목만 추출 (History, Description 등에 언급된 관련 PR 제외)
        
        유효한 PR 패턴:
        - 섹션 번호 패턴: "5.1.1.1.1. PR-XXXXXX :" 또는 "6.2.1.1.1. PR-XXXXXX :"
        - 제목 패턴: 줄 시작에 "PR-XXXXXX :" 또는 "PR-XXXXXX:" 형태
        
        Returns:
            List of (pr_number, context, pr_type) tuples
        """
        results = []
        seen_prs = set()  # 중복 방지
        
        # 패턴 1: 섹션 번호가 있는 PR 제목 (가장 정확)
        # 예: "5.1.1.1.1. PR-197591 : High Pass Filtered SVID..."
        # 예: "6.2.1.1.1. PR-196198 : No Warning/Alarm when..."
        section_pr_pattern = r'(\d+\.\d+\.\d+\.\d+\.\d+\.)\s*PR[-\s]?(\d{6})\s*[:\-]'
        
        for match in re.finditer(section_pr_pattern, text):
            pr_num = f"PR-{match.group(2)}"
            if pr_num in seen_prs:
                continue
            seen_prs.add(pr_num)
            
            # PR 주변 300자 컨텍스트 추출 (제목 포함)
            start = match.start()
            end = min(len(text), match.end() + 300)
            context = text[start:end].replace('\n', ' ').strip()
            
            # PR 유형 감지 (섹션 번호로 판단)
            section_num = match.group(1)
            if section_num.startswith('5.'):
                pr_type = 'feature'  # Section 5: New and Enhanced Features
            elif section_num.startswith('6.'):
                pr_type = 'bug_fix'  # Section 6: Problem Report and Escalations
            else:
                pr_type = self._detect_pr_type(text, match.start())
            
            results.append((pr_num, context, pr_type))
        
        # 패턴 2: 섹션 번호 없이 줄 시작에 PR 제목 (백업 패턴)
        # 예: "PR-197591 : High Pass Filtered..."
        # 단, History, Description 등에서 언급된 PR은 제외
        line_pr_pattern = r'(?:^|\n)\s*PR[-\s]?(\d{6})\s*[:\-]\s*([^\n]{10,})'
        
        for match in re.finditer(line_pr_pattern, text):
            pr_num = f"PR-{match.group(1)}"
            if pr_num in seen_prs:
                continue
            
            # 주변 텍스트 확인 - History, Description 등에서 언급된 것 제외
            start_context = max(0, match.start() - 200)
            before_text = text[start_context:match.start()].lower()
            
            # 제외 키워드: 이 PR이 다른 섹션에서 참조되는 경우
            exclude_keywords = ['history', 'description', 'see pr', 'related pr', 
                               'refer to', 'same as', 'duplicate', 'fixed in',
                               'introduced in', 'caused by', 'root cause']
            
            if any(kw in before_text[-100:] for kw in exclude_keywords):
                continue
            
            seen_prs.add(pr_num)
            
            # PR 주변 컨텍스트 추출
            end = min(len(text), match.end() + 200)
            context = text[match.start():end].replace('\n', ' ').strip()
            
            # PR 유형 감지
            pr_type = self._detect_pr_type(text, match.start())
            
            results.append((pr_num, context, pr_type))
        
        return results
    
    def build_index(self, force_rebuild: bool = False) -> Dict:
        """전체 인덱스 구축"""
        if not PYMUPDF_AVAILABLE:
            return {"error": "PyMuPDF not installed"}
        
        if not self.swrn_folder.exists():
            return {"error": f"SWRN folder not found: {self.swrn_folder}"}
        
        # 기존 DB 삭제 (강제 재구축 시)
        if force_rebuild and self.db_path.exists():
            os.remove(self.db_path)
            print(f"🗑️ Removed existing index: {self.db_path}")
        
        conn = sqlite3.Connection(str(self.db_path))
        self._create_tables(conn)
        cursor = conn.cursor()
        
        # PDF 파일 목록
        pdf_files = list(self.swrn_folder.glob("*.pdf"))
        total_files = len(pdf_files)
        
        if total_files == 0:
            return {"error": "No PDF files found"}
        
        print(f"\n{'='*60}")
        print(f"📚 SWRN Indexer - Building Index")
        print(f"{'='*60}")
        print(f"📁 Folder: {self.swrn_folder}")
        print(f"📄 Files: {total_files}")
        print(f"💾 Database: {self.db_path}")
        print(f"{'='*60}\n")
        
        stats = {
            "total_files": total_files,
            "processed_files": 0,
            "total_pages": 0,
            "total_prs": 0,
            "errors": [],
            "start_time": time.time()
        }
        
        for idx, pdf_path in enumerate(pdf_files, 1):
            filename = pdf_path.name
            
            # 이미 인덱싱된 파일 스킵 (업데이트 모드)
            if not force_rebuild:
                cursor.execute("SELECT id FROM pdf_files WHERE filename = ?", (filename,))
                if cursor.fetchone():
                    print(f"⏭️ [{idx}/{total_files}] Skipping (already indexed): {filename}")
                    continue
            
            print(f"📖 [{idx}/{total_files}] Processing: {filename}")
            
            try:
                doc = fitz.open(str(pdf_path))
                page_count = len(doc)
                sw_version = self._extract_version_from_filename(filename)
                file_size = pdf_path.stat().st_size
                
                # 파일 정보 저장
                cursor.execute("""
                    INSERT OR REPLACE INTO pdf_files 
                    (filename, filepath, sw_version, file_size, page_count, indexed_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (filename, str(pdf_path), sw_version, file_size, page_count, 
                      datetime.now().isoformat()))
                
                file_id = cursor.lastrowid
                
                # 페이지별 텍스트 추출 및 인덱싱
                file_pr_count = 0
                for page_num in range(page_count):
                    page = doc[page_num]
                    text = page.get_text()
                    
                    if not text.strip():
                        continue
                    
                    # FTS5에 페이지 내용 저장
                    cursor.execute("""
                        INSERT INTO page_content (file_id, page_num, content)
                        VALUES (?, ?, ?)
                    """, (str(file_id), str(page_num + 1), text))
                    
                    # PR 번호 추출 및 인덱싱 (pr_type 포함)
                    pr_entries = self._extract_pr_numbers(text)
                    for pr_num, context, pr_type in pr_entries:
                        cursor.execute("""
                            INSERT OR REPLACE INTO pr_index (pr_number, file_id, page_num, context, pr_type)
                            VALUES (?, ?, ?, ?, ?)
                        """, (pr_num, file_id, page_num + 1, context, pr_type))
                        file_pr_count += 1
                    
                    # 진행률 표시 (50페이지마다)
                    if (page_num + 1) % 50 == 0:
                        print(f"   📄 Page {page_num + 1}/{page_count}...")
                
                doc.close()
                conn.commit()
                
                stats["processed_files"] += 1
                stats["total_pages"] += page_count
                stats["total_prs"] += file_pr_count
                
                print(f"   ✅ {page_count} pages, {file_pr_count} PRs indexed")
                
            except Exception as e:
                error_msg = f"{filename}: {str(e)}"
                stats["errors"].append(error_msg)
                print(f"   ❌ Error: {e}")
                continue
        
        conn.close()
        
        # 완료 통계
        elapsed = time.time() - stats["start_time"]
        stats["elapsed_seconds"] = elapsed
        
        print(f"\n{'='*60}")
        print(f"✅ Indexing Complete!")
        print(f"{'='*60}")
        print(f"📄 Files processed: {stats['processed_files']}/{total_files}")
        print(f"📑 Total pages: {stats['total_pages']:,}")
        print(f"🔢 Total PRs indexed: {stats['total_prs']:,}")
        print(f"⏱️ Time elapsed: {elapsed:.1f} seconds ({elapsed/60:.1f} minutes)")
        print(f"💾 Database size: {self.db_path.stat().st_size / 1024 / 1024:.1f} MB")
        
        if stats["errors"]:
            print(f"\n⚠️ Errors ({len(stats['errors'])}):")
            for err in stats["errors"][:5]:
                print(f"   - {err}")
        
        return stats
    
    def get_prs_between_versions(self, version_from: str, version_to: str, include_details: bool = True) -> Dict:
        """
        두 버전 사이에 추가된 PR들을 검색 (Delta Summary 스타일)
        
        Args:
            version_from: 시작 버전 (예: "1.8.4-SP33-HF9e")
            version_to: 종료 버전 (예: "1.8.4-SP33-HF16")
            include_details: PR 상세 정보 포함 여부
        
        Returns:
            Dict with:
                - prs: 추가된 PR 목록 (상세 정보 포함)
                - versions_included: 포함된 버전들
                - from_version: 시작 버전
                - to_version: 종료 버전
                - summary: Delta Summary 통계
        """
        if not self.db_path.exists():
            return {"error": "SWRN index not found", "prs": []}
        
        # 버전 튜플 변환
        from_tuple = parse_sw_version(version_from)
        to_tuple = parse_sw_version(version_to)
        
        # from이 to보다 크면 스왑
        if from_tuple > to_tuple:
            from_tuple, to_tuple = to_tuple, from_tuple
            version_from, version_to = version_to, version_from
        
        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()
        
        # 모든 버전과 PR 목록 가져오기
        cursor.execute("""
            SELECT DISTINCT f.sw_version, p.pr_number, p.context, p.pr_type
            FROM pr_index p
            JOIN pdf_files f ON p.file_id = f.id
            WHERE p.pr_number IS NOT NULL AND p.pr_number != ''
            ORDER BY f.sw_version
        """)
        
        rows = cursor.fetchall()
        conn.close()
        
        # 버전별 PR 분류
        version_prs = {}  # version -> set of PRs
        all_versions = set()
        
        for row in rows:
            sw_version = row[0]
            pr_number = row[1]
            context = row[2] if len(row) > 2 else ""
            pr_type = row[3] if len(row) > 3 else "unknown"
            
            ver_tuple = parse_sw_version(sw_version)
            all_versions.add((ver_tuple, sw_version))
            
            # from 이후 ~ to 이하인 버전만 포함
            if from_tuple < ver_tuple <= to_tuple:
                if sw_version not in version_prs:
                    version_prs[sw_version] = {}
                if pr_number not in version_prs[sw_version]:
                    version_prs[sw_version][pr_number] = {
                        "pr_number": pr_number,
                        "context": context,
                        "pr_type": pr_type,
                        "sw_version": sw_version
                    }
        
        # 정렬된 버전 목록 (from 이후 ~ to 이하)
        sorted_versions = sorted(
            [(ver_tuple, sw_version) for ver_tuple, sw_version in all_versions 
             if from_tuple < ver_tuple <= to_tuple],
            key=lambda x: x[0]
        )
        
        # from 버전의 PR 목록 (이미 존재하는 PR)
        cursor = sqlite3.connect(str(self.db_path)).cursor()
        cursor.execute("""
            SELECT DISTINCT p.pr_number
            FROM pr_index p
            JOIN pdf_files f ON p.file_id = f.id
            WHERE p.pr_number IS NOT NULL AND p.pr_number != ''
        """)
        
        # from 버전 이하에 존재하는 모든 PR
        base_prs = set()
        rows = cursor.fetchall()
        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()
        
        for ver_tuple, sw_version in all_versions:
            if ver_tuple <= from_tuple:
                cursor.execute("""
                    SELECT DISTINCT p.pr_number
                    FROM pr_index p
                    JOIN pdf_files f ON p.file_id = f.id
                    WHERE f.sw_version = ?
                """, (sw_version,))
                for row in cursor.fetchall():
                    base_prs.add(row[0])
        
        conn.close()
        
        # 해당 버전 범위의 모든 PR 수집 (이전 버전에 있던 PR도 포함)
        all_prs = []
        versions_included = []
        seen_prs = set()  # 중복 방지용
        
        for ver_tuple, sw_version in sorted_versions:
            versions_included.append(sw_version)
            if sw_version in version_prs:
                for pr_number, pr_info in version_prs[sw_version].items():
                    if pr_number not in seen_prs:
                        # 이전 버전에 있었는지 표시
                        pr_info["is_new"] = pr_number not in base_prs
                        all_prs.append(pr_info)
                        seen_prs.add(pr_number)
                        # base_prs에 추가하여 다음 버전에서 중복 체크
                        base_prs.add(pr_number)
        
        # PR 상세 정보 추가 (include_details=True인 경우)
        if include_details and all_prs:
            detailed_prs = []
            for pr_info in all_prs:
                pr_number = pr_info["pr_number"]
                try:
                    detail_result = self.get_pr_detail(pr_number)
                    if detail_result and "detail" in detail_result:
                        detail = detail_result["detail"]
                        pr_info["component"] = detail.get("component", "")
                        pr_info["module"] = detail.get("module", "")
                        pr_info["module_type"] = detail.get("module_type", "")
                        pr_info["affected_function"] = detail.get("affected_function", "")
                        pr_info["title"] = detail.get("title", "")
                        pr_info["benefits"] = detail.get("benefits", "")
                        pr_info["history"] = detail.get("history", "")
                except Exception as e:
                    pass  # 상세 정보 없으면 기본 정보만 사용
                detailed_prs.append(pr_info)
            all_prs = detailed_prs
        
        # Delta Summary 통계 생성
        summary = self._generate_delta_summary(all_prs)
        
        # 새로 추가된 PR 수 계산
        new_pr_count = sum(1 for pr in all_prs if pr.get("is_new", False))
        
        return {
            "from_version": version_from,
            "to_version": version_to,
            "versions_included": versions_included,
            "total_prs": len(all_prs),
            "total_new_prs": new_pr_count,
            "prs": all_prs,
            "summary": summary
        }

    def _generate_delta_summary(self, prs: List[Dict]) -> Dict:
        """
        Delta Summary 통계 생성 (PR 타입별, 컴포넌트별 분류)
        """
        summary = {
            "by_type": {
                "features": [],  # new features
                "bugs": []       # bug fixes
            },
            "by_component": {},
            "by_module": {},
            "by_version": {}
        }
        
        for pr in prs:
            pr_number = pr.get("pr_number", "")
            pr_type = pr.get("pr_type", "unknown").lower()
            component = pr.get("component", "") or "Unknown"
            module = pr.get("module", "") or "Unknown"
            sw_version = pr.get("sw_version", "") or "Unknown"
            
            # Type별 분류 (new/feature -> features, fixed -> bugs)
            if pr_type in ("new", "feature"):
                summary["by_type"]["features"].append(pr_number)
            else:
                summary["by_type"]["bugs"].append(pr_number)
            
            # Component별 분류
            if component not in summary["by_component"]:
                summary["by_component"][component] = []
            summary["by_component"][component].append(pr_number)
            
            # Module별 분류
            if module not in summary["by_module"]:
                summary["by_module"][module] = []
            summary["by_module"][module].append(pr_number)
            
            # Version별 분류
            if sw_version not in summary["by_version"]:
                summary["by_version"][sw_version] = []
            summary["by_version"][sw_version].append(pr_number)
        
        return summary

    def search_pr(self, pr_number: str) -> List[Dict]:
        """PR 번호로 검색 - 최신 SW 버전 우선 (HF > Release > B 빌드)"""
        if not self.db_path.exists():
            return []
        
        # PR 번호 정규화
        pr_num = pr_number.upper().strip()
        if not pr_num.startswith("PR-"):
            if re.match(r'^\d{6}$', pr_num):
                pr_num = f"PR-{pr_num}"
        
        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()
        
        # 모든 버전에서 PR 검색
        cursor.execute("""
            SELECT 
                p.pr_number,
                f.filename,
                f.sw_version,
                p.page_num,
                p.context,
                p.pr_type
            FROM pr_index p
            JOIN pdf_files f ON p.file_id = f.id
            WHERE p.pr_number = ?
        """, (pr_num,))
        
        raw_results = []
        seen_files = {}  # filename -> best result for that file
        
        for row in cursor.fetchall():
            filename = row[1]
            sw_version = row[2]
            page_num = row[3]
            
            # 같은 파일에서는 가장 큰 페이지 번호만 사용 (상세 정보 페이지)
            if filename in seen_files:
                if page_num > seen_files[filename]['page']:
                    seen_files[filename]['page'] = page_num
                    seen_files[filename]['context'] = row[4]
                continue
            
            # pr_type 처리
            pr_type = row[5] if len(row) > 5 else 'unknown'
            
            seen_files[filename] = {
                "pr_number": row[0],
                "filename": filename,
                "sw_version": sw_version,
                "page": page_num,
                "context": row[4],
                "pr_type": pr_type,
                "_version_tuple": parse_sw_version(sw_version)
            }
        
        conn.close()
        
        # 버전 튜플 기준으로 내림차순 정렬 (최신 버전 먼저)
        results = list(seen_files.values())
        results.sort(key=lambda x: x.get("_version_tuple", (0,0,0,0,0)), reverse=True)
        
        # 정렬용 튜플 제거
        for r in results:
            r.pop("_version_tuple", None)
        
        return results
    
    def search_text(self, query: str, limit: int = 20) -> List[Dict]:
        """전문 검색 (FTS5)"""
        if not self.db_path.exists():
            return []
        
        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()
        
        # FTS5 검색
        cursor.execute("""
            SELECT 
                f.filename,
                f.sw_version,
                pc.page_num,
                snippet(page_content, 2, '<b>', '</b>', '...', 30) as snippet
            FROM page_content pc
            JOIN pdf_files f ON CAST(pc.file_id AS INTEGER) = f.id
            WHERE page_content MATCH ?
            ORDER BY rank
            LIMIT ?
        """, (query, limit))
        
        results = []
        for row in cursor.fetchall():
            results.append({
                "filename": row[0],
                "sw_version": row[1],
                "page": int(row[2]),
                "snippet": row[3]
            })
        
        conn.close()
        return results
    
    def get_pr_detail(self, pr_number: str) -> Optional[Dict]:
        """PR 상세 정보 - 여러 페이지에 걸친 PR도 완전히 추출"""
        results = self.search_pr(pr_number)
        
        if not results:
            return None
        
        # 가장 최신 버전의 결과 사용
        result = results[0]
        
        # 해당 PDF의 해당 페이지에서 상세 정보 추출
        pdf_path = self.swrn_folder / result["filename"]
        
        if not pdf_path.exists():
            return result
        
        try:
            doc = fitz.open(str(pdf_path))
            db_page = result["page"] - 1  # 0-indexed, DB에 저장된 페이지 (목차일 수 있음)
            total_pages = len(doc)
            
            # PR 번호 정규화
            pr_num = pr_number.replace("PR-", "")
            next_pr_pattern = re.compile(r'\d+\.\d+\.\d+\.\d+\.\d+\.\s*PR[-\s]?\d{6}')
            
            # DB 페이지가 목차(TOC)인지 확인하고, 실제 상세 페이지 찾기
            # 목차 페이지 특징: "Component:" 또는 "Module:" 없이 PR 번호만 있음
            db_page_text = doc[db_page].get_text() if db_page < total_pages else ""
            
            # PR 상세 내용이 있는 페이지 찾기 (Component: 또는 Benefits 등이 있는 페이지)
            start_page = db_page
            pr_pattern = re.compile(rf'PR[-\s]?{pr_num}', re.IGNORECASE)
            detail_indicators = ['Component:', 'Module:', 'Benefits', 'Description', 'History', 'CV(Configurable Variable)']
            
            # DB 페이지에 PR 번호가 있는지 먼저 확인
            has_pr_in_db_page = pr_pattern.search(db_page_text) is not None
            
            # DB 페이지에 상세 정보가 있는지 확인
            has_detail = any(ind in db_page_text for ind in detail_indicators)
            
            # ★ 수정: DB 페이지에 PR 번호가 있으면 그 페이지 사용 (Release Notes Summary 형식 지원)
            if not has_pr_in_db_page and not has_detail:
                # 목차 페이지일 가능성 → 전체 PDF에서 상세 페이지 찾기
                for page_idx in range(total_pages):
                    page_text = doc[page_idx].get_text()
                    # PR 번호가 있고 상세 정보 지표가 있는 페이지
                    if pr_pattern.search(page_text) and any(ind in page_text for ind in detail_indicators):
                        # 해당 PR의 상세 내용인지 추가 확인
                        # PR 번호 근처에 Component: 등이 있어야 함
                        pr_match = pr_pattern.search(page_text)
                        if pr_match:
                            after_pr = page_text[pr_match.end():pr_match.end()+500]
                            if any(ind in after_pr for ind in detail_indicators[:3]):  # Component:, Module:, Benefits
                                start_page = page_idx
                                break
            
            # 시작 페이지부터 최대 5페이지까지 읽기 (대부분 PR은 1-3페이지)
            full_text = ""
            pages_read = 0
            max_pages = 5
            
            for page_idx in range(start_page, min(start_page + max_pages, total_pages)):
                page = doc[page_idx]
                page_text = page.get_text()
                
                if page_idx == start_page:
                    # 첫 페이지는 전체 추가
                    full_text += page_text
                    pages_read += 1
                else:
                    # 다음 페이지에서 새로운 PR이 시작하는지 확인
                    # 새 PR 패턴이 페이지 상단에 있으면 중단
                    first_500_chars = page_text[:500]
                    if next_pr_pattern.search(first_500_chars):
                        # 새 PR이 시작하기 전까지만 포함
                        match = next_pr_pattern.search(page_text)
                        if match:
                            full_text += page_text[:match.start()]
                        break
                    else:
                        # 현재 PR이 계속되면 페이지 전체 추가
                        full_text += "\n" + page_text
                        pages_read += 1
                        
                        # 페이지 내에서 새 PR 패턴이 있으면 거기까지만
                        match = next_pr_pattern.search(page_text)
                        if match:
                            # 다음 PR이 시작되면 중단
                            break
            
            doc.close()
            
            # PR 상세 정보 파싱
            detail = self._parse_pr_detail(pr_number, full_text)
            detail["_pages_read"] = pages_read  # 디버깅용
            detail["_start_page"] = start_page  # 디버깅용
            detail["_db_page"] = db_page  # 디버깅용
            detail["_full_text_len"] = len(full_text)  # 디버깅용
            result["detail"] = detail
            
        except Exception as e:
            result["error"] = str(e)
        
        return result
    
    def _parse_pr_detail(self, pr_number: str, page_text: str) -> Dict:
        """페이지 텍스트에서 PR 상세 정보 파싱 (여러 페이지 지원)"""
        detail = {}
        
        # PR 번호 패턴으로 시작점 찾기
        pr_num = pr_number.replace("PR-", "")
        
        # 해당 PR의 텍스트 섹션 추출 (다음 PR까지)
        # 페이지 번호 패턴 (Page XXX of XXXX)도 무시하도록 개선
        pr_section_pattern = rf'PR[-\s]?{pr_num}[:\s]*(.+?)(?=\n\s*\d+\.\d+\.\d+\.\d+\.\d+\.\s*PR[-\s]?\d|$)'
        section_match = re.search(pr_section_pattern, page_text, re.DOTALL | re.IGNORECASE)
        
        if section_match:
            section_text = section_match.group(1)
        else:
            section_text = page_text
        
        # 페이지 머리말/꼬리말 제거 (여러 패턴)
        # 1. "2300 Release Notes Summary X.X.X-SPXX Release" 패턴
        section_text = re.sub(r'\n?2300 Release Notes Summary[^\n]*\n', '\n', section_text, flags=re.IGNORECASE)
        # 2. "Page XXX of XXXX" 패턴
        section_text = re.sub(r'\n?Page \d+ of \d+\n?', '\n', section_text, flags=re.IGNORECASE)
        # 3. "Lam Research CONFIDENTIAL" 패턴
        section_text = re.sub(r'\n?Lam Research CONFIDENTIAL[^\n]*\n', '\n', section_text, flags=re.IGNORECASE)
        # 4. 연속된 빈 줄 정리
        section_text = re.sub(r'\n{3,}', '\n\n', section_text)
        
        # PR 유형 감지 (New Feature vs Issue Fix)
        pr_position = page_text.find(f"PR-{pr_num}")
        if pr_position == -1:
            pr_position = page_text.find(pr_num)
        pr_type = self._detect_pr_type(page_text, pr_position) if pr_position >= 0 else 'unknown'
        detail["pr_type"] = pr_type
        detail["pr_type_label"] = "New Feature" if pr_type == 'new_feature' else ("Issue Fix" if pr_type == 'issue_fix' else "Unknown")
        
        # ★★★ 먼저 표 형식 파싱 시도 (Release Notes Summary 형식) ★★★
        # 형식: 각 열이 줄바꿈으로 구분됨
        # Area
        # Module  
        # Function (여러 줄일 수 있음)
        # PR-XXXXXX – Description
        # Solution
        
        # PR 번호 위치 찾기
        pr_pos = re.search(rf'PR[-\s]?{pr_num}', page_text, re.IGNORECASE)
        if pr_pos:
            # PR 번호 앞 400자 내에서 Affected Function 추출
            start_pos = max(0, pr_pos.start() - 400)
            before_pr_text = page_text[start_pos:pr_pos.start()]
            
            # 줄바꿈으로 분리된 각 줄 확인 (역순)
            lines = [l.strip() for l in before_pr_text.split('\n') if l.strip()]
            
            # 이전 PR까지의 텍스트 제거
            clean_lines = []
            for line in reversed(lines):
                # 이전 PR 패턴이면 중단
                if re.match(r'^PR[-\s]?\d{6}', line) or re.search(r'PR[-\s]?\d{6}', line):
                    break
                # 헤더나 무관한 텍스트 제외
                if line in ['Module', 'Module Type', 'Affected', 'Function', 'Issue', 'Solution', 
                            'Affected Function', 'Issue Description']:
                    continue
                # Solution 관련 텍스트면 중단 (이전 PR의 solution)
                if line.startswith('The software has been') or 'has been changed' in line.lower():
                    break
                clean_lines.insert(0, line)
            
            # Affected Function 추출 - 마지막 의미있는 줄들 합치기
            # clean_lines에서 'All' 이후의 줄들이 Affected Function
            affected_parts = []
            found_all = False
            for line in clean_lines:
                if line == 'All':
                    found_all = True
                    continue
                if found_all and line not in ['All', 'N/A', '-', 'All C', 'All G', 'Series']:
                    if not re.match(r'^[\d\.]+$', line) and not line.startswith('The '):
                        affected_parts.append(line)
            
            if affected_parts:
                # 여러 줄을 공백으로 합치기
                detail["affected_function"] = ' '.join(affected_parts[-3:])[:100]  # 최대 3줄
            else:
                # fallback: 마지막 의미있는 줄
                for line in reversed(clean_lines[-5:]):
                    if len(line) > 2 and line not in ['All', 'N/A', '-', 'All C', 'All G', 'Series', 'All All']:
                        if not re.match(r'^[\d\.]+$', line) and not line.startswith('The '):
                            detail["affected_function"] = line[:100]
                            break
        
        # PR 설명 추출 (Issue Description)
        pr_desc_match = re.search(rf'PR[-\s]?{pr_num}[\s–\-:]+([^\.]+\.)', page_text, re.IGNORECASE)
        if pr_desc_match:
            desc_text = pr_desc_match.group(1).strip()
            # "–" 뒤의 실제 설명 추출
            if desc_text.startswith('–') or desc_text.startswith('-'):
                desc_text = desc_text[1:].strip()
            if len(desc_text) > 10:
                detail["issue_description"] = desc_text[:300]
                detail["title"] = desc_text[:100]
        
        # Solution 추출 - PR 번호 이후의 텍스트에서만 검색
        if pr_pos:
            # PR 번호 이후 600자 내에서 solution 찾기
            after_pr_text = page_text[pr_pos.start():pr_pos.start()+600]
            # 줄바꿈을 공백으로 변경 (PDF 텍스트는 줄바꿈이 많음)
            after_pr_text_normalized = re.sub(r'\s+', ' ', after_pr_text)
            
            # "The software has been changed" 패턴 (줄바꿈 처리됨)
            solution_match = re.search(r'(The software has been changed[^\.]+\.)', after_pr_text_normalized, re.IGNORECASE)
            if solution_match:
                detail["solution"] = solution_match.group(1).strip()[:200]
            
            # 대안 패턴: "has been" + changed/fixed/updated
            if not detail.get("solution"):
                alt_solution = re.search(r'([A-Z][^\.]*has been (?:changed|fixed|updated|modified|corrected)[^\.]+\.)', after_pr_text_normalized, re.IGNORECASE)
                if alt_solution:
                    detail["solution"] = alt_solution.group(1).strip()[:200]
        
        # ★★★ 상세 형식 파싱 (Component:, Module: 등 헤더가 있는 경우) ★★★
        
        # Title 추출 (PR 번호 바로 뒤의 텍스트) - 이미 위에서 추출 안됐으면
        if not detail.get("title"):
            title_match = re.search(rf'PR[-\s]?{pr_num}[:\s]*([^\n]+)', page_text, re.IGNORECASE)
            if title_match:
                detail["title"] = title_match.group(1).strip()
        
        # Component 추출 - 항상 추출 시도
        comp_match = re.search(r'Component[:\s]*\n?([A-Za-z][^\n]+)', section_text, re.IGNORECASE)
        if comp_match:
            comp_val = comp_match.group(1).strip()
            # "PM", "Module" 등 불필요한 접미사 제거
            if not comp_val.lower().startswith('module'):
                detail["component"] = comp_val
                # Affected Function이 없으면 Component 사용
                if not detail.get("affected_function"):
                    detail["affected_function"] = comp_val[:80]
        
        # Module 추출
        module_match = re.search(r'(?<!Module )Module[:\s]*\n?([A-Za-z0-9][^\n]+)', section_text, re.IGNORECASE)
        if module_match:
            val = module_match.group(1).strip()
            # Module Type이 아닌 경우만
            if not val.lower().startswith('type'):
                detail["module"] = val
                # Component가 없으면 Module을 Component로 사용
                if not detail.get("component"):
                    detail["component"] = val
        
        # Affected Function 추출 (헤더 다음 줄의 실제 값)
        af_match = re.search(r'Affected Function[:\s]*\n([^\n]+)', section_text, re.IGNORECASE)
        if af_match:
            val = af_match.group(1).strip()
            # 페이지 정보가 아닌 경우만
            if not re.match(r'^\d+ Release Notes|^Page \d+|^Lam Research', val, re.IGNORECASE):
                detail["affected_function"] = val
        # 대안: 같은 줄에 값이 있는 경우
        if not detail.get("affected_function"):
            af_match2 = re.search(r'Affected Function[:\s]+([A-Za-z][^\n]+)', section_text, re.IGNORECASE)
            if af_match2:
                val = af_match2.group(1).strip()
                if not re.match(r'^\d+ Release Notes|^Page \d+|^Lam Research', val, re.IGNORECASE):
                    detail["affected_function"] = val
        
        # History 추출 (다음 섹션까지)
        history_match = re.search(
            r'History\s*\n(.+?)(?=Benefits|Description|CV\s*\(|Factory Automation|$)', 
            section_text, re.DOTALL | re.IGNORECASE
        )
        if history_match:
            history_text = history_match.group(1).strip()
            history_text = re.sub(r'\s+', ' ', history_text)
            detail["history"] = history_text
        
        # Benefits 추출 (페이지 정보 제외)
        benefits_match = re.search(
            r'Benefits\s*\n(.+?)(?=Description|CV\s*\(|History|Factory Automation|Recipe Parameter|UI Changes|Alarm|\d+\.\d+\.\d+\.\d+\.\d+\.|$)', 
            section_text, re.DOTALL | re.IGNORECASE
        )
        if benefits_match:
            benefits_text = benefits_match.group(1).strip()
            # 페이지 정보 제거
            benefits_text = re.sub(r'2300 Release Notes Summary[^\n]*', '', benefits_text)
            benefits_text = re.sub(r'Page \d+ of \d+', '', benefits_text)
            benefits_text = re.sub(r'Lam Research CONFIDENTIAL[^\n]*', '', benefits_text)
            benefits_text = re.sub(r'\s+', ' ', benefits_text).strip()
            if benefits_text:
                detail["benefits"] = benefits_text
        
        # Description 추출 (New Feature 섹션)
        desc_match = re.search(
            r'Description\s*\n(.+?)(?=CV\s*\(|Factory Automation|Recipe Parameter|UI Changes|Alarm|History|Benefits|\d+\.\d+\.\d+\.\d+\.\d+\.|$)', 
            section_text, re.DOTALL | re.IGNORECASE
        )
        if desc_match:
            desc_text = desc_match.group(1).strip()
            # 페이지 정보 제거
            desc_text = re.sub(r'2300 Release Notes Summary[^\n]*', '', desc_text)
            desc_text = re.sub(r'Page \d+ of \d+', '', desc_text)
            desc_text = re.sub(r'Lam Research CONFIDENTIAL[^\n]*', '', desc_text)
            desc_text = re.sub(r'\s+', ' ', desc_text).strip()
            if desc_text:
                detail["description"] = desc_text
        
        # ===== Problem Report 섹션 필드 (Issue Description, Root Cause, Solution) =====
        
        # Issue Description 추출
        issue_desc_match = re.search(
            r'Issue Description\s*\n(.+?)(?=Root Cause|Solution|CV\s*\(|Factory Automation|\d+\.\d+\.\d+\.\d+\.\d+\.|$)', 
            section_text, re.DOTALL | re.IGNORECASE
        )
        if issue_desc_match:
            issue_text = issue_desc_match.group(1).strip()
            # 페이지 정보 제거
            issue_text = re.sub(r'2300 Release Notes Summary[^\n]*', '', issue_text)
            issue_text = re.sub(r'Page \d+ of \d+', '', issue_text)
            issue_text = re.sub(r'Lam Research CONFIDENTIAL[^\n]*', '', issue_text)
            issue_text = re.sub(r'\s+', ' ', issue_text).strip()
            if issue_text:
                detail["issue_description"] = issue_text
        
        # Root Cause 추출
        root_cause_match = re.search(
            r'Root Cause\s*\n(.+?)(?=Solution|CV\s*\(|Factory Automation|Recipe Parameter|\d+\.\d+\.\d+\.\d+\.\d+\.|$)', 
            section_text, re.DOTALL | re.IGNORECASE
        )
        if root_cause_match:
            root_cause_text = root_cause_match.group(1).strip()
            # 페이지 정보 제거
            root_cause_text = re.sub(r'2300 Release Notes Summary[^\n]*', '', root_cause_text)
            root_cause_text = re.sub(r'Page \d+ of \d+', '', root_cause_text)
            root_cause_text = re.sub(r'Lam Research CONFIDENTIAL[^\n]*', '', root_cause_text)
            root_cause_text = re.sub(r'\s+', ' ', root_cause_text).strip()
            detail["root_cause"] = root_cause_text
        
        # Solution 추출 (헤더 형식 - Component:, Module: 등이 있는 상세 PDF용)
        # ★ 표 형식에서 이미 solution을 찾았으면 덮어쓰지 않음
        if not detail.get("solution"):
            solution_match = re.search(
                r'Solution\s*\n(.+?)(?=CV\s*\(|Factory Automation|Recipe Parameter|UI Changes|Alarm|\d+\.\d+\.\d+\.\d+\.\d+\.|$)', 
                section_text, re.DOTALL | re.IGNORECASE
            )
            if solution_match:
                solution_text = solution_match.group(1).strip()
                # 페이지 정보 제거
                solution_text = re.sub(r'2300 Release Notes Summary[^\n]*', '', solution_text)
                solution_text = re.sub(r'Page \d+ of \d+', '', solution_text)
                solution_text = re.sub(r'Lam Research CONFIDENTIAL[^\n]*', '', solution_text)
                solution_text = re.sub(r'\s+', ' ', solution_text).strip()
                if solution_text:
                    detail["solution"] = solution_text
        
        # ===== Solution and Benefit 통합 필드 (UI 표시용) =====
        # - New Feature: Benefits 사용
        # - Issue Fix: Solution 사용
        if pr_type == 'new_feature':
            detail["solution_or_benefit"] = detail.get("benefits", "")
            detail["solution_or_benefit_label"] = "Benefits"
        else:  # issue_fix or unknown
            detail["solution_or_benefit"] = detail.get("solution", "")
            detail["solution_or_benefit_label"] = "Solution"
        
        # ===== Issue Description 통합 필드 (UI 표시용) =====
        # - New Feature: Description 사용
        # - Issue Fix: Issue Description 사용
        if pr_type == 'new_feature':
            detail["issue_or_description"] = detail.get("description", "")
        else:
            detail["issue_or_description"] = detail.get("issue_description", detail.get("description", ""))
        
        # ===== 테이블 파싱 (모든 테이블 타입 통합 처리) =====
        
        # Factory Automation Changes 테이블 (ID Type 헤더 포함)
        fa_pattern = r'Factory Automation\s*(?:Changes|Interface)?\s*\n(?:ID Type|Name).*?Action\s*\n(.+?)(?=CV\s*\(Configurable|Recipe Parameter|UI\s*Changes|Alarm|$)'
        fa_match = re.search(fa_pattern, section_text, re.IGNORECASE | re.DOTALL)
        if fa_match:
            fa_text = fa_match.group(1).strip()
            if fa_text and len(fa_text) > 5:
                detail["factory_automation_changes"] = self._parse_fa_table(fa_text)
        
        # CV (Configurable Variable) Changes 테이블 - 모든 CV 테이블 찾기
        # 종료 조건: 다른 섹션 시작, 섹션 번호(7.X), 또는 테이블 끝
        cv_pattern = r'CV\s*\(Configurable Variable\)\s*Changes\s*\n(?:Name\s+Description.*?Action\s*\n)?(.+?)(?=Factory Automation|Recipe Parameter|UI\s*Changes|Alarm|CV\s*\(Configurable|\n\d+\.\d+\.?\s*\n|$)'
        cv_matches = list(re.finditer(cv_pattern, section_text, re.IGNORECASE | re.DOTALL))
        if cv_matches:
            all_cv_html = []
            for i, cv_match in enumerate(cv_matches):
                cv_text = cv_match.group(1).strip()
                if cv_text and len(cv_text) > 5:
                    cv_html = self._parse_cv_table(cv_text, target_pr=pr_number)
                    all_cv_html.append(cv_html)
            if all_cv_html:
                detail["cv_changes"] = '\n'.join(all_cv_html)
        
        # Recipe Parameter Changes 테이블
        rp_pattern = r'Recipe Parameter\s*Changes\s*\n(?:Name\s+Description.*?Action\s*\n)?(.+?)(?=Factory Automation|CV\s*\(|UI\s*Changes|Alarm|\n\d+\.\d+\.?\s*\n|$)'
        rp_match = re.search(rp_pattern, section_text, re.IGNORECASE | re.DOTALL)
        if rp_match:
            rp_text = rp_match.group(1).strip()
            if rp_text and len(rp_text) > 5:
                detail["recipe_parameter_changes"] = self._parse_cv_table(rp_text, target_pr=pr_number)
        
        # UI Changes 테이블
        ui_pattern = r'UI\s*Changes\s*\n(?:Name\s+Description.*?Action\s*\n)?(.+?)(?=Factory Automation|CV\s*\(|Recipe Parameter|Alarm|\n\d+\.\d+\.?\s*\n|$)'
        ui_match = re.search(ui_pattern, section_text, re.IGNORECASE | re.DOTALL)
        if ui_match:
            ui_text = ui_match.group(1).strip()
            if ui_text and len(ui_text) > 5:
                detail["ui_changes"] = self._parse_cv_table(ui_text, target_pr=pr_number)
        
        # Alarm Changes 테이블 (Alarm ID Severity Description Recovery 헤더)
        alarm_pattern = r'Alarm\s*(?:changes|Changes|modifications)?\s*\n(?:Alarm\s*ID|ID|Name).*?Action\s*\n(.+?)(?=Factory Automation|CV\s*\(|Recipe Parameter|UI\s*Changes|$)'
        alarm_match = re.search(alarm_pattern, section_text, re.IGNORECASE | re.DOTALL)
        if alarm_match:
            alarm_text = alarm_match.group(1).strip()
            if alarm_text and len(alarm_text) > 5:
                detail["alarm_changes"] = self._parse_alarm_table(alarm_text)
        
        return detail
    
    def _parse_fa_table(self, fa_text: str) -> str:
        """Factory Automation Changes 테이블을 HTML로 변환
        
        헤더: ID Type | Variable ID | Description | Old Values | New Values | Action
        """
        lines = [l.strip() for l in fa_text.split('\n') if l.strip()]
        
        if not lines:
            return f'<pre style="background:#f5f5f5;padding:10px;border-radius:5px;font-size:12px;">{fa_text}</pre>'
        
        # action 키워드 위치 찾기
        action_keywords = ['modified', 'added', 'removed', 'new', 'deleted']
        
        html = '<table style="width:100%;border-collapse:collapse;font-size:12px;margin-top:5px;">'
        html += '<thead><tr style="background:#e8f4f8;">'
        html += '<th style="border:1px solid #ccc;padding:6px;text-align:left;width:10%;">ID Type</th>'
        html += '<th style="border:1px solid #ccc;padding:6px;text-align:center;width:10%;">Variable ID</th>'
        html += '<th style="border:1px solid #ccc;padding:6px;text-align:left;width:40%;">Description</th>'
        html += '<th style="border:1px solid #ccc;padding:6px;text-align:center;width:12%;">Old Values</th>'
        html += '<th style="border:1px solid #ccc;padding:6px;text-align:center;width:12%;">New Values</th>'
        html += '<th style="border:1px solid #ccc;padding:6px;text-align:center;width:10%;">Action</th>'
        html += '</tr></thead><tbody>'
        
        # 각 항목 파싱 (CEID / SVID 로 시작하는 패턴)
        i = 0
        while i < len(lines):
            line = lines[i]
            
            # ID Type 시작 (CEID, SVID 등)
            if line.upper() in ['CEID', 'SVID', 'DCID', 'VID']:
                id_type = line
                variable_id = ''
                description = ''
                old_val = ''
                new_val = ''
                action = ''
                
                # 다음 줄들에서 정보 추출
                j = i + 1
                while j < len(lines):
                    next_line = lines[j]
                    
                    # action 키워드면 항목 종료
                    if next_line.lower() in action_keywords:
                        action = next_line
                        j += 1
                        break
                    # 다음 ID Type이면 종료
                    elif next_line.upper() in ['CEID', 'SVID', 'DCID', 'VID']:
                        break
                    # 숫자면 Variable ID (보통 0)
                    elif next_line.isdigit() and not variable_id:
                        variable_id = next_line
                    # 나머지는 Description
                    else:
                        if description:
                            description += ' ' + next_line
                        else:
                            description = next_line
                    j += 1
                
                # 행 추가
                action_color = '#d4edda' if action.lower() == 'added' else ('#fff3cd' if action.lower() == 'modified' else '#f8d7da' if action.lower() in ['removed', 'deleted'] else '')
                html += f'<tr>'
                html += f'<td style="border:1px solid #ccc;padding:6px;">{id_type}</td>'
                html += f'<td style="border:1px solid #ccc;padding:6px;text-align:center;">{variable_id}</td>'
                html += f'<td style="border:1px solid #ccc;padding:6px;">{description}</td>'
                html += f'<td style="border:1px solid #ccc;padding:6px;text-align:center;">{old_val}</td>'
                html += f'<td style="border:1px solid #ccc;padding:6px;text-align:center;">{new_val}</td>'
                html += f'<td style="border:1px solid #ccc;padding:6px;text-align:center;background:{action_color}">{action}</td>'
                html += '</tr>'
                
                i = j
            else:
                i += 1
        
        html += '</tbody></table>'
        return html
    
    def _parse_alarm_table(self, alarm_text: str) -> str:
        """Alarm Changes 테이블을 HTML로 변환
        
        헤더: Alarm ID | Severity | Description | Recovery | Old Value | New Value | Action
        """
        lines = [l.strip() for l in alarm_text.split('\n') if l.strip()]
        
        if not lines:
            return f'<pre style="background:#f5f5f5;padding:10px;border-radius:5px;font-size:12px;">{alarm_text}</pre>'
        
        action_keywords = ['modified', 'added', 'removed', 'new', 'deleted']
        severity_keywords = ['error', 'warning', 'info', 'critical']
        
        html = '<table style="width:100%;border-collapse:collapse;font-size:12px;margin-top:5px;">'
        html += '<thead><tr style="background:#ffe6e6;">'
        html += '<th style="border:1px solid #ccc;padding:6px;text-align:center;width:8%;">Alarm ID</th>'
        html += '<th style="border:1px solid #ccc;padding:6px;text-align:center;width:10%;">Severity</th>'
        html += '<th style="border:1px solid #ccc;padding:6px;text-align:left;width:35%;">Description</th>'
        html += '<th style="border:1px solid #ccc;padding:6px;text-align:left;width:20%;">Recovery</th>'
        html += '<th style="border:1px solid #ccc;padding:6px;text-align:center;width:9%;">Old Value</th>'
        html += '<th style="border:1px solid #ccc;padding:6px;text-align:center;width:9%;">New Value</th>'
        html += '<th style="border:1px solid #ccc;padding:6px;text-align:center;width:9%;">Action</th>'
        html += '</tr></thead><tbody>'
        
        # 각 Alarm 항목 파싱 (숫자 ID 또는 Severity로 시작)
        i = 0
        while i < len(lines):
            line = lines[i]
            
            # Alarm ID (숫자) 또는 Severity로 시작
            if line.isdigit() or line.lower() in severity_keywords:
                alarm_id = line if line.isdigit() else '0'
                severity = '' if line.isdigit() else line
                description = ''
                recovery = ''
                old_val = ''
                new_val = ''
                action = ''
                
                j = i + 1
                in_recovery = False
                
                while j < len(lines):
                    next_line = lines[j]
                    
                    # action 키워드면 항목 종료
                    if next_line.lower() in action_keywords:
                        action = next_line
                        j += 1
                        break
                    # Severity 키워드
                    elif next_line.lower() in severity_keywords and not severity:
                        severity = next_line
                    # 다음 Alarm (숫자 ID)이면 종료
                    elif next_line.isdigit() and description:
                        break
                    # Recovery 관련 키워드
                    elif 'Acknowle' in next_line or 'Restart' in next_line or 'Suppress' in next_line:
                        in_recovery = True
                        if recovery:
                            recovery += ' ' + next_line
                        else:
                            recovery = next_line
                    elif in_recovery and next_line not in severity_keywords:
                        # Recovery 계속
                        recovery += ' ' + next_line
                        if 'restart' in next_line.lower():
                            in_recovery = False
                    else:
                        # Description
                        if description:
                            description += ' ' + next_line
                        else:
                            description = next_line
                    j += 1
                
                # 행 추가
                severity_color = '#f8d7da' if severity.lower() == 'error' else ('#fff3cd' if severity.lower() == 'warning' else '')
                action_color = '#d4edda' if action.lower() == 'added' else ('#fff3cd' if action.lower() == 'modified' else '#f8d7da' if action.lower() in ['removed', 'deleted'] else '')
                
                html += f'<tr>'
                html += f'<td style="border:1px solid #ccc;padding:6px;text-align:center;">{alarm_id}</td>'
                html += f'<td style="border:1px solid #ccc;padding:6px;text-align:center;background:{severity_color}">{severity}</td>'
                html += f'<td style="border:1px solid #ccc;padding:6px;">{description}</td>'
                html += f'<td style="border:1px solid #ccc;padding:6px;font-size:11px;">{recovery}</td>'
                html += f'<td style="border:1px solid #ccc;padding:6px;text-align:center;">{old_val}</td>'
                html += f'<td style="border:1px solid #ccc;padding:6px;text-align:center;">{new_val}</td>'
                html += f'<td style="border:1px solid #ccc;padding:6px;text-align:center;background:{action_color}">{action}</td>'
                html += '</tr>'
                
                i = j
            else:
                i += 1
        
        html += '</tbody></table>'
        return html
    
    def _parse_cv_table(self, cv_text: str, target_pr: str = None) -> str:
        """CV Changes 텍스트를 HTML 테이블로 변환 (개선된 버전)
        
        PDF에서 추출된 텍스트 구조 문제 해결:
        1. 페이지 헤더/푸터가 중간에 삽입됨 → 제거
        2. 테이블 헤더가 반복됨 (Name Description...) → 제거
        3. 테이블 구조: Name | Description | Old Value | New Value | Action
        4. Description에 "min = X, max = Y, default = Z" 패턴 포함
        5. Action: added, modified, removed, deleted, new
        
        핵심 개선사항:
        - 변수명 패턴 (CamelCase, underscore) 정확히 탐지
        - Description 시작을 영어 문장 시작 패턴으로 구분 (This, The, A, Supports, etc.)
        - target_pr 지정 시 해당 PR 관련 항목만 필터링
        """
        
        # 0. 페이지 헤더/푸터 제거 (먼저 처리)
        cv_text = re.sub(r'Page\s+\d+\s+of\s+\d+', '', cv_text, flags=re.IGNORECASE)
        cv_text = re.sub(r'2300 Release Notes Summary[^\n]*', '', cv_text, flags=re.IGNORECASE)
        cv_text = re.sub(r'Lam Research CONFIDENTIAL[^\n]*', '', cv_text, flags=re.IGNORECASE)
        
        # 반복된 테이블 헤더 제거
        cv_text = re.sub(r'Name\s*\nDescription\s*\nOld\s*Value\s*\nNew\s*Value\s*\nAction\s*\n?', '', cv_text)
        cv_text = re.sub(r'Name\s*\nDescription\s*\nOld\s*\nValue\s*\nNew\s*\nValue\s*\nAction\s*\n?', '', cv_text)
        cv_text = re.sub(r'NameDescriptionOld\s*Value\s*New\s*Value\s*Action', '', cv_text, flags=re.IGNORECASE)
        cv_text = re.sub(r'\n{2,}', '\n', cv_text)
        
        action_keywords = ['modified', 'added', 'removed', 'new', 'deleted']
        
        # 줄 단위로 분리하고 빈 줄 제거
        lines = [l.strip() for l in cv_text.split('\n') if l.strip()]
        lines = [l for l in lines if not re.match(r'^(Page\s+\d+|2300 Release|Lam Research)', l, re.IGNORECASE)]
        
        # 섹션 번호(7.4. 등)가 나오면 그 이전까지만 처리
        section_break_idx = None
        for i, line in enumerate(lines):
            # 섹션 번호 패턴 (7.4., 8.1. 등)
            if re.match(r'^\d+\.\d+\.?\s*$', line):
                section_break_idx = i
                break
        if section_break_idx is not None:
            lines = lines[:section_break_idx]
        
        # 헤더 행 스킵
        start_idx = 0
        for i, line in enumerate(lines):
            # 패턴 1: 한 줄에 모든 헤더가 있는 경우
            if 'Name' in line and 'Description' in line and 'Action' in line:
                start_idx = i + 1
                break
            # 패턴 2: 여러 줄에 걸쳐 있는 경우 - "Action"이 단독으로 있는 줄 찾기
            if line.lower() == 'action' and i < 10:
                # 이전 줄들에 Name, Description 등이 있는지 확인
                prev_lines = ' '.join(lines[max(0, i-6):i]).lower()
                if 'name' in prev_lines and 'description' in prev_lines:
                    start_idx = i + 1
                    break
        
        lines = lines[start_idx:]
        
        if not lines:
            return f'<pre style="background:#f5f5f5;padding:10px;border-radius:5px;font-size:12px;white-space:pre-wrap;">{cv_text}</pre>'
        
        # 2. 각 CV 항목 파싱 - action 키워드 기준으로 분리
        current_row_lines = []
        rows_data = []
        
        for line in lines:
            current_row_lines.append(line)
            
            # 현재 줄이 action 키워드로 끝나면 하나의 행 완성
            if line.lower() in action_keywords:
                if current_row_lines:
                    row_text = ' '.join(current_row_lines)
                    rows_data.append(row_text)
                    current_row_lines = []
        
        # 마지막 남은 줄들 처리
        if current_row_lines:
            row_text = ' '.join(current_row_lines)
            if any(kw in row_text.lower() for kw in action_keywords):
                rows_data.append(row_text)
        
        if not rows_data:
            return f'<pre style="background:#f5f5f5;padding:10px;border-radius:5px;font-size:12px;white-space:pre-wrap;">{cv_text}</pre>'
        
        # 3. 각 행에서 Name, Description, Old Value, New Value, Action 추출
        cv_entries = []
        
        # Description 시작을 나타내는 영어 문장 시작 패턴
        description_start_words = [
            'this', 'the', 'a', 'an', 'when', 'if', 'used', 'uses', 'enables', 
            'specifies', 'defines', 'determines', 'indicates', 'controls', 'sets',
            'supports', 'holds', 'stores', 'represents', 'provides', 'allows',
            'configures', 'manages', 'handles', 'facilitates', 'contains', 'loads',
            'extended', 'corrected', 'updated', 'ensures', 'validates', 'represents'
        ]
        
        # target_pr 숫자만 추출 (PR-198877 -> 198877)
        target_pr_num = None
        if target_pr:
            target_pr_num = re.sub(r'[^0-9]', '', target_pr)
        
        for row_text in rows_data:
            # 다른 PR 번호가 포함된 행 필터링
            if target_pr_num:
                # 행에서 PR 번호 찾기 (PR-XXXXXX 또는 PR- XXXXXX 패턴)
                pr_in_row = re.search(r'PR[-\s]*(\d{5,6})', row_text, re.IGNORECASE)
                if pr_in_row:
                    row_pr_num = pr_in_row.group(1)
                    # 현재 검색 PR과 다르면 건너뜀
                    if row_pr_num != target_pr_num:
                        continue
                    # PR 번호 부분 제거 (Name에 포함되지 않도록)
                    row_text = re.sub(r'PR[-\s]*\d{5,6}\s*', '', row_text).strip()
            
            # Action 추출 (마지막 단어)
            action_match = re.search(r'\b(modified|added|removed|new|deleted)\s*$', row_text, re.IGNORECASE)
            if not action_match:
                continue
            
            action = action_match.group(1)
            remaining = row_text[:action_match.start()].strip()
            
            # NA NA 값 추출 (Old Value, New Value가 둘 다 NA인 경우)
            old_value = ''
            new_value = ''
            na_pattern = re.search(r'\s+NA\s+NA\s*$', remaining, re.IGNORECASE)
            if na_pattern:
                old_value = 'NA'
                new_value = 'NA'
                remaining = remaining[:na_pattern.start()].strip()
            
            # 패턴 1: "min = X, max = Y, default = Z"
            value_pattern = re.search(r'(min\s*=\s*[\d.]+,?\s*max\s*=\s*[\d.]+,?\s*default\s*=\s*[\w.]+)', remaining, re.IGNORECASE)
            if value_pattern:
                new_value = value_pattern.group(1)
                remaining = remaining[:value_pattern.start()].strip()
            else:
                # 패턴 2: "default = X" 만 있는 경우
                default_pattern = re.search(r'(default\s*=\s*[\w.]+)\s*$', remaining, re.IGNORECASE)
                if default_pattern:
                    new_value = default_pattern.group(1)
                    remaining = remaining[:default_pattern.start()].strip()
            
            # 개선된 Name과 Description 분리 로직
            words = remaining.split()
            name_parts = []
            description_start_idx = 0
            
            for i, word in enumerate(words):
                # Description 시작 감지: 영어 문장 시작 단어
                if word.lower() in description_start_words:
                    description_start_idx = i
                    break
                
                # 변수명 조각 판단
                is_varname_part = False
                
                if i == 0:
                    # 첫 단어: 변수명 패턴 여부 판단
                    # - 언더스코어 포함 (RFM_, ESC_ 등)
                    # - 대문자로 시작 (ConfigEditor, Process 등)
                    # - CamelCase 패턴 (loadConfig, restoreCVs 등) - 대문자 포함
                    # - 숫자 포함 (State1, Mode2 등)
                    has_underscore = '_' in word
                    starts_upper = len(word) > 0 and word[0].isupper()
                    has_camelcase = any(c.isupper() for c in word) or any(c.isdigit() for c in word)
                    is_description_word = word.lower() in description_start_words
                    
                    if not is_description_word and (has_underscore or starts_upper or has_camelcase):
                        is_varname_part = True
                else:
                    # 후속 단어: CamelCase 조각 판단
                    
                    # 소문자로 시작하는 짧은 단어 (CamelCase의 중간 조각)
                    if len(word) > 0 and word[0].islower() and len(word) <= 25:
                        # Description 시작 단어가 아니면 변수명 조각
                        if word.lower() not in description_start_words:
                            is_varname_part = True
                    # 숫자로 시작 (State1, State2 등)
                    elif len(word) > 0 and word[0].isdigit() and len(word) <= 5:
                        is_varname_part = True
                    # 대문자로 시작하고 언더스코어 포함 (변수명 연속)
                    elif '_' in word:
                        is_varname_part = True
                    # 대문자로 시작하는 짧은 단어 (CamelCase 조각일 수 있음)
                    elif len(word) > 0 and word[0].isupper() and len(word) <= 20:
                        # 하지만 Description 시작 단어면 중단
                        if word.lower() in description_start_words:
                            description_start_idx = i
                            break
                        is_varname_part = True
                
                if is_varname_part:
                    name_parts.append(word)
                    description_start_idx = i + 1
                else:
                    break
            
            # 변수명 조립 (공백 없이 합치기)
            name = ''.join(name_parts)
            
            # Description 추출 (변수명 이후의 모든 텍스트)
            if description_start_idx < len(words):
                description = ' '.join(words[description_start_idx:])
            else:
                description = ''
            
            # 변수명이 없거나 너무 짧으면 첫 번째 단어 사용
            if len(name) < 3:
                name = words[0] if words else ''
                description = ' '.join(words[1:]) if len(words) > 1 else ''
            
            cv_entries.append({
                'name': name,
                'description': description,
                'old_value': old_value,
                'new_value': new_value,
                'action': action
            })
        
        # 4. HTML 테이블 생성
        if not cv_entries:
            return f'<pre style="background:#f5f5f5;padding:10px;border-radius:5px;font-size:12px;white-space:pre-wrap;">{cv_text}</pre>'
        
        html = '<table style="width:100%;border-collapse:collapse;font-size:12px;margin-top:5px;">'
        html += '<thead><tr style="background:#e8f4f8;">'
        html += '<th style="border:1px solid #ccc;padding:8px;text-align:left;width:30%;">Name</th>'
        html += '<th style="border:1px solid #ccc;padding:8px;text-align:left;width:25%;">Description</th>'
        html += '<th style="border:1px solid #ccc;padding:8px;text-align:center;width:10%;">Old Value</th>'
        html += '<th style="border:1px solid #ccc;padding:8px;text-align:center;width:25%;">New Value</th>'
        html += '<th style="border:1px solid #ccc;padding:8px;text-align:center;width:10%;">Action</th>'
        html += '</tr></thead><tbody>'
        
        for entry in cv_entries:
            action_lower = entry['action'].lower()
            if action_lower in ['added', 'new']:
                action_color = '#28a745'
                action_bg = '#e8f5e9'
            elif action_lower in ['removed', 'deleted']:
                action_color = '#dc3545'
                action_bg = '#ffebee'
            else:
                action_color = '#007bff'
                action_bg = '#e3f2fd'
            
            html += f'<tr>'
            html += f'<td style="border:1px solid #ddd;padding:8px;font-family:monospace;font-weight:bold;background:#fafafa;word-break:break-all;">{entry["name"]}</td>'
            html += f'<td style="border:1px solid #ddd;padding:8px;">{entry["description"]}</td>'
            html += f'<td style="border:1px solid #ddd;padding:8px;text-align:center;font-family:monospace;background:#fff8e1;">{entry["old_value"]}</td>'
            html += f'<td style="border:1px solid #ddd;padding:8px;text-align:center;font-family:monospace;background:#e8f5e9;">{entry["new_value"]}</td>'
            html += f'<td style="border:1px solid #ddd;padding:8px;text-align:center;color:{action_color};font-weight:bold;background:{action_bg};">{entry["action"]}</td>'
            html += f'</tr>'
        
        html += '</tbody></table>'
        return html
    
    def search_pr_by_keyword(self, keyword: str, limit: int = 10) -> Dict:
        """키워드 기반 PR 검색 - 테이블 형태로 결과 반환
        
        Args:
            keyword: 검색할 키워드 (예: "Bias RF", "chamber", "alarm")
            limit: 최대 결과 수
            
        Returns:
            검색 결과 딕셔너리:
            - found: 결과 개수
            - keyword: 검색 키워드
            - results: PR 리스트 (pr_number, sw_version, title, issue_description, solution 등)
            - html_table: HTML 테이블 형태의 결과
        """
        if not self.db_path.exists():
            return {"found": 0, "error": "Index not built"}
        
        # FTS5 전문 검색으로 키워드 포함 페이지 찾기
        text_results = self.search_text(keyword, limit=limit * 3)  # 중복 고려하여 더 많이 검색
        
        if not text_results:
            return {"found": 0, "keyword": keyword, "results": [], "html_table": ""}
        
        # 발견된 페이지에서 PR 번호 추출 및 상세 정보 수집
        seen_prs = set()
        pr_results = []
        
        for text_result in text_results:
            # 해당 페이지의 PR들 찾기
            conn = sqlite3.connect(str(self.db_path))
            cursor = conn.cursor()
            
            cursor.execute("""
                SELECT DISTINCT p.pr_number, f.sw_version, p.context, f.filename
                FROM pr_index p
                JOIN pdf_files f ON p.file_id = f.id
                WHERE f.filename = ? AND p.page_num = ?
                ORDER BY f.sw_version DESC
            """, (text_result["filename"], text_result["page"]))
            
            for row in cursor.fetchall():
                pr_num = row[0]
                if pr_num in seen_prs:
                    continue
                seen_prs.add(pr_num)
                
                # PR 상세 정보 가져오기
                pr_detail = self.get_pr_detail(pr_num)
                if pr_detail:
                    detail = pr_detail.get("detail", {})
                    pr_results.append({
                        "pr_number": pr_num,
                        "sw_version": pr_detail.get("sw_version", ""),
                        "title": detail.get("title", ""),
                        "affected_function": detail.get("affected_function", ""),
                        "issue_description": detail.get("issue_description", detail.get("description", "")),
                        "solution": detail.get("solution", detail.get("benefits", "")),
                        "context": row[2][:150] if row[2] else ""
                    })
                
                if len(pr_results) >= limit:
                    break
            
            conn.close()
            
            if len(pr_results) >= limit:
                break
        
        # HTML 테이블 생성
        html_table = self._format_keyword_search_table(keyword, pr_results)
        
        return {
            "found": len(pr_results),
            "keyword": keyword,
            "results": pr_results,
            "html_table": html_table
        }
    
    def _format_keyword_search_table(self, keyword: str, results: List[Dict]) -> str:
        """키워드 검색 결과를 HTML 테이블로 포맷팅"""
        if not results:
            return f"<p>🔍 '<b>{keyword}</b>'에 대한 검색 결과가 없습니다.</p>"
        
        html = f'<div style="margin-bottom:10px;"><h3 style="margin:0 0 8px 0;color:#7c3aed;">🔍 "{keyword}" 관련 PR 검색 결과 ({len(results)}건)</h3></div>'
        html += '<table style="width:100%;border-collapse:collapse;font-size:14px;margin-bottom:10px;">'
        html += '<thead><tr style="background:linear-gradient(135deg,#7c3aed,#a855f7);color:white;">'
        html += '<th style="border:1px solid #6b21a8;padding:12px;text-align:left;width:12%;">PR Number</th>'
        html += '<th style="border:1px solid #6b21a8;padding:12px;text-align:left;width:10%;">SW Version</th>'
        html += '<th style="border:1px solid #6b21a8;padding:12px;text-align:left;width:25%;">Affected Function / Title</th>'
        html += '<th style="border:1px solid #6b21a8;padding:12px;text-align:left;width:28%;">Issue / Description</th>'
        html += '<th style="border:1px solid #6b21a8;padding:12px;text-align:left;width:25%;">Solution / Benefit</th>'
        html += '</tr></thead><tbody>'
        
        for idx, pr in enumerate(results):
            bg_color = "#faf5ff" if idx % 2 == 0 else "#ffffff"
            
            # 타이틀 또는 Affected Function 표시
            title_display = pr.get("affected_function") or pr.get("title") or "-"
            if len(title_display) > 150:
                title_display = title_display[:147] + "..."
            
            # Issue/Description (키워드 하이라이트)
            issue = pr.get("issue_description") or "-"
            if len(issue) > 200:
                issue = issue[:197] + "..."
            if keyword:
                for kw in keyword.split():
                    issue = re.sub(f'({re.escape(kw)})', r'<mark style="background:#fef08a;">\1</mark>', issue, flags=re.IGNORECASE)
            
            # Solution/Benefit
            solution = pr.get("solution") or "-"
            if len(solution) > 200:
                solution = solution[:197] + "..."
            
            html += f'<tr style="background:{bg_color};">'
            html += f'<td style="border:1px solid #ddd;padding:10px;font-family:monospace;font-weight:bold;color:#7c3aed;"><a href="#" onclick="searchPR(\'{pr["pr_number"]}\');return false;" style="color:#7c3aed;text-decoration:underline;">{pr["pr_number"]}</a></td>'
            html += f'<td style="border:1px solid #ddd;padding:10px;font-family:monospace;">{pr.get("sw_version", "-")}</td>'
            html += f'<td style="border:1px solid #ddd;padding:10px;">{title_display}</td>'
            html += f'<td style="border:1px solid #ddd;padding:10px;color:#555;">{issue}</td>'
            html += f'<td style="border:1px solid #ddd;padding:10px;color:#065f46;">{solution}</td>'
            html += '</tr>'
        
        html += '</tbody></table>'
        html += '<p style="font-size:12px;color:#666;margin:5px 0;">💡 PR 번호를 클릭하면 상세 정보를 볼 수 있습니다. Click PR number for details.</p>'
        html += '<script>function searchPR(prNum){const input=document.getElementById("chat-input");if(input){input.value=prNum;const form=input.closest("form");if(form){form.dispatchEvent(new Event("submit"));}}}</script>'
        
        return html

    def find_similar_prs_fast(self, pr_title: str, pr_number: str = None, limit: int = 3) -> Dict:
        """PR 제목 기반 유사 PR 빠른 검색 - 타임아웃 방지용 간소화 버전
        
        find_similar_prs의 간소화 버전으로:
        - 검색 키워드 수 제한 (5개)
        - FTS5 검색 결과 제한 (15개)
        - 간소화된 점수 계산
        
        Args:
            pr_title: 검색할 PR 제목
            pr_number: 원본 PR 번호 (결과에서 제외)
            limit: 최대 결과 수
            
        Returns:
            검색 결과 딕셔너리
        """
        if not self.db_path.exists():
            return {"found": 0, "error": "Index not built"}
        
        # 제목에서 핵심 키워드 추출
        keywords = self._extract_keywords_from_title(pr_title)
        
        if not keywords:
            return {"found": 0, "original_title": pr_title, "similar_prs": [], "keywords": []}
        
        # 키워드 제한 (빠른 검색)
        combo_keywords = [k for k in keywords if ' ' in k][:2]  # 조합 2개
        single_keywords = [k for k in keywords if ' ' not in k][:3]  # 단일 3개
        search_keywords = combo_keywords + single_keywords
        
        # PR 후보 수집
        candidate_prs = {}
        
        for keyword in search_keywords:
            text_results = self.search_text(keyword, limit=15)  # 결과 제한
            
            for text_result in text_results:
                conn = sqlite3.connect(str(self.db_path))
                cursor = conn.cursor()
                
                cursor.execute("""
                    SELECT DISTINCT p.pr_number, f.sw_version, p.context
                    FROM pr_index p
                    JOIN pdf_files f ON p.file_id = f.id
                    WHERE f.filename = ? AND p.page_num = ?
                    LIMIT 5
                """, (text_result["filename"], text_result["page"]))
                
                for row in cursor.fetchall():
                    found_pr = row[0]
                    
                    if pr_number and found_pr == f"PR-{pr_number.replace('PR-', '')}":
                        continue
                    
                    if found_pr not in candidate_prs:
                        pr_detail = self.get_pr_detail(found_pr)
                        if pr_detail:
                            detail = pr_detail.get("detail", {})
                            candidate_prs[found_pr] = {
                                "pr_number": found_pr,
                                "sw_version": pr_detail.get("sw_version", ""),
                                "title": detail.get("title", ""),
                                "affected_function": detail.get("affected_function", ""),
                                "issue_description": detail.get("issue_description", detail.get("description", "")),
                                "solution": detail.get("solution", detail.get("benefits", "")),
                                "matched_keywords": [],
                                "relevance_score": 0
                            }
                
                conn.close()
                
                # 후보 10개 수집 후 중단
                if len(candidate_prs) >= 10:
                    break
            
            if len(candidate_prs) >= 10:
                break
        
        # 간소화된 점수 계산
        for pr_num, pr_info in candidate_prs.items():
            full_text = (pr_info.get("title", "") + " " + pr_info.get("issue_description", "")).lower()
            score = 0
            matched = []
            
            for kw in search_keywords:
                kw_lower = kw.lower()
                if kw_lower in full_text:
                    matched.append(kw)
                    score += 20 if ' ' in kw else 5  # 조합 20점, 단일 5점
            
            pr_info["matched_keywords"] = matched
            pr_info["relevance_score"] = score
        
        # 점수 기반 정렬 및 필터
        sorted_results = sorted(
            [p for p in candidate_prs.values() if p["relevance_score"] > 0],
            key=lambda x: x["relevance_score"],
            reverse=True
        )[:limit]
        
        final_results = [{
            "pr_number": p["pr_number"],
            "sw_version": p["sw_version"],
            "title": p["title"],
            "affected_function": p["affected_function"],
            "issue_description": p["issue_description"],
            "solution": p["solution"],
            "matched_keywords": p["matched_keywords"],
            "relevance_score": p["relevance_score"]
        } for p in sorted_results]
        
        return {
            "found": len(final_results),
            "original_title": pr_title,
            "keywords": search_keywords,
            "similar_prs": final_results
        }
    
    def find_similar_prs(self, pr_title: str, pr_number: str = None, limit: int = 5, 
                         use_hybrid: bool = True, strictness: int = 2) -> Dict:
        """PR 제목 기반 유사 PR 검색 - SWRN에서 비슷한 문제/해결책 찾기
        
        하이브리드 검색 우선 시도, 실패 시 기존 방식 폴백
        
        Args:
            pr_title: 검색할 PR 제목
            pr_number: 원본 PR 번호 (결과에서 제외)
            limit: 최대 결과 수
            use_hybrid: 하이브리드 검색 사용 여부 (기본 True)
            strictness: 필터링 엄격도 0-3 (기본 2)
            
        Returns:
            검색 결과 딕셔너리
        """
        # 하이브리드 검색 우선 시도
        if use_hybrid and HYBRID_SEARCH_AVAILABLE:
            try:
                result = self.find_similar_prs_hybrid(pr_title, pr_number, limit, strictness)
                if result.get("found", 0) > 0:
                    return result
                # 하이브리드 결과 없으면 strictness 낮춰서 재시도
                if strictness > 0:
                    result = self.find_similar_prs_hybrid(pr_title, pr_number, limit, strictness=0)
                    if result.get("found", 0) > 0:
                        return result
            except Exception as e:
                print(f"⚠️ 하이브리드 검색 실패, 기존 방식으로 폴백: {e}")
        
        # 기존 검색 로직 (폴백)
        return self._find_similar_prs_legacy(pr_title, pr_number, limit)
    
    def _find_similar_prs_legacy(self, pr_title: str, pr_number: str = None, limit: int = 5) -> Dict:
        """기존 방식 유사 PR 검색 (레거시)
        
        개선된 알고리즘:
        1. WHERE + WHAT 키워드 추출
        2. 각 키워드로 FTS5 검색
        3. 검색된 PR의 title/issue_description에서 키워드 매칭 검증
        4. 매칭 점수 기반 정렬 (조합 키워드 > 단일 키워드)
        """
        if not self.db_path.exists():
            return {"found": 0, "error": "Index not built"}
        
        # 제목에서 핵심 키워드 추출
        keywords = self._extract_keywords_from_title(pr_title)
        
        if not keywords:
            return {"found": 0, "original_title": pr_title, "similar_prs": [], "keywords": []}
        
        # 키워드를 조합 키워드와 단일 키워드로 분리
        combo_keywords = [k for k in keywords if ' ' in k]  # WHERE+WHAT 조합
        single_keywords = [k for k in keywords if ' ' not in k]  # 단일 키워드
        
        # PR 후보 수집 (PR 상세 정보와 함께)
        candidate_prs = {}  # pr_number -> {pr_info, matched_keywords, scores}
        
        # 검색할 키워드 목록 (조합 우선, 최대 7개)
        search_keywords = combo_keywords[:4] + single_keywords[:3]
        
        for keyword in search_keywords:
            text_results = self.search_text(keyword, limit=30)
            
            for text_result in text_results:
                conn = sqlite3.connect(str(self.db_path))
                cursor = conn.cursor()
                
                # 해당 페이지의 PR들 찾기
                cursor.execute("""
                    SELECT DISTINCT p.pr_number, f.sw_version, p.context
                    FROM pr_index p
                    JOIN pdf_files f ON p.file_id = f.id
                    WHERE f.filename = ? AND p.page_num = ?
                """, (text_result["filename"], text_result["page"]))
                
                for row in cursor.fetchall():
                    found_pr = row[0]
                    
                    # 원본 PR 제외
                    if pr_number and found_pr == f"PR-{pr_number.replace('PR-', '')}":
                        continue
                    
                    # 새 PR이면 상세 정보 가져오기
                    if found_pr not in candidate_prs:
                        pr_detail = self.get_pr_detail(found_pr)
                        if pr_detail:
                            detail = pr_detail.get("detail", {})
                            candidate_prs[found_pr] = {
                                "pr_number": found_pr,
                                "sw_version": pr_detail.get("sw_version", ""),
                                "title": detail.get("title", ""),
                                "affected_function": detail.get("affected_function", ""),
                                "issue_description": detail.get("issue_description", detail.get("description", "")),
                                "solution": detail.get("solution", detail.get("benefits", "")),
                                "matched_combo_keywords": set(),
                                "matched_single_keywords": set(),
                                "title_matches": set(),
                                "content_matches": set(),
                                "relevance_score": 0
                            }
                
                conn.close()
        
        # 각 PR 후보에 대해 실제 키워드 매칭 검증
        for pr_num, pr_info in candidate_prs.items():
            # 검색 대상 텍스트 준비 (제목 + 이슈설명)
            title_text = (pr_info.get("title", "") + " " + pr_info.get("affected_function", "")).lower()
            content_text = (pr_info.get("issue_description", "") + " " + pr_info.get("solution", "")).lower()
            full_text = title_text + " " + content_text
            
            total_score = 0
            exact_match_count = 0  # 완전 매칭 개수
            
            # 조합 키워드 매칭 검증 (높은 점수)
            for combo_kw in combo_keywords[:4]:
                combo_lower = combo_kw.lower()
                # 조합 전체가 매칭되면 높은 점수
                if combo_lower in full_text:
                    pr_info["matched_combo_keywords"].add(combo_kw)
                    exact_match_count += 1
                    if combo_lower in title_text:
                        pr_info["title_matches"].add(combo_kw)
                        total_score += 30  # 제목에서 조합 매칭 = 최고점
                    else:
                        pr_info["content_matches"].add(combo_kw)
                        total_score += 15  # 내용에서 조합 매칭
                else:
                    # 조합의 개별 단어 매칭 확인 - 낮은 점수
                    combo_parts = combo_kw.lower().split()
                    parts_matched = sum(1 for part in combo_parts if part in full_text)
                    if parts_matched >= len(combo_parts) * 0.6:  # 60% 이상 매칭 필요
                        pr_info["matched_combo_keywords"].add(f"{combo_kw}*")  # 부분 매칭 표시
                        # 부분 매칭은 낮은 점수 (완전 매칭의 1/3)
                        partial_score = parts_matched * 2
                        total_score += partial_score
            
            # 단일 키워드 매칭 검증
            for single_kw in single_keywords[:5]:
                single_lower = single_kw.lower()
                if single_lower in full_text:
                    pr_info["matched_single_keywords"].add(single_kw)
                    if single_lower in title_text:
                        pr_info["title_matches"].add(single_kw)
                        total_score += 8  # 제목에서 단일 키워드 매칭
                    else:
                        pr_info["content_matches"].add(single_kw)
                        total_score += 3  # 내용에서 단일 키워드 매칭
            
            # 완전 매칭이 있으면 보너스 점수
            if exact_match_count > 0:
                total_score += exact_match_count * 10
            
            pr_info["relevance_score"] = total_score
            pr_info["exact_match_count"] = exact_match_count
        
        # 점수가 있는 PR만 필터링하고 정렬
        scored_prs = [
            pr_info for pr_info in candidate_prs.values() 
            if pr_info["relevance_score"] > 0 and (
                pr_info["matched_combo_keywords"] or pr_info["matched_single_keywords"]
            )
        ]
        
        # 정렬: 완전 매칭 개수 > 점수 > 제목 매칭 개수
        sorted_results = sorted(
            scored_prs, 
            key=lambda x: (
                x.get("exact_match_count", 0),  # 완전 매칭 우선
                x["relevance_score"],            # 점수
                len(x.get("title_matches", set()))  # 제목 매칭 개수
            ), 
            reverse=True
        )[:limit]
        
        # 결과 포맷팅
        final_results = []
        for pr_info in sorted_results:
            # 매칭된 키워드 통합
            all_matched = list(pr_info["matched_combo_keywords"]) + list(pr_info["matched_single_keywords"])
            title_matched = list(pr_info["title_matches"])
            
            final_results.append({
                "pr_number": pr_info["pr_number"],
                "sw_version": pr_info["sw_version"],
                "title": pr_info["title"],
                "affected_function": pr_info["affected_function"],
                "issue_description": pr_info["issue_description"],
                "solution": pr_info["solution"],
                "matched_keywords": all_matched,
                "title_matched_keywords": title_matched,  # 제목에서 매칭된 키워드
                "relevance_score": pr_info["relevance_score"]
            })
        
        return {
            "found": len(final_results),
            "original_title": pr_title,
            "keywords": keywords[:7],
            "combo_keywords": combo_keywords[:4],
            "single_keywords": single_keywords[:3],
            "similar_prs": final_results
        }
    
    def find_similar_prs_hybrid(self, pr_title: str, pr_number: str = None, limit: int = 5,
                               strictness: int = 2) -> Dict:
        """하이브리드 방식 유사 PR 검색 - TF-IDF + 동의어 + FTS5 조합
        
        개선된 검색 파이프라인:
        1. 동의어 확장 (Synonym Expansion) - 검색 범위 확대
        2. FTS5 BM25 검색 (Sparse Retrieval) - 빠른 후보 추출
        3. TF-IDF 재랭킹 (Dense Reranking) - 정밀 유사도 계산
        4. 하이브리드 점수 계산 - α×BM25 + β×TF-IDF + γ×keyword
        
        성능: 400+ PDF 문서에서 50-100ms 이내
        
        Args:
            pr_title: 검색할 PR 제목
            pr_number: 원본 PR 번호 (결과에서 제외)
            limit: 최대 결과 수
            strictness: 필터링 엄격도 (0-3)
            
        Returns:
            검색 결과 딕셔너리 (하이브리드 점수 포함)
        """
        if not HYBRID_SEARCH_AVAILABLE:
            # 하이브리드 엔진 없으면 기존 방식 폴백
            return self._find_similar_prs_legacy(pr_title, pr_number, limit)
        
        # 하이브리드 검색 엔진 지연 초기화
        if self._hybrid_engine is None:
            self._hybrid_engine = HybridPRSearchEngine(
                db_path=self.db_path,
                swrn_indexer=self
            )
            self._hybrid_engine.initialize()
        
        # 하이브리드 검색 수행
        exclude_pr = f"PR-{pr_number.replace('PR-', '')}" if pr_number else None
        results = self._hybrid_engine.search_similar_prs(
            query=pr_title,
            exclude_pr=exclude_pr,
            limit=limit,
            strictness=strictness
        )
        
        # 결과 포맷 변환 (기존 find_similar_prs와 호환)
        # 배치로 기본 정보 조회 (sw_version, context, pr_type)
        similar_prs = results.get("similar_prs", [])
        
        # AND 매칭 PR을 우선 정렬 (is_and_match가 True인 것 먼저, 그 다음 hybrid_score 순)
        similar_prs.sort(key=lambda x: (-1 if x.get("is_and_match") else 0, -x.get("hybrid_score", 0)))
        
        # PR 번호 수집
        pr_nums = [pr.get("pr_number", "").replace("PR-", "") for pr in similar_prs if pr.get("pr_number")]
        
        # 배치로 기본 정보 조회 (pr_index + pdf_files JOIN)
        pr_info_map = {}
        if pr_nums and self.db_path.exists():
            try:
                import sqlite3
                conn = sqlite3.connect(str(self.db_path))
                cursor = conn.cursor()
                
                # pr_number 앞에 PR- 붙어있을 수도 있고 없을 수도 있음
                pr_nums_with_prefix = [f"PR-{pn}" if not pn.startswith("PR-") else pn for pn in pr_nums]
                placeholders = ','.join(['?' for _ in pr_nums_with_prefix])
                
                cursor.execute(f"""
                    SELECT p.pr_number, f.sw_version, p.context, p.pr_type
                    FROM pr_index p
                    JOIN pdf_files f ON p.file_id = f.id
                    WHERE p.pr_number IN ({placeholders})
                """, pr_nums_with_prefix)
                
                for row in cursor.fetchall():
                    pr_num_clean = row[0].replace("PR-", "")
                    pr_type = row[3] if len(row) > 3 else 'unknown'
                    pr_info_map[pr_num_clean] = {
                        "sw_version": row[1] or "",
                        "context": row[2] or "",
                        "pr_type": pr_type
                    }
                conn.close()
            except Exception as e:
                print(f"⚠️ PR 기본 정보 조회 오류: {e}")
        
        formatted_results = []
        for pr in similar_prs:
            pr_num = pr.get("pr_number", "").replace("PR-", "")
            
            # 기본 정보 보완
            info = pr_info_map.get(pr_num, {})
            sw_version = info.get("sw_version", pr.get("sw_version", ""))
            context = info.get("context", pr.get("context", ""))
            pr_type = info.get("pr_type", pr.get("pr_type", "unknown"))
            
            # 상세 정보 가져오기 (solution_or_benefit, issue_description 등 포함)
            solution_or_benefit = ""
            benefits = ""
            solution = ""
            affected_function = ""
            description = ""
            issue_description = ""
            try:
                pr_detail = self.get_pr_detail(pr_num)
                if pr_detail:
                    detail = pr_detail.get("detail", {})
                    solution_or_benefit = detail.get("solution_or_benefit", "")
                    benefits = detail.get("benefits", "")
                    solution = detail.get("solution", "")
                    affected_function = detail.get("affected_function", "")
                    description = detail.get("description", "")
                    issue_description = detail.get("issue_description", "")
                    # pr_type도 상세 정보에서 가져옴
                    if pr_type == 'unknown' and detail.get("pr_type"):
                        pr_type = detail.get("pr_type", pr_type)
            except Exception:
                pass
            
            # PR 유형 라벨 생성 (unknown도 표시하지만 UI에서 다르게 처리 가능)
            if pr_type == 'new_feature':
                pr_type_label = "New Feature"
            elif pr_type == 'issue_fix':
                pr_type_label = "Issue Fix"
            else:
                pr_type_label = ""  # unknown은 빈 문자열로 표시 (UI에서 숨길 수 있음)
            
            # Issue Description / Description 결정 (PR 타입에 따라)
            # New Feature: description 사용
            # Issue Fix: issue_description 사용
            if pr_type == 'new_feature':
                issue_desc = description if description else issue_description
            else:
                issue_desc = issue_description if issue_description else description
            
            # 여전히 없으면 context에서 추출
            if not issue_desc:
                issue_desc = context[:200] + "..." if len(context) > 200 else context
            
            # 매칭 키워드
            matched_kw = pr.get("matched_keywords", [])
            
            # Solution or Benefit 최종 결정 (이미 상세 정보에서 가져옴, 없으면 pr_type 기반 선택)
            if not solution_or_benefit:
                if pr_type == 'new_feature':
                    solution_or_benefit = benefits if benefits else solution
                else:
                    solution_or_benefit = solution if solution else benefits
            
            formatted_results.append({
                "pr_number": pr_num,
                "sw_version": sw_version,
                "title": pr.get("title", ""),
                "affected_function": affected_function,  # detail에서 가져온 값 사용
                "issue_description": issue_desc,  # issue_or_description 값
                "description": description,  # New Feature용 Description
                "issue_desc_raw": issue_description,  # Issue Fix용 Issue Description 원본
                "solution": solution,
                "benefits": benefits,
                "solution_or_benefit": solution_or_benefit,
                "matched_keywords": matched_kw,
                "relevance_score": int(pr.get("hybrid_score", 0) * 100),
                "hybrid_score": pr.get("hybrid_score", 0),
                "bm25_score": pr.get("bm25_norm", 0),
                "tfidf_score": pr.get("tfidf_score", 0),
                "pr_type": pr_type,
                "pr_type_label": pr_type_label,
                "is_and_match": pr.get("is_and_match", False)  # AND 매칭 여부
            })
        
        return {
            "found": len(formatted_results),
            "original_title": pr_title,
            "keywords": results.get("expanded_queries", [])[:7],
            "search_method": "hybrid",  # 하이브리드 검색 표시
            "similar_prs": formatted_results
        }
    
    def rebuild_hybrid_index(self) -> bool:
        """하이브리드 검색 인덱스 재구축 (TF-IDF 캐시 갱신)"""
        if not HYBRID_SEARCH_AVAILABLE:
            print("⚠️ 하이브리드 검색 모듈을 사용할 수 없습니다.")
            return False
        
        if self._hybrid_engine is None:
            self._hybrid_engine = HybridPRSearchEngine(
                db_path=self.db_path,
                swrn_indexer=self
            )
        
        return self._hybrid_engine.initialize(force_rebuild=True)
    
    def _extract_keywords_from_title(self, title: str) -> List[str]:
        """PR 제목/이슈에서 핵심 기술 키워드 추출 (반도체 장비 SW 도메인 특화)
        
        핵심 원칙: WHERE(어디에서) + WHAT(무엇을) 조합
        
        WHERE 패턴 (위치/컨텍스트):
        - 장비명: Kiyo GX, Sensei, Akara, Vantex, Producer, Centris 등
        - 페이지명: Recipe Page, Recipe Constant Page, Tempo Editor, Setup Page 등
        - 모듈명: custom IO, process data, Factory Automation 등
        - 시스템: UI session, alarm system, control module 등
        
        WHAT 패턴 (대상/동작):
        - 문제: termination, crash, error, mismatch, timeout 등
        - 대상: process time, Cancel button, SVID, parameter 등
        - 동작: Add, Remove, Update, stabilization 등
        
        예시:
        - "Actual process time is more progressed... in Kiyo GX" 
          → WHERE: Kiyo GX, WHAT: process time
        - "Add Cancel button in the Tempo Editor page of the recipe page"
          → WHERE: recipe page, Tempo Editor, WHAT: Cancel button
        """
        
        # ============================================================
        # WHERE 카테고리 - 위치/컨텍스트 (어디에서)
        # ============================================================
        
        # 장비/제품명 (복합어 - 우선 추출)
        equipment_patterns = [
            r'(?i)\b(Kiyo\s*(?:G?X|45|CX)?)\b',  # Kiyo GX, Kiyo CX, Kiyo45
            r'(?i)\b(Sensei)\b',
            r'(?i)\b(Akara)\b',
            r'(?i)\b(Vantex)\b',
            r'(?i)\b(Producer\s*(?:GT|SE|XP)?)\b',  # Producer GT, Producer SE
            r'(?i)\b(Centris\s*(?:Sym3|Tera)?)\b',  # Centris Sym3
            r'(?i)\b(Versys\s*(?:Metal|Kyo)?)\b',
            r'(?i)\b(Flex\s*(?:D|E|F)?)\b',
            r'(?i)\b(Vector\s*(?:ICP|Extreme)?)\b',
            r'(?i)\b(Coronus\s*(?:DX|HP)?)\b',
        ]
        
        # 페이지/화면명 (복합어)
        page_patterns = [
            r'(?i)\b(Recipe\s+(?:Constant\s+)?Page)\b',
            r'(?i)\b(Tempo\s+Editor(?:\s+page)?)\b',
            r'(?i)\b(Setup\s+(?:Page|Screen|Dialog))\b',
            r'(?i)\b(Maintenance\s+(?:Page|Screen|Mode))\b',
            r'(?i)\b(Process\s+(?:Page|Monitor|Data|Summary))\b',
            r'(?i)\b(Alarm\s+(?:Page|List|Log|History))\b',
            r'(?i)\b(Config(?:uration)?\s+(?:Page|Screen|Dialog))\b',
            r'(?i)\b(Status\s+(?:Page|Bar|Panel))\b',
        ]
        
        # 모듈/시스템명 (복합어)
        module_patterns = [
            r'(?i)\b(custom\s+IO)\b',
            r'(?i)\b(Factory\s+Automation)\b',
            r'(?i)\b(process\s+data(?:\s+summ(?:ary)?)?)\b',
            r'(?i)\b(UI\s+session)\b',
            r'(?i)\b(control\s+(?:module|system))\b',
            r'(?i)\b(alarm\s+(?:system|module))\b',
            r'(?i)\b(recipe\s+(?:editor|manager))\b',
            r'(?i)\b(wafer\s+(?:handler|transfer))\b',
            r'(?i)\b(gas\s+(?:panel|system|box))\b',
            r'(?i)\b(RF\s+(?:generator|matcher|system))\b',
        ]
        
        # 단일 장소 키워드
        where_single = {
            'chamber', 'slot', 'loadport', 'aligner', 'foup', 'cassette',
            'plc', 'controller', 'host', 'server', 'client',
            'terminal', 'console', 'editor', 'viewer', 'dialog'
        }
        
        # ============================================================
        # WHAT 카테고리 - 대상/동작 (무엇을)
        # ============================================================
        
        # 기술 대상 (복합어)
        target_patterns = [
            r'(?i)\b(process\s+(?:time|parameter|data))\b',
            r'(?i)\b(setpoint\s+time)\b',
            r'(?i)\b(stabilization\s+time)\b',
            r'(?i)\b(Cancel\s+button)\b',
            r'(?i)\b(OK\s+button)\b',
            r'(?i)\b(SVID\s*[\"\']?[\w]+[\"\']?)\b',  # SVID "name" 또는 SVID name
            r'(?i)\b(new\s+SVID)\b',
            r'(?i)\b(recipe\s+(?:step|constant|parameter))\b',
            r'(?i)\b(CV\s+(?:value|parameter|variable))\b',
            r'(?i)\b(alarm\s+(?:ID|code|message))\b',
            r'(?i)\b(error\s+(?:code|message|log))\b',
            r'(?i)\b(wear\s+compensation)\b',
            r'(?i)\b(RF\s+(?:power|bias|match))\b',
            r'(?i)\b(gas\s+(?:flow|pressure))\b',
            r'(?i)\b(temperature\s+(?:value|setpoint|control))\b',
            r'(?i)\b(pressure\s+(?:value|setpoint|control))\b',
        ]
        
        # 동작/문제 (복합어)
        action_patterns = [
            r'(?i)\b(sudden\s+termination)\b',
            r'(?i)\b((?:UI|session)\s+termination)\b',
            r'(?i)\b(Add\s+(?:\w+\s+)?(?:button|SVID|parameter|field))\b',
            r'(?i)\b(Remove\s+(?:\w+\s+)?(?:button|SVID|parameter|field))\b',
            r'(?i)\b(parameter\s+(?:stabilization|validation|check))\b',
            r'(?i)\b((?:time(?:out)?|value)\s+mismatch)\b',
            r'(?i)\b((?:connection|communication)\s+(?:lost|error|fail))\b',
        ]
        
        # 증상/에러 키워드
        symptoms = {
            'termination', 'crash', 'hang', 'freeze', 'frozen', 'stuck',
            'error', 'fail', 'failure', 'fault', 'timeout', 'mismatch',
            'overflow', 'underflow', 'interlock', 'alarm', 'warning',
            'disconnect', 'lost', 'missing', 'corrupt', 'invalid',
            'uhe', 'exception', 'grayout', 'lockup', 'spike', 'shift'
        }
        
        # 동작 키워드 (Action words - WHAT에서 중요)
        actions = {
            'add', 'remove', 'update', 'modify', 'change', 'create', 'delete',
            'enable', 'disable', 'display', 'show', 'hide', 'request'
        }
        
        # 대상 키워드 (단일)
        targets = {
            'button', 'svid', 'ceid', 'dcid', 'vid', 'parameter', 'variable',
            'time', 'value', 'step', 'recipe', 'alarm', 'page', 'screen',
            'module', 'component', 'function', 'feature', 'option', 'field'
        }
        
        # ============================================================
        # 불용어 (제외)
        # ============================================================
        stopwords = {
            'the', 'a', 'an', 'is', 'are', 'was', 'were', 'be', 'been', 'being',
            'have', 'has', 'had', 'do', 'does', 'did', 'will', 'would', 'could',
            'should', 'may', 'might', 'must', 'shall', 'can', 'for', 'of', 'to',
            'in', 'on', 'at', 'by', 'with', 'from', 'as', 'into', 'through',
            'during', 'before', 'after', 'above', 'below', 'between', 'under',
            'over', 'up', 'down', 'about', 'this', 'that', 'these', 'those',
            'it', 'its', 'and', 'or', 'but', 'if', 'then', 'else', 'when',
            'where', 'which', 'who', 'what', 'how', 'why', 'not', 'no', 'yes',
            'all', 'any', 'some', 'every', 'each', 'few', 'more', 'most',
            'other', 'another', 'such', 'same', 'so', 'than', 'too', 'very',
            'just', 'only', 'also', 'even', 'still', 'already', 'yet', 'now',
            'here', 'there', 'pr', 'bug', 'fix', 'fixed', 'issue', 'problem',
            'both', 'particular', 'actual', 'into', 'request'
        }
        
        # ============================================================
        # 키워드 추출 로직
        # ============================================================
        
        found_where = []  # WHERE 키워드 (위치/컨텍스트)
        found_what = []   # WHAT 키워드 (대상/동작)
        seen = set()
        
        # 1. 복합 WHERE 패턴 추출 (장비명, 페이지명, 모듈명)
        for pattern in equipment_patterns + page_patterns + module_patterns:
            matches = re.findall(pattern, title)
            for m in matches:
                match_clean = re.sub(r'\s+', ' ', m.strip())
                if match_clean.lower() not in seen:
                    found_where.append(match_clean)
                    seen.add(match_clean.lower())
        
        # 2. 복합 WHAT 패턴 추출 (대상, 동작)
        for pattern in target_patterns + action_patterns:
            matches = re.findall(pattern, title)
            for m in matches:
                match_clean = re.sub(r'\s+', ' ', m.strip())
                if match_clean.lower() not in seen:
                    found_what.append(match_clean)
                    seen.add(match_clean.lower())
        
        # 3. 따옴표로 감싸진 식별자 추출 (SVID "TESRFWear...")
        quoted_ids = re.findall(r'["\']([A-Za-z][\w]+)["\']', title)
        for qid in quoted_ids:
            if qid.lower() not in seen and len(qid) > 3:
                found_what.append(qid)
                seen.add(qid.lower())
        
        # 4. 대문자 약어/제품코드 추출 (N120269, RF, SVID 등)
        # 숫자+문자 코드 (N120269, PR123456 등)
        codes = re.findall(r'\b([A-Z]\d{5,})\b', title)
        for code in codes:
            if code.lower() not in seen:
                found_where.append(code)
                seen.add(code.lower())
        
        # 대문자 약어
        abbreviations = re.findall(r'\b([A-Z]{2,6})\b', title)
        for abbr in abbreviations:
            abbr_lower = abbr.lower()
            if abbr_lower not in seen and abbr_lower not in stopwords:
                # SVID, CEID 등은 WHAT, 그 외 (RF, UI, IO)는 일단 보류
                if abbr_lower in {'svid', 'ceid', 'dcid', 'vid'}:
                    found_what.append(abbr)
                elif abbr_lower in {'rf', 'io', 'ui', 'cv', 'pm', 'fa'}:
                    found_where.append(abbr)
                else:
                    found_where.append(abbr)  # 기타 약어는 WHERE로 가정
                seen.add(abbr_lower)
        
        # 5. 단일 키워드 분류
        all_words = re.findall(r'\b([A-Za-z]{3,})\b', title)
        
        for word in all_words:
            word_lower = word.lower()
            if word_lower in seen or word_lower in stopwords:
                continue
            
            # 증상/에러 → WHAT
            if word_lower in symptoms:
                found_what.append(word)
                seen.add(word_lower)
            # 동작 → WHAT
            elif word_lower in actions:
                found_what.append(word)
                seen.add(word_lower)
            # 대상 → WHAT  
            elif word_lower in targets:
                found_what.append(word)
                seen.add(word_lower)
            # 장소 → WHERE
            elif word_lower in where_single:
                found_where.append(word)
                seen.add(word_lower)
        
        # 6. CamelCase 분리된 기술용어 추출 (TESRFWearCompansationFactorSlope)
        camel_matches = re.findall(r'\b([A-Z][a-z]+(?:[A-Z][a-z]+)+)\b', title)
        for cm in camel_matches:
            if cm.lower() not in seen:
                found_what.append(cm)
                seen.add(cm.lower())
        
        # ============================================================
        # 최종 키워드 조합 생성 
        # 핵심 원칙: WHERE + WHAT 조합이 검색의 핵심 (가장 앞에 배치)
        # 순서: 1) WHERE+WHAT 조합 → 2) WHAT 단독 → 3) WHERE 단독 (신뢰도 낮음)
        # ============================================================
        
        final_keywords = []
        combo_seen = set()
        
        # 1. WHERE + WHAT 조합 생성 (최우선 - 검색의 핵심!)
        # 예: "Kiyo GX process time", "Sensei sudden termination", "process data new SVID"
        if found_where and found_what:
            # 첫 번째 WHERE + 첫 번째 WHAT 조합 (가장 중요한 조합)
            primary_combo = f"{found_where[0]} {found_what[0]}"
            final_keywords.append(primary_combo)
            combo_seen.add(primary_combo.lower())
            
            # 추가 조합 (최대 2개 더)
            for where in found_where[:2]:
                for what in found_what[:3]:
                    combo = f"{where} {what}"
                    if combo.lower() not in combo_seen:
                        final_keywords.append(combo)
                        combo_seen.add(combo.lower())
                    if len(final_keywords) >= 3:
                        break
                if len(final_keywords) >= 3:
                    break
        
        # 2. WHAT 복합어 추가 (문제/대상 - 중요도 높음)
        # 예: "process time", "sudden termination", "new SVID"
        for what in found_what:
            if ' ' in what and what.lower() not in combo_seen:  # 복합어 우선
                final_keywords.append(what)
                combo_seen.add(what.lower())
                if len(final_keywords) >= 5:
                    break
        
        # 3. WHAT 단일 키워드 (신뢰도 중간)
        for what in found_what:
            if ' ' not in what and what.lower() not in combo_seen:
                final_keywords.append(what)
                combo_seen.add(what.lower())
                if len(final_keywords) >= 7:
                    break
        
        # 4. WHERE 단독은 마지막에 (신뢰도 낮음 - 범위가 너무 넓음)
        # 예: "Kiyo GX" 단독으로 검색하면 너무 많은 결과
        for where in found_where:
            if where.lower() not in combo_seen:
                final_keywords.append(where)
                combo_seen.add(where.lower())
                if len(final_keywords) >= 10:
                    break
        
        # 5. 키워드가 너무 적으면 일반 단어에서 추가 (4글자 이상)
        if len(final_keywords) < 3:
            for word in all_words:
                word_lower = word.lower()
                if word_lower not in combo_seen and word_lower not in stopwords and len(word) >= 4:
                    final_keywords.append(word)
                    combo_seen.add(word_lower)
                    if len(final_keywords) >= 5:
                        break
        
        return final_keywords[:10]  # 최대 10개 키워드
    
    def find_insights_for_open_prs(self, open_prs: List[Dict], limit_per_pr: int = 3) -> List[Dict]:
        """여러 Open PR에 대해 SWRN에서 인사이트 일괄 검색
        
        Args:
            open_prs: PR 리스트 [{"pr_number": "PR-123456", "title": "...", "days_open": 30}, ...]
            limit_per_pr: PR당 최대 유사 PR 개수
            
        Returns:
            인사이트 리스트
        """
        insights = []
        max_prs_to_process = 5  # 타임아웃 방지를 위해 최대 5개만 처리
        processed = 0
        
        for pr in open_prs:
            if processed >= max_prs_to_process:
                break
            
            pr_number = pr.get("pr_number", "")
            title = pr.get("title", "")
            days_open = pr.get("days_open", 0)
            
            if not title or len(title) < 10:  # 너무 짧은 제목 스킵
                continue
            
            # 유사 PR 검색 (빠른 검색 모드)
            similar_result = self.find_similar_prs_fast(title, pr_number, limit=limit_per_pr)
            
            processed += 1
            
            if similar_result.get("found", 0) > 0:
                insights.append({
                    "open_pr": {
                        "pr_number": pr_number,
                        "title": title,
                        "days_open": days_open,
                        "status": pr.get("status", "")
                    },
                    "keywords": similar_result.get("keywords", []),
                    "similar_prs": similar_result.get("similar_prs", []),
                    "insight_summary": self._generate_insight_summary(pr, similar_result.get("similar_prs", []))
                })
        
        return insights
    
    def _generate_insight_summary(self, open_pr: Dict, similar_prs: List[Dict]) -> str:
        """유사 PR 기반 인사이트 요약 생성"""
        if not similar_prs:
            return "유사한 해결 사례를 찾지 못했습니다."
        
        # 해결책이 있는 PR 확인
        solutions = [p for p in similar_prs if p.get("solution")]
        
        if solutions:
            return f"SWRN에서 {len(similar_prs)}개의 유사 PR 발견. {len(solutions)}개에서 해결책 확인 가능."
        else:
            return f"SWRN에서 {len(similar_prs)}개의 유사 PR 발견. 상세 내용 확인 필요."

    def get_stats(self) -> Dict:
        """인덱스 통계"""
        if not self.db_path.exists():
            return {"indexed": False}
        
        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()
        
        cursor.execute("SELECT COUNT(*) FROM pdf_files")
        file_count = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM pr_index")
        pr_count = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(DISTINCT pr_number) FROM pr_index")
        unique_prs = cursor.fetchone()[0]
        
        cursor.execute("SELECT SUM(page_count) FROM pdf_files")
        total_pages = cursor.fetchone()[0] or 0
        
        conn.close()
        
        return {
            "indexed": True,
            "file_count": file_count,
            "total_pages": total_pages,
            "pr_entries": pr_count,
            "unique_prs": unique_prs,
            "db_size_mb": self.db_path.stat().st_size / 1024 / 1024
        }
    
    def format_pr_result(self, pr_number: str) -> str:
        """PR 검색 결과를 HTML 포맷으로 반환"""
        result = self.get_pr_detail(pr_number)
        
        if not result:
            return f"📋 <b>{pr_number}</b>는 SWRN에서 찾을 수 없습니다."
        
        html = f"""📋 <b>{result['pr_number']}</b> Release Notes 정보:<br><br>
<b>SW Version:</b> {result['sw_version']}<br>
<b>Source:</b> {result['filename']}<br>
<b>Page:</b> {result['page']}<br>"""
        
        if "detail" in result and result["detail"]:
            d = result["detail"]
            
            if d.get("title"):
                html += f"<br><b>📌 Title:</b> {d['title']}<br>"
            if d.get("component"):
                html += f"<b>🔧 Component:</b> {d['component']}<br>"
            if d.get("module"):
                html += f"<b>📦 Module:</b> {d['module']}<br>"
            if d.get("affected_function"):
                html += f"<b>⚙️ Affected Function:</b> {d['affected_function']}<br>"
            if d.get("history"):
                html += f"<br><b>📜 History:</b><br><div style='margin-left:10px;color:#555;'>{d['history']}</div><br>"
            if d.get("benefits"):
                html += f"<b>✅ Benefits:</b><br><div style='margin-left:10px;color:#555;'>{d['benefits']}</div><br>"
            if d.get("description"):
                html += f"<b>📝 Description:</b><br><div style='margin-left:10px;color:#555;'>{d['description']}</div>"
            
            # Problem Report 섹션 필드
            if d.get("issue_description"):
                html += f"<br><br><b>🔴 Issue Description:</b><br><div style='margin-left:10px;color:#c00;'>{d['issue_description']}</div>"
            if d.get("root_cause"):
                html += f"<br><b>🔍 Root Cause:</b><br><div style='margin-left:10px;color:#555;'>{d['root_cause']}</div>"
            if d.get("solution"):
                html += f"<br><b>💡 Solution:</b><br><div style='margin-left:10px;color:#060;'>{d['solution']}</div>"
            
            if d.get("cv_changes"):
                # CV Changes 테이블
                html += f"<br><br><b>🔄 CV (Configurable Variable) Changes:</b><br>{d['cv_changes']}"
            if d.get("factory_automation_changes"):
                # Factory Automation Changes 테이블
                html += f"<br><br><b>🏭 Factory Automation Changes:</b><br>{d['factory_automation_changes']}"
            if d.get("recipe_parameter_changes"):
                # Recipe Parameter Changes 테이블
                html += f"<br><br><b>📋 Recipe Parameter Changes:</b><br>{d['recipe_parameter_changes']}"
            if d.get("ui_changes"):
                # UI Changes 테이블
                html += f"<br><br><b>🖥️ UI Changes:</b><br>{d['ui_changes']}"
            if d.get("alarm_changes"):
                # Alarm Changes 테이블
                html += f"<br><br><b>🚨 Alarm Changes:</b><br>{d['alarm_changes']}"
        
        # 다른 버전에서도 발견된 경우
        all_results = self.search_pr(pr_number)
        if len(all_results) > 1:
            versions = [r['sw_version'].replace('_ReleaseNotes', '') for r in all_results[:5]]
            html += f"<br><br>💡 이 PR은 <b>{len(all_results)}개 버전</b>에서 발견됨: {', '.join(versions)}"
            if len(all_results) > 5:
                html += f" 외 {len(all_results) - 5}개"
        
        return html


# 싱글톤 인스턴스
_indexer_instance = None

def get_swrn_indexer() -> SWRNIndexer:
    """SWRN Indexer 싱글톤 인스턴스"""
    global _indexer_instance
    if _indexer_instance is None:
        _indexer_instance = SWRNIndexer()
    return _indexer_instance


# CLI
if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="SWRN PDF Indexer")
    parser.add_argument("--build", action="store_true", help="Build full index")
    parser.add_argument("--rebuild", action="store_true", help="Force rebuild index")
    parser.add_argument("--update", action="store_true", help="Update index (new files only)")
    parser.add_argument("--search", type=str, help="Search for PR number")
    parser.add_argument("--text", type=str, help="Full-text search")
    parser.add_argument("--stats", action="store_true", help="Show index statistics")
    parser.add_argument("--folder", type=str, help="SWRN folder path")
    
    args = parser.parse_args()
    
    indexer = SWRNIndexer(swrn_folder=args.folder) if args.folder else get_swrn_indexer()
    
    if args.build or args.rebuild:
        indexer.build_index(force_rebuild=args.rebuild)
    
    elif args.update:
        indexer.build_index(force_rebuild=False)
    
    elif args.search:
        print(f"\n🔍 Searching for: {args.search}")
        print("-" * 40)
        result = indexer.format_pr_result(args.search)
        # HTML 태그 제거하여 콘솔 출력
        import html
        clean = re.sub(r'<[^>]+>', '', result)
        clean = html.unescape(clean)
        print(clean)
    
    elif args.text:
        print(f"\n🔍 Full-text search: {args.text}")
        print("-" * 40)
        results = indexer.search_text(args.text)
        for r in results:
            print(f"📄 {r['filename']} (p.{r['page']})")
            print(f"   {r['snippet']}\n")
    
    elif args.stats:
        stats = indexer.get_stats()
        print("\n📊 Index Statistics")
        print("-" * 40)
        if stats["indexed"]:
            print(f"📁 Files: {stats['file_count']}")
            print(f"📑 Pages: {stats['total_pages']:,}")
            print(f"🔢 PR entries: {stats['pr_entries']:,}")
            print(f"🆔 Unique PRs: {stats['unique_prs']:,}")
            print(f"💾 DB size: {stats['db_size_mb']:.1f} MB")
        else:
            print("❌ Index not built yet. Run with --build first.")
    
    else:
        parser.print_help()
