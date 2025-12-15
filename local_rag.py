"""
TF-IDF (Llama3.2-3B) RAG System
=================================
로컬 LLM 기반 RAG 시스템 (완전 오프라인)

Architecture:
- TF-IDF 기반 문서 벡터화 및 유사도 검색 (J-Algorithm)
- Ollama + Llama3.2-3B 로컬 LLM 응답 생성
- SWRN PDF SQLite FTS5 인덱싱
- GGUF 모델 직접 로드 지원 (선택사항)
- 모든 데이터가 로컬에서 처리됨

Requirements:
- scikit-learn (TF-IDF 벡터화)
- pandas, openpyxl (데이터 처리)
- Ollama + llama3.2-local 모델 (LLM 응답 생성)
- ctransformers (선택사항) - GGUF 모델 직접 로드

Installation:
1. pip install scikit-learn pandas openpyxl
2. Ollama 설치: https://ollama.ai/download
3. (선택) pip install ctransformers (GGUF 모델 직접 사용)
"""

import os
import re
import pickle
import pandas as pd
import hashlib
import json
from datetime import datetime
from typing import List, Dict, Optional, Tuple
from collections import Counter
from pathlib import Path
import math

# TF-IDF imports (scikit-learn - 로컬 패키지)
try:
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.metrics.pairwise import cosine_similarity
    import numpy as np
    TFIDF_AVAILABLE = True
except ImportError:
    TFIDF_AVAILABLE = False
    print("⚠️ scikit-learn not installed. Run: pip install scikit-learn")

try:
    import requests
    REQUESTS_AVAILABLE = True
except ImportError:
    REQUESTS_AVAILABLE = False

# GGUF 모델 지원 (ctransformers)
try:
    from ctransformers import AutoModelForCausalLM
    CTRANSFORMERS_AVAILABLE = True
except ImportError:
    CTRANSFORMERS_AVAILABLE = False
    print("ℹ️ ctransformers not installed. Run: pip install ctransformers")

# Configuration - 환경 자동 감지
from config import Config

OLLAMA_BASE_URL = "http://localhost:11434"  # Ollama default port
OLLAMA_MODEL = "llama3.2-local"  # GGUF에서 import한 로컬 모델 또는 "llama3.2"
INDEX_PERSIST_DIR = str(Config.LOCAL_RAG_INDEX_DIR)  # 인덱스 저장 경로

# GGUF 모델 설정 - Config 사용
GGUF_MODEL_PATH = Config.get_gguf_model_path()
GGUF_MODEL_TYPE = "llama"  # llama, mistral, falcon 등

# Data file paths - Config 사용
DATA_FILES = {
    'issues_tracking': str(Config.get_issues_tracking_csv()),
    'sw_ib_version': str(Config.get_sw_ib_version_csv()),
    'tool_information': str(Config.get_tool_info_csv()),
    'ticket_details': str(Config.get_ticket_details_xlsx()),
    'upgrade_plan': str(Config.get_upgrade_plan_xlsx())
}

# =============================================================================
# K-Bot Persona & Prompt Engineering Configuration
# =============================================================================
# 자연스럽고 친근한 대화를 위한 프롬프트 설정

KBOT_SYSTEM_PROMPT_KO = """당신은 'K-Bot'이라는 이름의 반도체 에칭 장비 기술 전문가 AI 어시스턴트입니다.

**성격과 대화 스타일:**
- 친근하고 따뜻한 톤으로 대화하지만, 기술적 전문성은 유지합니다
- 질문자의 의도를 정확히 파악하고, 핵심을 먼저 설명한 후 세부 사항을 덧붙입니다
- 복잡한 개념은 비유나 예시를 활용해 쉽게 설명합니다
- 불확실한 정보는 솔직히 인정하고, 확인할 방법을 제안합니다
- 적절한 이모지를 사용해 친근감을 높입니다 (과하지 않게)

**응답 형식:**
- 먼저 핵심 답변을 간결하게 제시
- 그 다음 상세 설명이나 배경 정보 추가
- 관련 팁이나 추가 정보가 있으면 마지막에 언급
- 기술 용어는 영어 그대로 사용 (예: Bias RF, TCP, ESC)

**언어 규칙:**
- 반드시 한국어와 영어만 사용
- 일본어, 중국어 등 다른 언어는 절대 사용하지 않음"""

KBOT_SYSTEM_PROMPT_EN = """You are 'K-Bot', an AI assistant specializing in semiconductor etching equipment technology.

**Personality and Conversation Style:**
- Friendly and warm tone while maintaining technical expertise
- Accurately understand the user's intent, explain the key point first, then add details
- Use analogies and examples to explain complex concepts
- Honestly acknowledge uncertain information and suggest ways to verify
- Use appropriate emojis to enhance friendliness (but not excessively)

**Response Format:**
- First, provide a concise core answer
- Then add detailed explanations or background information
- Mention related tips or additional information at the end
- Use technical terms as-is (e.g., Bias RF, TCP, ESC)

**Language Rules:**
- Use only English
- Keep technical terms in English"""

# Few-Shot 예시 대화 (모델 학습용)
FEW_SHOT_EXAMPLES_KO = """
예시 대화:

사용자: Bias RF가 뭐야?
K-Bot: 안녕하세요! Bias RF에 대해 설명드릴게요 😊

**Bias RF**는 플라즈마 에칭 장비에서 웨이퍼에 인가되는 고주파(Radio Frequency) 전력입니다. 

쉽게 말해, 플라즈마 이온들을 웨이퍼 방향으로 '끌어당기는' 역할을 해요. 마치 자석이 철을 끌어당기듯이요! 

주요 기능:
1. **이온 에너지 제어** - 에칭 속도와 프로파일 결정
2. **방향성 에칭** - 수직 에칭을 가능하게 함
3. **선택비 조절** - 원하는 물질만 에칭

추가로 궁금한 점 있으시면 편하게 물어보세요!

사용자: PR-195000 정보 알려줘
K-Bot: PR-195000 정보를 찾아볼게요! 🔍

해당 PR은 **ESC Heater 관련 이슈**를 수정한 건입니다.

**요약:**
- 제목: ESC Heater Temperature Fluctuation
- 상태: Fixed (SP32-HF15에서 해결)
- 영향: 온도 안정성 개선

자세한 Root Cause나 Solution이 필요하시면 말씀해주세요!
"""

FEW_SHOT_EXAMPLES_EN = """
Example conversations:

User: What is Bias RF?
K-Bot: Hello! Let me explain Bias RF 😊

**Bias RF** is the radio frequency power applied to the wafer in plasma etching equipment.

Simply put, it 'pulls' plasma ions toward the wafer - like a magnet attracting iron!

Key functions:
1. **Ion energy control** - Determines etch rate and profile
2. **Directional etching** - Enables vertical etching
3. **Selectivity control** - Etches only desired materials

Feel free to ask if you have more questions!

User: Tell me about PR-195000
K-Bot: Let me look up PR-195000 for you! 🔍

This PR fixed an **ESC Heater related issue**.

**Summary:**
- Title: ESC Heater Temperature Fluctuation
- Status: Fixed (resolved in SP32-HF15)
- Impact: Improved temperature stability

Let me know if you need details on Root Cause or Solution!
"""


