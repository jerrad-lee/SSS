# SSS Dashboard Technical Whitepaper

## Semiconductor Software Support Intelligence Platform

**Version**: 3.5  
**Document Version**: 1.1  
**Last Updated**: December 2024  
**Classification**: Internal Technical Documentation

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [System Architecture Overview](#2-system-architecture-overview)
3. [Core Module Specifications](#3-core-module-specifications)
4. [Search Pipeline Architecture](#4-search-pipeline-architecture)
5. [Authentication & Security Model](#5-authentication--security-model)
6. [Data Management Layer](#6-data-management-layer)
7. [Frontend Architecture](#7-frontend-architecture)
8. [LLM Integration](#8-llm-integration)
9. [API Endpoints Reference](#9-api-endpoints-reference)
10. [Deployment Architecture](#10-deployment-architecture)
11. [Performance Characteristics](#11-performance-characteristics)
12. [Future Roadmap](#12-future-roadmap)

---

## 1. Executive Summary

### 1.1 Project Overview

SSS (Software Support System) Dashboard is an enterprise-grade web application designed for semiconductor etching equipment software management. The platform integrates:

- **Real-time Dashboard Analytics** - Equipment status, software versions, and maintenance metrics
- **AI-Powered Search (K-Bot)** - Natural language query system with RAG architecture
- **Document Intelligence** - 416+ SWRN (Software Release Notes) PDFs indexed and searchable
- **Multi-dimensional Reporting** - Issue tracking, FIF analysis, CXL3 statistics

### 1.2 Technology Stack Summary

| Layer | Technology | Version |
|-------|------------|---------|
| **Backend** | Flask (Python) | 2.0+ |
| **Frontend** | HTML5/CSS3/JavaScript | - |
| **Charting** | Chart.js, ECharts | 5.x |
| **Data Grid** | AG-Grid Community | 31.x |
| **UI Framework** | Tailwind CSS (CDN) | 3.x |
| **Search Engine** | SQLite FTS5 (BM25) | 3.9+ |
| **Vector Search** | TF-IDF (scikit-learn) | - |
| **LLM Engine** | Ollama + Llama 3.2-3B | GGUF Q4_K_M |
| **PDF Processing** | PyMuPDF (fitz) | 1.23+ |
| **Data Processing** | pandas, openpyxl | - |

### 1.3 Key Metrics

| Metric | Value |
|--------|-------|
| Total Source Lines | ~10,000+ |
| Main Flask Application | 3,484 lines |
| RAG System Module | 3,767 lines |
| PDF Indexer Module | 2,757 lines |
| Dashboard Frontend | 7,741 lines |
| Indexed PRs | 24,000+ |
| Indexed PDF Files | 416 |
| Database Size | ~195 MB |

---

## 2. System Architecture Overview

### 2.1 High-Level Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         SSS Dashboard v3.5                                   │
│                    K-Bots AI Insight Platform                               │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────┐    ┌─────────────┐  │
│  │   Browser   │────│   Flask     │────│   SQLite    │────│   Ollama    │  │
│  │  (Client)   │    │   Server    │    │   FTS5 DB   │    │   LLM API   │  │
│  └─────────────┘    └─────────────┘    └─────────────┘    └─────────────┘  │
│        ▲                   │                   │                   │        │
│        │                   ▼                   ▼                   ▼        │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                        Data Layer                                    │   │
│  │  ┌──────────────┐ ┌──────────────┐ ┌──────────────┐ ┌────────────┐  │   │
│  │  │ CSV/Excel    │ │ SWRN PDFs   │ │ TF-IDF Index │ │ User Auth  │  │   │
│  │  │ Data Files   │ │ (416 files) │ │ (Pickle)     │ │ (JSON/Enc) │  │   │
│  │  └──────────────┘ └──────────────┘ └──────────────┘ └────────────┘  │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 2.2 Module Interaction Flow

```
┌──────────────────────────────────────────────────────────────────────────┐
│                           Request Flow                                    │
├──────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│   HTTP Request                                                           │
│        │                                                                 │
│        ▼                                                                 │
│   ┌─────────────────────────────────────────────────────────────────┐   │
│   │                    Main_SSS.py (Flask App)                       │   │
│   │  - Session-based Authentication                                  │   │
│   │  - Route Handling (20+ endpoints)                               │   │
│   │  - Data Aggregation & Statistics                                │   │
│   └──────────────────────────┬──────────────────────────────────────┘   │
│                              │                                           │
│              ┌───────────────┼───────────────┐                          │
│              ▼               ▼               ▼                          │
│   ┌─────────────────┐ ┌─────────────┐ ┌─────────────────┐              │
│   │  local_rag.py   │ │swrn_indexer │ │  config.py      │              │
│   │                 │ │    .py      │ │                 │              │
│   │ - Query Process │ │             │ │ - Path Config   │              │
│   │ - TF-IDF Search │ │ - FTS5 DB   │ │ - Environment   │              │
│   │ - LLM Response  │ │ - PDF Parse │ │   Detection     │              │
│   └────────┬────────┘ └──────┬──────┘ └─────────────────┘              │
│            │                 │                                          │
│            ▼                 ▼                                          │
│   ┌─────────────────────────────────────────────────────────────────┐   │
│   │                    Ollama LLM Service                            │   │
│   │  Model: llama3.2-local (3B parameters, Q4_K_M quantization)     │   │
│   │  Port: 11434 (localhost)                                        │   │
│   └─────────────────────────────────────────────────────────────────┘   │
│                                                                          │
└──────────────────────────────────────────────────────────────────────────┘
```

---

## 3. Core Module Specifications

### 3.1 Main_SSS.py - Flask Web Server

**File Size**: 3,484 lines  
**Primary Purpose**: HTTP request handling, authentication, and data aggregation

#### 3.1.1 Key Features

| Feature | Description |
|---------|-------------|
| **Authentication** | Session-based with XOR encryption + SHA256 hashing |
| **User Management** | Thread-safe JSON file storage with audit logging |
| **Route Decorators** | `@login_required` for protected endpoints |
| **Data Caching** | 5-minute cache for SharePoint/PowerBI data |
| **Statistics APIs** | 15+ statistical analysis endpoints |

#### 3.1.2 Core Functions

```python
# Authentication Functions
def _xor_encrypt_decrypt(data: bytes, key: bytes) -> bytes
def _hash_password(password: str) -> str
def load_users() -> dict
def save_users(data: dict) -> bool
def log_access(username: str, action: str, ip_address: str) -> None

# Route Decorator
@login_required  # Enforces authentication for protected routes
```

#### 3.1.3 API Route Summary

| Route | Method | Description |
|-------|--------|-------------|
| `/` | GET | Redirect to login |
| `/login` | GET/POST | Authentication page |
| `/signup` | POST | User registration |
| `/logout` | GET | Session termination |
| `/dashboard` | GET | Main dashboard page |
| `/dashboard_stats` | GET | Tool statistics API |
| `/puca_stats` | GET | PUCA analysis API |
| `/ticket_stats` | GET | Ticket statistics API |
| `/issue_stats` | GET | Issue tracking API |
| `/pr_status` | GET | PR distribution API |
| `/cxl3_stats` | GET | CXL3 metrics API |
| `/chat` | POST | AI chat endpoint |
| `/rag/status` | GET | RAG system status |

### 3.2 local_rag.py - RAG Search System

**File Size**: 3,767 lines  
**Primary Purpose**: TF-IDF based document search with LLM response generation

#### 3.2.1 Architecture Components

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         LocalRAGSystem Architecture                         │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ┌───────────────┐    ┌───────────────┐    ┌───────────────┐               │
│  │ Query Input   │───▶│ Preprocessing │───▶│ Query         │               │
│  │ (Natural      │    │               │    │ Expansion     │               │
│  │  Language)    │    │ - Tokenize    │    │               │               │
│  └───────────────┘    │ - Lowercase   │    │ - Korean→Eng  │               │
│                       │ - Stopwords   │    │ - Synonyms    │               │
│                       └───────────────┘    └───────┬───────┘               │
│                                                    │                        │
│                              ┌─────────────────────┴─────────────────┐     │
│                              ▼                                       ▼     │
│                    ┌───────────────┐                       ┌───────────────┐
│                    │ TF-IDF Search │                       │ FTS5 Search   │
│                    │               │                       │               │
│                    │ - Vectorize   │                       │ - BM25 Rank   │
│                    │ - Cosine Sim  │                       │ - Phrase Match│
│                    └───────┬───────┘                       └───────┬───────┘
│                            │                                       │        │
│                            └───────────────┬───────────────────────┘        │
│                                            ▼                                │
│                                  ┌───────────────┐                         │
│                                  │ Hybrid Ranking│                         │
│                                  │               │                         │
│                                  │ Score =       │                         │
│                                  │ α×BM25 +      │                         │
│                                  │ β×TF-IDF +    │                         │
│                                  │ γ×Keyword     │                         │
│                                  └───────┬───────┘                         │
│                                          │                                  │
│                                          ▼                                  │
│                                  ┌───────────────┐                         │
│                                  │ LLM Response  │                         │
│                                  │ Generation    │                         │
│                                  │               │                         │
│                                  │ Ollama API    │                         │
│                                  │ or GGUF Model │                         │
│                                  └───────────────┘                         │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

#### 3.2.2 Key Classes and Methods

```python
class LocalRAGSystem:
    """Main RAG engine with TF-IDF + LLM integration"""
    
    def __init__(self):
        self.vectorizer = TfidfVectorizer()  # scikit-learn
        self.tfidf_matrix = None
        self.documents = []
        self.doc_metadata = []
        self.ollama_available = False
    
    # Core Methods
    def build_index(self, data_files: dict) -> bool
    def search(self, query: str, top_k: int = 10) -> List[Dict]
    def query(self, question: str, lang: str = 'ko') -> str
    def expand_query(self, query: str) -> str
    def _translate_korean_keywords(self, text: str) -> str
```

#### 3.2.3 Query Expansion System

The system translates Korean technical terms to English for improved search accuracy:

| Korean | English Expansion |
|--------|-------------------|
| 바이어스 | Bias |
| 고주파 | RF, Radio Frequency |
| 플라즈마 | Plasma |
| 에칭 | Etching, Etch |
| 챔버 | Chamber |
| 웨이퍼 | Wafer |
| 온도 | Temperature |

#### 3.2.4 Version Typo Correction

Handles common version string typos:

```python
# Patterns implemented in local_rag.py
"P33-HF16" → "SP33-HF16"  # Missing 'S' prefix
"HG15" → "HF15"           # Wrong letter (G → F)
```

### 3.3 swrn_indexer.py - PDF Document Indexer

**File Size**: 2,757 lines  
**Primary Purpose**: PDF parsing and SQLite FTS5 full-text search indexing

#### 3.3.1 Database Schema

```sql
-- PDF file metadata
CREATE TABLE pdf_files (
    id INTEGER PRIMARY KEY,
    filename TEXT UNIQUE,
    filepath TEXT,
    sw_version TEXT,
    file_size INTEGER,
    page_count INTEGER,
    indexed_at TEXT
);

-- FTS5 virtual table for full-text search
CREATE VIRTUAL TABLE page_content USING fts5(
    file_id,
    page_num,
    content,
    tokenize='unicode61'
);

-- PR number index for fast lookups
CREATE TABLE pr_index (
    pr_number TEXT,
    file_id INTEGER,
    page_num INTEGER,
    context TEXT,
    pr_type TEXT DEFAULT 'unknown',
    PRIMARY KEY (pr_number, file_id, page_num),
    FOREIGN KEY (file_id) REFERENCES pdf_files(id)
);
```

#### 3.3.2 Key Features

| Feature | Implementation |
|---------|----------------|
| **PDF Parsing** | PyMuPDF (fitz) library |
| **Full-Text Search** | SQLite FTS5 with unicode61 tokenizer |
| **PR Detection** | Regex pattern `PR-\d{5,6}` |
| **PR Classification** | `new_feature` vs `issue_fix` detection |
| **Version Parsing** | Tuple-based sorting: `(major, minor, patch, SP, HF)` |

#### 3.3.3 Version Parsing Algorithm

```python
def parse_sw_version(version_str: str) -> Tuple[int, int, int, int, int]:
    """
    Convert version string to sortable tuple
    
    Examples:
        "1.8.4-SP28-HF11-Release" → (1, 8, 4, 28, 11)
        "1.8.4-SP28-Release"      → (1, 8, 4, 28, 0)
        "1.8.4-SP27-B2-Release"   → (1, 8, 4, 27, -2)  # B build < HF
    """
```

#### 3.3.4 PR Type Detection

The indexer distinguishes between:
- **New Features**: Found under "New and Enhanced Features" section
- **Issue Fixes**: Found under "Problem Report and Escalations" section

```python
def _detect_pr_type(self, text: str, pr_position: int) -> str:
    """
    Returns: 'new_feature' | 'issue_fix' | 'unknown'
    """
```

### 3.4 config.py - Environment Configuration

**File Size**: 125 lines  
**Primary Purpose**: Auto-detection of deployment environment (local vs server)

```python
class Config:
    """Environment auto-detection based configuration"""
    
    # Base directory (relative to script location)
    BASE_DIR = Path(__file__).parent.resolve()
    
    # Environment detection
    IS_SERVER = 'server' in hostname or os.path.exists(r"C:\FlaskDashboard\app")
    
    # Path configuration
    DATA_DIR = BASE_DIR / "data"
    STATIC_DIR = BASE_DIR / "static"
    TEMPLATES_DIR = BASE_DIR / "templates"
    LOCAL_RAG_INDEX_DIR = BASE_DIR / "local_rag_index"
    
    # Data file accessors
    @classmethod
    def get_tool_info_csv(cls) -> Path
    @classmethod
    def get_issues_tracking_csv(cls) -> Path
    @classmethod
    def get_gguf_model_path(cls) -> str
```

---

## 4. Search Pipeline Architecture

### 4.1 Hybrid Search Model

The system employs a three-component hybrid search:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         Hybrid Search Scoring                               │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  Final Score = α × BM25_Score + β × TF-IDF_Score + γ × Keyword_Score        │
│                                                                             │
│  Where: α = 0.4, β = 0.4, γ = 0.2                                          │
│                                                                             │
│  ┌──────────────────────────────────────────────────────────────────────┐  │
│  │                                                                      │  │
│  │  BM25 (Sparse)          TF-IDF (Dense-ish)      Keyword Match        │  │
│  │  ┌─────────────┐        ┌─────────────┐        ┌─────────────┐       │  │
│  │  │             │        │             │        │             │       │  │
│  │  │  FTS5 Index │        │ Vectorizer  │        │ Phrase      │       │  │
│  │  │  BM25 Rank  │        │ Cosine Sim  │        │ Matching    │       │  │
│  │  │             │        │             │        │             │       │  │
│  │  │  Weight:40% │        │  Weight:40% │        │  Weight:20% │       │  │
│  │  └─────────────┘        └─────────────┘        └─────────────┘       │  │
│  │                                                                      │  │
│  └──────────────────────────────────────────────────────────────────────┘  │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 4.2 BM25 Algorithm Implementation

```
BM25(D, Q) = Σ IDF(qi) × [f(qi, D) × (k1 + 1)] / [f(qi, D) + k1 × (1 - b + b × |D|/avgdl)]

Where:
- D = Document
- Q = Query terms
- f(qi, D) = Term frequency in document
- |D| = Document length
- avgdl = Average document length
- k1 = 1.2 (term saturation parameter)
- b = 0.75 (length normalization)
```

### 4.3 TF-IDF Implementation

```python
# Using scikit-learn TfidfVectorizer
vectorizer = TfidfVectorizer(
    max_features=10000,
    ngram_range=(1, 2),
    min_df=2,
    max_df=0.95
)

# Cosine similarity for ranking
similarity = cosine_similarity(query_vector, doc_vectors)
```

### 4.4 Phrase Match Scoring

| Match Type | Score | Description |
|------------|-------|-------------|
| Exact Phrase in Affected Function | 2000 | "Bias RF" found as-is |
| All Words Present (Any Order) | 1500 | All query terms found |
| Partial Match (≥70%) | 1000 | Most terms found |
| Loose Match (≥50%) | 800 | Half or more terms |
| Minimal Match | 500 | Some terms found |

### 4.5 AND/OR Filter Strategy

```python
# Search strategy with fallback
def search(query: str) -> List[Dict]:
    # 1. Try AND filter (all original query tokens)
    results = fts5_search_and(query)
    
    if len(results) < min_required:
        # 2. Fallback to OR filter
        results = fts5_search_or(query)
    
    # 3. Apply hybrid ranking
    return hybrid_rank(results)
```

---

## 5. Authentication & Security Model

### 5.1 User Storage Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                      User Authentication Flow                               │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ┌──────────────┐         ┌──────────────┐         ┌──────────────┐        │
│  │   Client     │   POST  │   Flask      │   R/W   │  users.json  │        │
│  │  (Browser)   │────────▶│  Session     │────────▶│  (Encrypted) │        │
│  └──────────────┘         └──────────────┘         └──────────────┘        │
│        │                         │                        │                 │
│        │ Cookie:                 │ Validate:              │ Format:         │
│        │ session_id              │ - Username             │ ENC: + XOR      │
│        │                         │ - SHA256(pwd)          │ encrypted data  │
│        │                         │ - IP logging           │                 │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 5.2 Encryption Implementation

#### XOR Encryption (File-level)

```python
ENCRYPTION_KEY = b'SSS_Dashboard_Secret_Key_2025!'

def _xor_encrypt_decrypt(data: bytes, key: bytes) -> bytes:
    """Simple XOR cipher for file encryption"""
    return bytes([b ^ key[i % len(key)] for i, b in enumerate(data)])

# File format: b'ENC:' + encrypted_json_data
```

#### Password Hashing (SHA256 + Salt)

```python
def _hash_password(password: str) -> str:
    """SHA256 hash with static salt"""
    salt = "SSS_Dashboard_Salt_2025"
    return hashlib.sha256(f"{salt}{password}".encode()).hexdigest()
```

### 5.3 Session Management

| Feature | Implementation |
|---------|----------------|
| Session Storage | Flask server-side sessions |
| Session Key | `secrets.token_hex(32)` - 256-bit random |
| Cookie Settings | HTTPOnly, Secure (production) |
| Timeout | Browser session (closes with browser) |

### 5.4 Access Logging

```python
def log_access(username: str, action: str, ip_address: str):
    """
    Audit trail with 1000-entry rolling log
    
    Log entry format:
    {
        "username": "jerrad",
        "action": "login_success",
        "ip_address": "192.168.1.100",
        "timestamp": "2024-12-03T10:30:00"
    }
    """
```

### 5.5 Registered Users (Production)

| Username | Role | Access Level |
|----------|------|--------------|
| Jerrad | admin | Full access + user management |
| Korea | user | Dashboard + Search |
| lam | user | Dashboard + Search |

---

## 6. Data Management Layer

### 6.1 Data Sources

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           Data Sources                                       │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ┌────────────────────────────────────────────────────────────────────┐    │
│  │                         CSV/Excel Files                             │    │
│  │  ┌──────────────────┐  ┌──────────────────┐  ┌──────────────────┐  │    │
│  │  │ Issues Tracking  │  │ SW_IB_Version    │  │ SKH_tool_info    │  │    │
│  │  │      .csv        │  │     .csv         │  │    _fixed.csv    │  │    │
│  │  └──────────────────┘  └──────────────────┘  └──────────────────┘  │    │
│  │  ┌──────────────────┐  ┌──────────────────┐                        │    │
│  │  │ Ticket Details   │  │ FiF Sw Upgrade   │                        │    │
│  │  │     .xlsx        │  │    Plan.xlsx     │                        │    │
│  │  └──────────────────┘  └──────────────────┘                        │    │
│  └────────────────────────────────────────────────────────────────────┘    │
│                                                                             │
│  ┌────────────────────────────────────────────────────────────────────┐    │
│  │                         PDF Documents                               │    │
│  │                                                                      │    │
│  │  data/SWRN/                                                         │    │
│  │  ├── Version_1.8.4-SP28-Release_ReleaseNotes.pdf                   │    │
│  │  ├── Version_1.8.4-SP29-HF10-Release_ReleaseNotes.pdf              │    │
│  │  ├── ... (416 files total)                                         │    │
│  │  └── Version_1.8.4-SP35-Release_ReleaseNotes.pdf                   │    │
│  │                                                                      │    │
│  │  Total Size: ~500 MB (PDF files)                                   │    │
│  │  Index Size: ~195 MB (SQLite FTS5)                                 │    │
│  └────────────────────────────────────────────────────────────────────┘    │
│                                                                             │
│  ┌────────────────────────────────────────────────────────────────────┐    │
│  │                         Indexed Data                                │    │
│  │  ┌──────────────────┐  ┌──────────────────┐  ┌──────────────────┐  │    │
│  │  │ swrn_index.db    │  │ tfidf_cache.pkl  │  │ users.json       │  │    │
│  │  │ (SQLite FTS5)    │  │ (TF-IDF Matrix)  │  │ (XOR Encrypted)  │  │    │
│  │  │ ~195 MB          │  │ ~5 MB            │  │ ~1 KB            │  │    │
│  │  └──────────────────┘  └──────────────────┘  └──────────────────┘  │    │
│  └────────────────────────────────────────────────────────────────────┘    │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 6.2 Data Processing Pipeline

```python
# CSV loading with pandas
df = pd.read_csv(csv_path, encoding='utf-8')

# Excel loading with openpyxl engine
df = pd.read_excel(xlsx_path, engine='openpyxl')

# Data cleaning and normalization
df.columns = df.columns.str.strip()
df = df.fillna('')
```

### 6.3 Caching Strategy

| Cache Type | Duration | Purpose |
|------------|----------|---------|
| SharePoint Data | 5 minutes | Reduce API calls |
| PowerBI Data | 5 minutes | Reduce API calls |
| TF-IDF Matrix | Persistent | Avoid re-vectorization |
| FTS5 Index | Persistent | Full-text search |

---

## 7. Frontend Architecture

### 7.1 UI Framework Stack

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         Frontend Architecture                                │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                       Tailwind CSS (CDN)                             │   │
│  │   - Utility-first styling                                            │   │
│  │   - Dark mode support (class-based)                                  │   │
│  │   - Responsive design                                                │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                         Chart Libraries                              │   │
│  │  ┌─────────────────┐         ┌─────────────────┐                    │   │
│  │  │   Chart.js      │         │    ECharts      │                    │   │
│  │  │                 │         │                 │                    │   │
│  │  │ - Pie charts    │         │ - Advanced viz  │                    │   │
│  │  │ - Bar charts    │         │ - Animations    │                    │   │
│  │  │ - Line charts   │         │ - Interactivity │                    │   │
│  │  └─────────────────┘         └─────────────────┘                    │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                         AG-Grid Community                            │   │
│  │   - Enterprise-grade data tables                                     │   │
│  │   - Sorting, filtering, pagination                                   │   │
│  │   - Column resizing                                                  │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                         Custom Components                            │   │
│  │   - Glassmorphism cards                                              │   │
│  │   - Skeleton loading animations                                      │   │
│  │   - Multi-select checkbox dropdowns                                  │   │
│  │   - Dark mode toggle                                                 │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 7.2 Dashboard Tabs

| Tab | Description | Key Features |
|-----|-------------|--------------|
| **Main Page** | Overview dashboard | KPI cards, trend charts, CXL3 summary |
| **Issue Tracking** | Issue management | Status distribution, priority analysis |
| **PUCA** | PUCA analysis | Progress tracking, completion rates |
| **Ticket Details** | Support tickets | Ticket timeline, resolution metrics |
| **SW I/B Version** | Software inventory | Version distribution, upgrade tracking |
| **PR Status** | PR management | PR type breakdown, status flow |
| **CXL3** | CXL3 dedicated | FIF/Side Effect/Rollback charts |
| **AI Chat** | K-Bot interface | Natural language search, PR lookup |

### 7.3 Theme System

```javascript
// Dark mode implementation
tailwind.config = {
    darkMode: 'class',  // Toggle via html.dark class
    theme: {
        extend: {
            colors: {
                primary: { /* teal palette */ },
                dark: { /* slate palette */ }
            }
        }
    }
}

// CSS Variables for theming
:root {
    --card-bg: rgba(255, 255, 255, 0.95);
    --text-primary: #1e293b;
}

html.dark {
    --card-bg: rgba(30, 41, 59, 0.85);
    --text-primary: #f1f5f9;
}
```

---

## 8. LLM Integration

### 8.1 Ollama Service Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         LLM Integration Layer                                │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                       Ollama Service                                 │   │
│  │                                                                       │   │
│  │   URL: http://localhost:11434                                        │   │
│  │   Model: llama3.2-local                                              │   │
│  │   Base: Llama 3.2 3B Instruct                                        │   │
│  │                                                                       │   │
│  │   ┌─────────────────────────────────────────────────────────────┐   │   │
│  │   │              GGUF Model Specification                       │   │   │
│  │   │                                                              │   │   │
│  │   │   File: Llama-3.2-3B-Instruct-Q4_K_M.gguf                  │   │   │
│  │   │   Size: ~2 GB                                               │   │   │
│  │   │   Quantization: Q4_K_M (4-bit mixed precision)             │   │   │
│  │   │   Parameters: 3 Billion                                     │   │   │
│  │   │   Context Length: 8192 tokens                               │   │   │
│  │   │                                                              │   │   │
│  │   └─────────────────────────────────────────────────────────────┘   │   │
│  │                                                                       │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                       Alternative: ctransformers                     │   │
│  │                                                                       │   │
│  │   Direct GGUF model loading (fallback when Ollama unavailable)      │   │
│  │                                                                       │   │
│  │   from ctransformers import AutoModelForCausalLM                    │   │
│  │   model = AutoModelForCausalLM.from_pretrained(                     │   │
│  │       model_path,                                                    │   │
│  │       model_type="llama",                                            │   │
│  │       gpu_layers=0  # CPU-only for compatibility                    │   │
│  │   )                                                                  │   │
│  │                                                                       │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 8.2 Prompt Engineering

#### K-Bot System Prompt (Korean)

```
당신은 'K-Bot'이라는 이름의 반도체 에칭 장비 기술 전문가 AI 어시스턴트입니다.

**성격과 대화 스타일:**
- 친근하고 따뜻한 톤으로 대화하지만, 기술적 전문성은 유지합니다
- 질문자의 의도를 정확히 파악하고, 핵심을 먼저 설명한 후 세부 사항을 덧붙입니다
- 복잡한 개념은 비유나 예시를 활용해 쉽게 설명합니다
- 불확실한 정보는 솔직히 인정하고, 확인할 방법을 제안합니다

**언어 규칙:**
- 반드시 한국어와 영어만 사용
- 기술 용어는 영어 그대로 사용 (예: Bias RF, TCP, ESC)
```

#### Response Format

```
1. Core answer (concise)
2. Detailed explanation
3. Related tips/additional info
4. Appropriate emoji usage (moderate)
```

### 8.3 RAG Context Injection

```python
def generate_response(query: str, context_docs: List[Dict]) -> str:
    """
    Generate LLM response with retrieved context
    
    Prompt structure:
    [System Prompt]
    [Few-shot Examples]
    [Retrieved Context Documents]
    [User Query]
    """
    
    prompt = f"""
    {KBOT_SYSTEM_PROMPT}
    
    {FEW_SHOT_EXAMPLES}
    
    관련 문서:
    {format_context(context_docs)}
    
    사용자 질문: {query}
    """
    
    return ollama_generate(prompt)
```

### 8.4 K-Bot Capabilities Reference Table

The following table provides a comprehensive overview of all capabilities available in the K-Bot AI assistant:

#### 8.4.1 Query Type Classification

| Category | Query Pattern | Detection Logic | Priority |
|----------|--------------|-----------------|----------|
| **Greeting** | "안녕", "hi", "hello" | Regex pattern match | Highest |
| **PR Direct** | "PR-XXXXXX" | 6-digit pattern | High |
| **Version Compare** | "SPxx vs SPxx" | Version range regex | High |
| **Keyword PR Search** | "OOO 관련 PR" | Keyword + "PR" suffix | Medium |
| **Concept Explanation** | "OOO 설명해줘" | Explanation suffix | Medium |
| **General Query** | Free text | Default fallback | Low |

#### 8.4.2 Complete K-Bot Capabilities Matrix

| Feature | Input Example | Data Source | Technology Stack | Processing Time | Output Format |
|---------|---------------|-------------|------------------|-----------------|---------------|
| **Greeting Response** | "안녕하세요", "K-Bot 소개" | Hardcoded templates | Pattern matching | <1ms | Emoji-rich text |
| **PR Direct Lookup** | "PR-123456" | `swrn_index.db` (pr_index) | SQLite direct query | 5-10ms | HTML detail card |
| **PR Content Search** | "PR-123456 내용" | `swrn_index.db` (pr_fts) | FTS5 BM25 lookup | 10-20ms | HTML detail card |
| **Keyword PR Search** | "Bias RF 관련 PR 찾아줘" | `swrn_index.db` (pr_fts) | FTS5 + Phrase Match scoring | 30-50ms | HTML PR table (max 10) |
| **Multi-Keyword Search** | "TCP power AND ESC temp" | `swrn_index.db` (pr_fts) | FTS5 boolean query | 30-50ms | HTML PR table |
| **Version Delta** | "SP33-HF15 vs SP33-HF16" | `swrn_index.db` (pr_index) | Range query + aggregation | 50-100ms | Delta summary HTML |
| **SWRN Compare** | "SP33-HF15 ~ SP33-HF16 비교" | `swrn_index.db` (pr_index) | `get_prs_between_versions()` | 50-100ms | PR list with counts |
| **SWRN PR Extract** | "SP33-HF16 PR 목록" | `swrn_index.db` (swrn_index) | Version match + PR join | 30-50ms | PR list HTML |
| **Concept Explanation** | "Bias RF 설명해줘" | CSV/Excel + TF-IDF index | TF-IDF → Ollama LLM | 2-5s | Natural language |
| **Technical Q&A** | "TCP power 역할이 뭐야?" | local_rag_index (TF-IDF) | RAG: TF-IDF + Ollama | 2-5s | Natural language |
| **Equipment Search** | "OPUS chamber 정보" | CSV datasets | TF-IDF similarity | 100-300ms | Markdown table |
| **Error Diagnosis** | "Error code E1234" | CSV + SWRN index | Multi-source search | 100-500ms | Diagnosis text |

#### 8.4.3 Search Technology Details

| Search Type | Algorithm | Index Used | Scoring Method | Result Limit |
|-------------|-----------|------------|----------------|--------------|
| **PR FTS Search** | SQLite FTS5 | `pr_fts` | BM25 + Phrase Match bonus | Top 100 → Re-rank to 10 |
| **Concept Search** | TF-IDF | `local_rag_index/` | Cosine similarity | Top 5 documents |
| **CSV Search** | Pandas + TF-IDF | In-memory DataFrame | Column-weighted match | All matches |
| **Version Range** | SQL BETWEEN | `pr_index.sp_version` | Numeric ordering | All in range |

#### 8.4.4 Phrase Match Scoring System

| Match Type | Score | Example Pattern |
|------------|-------|-----------------|
| **Exact phrase in title** | +2000 | Query "Bias RF" in PR title |
| **Exact phrase in content** | +1500 | Query "Bias RF" in PR content |
| **All words in title** | +1000 | "Bias" AND "RF" in title |
| **All words in content** | +800 | "Bias" AND "RF" in content |
| **Partial word match** | +500 | Some query words found |
| **FTS5 base score** | BM25 | SQLite built-in ranking |

#### 8.4.5 Response Format by Query Type

| Query Type | Response Structure | HTML Components |
|------------|-------------------|-----------------|
| **PR Detail** | Card with metadata | `<div class="pr-card">` with title, type, version, content |
| **PR Search Results** | Sortable table | `<table>` with PR#, Title, Type, SWRN, Score columns |
| **Version Delta** | Summary + PR list | `<div class="delta-summary">` + grouped PR table |
| **Concept Explanation** | Natural language | Markdown-formatted text with bullet points |
| **Greeting** | Informal text | Plain text with emoji decorations |

#### 8.4.6 Query Expansion & Korean-English Mapping

| Korean Term | English Mapping | Expansion Terms |
|-------------|-----------------|-----------------|
| 바이어스 | Bias | bias, rf bias, bias rf |
| 티씨피 | TCP | tcp, tcp power, transformer coupled plasma |
| 이에스씨 | ESC | esc, electrostatic chuck, chuck |
| 리플렉트 | Reflect | reflect, reflected, reflection |
| 임피던스 | Impedance | impedance, z, matching |
| 레시피 | Recipe | recipe, process recipe, rcp |
| 챔버 | Chamber | chamber, process chamber |
| 압력 | Pressure | pressure, press, mbar, torr |
| 가스 | Gas | gas, gas flow, flow |
| 온도 | Temperature | temperature, temp, thermal |

#### 8.4.7 Error Handling & Fallback Behavior

| Scenario | Detection | Fallback Action | User Message |
|----------|-----------|-----------------|--------------|
| **No PR found** | Empty result set | Suggest keyword search | "PR-XXXXXX를 찾을 수 없습니다. 키워드 검색을 시도해보세요." |
| **LLM timeout** | 30s timeout | Return TF-IDF results only | "AI 응답 시간 초과. 검색 결과만 표시합니다." |
| **Ollama unavailable** | Connection error | Use ctransformers fallback | Transparent fallback |
| **Empty query** | Whitespace only | Return greeting | Standard greeting response |
| **Ambiguous query** | Low confidence | Ask clarification | "질문을 더 구체적으로 해주세요." |

#### 8.4.8 Performance Benchmarks

| Operation | Cold Start | Warm Cache | 95th Percentile |
|-----------|------------|------------|-----------------|
| Greeting response | <1ms | <1ms | <1ms |
| PR direct lookup | 15ms | 5ms | 20ms |
| FTS5 keyword search | 80ms | 30ms | 100ms |
| TF-IDF concept search | 500ms | 200ms | 800ms |
| LLM generation (3B) | 5s | 2s | 8s |
| Full RAG pipeline | 6s | 3s | 10s |

---

## 9. API Endpoints Reference

### 9.1 Authentication APIs

| Endpoint | Method | Description | Auth Required |
|----------|--------|-------------|---------------|
| `/login` | GET | Login page | No |
| `/login` | POST | Authenticate user | No |
| `/signup` | POST | Register new user | No |
| `/logout` | GET | Terminate session | Yes |

### 9.2 Dashboard APIs

| Endpoint | Method | Description | Response |
|----------|--------|-------------|----------|
| `/dashboard` | GET | Main dashboard HTML | HTML |
| `/dashboard_stats` | GET | Tool statistics | JSON |
| `/puca_stats` | GET | PUCA analysis | JSON |
| `/ticket_stats` | GET | Ticket data | JSON |
| `/issue_stats` | GET | Issue tracking | JSON |
| `/pr_status` | GET | PR distribution | JSON |
| `/cxl3_stats` | GET | CXL3 metrics | JSON |
| `/sw_ib_stats` | GET | Software versions | JSON |

### 9.3 Search APIs

| Endpoint | Method | Description | Parameters |
|----------|--------|-------------|------------|
| `/chat` | POST | AI chat query | `message`, `mode` |
| `/pr_swrn_insights` | GET | SWRN insights | `pr_number` |
| `/pr_similar_search` | GET | Similar PR search | `query` |
| `/rag/status` | GET | RAG system status | - |

### 9.4 Data Export APIs

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/save_data` | POST | Save CSV edits |
| `/export_csv` | POST | Export filtered data |
| `/download_csv` | GET | Download file |

---

## 10. Deployment Architecture

### 10.1 Deployment Topology

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         Production Deployment                                │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                    Windows Server 2019+                              │   │
│  │                    IP: 10.173.135.202                                │   │
│  │                                                                       │   │
│  │   ┌─────────────────────────────────────────────────────────────┐   │   │
│  │   │              C:\FlaskDashboard\                             │   │   │
│  │   │                                                              │   │   │
│  │   │   ├── app\                                                  │   │   │
│  │   │   │   ├── Main_SSS.py                                       │   │   │
│  │   │   │   ├── local_rag.py                                      │   │   │
│  │   │   │   ├── swrn_indexer.py                                   │   │   │
│  │   │   │   ├── config.py                                         │   │   │
│  │   │   │   ├── templates\                                        │   │   │
│  │   │   │   ├── static\                                           │   │   │
│  │   │   │   └── data\                                             │   │   │
│  │   │   │       └── swrn_index.db (~195 MB)                       │   │   │
│  │   │   │                                                          │   │   │
│  │   │   ├── Llama-3.2-3B-Instruct-Q4_K_M.gguf (~2 GB)            │   │   │
│  │   │   └── QUICK_RESTART.bat                                     │   │   │
│  │   │                                                              │   │   │
│  │   └─────────────────────────────────────────────────────────────┘   │   │
│  │                                                                       │   │
│  │   ┌─────────────────────────────────────────────────────────────┐   │   │
│  │   │                 Service Configuration                       │   │   │
│  │   │                                                              │   │   │
│  │   │   Flask Port: 8060                                          │   │   │
│  │   │   Ollama Port: 11434                                        │   │   │
│  │   │   Debug Mode: True (development)                            │   │   │
│  │   │   Host: 0.0.0.0 (all interfaces)                            │   │   │
│  │   │                                                              │   │   │
│  │   └─────────────────────────────────────────────────────────────┘   │   │
│  │                                                                       │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                    Client Access                                     │   │
│  │                                                                       │   │
│  │   URL: http://10.173.135.202:8060/dashboard                         │   │
│  │   Intranet Access Only                                               │   │
│  │                                                                       │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 10.2 Quick Restart Procedure

```batch
@echo off
:: QUICK_RESTART.bat
cd /d C:\FlaskDashboard\app
taskkill /IM python.exe /F 2>nul
timeout /t 2 /nobreak >nul
start /B python Main_SSS.py
echo Server restarted successfully!
pause
```

### 10.3 Deployment Script (deploy.ps1)

```powershell
# Sync local to server
$serverPath = "\\10.173.135.202\c$\FlaskDashboard\app\"

# Files to deploy
$files = @(
    "Main_SSS.py",
    "local_rag.py", 
    "swrn_indexer.py",
    "config.py",
    "templates\*",
    "static\*",
    "data\swrn_index.db"
)

foreach ($file in $files) {
    Copy-Item $file $serverPath -Force -Recurse
}
```

---

## 11. Performance Characteristics

### 11.1 Response Time Metrics

| Operation | Typical Time | Notes |
|-----------|--------------|-------|
| FTS5 Search | ~10ms | SQLite indexed query |
| TF-IDF Ranking | ~30ms | 500 candidate documents |
| Hybrid Scoring | ~5ms | Score combination |
| PR Detail Lookup | ~30ms | PDF page parsing |
| LLM Response | 2-5s | Depends on context length |
| Full Search Pipeline | <1s | 20 results |

### 11.2 Resource Utilization

| Resource | Requirement | Notes |
|----------|-------------|-------|
| RAM | 4 GB minimum | 8 GB recommended for LLM |
| Disk | 3 GB | Index + GGUF model |
| CPU | 4 cores | LLM inference benefits from more |
| GPU | Optional | Not required for Q4 quantization |

### 11.3 Scalability Considerations

| Factor | Current Limit | Mitigation |
|--------|---------------|------------|
| Concurrent Users | ~50 | Session-based, stateless API |
| Document Count | 24,000+ PRs | FTS5 handles efficiently |
| Index Size | 195 MB | SQLite performs well |
| LLM Context | 8192 tokens | Truncation strategy |

---

## 12. Future Roadmap

### 12.1 Planned Enhancements

| Feature | Priority | Status |
|---------|----------|--------|
| **Neural Embeddings** | Medium | Research |
| **Vector Database** | Low | Evaluation |
| **Multi-language UI** | Medium | Planned |
| **Mobile Optimization** | High | In Progress |
| **Real-time Updates** | Medium | Planned |

### 12.2 Technical Debt

| Item | Impact | Resolution |
|------|--------|------------|
| Debug mode in production | Security | Disable before public release |
| Static salt in password hash | Security | Use per-user random salt |
| Synchronous LLM calls | Performance | Implement async endpoints |
| CDN dependencies | Reliability | Bundle critical assets |

### 12.3 Why No BERT/Neural Embeddings?

| Factor | Decision Rationale |
|--------|---------------------|
| **Hardware** | Server lacks GPU, CPU inference too slow |
| **Latency** | TF-IDF: 30ms vs BERT: 500ms+ on CPU |
| **Accuracy** | Technical domain vocabulary well-covered by TF-IDF |
| **Maintenance** | No model fine-tuning required |
| **Simplicity** | scikit-learn is production-proven |

---

## Appendix A: File Structure

```
flask_dashboard_project/
├── Main_SSS.py          # Flask web server (3,484 lines)
├── local_rag.py         # RAG system (3,767 lines)
├── swrn_indexer.py      # PDF indexer (2,757 lines)
├── config.py            # Configuration (125 lines)
├── requirements.txt     # Python dependencies
├── start_server.bat     # Local startup script
├── deploy.ps1           # Deployment script
│
├── data/
│   ├── swrn_index.db    # SQLite FTS5 database (~195 MB)
│   ├── users.json       # Encrypted user storage
│   ├── Issues Tracking.csv
│   ├── SW_IB_Version.csv
│   ├── SKH_tool_information_fixed.csv
│   └── SWRN/            # PDF documents (416 files)
│
├── static/
│   ├── style.css        # Custom styles
│   └── chart.min.js     # Chart.js library
│
├── templates/
│   └── dashboard.html   # Main UI (7,741 lines)
│
├── local_rag_index/     # TF-IDF cache
│
└── documentation/
    ├── TECHNICAL_WHITEPAPER_EN.md  # This document
    └── SWRN_Indexer_Whitepaper.md  # Korean version
```

---

## Appendix B: Key Dependencies

```
# requirements.txt
flask>=2.0.0
pandas>=1.5.0
openpyxl>=3.0.0
scikit-learn>=1.0.0
PyMuPDF>=1.23.0
requests>=2.28.0
ctransformers>=0.2.0  # Optional: GGUF direct loading
```

---

## Document Control

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 1.0 | Dec 2024 | K-Bot | Initial English version |
| 1.1 | Dec 2024 | K-Bot | Added Section 8.4: K-Bot Capabilities Reference Table |

---

*This document is auto-generated based on source code analysis and is intended for internal technical reference.*
