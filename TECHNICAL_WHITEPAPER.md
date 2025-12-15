# SSSS Dashboard Project - Technical Whitepaper
**Version:** 2.5
**Last Updated:** 2025-12-10

## 1. Executive Summary
The SSSS Dashboard is a comprehensive web-based monitoring and analytics platform designed to track software issues, upgrade trends, and technical documentation for semiconductor equipment. It integrates real-time data visualization with a Local RAG (Retrieval-Augmented Generation) system to provide intelligent search capabilities over technical release notes.

## 2. System Architecture

### 2.1 High-Level Overview
The system follows a monolithic architecture with a Flask backend serving both API endpoints and HTML templates.

*   **Frontend**: HTML5, CSS3, JavaScript (Vanilla), Chart.js
*   **Backend**: Python (Flask)
*   **Database**: 
    *   SQLite (`swrn_indexer.db`) for RAG index
    *   JSON (`users.json`) for Authentication
    *   CSV/Excel (`Issues Tracking.csv`, `Monthly_IB_CX_L3_SK_Hynix.xlsx`) for raw data
*   **AI/ML**: Local RAG with TF-IDF & Ollama (Llama 3.2)

### 2.2 Directory Structure
```
flask_dashboard_project/
├── app.py / Main_SSS.py    # Main Flask Application Entry Point
├── local_rag.py            # RAG System Logic (Search & Generation)
├── swrn_indexer.py         # PDF Indexing Service
├── data/                   # Data Storage
│   ├── users.json          # Encrypted User Database
│   ├── swrn_index.db       # Search Index Database
│   └── *.csv, *.xlsx       # Raw Data Files
├── static/                 # Static Assets (CSS, JS, Images)
├── templates/              # HTML Templates
└── documentation/          # Project Documentation
```

## 3. Core Technologies

### 3.1 Backend (Python/Flask)
*   **Framework**: Flask 3.0+
*   **Data Processing**: `pandas` for CSV/Excel manipulation, `openpyxl` for Excel read/write.
*   **Concurrency**: Thread-safe file operations for user authentication and logging.

### 3.2 Frontend (Web)
*   **Visualization**: `Chart.js` with `chartjs-plugin-datalabels` for interactive charts.
*   **Styling**: Custom CSS with responsive design (Dark/Light mode support).
*   **Interaction**: Asynchronous JavaScript (`fetch` API) for non-blocking data updates.

### 3.3 AI & Search (Local RAG)
*   **Indexing**: `PyMuPDF` (fitz) for high-fidelity PDF text extraction.
*   **Vectorization**: `scikit-learn` TF-IDF Vectorizer for fast, sparse retrieval.
*   **LLM Integration**: `Ollama` running local Llama 3.2 models for answer generation.
*   **NLP**: Custom Korean/English stopword filtering, Query Expansion, and Version Normalization (e.g., "P33" → "SP33").

### 3.4 Security
*   **Authentication**: Custom implementation using `users.json`.
    *   **Encryption**: File-level XOR encryption to prevent plain-text reading.
    *   **Hashing**: SHA-256 with salt for password storage.
*   **Session Management**: Flask `session` for state maintenance.

## 4. Key Features & Workflows

### 4.1 Dashboard Visualization
**Sequence:**
1.  **Data Loading**: Server reads `Issues Tracking.csv` and `Monthly_IB_CX_L3_SK_Hynix.xlsx` on startup/request.
2.  **Filtering**: Applies date ranges (3M, 6M, 1Y) and specific filters (Year/Quarter for CXL3).
3.  **API Response**: Returns JSON data containing statistics (Status counts, Failure rates).
4.  **Rendering**: Frontend JS processes JSON and updates Chart.js instances.

**Key Charts:**
*   **Main Page**: Issue Status, SW Upgrade Trend, CXL3 Stats.
*   **CXL3 Tab**: Detailed breakdown by Year/Quarter, FIF/Side Effect/Rollback rates.

### 4.2 Intelligent Search (RAG)
**Sequence:**
1.  **Indexing (Background)**: `swrn_indexer.py` scans `data/SWRN` for new PDF Release Notes, extracts text, and updates SQLite DB.
2.  **Query Processing**:
    *   User inputs query (e.g., "Bias RF 관련 설명해줘").
    *   **Normalization**: Fixes version typos (e.g., "HG16" → "HF16").
    *   **Expansion**: Adds synonyms (e.g., "Fixed" → "Solved", "Resolved").
    *   **Filtering**: Removes stopwords (Korean/English).
3.  **Retrieval**: TF-IDF cosine similarity finds top-k relevant document chunks.
4.  **Generation**:
    *   **Search Mode**: Returns raw snippets.
    *   **Explain Mode**: Sends snippets + Query to Ollama LLM to generate a natural language summary.

### 4.3 User Management
*   **Login**: Validates credentials against hashed values in `users.json`.
*   **Role-Based Access**: Admin/User roles (Admin can manage users).

## 5. Deployment & Maintenance

### 5.1 Environment
*   **OS**: Windows Server
*   **Runtime**: Python 3.12+ (Virtual Environment)
*   **Service**: Runs as a background process or via Task Scheduler.

### 5.2 Deployment Scripts
*   `deploy_simple.ps1`: Lightweight file copy to server.
*   `restart_flask.bat`: Graceful service restart (Kill process -> Clear Cache -> Start).
*   `QUICK_RESTART.bat`: Emergency restart script on server.

## 6. Recent Updates (v2.5)
*   **CXL3 Integration**: Added dedicated tab and Main Page widgets for CXL3 metrics.
*   **Search Improvements**: Fixed Korean stopword filtering logic for better accuracy.
*   **Fuzzy Matching**: Implemented regex-based version typo correction.
*   **Security**: Enhanced user credential storage with encryption.

---
*Confidential - Internal Use Only*