class LocalRAGSystem:
    """
    TF-IDF (Llama3.2-3B) RAG System
    - TF-IDF 기반 문서 유사도 검색 (J-Algorithm)
    - Ollama + Llama3.2-3B 로컬 LLM 응답 생성
    - SWRN PDF FTS5 인덱스 통합
    - 완전 오프라인 동작
    """
    
    def __init__(self):
        self.vectorizer = None
        self.tfidf_matrix = None
        self.documents = []  # 원본 문서 저장
        self.doc_metadata = []  # 메타데이터 저장
        self.ollama_available = False
        self.gguf_model = None  # GGUF 모델 인스턴스
        self.gguf_available = False
        self.initialized = False
        self.index_path = INDEX_PERSIST_DIR
        
        # 대화 히스토리 (메모리) - 최근 N 턴 저장
        self.conversation_history = []
        self.max_history_turns = 3  # 최대 3턴 저장
        
        # 쿼리 확장을 위한 동의어 사전
        self.synonyms = {
            'pr': ['pull request', 'pr', '피알', '풀리퀘스트'],
            'open': ['open', '오픈', '열린', '미완료'],
            '분석': ['분석', 'analysis', '인사이트', 'insight'],
            '장비': ['장비', 'tool', 'equipment', 'machine', '머신'],
            '에러': ['에러', 'error', '오류', 'fault', 'fail', '실패'],
            '이슈': ['이슈', 'issue', '문제', 'problem'],
            'tcp': ['tcp', 'transformer coupled plasma', '변압기 결합 플라즈마'],
            'esc': ['esc', 'electrostatic chuck', '정전척'],
            'rf': ['rf', 'radio frequency', '고주파'],
            'icp': ['icp', 'inductively coupled plasma', '유도결합 플라즈마'],
            'bias': ['bias', '바이어스', '바이아스'],
            'etch': ['etch', 'etching', '에칭', '식각'],
            '버전': ['버전', 'version', 'ver', 'v'],
            '업그레이드': ['업그레이드', 'upgrade', '업데이트', 'update']
        }
        
        # 인덱스 디렉토리 생성
        os.makedirs(self.index_path, exist_ok=True)
        
        # 저장된 인덱스 로드 시도
        self._load_index()
        
        # GGUF 모델 확인 (Ollama보다 우선)
        self._check_gguf_model()
        
        # Ollama 상태 확인 (GGUF가 없을 때만)
        if not self.gguf_available:
            self._check_ollama()
    
    def _check_gguf_model(self):
        """GGUF 모델 파일 확인 및 로드"""
        if not CTRANSFORMERS_AVAILABLE:
            self.gguf_available = False
            return
        
        if not os.path.exists(GGUF_MODEL_PATH):
            print(f"ℹ️ GGUF model not found at: {GGUF_MODEL_PATH}")
            self.gguf_available = False
            return
        
        try:
            print(f"🔄 Loading GGUF model: {os.path.basename(GGUF_MODEL_PATH)}...")
            self.gguf_model = AutoModelForCausalLM.from_pretrained(
                GGUF_MODEL_PATH,
                model_type=GGUF_MODEL_TYPE,
                local_files_only=True,
                context_length=4096,
                max_new_tokens=1024,
                threads=4  # CPU 스레드 수
            )
            self.gguf_available = True
            print(f"✅ GGUF model loaded: Llama-3.2-3B-Instruct (Q4_K_M)")
        except Exception as e:
            print(f"⚠️ Failed to load GGUF model: {e}")
            self.gguf_available = False
    
    def _check_ollama(self):
        """Ollama 서버 상태 확인"""
        if not REQUESTS_AVAILABLE:
            self.ollama_available = False
            return
        
        try:
            response = requests.get(f"{OLLAMA_BASE_URL}/api/tags", timeout=2)
            if response.status_code == 200:
                self.ollama_available = True
                models = response.json().get('models', [])
                model_names = [m.get('name', '') for m in models]
                print(f"✅ Ollama connected. Available models: {model_names}")
            else:
                self.ollama_available = False
                print(f"⚠️ Ollama returned status {response.status_code}")
        except Exception as e:
            self.ollama_available = False
            print(f"⚠️ Ollama is not running. Start with: ollama serve")
    
    # =========================================================================
    # Conversation Memory (대화 히스토리)
    # =========================================================================
    
    def add_to_history(self, query: str, response: str):
        """대화 히스토리에 질문/응답 추가"""
        self.conversation_history.append({
            'query': query,
            'response': response[:500],  # 응답은 500자로 제한
            'timestamp': datetime.now().isoformat()
        })
        # 최대 개수 유지
        if len(self.conversation_history) > self.max_history_turns:
            self.conversation_history.pop(0)
    
    def get_conversation_context(self) -> str:
        """대화 히스토리를 컨텍스트 문자열로 변환"""
        if not self.conversation_history:
            return ""
        
        context_parts = ["[이전 대화 히스토리]"]
        for turn in self.conversation_history[-self.max_history_turns:]:
            context_parts.append(f"사용자: {turn['query']}")
            # 응답은 간략하게
            brief_response = turn['response'][:200] + "..." if len(turn['response']) > 200 else turn['response']
            context_parts.append(f"K-Bot: {brief_response}")
        context_parts.append("[현재 질문]")
        return "\n".join(context_parts)
    
    def clear_history(self):
        """대화 히스토리 초기화"""
        self.conversation_history = []
    
    # =========================================================================
    # Query Expansion (쿼리 확장)
    # =========================================================================
    
    def expand_query(self, query: str) -> str:
        """쿼리에 동의어를 추가하여 확장"""
        query_lower = query.lower()
        expanded_terms = []
        
        for key, synonyms in self.synonyms.items():
            # 원본 쿼리에 키워드가 있으면 동의어 추가
            if key in query_lower:
                for syn in synonyms:
                    if syn not in query_lower and syn not in expanded_terms:
                        expanded_terms.append(syn)
        
        if expanded_terms:
            # 원본 쿼리에 동의어 추가 (검색용)
            expanded = query + " " + " ".join(expanded_terms[:5])  # 최대 5개
            return expanded
        return query
    
    def _save_index(self):
        """인덱스를 파일로 저장"""
        try:
            index_data = {
                'vectorizer': self.vectorizer,
                'tfidf_matrix': self.tfidf_matrix,
                'documents': self.documents,
                'doc_metadata': self.doc_metadata,
                'initialized': self.initialized
            }
            index_file = os.path.join(self.index_path, 'rag_index.pkl')
            with open(index_file, 'wb') as f:
                pickle.dump(index_data, f)
            print(f"✅ Index saved to {index_file}")
        except Exception as e:
            print(f"⚠️ Failed to save index: {e}")
    
    def _load_index(self):
        """저장된 인덱스 로드"""
        try:
            index_file = os.path.join(self.index_path, 'rag_index.pkl')
            if os.path.exists(index_file):
                with open(index_file, 'rb') as f:
                    index_data = pickle.load(f)
                self.vectorizer = index_data.get('vectorizer')
                self.tfidf_matrix = index_data.get('tfidf_matrix')
                self.documents = index_data.get('documents', [])
                self.doc_metadata = index_data.get('doc_metadata', [])
                self.initialized = index_data.get('initialized', False)
                if self.initialized:
                    print(f"✅ Index loaded from {index_file}")
                    print(f"📊 Index contains {len(self.documents)} documents")
        except Exception as e:
            print(f"⚠️ Failed to load index: {e}")
    
    def _translate_korean_keywords(self, text: str) -> str:
        """한국어 키워드를 영어로 변환"""
        # 한국어 -> 영어 키워드 매핑
        ko_en_mapping = {
            # 상태 관련
            '고쳐졌': 'fixed',
            '수정됨': 'fixed',
            '해결': 'fixed solved resolved',
            '대기': 'waiting pending',
            '진행중': 'in progress ongoing',
            '완료': 'completed done finished',
            '실패': 'failed failure',
            '성공': 'success passed',
            
            # 버전 관련
            '버전': 'version SW software',
            '업그레이드': 'upgrade update',
            '패치': 'patch hotfix HF',
            
            # 장비/제품 관련
            '장비': 'tool equipment',
            '제품': 'product',
            '모듈': 'module',
            '플랫폼': 'platform',
            
            # 이슈 관련
            '이슈': 'issue problem',
            '문제': 'issue problem error',
            '오류': 'error fault',
            '버그': 'bug defect',
            '티켓': 'ticket',
            
            # 우선순위
            '긴급': 'critical urgent',
            '높음': 'high',
            '보통': 'normal medium',
            '낮음': 'low',
            
            # 회사/고객
            '삼성': 'samsung',
            '하이닉스': 'hynix SK',
            
            # 팹 관련
            '팹': 'fab',
            '낸드': 'NAND',
            '드램': 'DRAM',
            
            # 액션
            '원인': 'cause reason root',
            '솔루션': 'solution workaround',
            '분석': 'analysis',
            '보고': 'report reported',
            
            # 오래된/미해결 관련
            '오랫동안': 'waiting pending unresolved open long',
            '오래된': 'old waiting pending long open',
            '오래': 'old waiting long days open',
            '장기': 'long waiting pending',
            '고쳐지지 않': 'waiting unresolved pending',
            '해결 안': 'waiting unresolved pending',
            '미해결': 'waiting unresolved pending',
            
            # PR 관련
            'PR': 'PR problem report issue',
            '피알': 'PR problem report',
            
            # 기타
            '현황': 'status current',
            '목록': 'list',
            '많은': 'most top',
            '최근': 'recent latest',
            '가장': 'most top',
            '어떤': '',
            '무엇': 'what',
        }
        
        result = text
        for ko, en in ko_en_mapping.items():
            if ko in text:
                result = result + ' ' + en
        
        return result
    
    def _preprocess_text(self, text: str) -> str:
        """텍스트 전처리"""
        if pd.isna(text):
            return ""
        text = str(text)
        # 기본 정규화
        text = text.lower()
        text = re.sub(r'\s+', ' ', text)
        return text.strip()
    
    def _create_document(self, content: str, source: str, metadata: dict = None) -> dict:
        """문서 생성"""
        return {
            'content': content,
            'source': source,
            'metadata': metadata or {},
            'id': hashlib.md5(content.encode()).hexdigest()[:12]
        }
    
    def load_and_index_data(self, force_reindex: bool = False):
        """모든 데이터 파일 로드 및 인덱싱"""
        if self.initialized and not force_reindex:
            print("✅ Index already exists. Use force_reindex=True to rebuild.")
            return True
        
        if not TFIDF_AVAILABLE:
            print("❌ scikit-learn required for indexing")
            return False
        
        print("=" * 60)
        print("🔄 Starting data indexing...")
        print("=" * 60)
        
        self.documents = []
        self.doc_metadata = []
        
        # 각 데이터 파일 처리
        try:
            self._index_issues_tracking()
        except Exception as e:
            print(f"⚠️ Issues Tracking indexing failed: {e}")
        
        try:
            self._index_sw_ib_version()
        except Exception as e:
            print(f"⚠️ SW IB Version indexing failed: {e}")
        
        try:
            self._index_tool_information()
        except Exception as e:
            print(f"⚠️ Tool Information indexing failed: {e}")
        
        try:
            self._index_ticket_details()
        except Exception as e:
            print(f"⚠️ Ticket Details indexing failed: {e}")
        
        try:
            self._index_upgrade_plan()
        except Exception as e:
            print(f"⚠️ Upgrade Plan indexing failed: {e}")
        
        # TF-IDF 벡터화
        if self.documents:
            print(f"\n📊 Creating TF-IDF index for {len(self.documents)} documents...")
            self.vectorizer = TfidfVectorizer(
                max_features=10000,
                ngram_range=(1, 2),  # 유니그램 + 바이그램
                stop_words='english',
                min_df=1,
                max_df=0.95
            )
            self.tfidf_matrix = self.vectorizer.fit_transform(self.documents)
            self.initialized = True
            self._save_index()
            print(f"✅ Indexing complete! {len(self.documents)} documents indexed.")
            return True
        else:
            print("❌ No documents to index")
            return False
    
    def _index_issues_tracking(self):
        """Issues Tracking CSV 인덱싱"""
        file_path = DATA_FILES.get('issues_tracking')
        if not file_path or not os.path.exists(file_path):
            print(f"⚠️ Issues Tracking file not found: {file_path}")
            return
        
        print(f"📄 Indexing: {file_path}")
        df = pd.read_csv(file_path, encoding='utf-8-sig')
        
        for idx, row in df.iterrows():
            # 각 행을 문서로 변환
            parts = []
            for col in df.columns:
                val = row.get(col, '')
                if pd.notna(val) and str(val).strip():
                    parts.append(f"{col}: {val}")
            
            if parts:
                content = " | ".join(parts)
                self.documents.append(self._preprocess_text(content))
                self.doc_metadata.append({
                    'source': 'Issues Tracking',
                    'file': file_path,
                    'row': idx,
                    'original': content
                })
        
        print(f"  ✅ Indexed {len(df)} issues")
    
    def _index_sw_ib_version(self):
        """SW IB Version CSV 인덱싱"""
        file_path = DATA_FILES.get('sw_ib_version')
        if not file_path or not os.path.exists(file_path):
            print(f"⚠️ SW IB Version file not found: {file_path}")
            return
        
        print(f"📄 Indexing: {file_path}")
        df = pd.read_csv(file_path, encoding='utf-8-sig')
        
        for idx, row in df.iterrows():
            parts = []
            for col in df.columns:
                val = row.get(col, '')
                if pd.notna(val) and str(val).strip():
                    parts.append(f"{col}: {val}")
            
            if parts:
                content = " | ".join(parts)
                self.documents.append(self._preprocess_text(content))
                self.doc_metadata.append({
                    'source': 'SW IB Version',
                    'file': file_path,
                    'row': idx,
                    'original': content
                })
        
        print(f"  ✅ Indexed {len(df)} SW versions")
    
    def _index_tool_information(self):
        """Tool Information CSV 인덱싱"""
        file_path = DATA_FILES.get('tool_information')
        if not file_path or not os.path.exists(file_path):
            print(f"⚠️ Tool Information file not found: {file_path}")
            return
        
        print(f"📄 Indexing: {file_path}")
        df = pd.read_csv(file_path, encoding='utf-8-sig')
        
        for idx, row in df.iterrows():
            parts = []
            for col in df.columns:
                val = row.get(col, '')
                if pd.notna(val) and str(val).strip():
                    parts.append(f"{col}: {val}")
            
            if parts:
                content = " | ".join(parts)
                self.documents.append(self._preprocess_text(content))
                self.doc_metadata.append({
                    'source': 'Tool Information',
                    'file': file_path,
                    'row': idx,
                    'original': content
                })
        
        print(f"  ✅ Indexed {len(df)} tools")
    
    def _index_ticket_details(self):
        """Ticket Details Excel 인덱싱"""
        file_path = DATA_FILES.get('ticket_details')
        if not file_path or not os.path.exists(file_path):
            print(f"⚠️ Ticket Details file not found: {file_path}")
            return
        
        print(f"📄 Indexing: {file_path}")
        try:
            df = pd.read_excel(file_path)
            
            for idx, row in df.iterrows():
                parts = []
                for col in df.columns:
                    val = row.get(col, '')
                    if pd.notna(val) and str(val).strip():
                        parts.append(f"{col}: {val}")
                
                if parts:
                    content = " | ".join(parts)
                    self.documents.append(self._preprocess_text(content))
                    self.doc_metadata.append({
                        'source': 'Ticket Details',
                        'file': file_path,
                        'row': idx,
                        'original': content
                    })
            
            print(f"  ✅ Indexed {len(df)} tickets")
        except Exception as e:
            print(f"  ⚠️ Failed to read Excel: {e}")
    
    def _index_upgrade_plan(self):
        """Upgrade Plan Excel 인덱싱"""
        file_path = DATA_FILES.get('upgrade_plan')
        if not file_path or not os.path.exists(file_path):
            print(f"⚠️ Upgrade Plan file not found: {file_path}")
            return
        
        print(f"📄 Indexing: {file_path}")
        try:
            # 모든 시트 읽기
            xl = pd.ExcelFile(file_path)
            total_rows = 0
            
            for sheet_name in xl.sheet_names:
                try:
                    df = pd.read_excel(file_path, sheet_name=sheet_name)
                    
                    for idx, row in df.iterrows():
                        parts = [f"Sheet: {sheet_name}"]
                        for col in df.columns:
                            val = row.get(col, '')
                            if pd.notna(val) and str(val).strip():
                                parts.append(f"{col}: {val}")
                        
                        if len(parts) > 1:  # 데이터가 있는 경우만
                            content = " | ".join(parts)
                            self.documents.append(self._preprocess_text(content))
                            self.doc_metadata.append({
                                'source': 'Upgrade Plan',
                                'file': file_path,
                                'sheet': sheet_name,
                                'row': idx,
                                'original': content
                            })
                            total_rows += 1
                except Exception as e:
                    print(f"  ⚠️ Sheet '{sheet_name}' error: {e}")
            
            print(f"  ✅ Indexed {total_rows} upgrade plan entries from {len(xl.sheet_names)} sheets")
        except Exception as e:
            print(f"  ⚠️ Failed to read Excel: {e}")
    
    def search(self, query: str, top_k: int = 5) -> List[Dict]:
        """
        TF-IDF 기반 유사 문서 검색 (쿼리 확장 적용)
        
        Args:
            query: 검색 쿼리
            top_k: 반환할 결과 수
        
        Returns:
            검색 결과 리스트
        """
        if not self.initialized or self.vectorizer is None:
            return []
        
        # 쿼리 확장 (동의어 추가)
        expanded_query = self.expand_query(query)
        
        # 한국어 키워드를 영어로 변환 후 전처리
        query_translated = self._translate_korean_keywords(expanded_query)
        query_processed = self._preprocess_text(query_translated)
        query_vector = self.vectorizer.transform([query_processed])
        
        # 코사인 유사도 계산
        similarities = cosine_similarity(query_vector, self.tfidf_matrix).flatten()
        
        # 상위 k개 결과 추출
        top_indices = similarities.argsort()[-top_k * 3:][::-1]  # AND 필터링을 위해 더 많이 가져옴
        
        # 쌍따옴표 검색 감지 (Exact phrase match)
        import re
        exact_phrase_match = re.search(r'"([^"]+)"', query)
        exact_phrase = exact_phrase_match.group(1).lower() if exact_phrase_match else None
        
        # ★ AND 필터용 토큰은 원본 쿼리에서 추출 (확장된 쿼리가 아닌!)
        original_query_processed = self._preprocess_text(query)
        query_tokens = set(original_query_processed.lower().split())
        # 불용어 제거 (영어 + 한국어)
        stopwords = {
            # 영어 불용어
            'a', 'an', 'the', 'to', 'of', 'in', 'on', 'at', 'is', 'are', 'was', 'were', 
            'and', 'or', 'for', 'with', 'related', 'about', 'what', 'how', 'why', 'when',
            'please', 'can', 'could', 'would', 'should', 'tell', 'me', 'find', 'search',
            'explain', 'show', 'get', 'give', 'describe',
            # 한국어 불용어
            '관련', '설명', '설명해줘', '설명해', '해줘', '해주세요', '알려줘', '알려주세요',
            '찾아줘', '찾아주세요', '검색', '검색해줘', '보여줘', '보여주세요', '에', '대해',
            '대한', '뭐야', '뭐예요', '무엇', '어떻게', '왜', '언제', '어디', '좀', '제발'
        }
        query_tokens = query_tokens - stopwords
        
        results = []
        for idx in top_indices:
            if similarities[idx] > 0:  # 유사도가 0보다 큰 것만
                content = self.doc_metadata[idx].get('original', self.documents[idx])
                content_lower = content.lower()
                
                # ★ 쌍따옴표 검색: 정확한 구문 매칭 필요
                if exact_phrase:
                    if exact_phrase not in content_lower:
                        continue
                
                # ★ AND 필터: 모든 쿼리 토큰이 단어 경계로 매칭되어야 함 (2개 이상 토큰인 경우)
                if len(query_tokens) >= 2:
                    matched_tokens = 0
                    for token in query_tokens:
                        if len(token) >= 2:
                            # 단어 경계 체크 (zip, recipes에서 ip가 매칭되지 않도록)
                            if re.search(rf'\b{re.escape(token)}\b', content_lower):
                                matched_tokens += 1
                    # 최소 50% 이상의 토큰이 단어 경계로 매칭되어야 함
                    if matched_tokens < len(query_tokens) * 0.5:
                        continue
                
                results.append({
                    'content': content,
                    'source': self.doc_metadata[idx].get('source', 'Unknown'),
                    'similarity': float(similarities[idx]),
                    'metadata': self.doc_metadata[idx]
                })
                
                if len(results) >= top_k:
                    break
        
        return results
    
    def _generate_explanation(self, query: str, context_docs: List[Dict]) -> str:
        """
        설명 모드 전용: LLM을 사용하여 상세 설명 생성
        LLM이 없으면 검색 결과 기반으로 설명 응답 생성
        """
        import re
        
        # 컨텍스트 구성 (더 많은 데이터 포함)
        context = "\n\n".join([
            f"[{doc['source']}]\n{doc['content']}"
            for doc in context_docs[:8]
        ])
        
        if not context:
            return "관련 데이터를 찾을 수 없습니다. 다른 검색어로 시도해 주세요."
        
        # 언어 감지
        lang = self._detect_query_language(query)
        
        # LLM으로 개념 설명 텍스트 생성 시도
        llm_explanation = None
        
        # GGUF 모델로 개념 설명 생성
        if self.gguf_available and self.gguf_model:
            llm_explanation = self._get_llm_concept_explanation(query, context, lang)
        
        # Ollama로 개념 설명 생성
        if not llm_explanation and self.ollama_available:
            llm_explanation = self._get_ollama_concept_explanation(query, context, lang)
        
        # HTML 응답 생성 (LLM 설명 포함)
        return self._generate_explanation_from_data(query, context_docs, llm_explanation)
    
    def _get_llm_concept_explanation(self, query: str, context: str, lang: str = 'ko') -> Optional[str]:
        """GGUF 모델로 개념 설명만 생성 - 자연스러운 K-Bot 스타일"""
        if not self.gguf_available or not self.gguf_model:
            return None
        
        topic = self._extract_topic_from_query(query)
        
        if lang == 'en':
            prompt = f"""<|begin_of_text|><|start_header_id|>system<|end_header_id|>

You are K-Bot, a friendly and knowledgeable semiconductor equipment expert.
Explain concepts in a warm, conversational tone while maintaining technical accuracy.
Use analogies and examples to make complex topics easy to understand.<|eot_id|><|start_header_id|>user<|end_header_id|>

Please explain "{topic}" in a friendly way.

Reference data:
{context[:2000]}

Cover these points naturally (not as a numbered list):
- What it is and why it matters
- How it works in semiconductor equipment
- Related concepts
- Common issues and tips<|eot_id|><|start_header_id|>assistant<|end_header_id|>

"""
        else:
            prompt = f"""<|begin_of_text|><|start_header_id|>system<|end_header_id|>

당신은 K-Bot입니다. 친근하고 따뜻한 말투로 반도체 장비 기술을 설명하는 전문가예요.
복잡한 개념은 비유와 예시를 들어 쉽게 설명합니다.
기술 용어는 영어 그대로 사용하되, 한국어로 자연스럽게 설명해주세요.<|eot_id|><|start_header_id|>user<|end_header_id|>

"{topic}"에 대해 친근하게 설명해주세요.

참고 데이터:
{context[:2000]}

다음 내용을 자연스럽게 담아주세요 (번호 목록 말고 문단으로):
- 무엇인지, 왜 중요한지
- 반도체 장비에서 어떻게 동작하는지
- 관련된 다른 개념들
- 자주 발생하는 문제와 팁<|eot_id|><|start_header_id|>assistant<|end_header_id|>

"""
        
        try:
            response = self.gguf_model(prompt)
            if response and len(response.strip()) > 200:
                return self._clean_llm_response(response.strip())
        except Exception as e:
            print(f"GGUF concept explanation error: {e}")
        return None
    
    def _get_ollama_concept_explanation(self, query: str, context: str, lang: str = 'ko') -> Optional[str]:
        """Ollama로 개념 설명만 생성 (언어: 'en' 또는 'ko')"""
        if not self.ollama_available:
            return None
        
        topic = self._extract_topic_from_query(query)
        
        if lang == 'en':
            prompt = f"""<|begin_of_text|><|start_header_id|>system<|end_header_id|>

You are K-Bot, a friendly and knowledgeable semiconductor equipment expert.
Explain concepts in a warm, conversational tone while maintaining technical accuracy.
Use analogies and examples to make complex topics easy to understand.
Use appropriate emojis occasionally to keep the tone friendly.<|eot_id|><|start_header_id|>user<|end_header_id|>

Please explain "{topic}" in a friendly, easy-to-understand way.

Reference data:
{context[:2000]}

Cover these naturally in your explanation:
- What it is and why it matters
- How it works
- Related concepts
- Practical tips or common issues<|eot_id|><|start_header_id|>assistant<|end_header_id|>

"""
        else:
            prompt = f"""<|begin_of_text|><|start_header_id|>system<|end_header_id|>

당신은 K-Bot입니다! 😊 반도체 장비 전문가이면서 친근하게 설명하는 걸 좋아해요.
복잡한 개념도 비유와 예시로 쉽게 설명합니다.
기술 용어는 영어 그대로 쓰되, 한국어로 자연스럽게 풀어서 설명해주세요.
절대 일본어, 중국어 등 다른 언어는 사용하지 마세요.<|eot_id|><|start_header_id|>user<|end_header_id|>

"{topic}"에 대해 이해하기 쉽게 설명해주세요!

참고 데이터:
{context[:2000]}

자연스럽게 담아주세요:
- 이게 뭔지, 왜 중요한지
- 어떻게 동작하는지
- 관련 개념들
- 실무 팁이나 자주 발생하는 문제<|eot_id|><|start_header_id|>assistant<|end_header_id|>

"""
        
        try:
            response = requests.post(
                f"{OLLAMA_BASE_URL}/api/generate",
                json={
                    "model": OLLAMA_MODEL,
                    "prompt": prompt,
                    "stream": False,
                    "options": {
                        "temperature": 0.75,
                        "top_p": 0.92,
                        "top_k": 40,
                        "repeat_penalty": 1.15,
                        "num_predict": 1500
                    }
                },
                timeout=90
            )
            
            if response.status_code == 200:
                result = response.json()
                raw_response = result.get('response', '')
                if raw_response and len(raw_response.strip()) > 200:
                    return self._clean_llm_response(raw_response.strip())
        except Exception as e:
            print(f"Ollama concept explanation error: {e}")
        return None
    
    def _clean_llm_response(self, text: str) -> str:
        """LLM 응답에서 한글/영어/숫자/기본 특수문자만 유지하고 깨진 문자 제거, 번호목록 줄바꿈 추가"""
        import re
        
        if not text:
            return text
        
        # ★ 불필요한 시작 문구 제거 (LLM이 자주 추가하는 패턴)
        unwanted_starts = [
            r"^I'd be happy to explain[^.]*\.?\s*",
            r"^I'd be happy to help[^.]*\.?\s*",
            r"^I would be happy to[^.]*\.?\s*",
            r"^I'm happy to explain[^.]*\.?\s*",
            r"^I'm happy to help[^.]*\.?\s*",
            r"^Sure,? I can explain[^.]*\.?\s*",
            r"^Sure,? let me explain[^.]*\.?\s*",
            r"^Of course[,!]?\s*",
            r"^Certainly[,!]?\s*",
            r"^Absolutely[,!]?\s*",
            r"^Great question[,!]?\s*",
            r"^Good question[,!]?\s*",
            r"^That's a great question[,!]?\s*",
            r"^Here's an explanation[^.]*\.?\s*",
            r"^Let me explain[^.]*\.?\s*",
        ]
        for pattern in unwanted_starts:
            text = re.sub(pattern, '', text, flags=re.IGNORECASE)
        
        # 허용할 문자 범위 정의:
        # - 한글: 가-힣, ㄱ-ㅎ, ㅏ-ㅣ
        # - 영어: a-zA-Z
        # - 숫자: 0-9
        # - 기본 특수문자: 공백, 줄바꿈, 마침표, 쉼표, 괄호, 콜론 등
        # 그 외 모든 문자 제거
        
        # 허용되는 문자만 남기기 (한글, 영어, 숫자, 기본 특수문자)
        allowed_pattern = r'[가-힣ㄱ-ㅎㅏ-ㅣa-zA-Z0-9\s\.\,\!\?\:\;\'\"\-\_\(\)\[\]\{\}\@\#\$\%\&\*\+\=\/\\\<\>\~\`\|\n\r]'
        
        # 문자 하나씩 검사하여 허용된 문자만 유지
        cleaned_chars = []
        for char in text:
            if re.match(allowed_pattern, char):
                cleaned_chars.append(char)
            elif char in '·•–—…''""':  # 추가 허용 문자
                cleaned_chars.append(char)
        
        text = ''.join(cleaned_chars)
        
        # 빈 괄호 정리
        text = re.sub(r'\(\s*\)', '', text)
        text = re.sub(r'\[\s*\]', '', text)
        
        # 연속된 특수문자 정리
        text = re.sub(r'\.{3,}', '...', text)
        text = re.sub(r'\-{2,}', '-', text)
        
        # 번호 목록 줄바꿈 처리 (1. 2. 3. 또는 1) 2) 3) 형식)
        # 숫자+마침표 또는 숫자+괄호 앞에 줄바꿈 추가 (단, 이미 줄바꿈이 있으면 무시)
        text = re.sub(r'([^\n])\s*(\d+[\.\)])\s+', r'\1\n\n\2 ', text)
        
        # 연속된 공백 정리 (줄바꿈 유지)
        text = re.sub(r'[^\S\n]+', ' ', text)
        # 3개 이상 연속 줄바꿈을 2개로 줄이기
        text = re.sub(r'\n{3,}', '\n\n', text)
        
        return text.strip()
    
    def _detect_query_language(self, query: str) -> str:
        """질문 언어 감지: 'en' 또는 'ko' 반환"""
        import re
        # 한글이 포함되어 있으면 한국어
        if re.search(r'[가-힣]', query):
            return 'ko'
        return 'en'
    
    def _generate_explanation_from_data(self, query: str, context_docs: List[Dict], llm_explanation: Optional[str] = None) -> str:
        """
        LLM 스타일의 자연스러운 설명 응답 생성 (HTML 형식)
        검색 결과가 아닌, 개념 설명 + 핵심 요약 형태
        llm_explanation: LLM이 생성한 개념 설명 텍스트 (있으면 사용)
        """
        import re
        
        # 언어 감지
        lang = self._detect_query_language(query)
        
        # 주제어 추출
        topic = self._extract_topic_from_query(query)
        topic_upper = topic.upper()
        
        # 데이터 분석
        pr_features = []  # (PR번호, 설명, SW버전) 튜플
        pr_fixes = []     # (PR번호, 설명, SW버전) 튜플
        issues_list = []  # (이슈명, PR번호, Issued SW, Fixed SW, PR Suggestion) 튜플
        affected_functions = set()
        sw_versions = set()
        
        # SWRN 인덱서 초기화 (PR Suggestion용)
        swrn_indexer = None
        try:
            from swrn_indexer import SWRNIndexer
            swrn_indexer = SWRNIndexer()
        except Exception:
            pass
        
        for doc in context_docs:
            content = doc.get('content', '')
            source = doc.get('source', '')
            
            # Affected Function 수집
            func_match = re.search(r'Affected\s*Function[:\s]*([^\n|]+)', content, re.IGNORECASE)
            if func_match:
                func_name = func_match.group(1).strip()
                if func_name and len(func_name) < 50:
                    affected_functions.add(func_name)
            
            # SW Version 수집
            ver_match = re.search(r'SW Version[:\s]*([\d\.\-SP\w]+)', content, re.IGNORECASE)
            sw_ver = ver_match.group(1).strip() if ver_match else ''
            if sw_ver:
                sw_versions.add(sw_ver)
            
            # PR 번호 및 설명 추출
            pr_match = re.search(r'PR[-\s]?(\d{6})', content)
            if pr_match:
                pr_num = f"PR-{pr_match.group(1)}"
                
                # Issue Description 추출 (더 깨끗하게)
                desc_match = re.search(r'Issue Description[:\s]*([^|]+)', content, re.IGNORECASE)
                if desc_match:
                    desc_text = desc_match.group(1).strip()
                    # 텍스트 정리
                    desc_text = re.sub(r'\s+', ' ', desc_text)[:150]
                    
                    # New Feature vs Bug Fix 구분
                    if 'new feature' in content.lower():
                        pr_features.append((pr_num, desc_text, sw_ver))
                    elif 'bug' in content.lower() or 'fix' in content.lower():
                        pr_fixes.append((pr_num, desc_text, sw_ver))
            
            # Issue Tracking 데이터 (PR번호, Fixed SW 포함)
            if 'Issues' in source:
                issue_match = re.search(r'Issue:\s*([^|]+)', content)
                if issue_match:
                    issue_text = issue_match.group(1).strip()[:80]
                    if issue_text and len(issue_text) > 10:
                        # PR 번호 추출 (PR or ES 필드에서)
                        issue_pr = re.search(r'PR[-\s]?(\d{5,6})', content)
                        issue_pr_num = f"PR-{issue_pr.group(1)}" if issue_pr else '-'
                        
                        # Issued SW 버전 추출 (이슈가 발견된 SW 버전)
                        issued_match = re.search(r'Issued\s*SW[:\s]*([\d]+\.[\d]+\.[\d]+[-\w]*)', content, re.IGNORECASE)
                        if issued_match:
                            issued_sw = issued_match.group(1).strip()
                        else:
                            issued_sw = '-'
                        
                        # Fixed SW 버전 추출 (Fixed SW: 또는 Fixed: 다음에 버전 형식)
                        fixed_match = re.search(r'Fixed\s*(?:SW)?[:\s]*([\d]+\.[\d]+\.[\d]+[-\w]*)', content, re.IGNORECASE)
                        if not fixed_match:
                            # 대안: "1.8.4-SP" 형식 직접 검색
                            fixed_match = re.search(r'Fixed[:\s]*(\d+\.\d+\.\d+-SP\d+[-\w]*)', content, re.IGNORECASE)
                        if not fixed_match:
                            # 대안: No solution yet 체크
                            if 'No solution yet' in content:
                                fixed_sw = 'No solution yet'
                            else:
                                fixed_sw = '-'
                        else:
                            fixed_sw = fixed_match.group(1).strip()
                        
                        # PR Suggestion: SWRN에서 해당 PR이 언급된 최신 SW 버전 조회
                        pr_suggestion = '-'
                        if swrn_indexer and issue_pr_num != '-':
                            try:
                                swrn_results = swrn_indexer.search_pr(issue_pr_num)
                                if swrn_results:
                                    # 최신 SW 버전 가져오기 (이미 정렬됨)
                                    pr_suggestion = swrn_results[0].get('sw_version', '-')
                            except Exception:
                                pass
                        
                        issues_list.append((issue_text, issue_pr_num, issued_sw, fixed_sw, pr_suggestion))
        
        # ===== LLM 스타일 자연어 설명 생성 =====
        html = []
        
        # 언어별 텍스트 설정
        if lang == 'en':
            header_title = f"💡 About {topic_upper}"
            concept_title = "📖 Concept Overview"
            features_title = "✨ Key Features"
            fixes_title = "🔧 Major Bug Fixes"
            issues_title = "⚠️ Known Issues"
            functions_title = "🏷️ Related Functional Areas"
            footer_info = "More information needed"
            footer_pr = f'"{topic} PR list" - Search SWRN PRs'
            footer_issue = f'"{topic} issues" - Search issue tracking'
        else:
            header_title = f"💡 {topic_upper}에 대한 설명"
            concept_title = "📖 개념 설명"
            features_title = "✨ 주요 기능 및 특징"
            fixes_title = "🔧 주요 버그 수정"
            issues_title = "⚠️ 알려진 이슈"
            functions_title = "🏷️ 관련 기능 영역"
            footer_info = "더 자세한 정보가 필요하시면"
            footer_pr = f'"{topic} 관련 PR 찾아줘" - SWRN PR 목록 검색'
            footer_issue = f'"{topic} 이슈 찾아줘" - 관련 이슈 트래킹 검색'
        
        # 헤더 (LLM 스타일)
        html.append(f'''
<div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; line-height: 1.8;">
    <h3 style="color: #7c3aed; margin: 0 0 20px 0; font-size: 1.3em;">
        {header_title}
    </h3>
''')
        
        # 개념 설명 섹션
        html.append(f'''
    <div style="background: linear-gradient(135deg, #f5f3ff 0%, #ede9fe 100%); 
                padding: 20px; border-radius: 12px; margin-bottom: 20px;
                border-left: 4px solid #7c3aed;">
        <h4 style="color: #5b21b6; margin: 0 0 12px 0; font-size: 1.1em;">{concept_title}</h4>
''')
        
        # LLM 설명이 있으면 사용, 없으면 기본 템플릿 사용
        topic_lower = topic.lower()
        
        if llm_explanation and len(llm_explanation) > 100:
            # LLM이 생성한 상세 설명 사용
            # 더블 줄바꿈을 <p> 태그로, 싱글 줄바꿈을 <br>로 변환
            paragraphs = llm_explanation.split('\n\n')
            formatted_paragraphs = []
            for p in paragraphs:
                p = p.strip()
                if p:
                    # 볼드 처리
                    p = re.sub(r'\*\*([^*]+)\*\*', r'<strong style="color:#7c3aed;">\1</strong>', p)
                    # 언더스코어 볼드 처리
                    p = re.sub(r'_([^_]+)_', r'<strong style="color:#7c3aed;">\1</strong>', p)
                    # 싱글 줄바꿈을 <br>로 변환
                    p = p.replace('\n', '<br>')
                    formatted_paragraphs.append(f'<p style="margin: 0 0 12px 0; color: #374151;">{p}</p>')
            
            concept_text = ''.join(formatted_paragraphs)
        elif 'bias' in topic_lower and 'rf' in topic_lower:
            if lang == 'en':
                concept_text = f'''<p style="margin: 0 0 10px 0; color: #374151;">
                    <strong>{topic_upper}</strong> is an RF (Radio Frequency) power system used in semiconductor 
                    etching equipment to apply bias voltage to the wafer.
                </p>
                <p style="margin: 0; color: #374151;">
                    It's a key component that controls ion energy to adjust etch profile and selectivity, 
                    determining the directionality and energy of ions in the plasma.
                </p>'''
            else:
                concept_text = f'''<p style="margin: 0 0 10px 0; color: #374151;">
                    <strong>{topic_upper}</strong>는 반도체 에칭(Etching) 장비에서 웨이퍼에 
                    바이어스 전압을 인가하기 위한 RF(Radio Frequency) 전원 시스템입니다.
                </p>
                <p style="margin: 0; color: #374151;">
                    이온 에너지를 제어하여 에칭 프로파일과 선택비를 조절하는 핵심 구성요소로, 
                    플라즈마 내 이온의 방향성과 에너지를 결정합니다.
                </p>'''
        elif 'tcp' in topic_lower:
            if lang == 'en':
                concept_text = f'''<p style="margin: 0 0 10px 0; color: #374151;">
                    <strong>{topic_upper}</strong> stands for Transformer Coupled Plasma, 
                    a type of plasma source using transformer coupling.
                </p>
                <p style="margin: 0; color: #374151;">
                    It generates high-density plasma used in etching and deposition processes.
                </p>'''
            else:
                concept_text = f'''<p style="margin: 0 0 10px 0; color: #374151;">
                    <strong>{topic_upper}</strong>는 Transformer Coupled Plasma의 약자로, 
                    변압기 결합 방식의 플라즈마 소스입니다.
                </p>
                <p style="margin: 0; color: #374151;">
                    고밀도 플라즈마를 생성하여 에칭 및 증착 공정에 사용됩니다.
                </p>'''
        elif 'ecat' in topic_lower or 'match' in topic_lower:
            if lang == 'en':
                concept_text = f'''<p style="margin: 0 0 10px 0; color: #374151;">
                    <strong>{topic_upper}</strong> is an impedance matching network 
                    that optimizes RF power delivery efficiency.
                </p>
                <p style="margin: 0; color: #374151;">
                    It minimizes reflected power to maintain stable plasma conditions.
                </p>'''
            else:
                concept_text = f'''<p style="margin: 0 0 10px 0; color: #374151;">
                    <strong>{topic_upper}</strong>는 RF 전력 전달 효율을 최적화하기 위한 
                    임피던스 매칭 네트워크입니다.
                </p>
                <p style="margin: 0; color: #374151;">
                    반사 전력을 최소화하여 안정적인 플라즈마 유지에 기여합니다.
                </p>'''
        elif 'esc' in topic_lower or 'chuck' in topic_lower:
            if lang == 'en':
                concept_text = f'''<p style="margin: 0 0 10px 0; color: #374151;">
                    <strong>{topic_upper}</strong> (Electrostatic Chuck) is a device 
                    that holds wafers using electrostatic force.
                </p>
                <p style="margin: 0; color: #374151;">
                    It works together with temperature control and Helium backside cooling.
                </p>'''
            else:
                concept_text = f'''<p style="margin: 0 0 10px 0; color: #374151;">
                    <strong>{topic_upper}</strong>는 Electrostatic Chuck의 약자로, 
                    정전기력을 이용해 웨이퍼를 고정하는 장치입니다.
                </p>
                <p style="margin: 0; color: #374151;">
                    온도 제어 및 헬륨 백사이드 쿨링과 함께 작동합니다.
                </p>'''
        elif 'mfc' in topic_lower or 'gas' in topic_lower:
            if lang == 'en':
                concept_text = f'''<p style="margin: 0 0 10px 0; color: #374151;">
                    <strong>{topic_upper}</strong> (Mass Flow Controller) is a device 
                    that precisely controls process gas flow rates.
                </p>
                <p style="margin: 0; color: #374151;">
                    Each gas line has its own MFC to deliver accurate gas supply based on recipes.
                </p>'''
            else:
                concept_text = f'''<p style="margin: 0 0 10px 0; color: #374151;">
                    <strong>{topic_upper}</strong>는 Mass Flow Controller의 약자로, 
                    공정 가스의 유량을 정밀하게 제어하는 장치입니다.
                </p>
                <p style="margin: 0; color: #374151;">
                    각 가스 라인별로 설치되어 레시피에 따른 정확한 가스 공급을 담당합니다.
                </p>'''
        else:
            # 일반적인 설명 (General explanation)
            func_list = list(affected_functions)[:3]
            func_text = ', '.join(func_list) if func_list else ('various functions' if lang == 'en' else '다양한 기능')
            if lang == 'en':
                concept_text = f'''<p style="margin: 0; color: #374151;">
                    <strong>{topic_upper}</strong> is a feature in semiconductor equipment software 
                    related to {func_text}.
                </p>'''
            else:
                concept_text = f'''<p style="margin: 0; color: #374151;">
                    <strong>{topic_upper}</strong>는 반도체 장비 소프트웨어에서 
                    {func_text} 등과 관련된 기능입니다.
                </p>'''
        
        html.append(concept_text)
        html.append('    </div>')
        
        # 신규 기능 섹션 (New Features)
        if pr_features:
            html.append(f'''
    <div style="background: #f0fdf4; padding: 20px; border-radius: 12px; margin-bottom: 20px;
                border-left: 4px solid #22c55e;">
        <h4 style="color: #166534; margin: 0 0 12px 0; font-size: 1.1em;">{features_title}</h4>
        <ul style="margin: 0; padding-left: 20px; color: #374151;">
''')
            seen = set()
            count = 0
            for pr_num, desc in pr_features[:5]:
                if desc not in seen:
                    seen.add(desc)
                    html.append(f'''            <li style="margin: 8px 0;">
                <strong style="color: #059669;">{pr_num}</strong>: {desc}
            </li>''')
                    count += 1
                    if count >= 3:
                        break
            html.append('''        </ul>
    </div>''')
        
        # 버그 수정 섹션 (Bug Fixes)
        if pr_fixes:
            html.append(f'''
    <div style="background: #fef3c7; padding: 20px; border-radius: 12px; margin-bottom: 20px;
                border-left: 4px solid #d97706;">
        <h4 style="color: #b45309; margin: 0 0 12px 0; font-size: 1.1em;">{fixes_title}</h4>
        <ul style="margin: 0; padding-left: 20px; color: #374151;">
''')
            seen = set()
            count = 0
            for pr_num, desc in pr_fixes[:5]:
                if desc not in seen:
                    seen.add(desc)
                    html.append(f'''            <li style="margin: 8px 0;">
                <strong style="color: #d97706;">{pr_num}</strong>: {desc}
            </li>''')
                    count += 1
                    if count >= 3:
                        break
            html.append('''        </ul>
    </div>''')
        
        # 알려진 이슈 섹션 (테이블 형식으로 PR번호, Issued SW, Fixed SW, PR Suggestion 포함)
        if issues_list:
            html.append(f'''
    <div style="background: #fef2f2; padding: 20px; border-radius: 12px; margin-bottom: 20px;
                border-left: 4px solid #ef4444;">
        <h4 style="color: #dc2626; margin: 0 0 12px 0; font-size: 1.1em;">{issues_title}</h4>
        <table style="width: 100%; border-collapse: collapse; font-size: 0.85em;">
            <thead>
                <tr style="background: #fecaca;">
                    <th style="padding: 6px 8px; text-align: left; border-bottom: 2px solid #ef4444;">Issue Description</th>
                    <th style="padding: 6px 8px; text-align: center; border-bottom: 2px solid #ef4444; width: 90px;">PR Number</th>
                    <th style="padding: 6px 8px; text-align: center; border-bottom: 2px solid #ef4444; width: 110px;">Issued SW</th>
                    <th style="padding: 6px 8px; text-align: center; border-bottom: 2px solid #ef4444; width: 110px;">Fixed SW</th>
                    <th style="padding: 6px 8px; text-align: center; border-bottom: 2px solid #ef4444; width: 110px;">PR Suggestion</th>
                </tr>
            </thead>
            <tbody>
''')
            seen = set()
            count = 0
            for issue_text, pr_num, issued_sw, fixed_sw, pr_suggestion in issues_list:
                if issue_text not in seen and count < 5:
                    seen.add(issue_text)
                    pr_link = f'<a href="https://iplmprd.fremont.lamrc.net/3dspace/goto/o/LRC+Problem+Report/{pr_num}" target="_blank" style="color: #dc2626;">{pr_num}</a>' if pr_num != '-' else '-'
                    # PR Suggestion 스타일: 값이 있으면 녹색 배경
                    suggestion_style = 'background: #d1fae5; color: #065f46;' if pr_suggestion != '-' else ''
                    html.append(f'''                <tr style="border-bottom: 1px solid #fecaca;">
                    <td style="padding: 6px 8px;">{issue_text}</td>
                    <td style="padding: 6px 8px; text-align: center;">{pr_link}</td>
                    <td style="padding: 6px 8px; text-align: center; font-family: monospace; font-size: 0.85em;">{issued_sw}</td>
                    <td style="padding: 6px 8px; text-align: center; font-family: monospace; font-size: 0.85em;">{fixed_sw}</td>
                    <td style="padding: 6px 8px; text-align: center; font-family: monospace; font-size: 0.85em; {suggestion_style}">{pr_suggestion}</td>
                </tr>''')
                    count += 1
            html.append('''            </tbody>
        </table>
    </div>''')
        
        # 관련 기능 영역 태그
        if affected_functions:
            html.append(f'''
    <div style="margin-bottom: 20px;">
        <h4 style="color: #374151; margin: 0 0 10px 0; font-size: 1em;">{functions_title}</h4>
        <div style="display: flex; flex-wrap: wrap; gap: 8px;">
''')
            for func in list(affected_functions)[:6]:
                html.append(f'''            <span style="background: #e0e7ff; color: #4338ca; padding: 4px 12px; 
                          border-radius: 20px; font-size: 0.85em;">{func}</span>''')
            html.append('''        </div>
    </div>''')
        
        # 푸터 (추가 검색 안내 + 외부 링크)
        html.append(f'''
    <div style="background: #f8fafc; padding: 15px; border-radius: 10px; 
                border: 1px dashed #cbd5e1; margin-top: 10px;">
        <p style="margin: 0 0 12px 0; font-size: 0.9em; color: #64748b;">
            💬 <strong>{footer_info}:</strong><br>
            • {footer_pr}<br>
            • {footer_issue}
        </p>
        <div style="display: flex; gap: 12px; flex-wrap: wrap; margin-top: 10px; padding-top: 10px; border-top: 1px solid #e2e8f0;">
            <a href="https://lamrc.atlassian.net/wiki/home" target="_blank" 
               style="display: inline-flex; align-items: center; gap: 4px; padding: 6px 12px; 
                      background: #0052CC; color: white; border-radius: 6px; 
                      text-decoration: none; font-size: 0.85em; font-weight: 500;">
                📘 Confluence
            </a>
            <a href="https://lambots.lamrc.net/" target="_blank" 
               style="display: inline-flex; align-items: center; gap: 6px; padding: 6px 12px; 
                      background: #84BD00; color: white; border-radius: 6px; 
                      text-decoration: none; font-size: 0.85em; font-weight: 500;">
                <span style="display: inline-flex; align-items: center; justify-content: center; width: 18px; height: 18px; background: white; border-radius: 3px; font-weight: bold; font-size: 12px; color: #84BD00; font-family: Arial, sans-serif;">L</span>
                LamBots
            </a>
            <a href="https://wiki/2300SW" target="_blank" 
               style="display: inline-flex; align-items: center; gap: 4px; padding: 6px 12px; 
                      background: #059669; color: white; border-radius: 6px; 
                      text-decoration: none; font-size: 0.85em; font-weight: 500;">
                📚 Wiki
            </a>
        </div>
    </div>
</div>
''')
        
        # HTML 결합 후 불필요한 줄바꿈 제거 (이미 HTML이므로 <br> 변환 방지)
        result = ''.join(html)
        import re
        # 모든 줄바꿈과 여러 공백을 하나의 공백으로 정리
        result = re.sub(r'\s+', ' ', result)
        # 태그 사이의 불필요한 공백 정리
        result = re.sub(r'>\s+<', '><', result)
        
        return result.strip()
    
    def generate_response(self, query: str, context_docs: List[Dict]) -> str:
        """
        LLM을 사용하여 응답 생성 (대화 히스토리 저장 포함)
        우선순위: GGUF 모델 > Ollama > 폴백 응답
        """
        # 컨텍스트 구성
        context = "\n\n".join([
            f"[{doc['source']}]\n{doc['content']}"
            for doc in context_docs[:5]
        ])
        
        if not context:
            return "관련 데이터를 찾을 수 없습니다. 다른 검색어로 시도해 주세요."
        
        response = None
        
        # GGUF 모델 사용 (우선)
        if self.gguf_available and self.gguf_model:
            response = self._generate_with_gguf(query, context, context_docs)
        
        # Ollama 사용 (GGUF 없을 때)
        elif self.ollama_available:
            response = self._generate_with_ollama(query, context, context_docs)
        
        # 폴백 응답
        else:
            response = self._fallback_response(query, context_docs)
        
        # 대화 히스토리에 저장 (HTML 태그 제거하여 저장)
        if response:
            import re
            clean_response = re.sub(r'<[^>]+>', '', response)  # HTML 태그 제거
            self.add_to_history(query, clean_response)
        
        return response
    
    def _format_llm_response_to_html(self, text: str) -> str:
        """LLM 응답을 읽기 쉬운 HTML로 변환"""
        import re
        
        if not text:
            return text
        
        # 이미 완성된 HTML 응답인 경우 변환 건너뛰기
        if text.strip().startswith('<div style="font-family:') or text.strip().startswith('<div class="swrn-search-result">'):
            return text
        
        # 1. _text_ 형식을 <strong>text</strong>로 변환 (이탤릭 대신 볼드로)
        text = re.sub(r'_([^_]+)_', r'<strong style="color:#7c3aed;">\1</strong>', text)
        
        # 2. **text** 형식을 <strong>text</strong>로 변환
        text = re.sub(r'\*\*([^*]+)\*\*', r'<strong>\1</strong>', text)
        
        # 3. `code` 형식을 <code>로 변환
        text = re.sub(r'`([^`]+)`', r'<code style="background:#f3f4f6;padding:2px 6px;border-radius:4px;font-family:monospace;">\1</code>', text)
        
        # 4. 줄바꿈을 <br>로 변환
        text = text.replace('\n\n', '</p><p style="margin:10px 0;">')
        text = text.replace('\n', '<br>')
        
        # 5. 리스트 형식 변환 (- 또는 • 로 시작하는 줄)
        lines = text.split('<br>')
        formatted_lines = []
        in_list = False
        
        for line in lines:
            stripped = line.strip()
            if stripped.startswith('- ') or stripped.startswith('• '):
                if not in_list:
                    formatted_lines.append('<ul style="margin:8px 0;padding-left:20px;">')
                    in_list = True
                item_content = stripped[2:].strip()
                formatted_lines.append(f'<li style="margin:4px 0;">{item_content}</li>')
            elif stripped.startswith('* '):
                if not in_list:
                    formatted_lines.append('<ul style="margin:8px 0;padding-left:20px;">')
                    in_list = True
                item_content = stripped[2:].strip()
                formatted_lines.append(f'<li style="margin:4px 0;">{item_content}</li>')
            else:
                if in_list:
                    formatted_lines.append('</ul>')
                    in_list = False
                formatted_lines.append(line)
        
        if in_list:
            formatted_lines.append('</ul>')
        
        text = '<br>'.join(formatted_lines)
        
        # 6. 번호 리스트 변환 (1. 2. 3. 형식)
        text = re.sub(r'<br>(\d+)\. ', r'<br><strong style="color:#7c3aed;">\1.</strong> ', text)
        
        # 7. 섹션 헤더 변환 (### 또는 ## 형식)
        text = re.sub(r'###\s*(.+?)(<br>|</p>)', r'<h4 style="color:#7c3aed;margin:12px 0 6px 0;font-size:14px;">\1</h4>\2', text)
        text = re.sub(r'##\s*(.+?)(<br>|</p>)', r'<h3 style="color:#7c3aed;margin:12px 0 6px 0;font-size:15px;">\1</h3>\2', text)
        
        # 8. 기술 용어 하이라이트 (대문자로 시작하는 약어들)
        tech_terms = ['RF', 'TCP', 'IP', 'ESC', 'MFC', 'CVF', 'SNAP', 'NPT', 'KPI', 'SW', 'HF', 'SP', 'PR', 'SWRN', 'PLM', 'NPVCI', 'ECAT', 'EIOC', 'AMS', 'PM']
        for term in tech_terms:
            # 단어 경계에서만 매칭 (이미 태그 안에 있지 않은 경우)
            text = re.sub(
                rf'(?<!<[^>]*)\b({term})\b(?![^<]*>)',
                rf'<span style="background:#e0e7ff;padding:1px 4px;border-radius:3px;font-weight:500;">\1</span>',
                text
            )
        
        # 9. 최종 래핑
        if not text.startswith('<p'):
            text = f'<p style="margin:10px 0;">{text}</p>'
        
        return text
    
    def _generate_with_gguf(self, query: str, context: str, context_docs: List[Dict], lang: str = 'ko') -> str:
        """GGUF 모델로 자연스러운 K-Bot 응답 생성 (Enhanced Prompt Engineering)"""
        
        # 언어별 시스템 프롬프트 선택
        system_prompt = KBOT_SYSTEM_PROMPT_KO if lang == 'ko' else KBOT_SYSTEM_PROMPT_EN
        few_shot = FEW_SHOT_EXAMPLES_KO if lang == 'ko' else FEW_SHOT_EXAMPLES_EN
        
        if lang == 'ko':
            prompt = f"""<|begin_of_text|><|start_header_id|>system<|end_header_id|>

{system_prompt}

{few_shot}<|eot_id|><|start_header_id|>user<|end_header_id|>

**참고 데이터:**
{context[:3000]}

**질문:** {query}

위 데이터를 바탕으로 친근하고 자연스럽게 답변해주세요.
핵심 내용을 먼저 설명하고, 세부 사항을 덧붙여주세요.<|eot_id|><|start_header_id|>assistant<|end_header_id|>

"""
        else:
            prompt = f"""<|begin_of_text|><|start_header_id|>system<|end_header_id|>

{system_prompt}

{few_shot}<|eot_id|><|start_header_id|>user<|end_header_id|>

**Reference Data:**
{context[:3000]}

**Question:** {query}

Please answer in a friendly and natural way based on the data above.
Explain the key points first, then add details.<|eot_id|><|start_header_id|>assistant<|end_header_id|>

"""
        
        try:
            response = self.gguf_model(prompt)
            if response and response.strip():
                cleaned = self._clean_kbot_response(response.strip())
                return self._format_llm_response_to_html(cleaned)
            else:
                return self._fallback_response(query, context_docs)
        except Exception as e:
            print(f"GGUF generation error: {e}")
            return self._fallback_response(query, context_docs)
    
    def _generate_with_gguf_for_explain(self, query: str, context: str, context_docs: List[Dict]) -> Optional[str]:
        """GGUF 모델로 설명 응답 생성 (실패 시 None 반환)"""
        if not self.gguf_available or not self.gguf_model:
            return None
        try:
            prompt = f"""당신은 반도체 장비 기술 전문가입니다. 
주어진 데이터를 바탕으로 사용자의 질문에 대해 상세하게 설명해주세요.

중요: 검색 결과 목록이 아닌 **설명 형식**으로 답변하세요.

데이터:
{context}

질문: {query}

위 데이터를 참고하여 기술적 설명을 제공하세요. 
- 개념 정의
- 관련 기능
- 해결된 이슈 요약
- 실무 적용 사례
"""
            response = self.gguf_model(prompt)
            if response and response.strip() and len(response.strip()) > 100:
                return self._format_llm_response_to_html(response.strip())
            return None
        except Exception as e:
            print(f"GGUF explain error: {e}")
            return None
    
    def _generate_with_ollama_for_explain(self, query: str, context: str, context_docs: List[Dict]) -> Optional[str]:
        """Ollama로 설명 응답 생성 (실패 시 None 반환)"""
        if not self.ollama_available:
            return None
        
        prompt = f"""당신은 반도체 장비 기술 전문가입니다.
주어진 데이터를 바탕으로 사용자의 질문에 대해 **설명 형식**으로 답변하세요.

중요 규칙:
- 검색 결과 목록이 아닌 설명문으로 작성
- **볼드**를 사용하여 핵심 용어 강조
- 개념 정의, 관련 기능, 해결 사례를 포함

데이터:
{context}

질문: {query}

기술적 설명을 한국어로 작성하세요:"""
        
        try:
            response = requests.post(
                f"{OLLAMA_BASE_URL}/api/generate",
                json={
                    "model": OLLAMA_MODEL,
                    "prompt": prompt,
                    "stream": False,
                    "options": {
                        "temperature": 0.7,
                        "top_p": 0.9,
                        "num_predict": 2048
                    }
                },
                timeout=90
            )
            
            if response.status_code == 200:
                result = response.json()
                raw_response = result.get('response', '')
                if raw_response and len(raw_response.strip()) > 100:
                    return self._format_llm_response_to_html(raw_response)
            return None
        except Exception as e:
            print(f"Ollama explain error: {e}")
            return None
    
    def _generate_with_ollama(self, query: str, context: str, context_docs: List[Dict], lang: str = 'ko') -> str:
        """Ollama API로 자연스러운 K-Bot 응답 생성 (Enhanced Prompt Engineering with Memory & Grounding)"""
        
        # 언어별 시스템 프롬프트 선택
        system_prompt = KBOT_SYSTEM_PROMPT_KO if lang == 'ko' else KBOT_SYSTEM_PROMPT_EN
        few_shot = FEW_SHOT_EXAMPLES_KO if lang == 'ko' else FEW_SHOT_EXAMPLES_EN
        
        # 대화 히스토리 컨텍스트 추가
        conversation_context = self.get_conversation_context()
        
        # Grounding 지시 (환각 방지)
        grounding_instruction = """
**중요 규칙 (Grounding):**
- 위 '참고 데이터'에 있는 정보만 사용하세요
- 데이터에 없는 내용은 "해당 정보를 찾을 수 없습니다"라고 답하세요
- 추측이나 일반 지식으로 답변하지 마세요
- 숫자, 날짜, 버전 등은 데이터에서 정확히 인용하세요
"""
        
        # Chain-of-Thought 유도를 위한 프롬프트 구성
        if lang == 'ko':
            prompt = f"""<|begin_of_text|><|start_header_id|>system<|end_header_id|>

{system_prompt}

{few_shot}<|eot_id|><|start_header_id|>user<|end_header_id|>

{conversation_context}

**참고 데이터:**
{context[:3000]}

{grounding_instruction}

**질문:** {query}

단계적으로 생각해보세요:
1. 먼저 질문의 핵심이 무엇인지 파악합니다
2. 참고 데이터에서 관련 정보를 찾습니다
3. 핵심 내용을 먼저 답하고, 세부 사항을 추가합니다<|eot_id|><|start_header_id|>assistant<|end_header_id|>

"""
        else:
            prompt = f"""<|begin_of_text|><|start_header_id|>system<|end_header_id|>

{system_prompt}

{few_shot}<|eot_id|><|start_header_id|>user<|end_header_id|>

{conversation_context}

**Reference Data:**
{context[:3000]}

**Important Rules (Grounding):**
- Use ONLY information from the Reference Data above
- If information is not in the data, say "I couldn't find that information"
- Do not guess or use general knowledge
- Quote numbers, dates, versions exactly from the data

**Question:** {query}

Think step by step:
1. First identify what the question is asking
2. Find relevant information in the reference data
3. Answer the key points first, then add details<|eot_id|><|start_header_id|>assistant<|end_header_id|>

"""
        
        try:
            response = requests.post(
                f"{OLLAMA_BASE_URL}/api/generate",
                json={
                    "model": OLLAMA_MODEL,
                    "prompt": prompt,
                    "stream": False,
                    "options": {
                        "temperature": 0.75,  # 약간 높여서 더 자연스러운 응답
                        "top_p": 0.92,  # 다양성 증가
                        "top_k": 40,  # 상위 40개 토큰에서 선택
                        "repeat_penalty": 1.15,  # 반복 방지
                        "num_predict": 2048
                    }
                },
                timeout=90
            )
            
            if response.status_code == 200:
                result = response.json()
                raw_response = result.get('response', '')
                if raw_response:
                    # 응답 후처리 및 포맷팅
                    cleaned = self._clean_kbot_response(raw_response)
                    return self._format_llm_response_to_html(cleaned)
                return self._fallback_response(query, context_docs)
            else:
                return self._fallback_response(query, context_docs)
        
        except Exception as e:
            print(f"Ollama error: {e}")
            return self._fallback_response(query, context_docs)
    
    def _clean_kbot_response(self, response: str) -> str:
        """K-Bot 응답 정리 - 불필요한 요소 제거 및 자연스러움 향상"""
        import re
        
        # 1. Llama 특수 토큰 제거
        response = re.sub(r'<\|[^|]+\|>', '', response)
        
        # 2. 응답 시작 부분의 불필요한 패턴 제거
        response = re.sub(r'^(네,?\s*|알겠습니다\.?\s*|물론이죠\.?\s*)', '', response.strip())
        
        # 3. 반복되는 문장 제거
        lines = response.split('\n')
        seen = set()
        unique_lines = []
        for line in lines:
            clean_line = line.strip()
            if clean_line and clean_line not in seen:
                seen.add(clean_line)
                unique_lines.append(line)
        response = '\n'.join(unique_lines)
        
        # 4. 과도한 이모지 제거 (2개 이상 연속 시 1개로)
        response = re.sub(r'([\U0001F300-\U0001F9FF])\1+', r'\1', response)
        
        # 5. 마지막에 질문 유도 문구 추가 (없는 경우)
        if not any(phrase in response for phrase in ['궁금하', '질문', '더 필요하', '물어보']):
            response = response.rstrip() + '\n\n추가로 궁금한 점이 있으시면 말씀해주세요! 😊'
        
        return response.strip()
    
    def _fallback_response(self, query: str, context_docs: List[Dict]) -> str:
        """Ollama 없이 스마트 데이터 분석 응답 생성"""
        if not context_docs:
            return "안녕하세요! 🔍 요청하신 내용과 관련된 데이터를 찾지 못했어요.\n\n다른 키워드나 조건으로 다시 질문해 주시면 최선을 다해 찾아드릴게요! 😊"
        
        import re
        
        # 쿼리 의도 파악
        query_lower = query.lower()
        intent = self._detect_query_intent(query)
        
        response_parts = []
        
        # 의도에 따른 스마트 분석
        if intent == 'fixed_version':
            response_parts.extend(self._analyze_fixed_versions(query, context_docs))
        elif intent == 'waiting_status':
            response_parts.extend(self._analyze_waiting_issues(query, context_docs))
        elif intent == 'upgrade':
            response_parts.extend(self._analyze_upgrades(query, context_docs))
        elif intent == 'status_count':
            response_parts.extend(self._analyze_status_distribution(query, context_docs))
        elif intent == 'fab_specific':
            response_parts.extend(self._analyze_fab_issues(query, context_docs))
        elif intent == 'long_open_prs':
            response_parts.extend(self._analyze_long_open_prs(query, context_docs))
        else:
            response_parts.extend(self._general_analysis(query, context_docs))
        
        return "".join(response_parts)
    
    def _detect_query_intent(self, query: str) -> str:
        """쿼리 의도 파악"""
        query_lower = query.lower()
        
        # 오랫동안 고쳐지지 않는 PR 관련
        if any(kw in query for kw in ['오랫동안', '오래된', '오래', 'long', '장기', '해결 안', '고쳐지지 않']):
            return 'long_open_prs'
        elif any(kw in query for kw in ['고쳐', '수정', 'fixed', 'solve','solved','resolved','fix된', '해결된']):
            return 'fixed_version'
        elif any(kw in query for kw in ['대기', 'waiting', 'pending', '진행중']):
            return 'waiting_status'
        elif any(kw in query for kw in ['업그레이드', 'upgrade', '업데이트', 'update','버전']):
            return 'upgrade'
        elif any(kw in query for kw in ['몇개', '몇 개', '개수', 'count', '통계', '분포']):
            return 'status_count'
        elif any(kw in query for kw in ['R3', 'R4','M16','M15X','M14','M15', 'M10', 'M11', 'M12', 'NAND', 'DRAM', 'fab', 'Fab']):
            return 'fab_specific'
        return 'general'
    
    def _analyze_fixed_versions(self, query: str, docs: List[Dict]) -> List[str]:
        """Fixed SW 버전 분석 - 기본 3개월 데이터, 없으면 전체"""
        import re
        from datetime import datetime, timedelta
        
        # 기본 검색 기간: 3개월
        cutoff_date = datetime.now() - timedelta(days=90)
        use_date_filter = True
        
        parts = []
        
        def extract_items(docs_list, apply_date_filter):
            """문서에서 항목 추출"""
            fixed_items = []
            no_solution = []
            
            for doc in docs_list:
                content = doc.get('content', '')
                
                # 날짜 추출
                date_match = re.search(r'Date reported:\s*(\d{1,2}/\d{1,2}/\d{4})', content)
                date_reported = date_match.group(1) if date_match else "N/A"
                
                # 날짜 필터링 (옵션)
                if apply_date_filter and date_match:
                    try:
                        doc_date = datetime.strptime(date_match.group(1), '%m/%d/%Y')
                        if doc_date < cutoff_date:
                            continue
                    except:
                        pass
                
                fixed_match = re.search(r'Fixed SW:\s*([^\|]+)', content)
                issue_match = re.search(r'Issue:\s*([^\|]+)', content)
                status_match = re.search(r'Current Status:\s*([^\|]+)', content)
                fab_match = re.search(r'Fab:\s*([^\|]+)', content)
                pr_match = re.search(r'PR or ES\s*:\s*([^\|]+)', content)
                issued_sw_match = re.search(r'Issued SW:\s*([^\|]+)', content)
                
                if fixed_match:
                    fixed_sw = fixed_match.group(1).strip()
                    issue = issue_match.group(1).strip() if issue_match else "N/A"
                    status = status_match.group(1).strip() if status_match else ""
                    fab = fab_match.group(1).strip() if fab_match else ""
                    pr_link = pr_match.group(1).strip() if pr_match else ""
                    issued_sw = issued_sw_match.group(1).strip() if issued_sw_match else ""
                    
                    pr_num_match = re.search(r'(PR-\d+)', pr_link)
                    pr_num = pr_num_match.group(1) if pr_num_match else ""
                    
                    if 'No solution' in fixed_sw or 'No software' in fixed_sw:
                        no_solution.append({
                            'issue': issue, 'status': status, 'fab': fab,
                            'pr': pr_num, 'issued_sw': issued_sw, 'date': date_reported
                        })
                    else:
                        fixed_items.append({
                            'version': fixed_sw, 'issue': issue, 'fab': fab, 'date': date_reported
                        })
            
            return fixed_items, no_solution
        
        # 먼저 3개월 필터 적용
        fixed_items, no_solution = extract_items(docs, True)
        
        # 결과가 없으면 전체 데이터로 재시도
        if not fixed_items and not no_solution:
            fixed_items, no_solution = extract_items(docs, False)
            parts.append(f"## 🔧 SW 버전 수정 현황 분석\n\n")
            parts.append(f"안녕하세요! 요청하신 SW 수정 현황을 분석해 드릴게요 😊\n\n")
            parts.append(f"📅 **검색 기간**: 전체 (최근 3개월 내 데이터 없음)\n\n")
        else:
            parts.append(f"## 🔧 SW 버전 수정 현황 분석\n\n")
            parts.append(f"안녕하세요! 요청하신 SW 수정 현황을 분석해 드릴게요 😊\n\n")
            parts.append(f"📅 **검색 기간**: {cutoff_date.strftime('%Y-%m-%d')} ~ {datetime.now().strftime('%Y-%m-%d')} (최근 3개월)\n\n")
        
        if fixed_items:
            parts.append(f"### ✅ 수정 완료된 이슈 ({len(fixed_items)}건)\n\n")
            parts.append("| Date | Fab | 이슈 | Fixed SW 버전 |\n")
            parts.append("|------|-----|------|---------------|\n")
            for item in fixed_items[:15]:
                parts.append(f"| {item['date']} | {item['fab']} | {item['issue']} | **{item['version']}** |\n")
            parts.append("\n")
        
        if no_solution:
            parts.append(f"### ⏳ 아직 수정되지 않은 이슈 ({len(no_solution)}건)\n\n")
            parts.append("| Date | Fab | 이슈 | PR 번호 | Issued SW |\n")
            parts.append("|------|-----|------|---------|----------|\n")
            for item in no_solution[:15]:
                parts.append(f"| {item['date']} | {item['fab']} | {item['issue']} | {item['pr']} | {item['issued_sw']} |\n")
            parts.append("\n")
        
        # 요약
        total = len(fixed_items) + len(no_solution)
        if total > 0:
            fix_rate = len(fixed_items) / total * 100
            parts.append(f"### 📈 요약\n")
            parts.append(f"- 검색된 이슈: **{total}건**\n")
            parts.append(f"- 수정 완료: **{len(fixed_items)}건** ({fix_rate:.0f}%)\n")
            parts.append(f"- 수정 대기: **{len(no_solution)}건**\n\n")
            parts.append(f"더 자세한 정보가 필요하시면 말씀해주세요! 🙌\n")
        
        return parts
    
    def _analyze_waiting_issues(self, query: str, docs: List[Dict]) -> List[str]:
        """대기 중인 이슈 분석 - 기본 3개월 데이터"""
        import re
        from datetime import datetime, timedelta
        
        cutoff_date = datetime.now() - timedelta(days=90)
        
        def extract_waiting(docs_list, apply_date_filter):
            """대기 이슈 추출"""
            items = []
            for doc in docs_list:
                content = doc.get('content', '')
                
                date_match = re.search(r'Date reported:\s*(\d{1,2}/\d{1,2}/\d{4})', content)
                date_reported = date_match.group(1) if date_match else "N/A"
                
                if apply_date_filter and date_match:
                    try:
                        doc_date = datetime.strptime(date_match.group(1), '%m/%d/%Y')
                        if doc_date < cutoff_date:
                            continue
                    except:
                        pass
                
                if 'Waiting' in content or '대기' in content or 'pending' in content.lower():
                    issue_match = re.search(r'Issue:\s*([^\|]+)', content)
                    status_match = re.search(r'Current Status:\s*([^\|]+)', content)
                    priority_match = re.search(r'Priority:\s*([^\|]+)', content)
                    fab_match = re.search(r'Fab:\s*([^\|]+)', content)
                    pr_match = re.search(r'PR or ES\s*:\s*([^\|]+)', content)
                    issued_sw_match = re.search(r'Issued SW:\s*([^\|]+)', content)
                    
                    pr_link = pr_match.group(1).strip() if pr_match else ""
                    pr_num_match = re.search(r'(PR-\d+)', pr_link)
                    pr_num = pr_num_match.group(1) if pr_num_match else ""
                    
                    items.append({
                        'issue': issue_match.group(1).strip() if issue_match else "N/A",
                        'status': status_match.group(1).strip() if status_match else "",
                        'priority': priority_match.group(1).strip() if priority_match else "",
                        'fab': fab_match.group(1).strip() if fab_match else "",
                        'pr': pr_num,
                        'issued_sw': issued_sw_match.group(1).strip() if issued_sw_match else "",
                        'date': date_reported
                    })
            return items
        
        parts = []
        waiting_issues = extract_waiting(docs, True)
        
        if not waiting_issues:
            waiting_issues = extract_waiting(docs, False)
            parts.append(f"## ⏳ 대기 중인 이슈 현황\n\n")
            parts.append(f"안녕하세요! 현재 대기 중인 이슈들을 정리해 드릴게요 😊\n\n")
            parts.append(f"📅 **검색 기간**: 전체 (최근 3개월 내 데이터 없음)\n\n")
        else:
            parts.append(f"## ⏳ 대기 중인 이슈 현황\n\n")
            parts.append(f"안녕하세요! 현재 대기 중인 이슈들을 정리해 드릴게요 😊\n\n")
            parts.append(f"📅 **검색 기간**: {cutoff_date.strftime('%Y-%m-%d')} ~ {datetime.now().strftime('%Y-%m-%d')} (최근 3개월)\n\n")
        
        # Priority 별 분류
        critical = [i for i in waiting_issues if 'Critical' in i['priority']]
        high = [i for i in waiting_issues if 'High' in i['priority']]
        normal = [i for i in waiting_issues if 'Normal' in i['priority'] or not i['priority']]
        
        if critical:
            parts.append(f"### 🔴 Critical ({len(critical)}건)\n\n")
            parts.append("| Date | Fab | 이슈 | PR 번호 | Issued SW |\n")
            parts.append("|------|-----|------|---------|----------|\n")
            for item in critical[:10]:
                parts.append(f"| {item['date']} | {item['fab']} | {item['issue']} | {item['pr']} | {item['issued_sw']} |\n")
            parts.append("\n")
        
        if high:
            parts.append(f"### 🟠 High ({len(high)}건)\n\n")
            parts.append("| Date | Fab | 이슈 | PR 번호 | Issued SW |\n")
            parts.append("|------|-----|------|---------|----------|\n")
            for item in high[:10]:
                parts.append(f"| {item['date']} | {item['fab']} | {item['issue']} | {item['pr']} | {item['issued_sw']} |\n")
            parts.append("\n")
        
        if normal:
            parts.append(f"### 🟡 Normal ({len(normal)}건)\n\n")
            parts.append("| Date | Fab | 이슈 | PR 번호 | Issued SW |\n")
            parts.append("|------|-----|------|---------|----------|\n")
            for item in normal[:10]:
                parts.append(f"| {item['date']} | {item['fab']} | {item['issue']} | {item['pr']} | {item['issued_sw']} |\n")
            parts.append("\n")
        
        parts.append(f"### 📊 요약\n")
        parts.append(f"- 총 대기 이슈: **{len(waiting_issues)}건**\n")
        parts.append(f"- Critical: **{len(critical)}건**, High: **{len(high)}건**, Normal: **{len(normal)}건**\n\n")
        parts.append(f"특정 이슈에 대해 더 알고 싶으시면 말씀해주세요! 🙋\n")
        
        return parts
    
    def _analyze_upgrades(self, query: str, docs: List[Dict]) -> List[str]:
        """업그레이드 현황 분석"""
        import re
        parts = [f"## 🚀 SW 업그레이드 현황\n\n"]
        parts.append(f"안녕하세요! SW 업그레이드 현황을 분석해 드릴게요 😊\n\n")
        
        upgrades = []
        for doc in docs:
            content = doc.get('content', '')
            from_match = re.search(r'Software Version From:\s*([^\|]+)', content)
            to_match = re.search(r'Software Version To:\s*([^\|]+)', content)
            status_match = re.search(r'FIF Status:\s*([^\|]+)', content)
            product_match = re.search(r'Product Name:\s*([^\|]+)', content)
            fab_match = re.search(r'Fab:\s*([^\|]+)', content)
            reason_match = re.search(r'Reason For\s*Upgrade:\s*([^\|]+)', content)
            
            if from_match or to_match:
                upgrades.append({
                    'from': from_match.group(1).strip()[:25] if from_match else "N/A",
                    'to': to_match.group(1).strip()[:25] if to_match else "N/A",
                    'status': status_match.group(1).strip() if status_match else "",
                    'product': product_match.group(1).strip()[:20] if product_match else "",
                    'fab': fab_match.group(1).strip()[:15] if fab_match else "",
                    'reason': reason_match.group(1).strip()[:40] if reason_match else ""
                })
        
        if upgrades:
            # 상태별 분류
            completed = [u for u in upgrades if 'Completed' in u['status']]
            failed = [u for u in upgrades if 'Failed' in u['status']]
            
            parts.append("### 📋 업그레이드 목록\n\n")
            parts.append("| Product | From | To | Status |\n")
            parts.append("|---------|------|----|---------|\n")
            for u in upgrades[:8]:
                status_icon = "✅" if 'Completed' in u['status'] else "❌" if 'Failed' in u['status'] else "⏳"
                parts.append(f"| {u['product']} | {u['from']} | {u['to']} | {status_icon} {u['status']} |\n")
            parts.append("\n")
            
            parts.append(f"### 📈 요약\n")
            parts.append(f"- 총 업그레이드: **{len(upgrades)}건**\n")
            parts.append(f"- 완료: **{len(completed)}건** ✅\n")
            parts.append(f"- 실패: **{len(failed)}건** ❌\n")
            if len(upgrades) > 0:
                success_rate = len(completed) / len(upgrades) * 100
                parts.append(f"- 성공률: **{success_rate:.1f}%**\n\n")
            parts.append(f"추가 질문이 있으시면 편하게 물어보세요! 💬\n")
        
        return parts
    
    def _analyze_status_distribution(self, query: str, docs: List[Dict]) -> List[str]:
        """상태 분포 분석"""
        import re
        from collections import Counter
        
        parts = [f"## 📊 상태 분포 분석\n\n"]
        parts.append(f"안녕하세요! 현재 이슈들의 상태 분포를 분석해 드릴게요 😊\n\n")
        
        statuses = []
        for doc in docs:
            content = doc.get('content', '')
            status_match = re.search(r'Current Status:\s*([^\|]+)', content)
            if status_match:
                statuses.append(status_match.group(1).strip())
        
        if statuses:
            counter = Counter(statuses)
            total = len(statuses)
            
            parts.append("| 상태 | 건수 | 비율 |\n")
            parts.append("|------|------|------|\n")
            for status, count in counter.most_common(10):
                pct = count / total * 100
                parts.append(f"| {status} | {count}건 | {pct:.1f}% |\n")
            parts.append(f"\n**총 {total}건** 분석됨\n\n")
            parts.append(f"특정 상태에 대해 더 알고 싶으시면 말씀해주세요! 🔍\n")
        
        return parts
    
    def _analyze_long_open_prs(self, query: str, docs: List[Dict]) -> List[str]:
        """오랫동안 고쳐지지 않는 PR들 분석"""
        import re
        from datetime import datetime
        
        parts = [f"## ⏳ 오랫동안 해결되지 않는 PR 분석\n\n"]
        parts.append(f"안녕하세요! 장기 미해결 PR들을 분석해 드릴게요 🔍\n\n")
        
        # 미해결 상태들
        unresolved_statuses = ['Waiting PR fix', 'Waiting Patch', 'No solution yet', 
                               'In Progress', 'Confirmed', 'In Review', 'Develop']
        
        today = datetime.now()
        long_open_prs = []
        
        for doc in docs:
            content = doc.get('content', '')
            
            # 상태 확인
            status_match = re.search(r'Current Status:\s*([^\|]+)', content)
            status = status_match.group(1).strip() if status_match else ""
            
            # 미해결 상태만 처리
            is_unresolved = any(s in status for s in unresolved_statuses)
            if not is_unresolved:
                continue
            
            # PR 번호 추출
            pr_match = re.search(r'PR[- ]?(\d+)', content)
            pr_number = pr_match.group(0) if pr_match else "N/A"
            
            # 날짜 추출
            date_match = re.search(r'Date reported:\s*(\d{1,2}/\d{1,2}/\d{4})', content)
            if date_match:
                try:
                    date_obj = datetime.strptime(date_match.group(1), '%m/%d/%Y')
                    days_open = (today - date_obj).days
                except:
                    days_open = 0
            else:
                days_open = 0
            
            # Issue 추출
            issue_match = re.search(r'Issue:\s*([^\|]+)', content)
            issue = issue_match.group(1).strip() if issue_match else ""
            
            # Fab 추출
            fab_match = re.search(r'Fab:\s*([^\|]+)', content)
            fab = fab_match.group(1).strip() if fab_match else ""
            
            # Priority 추출
            priority_match = re.search(r'Priority:\s*([^\|]+)', content)
            priority = priority_match.group(1).strip() if priority_match else "Normal"
            
            # Issued SW 추출
            issued_sw_match = re.search(r'Issued SW:\s*([^\|]+)', content)
            issued_sw = issued_sw_match.group(1).strip() if issued_sw_match else ""
            
            if days_open > 30:  # 30일 이상 오픈된 PR만
                long_open_prs.append({
                    'pr': pr_number,
                    'days': days_open,
                    'issue': issue[:80] if issue else "N/A",
                    'status': status,
                    'fab': fab,
                    'priority': priority,
                    'issued_sw': issued_sw
                })
        
        # 오래된 순으로 정렬
        long_open_prs.sort(key=lambda x: x['days'], reverse=True)
        
        if not long_open_prs:
            parts.append("✅ 30일 이상 오픈된 미해결 PR이 없습니다.\n")
            return parts
        
        # 통계
        critical = [p for p in long_open_prs if 'Critical' in p['priority'] or 'High' in p['priority']]
        over_90 = [p for p in long_open_prs if p['days'] > 90]
        over_180 = [p for p in long_open_prs if p['days'] > 180]
        
        parts.append(f"### 📊 요약 통계\n\n")
        parts.append(f"- 총 미해결 PR: **{len(long_open_prs)}건**\n")
        parts.append(f"- High/Critical 우선순위: **{len(critical)}건**\n")
        parts.append(f"- 90일 초과: **{len(over_90)}건**\n")
        parts.append(f"- 180일 초과: **{len(over_180)}건** ⚠️\n\n")
        
        # 테이블 형식으로 출력
        parts.append("### 📋 상세 목록 (오래된 순)\n\n")
        parts.append("| PR | 경과일 | 우선순위 | 상태 | Fab | Issue |\n")
        parts.append("|-----|--------|----------|------|-----|-------|\n")
        
        for pr in long_open_prs[:15]:  # 상위 15개만
            days_str = f"**{pr['days']}일**" if pr['days'] > 90 else f"{pr['days']}일"
            issue_short = pr['issue'][:40] + "..." if len(pr['issue']) > 40 else pr['issue']
            priority_icon = "🔴" if pr['priority'] in ['Critical', 'High'] else "🟡" if pr['priority'] == 'Normal' else "⚪"
            parts.append(f"| {pr['pr']} | {days_str} | {priority_icon} {pr['priority']} | {pr['status'][:15]} | {pr['fab'][:10]} | {issue_short} |\n")
        
        if len(long_open_prs) > 15:
            parts.append(f"\n*...외 {len(long_open_prs) - 15}건 더 있음*\n")
        
        # 권장 조치
        parts.append("\n### 💡 권장 조치\n\n")
        if over_180:
            parts.append(f"1. **180일 초과 PR ({len(over_180)}건)**: 즉시 검토 및 에스컬레이션 필요\n")
        if critical:
            parts.append(f"2. **High/Critical PR ({len(critical)}건)**: 우선적으로 리소스 할당 검토\n")
        parts.append("3. 장기 미해결 PR에 대한 정기 리뷰 미팅 권장\n\n")
        parts.append(f"더 궁금한 점이 있으시면 말씀해주세요! 언제든 도와드릴게요 😊\n")
        
        return parts
    
    def _analyze_fab_issues(self, query: str, docs: List[Dict]) -> List[str]:
        """특정 Fab 이슈 분석"""
        import re
        parts = [f"## 🏭 Fab별 이슈 분석\n\n"]
        parts.append(f"안녕하세요! Fab별 이슈 현황을 분석해 드릴게요 😊\n\n")
        
        fab_issues = {}
        for doc in docs:
            content = doc.get('content', '')
            fab_match = re.search(r'Fab:\s*([^\|]+)', content)
            issue_match = re.search(r'Issue:\s*([^\|]+)', content)
            status_match = re.search(r'Current Status:\s*([^\|]+)', content)
            priority_match = re.search(r'Priority:\s*([^\|]+)', content)
            issued_sw_match = re.search(r'Issued SW:\s*([^\|]+)', content)
            date_match = re.search(r'Date reported:\s*(\d{1,2}/\d{1,2}/\d{4})', content)
            
            if fab_match:
                fab = fab_match.group(1).strip()
                if fab not in fab_issues:
                    fab_issues[fab] = []
                fab_issues[fab].append({
                    'issue': issue_match.group(1).strip() if issue_match else "N/A",
                    'status': status_match.group(1).strip() if status_match else "",
                    'priority': priority_match.group(1).strip() if priority_match else "Normal",
                    'issued_sw': issued_sw_match.group(1).strip() if issued_sw_match else "",
                    'date': date_match.group(1) if date_match else ""
                })
        
        if not fab_issues:
            parts.append("😅 Fab 데이터를 찾지 못했어요. 다른 키워드로 검색해 보시겠어요?\n")
            return parts
        
        # 요약 통계
        parts.append("### 📊 Fab별 이슈 현황\n\n")
        parts.append("| Fab | 총 건수 | High/Critical | 미해결 |\n")
        parts.append("|-----|---------|---------------|--------|\n")
        
        sorted_fabs = sorted(fab_issues.items(), key=lambda x: len(x[1]), reverse=True)
        
        for fab, issues in sorted_fabs[:10]:
            high_count = len([i for i in issues if i['priority'] in ['High', 'Critical']])
            unresolved = len([i for i in issues if 'Waiting' in i['status'] or 'No solution' in i['status']])
            parts.append(f"| {fab[:15]} | {len(issues)}건 | {high_count}건 | {unresolved}건 |\n")
        
        parts.append("\n")
        
        # 상위 Fab별 상세 이슈
        for fab, issues in sorted_fabs[:5]:
            high_issues = [i for i in issues if i['priority'] in ['High', 'Critical']]
            unresolved = [i for i in issues if 'Waiting' in i['status'] or 'No solution' in i['status']]
            
            parts.append(f"### 🏭 {fab} ({len(issues)}건)\n\n")
            
            if high_issues:
                parts.append(f"**🔴 High/Critical ({len(high_issues)}건):**\n")
                for i, item in enumerate(high_issues[:3], 1):
                    issue_short = item['issue'][:60] + "..." if len(item['issue']) > 60 else item['issue']
                    parts.append(f"- {issue_short} [{item['status'][:15]}]\n")
                parts.append("\n")
            
            if unresolved:
                parts.append(f"**⏳ 미해결 ({len(unresolved)}건):**\n")
                for i, item in enumerate(unresolved[:3], 1):
                    issue_short = item['issue'][:60] + "..." if len(item['issue']) > 60 else item['issue']
                    parts.append(f"- {issue_short} [{item['status'][:15]}]\n")
                parts.append("\n")
        
        parts.append(f"특정 Fab에 대해 더 자세히 알고 싶으시면 물어봐 주세요! 🙌\n")
        
        return parts
    
    def _general_analysis(self, query: str, docs: List[Dict]) -> List[str]:
        """일반 검색 결과 분석"""
        import re
        parts = [f"## 📊 '{query}' 검색 결과\n\n"]
        parts.append(f"안녕하세요! 요청하신 내용과 관련된 데이터 **{len(docs)}건**을 찾았어요! 😊\n\n")
        
        # 소스별로 그룹화
        by_source = {}
        for doc in docs:
            source = doc.get('source', 'Unknown')
            if source not in by_source:
                by_source[source] = []
            by_source[source].append(doc)
        
        for source, source_docs in by_source.items():
            parts.append(f"### 📁 {source} ({len(source_docs)}건)\n\n")
            for i, doc in enumerate(source_docs[:4], 1):
                content = doc.get('content', '')
                key_info = self._extract_key_info(content)
                similarity = doc.get('similarity', 0)
                parts.append(f"{i}. {key_info} *(유사도: {similarity:.1%})*\n\n")
        
        parts.append(f"더 자세한 정보가 필요하시면 말씀해주세요! 도와드릴게요 😊\n")
        
        return parts
    
    def _extract_key_info(self, content: str) -> str:
        """콘텐츠에서 주요 정보만 추출"""
        import re
        
        # 주요 필드들
        fields = {}
        for field in ['Issue', 'Current Status', 'Issued SW', 'Fixed SW', 'Fab', 'Module Type', 
                      'Software Version From', 'Software Version To', 'FIF Status', 'Product Name']:
            match = re.search(rf'{field}:\s*([^\|]+)', content)
            if match:
                val = match.group(1).strip()
                if val and val != 'nan':
                    fields[field] = val[:60]
        
        if fields:
            parts = []
            if 'Issue' in fields:
                parts.append(f"**{fields['Issue'][:50]}**")
            if 'Current Status' in fields:
                parts.append(f"[{fields['Current Status']}]")
            if 'Fixed SW' in fields:
                parts.append(f"Fixed: {fields['Fixed SW']}")
            elif 'Software Version To' in fields:
                parts.append(f"Version: {fields['Software Version To']}")
            if 'Fab' in fields:
                parts.append(f"({fields['Fab']})")
            return " | ".join(parts) if parts else content[:150]
        
        return content[:150]
    
    def _detect_query_mode(self, query: str) -> str:
        """
        쿼리 의도 분석: 검색 모드 vs 설명 모드
        Returns: 'search' | 'explain' | 'general'
        """
        query_lower = query.lower().strip()
        
        # 설명/알려줘 모드 키워드 (LLM이 설명 생성) - 영어 키워드 우선 체크
        explain_keywords = [
            # 영어 (우선순위 높음 - 먼저 매칭)
            'explain', 'what is', 'what are', 'how to', 'how does', 'why',
            'tell me about', 'describe', 'definition', 'meaning', 'method',
            'want to know', 'need to know', 'understand', 'learn about',
            'difference between', 'compare', 'pros and cons', 'cause', 'about',
            # 한국어
            '설명', '알려줘', '알려 줘', '알고싶', '알고 싶', '무엇', '뭐야', '뭔가요',
            '어떻게', '왜', '이유', '원리', '개념', '정의', '의미', '방법', '하는법',
            '사용법', '활용', '기능', '특징', '차이', '비교', '장단점', '원인'
        ]
        
        # 검색/찾기 모드 키워드 (데이터 검색 결과 표시)
        search_keywords = [
            # 한국어
            '찾아', '찾아줘', '찾아 줘', '검색', '조사', '조사해', '조사해줘',
            '보여줘', '보여 줘', '목록', '리스트', '현황', '상태', '통계',
            '몇개', '몇 개', '개수', '건수', '어디', '언제', '누가',
            # 영어
            'find', 'search', 'look for', 'investigate', 'show', 'list',
            'status', 'count', 'how many', 'where', 'when', 'who'
        ]
        
        # 먼저 설명 모드 체크 (우선순위 높음)
        for keyword in explain_keywords:
            if keyword in query_lower:
                print(f"🎯 Query mode: EXPLAIN (matched: '{keyword}')")
                return 'explain'
        
        # 검색 모드 체크
        for keyword in search_keywords:
            if keyword in query_lower:
                print(f"🔍 Query mode: SEARCH (matched: '{keyword}')")
                return 'search'
        
        # 기본값: 일반 모드 (검색 후 LLM 분석)
        print(f"📊 Query mode: GENERAL")
        return 'general'
    
    def _extract_topic_from_query(self, query: str) -> str:
        """쿼리에서 주제어 추출 (검색/설명 키워드 제거)"""
        import re
        
        # 제거할 패턴들
        remove_patterns = [
            r'설명해\s*줘?', r'알려\s*줘?', r'알고\s*싶어?', r'찾아\s*줘?',
            r'검색해?\s*줘?', r'조사해?\s*줘?', r'보여\s*줘?', r'관련',
            r'에\s*대해', r'이?란', r'무엇', r'뭐야', r'어떻게',
            r'explain', r'what\s+is', r'tell\s+me\s+about', r'find',
            r'search', r'show\s+me', r'related\s+to', r'about'
        ]
        
        topic = query
        for pattern in remove_patterns:
            topic = re.sub(pattern, '', topic, flags=re.IGNORECASE)
        
        # 공백 정리
        topic = ' '.join(topic.split()).strip()
        return topic if topic else query
    
    def rag_query(self, query: str, top_k: int = 20) -> str:
        """
        RAG 파이프라인 실행: 검색 + 응답 생성
        기본 top_k=20으로 더 많은 결과 분석
        """
        # 일상 대화/인사말 처리
        greeting_response = self._check_greeting(query)
        if greeting_response:
            return greeting_response
        
        # PR 번호 검색 패턴 감지 (PR-XXXXXX 또는 6자리 숫자)
        pr_result = self._check_pr_query(query)
        if pr_result:
            return pr_result
        
        if not self.initialized:
            # 자동 인덱싱 시도
            print("🔄 Index not found, starting automatic indexing...")
            if not self.load_and_index_data():
                return "❌ 데이터 인덱싱에 실패했습니다. 데이터 파일을 확인해 주세요."
        
        # 쿼리 모드 감지
        query_mode = self._detect_query_mode(query)
        
        # 검색 실행
        search_results = self.search(query, top_k=top_k)
        
        if not search_results:
            return f"'{query}'에 대한 관련 데이터를 찾을 수 없습니다."
        
        # 모드에 따른 응답 생성
        if query_mode == 'explain':
            # 설명 모드: LLM을 사용하여 상세 설명 생성
            # LLM 연결 재시도
            if not self.ollama_available and not self.gguf_available:
                self._check_ollama()
            
            response = self._generate_explanation(query, search_results)
        elif query_mode == 'search':
            # 검색 모드: 검색 결과만 표시 (fallback 응답 사용)
            response = self._fallback_response(query, search_results)
        else:
            # 일반 모드: LLM 사용 가능하면 사용, 없으면 fallback
            response = self.generate_response(query, search_results)
        
        return response
    
    def _check_greeting(self, query: str) -> Optional[str]:
        """인사말 및 일상 대화 처리 (한글/영어 동시 지원)"""
        query_lower = query.lower().strip()
        
        # 인사말 패턴 (한글 + 영어 동시 응답)
        greetings = {
            # 한국어 인사
            '안녕': '안녕하세요! 👋 저는 K-Bot AI 어시스턴트입니다.\nHello! I\'m K-Bot AI Assistant.\n\n무엇이든 물어보세요! Ask me anything!\n• PR 검색 (예: "PR-187159")\n• 장비 현황 (예: "5ELVD701 현황")\n• 이슈 분석 (예: "Bias RF 관련 PR")',
            '안녕하세요': '안녕하세요! 👋 K-Bot입니다.\nHello! I\'m K-Bot.\n\n무엇을 도와드릴까요? How can I help you?',
            'ㅎㅇ': '안녕하세요! 👋 K-Bot입니다. 무엇이든 물어보세요!\nHey! K-Bot here. Ask me anything!',
            '하이': '안녕하세요! 👋\nHi there! How can I assist you today?',
            '헬로': '안녕하세요! 👋 K-Bot입니다.\nHello! I\'m K-Bot. What do you need?',
            # 영어 인사
            'hello': 'Hello! 👋 I\'m K-Bot AI Assistant.\n안녕하세요! K-Bot AI 어시스턴트입니다.\n\nHow can I help you? 무엇을 도와드릴까요?',
            'hi': 'Hi! 👋 I\'m K-Bot.\n안녕하세요! K-Bot입니다.\n\nWhat can I do for you?',
            'hey': 'Hey! 👋 K-Bot here.\n안녕하세요! K-Bot입니다.\n\nHow can I assist you?',
            # 감사
            '고마워': '천만에요! 😊 더 궁금한 점이 있으면 언제든 물어보세요.\nYou\'re welcome! Feel free to ask more questions.',
            '감사': '감사합니다! 도움이 되었다니 기쁩니다. 😊\nThank you! Glad I could help.',
            '감사합니다': '천만에요! 😊 언제든 다시 물어보세요.\nYou\'re welcome! Ask me anytime.',
            'thanks': 'You\'re welcome! 😊\n천만에요! 더 필요한 게 있으면 말씀하세요.',
            'thank you': 'You\'re welcome! Happy to help. 😊\n도움이 되었다니 기쁩니다!',
            # 자기소개
            '뭐해': '저는 SW Release Notes, 장비 데이터, 이슈 트래킹을 분석해요. 🔍\nI analyze SW Release Notes, equipment data, and issue tracking.\n\n무엇이 궁금하신가요? What would you like to know?',
            '뭐야': '저는 K-Bot, TF-IDF + Llama3.2 기반 AI 어시스턴트예요! 🤖\nI\'m K-Bot, an AI assistant powered by TF-IDF + Llama3.2!\n\nSWRN, 장비 현황, 이슈 등을 검색하고 분석해 드립니다.',
            '누구': '저는 K-Bot AI 어시스턴트입니다! 🤖\nI\'m K-Bot AI Assistant!\n\nPowered by TF-IDF search + Llama3.2-3B LLM',
            'who are you': 'I\'m K-Bot, an AI assistant! 🤖\n저는 K-Bot AI 어시스턴트입니다!\n\nPowered by TF-IDF + Llama3.2-3B, I help you explore SW data.',
        }
        
        # 정확히 일치하는 인사말 확인
        for greeting, response in greetings.items():
            if query_lower == greeting or query_lower.startswith(greeting + ' ') or query_lower.endswith(' ' + greeting):
                return response
        
        # "분석", "할 수 있어", "기능", "뭘 해", "what can you do" 등의 질문 처리
        capability_keywords_kr = ['분석', '할 수 있', '뭘 해', '뭐 해', '뭘해', '뭐해', '기능', '뭘 할', '뭐 할']
        capability_keywords_en = ['what can you', 'what do you', 'capabilities', 'can you do', 'help me with', 'able to']
        
        # PR 분석 관련 키워드가 있으면 capability 응답 건너뛰기 (실제 분석 수행)
        pr_analysis_keywords = ['pr', '피알', 'open', 'waiting', '장기', '만성', 'chronic', 'insight', '인사이트']
        has_pr_keyword = any(kw in query_lower for kw in pr_analysis_keywords)
        
        if not has_pr_keyword and (any(kw in query_lower for kw in capability_keywords_kr) or any(kw in query_lower for kw in capability_keywords_en)):
            return """🤖 **K-Bot Capabilities / K-Bot이 할 수 있는 것들**

Hey there! I'm your curious companion for all things SW! 🚀
안녕하세요! SW에 관한 모든 것을 도와드리는 K-Bot입니다! 

**📋 PR Search / PR 검색**
• "PR-187159" → Get detailed release notes / 릴리즈 노트 상세 정보
• "192338 what's this?" → Quick PR lookup / PR 빠른 조회
• "Bias RF 관련 PR 찾아줘" → Keyword-based PR search / 키워드 기반 PR 검색

**🔧 Equipment Info / 장비 정보**
• "ELPC61 현황" → Equipment analysis / 장비 분석
• "PM chamber issues" → Related issues / 관련 이슈

**📊 Open PR Insights / Open PR 분석** ⭐NEW
• "Waiting PR 분석" → Find similar past PRs for Waiting PRs / 대기중 PR 유사 분석
• "장기 Open PR 분석" → Analyze long-open chronic PRs / 장기 미해결 PR 분석
• "Open PR 인사이트" → SWRN insights for open issues / 열린 이슈 인사이트

**🔍 Smart Search / 스마트 검색**
• Just type a 6-digit number for instant PR search! / 6자리 숫자만 입력하면 즉시 PR 검색!

💡 *Tip: I understand both Korean and English!*
💡 *팁: 한글과 영어 모두 이해해요!*

What would you like to explore? 무엇이 궁금하신가요? 🎯"""
        
        # 도움말 요청
        help_keywords = ['도움', 'help', '사용법', '어떻게', '기능', 'how to', 'guide']
        if any(kw in query_lower for kw in help_keywords):
            return """🤖 **K-Bot AI Assistant Help / 도움말**

I can help you with the following / 다음을 도와드릴 수 있습니다:

**📋 PR Search / PR 검색**
• "PR-187159 알려줘" / "Tell me about PR-187159"
• Just type 6-digit PR number / 6자리 PR 번호만 입력
• "Valve 관련 PR 찾아줘" / "Find PRs about Valve"

**🔧 Equipment / 장비**
• "ELPC61 장비 현황" / "ELPC61 equipment status"
• "PM chamber issues" / "PM chamber 이슈"

**📊 Open PR Analysis / Open PR 분석** ⭐NEW
• "Waiting PR 분석" / "Analyze Waiting PRs"
• "장기 Open PR 분석" / "Analyze chronic open PRs"
• "Open PR 인사이트" / "Open PR insights"

**💬 I speak both Korean & English!**
**한글과 영어 모두 지원합니다!**

What do you need? 무엇이 필요하신가요? 🎯"""
        
        return None
    
    def _get_previous_version(self, version: str) -> str:
        """
        주어진 버전의 이전 버전을 찾습니다.
        예: SP33-HF16 -> SP33-HF15, SP33-HF1 -> SP33-Release
        """
        import re
        
        # 버전 파싱: 1.8.4-SP33-HF16
        match = re.match(r'1\.8\.4-(SP\d+)-(HF(\d+)([a-z]?)|B(\d+)([a-z]?)|RELEASE)', version, re.IGNORECASE)
        if not match:
            return version
        
        sp_part = match.group(1).upper()  # SP33
        suffix_type = match.group(2).upper()  # HF16 or B1 or RELEASE
        
        # HF 버전인 경우
        if suffix_type.startswith('HF'):
            hf_num_match = re.match(r'HF(\d+)([a-z]?)', suffix_type, re.IGNORECASE)
            if hf_num_match:
                hf_num = int(hf_num_match.group(1))
                hf_letter = hf_num_match.group(2) or ''
                
                if hf_letter:
                    # HF9e -> HF9d, HF9a -> HF9
                    if hf_letter.lower() == 'a':
                        return f"1.8.4-{sp_part}-HF{hf_num}"
                    else:
                        prev_letter = chr(ord(hf_letter.lower()) - 1)
                        return f"1.8.4-{sp_part}-HF{hf_num}{prev_letter}"
                elif hf_num > 1:
                    return f"1.8.4-{sp_part}-HF{hf_num - 1}"
                else:
                    # HF1 -> Release
                    return f"1.8.4-{sp_part}-RELEASE"
        
        # B 버전인 경우
        elif suffix_type.startswith('B'):
            b_num_match = re.match(r'B(\d+)([a-z]?)', suffix_type, re.IGNORECASE)
            if b_num_match:
                b_num = int(b_num_match.group(1))
                if b_num > 1:
                    return f"1.8.4-{sp_part}-B{b_num - 1}"
                else:
                    return f"1.8.4-{sp_part}-RELEASE"
        
        # Release인 경우: 이전 SP 버전
        elif suffix_type == 'RELEASE':
            sp_num_match = re.match(r'SP(\d+)', sp_part, re.IGNORECASE)
            if sp_num_match:
                sp_num = int(sp_num_match.group(1))
                if sp_num > 1:
                    return f"1.8.4-SP{sp_num - 1}-RELEASE"
        
        return version
    
    def _check_version_range_query(self, query: str) -> Optional[str]:
        """
        버전 범위 검색 쿼리인지 확인
        예: "1.8.4-SP33-HF9e와 1.8.4-SP33-HF16 사이에 추가된 PR들을 찾아줘"
            "SP33-HF9와 SP33-HF16 사이 PR"
            "SP30-HF9과 SP33-HF16의 PR 찾아줘"
            "SP33-HF16에 추가된 PR을 알려줘" (단일 버전도 지원)
            "between SP33-HF9e and SP33-HF16"
            "what changed from SP30-HF9 to SP33-HF16"
            "PR changes SP30-HF9 ~ SP33-HF16"
        """
        import re
        
        query_lower = query.lower().strip()
        
        # 버전 범위 관련 키워드 확인 (한글 + 영어 다양한 표현)
        range_keywords = [
            # Korean keywords
            '사이', '간', '차이', '추가', '부터', '에서', '까지', '와', '과', '의 pr', '의pr',
            'pr을', 'pr 을', 'pr을 알려', 'pr 알려', 'pr이', 'pr 이',
            # English keywords - conjunctions & prepositions
            'between', 'from', 'to', 'and', 'through', 'thru', '~', '-',
            # English keywords - actions & nouns  
            'delta', 'diff', 'difference', 'changes', 'change', 'changed',
            'added', 'new', 'updated', 'modified', 'released',
            # English keywords - questions
            'what', 'which', 'list', 'show', 'find', 'get', 'compare',
            # Common phrases
            'pr list', 'prs', 'release notes', 'releases'
        ]
        has_range_keyword = any(kw in query_lower for kw in range_keywords)
        
        # 버전 패턴 매칭 (타이포 지원: P33 → SP33, HG16 → HF16)
        # 먼저 쿼리에서 타이포 정규화
        normalized_query = query
        # P33 → SP33 (S가 빠진 경우)
        normalized_query = re.sub(r'\b([Pp])(\d+)', r'SP\2', normalized_query)
        # HG → HF (키보드 타이포: G와 F가 가깝다)
        normalized_query = re.sub(r'([Hh])([Gg])(\d+)', r'\1F\3', normalized_query)
        
        version_pattern = r'(?:1\.8\.4[- ]?)?(SP\d+)(?:[- ]?(HF\d+[a-z]?|B\d+[a-z]?|Release))?'
        matches = re.findall(version_pattern, normalized_query, re.IGNORECASE)
        
        if len(matches) >= 2:
            has_range_keyword = True  # 두 버전이 있으면 range로 인식
        
        if not has_range_keyword:
            return None
        
        # 버전이 없으면 처리 불가
        if len(matches) < 1:
            return None
        
        # 첫 번째와 두 번째 버전 추출
        def build_version(match):
            sp_part = match[0].upper()
            suffix = match[1].upper() if match[1] else "RELEASE"
            # suffix 정규화: HF9 -> HF9, B1 -> B1 등
            if suffix and not suffix.endswith('-RELEASE'):
                suffix = suffix.replace('RELEASE', '').strip('-')
            if not suffix or suffix == '':
                suffix = "RELEASE"
            return f"1.8.4-{sp_part}-{suffix}"
        
        # 단일 버전인 경우: 이전 버전과 해당 버전 사이의 PR 검색
        if len(matches) == 1:
            version_to = build_version(matches[0])
            # 이전 버전 자동 계산
            version_from = self._get_previous_version(version_to)
            print(f"🔍 Single version query detected: {version_to} (comparing with {version_from})")
        else:
            version_from = build_version(matches[0])
            version_to = build_version(matches[1])
            print(f"🔍 Version range detected: {version_from} → {version_to}")
        
        # SWRN 인덱서에서 버전 범위 검색
        try:
            from swrn_indexer import SWRNIndexer
            indexer = SWRNIndexer()
            
            result = indexer.get_prs_between_versions(version_from, version_to)
            
            if "error" in result:
                return f"⚠️ {result['error']}"
            
            # 결과 포맷팅 (Delta Summary 스타일)
            prs = result.get("prs", [])
            versions_included = result.get("versions_included", [])
            total_new = result.get("total_new_prs", 0)
            summary = result.get("summary", {})
            
            # Delta Summary 스타일 HTML 생성
            html = self._generate_delta_summary_html(result, prs, versions_included, summary)
            
            return html
            
        except Exception as e:
            print(f"⚠️ Version range search error: {e}")
            import traceback
            traceback.print_exc()
            return f"⚠️ 버전 범위 검색 중 오류가 발생했습니다: {str(e)}"
    
    def _generate_delta_summary_html(self, result: Dict, prs: List, versions_included: List, summary: Dict) -> str:
        """
        Delta Summary 스타일 HTML 생성 (JavaScript 없이 순수 HTML)
        K-Bot 채팅창에서는 JavaScript가 실행되지 않으므로 HTML만 사용
        - 줄바꿈 없이 한 줄로 압축 (빈 줄 방지)
        - 짙은 민트색 그라데이션 배경
        """
        total_prs = result.get("total_prs", len(prs))  # 전체 PR 수
        total_new = result.get("total_new_prs", 0)     # 새로 추가된 PR 수
        from_version = result.get("from_version", "")
        to_version = result.get("to_version", "")
        
        # Type별 통계 - pr_type 기반 분류
        # feature -> Features, bug_fix/unknown -> Bugs
        features_count = 0
        for pr in prs:
            pr_type = pr.get('pr_type', '').lower()
            title = (pr.get('title', '') or pr.get('context', '') or '').lower()
            # feature이거나 title에 feature 키워드가 있으면 Features로 분류
            if pr_type == 'feature' or any(kw in title for kw in ['added ', 'enhanced ', 'improved ', 'support for ', 'new ', 'update ', 'enable']):
                features_count += 1
        bugs_count = total_prs - features_count
        
        # Version별 통계
        by_version = summary.get("by_version", {})
        
        # 버전별 테이블 행 생성
        version_rows = ""
        for version in versions_included:
            pr_count = len(by_version.get(version, []))
            if pr_count > 0:
                clean_version = version.replace('_ReleaseNotes', '')
                version_rows += f'<tr><td style="padding:4px 8px;border:1px solid #ddd">{clean_version}</td><td style="padding:4px 8px;border:1px solid #ddd;font-weight:bold;color:#00897b">{pr_count}</td></tr>'
        
        # PR 테이블 생성 (최대 30개, 나머지는 요약)
        pr_rows = ""
        display_count = min(30, len(prs))
        for i, pr in enumerate(prs[:display_count]):
            pr_num = pr.get('pr_number', '')
            pr_link = f'https://iplmprd.fremont.lamrc.net/3dspace/goto/o/LRC+Problem+Report/{pr_num}/'
            # Component: module에서 추출하거나 title에서 추론
            component = pr.get('component', '') or ''
            module = pr.get('module', '') or ''
            title = pr.get('title', '') or pr.get('context', '') or ''
            affected = pr.get('affected_function', '') or ''
            
            # Component가 비어있으면 module 또는 title에서 추출
            if not component and module:
                # Module이 Component 역할을 할 수 있음 (예: Sense.i, ALD 등)
                known_components = ['Sense.i', 'ALD', 'Bevel', 'FA', 'Kiyo', 'SP203', 'All', 'CVD', 'Etch', 'Deposition']
                for kc in known_components:
                    if kc.lower() in module.lower() or kc.lower() in title.lower():
                        component = kc
                        break
                if not component:
                    component = module  # module을 component로 사용
            
            # 값 자르기
            component_display = component[:25] if component else '-'
            module_display = module[:20] if module else '-'
            title_display = title[:40] if title else '-'
            affected_display = affected[:25] if affected else '-'
            version = (pr.get('sw_version', '') or '-').replace('_ReleaseNotes', '')
            
            # Type 결정 (title 키워드 기반)
            pr_type = pr.get('pr_type', 'unknown').lower()
            title_lower = title.lower()
            if pr_type == 'new_feature' or any(kw in title_lower for kw in ['added ', 'enhanced ', 'improved ', 'support for ', 'new ', 'update ', 'enable']):
                type_label = '🆕'
                type_text = 'Feature'
            else:
                type_label = '🔧'
                type_text = 'Bug Fix'
            
            pr_rows += f'<tr style="border-bottom:1px solid #eee"><td style="padding:5px"><a href="{pr_link}" target="_blank" style="color:#00897b;font-weight:bold;text-decoration:none">{pr_num}</a></td><td style="padding:5px" title="{component}">{component_display}</td><td style="padding:5px" title="{module}">{module_display}</td><td style="padding:5px" title="{title}">{title_display}</td><td style="padding:5px" title="{affected}">{affected_display}</td><td style="padding:5px">{version}</td><td style="padding:5px">{type_label}</td></tr>'
        
        # CSV 데이터 생성 (Base64 인코딩으로 다운로드 링크 생성)
        import base64
        csv_lines = ['PR Number,Component,Module,Feature/Issue,Affected Function,Fixed Version,Type']
        for pr in prs:
            pr_num = pr.get('pr_number', '')
            component = pr.get('component', '') or pr.get('module', '') or ''
            module = pr.get('module', '') or ''
            title = pr.get('title', '') or pr.get('context', '') or ''
            affected = pr.get('affected_function', '') or ''
            version = (pr.get('sw_version', '') or '').replace('_ReleaseNotes', '')
            pr_type = pr.get('pr_type', 'unknown').lower()
            title_lower = title.lower()
            if pr_type == 'new_feature' or any(kw in title_lower for kw in ['added ', 'enhanced ', 'improved ', 'support for ', 'new ', 'update ', 'enable']):
                type_text = 'Feature'
            else:
                type_text = 'Bug Fix'
            # CSV 이스케이프
            component = component.replace('"', '""')
            module = module.replace('"', '""')
            title = title.replace('"', '""')
            affected = affected.replace('"', '""')
            csv_lines.append(f'{pr_num},"{component}","{module}","{title}","{affected}",{version},{type_text}')
        csv_content = '\n'.join(csv_lines)
        csv_b64 = base64.b64encode(csv_content.encode('utf-8')).decode('utf-8')
        csv_filename = f'Delta_PRs_{from_version}_to_{to_version}.csv'
        
        # 모든 HTML을 한 줄로 압축 (줄바꿈 없음 -> 빈 줄 방지)
        html = f'<div style="font-family:Segoe UI,Arial,sans-serif;max-width:100%">'
        # 헤더 - 짙은 민트색 그라데이션
        html += f'<div style="background:linear-gradient(135deg,#00695c,#00897b,#26a69a);color:#fff;padding:15px;border-radius:8px 8px 0 0">'
        html += f'<h2 style="margin:0 0 8px 0;font-size:1.3em">📊 Delta Summary</h2>'
        html += f'<div style="display:flex;flex-wrap:wrap;gap:10px 20px">'
        html += f'<span><b>Base:</b> {from_version}</span>'
        html += f'<span><b>Target:</b> {to_version}</span>'
        html += f'<span><b>Versions:</b> {len(versions_included)}</span>'
        html += f'<span><b>Total PRs:</b> <strong style="font-size:1.1em">{total_prs}</strong></span>'
        if total_new != total_prs:
            html += f'<span><b>New:</b> <strong style="font-size:1.1em;color:#81c784">{total_new}</strong></span>'
        html += f'</div></div>'
        # 본문
        html += f'<div style="background:#f0f9f7;border:1px solid #b2dfdb;border-top:none;padding:12px;border-radius:0 0 8px 8px">'
        # Type Summary 테이블
        html += f'<table style="width:100%;border-collapse:collapse;margin-bottom:10px;background:#fff;border-radius:4px;overflow:hidden">'
        html += f'<tr><th style="background:#00897b;color:#fff;padding:8px;text-align:center">Features 🆕</th><th style="background:#00897b;color:#fff;padding:8px;text-align:center">Bug Fixes 🔧</th></tr>'
        html += f'<tr><td style="padding:10px;text-align:center;font-size:1.4em;font-weight:bold;color:#2e7d32">{features_count}</td><td style="padding:10px;text-align:center;font-size:1.4em;font-weight:bold;color:#c62828">{bugs_count}</td></tr>'
        html += f'</table>'
        # PRs by Version 테이블
        html += f'<details style="margin-bottom:10px"><summary style="cursor:pointer;font-weight:bold;color:#00695c;padding:5px">📦 PRs by Version (click to expand)</summary>'
        html += f'<table style="width:100%;border-collapse:collapse;background:#fff;margin-top:5px">'
        html += f'<tr><th style="background:#00897b;color:#fff;padding:6px;text-align:left">Version</th><th style="background:#00897b;color:#fff;padding:6px;text-align:left">Count</th></tr>'
        html += version_rows
        html += f'</table></details>'
        # Download 버튼
        html += f'<div style="margin:10px 0"><a href="data:text/csv;base64,{csv_b64}" download="{csv_filename}" style="display:inline-block;background:linear-gradient(135deg,#2e7d32,#43a047);color:#fff;padding:10px 20px;border-radius:20px;text-decoration:none;font-weight:bold;box-shadow:0 2px 5px rgba(0,0,0,0.2)">📥 Download CSV ({total_prs} PRs)</a></div>'
        # PR List 테이블
        html += f'<div style="overflow-x:auto"><table style="width:100%;border-collapse:collapse;font-size:0.85em;background:#fff">'
        html += f'<thead><tr style="background:#00695c;color:#fff"><th style="padding:6px;text-align:left">PR#</th><th style="padding:6px;text-align:left">Component</th><th style="padding:6px;text-align:left">Module</th><th style="padding:6px;text-align:left">Feature/Issue</th><th style="padding:6px;text-align:left">Affected</th><th style="padding:6px;text-align:left">Version</th><th style="padding:6px;text-align:center">Type</th></tr></thead>'
        html += f'<tbody>{pr_rows}</tbody></table></div>'
        if total_prs > display_count:
            html += f'<p style="color:#666;font-size:0.85em;margin:8px 0 0 0">⚠️ {total_prs - display_count}개 더 있습니다. 전체 목록은 CSV 다운로드를 이용해주세요.</p>'
        html += f'</div></div>'
        
        return html

    def _check_pr_query(self, query: str) -> Optional[str]:
        """
        PR 번호 관련 쿼리인지 확인하고 SWRN SQLite 인덱스에서 검색
        (SQLite FTS5 기반 - 밀리초 단위 검색)
        키워드 기반 PR 검색도 지원: "Bias RF 관련 PR 찾아줘"
        유사 PR 검색 지원: "Open PR 인사이트", "Waiting PR 분석"
        버전 범위 검색 지원: "SP33-HF9e와 SP33-HF16 사이 PR 찾아줘"
        """
        import re
        
        query_lower = query.lower().strip()
        
        # ★★★ 버전 범위 검색 패턴 감지 (최우선) ★★★
        version_range_result = self._check_version_range_query(query)
        if version_range_result:
            return version_range_result
        
        # ★ 검색 관련 키워드가 있으면 explain 스킵하지 않음
        search_action_keywords = ['find', 'search', 'look for', 'show', 'list', 'related to', 
                                   '찾아', '검색', '조사', '보여', '관련', 'pr']
        is_search_query = any(kw in query_lower for kw in search_action_keywords)
        
        # ★ explain 키워드가 있고 검색 쿼리가 아니면 설명 모드로 가도록 조기 반환
        if not is_search_query:
            explain_skip_keywords = [
                'explain', 'what is', 'what are', 'how to', 'how does', 'why',
                'tell me about', 'describe', 'definition', 'meaning',
                '설명', '알려줘', '알려 줘', '무엇', '뭐야', '어떻게', '왜'
            ]
            for kw in explain_skip_keywords:
                if kw in query_lower:
                    return None  # 설명 모드로 전환
        
        # ★★★ 세 가지 PR 분석 유형 분리 ★★★
        # 1. "Open PR 인사이트" → SWRN에서 유사 Fixed 사례 검색
        # 2. "Waiting/Open PR 분석" → 30일+ 대기 PR 테이블
        # 3. "장기 Open PR 분석" → 60일+ 장기 PR 테이블
        
        # 1. Open PR 인사이트 (SWRN Fixed 사례 검색) - "인사이트", "insight" 키워드
        insight_patterns = [
            r'(open|waiting)?\s*PR\s*(인사이트|insight)',
            r'(인사이트|insight)\s*.*?(open|waiting)?\s*PR',
            r'^open\s*PR\s*인사이트$',
        ]
        for pattern in insight_patterns:
            if re.search(pattern, query, re.IGNORECASE):
                return self._get_open_pr_insights(query)
        
        # 2. 장기 Open PR 분석 (60일+) - "장기", "chronic", "만성" 키워드
        chronic_patterns = [
            r'(장기|chronic|만성|오래된|long)\s*(open)?\s*PR\s*(분석|analysis)?',
            r'(장기|chronic|만성)\s*PR',
        ]
        for pattern in chronic_patterns:
            if re.search(pattern, query, re.IGNORECASE):
                return self._analyze_open_prs_local(is_chronic=True, is_waiting=False)
        
        # 3. Waiting/Open PR 분석 (30일+) - "waiting", "분석" 키워드 (인사이트 제외)
        waiting_patterns = [
            r'(waiting|대기|open)\s*(\/|or)?\s*(open)?\s*PR\s*분석',
            r'PR\s*분석$',
            r'^waiting\s*PR',
        ]
        for pattern in waiting_patterns:
            if re.search(pattern, query, re.IGNORECASE):
                return self._analyze_open_prs_local(is_chronic=False, is_waiting=True)
        
        # 키워드 기반 PR 검색 패턴 감지 (PR 번호 검색보다 먼저 체크)
        # ★★★ 다양한 한국어/영어 표현 지원 ★★★
        keyword_search_patterns = [
            # 한국어 패턴 (더 유연하게 - 조사 포함)
            r'(.+?)\s*(?:와\s*|에\s*)?관련(?:된|)\s*(?:PR|피알|이슈)(?:를|을)?\s*(?:찾아|검색|보여)?',  # "Bias RF 와 관련된 PR을 찾아줘"
            r'(.+?)\s*(?:에\s*)?(?:대한|관한)\s*(?:PR|피알)(?:를|을)?\s*(?:찾아|검색)?',  # "Bias RF에 대한 PR 찾아줘"
            r'(.+?)\s*(?:PR|피알|이슈)\s*(?:찾아|검색|보여)',  # "Bias RF PR 찾아줘"
            r'(?:PR|피알)\s*(.+?)\s*(?:검색|찾아)',  # "PR Bias RF 검색"
            r'(.+?)\s*(?:이슈|issues?)\s*(?:PR|피알)',  # "etching issues PR"
            # 영어 패턴
            r'find\s*(?:PR|PRs|issues?)\s+(?:related\s+to|about|for|on)\s+(.+)',  # "find PR related to bias RF"
            r'find\s*(?:PR|PRs|issues?)\s+(.+)',  # "find PRs bias RF"
            r'search\s*(?:PR|PRs|issues?)\s+(?:related\s+to|about|for|on)\s+(.+)',  # "search PR related to chamber"
            r'(?:PR|PRs)\s+(?:related\s+to|about|for)\s+(.+)',  # "PR related to bias RF"
            r'(.+?)\s+(?:PR|PRs|issues?)\s*$',  # "bias rf PR" (끝에 PR)
        ]
        
        for pattern in keyword_search_patterns:
            match = re.search(pattern, query, re.IGNORECASE)
            if match:
                # 키워드 추출
                groups = match.groups()
                keyword = None
                for g in groups:
                    if g and g.upper() not in ['PR', 'PRS', '피알', '이슈', 'ISSUES', 'ISSUE']:
                        # 앞뒤 불용어 제거 (the, a, an, to, for, with 등)
                        cleaned = g.strip()
                        cleaned = re.sub(r'^(the|a|an|to|for|with|about|on|related\s+to)\s+', '', cleaned, flags=re.IGNORECASE)
                        cleaned = re.sub(r'\s+(the|a|an)$', '', cleaned.strip(), flags=re.IGNORECASE)
                        if cleaned and len(cleaned) >= 2:
                            keyword = cleaned
                            break
                
                if keyword and len(keyword) >= 2:
                    return self._keyword_pr_search(keyword)
        
        # 기술 키워드 직접 검색 (2-4 단어, PR/관련 없이도 SWRN 검색)
        # 예: "bias rf", "rf power", "chamber pressure", "valve control"
        tech_keyword_pattern = r'^([a-zA-Z0-9]+(?:\s+[a-zA-Z0-9]+){1,3})$'
        tech_match = re.match(tech_keyword_pattern, query.strip(), re.IGNORECASE)
        if tech_match:
            keyword = tech_match.group(1).strip()
            # 최소 4자 이상이고, 일반적인 명령어가 아닌 경우
            if len(keyword) >= 4 and keyword.lower() not in ['help', 'test', 'hello', 'hi there', 'thank you']:
                return self._keyword_pr_search(keyword)
        
        # PR 번호 패턴: PR-XXXXXX, PR XXXXXX, PRXXXXXX, 또는 6자리 숫자
        pr_patterns = [
            r'PR[-\s]?(\d{6})',  # PR-123456, PR 123456, PR123456
            r'(?:^|\s)(\d{6})(?:\s|$|[?.,])',  # 단독 6자리 숫자
        ]
        
        pr_number = None
        for pattern in pr_patterns:
            match = re.search(pattern, query.upper())
            if match:
                pr_number = match.group(1)
                break
        
        if not pr_number:
            return None
        
        # PR 관련 키워드가 있는지 확인 (단순 숫자만 있을 때 오탐 방지)
        pr_keywords = ['pr', 'PR', '피알', '릴리즈', 'release', 'fix', '수정', '패치', 'patch', 
                       '노트', 'note', '어떤', '뭐', '무슨', '내용', '설명', 'what', 'about']
        
        # 6자리 숫자만 있는 경우, PR 관련 키워드가 없으면 무시
        if f'PR-{pr_number}' not in query.upper() and f'PR{pr_number}' not in query.upper():
            has_pr_keyword = any(kw in query.lower() for kw in pr_keywords)
            if not has_pr_keyword:
                return None
        
        # SWRN SQLite FTS5 인덱스에서 검색 (새로운 방식 - 밀리초 단위)
        try:
            from swrn_indexer import SWRNIndexer
            indexer = SWRNIndexer()
            
            # PR 번호 정규화
            pr_id = f"PR-{pr_number}"
            
            # 인덱스 존재 확인
            stats = indexer.get_stats()
            if not stats.get("indexed"):
                return f"📋 <b>{pr_id}</b> 검색 불가<br><br>⚠️ SWRN 인덱스가 아직 구축되지 않았습니다.<br>터미널에서 <code>python swrn_indexer.py --build</code>를 실행해 주세요."
            
            # HTML 형식 결과 반환
            result = indexer.format_pr_result(pr_id)
            return result
                
        except ImportError:
            print("⚠️ swrn_indexer module not found")
            return f"📋 <b>PR-{pr_number}</b><br><br>swrn_indexer 모듈을 찾을 수 없습니다."
        except Exception as e:
            print(f"⚠️ PR search error: {e}")
            return f"📋 <b>PR-{pr_number}</b> 검색 중 오류 발생<br><br>오류: {str(e)}"
    
    def _keyword_pr_search(self, keyword: str) -> str:
        """키워드 기반 PR 검색 (FTS5 직접 검색 + Phrase Match 우선)"""
        try:
            from swrn_indexer import SWRNIndexer, parse_sw_version
            import re
            import sqlite3
            indexer = SWRNIndexer()
            
            # 인덱스 존재 확인
            stats = indexer.get_stats()
            if not stats.get("indexed"):
                return f"🔍 <b>{keyword}</b> 검색 불가<br><br>⚠️ SWRN 인덱스가 아직 구축되지 않았습니다.<br>터미널에서 <code>python swrn_indexer.py --build</code>를 실행해 주세요."
            
            # 원본 키워드 정리
            original_keyword_lower = keyword.lower().strip()
            keyword_words = [w for w in original_keyword_lower.split() if len(w) >= 2]
            
            # ★ FTS5 직접 검색 (모든 키워드 AND 검색)
            pr_candidates = {}  # pr_number -> pr_info
            
            if keyword_words and indexer.db_path.exists():
                conn = sqlite3.connect(str(indexer.db_path))
                cursor = conn.cursor()
                
                # FTS5 AND 쿼리 생성
                fts_query = " AND ".join(keyword_words)
                
                try:
                    # FTS5 검색으로 페이지 찾기
                    cursor.execute("""
                        SELECT DISTINCT f.filename, pc.page_num, f.sw_version
                        FROM page_content pc
                        JOIN pdf_files f ON CAST(pc.file_id AS INTEGER) = f.id
                        WHERE page_content MATCH ?
                        ORDER BY rank
                        LIMIT 100
                    """, (fts_query,))
                    
                    pages_with_keywords = cursor.fetchall()
                    
                    # 해당 페이지의 PR들 찾기
                    for filename, page_num, sw_version in pages_with_keywords:
                        cursor.execute("""
                            SELECT DISTINCT p.pr_number
                            FROM pr_index p
                            JOIN pdf_files f ON p.file_id = f.id
                            WHERE f.filename = ? AND p.page_num = ?
                        """, (filename, page_num))
                        
                        for row in cursor.fetchall():
                            pr_num = row[0].replace("PR-", "")
                            if pr_num not in pr_candidates:
                                pr_candidates[pr_num] = {"pr_number": pr_num, "fts_match": True}
                    
                except sqlite3.OperationalError as e:
                    print(f"⚠️ FTS5 search error: {e}")
                
                conn.close()
            
            # 하이브리드 검색 결과도 추가 (보조)
            result = indexer.find_similar_prs(keyword, limit=20, strictness=0)
            for pr in result.get("similar_prs", []):
                pr_num = pr.get("pr_number", "").replace("PR-", "")
                if pr_num and pr_num not in pr_candidates:
                    pr_candidates[pr_num] = pr
                elif pr_num in pr_candidates:
                    # 기존 항목에 hybrid 정보 병합
                    pr_candidates[pr_num].update(pr)
            
            if not pr_candidates:
                return f"🔍 '<b>{keyword}</b>'와 관련된 PR을 찾을 수 없습니다.<br><br>💡 다른 키워드로 검색해 보세요."
            
            # 상세 정보 가져오기 + Phrase Match 점수 계산
            similar_prs = []
            for pr_num, pr in pr_candidates.items():
                pr_detail = indexer.get_pr_detail(pr_num)
                
                # ★ PyMuPDF 없을 때 fallback: context에서 정보 추출
                if pr_detail:
                    detail = pr_detail.get("detail", {})
                    pr["pr_number"] = pr_num
                    pr["sw_version"] = pr_detail.get("sw_version", "")
                    context = pr_detail.get("context", "")
                    
                    # detail이 비어있으면 context에서 파싱 시도
                    if not detail.get("affected_function") and context:
                        # ★ 표 형식 PDF 파싱 (대부분의 Release Notes)
                        # 형식: "Area  Module  Function  PR-XXXXXX – Description  Solution"
                        
                        # 1. PR 번호 앞의 Affected Function 추출
                        # 패턴: "xxx  xxx  FunctionName  PR-XXXXXX"
                        pr_position = context.find(f'PR-{pr_num}')
                        if pr_position == -1:
                            pr_position = context.find(f'PR {pr_num}')
                        if pr_position == -1:
                            pr_position = context.find(pr_num)
                        
                        if pr_position > 0:
                            before_pr = context[:pr_position].strip()
                            # 마지막 "  " (두 칸 공백) 이후의 텍스트가 Affected Function
                            parts = before_pr.split('  ')
                            if len(parts) >= 1:
                                # 마지막 non-empty 부분
                                for p in reversed(parts):
                                    p = p.strip()
                                    if p and len(p) > 2 and not p.isspace():
                                        # 알려진 무시 패턴 제외
                                        if p not in ['All', 'N/A', '-'] and not re.match(r'^[\d\.]+$', p):
                                            detail["affected_function"] = p[:100]
                                            break
                        
                        # 2. PR 번호 뒤의 Issue Description 추출
                        # 패턴: "PR-XXXXXX – Description text.  Solution text."
                        pr_match = re.search(rf'PR[-\s]?{pr_num}[\s–\-:]+([^\.]+\.)', context, re.IGNORECASE)
                        if pr_match:
                            issue_text = pr_match.group(1).strip()
                            if len(issue_text) > 10:
                                detail["issue_description"] = issue_text[:300]
                                detail["title"] = issue_text[:100]
                        
                        # 3. Solution 추출 - "The software has been changed" 패턴
                        solution_match = re.search(r'(The software has been changed[^\.]+\.)', context, re.IGNORECASE)
                        if solution_match:
                            detail["solution"] = solution_match.group(1).strip()[:200]
                        
                        # 대안: "has been" 패턴
                        if not detail.get("solution"):
                            alt_solution = re.search(r'([A-Z][^\.]*has been[^\.]+\.)', context, re.IGNORECASE)
                            if alt_solution:
                                sol_text = alt_solution.group(1).strip()
                                # 설명이 아닌 해결책인지 확인
                                if 'changed' in sol_text.lower() or 'fixed' in sol_text.lower() or 'updated' in sol_text.lower():
                                    detail["solution"] = sol_text[:200]
                        
                        # 4. 상세 형식 fallback (Component:, Module: 헤더가 있는 경우)
                        if not detail.get("affected_function"):
                            comp_match = re.search(r'Component[:\s]*([A-Za-z][^\n]+?)(?:Module:|History|$)', context, re.IGNORECASE)
                            if comp_match:
                                detail["affected_function"] = comp_match.group(1).strip()[:80]
                        
                        if not detail.get("affected_function"):
                            module_match = re.search(r'Module[:\s]*([A-Za-z0-9][^\n]+?)(?:Module Type:|History|$)', context, re.IGNORECASE)
                            if module_match:
                                val = module_match.group(1).strip()
                                if not val.lower().startswith('type'):
                                    detail["affected_function"] = val[:80]
                        
                        if not detail.get("solution"):
                            benefits_match = re.search(r'Benefits[:\s]*([^\n]+)', context, re.IGNORECASE)
                            if benefits_match:
                                detail["solution"] = benefits_match.group(1).strip()[:150]
                        
                        # 5. pr_type 감지
                        if 'new feature' in context.lower() or 'added' in context.lower() or 'support' in context.lower():
                            detail["pr_type"] = "new_feature"
                            detail["pr_type_label"] = "New Feature"
                        elif 'issue' in context.lower() or 'fix' in context.lower() or 'bug' in context.lower():
                            detail["pr_type"] = "issue_fix"
                            detail["pr_type_label"] = "Issue Fix"
                    
                    pr["affected_function"] = detail.get("affected_function", "")
                    pr["pr_type"] = detail.get("pr_type", pr_detail.get("pr_type", "unknown"))
                    pr["pr_type_label"] = detail.get("pr_type_label", "")
                    pr["title"] = detail.get("title", "")
                    pr["description"] = detail.get("description", "")
                    pr["issue_description"] = detail.get("issue_description", "") or detail.get("issue_or_description", "") or context[:200]
                    pr["solution"] = detail.get("solution", "")
                    pr["benefits"] = detail.get("benefits", "")
                    pr["solution_or_benefit"] = detail.get("solution_or_benefit", "")
                    
                    # ★ Phrase Match 점수 계산
                    # 우선순위: Affected Function > Title > 기타 필드
                    affected_func = str(pr.get("affected_function", "")).lower()
                    title_text = str(pr.get("title", "")).lower()
                    context_text = str(pr_detail.get("context", "")) or ""
                    
                    other_text = " ".join([
                        str(pr.get("issue_description", "")),
                        str(pr.get("solution", "")),
                        str(pr.get("description", "")),
                        context_text
                    ]).lower()
                    
                    phrase_match_score = 0
                    
                    # 1) Affected Function에서 phrase 일치 (최고 점수: 2000)
                    if original_keyword_lower in affected_func:
                        phrase_match_score = 2000
                    # 2) Title에서 phrase 일치 (1500)
                    elif original_keyword_lower in title_text:
                        phrase_match_score = 1500
                    # 3) 기타 필드에서 phrase 일치 (1000)
                    elif original_keyword_lower in other_text:
                        phrase_match_score = 1000
                    # 4) Affected Function에 모든 단어 포함 (800)
                    elif len(keyword_words) > 1 and all(w in affected_func for w in keyword_words):
                        phrase_match_score = 800
                    # 5) 모든 단어가 어딘가에 있음 (500)
                    elif len(keyword_words) > 1:
                        all_text = f"{affected_func} {title_text} {other_text}"
                        if all(w in all_text for w in keyword_words):
                            phrase_match_score = 500
                        else:
                            matched_words = sum(1 for w in keyword_words if w in all_text)
                            phrase_match_score = matched_words * 100
                    elif len(keyword_words) == 1:
                        all_text = f"{affected_func} {title_text} {other_text}"
                        if keyword_words[0] in all_text:
                            phrase_match_score = 300
                    
                    pr["phrase_match_score"] = phrase_match_score
                    similar_prs.append(pr)
            
            # ★ 정렬: Phrase Match 점수 > SW Version (내림차순)
            def get_sort_key(x):
                phrase_score = x.get("phrase_match_score", 0)
                ver_tuple = parse_sw_version(x.get("sw_version", ""))
                return (-phrase_score, tuple(-v for v in ver_tuple))
            
            similar_prs.sort(key=get_sort_key)
            
            # 상위 20개만 표시
            similar_prs = similar_prs[:20]
            
            # 키워드 하이라이트 함수
            def highlight_keywords(text, keywords):
                if not text:
                    return "-"
                for kw in keywords.split():
                    if len(kw) >= 2:
                        text = re.sub(f'({re.escape(kw)})', r'<mark style="background:#fef08a;">\1</mark>', text, flags=re.IGNORECASE)
                return text
            
            # PLM 링크 생성 함수
            def get_plm_link(pr_num):
                # PR 번호에서 숫자만 추출
                clean_num = str(pr_num).replace('PR-', '').replace('PR', '').strip()
                return f"https://iplmprd.fremont.lamrc.net/3dspace/goto/o/LRC+Problem+Report/PR-{clean_num}"
            
            # HTML 테이블 생성 (Enhanced/Bug 컬럼 추가)
            html = f'<div class="swrn-search-result"><h4>🔍 \'<b>{keyword}</b>\' 검색 결과 ({len(similar_prs)}건)</h4><table class="pr-table" style="width:100%; border-collapse:collapse; margin-top:5px;"><thead><tr style="background:#f0f0f0;"><th style="padding:8px; border:1px solid #ddd; text-align:left;">PR 번호</th><th style="padding:8px; border:1px solid #ddd; text-align:center;">Enhanced/Bug</th><th style="padding:8px; border:1px solid #ddd; text-align:left;">SW Version</th><th style="padding:8px; border:1px solid #ddd; text-align:left;">Affected Function</th><th style="padding:8px; border:1px solid #ddd; text-align:left;">Issue Description</th><th style="padding:8px; border:1px solid #ddd; text-align:left;">Solution</th></tr></thead><tbody>'
            
            for pr in similar_prs:
                pr_num = pr.get("pr_number", "N/A")
                sw_ver = pr.get("sw_version", "-")[:35]
                
                # PR 유형 배지
                pr_type = pr.get("pr_type", "unknown")
                pr_type_label = pr.get("pr_type_label", "")
                if pr_type == 'new_feature':
                    type_badge = '<span style="background:#22c55e;color:white;padding:2px 6px;border-radius:3px;font-size:11px;">New Feature</span>'
                elif pr_type == 'issue_fix':
                    type_badge = '<span style="background:#ef4444;color:white;padding:2px 6px;border-radius:3px;font-size:11px;">Issue Fix</span>'
                else:
                    type_badge = '<span style="background:#6b7280;color:white;padding:2px 6px;border-radius:3px;font-size:11px;">-</span>'
                
                # Affected Function
                affected = pr.get("affected_function", "")
                if affected and len(affected) > 60:
                    affected = affected[:60] + "..."
                if not affected:
                    affected = "-"
                
                # Issue Description (PR Type에 따라 실제 데이터 선택)
                # New Feature: description, Issue Fix: issue_description
                if pr_type == 'new_feature':
                    issue = pr.get("description", "") or pr.get("issue_description", "")
                else:
                    issue = pr.get("issue_description", "") or pr.get("description", "")
                if issue and len(issue) > 150:
                    issue = issue[:150] + "..."
                if not issue:
                    issue = "-"
                
                # Solution/Benefits (PR Type에 따라 실제 데이터 선택)
                # New Feature: benefits, Issue Fix: solution
                if pr_type == 'new_feature':
                    solution = pr.get("benefits", "") or pr.get("solution_or_benefit", "") or pr.get("solution", "")
                else:
                    solution = pr.get("solution", "") or pr.get("solution_or_benefit", "") or pr.get("benefits", "")
                if solution and len(solution) > 100:
                    solution = solution[:100] + "..."
                if not solution:
                    solution = "-"
                
                # 키워드 하이라이트 적용
                affected = highlight_keywords(affected, keyword)
                issue = highlight_keywords(issue, keyword)
                solution = highlight_keywords(solution, keyword)
                
                # PLM 링크로 변경
                plm_link = get_plm_link(pr_num)
                html += f'<tr><td style="padding:8px; border:1px solid #ddd;"><a href="{plm_link}" target="_blank">PR-{pr_num}</a></td><td style="padding:8px; border:1px solid #ddd; text-align:center;">{type_badge}</td><td style="padding:8px; border:1px solid #ddd;">{sw_ver}</td><td style="padding:8px; border:1px solid #ddd;">{affected}</td><td style="padding:8px; border:1px solid #ddd;">{issue}</td><td style="padding:8px; border:1px solid #ddd;">{solution}</td></tr>'
            
            html += '</tbody></table><p style="margin-top:10px; font-size:0.9em; color:#666;">💡 PR 번호를 클릭하면 PLM에서 상세 정보를 볼 수 있습니다.</p></div>'
            
            return html
            
        except ImportError as e:
            return f"🔍 키워드 검색 기능을 사용할 수 없습니다.<br>오류: {str(e)}"
        except Exception as e:
            print(f"⚠️ Keyword PR search error: {e}")
            return f"🔍 '<b>{keyword}</b>' 검색 중 오류 발생<br><br>오류: {str(e)}"
    
    def _extract_keywords_from_title(self, title: str) -> List[str]:
        """PR 제목에서 핵심 키워드 추출 (SWRN 검색용)"""
        import re
        
        if not title:
            return []
        
        # 불용어 정의
        stopwords = {'a', 'an', 'the', 'is', 'are', 'was', 'were', 'be', 'been', 'being',
                    'have', 'has', 'had', 'do', 'does', 'did', 'will', 'would', 'could',
                    'should', 'may', 'might', 'must', 'shall', 'can', 'need', 'dare',
                    'to', 'of', 'in', 'for', 'on', 'with', 'at', 'by', 'from', 'up',
                    'about', 'into', 'over', 'after', 'and', 'or', 'but', 'if', 'then',
                    'so', 'than', 'too', 'very', 'just', 'only', 'when', 'where', 'why',
                    'how', 'all', 'each', 'every', 'both', 'few', 'more', 'most', 'other',
                    'some', 'such', 'no', 'nor', 'not', 'same', 'that', 'this', 'these',
                    'those', 'request', 'add', 'new', 'issue', 'problem', 'please'}
        
        # 기술 용어 (우선 추출)
        tech_terms = ['rf', 'tcp', 'esc', 'mfc', 'sw', 'ui', 'sp', 'hf', 'cvf', 'snap',
                     'kiyo', 'sensei', 'akara', 'vantex', 'tempo', 'svid', 'recipe',
                     'process', 'bias', 'etching', 'chamber', 'wafer', 'gas', 'power',
                     'pressure', 'temperature', 'temp', 'wear', 'compensation', 'error',
                     'timeout', 'crash', 'fail', 'upgrade', 'version', 'parameter']
        
        # 제목을 소문자로 변환하고 특수문자 제거
        title_clean = re.sub(r'[^\w\s]', ' ', title.lower())
        words = title_clean.split()
        
        keywords = []
        
        # 1. 기술 용어 우선 추출
        for word in words:
            if word in tech_terms and word not in keywords:
                keywords.append(word)
        
        # 2. 불용어가 아닌 3자 이상 단어 추출
        for word in words:
            if len(word) >= 3 and word not in stopwords and word not in keywords:
                keywords.append(word)
                if len(keywords) >= 5:  # 최대 5개
                    break
        
        return keywords
    
    def _get_open_pr_insights(self, query: str) -> str:
        """Open PR에 대해 과거 Fixed된 유사 사례를 SWRN에서 검색하여 인사이트 제공"""
        try:
            import os
            import pandas as pd
            from datetime import datetime
            
            # Open PR 목록 가져오기
            csv_path = os.path.join(os.path.dirname(__file__), 'data', 'TableExport.csv')
            if not os.path.exists(csv_path):
                csv_path = os.path.join(os.path.dirname(__file__), 'data', 'Issues Tracking.csv')
            
            if not os.path.exists(csv_path):
                return "❌ PR 데이터 파일을 찾을 수 없습니다."
            
            df = pd.read_csv(csv_path, encoding='utf-8')
            today = datetime.now()
            
            # 컬럼명 확인 (컬럼명에 공백이 있을 수 있음)
            status_col = 'Current Status' if 'Current Status' in df.columns else 'Status'
            # PR 컬럼: "PR or ES " (끝에 공백) 또는 "PR or ES #"
            pr_col = None
            for col in df.columns:
                if 'PR or ES' in col or col == 'PR Number':
                    pr_col = col
                    break
            if not pr_col:
                pr_col = df.columns[6] if len(df.columns) > 6 else 'PR or ES #'
            
            title_col = 'Issue' if 'Issue' in df.columns else 'Title'
            date_col = 'Date reported' if 'Date reported' in df.columns else 'Submitted Date'
            
            # ★★★ Fixed/Closed 상태 제외 키워드 (대소문자 무시, JSON 형식 포함) ★★★
            exclude_keywords = ['fixed', 'closed', 'resolved', 'rejected', 'completed', 'done', 'cancel']
            
            # Open 상태 PR 필터링 (30일 이상, Fixed 제외)
            # 실제 Open/Waiting 상태 키워드
            open_keywords = ['waiting', 'in review', 'develop', 'confirmed', 'create', 'monitoring', 'installed', 'no solution']
            open_prs = []
            
            for _, row in df.iterrows():
                status_raw = str(row.get(status_col, ''))
                # JSON 형식 제거: [""Fixed by SW upgrade""] → Fixed by SW upgrade
                status_clean = status_raw.replace('[', '').replace(']', '').replace('"', '').strip()
                status_lower = status_clean.lower()
                
                # ★★★ Fixed/Closed 상태는 무조건 제외 (가장 먼저 체크) ★★★
                is_fixed = any(ex in status_lower for ex in exclude_keywords)
                if is_fixed:
                    continue  # Fixed 상태이므로 건너뜀
                
                # Open/Waiting 상태인지 확인
                is_open = any(kw in status_lower for kw in open_keywords)
                if not is_open:
                    continue  # Open 상태가 아니므로 건너뜀
                
                # 날짜 계산
                submitted = row.get(date_col)
                days_open = 0
                if pd.notna(submitted):
                    try:
                        date_obj = pd.to_datetime(submitted, errors='coerce')
                        if pd.notna(date_obj):
                            days_open = (today - date_obj).days
                    except:
                        pass
                
                # 30일 이상 Open된 PR만 추가
                if days_open >= 30:
                    # PR 번호 추출 (URL에서 또는 직접)
                    pr_value = str(row.get(pr_col, 'N/A'))
                    pr_number = pr_value
                    # URL인 경우 PR 번호 추출: .../PR-123456/
                    import re
                    pr_match = re.search(r'PR-(\d+)', pr_value)
                    if pr_match:
                        pr_number = f'PR-{pr_match.group(1)}'
                    
                    open_prs.append({
                        'pr_number': pr_number,
                        'title': str(row.get(title_col, ''))[:80],
                        'status': status_clean,
                        'days_open': days_open
                    })
            
            if not open_prs:
                return "🔍 30일 이상 Open된 PR이 없습니다."
            
            # 상위 5개 PR에 대해 유사 Fixed 사례 검색
            open_prs.sort(key=lambda x: x['days_open'], reverse=True)
            top_prs = open_prs[:5]
            
            html = '<div style="margin-bottom:12px;"><h3 style="margin:0 0 8px 0;color:#7c3aed;font-size:18px;">🔍 Open PR 인사이트</h3>'
            html += '<p style="margin:0 0 10px 0;color:#666;font-size:13px;">미해결 Open PR에 대해 과거 Fixed된 유사 사례를 검색한 결과입니다.</p></div>'
            
            insights_found = 0
            
            for pr in top_prs:
                # PR 제목에서 키워드 추출하여 SWRN 검색
                keywords = self._extract_keywords_from_title(pr['title'])
                
                if keywords:
                    # TF-IDF 검색으로 유사 문서 찾기
                    search_query = ' '.join(keywords)
                    similar_docs = self.search(search_query, top_k=3)
                    
                    # Fixed 관련 문서만 필터링
                    fixed_docs = [doc for doc in similar_docs if 
                                  any(kw in doc['content'].lower() for kw in ['fixed', 'resolved', 'solution', 'workaround', 'fix된', '해결'])]
                    
                    if fixed_docs:
                        insights_found += 1
                        html += f'<div style="background:#faf5ff;border-radius:8px;padding:10px;margin-bottom:10px;border-left:4px solid #7c3aed;">'
                        html += f'<div style="font-weight:bold;color:#7c3aed;margin-bottom:5px;">📌 {pr["pr_number"]} ({pr["days_open"]}일 Open)</div>'
                        html += f'<div style="font-size:12px;color:#374151;margin-bottom:8px;">{pr["title"]}</div>'
                        html += f'<div style="background:#f0fdf4;padding:8px;border-radius:6px;">'
                        html += f'<div style="color:#166534;font-weight:bold;font-size:12px;margin-bottom:4px;">💡 유사 Fixed 사례:</div>'
                        
                        for doc in fixed_docs[:2]:
                            snippet = doc['content'][:150].replace('\n', ' ')
                            source = doc.get('source', 'SWRN')
                            html += f'<div style="font-size:11px;color:#374151;margin:4px 0;padding-left:10px;border-left:2px solid #22c55e;">'
                            html += f'<span style="color:#059669;">[{source}]</span> {snippet}...</div>'
                        
                        html += '</div></div>'
            
            if insights_found == 0:
                html += '<div style="padding:15px;background:#fef3c7;border-radius:8px;color:#92400e;">'
                html += '⚠️ 현재 Open PR들에 대한 유사 Fixed 사례를 찾지 못했습니다.<br>'
                html += 'SWRN 인덱스를 업데이트하거나, 더 구체적인 키워드로 검색해보세요.</div>'
            else:
                html += f'<div style="margin-top:10px;padding:8px;background:#e0e7ff;border-radius:6px;font-size:12px;color:#3730a3;">'
                html += f'✅ {len(top_prs)}개의 Open PR 중 {insights_found}개에서 유사 Fixed 사례를 발견했습니다.</div>'
            
            return html
            
        except Exception as e:
            print(f"⚠️ Open PR insights error: {e}")
            import traceback
            traceback.print_exc()
            return f"❌ Open PR 인사이트 분석 중 오류가 발생했습니다: {str(e)}"
    
    def _analyze_open_prs_local(self, is_chronic: bool = False, is_waiting: bool = False) -> str:
        """로컬 TF-IDF 기반으로 Open PR 분석 (Fixed 상태 제외)"""
        import os
        import pandas as pd
        from datetime import datetime
        
        # TableExport.csv 로드
        csv_path = os.path.join(os.path.dirname(__file__), 'data', 'TableExport.csv')
        if not os.path.exists(csv_path):
            # 대체 경로 시도
            csv_path = os.path.join(os.path.dirname(__file__), 'data', 'Issues Tracking.csv')
            if not os.path.exists(csv_path):
                return "❌ PR 데이터 파일(TableExport.csv 또는 Issues Tracking.csv)을 찾을 수 없습니다."
        
        try:
            df = pd.read_csv(csv_path, encoding='utf-8')
        except Exception as e:
            return f"❌ CSV 파일 읽기 오류: {str(e)}"
        
        today = datetime.now()
        open_prs = []
        
        # 컬럼명 확인 및 조정 (컬럼명에 공백이 있을 수 있음)
        status_col = 'Current Status' if 'Current Status' in df.columns else 'Status'
        # PR 컬럼: "PR or ES " (끝에 공백) 또는 "PR or ES #"
        pr_col = None
        for col in df.columns:
            if 'PR or ES' in col or col == 'PR Number':
                pr_col = col
                break
        if not pr_col:
            pr_col = df.columns[6] if len(df.columns) > 6 else 'PR or ES #'
        
        title_col = 'Issue' if 'Issue' in df.columns else 'Title'
        date_col = 'Date reported' if 'Date reported' in df.columns else 'Submitted Date'
        
        # ★★★ Fixed/Closed 상태 제외 키워드 (JSON 형식 처리) ★★★
        exclude_keywords = ['fixed', 'closed', 'resolved', 'rejected', 'completed', 'done', 'cancel']
        
        # Open/Waiting 상태 키워드
        open_keywords = ['waiting', 'in review', 'develop', 'confirmed', 'create', 'monitoring', 'installed', 'no solution']
        
        if is_chronic:
            # Chronic (장기 Open) - 60일 이상 Open된 PR
            type_label = "Chronic (장기 Open)"
            min_days = 60
        else:
            # Waiting PR - 30일 이상 대기 중인 PR
            type_label = "Waiting PR Fix"
            min_days = 30
        
        for _, row in df.iterrows():
            status_raw = str(row.get(status_col, ''))
            # JSON 형식 제거: [""Fixed by SW upgrade""] → Fixed by SW upgrade
            status_clean = status_raw.replace('[', '').replace(']', '').replace('"', '').strip()
            status_lower = status_clean.lower()
            
            # ★★★ Fixed/Closed 상태는 무조건 제외 ★★★
            is_fixed = any(ex in status_lower for ex in exclude_keywords)
            if is_fixed:
                continue
            
            # Open/Waiting 상태인지 확인
            is_open = any(kw in status_lower for kw in open_keywords)
            if not is_open:
                continue
            
            # 날짜 계산
            submitted_date = row.get(date_col)
            days_open = 0
            if pd.notna(submitted_date):
                try:
                    date_obj = pd.to_datetime(submitted_date, errors='coerce')
                    if pd.notna(date_obj):
                        days_open = (today - date_obj).days
                except:
                    pass
            
            if days_open >= min_days:
                # PR 번호 추출 (URL에서 또는 직접)
                pr_value = str(row.get(pr_col, 'N/A'))
                pr_num = pr_value
                # URL인 경우 PR 번호 추출: .../PR-123456/
                import re
                pr_match = re.search(r'PR-(\d+)', pr_value)
                if pr_match:
                    pr_num = f'PR-{pr_match.group(1)}'
                
                title = str(row.get(title_col, 'N/A'))[:100]
                # 상태 표시용 정리
                status_display = status_clean if len(status_clean) < 30 else status_clean[:27] + '...'
                open_prs.append({
                    'pr_number': pr_num,
                    'title': title,
                    'status': status_display,
                    'days_open': days_open
                })
        
        # days_open 기준 정렬
        open_prs.sort(key=lambda x: x['days_open'], reverse=True)
        open_prs = open_prs[:10]  # 상위 10개
        
        if not open_prs:
            return f"🔍 {min_days}일 이상 Open된 PR이 없습니다. 데이터를 확인해주세요."
        
        # HTML 결과 생성 (공백 최소화)
        html = f'<div style="margin-bottom:10px;"><h3 style="margin:0 0 8px 0;color:#7c3aed;font-size:18px;">📊 {type_label} PR 분석 ({len(open_prs)}건)</h3>'
        html += f'<p style="margin:0 0 10px 0;color:#666;font-size:13px;">{min_days}일 이상 Open된 PR 목록입니다.</p></div>'
        
        # PR 테이블
        html += '<table style="width:100%;border-collapse:collapse;font-size:13px;background:#fff;border-radius:8px;overflow:hidden;">'
        html += '<thead><tr style="background:linear-gradient(135deg,#7c3aed,#9333ea);color:white;">'
        html += '<th style="padding:10px;text-align:left;width:15%;">PR 번호</th>'
        html += '<th style="padding:10px;text-align:left;width:45%;">제목</th>'
        html += '<th style="padding:10px;text-align:center;width:20%;">상태</th>'
        html += '<th style="padding:10px;text-align:center;width:20%;">Open 일수</th>'
        html += '</tr></thead><tbody>'
        
        for idx, pr in enumerate(open_prs):
            bg_color = '#faf5ff' if idx % 2 == 0 else '#fff'
            days_color = '#dc2626' if pr['days_open'] > 90 else ('#f59e0b' if pr['days_open'] > 60 else '#059669')
            
            html += f'<tr style="background:{bg_color};">'
            html += f'<td style="padding:8px;border-bottom:1px solid #e5e7eb;font-weight:bold;color:#7c3aed;">{pr["pr_number"]}</td>'
            html += f'<td style="padding:8px;border-bottom:1px solid #e5e7eb;">{pr["title"]}</td>'
            html += f'<td style="padding:8px;border-bottom:1px solid #e5e7eb;text-align:center;"><span style="background:#fef3c7;color:#92400e;padding:2px 8px;border-radius:4px;font-size:11px;">{pr["status"]}</span></td>'
            html += f'<td style="padding:8px;border-bottom:1px solid #e5e7eb;text-align:center;"><span style="background:{days_color};color:white;padding:3px 10px;border-radius:12px;font-weight:bold;">{pr["days_open"]}일</span></td>'
            html += '</tr>'
        
        html += '</tbody></table>'
        
        # 요약 통계
        avg_days = sum(pr['days_open'] for pr in open_prs) / len(open_prs) if open_prs else 0
        max_days = max(pr['days_open'] for pr in open_prs) if open_prs else 0
        
        html += f'<div style="margin-top:12px;padding:10px;background:#f0fdf4;border-radius:8px;border-left:4px solid #22c55e;">'
        html += f'<h4 style="margin:0 0 6px 0;color:#166534;font-size:14px;">📈 요약 통계</h4>'
        html += f'<ul style="margin:0;padding-left:20px;color:#374151;font-size:13px;">'
        html += f'<li>총 {type_label} PR: <strong>{len(open_prs)}건</strong></li>'
        html += f'<li>평균 Open 일수: <strong>{avg_days:.1f}일</strong></li>'
        html += f'<li>최장 Open 일수: <strong>{max_days}일</strong></li>'
        html += '</ul></div>'
        
        html += '<p style="font-size:11px;color:#666;margin-top:8px;">💡 개별 PR 번호를 입력하면 상세 정보를 확인할 수 있습니다.</p>'
        
        return html

    def get_status(self) -> Dict:
        """시스템 상태 확인"""
        llm_status = "None"
        llm_model = "N/A"
        
        if self.gguf_available:
            llm_status = "GGUF (Local)"
            llm_model = os.path.basename(GGUF_MODEL_PATH)
        elif self.ollama_available:
            llm_status = "Ollama + Llama3.2-3B"
            llm_model = OLLAMA_MODEL
        
        return {
            'system_name': 'TF-IDF (Llama3.2-3B)',
            'tfidf_available': TFIDF_AVAILABLE,
            'gguf_available': self.gguf_available,
            'ollama_available': self.ollama_available,
            'llm_status': llm_status,
            'llm_model': llm_model,
            'document_count': len(self.documents),
            'initialized': self.initialized,
            'index_path': self.index_path
        }
    
    def get_sources_summary(self) -> Dict:
        """인덱싱된 소스 요약"""
        if not self.doc_metadata:
            return {}
        
        summary = {}
        for meta in self.doc_metadata:
            source = meta.get('source', 'Unknown')
            summary[source] = summary.get(source, 0) + 1
        
        return summary


# 싱글톤 인스턴스
_rag_instance = None

def get_rag_system() -> LocalRAGSystem:
    """RAG 시스템 싱글톤 인스턴스 반환"""
    global _rag_instance
    if _rag_instance is None:
        _rag_instance = LocalRAGSystem()
    return _rag_instance


# CLI 테스트
if __name__ == "__main__":
    print("=" * 60)
    print("🔧 TF-IDF (Llama3.2-3B) RAG System (완전 오프라인)")
    print("=" * 60)
    
    rag = get_rag_system()
    print("\n📊 System Status:", rag.get_status())
    
    # 데이터 인덱싱
    print("\n" + "=" * 60)
    rag.load_and_index_data(force_reindex=True)
    
    # 테스트 쿼리
    test_queries = [
        "CVD 장비 현황",
        "SW 버전 업그레이드",
        "PR Fix 대기중인 이슈"
    ]
    
    print("\n" + "=" * 60)
    print("🔍 Test Queries")
    print("=" * 60)
    
    for query in test_queries:
        print(f"\n📝 Query: {query}")
        print("-" * 40)
        response = rag.rag_query(query)
        print(response[:500] + "..." if len(response) > 500 else response)
