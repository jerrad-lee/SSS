from flask import Flask, render_template, send_file, request, jsonify, Response, redirect, url_for, session
import pandas as pd
import os
import sys
import matplotlib.colors as mcolors
import random
import json
import re
import traceback
from io import StringIO
from datetime import datetime
from pathlib import Path
from functools import wraps
import threading
import hashlib
import secrets

# Windows 콘솔에서 UTF-8 출력 설정
if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except:
        pass

# 환경 자동 감지 설정
from config import Config
Config.print_config()

app = Flask(__name__)
app.secret_key = secrets.token_hex(32)  # Session encryption key

# ============ User Authentication System ============
USERS_FILE = Path(__file__).parent / 'data' / 'users.json'
users_lock = threading.Lock()  # Thread-safe file access

# Simple XOR encryption key (change this in production)
ENCRYPTION_KEY = b'SSS_Dashboard_Secret_Key_2025!'

def _xor_encrypt_decrypt(data: bytes, key: bytes) -> bytes:
    """Simple XOR encryption/decryption"""
    return bytes([b ^ key[i % len(key)] for i, b in enumerate(data)])

def _hash_password(password: str) -> str:
    """Hash password with salt using SHA256"""
    salt = "SSS_Dashboard_Salt_2025"
    return hashlib.sha256(f"{salt}{password}".encode()).hexdigest()

def load_users():
    """Load users from encrypted JSON file with thread safety"""
    with users_lock:
        try:
            if USERS_FILE.exists():
                with open(USERS_FILE, 'rb') as f:
                    encrypted_data = f.read()
                
                # Check if file is encrypted (starts with specific marker)
                if encrypted_data.startswith(b'ENC:'):
                    decrypted = _xor_encrypt_decrypt(encrypted_data[4:], ENCRYPTION_KEY)
                    return json.loads(decrypted.decode('utf-8'))
                else:
                    # Legacy plain text JSON - migrate to encrypted
                    with open(USERS_FILE, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                    # Hash existing plain passwords
                    for username in data.get('users', {}):
                        pwd = data['users'][username].get('password', '')
                        if len(pwd) < 64:  # Not already hashed
                            data['users'][username]['password'] = _hash_password(pwd)
                    # Save encrypted
                    save_users(data)
                    return data
        except Exception as e:
            print(f"⚠️ Error loading users: {e}")
    return {"users": {}, "access_log": []}

def save_users(data):
    """Save users to encrypted JSON file with thread safety"""
    with users_lock:
        try:
            json_data = json.dumps(data, indent=4, ensure_ascii=False)
            encrypted = b'ENC:' + _xor_encrypt_decrypt(json_data.encode('utf-8'), ENCRYPTION_KEY)
            with open(USERS_FILE, 'wb') as f:
                f.write(encrypted)
            return True
        except Exception as e:
            print(f"⚠️ Error saving users: {e}")
            return False

def log_access(username, action, ip_address):
    """Log user access for security auditing"""
    data = load_users()
    log_entry = {
        "username": username,
        "action": action,
        "ip_address": ip_address,
        "timestamp": datetime.now().isoformat()
    }
    data.setdefault("access_log", []).append(log_entry)
    # Keep only last 1000 entries
    if len(data["access_log"]) > 1000:
        data["access_log"] = data["access_log"][-1000:]
    save_users(data)
    print(f"📝 Access log: {username} - {action} from {ip_address}")

def login_required(f):
    """Decorator to require login for routes - returns JSON for API calls"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user' not in session:
            # Check if it's an API request (AJAX)
            if request.is_json or request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return jsonify({'error': 'Authentication required', 'redirect': '/login'}), 401
            return redirect(url_for('login_page'))
        return f(*args, **kwargs)
    return decorated_function

# Load environment variables at startup (Windows User-level)
print("🔧 Loading environment variables from Windows Registry...")
try:
    import winreg
    
    # Read User environment variables from Windows Registry
    reg = winreg.ConnectRegistry(None, winreg.HKEY_CURRENT_USER)
    key = winreg.OpenKey(reg, r"Environment")
    
    try:
        google_key, _ = winreg.QueryValueEx(key, "GOOGLE_API_KEY")
        os.environ['GOOGLE_API_KEY'] = google_key
        print(f"✅ Loaded GOOGLE_API_KEY: {google_key[:20]}...")
    except:
        print("⚠️ GOOGLE_API_KEY not found in registry")
    
    try:
        groq_key, _ = winreg.QueryValueEx(key, "GROQ_API_KEY")
        os.environ['GROQ_API_KEY'] = groq_key
        print(f"✅ Loaded GROQ_API_KEY: {groq_key[:20]}...")
    except:
        print("⚠️ GROQ_API_KEY not found in registry")
    
    try:
        openrouter_key, _ = winreg.QueryValueEx(key, "OPENROUTER_API_KEY")
        os.environ['OPENROUTER_API_KEY'] = openrouter_key
        print(f"✅ Loaded OPENROUTER_API_KEY: {openrouter_key[:20]}...")
    except:
        print("⚠️ OPENROUTER_API_KEY not found in registry")
    
    try:
        deepseek_key, _ = winreg.QueryValueEx(key, "DEEPSEEK_API_KEY")
        os.environ['DEEPSEEK_API_KEY'] = deepseek_key
        print(f"✅ Loaded DEEPSEEK_API_KEY: {deepseek_key[:20]}...")
    except:
        print("⚠️ DEEPSEEK_API_KEY not found in registry")
    
    winreg.CloseKey(key)
    print("✅ Environment variables loaded successfully")
except Exception as e:
    print(f"⚠️ Could not load environment variables from registry: {e}")
    print("Using system environment variables instead...")

# SharePoint Configuration
SHAREPOINT_SITE_URL = "https://lamresearch.sharepoint.com/sites/SKHEtch2300softwareTeam"
SHAREPOINT_LIST_NAME = "Issues Tracking"

# Power BI Configuration
POWERBI_GROUP_ID = "6855773d-d300-4246-bc6c-857ca094ea82"
POWERBI_REPORT_ID = "12e68e5a-0135-4bbc-b9a5-0d96ee80ac8d"
POWERBI_DATASET_ID = None  # Will be fetched dynamically

# Cache for SharePoint data (refresh every 5 minutes)
sharepoint_cache = {
    'data': None,
    'last_update': None,
    'cache_duration': 300  # 5 minutes in seconds
}

# Cache for Power BI data (refresh every 5 minutes)
powerbi_cache = {
    'data': None,
    'last_update': None,
    'cache_duration': 300  # 5 minutes in seconds
}

def get_sharepoint_credentials():
    """
    Get SharePoint credentials from environment variables or config file
    For security, credentials should not be hardcoded
    Returns: (username, password) or ('oauth', client_id, client_secret, tenant_id)
    """
    # Option 1: Environment variables (recommended)
    username = os.getenv('SHAREPOINT_USER')
    password = os.getenv('SHAREPOINT_PASSWORD')
    
    # OAuth credentials
    client_id = os.getenv('AZURE_CLIENT_ID')
    client_secret = os.getenv('AZURE_CLIENT_SECRET')
    tenant_id = os.getenv('AZURE_TENANT_ID')
    
    if client_id and client_secret and tenant_id:
        return ('oauth', client_id, client_secret, tenant_id)
    
    # Option 2: Config file (create sharepoint_config.txt with username and password)
    if not username or not password:
        config_file = 'sharepoint_config.txt'
        if os.path.exists(config_file):
            with open(config_file, 'r', encoding='utf-8') as f:
                content = f.read()
                
                # Check if it's OAuth format
                if '[OAUTH]' in content:
                    lines = [line.strip() for line in content.split('\n') if line.strip() and not line.strip().startswith('[')]
                    config = {}
                    for line in lines:
                        if '=' in line:
                            key, value = line.split('=', 1)
                            config[key.strip()] = value.strip()
                    
                    client_id = config.get('client_id')
                    client_secret = config.get('client_secret')
                    tenant_id = config.get('tenant_id')
                    
                    if client_id and client_secret and tenant_id:
                        return ('oauth', client_id, client_secret, tenant_id)
                else:
                    # Basic format
                    lines = content.split('\n')
                    if len(lines) >= 2:
                        username = lines[0].strip()
                        password = lines[1].strip()
    
    return username, password

def fetch_sharepoint_data():
    """
    Fetch data from SharePoint List using Microsoft Graph API
    Returns DataFrame or None if failed
    """
    global sharepoint_cache
    
    # Check cache first
    now = datetime.now()
    if sharepoint_cache['data'] is not None and sharepoint_cache['last_update']:
        elapsed = (now - sharepoint_cache['last_update']).total_seconds()
        if elapsed < sharepoint_cache['cache_duration']:
            print(f"Using cached SharePoint data (age: {int(elapsed)}s)")
            return sharepoint_cache['data']
    
    try:
        import requests
        from requests.auth import HTTPBasicAuth
        
        credentials = get_sharepoint_credentials()
        
        if not credentials or credentials[0] is None:
            print("SharePoint credentials not configured")
            return None
        
        # Check if OAuth or Basic Auth
        if credentials[0] == 'oauth':
            # OAuth2.0 Authentication
            _, client_id, client_secret, tenant_id = credentials
            
            print(f"Attempting OAuth2.0 authentication...")
            
            try:
                import msal
                
                authority = f"https://login.microsoftonline.com/{tenant_id}"
                scope = ["https://graph.microsoft.com/.default"]
                
                # Create MSAL app
                app = msal.ConfidentialClientApplication(
                    client_id,
                    authority=authority,
                    client_credential=client_secret
                )
                
                # Acquire token
                result = app.acquire_token_for_client(scopes=scope)
                
                if "access_token" in result:
                    access_token = result["access_token"]
                    print("✅ OAuth token acquired")
                    
                    # Use Microsoft Graph API to get SharePoint list items
                    # Extract site details from URL
                    # Format: https://TENANT.sharepoint.com/sites/SITENAME
                    site_parts = SHAREPOINT_SITE_URL.split('/')
                    tenant_domain = site_parts[2]  # e.g., lamresearch.sharepoint.com
                    site_path = '/'.join(site_parts[3:])  # e.g., sites/SKHEtch2300softwareTeam
                    
                    # Get site ID using Graph API
                    graph_url = f"https://graph.microsoft.com/v1.0/sites/{tenant_domain}:/{site_path}"
                    headers = {
                        'Authorization': f'Bearer {access_token}',
                        'Accept': 'application/json'
                    }
                    
                    site_response = requests.get(graph_url, headers=headers, timeout=30)
                    
                    if site_response.status_code == 200:
                        site_id = site_response.json()['id']
                        print(f"✅ Site ID: {site_id[:50]}...")
                        
                        # Get list ID
                        lists_url = f"https://graph.microsoft.com/v1.0/sites/{site_id}/lists"
                        lists_response = requests.get(lists_url, headers=headers, timeout=30)
                        
                        if lists_response.status_code == 200:
                            lists = lists_response.json().get('value', [])
                            list_id = None
                            for lst in lists:
                                if lst.get('displayName') == SHAREPOINT_LIST_NAME:
                                    list_id = lst['id']
                                    break
                            
                            if list_id:
                                print(f"✅ List ID: {list_id}")
                                
                                # Get list items (paginated)
                                items_url = f"https://graph.microsoft.com/v1.0/sites/{site_id}/lists/{list_id}/items?$expand=fields&$top=5000"
                                items_response = requests.get(items_url, headers=headers, timeout=60)
                                
                                if items_response.status_code == 200:
                                    items_data = items_response.json()
                                    items = items_data.get('value', [])
                                    
                                    print(f"✅ Graph API Success! Fetched {len(items)} items")
                                    
                                    # Convert to DataFrame
                                    data = []
                                    for item in items:
                                        fields = item.get('fields', {})
                                        
                                        # Parse date
                                        date_reported = fields.get('Date_x0020_reported') or fields.get('Created')
                                        if date_reported:
                                            try:
                                                date_obj = pd.to_datetime(date_reported)
                                                date_str = date_obj.strftime('%m/%d/%Y')
                                            except:
                                                date_str = str(date_reported)
                                        else:
                                            date_str = ''
                                        
                                        data.append({
                                            'ID': fields.get('id'),
                                            'Title': fields.get('Title', ''),
                                            'date_reported': date_str,
                                            'fab': fields.get('Fab', ''),
                                            'module_type': fields.get('Module_x0020_Type', ''),
                                            'issue': fields.get('Title', ''),
                                            'solution': fields.get('Solution', ''),
                                            'current_status': fields.get('Current_x0020_Status', ''),
                                            'pr_or_es': fields.get('PR_x0020_or_x0020_ES', ''),
                                            'pr_url': f"https://jira.lamresearch.com/browse/{fields.get('PR_x0020_or_x0020_ES', '')}" if fields.get('PR_x0020_or_x0020_ES') else '#',
                                            'priority': fields.get('Priority', 'Normal'),
                                            'issued_by': fields.get('Issued_x0020_by', '')
                                        })
                                    
                                    df = pd.DataFrame(data)
                                    
                                    # Update cache
                                    sharepoint_cache['data'] = df
                                    sharepoint_cache['last_update'] = now
                                    
                                    return df
                                else:
                                    print(f"Failed to get list items: {items_response.status_code}")
                            else:
                                print(f"List '{SHAREPOINT_LIST_NAME}' not found")
                        else:
                            print(f"Failed to get lists: {lists_response.status_code}")
                    else:
                        print(f"Failed to get site: {site_response.status_code}")
                        print(f"Response: {site_response.text[:500]}")
                else:
                    print(f"OAuth token acquisition failed: {result.get('error_description', 'Unknown error')}")
                    
            except ImportError:
                print("⚠️ msal library not installed. Run: pip install msal")
            except Exception as e:
                print(f"⚠️ OAuth error: {e}")
                traceback.print_exc()
        
        else:
            # Basic Authentication (Legacy - will not work for SharePoint Online)
            username, password = credentials
            
            print(f"Attempting REST API with Basic Auth (likely to fail on SharePoint Online)...")
        
        # Try REST API as fallback (both for Basic Auth and if OAuth fails)
        username, password = credentials[:2] if credentials[0] != 'oauth' else (None, None)
        
        if username and password:
            site_url = SHAREPOINT_SITE_URL.rstrip('/')
            list_name = SHAREPOINT_LIST_NAME
            
            # Try multiple authentication methods
            
            # Method 1: Direct REST API call (works for some on-prem SharePoint)
            api_url = f"{site_url}/_api/web/lists/getbytitle('{list_name}')/items?$top=5000"
            
            headers = {
                'Accept': 'application/json;odata=verbose',
                'Content-Type': 'application/json;odata=verbose',
            }
            
            try:
                print(f"Trying REST API: {api_url}")
                response = requests.get(
                    api_url,
                    auth=HTTPBasicAuth(username, password),
                    headers=headers,
                    timeout=30
                )
            
                if response.status_code == 200:
                    data_json = response.json()
                    items = data_json.get('d', {}).get('results', [])
                    
                    if len(items) > 0:
                        print(f"✅ REST API Success! Fetched {len(items)} items")
                        
                        # Convert to DataFrame
                        data = []
                        for item in items:
                            # Parse date
                            date_reported = item.get('Date_x0020_reported') or item.get('Created')
                            if date_reported:
                                try:
                                    if isinstance(date_reported, str):
                                        date_obj = pd.to_datetime(date_reported)
                                    else:
                                        date_obj = pd.Timestamp(date_reported)
                                    date_str = date_obj.strftime('%m/%d/%Y')
                                except:
                                    date_str = str(date_reported)
                            else:
                                date_str = ''
                            
                            data.append({
                                'ID': item.get('ID'),
                                'Title': item.get('Title', ''),
                                'date_reported': date_str,
                                'fab': item.get('Fab', ''),
                                'module_type': item.get('Module_x0020_Type', ''),
                                'issue': item.get('Title', ''),
                                'solution': item.get('Solution', ''),
                                'current_status': item.get('Current_x0020_Status', ''),
                                'pr_or_es': item.get('PR_x0020_or_x0020_ES', ''),
                                'pr_url': f"https://jira.lamresearch.com/browse/{item.get('PR_x0020_or_x0020_ES', '')}" if item.get('PR_x0020_or_x0020_ES') else '#',
                                'priority': item.get('Priority', 'Normal'),
                                'issued_by': item.get('Issued_x0020_by', '')
                            })
                        
                        df = pd.DataFrame(data)
                        
                        # Update cache
                        sharepoint_cache['data'] = df
                        sharepoint_cache['last_update'] = now
                        
                        return df
                    else:
                        print(f"REST API returned status {response.status_code}")
                        print(f"Response: {response.text[:500]}")
                        
            except requests.exceptions.Timeout:
                print("⚠️ REST API timeout")
            except Exception as e:
                print(f"⚠️ REST API error: {e}")
        
        # Method 2: Try Office365 library as fallback
        try:
            from office365.runtime.auth.user_credential import UserCredential
            from office365.sharepoint.client_context import ClientContext
            
            print("Trying Office365 library...")
            credentials = UserCredential(username, password)
            ctx = ClientContext(SHAREPOINT_SITE_URL).with_credentials(credentials)
            
            # Get the list
            sp_list = ctx.web.lists.get_by_title(SHAREPOINT_LIST_NAME)
            items = sp_list.items.get().execute_query()
            
            # Extract data
            data = []
            for item in items:
                props = item.properties
                
                # Parse date
                date_reported = props.get('Date_x0020_reported') or props.get('Created')
                if date_reported:
                    try:
                        if isinstance(date_reported, str):
                            date_obj = pd.to_datetime(date_reported)
                        else:
                            date_obj = pd.Timestamp(date_reported)
                        date_str = date_obj.strftime('%m/%d/%Y')
                    except:
                        date_str = str(date_reported)
                else:
                    date_str = ''
                
                data.append({
                    'ID': props.get('ID'),
                    'Title': props.get('Title', ''),
                    'date_reported': date_str,
                    'fab': props.get('Fab', ''),
                    'module_type': props.get('Module_x0020_Type', ''),
                    'issue': props.get('Title', ''),
                    'solution': props.get('Solution', ''),
                    'current_status': props.get('Current_x0020_Status', ''),
                    'pr_or_es': props.get('PR_x0020_or_x0020_ES', ''),
                    'pr_url': f"https://jira.lamresearch.com/browse/{props.get('PR_x0020_or_x0020_ES', '')}" if props.get('PR_x0020_or_x0020_ES') else '#',
                    'priority': props.get('Priority', 'Normal'),
                    'issued_by': props.get('Issued_x0020_by', '')
                })
            
            df = pd.DataFrame(data)
            
            # Update cache
            sharepoint_cache['data'] = df
            sharepoint_cache['last_update'] = now
            
            print(f"✅ Office365 library success! Fetched {len(data)} items")
            return df
            
        except ImportError:
            print("⚠️ Office365-REST-Python-Client not installed")
        except Exception as e:
            print(f"⚠️ Office365 library error: {e}")
        
        return None
        
    except Exception as e:
        print(f"❌ SharePoint fetch error: {e}")
        traceback.print_exc()
        return None

def get_powerbi_credentials():
    """
    Get Power BI credentials from environment variables or config file
    Returns: (client_id, client_secret, tenant_id) or (username, password) for user auth
    """
    # Option 1: Service Principal (OAuth2.0) - Recommended
    client_id = os.getenv('POWERBI_CLIENT_ID') or os.getenv('AZURE_CLIENT_ID')
    client_secret = os.getenv('POWERBI_CLIENT_SECRET') or os.getenv('AZURE_CLIENT_SECRET')
    tenant_id = os.getenv('POWERBI_TENANT_ID') or os.getenv('AZURE_TENANT_ID')
    
    if client_id and client_secret and tenant_id:
        return ('service_principal', client_id, client_secret, tenant_id)
    
    # Option 2: Config file
    config_file = 'powerbi_config.txt'
    if os.path.exists(config_file):
        with open(config_file, 'r', encoding='utf-8') as f:
            content = f.read()
            
            if '[SERVICE_PRINCIPAL]' in content or '[OAUTH]' in content:
                lines = [line.strip() for line in content.split('\n') if line.strip() and not line.strip().startswith('[')]
                config = {}
                for line in lines:
                    if '=' in line:
                        key, value = line.split('=', 1)
                        config[key.strip()] = value.strip()
                
                client_id = config.get('client_id')
                client_secret = config.get('client_secret')
                tenant_id = config.get('tenant_id')
                
                if client_id and client_secret and tenant_id:
                    return ('service_principal', client_id, client_secret, tenant_id)
            else:
                # Username/Password format
                lines = content.split('\n')
                if len(lines) >= 2:
                    username = lines[0].strip()
                    password = lines[1].strip()
                    return ('user_auth', username, password)
    
    return None

def fetch_powerbi_data():
    """
    Fetch data from Power BI Report using REST API
    Returns DataFrame or None if failed
    
    Filter: Region=KOREA, Support Type=Software
    """
    global powerbi_cache
    
    # Check cache first
    now = datetime.now()
    if powerbi_cache['data'] is not None and powerbi_cache['last_update']:
        elapsed = (now - powerbi_cache['last_update']).total_seconds()
        if elapsed < powerbi_cache['cache_duration']:
            print(f"✓ Using cached Power BI data (age: {int(elapsed)}s)")
            return powerbi_cache['data']
    
    print("🔄 Fetching fresh Power BI data...")
    
    try:
        import requests
        
        credentials = get_powerbi_credentials()
        
        if not credentials:
            print("⚠️ Power BI credentials not configured")
            print("📝 Create 'powerbi_config.txt' with Azure AD credentials:")
            print("   [SERVICE_PRINCIPAL]")
            print("   client_id=YOUR_CLIENT_ID")
            print("   client_secret=YOUR_CLIENT_SECRET")
            print("   tenant_id=YOUR_TENANT_ID")
            return None
        
        auth_type = credentials[0]
        
        # Get Access Token
        access_token = None
        
        if auth_type == 'service_principal':
            _, client_id, client_secret, tenant_id = credentials
            
            # OAuth2.0 Token Endpoint
            token_url = f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token"
            token_data = {
                'grant_type': 'client_credentials',
                'client_id': client_id,
                'client_secret': client_secret,
                'scope': 'https://analysis.windows.net/powerbi/api/.default'
            }
            
            print(f"🔐 Authenticating with Service Principal...")
            token_response = requests.post(token_url, data=token_data, timeout=30)
            
            if token_response.status_code == 200:
                access_token = token_response.json().get('access_token')
                print("✓ Authentication successful")
            else:
                print(f"❌ Authentication failed: {token_response.status_code}")
                print(f"Response: {token_response.text}")
                return None
        
        elif auth_type == 'user_auth':
            _, username, password = credentials
            # User authentication requires interactive login or Device Code Flow
            # This is more complex - recommend using Service Principal instead
            print("⚠️ User authentication not fully supported. Use Service Principal (Azure AD App)")
            return None
        
        if not access_token:
            print("❌ Failed to obtain access token")
            return None
        
        # API Headers
        headers = {
            'Authorization': f'Bearer {access_token}',
            'Content-Type': 'application/json'
        }
        
        # Step 1: Get Dataset ID from Report
        report_url = f"https://api.powerbi.com/v1.0/myorg/groups/{POWERBI_GROUP_ID}/reports/{POWERBI_REPORT_ID}"
        print(f"📊 Fetching report metadata...")
        
        report_response = requests.get(report_url, headers=headers, timeout=30)
        
        if report_response.status_code != 200:
            print(f"❌ Failed to get report: {report_response.status_code}")
            print(f"Response: {report_response.text}")
            return None
        
        report_data = report_response.json()
        dataset_id = report_data.get('datasetId')
        
        if not dataset_id:
            print("❌ Dataset ID not found in report")
            return None
        
        print(f"✓ Dataset ID: {dataset_id}")
        
        # Step 2: Execute DAX Query with Filters
        # Region=KOREA, Support Type=Software
        dax_query = """
        EVALUATE
        FILTER(
            FILTER(
                'YourTableName',
                'YourTableName'[Region] = "KOREA"
            ),
            'YourTableName'[Support Type] = "Software"
        )
        """
        
        # Note: You need to replace 'YourTableName' with actual table name
        # Alternative: Use executeQueries API endpoint
        query_url = f"https://api.powerbi.com/v1.0/myorg/groups/{POWERBI_GROUP_ID}/datasets/{dataset_id}/executeQueries"
        
        query_payload = {
            "queries": [
                {
                    "query": dax_query
                }
            ],
            "serializerSettings": {
                "includeNulls": True
            }
        }
        
        print(f"🔍 Executing DAX query with filters (Region=KOREA, Support Type=Software)...")
        
        query_response = requests.post(query_url, headers=headers, json=query_payload, timeout=60)
        
        if query_response.status_code != 200:
            print(f"⚠️ Query execution failed: {query_response.status_code}")
            print(f"Response: {query_response.text}")
            
            # Fallback: Try to get tables list
            print("📋 Attempting to list dataset tables...")
            tables_url = f"https://api.powerbi.com/v1.0/myorg/groups/{POWERBI_GROUP_ID}/datasets/{dataset_id}/tables"
            tables_response = requests.get(tables_url, headers=headers, timeout=30)
            
            if tables_response.status_code == 200:
                tables = tables_response.json().get('value', [])
                print(f"✓ Available tables: {[t.get('name') for t in tables]}")
            
            return None
        
        # Parse response
        query_result = query_response.json()
        
        if 'results' in query_result and len(query_result['results']) > 0:
            result = query_result['results'][0]
            
            if 'tables' in result and len(result['tables']) > 0:
                table = result['tables'][0]
                rows = table.get('rows', [])
                
                if rows:
                    # Convert to DataFrame
                    df = pd.DataFrame(rows)
                    print(f"✓ Retrieved {len(df)} rows from Power BI")
                    
                    # Update cache
                    powerbi_cache['data'] = df
                    powerbi_cache['last_update'] = datetime.now()
                    
                    return df
                else:
                    print("⚠️ No rows returned from query")
            else:
                print("⚠️ No tables in query result")
        else:
            print("⚠️ No results from query")
        
        return None
        
    except ImportError as e:
        print(f"⚠️ Missing required package: {e}")
        print("Install with: pip install requests")
        return None
    except Exception as e:
        print(f"❌ Power BI fetch error: {e}")
        traceback.print_exc()
        return None

# 색상 팔레트 생성 함수
def generate_colors(n):
    colors = list(mcolors.TABLEAU_COLORS.values()) + list(mcolors.CSS4_COLORS.values())
    random.shuffle(colors)
    return colors[:n]

# ============ Login Routes ============
@app.route('/')
def index():
    """Redirect root to login or dashboard"""
    if 'user' in session:
        return redirect(url_for('dashboard'))
    return redirect(url_for('login_page'))

@app.route('/login')
def login_page():
    """Render login page"""
    if 'user' in session:
        return redirect(url_for('dashboard'))
    return render_template('login.html')

@app.route('/login', methods=['POST'])
def login():
    """Handle login request"""
    try:
        data = request.get_json()
        username = data.get('username', '').strip()
        password = data.get('password', '')
        
        users_data = load_users()
        users = users_data.get('users', {})
        
        # Hash the input password and compare
        hashed_password = _hash_password(password)
        
        if username in users and users[username]['password'] == hashed_password:
            session['user'] = username
            session['role'] = users[username].get('role', 'user')
            session['login_time'] = datetime.now().isoformat()
            
            # Log successful login
            ip_address = request.remote_addr or 'unknown'
            log_access(username, 'login', ip_address)
            
            return jsonify({'success': True})
        else:
            # Log failed attempt
            ip_address = request.remote_addr or 'unknown'
            log_access(username or 'unknown', 'login_failed', ip_address)
            
            return jsonify({'success': False, 'message': 'Invalid username or password'})
    except Exception as e:
        print(f"Login error: {e}")
        return jsonify({'success': False, 'message': 'Login error occurred'})

@app.route('/signup', methods=['POST'])
def signup():
    """Handle signup request"""
    try:
        data = request.get_json()
        username = data.get('username', '').strip()
        password = data.get('password', '')
        signature = data.get('signature', '').strip()
        agreed_at = data.get('agreed_at', datetime.now().isoformat())
        
        # Validation
        if len(username) < 3:
            return jsonify({'success': False, 'message': 'Username must be at least 3 characters'})
        
        if len(password) < 1:
            return jsonify({'success': False, 'message': 'Password is required'})
        
        if len(signature) < 2:
            return jsonify({'success': False, 'message': 'Electronic signature is required'})
        
        users_data = load_users()
        users = users_data.get('users', {})
        
        # Check if username exists
        if username in users:
            return jsonify({'success': False, 'message': 'Username already exists'})
        
        # Create new user
        # Hash the password before storing
        users[username] = {
            'password': _hash_password(password),
            'role': 'user',
            'created_at': datetime.now().isoformat(),
            'signature': signature,
            'agreed_at': agreed_at
        }
        
        users_data['users'] = users
        
        if save_users(users_data):
            # Log signup
            ip_address = request.remote_addr or 'unknown'
            log_access(username, 'signup', ip_address)
            
            return jsonify({'success': True})
        else:
            return jsonify({'success': False, 'message': 'Failed to save user data'})
            
    except Exception as e:
        print(f"Signup error: {e}")
        return jsonify({'success': False, 'message': 'Signup error occurred'})

@app.route('/logout')
def logout():
    """Handle logout"""
    if 'user' in session:
        ip_address = request.remote_addr or 'unknown'
        log_access(session['user'], 'logout', ip_address)
    session.clear()
    return redirect(url_for('login_page'))

@app.route('/dashboard')
@login_required
def dashboard():
    try:
        # Read CSV with UTF-8 BOM encoding and preserve empty strings
        df = pd.read_csv(Config.get_tool_info_csv(), encoding='utf-8-sig', dtype=str, keep_default_na=False)
        
        # Remove completely empty rows only
        df = df[df.apply(lambda row: row.astype(str).str.strip().ne('').any(), axis=1)]

        pm_columns = [col for col in df.columns if col.startswith('PM')]
        fab_values = df['Fab'].dropna().unique()
        module_values = pd.unique(df[pm_columns].values.ravel('K'))
        module_values = [m for m in module_values if pd.notna(m) and m != '']

        # Fab과 Module Name별 색상 매핑
        fab_colors = dict(zip(fab_values, generate_colors(len(fab_values))))
        module_colors = dict(zip(module_values, generate_colors(len(module_values))))

        # CSS를 동적으로 생성 (파일에 쓰지 않고 HTML에 inline으로 추가)
        css_styles = "<style>\n"
        for fab, color in fab_colors.items():
            css_styles += f".fab-{fab} {{ background-color: {color}; }}\n"
        for module, color in module_colors.items():
            safe_module = module.replace('#', '').replace(' ', '_')
            css_styles += f".module-{safe_module} {{ background-color: {color}; }}\n"
        css_styles += "</style>\n"

        # HTML 테이블 생성
        table_html = '<table class="data">\n<thead><tr>\n'
        for col in df.columns:
            table_html += f'<th>{col}</th>\n'
        table_html += '</tr></thead>\n<tbody>\n'

        for _, row in df.iterrows():
            table_html += '<tr>\n'
            for col in df.columns:
                val = row[col]
                cell_value = '' if pd.isna(val) else str(val).strip()
                classes = []
                if col == 'Fab' and cell_value:
                    classes.append(f"fab-{cell_value}")
                if col in pm_columns and cell_value:
                    safe_module = cell_value.replace('#', '').replace(' ', '_')
                    classes.append(f"module-{safe_module}")
                class_attr = f' class="{" ".join(classes)}"' if classes else ''
                table_html += f'<td{class_attr}>{cell_value}</td>\n'
            table_html += '</tr>\n'
        table_html += '</tbody></table>\n'

        return render_template('dashboard.html', table_html=table_html, css_styles=css_styles)
    
    except Exception as e:
        error_msg = f"Error: {type(e).__name__}: {str(e)}\n\n{traceback.format_exc()}"
        print(error_msg)
        return f"<pre>{error_msg}</pre>", 500

@app.route('/save_data', methods=['POST'])
@login_required
def save_data():
    try:
        from datetime import datetime
        import shutil
        
        data = request.json
        all_data = data.get('data', [])
        
        print("=== SAVE_DATA DEBUG ===")
        print(f"Received {len(all_data)} rows")
        if all_data:
            print(f"First row keys: {list(all_data[0].keys())}")
            print(f"First row sample: {all_data[0]}")
        else:
            print("WARNING: No data received!")
        
        if not all_data:
            return jsonify({'success': False, 'error': 'No data provided'}), 400
        
        # Create backup before saving
        csv_path = Config.get_tool_info_csv()
        backup_path = Config.DATA_DIR / f'SKH_tool_information_fixed_backup_{datetime.now().strftime("%Y%m%d_%H%M%S")}.csv'
        shutil.copy2(csv_path, backup_path)
        print(f"✓ Backup created: {backup_path}")
        
        # Read original CSV to preserve column order and structure
        original_df = pd.read_csv(csv_path, encoding='utf-8-sig', dtype=str, keep_default_na=False)
        original_columns = original_df.columns.tolist()
        
        print(f"Original columns: {original_columns}")
        print(f"Original rows: {len(original_df)}")
        
        # Convert received data to DataFrame, preserving empty strings
        df = pd.DataFrame(all_data)
        
        print(f"Received columns: {list(df.columns)}")
        print(f"Received rows: {len(df)}")
        
        # Ensure all original columns exist (add missing ones as empty)
        for col in original_columns:
            if col not in df.columns:
                df[col] = ''
                print(f"Added missing column: {col}")
        
        # Remove any extra columns that shouldn't be there (like 'Save')
        extra_cols = [col for col in df.columns if col not in original_columns]
        if extra_cols:
            print(f"Removing extra columns: {extra_cols}")
            df = df.drop(columns=extra_cols)
        
        # Reorder columns to match original
        df = df[original_columns]
        
        # Replace NaN with empty string to preserve CSV structure
        df = df.fillna('')
        
        # Convert all values to strings and strip whitespace
        for col in df.columns:
            df[col] = df[col].astype(str).str.strip()
            # Replace 'nan' string with empty string
            df[col] = df[col].replace('nan', '')
        
        print(f"Final shape before save: {df.shape}")
        print(f"Sample first row: {df.iloc[0].to_dict()}")
        
        # Save to CSV with UTF-8 BOM encoding (Excel compatible)
        df.to_csv(csv_path, index=False, encoding='utf-8-sig')
        
        print("✅ Save successful!")
        
        # Verify saved file
        verify_df = pd.read_csv(csv_path, encoding='utf-8-sig', dtype=str, keep_default_na=False)
        print(f"Verification: {verify_df.shape}")
        
        return jsonify({'success': True, 'message': f'Saved {len(df)} rows', 'refresh_charts': True})
    
    except Exception as e:
        error_msg = traceback.format_exc()
        print("❌ Save failed:")
        print(error_msg)
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/export_csv', methods=['POST'])
@login_required
def export_csv():
    try:
        from datetime import datetime
        data = request.json
        all_data = data.get('data', [])
        
        if not all_data:
            # Fallback to reading from file
            df = pd.read_csv(Config.get_tool_info_csv(), encoding='utf-8')
        else:
            df = pd.DataFrame(all_data)
        
        # Create CSV in memory with UTF-8 encoding
        output = StringIO()
        df.to_csv(output, index=False, encoding='utf-8')
        output.seek(0)
        
        # Generate filename with YYYYMMDD format
        date_str = datetime.now().strftime('%Y%m%d')
        filename = f'SSSS_{date_str}.csv'
        
        # Create response with UTF-8 BOM for Excel compatibility
        csv_content = '\ufeff' + output.getvalue()
        
        # Create response
        return Response(
            csv_content.encode('utf-8'),
            mimetype='text/csv; charset=utf-8',
            headers={'Content-Disposition': f'attachment;filename={filename}'}
        )
    
    except Exception as e:
        print(traceback.format_exc())
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/download_csv')
@login_required
def download_csv():
    return send_file(str(Config.get_tool_info_csv()), as_attachment=True)

@app.route('/dashboard_stats')
@login_required
def dashboard_stats():
    try:
        # Read CSV without caching
        df = pd.read_csv(Config.get_tool_info_csv(), encoding='utf-8-sig')
        df = df.dropna(how='all')
        
        # Current SW에서 -Release 제거
        df['Current SW'] = df['Current SW'].apply(
            lambda x: str(x).replace('-Release', '') if pd.notna(x) else ''
        )
        
        # 1. Fab별 Current SW 버전 통계 (고객사 구분 제거)
        fab_sw_counts = {}
        for _, row in df.iterrows():
            fab = str(row['Fab']) if pd.notna(row['Fab']) else ''
            sw = str(row['Current SW']) if pd.notna(row['Current SW']) else ''
            
            if fab and sw:
                key = f"{fab} - {sw}"
                fab_sw_counts[key] = fab_sw_counts.get(key, 0) + 1
        
        # 2. Akara/Vantex SW 버전 통계
        pm_columns = [col for col in df.columns if col.startswith('PM')]
        
        akara_versions = set()
        vantex_versions = set()
        
        for _, row in df.iterrows():
            row_akara = set()
            row_vantex = set()
            
            for pm_col in pm_columns:
                pm_value = str(row[pm_col]) if pd.notna(row[pm_col]) else ''
                
                # Akara 체크 (AkaraAX, AkaraAL, AkaraBL, AkaraAP 등)
                if 'Akara' in pm_value:
                    current_sw = str(row['Current SW']) if pd.notna(row['Current SW']) else ''
                    if current_sw:
                        row_akara.add(current_sw)
                
                # Vantex 체크 (VantexB, VantexBX, VantexBPlus, VantexCX 등)
                if 'Vantex' in pm_value:
                    current_sw = str(row['Current SW']) if pd.notna(row['Current SW']) else ''
                    if current_sw:
                        row_vantex.add(current_sw)
            
            # 각 row당 하나의 SW 버전만 카운트
            akara_versions.update(row_akara)
            vantex_versions.update(row_vantex)
        
        # SW 버전별 카운트
        akara_sw_counts = {}
        vantex_sw_counts = {}
        
        for version in akara_versions:
            count = 0
            for _, row in df.iterrows():
                has_akara = False
                for pm_col in pm_columns:
                    pm_value = str(row[pm_col]) if pd.notna(row[pm_col]) else ''
                    if 'Akara' in pm_value:
                        has_akara = True
                        break
                
                if has_akara and str(row['Current SW']) == version:
                    count += 1
            
            if count > 0:
                akara_sw_counts[version] = count
        
        for version in vantex_versions:
            count = 0
            for _, row in df.iterrows():
                has_vantex = False
                for pm_col in pm_columns:
                    pm_value = str(row[pm_col]) if pd.notna(row[pm_col]) else ''
                    if 'Vantex' in pm_value:
                        has_vantex = True
                        break
                
                if has_vantex and str(row['Current SW']) == version:
                    count += 1
            
            if count > 0:
                vantex_sw_counts[version] = count
        
        # Sort SW versions by SP (ascending) then HF (ascending)
        def sort_sw_version(version_str):
            # Extract SP and HF numbers from version string like "SP09-HF02"
            sp_match = re.search(r'SP(\d+)', version_str)
            hf_match = re.search(r'HF(\d+)', version_str)
            
            sp_num = int(sp_match.group(1)) if sp_match else 0
            hf_num = int(hf_match.group(1)) if hf_match else 0
            
            # Return positive values for ascending sort
            return (sp_num, hf_num)
        
        # Sort and create ordered dictionaries
        akara_sw_sorted = dict(sorted(akara_sw_counts.items(), key=lambda x: sort_sw_version(x[0])))
        vantex_sw_sorted = dict(sorted(vantex_sw_counts.items(), key=lambda x: sort_sw_version(x[0])))
        
        return jsonify({
            'fab_sw_counts': fab_sw_counts,
            'akara_sw_counts': akara_sw_sorted,
            'vantex_sw_counts': vantex_sw_sorted
        })
    
    except Exception as e:
        print(traceback.format_exc())
        return jsonify({'error': str(e)}), 500

@app.route('/puca_stats')
@login_required
def puca_stats():
    try:
        # Excel file read (force fresh read, no caching)
        df = pd.read_excel(Config.get_upgrade_plan_xlsx(), engine='openpyxl')
        df = df.dropna(how='all')
        
        # Convert Commit Date to datetime
        df['Commit Date'] = pd.to_datetime(df['Commit Date'], errors='coerce')
        
        # Get date range from query parameters (default: last 3 months)
        months = request.args.get('months', '3')
        try:
            months = int(months)
        except:
            months = 3
        
        # Get customer filter (optional - for Samsung/SK Hynix specific charts)
        customer_filter = request.args.get('customer', None)
        product_type_filter = request.args.get('product_type', None)
        chamber_filter = request.args.get('chamber', None)  # Product Name
        
        # Filter by date range using Commit Date
        today = pd.Timestamp.now()
        start_date = today - pd.DateOffset(months=months)
        df = df[df['Commit Date'] >= start_date]
        
        # Product Type normalization (Dep/Nexus → Dep)
        df['Product Type'] = df['Product Type'].str.replace('Dep/Nexus', 'Dep', regex=False)
        
        # Get unique filter options (before applying customer filter)
        product_types = sorted(df['Product Type'].dropna().unique().tolist())
        chambers = sorted(df['Product Name'].dropna().unique().tolist())
        customers = sorted(df['Customer'].dropna().unique().tolist())
        
        # Apply filters
        if customer_filter:
            df = df[df['Customer'] == customer_filter]
        if product_type_filter:
            df = df[df['Product Type'] == product_type_filter]
        if chamber_filter:
            df = df[df['Product Name'] == chamber_filter]
        
        # 1. PUCA Status by Product Type aggregation (overall)
        puca_status_counts = {}
        for status in ['Completed', 'Not Tested', 'In Progress']:
            status_df = df[df['PUCA Status'] == status]
            type_counts = status_df['Product Type'].value_counts().to_dict()
            puca_status_counts[status] = {
                'Etch': type_counts.get('Etch', 0),
                'Dep': type_counts.get('Dep', 0)
            }
        
        # Helper function to get customer-specific stats
        def get_customer_stats(dataframe, customer_name):
            cust_df = dataframe[dataframe['Customer'] == customer_name] if customer_name else dataframe
            stats = {}
            for status in ['Completed', 'Not Tested', 'In Progress']:
                status_df = cust_df[cust_df['PUCA Status'] == status]
                type_counts = status_df['Product Type'].value_counts().to_dict()
                stats[status] = {
                    'Etch': type_counts.get('Etch', 0),
                    'Dep': type_counts.get('Dep', 0)
                }
            return stats
        
        # Re-read original filtered data for customer-specific stats (before customer filter)
        df_base = pd.read_excel(Config.get_upgrade_plan_xlsx(), engine='openpyxl')
        df_base = df_base.dropna(how='all')
        df_base['Commit Date'] = pd.to_datetime(df_base['Commit Date'], errors='coerce')
        df_base = df_base[df_base['Commit Date'] >= start_date]
        df_base['Product Type'] = df_base['Product Type'].str.replace('Dep/Nexus', 'Dep', regex=False)
        
        # Apply only product_type and chamber filters to base data for customer charts
        if product_type_filter:
            df_base = df_base[df_base['Product Type'] == product_type_filter]
        if chamber_filter:
            df_base = df_base[df_base['Product Name'] == chamber_filter]
        
        # 2. Samsung stats
        samsung_stats = get_customer_stats(df_base, 'Samsung')
        
        # 3. SK Hynix stats
        skhynix_stats = get_customer_stats(df_base, 'SK hynix')
        
        # 4. All Jira review data (exclude Completed status, sorted by SAT number descending)
        review_df = df[df['PUCA Status'] != 'Completed'].copy()
        review_data = []
        
        for _, row in review_df.iterrows():
            if pd.notna(row.get('Jira Issue Key')):
                jira_key = str(row['Jira Issue Key'])
                review_data.append({
                    'jira_key': jira_key,
                    'jira_url': f'https://jira.lamresearch.com/browse/{jira_key}',
                    'puca_status': str(row.get('PUCA Status', '')),
                    'execution_status': str(row.get('PUCA Execution Status', '')),
                    'software_version_from': str(row.get('Software Version From', '')),
                    'software_version_to': str(row.get('Software Version To', '')),
                    'product_name': str(row.get('Product Name', '')),
                    'product_type': str(row.get('Product Type', '')),
                    'customer': str(row.get('Customer', ''))
                })
        
        # Sort by SAT number descending (extract number from SAT-XXXX)
        def extract_sat_number(item):
            try:
                return int(item['jira_key'].split('-')[1])
            except:
                return 0
        
        review_data.sort(key=extract_sat_number, reverse=True)
        
        return jsonify({
            'puca_status_counts': puca_status_counts,
            'samsung_stats': samsung_stats,
            'skhynix_stats': skhynix_stats,
            'review_data': review_data,
            'date_range': {
                'start': start_date.strftime('%Y-%m-%d'),
                'end': today.strftime('%Y-%m-%d'),
                'months': months
            },
            'filter_options': {
                'product_types': product_types,
                'chambers': chambers,
                'customers': customers
            }
        })
    
    except Exception as e:
        print(traceback.format_exc())
        return jsonify({'error': str(e)}), 500

@app.route('/ticket_stats')
@login_required
def ticket_stats():
    try:
        # Read Ticket Details.xlsx (force fresh read, no caching)
        excel_path = Config.get_ticket_details_xlsx()
        
        df = None
        if excel_path.exists():
            print(f"✅ Loading Ticket Details from: {excel_path}")
            df = pd.read_excel(excel_path, engine='openpyxl')
        
        if df is None:
            print("❌ Ticket Details.xlsx not found in any path")
            return jsonify({
                'type3_tickets': [],
                'type2_tickets': [],
                'all_tickets': [],
                'error': 'Ticket Details.xlsx not found'
            })
        
        # Type 3 tickets
        type3_df = df[df['Ticket Type'] == 'Type 3 (PG)'].copy()
        type3_data = []
        for _, row in type3_df.iterrows():
            if pd.notna(row.get('Ticket ID')) and pd.notna(row.get('Days Open')):
                # Handle both string and numeric Ticket IDs
                ticket_id_raw = row['Ticket ID']
                try:
                    ticket_id = str(int(float(str(ticket_id_raw))))
                except (ValueError, TypeError):
                    ticket_id = str(ticket_id_raw).strip()
                
                # Skip if ticket ID is not numeric
                if not ticket_id.isdigit():
                    continue
                    
                type3_data.append({
                    'ticket_id': ticket_id,
                    'ticket_url': f'https://es.fremont.lamrc.net/tickets/{ticket_id}',
                    'days_open': float(row['Days Open']),
                    'support_lead': str(row.get('Support Lead', '')),
                    'type': 'Type 3'
                })
        
        # Type 2 tickets
        type2_df = df[df['Ticket Type'] == 'Type 2 (Chronic)'].copy()
        type2_data = []
        for _, row in type2_df.iterrows():
            if pd.notna(row.get('Ticket ID')) and pd.notna(row.get('Days Open')):
                # Handle both string and numeric Ticket IDs
                ticket_id_raw = row['Ticket ID']
                try:
                    ticket_id = str(int(float(str(ticket_id_raw))))
                except (ValueError, TypeError):
                    ticket_id = str(ticket_id_raw).strip()
                
                # Skip if ticket ID is not numeric
                if not ticket_id.isdigit():
                    continue
                    
                type2_data.append({
                    'ticket_id': ticket_id,
                    'ticket_url': f'https://es.fremont.lamrc.net/tickets/{ticket_id}',
                    'days_open': float(row['Days Open']),
                    'support_lead': str(row.get('Support Lead', '')),
                    'type': 'Type 2'
                })
        
        # All tickets with full details for table
        # Available columns: Ticket ID, Days Open, Ticket Type, Product, Support Lead, 
        # First Symptom, Customer, Escalation Date, Start Work Date
        all_tickets = []
        for _, row in df.iterrows():
            if pd.notna(row.get('Ticket ID')):
                # Handle both string and numeric Ticket IDs
                ticket_id_raw = row['Ticket ID']
                try:
                    ticket_id = str(int(float(str(ticket_id_raw))))
                except (ValueError, TypeError):
                    ticket_id = str(ticket_id_raw).strip()
                
                # Skip if ticket ID is not numeric
                if not ticket_id.isdigit():
                    continue
                    
                ticket_type = str(row.get('Ticket Type', '')).replace(' (PG)', '').replace(' (Chronic)', '')
                
                # Format dates
                esc_date = row.get('Escalation Date')
                if pd.notna(esc_date):
                    try:
                        esc_date = pd.Timestamp(esc_date).strftime('%Y-%m-%d')
                    except:
                        esc_date = str(esc_date)
                else:
                    esc_date = ''
                
                all_tickets.append({
                    'ticket_id': ticket_id,
                    'ticket_url': f'https://es.fremont.lamrc.net/tickets/{ticket_id}',
                    'type': ticket_type,
                    'days_open': float(row.get('Days Open', 0)) if pd.notna(row.get('Days Open')) else 0,
                    'customer': str(row.get('Customer', '')),
                    'product': str(row.get('Product', '')),
                    'support_lead': str(row.get('Support Lead', '')),
                    'status': 'Open',
                    'priority': 'High' if 'Type 3' in str(row.get('Ticket Type', '')) else 'Medium',
                    'description': str(row.get('First Symptom', '')),
                    'created_date': esc_date
                })
        
        return jsonify({
            'type3_tickets': type3_data,
            'type2_tickets': type2_data,
            'all_tickets': all_tickets
        })
    
    except Exception as e:
        print(traceback.format_exc())
        return jsonify({'error': str(e)}), 500

@app.route('/issue_stats')
@login_required
def issue_stats():
    """
    Etch Issue Tracker endpoint
    Automatically fetches data from SharePoint in real-time
    """
    try:
        # Get date range from query parameters (default: 3 months)
        months = request.args.get('months', '3')
        try:
            months = int(months)
        except:
            months = 3  # Default to 3 months
        
        # Get status filter from query parameters
        status_filter = request.args.get('statuses', '').split(',') if request.args.get('statuses') else []
        
        # Calculate date range
        today = pd.Timestamp.now()
        if months > 0:
            start_date = today - pd.DateOffset(months=months)
            use_date_filter = True
        else:
            start_date = pd.Timestamp('2000-01-01')  # Very old date to include all
            use_date_filter = False
        
        # Debug: Print filter settings
        print(f"📅 Date Filter: months={months}, use_filter={use_date_filter}")
        print(f"📅 Start Date: {start_date.strftime('%Y-%m-%d')}, Today: {today.strftime('%Y-%m-%d')}")
        
        all_issues_table = []  # For table display - ALL data without filter
        filtered_issues_chart = []  # For chart - WITH date filter
        seen_prs = set()  # Track seen PRs to prevent duplicates
        data_source = "sample"
        
        # Read from Issues Tracking CSV
        csv_path = Config.get_issues_tracking_csv()
        
        csv_found = False
        
        if csv_path.exists():
            abs_path = str(csv_path.resolve())
            print(f"✅ Found CSV at: {abs_path}")
            try:
                df = pd.read_csv(csv_path, encoding='utf-8')
                data_source = "downloads_csv"
                csv_found = True
                
                # ★★★ CRITICAL: Remove duplicates BEFORE processing ★★★
                # Remove duplicate rows based on PR number
                if 'PR or ES ' in df.columns:
                    original_count = len(df)
                    df = df.drop_duplicates(subset=['PR or ES '], keep='first')
                    removed_count = original_count - len(df)
                    if removed_count > 0:
                        print(f"🔧 Removed {removed_count} duplicate PR entries from CSV")
                
                for _, row in df.iterrows():
                    # Check for duplicates using PR number
                    pr_raw = row.get('PR or ES ', '')
                    if pd.isna(pr_raw):
                        pr_raw = ''
                    else:
                        pr_raw = str(pr_raw).strip()
                        
                    pr_id = pr_raw.replace('https://iplmprd.fremont.lamrc.net/3dspace/goto/o/LRC+Problem+Report/', '').replace('/', '')
                    
                    if pr_id and pr_id in seen_prs:
                        continue
                    if pr_id and pr_id != '#' and pr_id != 'nan':
                        seen_prs.add(pr_id)

                    date_reported = row.get('Date reported')
                    if pd.isna(date_reported):
                        continue
                    
                    try:
                        date_obj = pd.to_datetime(date_reported)
                    except:
                        continue
                    
                    # Parse Module Type (it's in JSON array format)
                    module_type = str(row.get('Module Type', ''))
                    if module_type.startswith('["') and module_type.endswith('"]'):
                        try:
                            module_list = json.loads(module_type.replace("'", '"'))
                            module_type = ', '.join(module_list) if isinstance(module_list, list) else module_type
                        except:
                            pass
                    
                    # Parse Current Status
                    current_status = str(row.get('Current Status', ''))
                    if current_status.startswith('["') and current_status.endswith('"]'):
                        try:
                            status_list = json.loads(current_status.replace("'", '"'))
                            current_status = ', '.join(status_list) if isinstance(status_list, list) else current_status
                        except:
                            pass
                    
                    issue_data = {
                        'date_reported': date_obj.strftime('%m/%d/%Y'),
                        'fab': str(row.get('Fab', '')),
                        'module_type': module_type,
                        'issue': str(row.get('Issue', '')),
                        'solution': str(row.get('Solution', '') if pd.notna(row.get('Solution')) else ''),
                        'current_status': current_status,
                        'pr_or_es': pr_id,
                        'pr_url': str(row.get('PR or ES ', '#')),
                        'priority': str(row.get('Priority', 'Normal')),
                        'issued_by': str(row.get('Issued by', '')),
                        'issued_sw': str(row.get('Issued SW', ''))
                    }
                    
                    # Add to table list (ALL data)
                    all_issues_table.append(issue_data)
                    
                    # Add to chart list only if passes date filter
                    # Compare dates only (ignore time)
                    if not use_date_filter or date_obj.date() >= start_date.date():
                        filtered_issues_chart.append(issue_data)
                
                print(f"✅ Loaded {len(all_issues_table)} issues for table, {len(filtered_issues_chart)} for chart (filter: {months}M)")
                    
            except Exception as e:
                print(f"Error reading CSV: {e}")
                traceback.print_exc()
                # If error occurs, clear partial data
                all_issues_table = []
                filtered_issues_chart = []
                seen_prs = set()
        
        # Method 2: Try to fetch from SharePoint API (real-time)
        if len(all_issues_table) == 0:
            print("Attempting to fetch SharePoint data...")
            sp_df = fetch_sharepoint_data()
        
            if sp_df is not None and len(sp_df) > 0:
                print(f"✅ Using live SharePoint data: {len(sp_df)} items")
                data_source = "sharepoint_api"
            
            for _, row in sp_df.iterrows():
                # Check for duplicates using PR number
                pr_id = str(row.get('pr_or_es', '')).strip()
                
                if pr_id and pr_id in seen_prs:
                    continue
                if pr_id and pr_id != '#' and pr_id != 'nan':
                    seen_prs.add(pr_id)

                # Parse date
                date_reported = row.get('date_reported')
                if pd.isna(date_reported) or not date_reported:
                    continue
                
                try:
                    date_obj = pd.to_datetime(date_reported)
                except:
                    continue
                
                issue_data = {
                    'date_reported': date_obj.strftime('%m/%d/%Y'),
                    'fab': str(row.get('fab', '')),
                    'module_type': str(row.get('module_type', '')),
                    'issue': str(row.get('issue', '')),
                    'solution': str(row.get('solution', '')),
                    'current_status': str(row.get('current_status', '')),
                    'pr_or_es': str(row.get('pr_or_es', '')),
                    'pr_url': str(row.get('pr_url', '#')),
                    'priority': str(row.get('priority', 'Normal')),
                    'issued_by': str(row.get('issued_by', '')),
                    'issued_sw': str(row.get('issued_sw', ''))
                }
                
                # Add to table (ALL data)
                all_issues_table.append(issue_data)
                
                # Add to chart only if passes date filter
                if not use_date_filter or date_obj.date() >= start_date.date():
                    filtered_issues_chart.append(issue_data)
        
        # Method 3: Try to read from Excel file (fallback)
        if len(all_issues_table) == 0:
            sharepoint_file = Config.DATA_DIR / 'Issues_Tracking_SharePoint.xlsx'
            if sharepoint_file.exists():
                print(f"Reading SharePoint data from {sharepoint_file}")
                data_source = "excel_file"
                try:
                    df = pd.read_excel(sharepoint_file, engine='openpyxl')
                    
                    for _, row in df.iterrows():
                        if pd.isna(row.get('Title')) or pd.isna(row.get('Date reported')):
                            continue
                        
                        # Check for duplicates using PR number
                        pr_raw = str(row.get('PR or ES', '')).strip()
                        pr_id = pr_raw.replace('https://iplmprd.fremont.lamrc.net/3dspace/goto/o/LRC+Problem+Report/', '').replace('/', '')

                        if pr_id and pr_id in seen_prs:
                            continue
                        if pr_id and pr_id != '#' and pr_id != 'nan':
                            seen_prs.add(pr_id)

                        date_reported = row.get('Date reported')
                        if isinstance(date_reported, str):
                            try:
                                date_obj = pd.to_datetime(date_reported)
                            except:
                                continue
                        else:
                            date_obj = pd.Timestamp(date_reported)
                        
                        issue_data = {
                            'date_reported': date_obj.strftime('%m/%d/%Y'),
                            'fab': str(row.get('Fab', '')),
                            'module_type': str(row.get('Module Type', '')),
                            'issue': str(row.get('Title', '')),
                            'solution': str(row.get('Solution', '') if pd.notna(row.get('Solution')) else ''),
                            'current_status': str(row.get('Current Status', '')),
                            'pr_or_es': str(row.get('PR or ES', '')),
                            'pr_url': f"https://jira.lamresearch.com/browse/{row.get('PR or ES', '')}" if pd.notna(row.get('PR or ES')) else '#',
                            'priority': str(row.get('Priority', 'Normal')),
                            'issued_by': str(row.get('Issued by', '')),
                            'issued_sw': str(row.get('Issued SW', ''))
                        }
                        
                        # Add to table (ALL data)
                        all_issues_table.append(issue_data)
                        
                        # Add to chart only if passes date filter
                        if not use_date_filter or date_obj.date() >= start_date.date():
                            filtered_issues_chart.append(issue_data)
                    
                    print(f"Loaded {len(all_issues_table)} issues from Excel file")
                    
                except Exception as e:
                    print(f"Error reading Excel file: {e}")
        
        # If no data found from any source, return empty result
        if len(all_issues_table) == 0:
            print("⚠️ No issue data available from any source (CSV, SharePoint, Excel)")
            data_source = "none"
        
        # Count statuses from CHART data (with date filter)
        all_status_counts = {}
        for issue in filtered_issues_chart:
            status = issue['current_status']
            all_status_counts[status] = all_status_counts.get(status, 0) + 1
        
        # Debug: Print status breakdown
        print(f"📊 Status Counts (from filtered chart data): {all_status_counts}")
        waiting_pr_count = all_status_counts.get('Waiting PR fix', 0)
        print(f"🔴 Waiting PR fix count: {waiting_pr_count}")
        
        # Apply status filter to TABLE data if provided
        if status_filter and status_filter[0]:  # Check if not empty
            table_issues = [issue for issue in all_issues_table if issue['current_status'] in status_filter]
        else:
            table_issues = all_issues_table
        
        # Apply status filter to CHART data as well if provided
        if status_filter and status_filter[0]:
            chart_issues = [issue for issue in filtered_issues_chart if issue['current_status'] in status_filter]
        else:
            chart_issues = filtered_issues_chart
        
        print(f"✅ Final counts - Table: {len(table_issues)}, Chart: {len(chart_issues)}")
        
        return jsonify({
            'status_counts': all_status_counts,  # For chart - filtered by date
            'all_statuses': list(all_status_counts.keys()),
            'issues': table_issues,  # For table - ALL data
            'chart_issues': chart_issues,  # For charts - filtered by date
            'data_source': data_source,
            'total_issues': len(filtered_issues_chart),  # Chart count
            'table_total': len(all_issues_table),  # Table count
            'date_range': {
                'start': start_date.strftime('%Y-%m-%d'),
                'end': today.strftime('%Y-%m-%d'),
                'months': months
            }
        })
        
    except Exception as e:
        print(traceback.format_exc())
        return jsonify({'error': str(e)}), 500

@app.route('/pr_status')
@login_required
def pr_status():
    """
    PR Status endpoint - loads data from TableExport.csv
    Shows PR Current Status, Days Open, and PCD Over charts
    """
    try:
        # Get date range from query parameters (default: 6 months)
        months = request.args.get('months', '6')
        try:
            months = int(months)
        except:
            months = 6  # Default to 6 months
        
        # Calculate date range
        today = pd.Timestamp.now()
        if months > 0:
            start_date = today - pd.DateOffset(months=months)
            use_date_filter = True
        else:
            start_date = pd.Timestamp('2000-01-01')  # Very old date to include all
            use_date_filter = False
        
        print(f"📅 PR Status - Date Filter: months={months}, use_filter={use_date_filter}")
        
        all_prs = []  # For table display - ALL data
        filtered_prs = []  # For chart - WITH date filter
        data_source = "TableExport.csv"
        
        # Try to read TableExport.csv
        csv_path = Config.get_table_export_csv()
        
        csv_found = False
        if csv_path.exists():
            print(f"✅ Found TableExport.csv at: {csv_path}")
            try:
                df = pd.read_csv(csv_path, encoding='utf-8')
                csv_found = True
                
                for _, row in df.iterrows():
                    # Parse Submitted Date
                    submitted_date = row.get('Submitted Date')
                    if pd.isna(submitted_date):
                        submitted_date_str = ''
                        date_obj = None
                    else:
                        try:
                            date_obj = pd.to_datetime(submitted_date)
                            submitted_date_str = date_obj.strftime('%m/%d/%Y')
                        except:
                            submitted_date_str = str(submitted_date)
                            date_obj = None
                    
                    # Parse Planned Completion Date (PCD)
                    pcd = row.get('Planned Completion Date')
                    if pd.isna(pcd):
                        pcd_str = ''
                        pcd_obj = None
                    else:
                        try:
                            pcd_obj = pd.to_datetime(pcd)
                            pcd_str = pcd_obj.strftime('%m/%d/%Y')
                        except:
                            pcd_str = str(pcd)
                            pcd_obj = None
                    
                    # Parse Date Fixed
                    date_fixed = row.get('Date Fixed')
                    if pd.isna(date_fixed):
                        date_fixed_str = ''
                    else:
                        try:
                            date_fixed_str = pd.to_datetime(date_fixed).strftime('%m/%d/%Y')
                        except:
                            date_fixed_str = str(date_fixed)
                    
                    # Calculate Days Open (from Submitted Date to today for non-closed PRs)
                    status = str(row.get('Status', '')).strip()
                    days_open = 0
                    if date_obj and status not in ['Closed', '']:
                        days_open = (today - date_obj).days
                    
                    # Check if PCD is over (past planned completion date and not closed)
                    pcd_over = False
                    days_over_pcd = 0
                    if pcd_obj and status not in ['Closed', '']:
                        if today > pcd_obj:
                            pcd_over = True
                            days_over_pcd = (today - pcd_obj).days
                    
                    pr_data = {
                        'pr_number': str(row.get('PR Number', '')),
                        'pr_url': f"https://iplmprd.fremont.lamrc.net/3dspace/goto/o/LRC+Problem+Report/{str(row.get('PR Number', ''))}/",
                        'record_type': str(row.get('Record Type', '')),
                        'title': str(row.get('Title', '')),
                        'priority': str(row.get('Priority', '')),
                        'hot_critical': str(row.get('Hot/Critical PR', '')),
                        'originator': str(row.get('Originator', '')),
                        'assigned_engineer': str(row.get('Assigned Engineer / Developer', '')),
                        'version_reported': str(row.get('Version Reported', '')),
                        'version_fixed': str(row.get('Version Fixed', '')),
                        'status': status,
                        'primary_product': str(row.get('Primary Product Affected', '')),
                        'date_fixed': date_fixed_str,
                        'submitted_date': submitted_date_str,
                        'need_date': str(row.get('Need Date', '')) if pd.notna(row.get('Need Date')) else '',
                        'planned_completion_date': pcd_str,
                        'days_open': days_open,
                        'pcd_over': pcd_over,
                        'days_over_pcd': days_over_pcd
                    }
                    
                    # Add to table list (ALL data)
                    all_prs.append(pr_data)
                    
                    # Add to chart list only if passes date filter
                    if date_obj:
                        if not use_date_filter or date_obj.date() >= start_date.date():
                            filtered_prs.append(pr_data)
                
                print(f"✅ Loaded {len(all_prs)} PRs for table, {len(filtered_prs)} for chart (filter: {months}M)")
                    
            except Exception as e:
                print(f"Error reading TableExport.csv: {e}")
                traceback.print_exc()
        
        if not csv_found:
            return jsonify({'error': 'TableExport.csv not found', 'prs': [], 'status_counts': {}}), 404
        
        # Calculate status counts for chart (filtered by date)
        status_counts = {}
        for pr in filtered_prs:
            status = pr['status'] if pr['status'] else 'Unknown'
            status_counts[status] = status_counts.get(status, 0) + 1
        
        # Calculate Days Open data for "Waiting PR Fix" statuses (Confirmed, In Review, Develop)
        waiting_statuses = ['Confirmed', 'In Review', 'Develop']
        days_open_data = []
        for pr in filtered_prs:
            if pr['status'] in waiting_statuses and pr['days_open'] > 0:
                days_open_data.append({
                    'pr_number': pr['pr_number'],
                    'pr_url': pr['pr_url'],
                    'status': pr['status'],
                    'days_open': pr['days_open'],
                    'title': pr['title'][:50] + '...' if len(pr['title']) > 50 else pr['title']
                })
        # Sort by days_open descending (oldest first)
        days_open_data.sort(key=lambda x: x['days_open'], reverse=True)
        # Limit to top 15 for chart readability
        days_open_data = days_open_data[:15]
        
        # Calculate PCD Over data (only for In Review, Confirmed, Create statuses)
        pcd_over_statuses = ['In Review', 'Confirmed', 'Create']
        pcd_over_data = []
        for pr in filtered_prs:
            if pr['pcd_over'] and pr['status'] in pcd_over_statuses:
                pcd_over_data.append({
                    'pr_number': pr['pr_number'],
                    'pr_url': pr['pr_url'],
                    'status': pr['status'],
                    'days_over_pcd': pr['days_over_pcd'],
                    'title': pr['title'][:50] + '...' if len(pr['title']) > 50 else pr['title']
                })
        # Sort by days_over_pcd descending
        pcd_over_data.sort(key=lambda x: x['days_over_pcd'], reverse=True)
        # Limit to top 15 for chart readability
        pcd_over_data = pcd_over_data[:15]
        
        return jsonify({
            'status_counts': status_counts,
            'all_statuses': list(status_counts.keys()),
            'prs': all_prs,  # For table - ALL data
            'chart_prs': filtered_prs,  # For charts - filtered by date
            'days_open_data': days_open_data,  # For Days Open chart
            'pcd_over_data': pcd_over_data,  # For PCD Over chart
            'data_source': data_source,
            'total_prs': len(filtered_prs),
            'table_total': len(all_prs),
            'date_range': {
                'start': start_date.strftime('%Y-%m-%d'),
                'end': today.strftime('%Y-%m-%d'),
                'months': months
            }
        })
        
    except Exception as e:
        print(traceback.format_exc())
        return jsonify({'error': str(e)}), 500


@app.route('/cxl3_stats')
@login_required
def cxl3_stats():
    """
    CXL3 Install Base Statistics API
    Reads from SK_Etch_InstallBase sheet in Monthly_IB_CX_L3_SK_Hynix.xlsx
    Provides FIF, Side-Effect, Rollback charts with Year/Quarter multi-select filters
    """
    try:
        # Get filter parameters (multi-select, comma-separated)
        years_param = request.args.get('years', '')
        quarters_param = request.args.get('quarters', '')
        
        # Parse multi-select values
        selected_years = [int(y) for y in years_param.split(',') if y and y != 'all']
        selected_quarters = [q for q in quarters_param.split(',') if q and q != 'all']
        
        # Excel file paths to try (Downloads folder first, then data folder)
        excel_paths = [
            Path(os.path.expanduser('~')) / 'Downloads' / 'Monthly_IB_CX_L3_SK_Hynix.xlsx',
            Path(__file__).parent / 'data' / 'Monthly_IB_CX_L3_SK_Hynix.xlsx',
        ]
        
        df = None
        used_path = None
        
        for excel_path in excel_paths:
            if excel_path.exists():
                try:
                    df = pd.read_excel(excel_path, sheet_name='SK_Etch_InstallBase', header=0)
                    used_path = str(excel_path)
                    print(f"✅ CXL3: Loaded {len(df)} rows from {used_path}")
                    break
                except Exception as e:
                    print(f"⚠️ CXL3: Error reading {excel_path}: {e}")
                    continue
        
        if df is None or df.empty:
            return jsonify({
                'error': 'Monthly_IB_CX_L3_SK_Hynix.xlsx not found or empty',
                'searched_paths': [str(p) for p in excel_paths]
            }), 404
        
        # Clean data - drop rows with null Date
        df = df.dropna(subset=['Date'])
        
        # Parse Date and add Year/Quarter columns
        df['Date'] = pd.to_datetime(df['Date'], errors='coerce')
        df = df.dropna(subset=['Date'])
        df['Year'] = df['Date'].dt.year.astype(int)
        df['Month'] = df['Date'].dt.month
        
        # Calculate Quarter (1-3: Q1, 4-6: Q2, 7-9: Q3, 10-12: Q4)
        df['Quarter'] = df['Month'].apply(lambda m: 'Q1' if m <= 3 else ('Q2' if m <= 6 else ('Q3' if m <= 9 else 'Q4')))
        
        # Get available years and quarters for filters
        available_years = sorted(df['Year'].unique().tolist())
        available_quarters = ['Q1', 'Q2', 'Q3', 'Q4']
        
        # Apply filters (multi-select)
        filtered_df = df.copy()
        if selected_years:
            filtered_df = filtered_df[filtered_df['Year'].isin(selected_years)]
        if selected_quarters:
            filtered_df = filtered_df[filtered_df['Quarter'].isin(selected_quarters)]
        
        total_count = len(filtered_df)
        
        # 1. FIF (Failure In Field) - Result column contains Failure/Fail/Failed
        failure_keywords = ['failure', 'fail', 'failed']
        fif_df = filtered_df[filtered_df['Result'].str.lower().str.contains('|'.join(failure_keywords), na=False)]
        fif_count = len(fif_df)
        fif_rate = round((fif_count / total_count * 100), 1) if total_count > 0 else 0
        
        # Get FIF details for tooltip
        fif_details = []
        for _, row in fif_df.iterrows():
            fif_details.append({
                'date': row['Date'].strftime('%Y-%m-%d') if pd.notna(row['Date']) else '',
                'line': str(row.get('Line', '')),
                'tool_id': str(row.get('Tool_ID', '')),
                'module_type': str(row.get('Module Type', '')),
                'new_sw_version': str(row.get('New_SW_Version', '')),
                'purpose': str(row.get('Purpose', ''))[:50]
            })
        
        # 2. Side Effect - Side_Effect column = 'Y'
        side_effect_df = filtered_df[filtered_df['Side_Effect'].str.upper() == 'Y']
        side_effect_count = len(side_effect_df)
        side_effect_rate = round((side_effect_count / total_count * 100), 1) if total_count > 0 else 0
        
        # Get Side Effect details
        side_effect_details = []
        for _, row in side_effect_df.iterrows():
            side_effect_details.append({
                'date': row['Date'].strftime('%Y-%m-%d') if pd.notna(row['Date']) else '',
                'line': str(row.get('Line', '')),
                'tool_id': str(row.get('Tool_ID', '')),
                'module_type': str(row.get('Module Type', '')),
                'new_sw_version': str(row.get('New_SW_Version', '')),
                'purpose': str(row.get('Purpose', ''))[:50]
            })
        
        # 3. Rollback - Down_Grade column = 'Y'
        rollback_df = filtered_df[filtered_df['Down_Grade'].str.upper() == 'Y']
        rollback_count = len(rollback_df)
        rollback_rate = round((rollback_count / total_count * 100), 1) if total_count > 0 else 0
        
        # Get Rollback details with New SW Version
        rollback_details = []
        for _, row in rollback_df.iterrows():
            rollback_details.append({
                'date': row['Date'].strftime('%Y-%m-%d') if pd.notna(row['Date']) else '',
                'line': str(row.get('Line', '')),
                'tool_id': str(row.get('Tool_ID', '')),
                'module_type': str(row.get('Module Type', '')),
                'new_sw_version': str(row.get('New_SW_Version', '')),
                'previous_sw_version': str(row.get('Previous_SW_Version', '')),
                'purpose': str(row.get('Purpose', ''))[:50]
            })
        
        # 4. Table data - all filtered rows sorted by date descending
        table_data = []
        for _, row in filtered_df.sort_values('Date', ascending=False).iterrows():
            table_data.append({
                'date': row['Date'].strftime('%Y-%m-%d') if pd.notna(row['Date']) else '',
                'line': str(row.get('Line', '')),
                'who': str(row.get('Who', '')),
                'module_type': str(row.get('Module Type', '')),
                'tool_id': str(row.get('Tool_ID', '')),
                'previous_sw_version': str(row.get('Previous_SW_Version', '')) if pd.notna(row.get('Previous_SW_Version')) else '',
                'new_sw_version': str(row.get('New_SW_Version', '')) if pd.notna(row.get('New_SW_Version')) else '',
                'purpose': str(row.get('Purpose', '')) if pd.notna(row.get('Purpose')) else '',
                'result': str(row.get('Result', '')),
                'side_effect': str(row.get('Side_Effect', '')),
                'new_sw_install': str(row.get('New_SW_Install', '')),
                'proliferation': str(row.get('Proliferation', '')),
                'down_grade': str(row.get('Down_Grade', ''))
            })
        
        # Get unique values for table filters
        filter_options = {
            'line': sorted(filtered_df['Line'].dropna().unique().tolist()),
            'who': sorted(filtered_df['Who'].dropna().unique().tolist()),
            'module_type': sorted(filtered_df['Module Type'].dropna().unique().tolist()),
            'result': sorted(filtered_df['Result'].dropna().unique().tolist())
        }
        
        # 5. SW Failure Trend - Based on selected years (all quarters)
        from datetime import datetime
        current_year = datetime.now().year
        
        # Determine which years to show in trend chart
        if selected_years:
            trend_years = sorted(selected_years)
        else:
            # Default: last 2 years
            trend_start_year = current_year - 2
            trend_years = [y for y in range(trend_start_year, current_year + 1)]
        
        # Filter for trend data based on selected years
        trend_df = df[df['Year'].isin(trend_years)].copy()
        
        # Create Year-Quarter label for grouping
        trend_df['YearQuarter'] = trend_df['Year'].astype(str) + '-' + trend_df['Quarter']
        
        # Get sorted unique Year-Quarters
        all_yq = []
        for y in sorted(trend_years):
            for q in ['Q1', 'Q2', 'Q3', 'Q4']:
                yq = f"{y}-{q}"
                if yq in trend_df['YearQuarter'].values:
                    all_yq.append(yq)
        
        # Calculate counts per Quarter
        failure_keywords = ['failure', 'fail', 'failed']
        trend_failure = []
        trend_rollback = []
        trend_side_effect = []
        trend_total = []
        
        for yq in all_yq:
            yq_df = trend_df[trend_df['YearQuarter'] == yq]
            
            # Total count
            total = len(yq_df)
            trend_total.append(total)
            
            # Failure count
            fail_count = len(yq_df[yq_df['Result'].str.lower().str.contains('|'.join(failure_keywords), na=False)])
            trend_failure.append(fail_count)
            
            # Rollback count
            rb_count = len(yq_df[yq_df['Down_Grade'].str.upper() == 'Y'])
            trend_rollback.append(rb_count)
            
            # Side Effect count
            se_count = len(yq_df[yq_df['Side_Effect'].str.upper() == 'Y'])
            trend_side_effect.append(se_count)
        
        trend_data = {
            'labels': all_yq,
            'failure': trend_failure,
            'rollback': trend_rollback,
            'side_effect': trend_side_effect,
            'total': trend_total
        }
        
        return jsonify({
            'success': True,
            'data_source': used_path,
            'total_count': total_count,
            'available_years': available_years,
            'available_quarters': available_quarters,
            'current_filter': {
                'years': selected_years if selected_years else 'all',
                'quarters': selected_quarters if selected_quarters else 'all'
            },
            'fif': {
                'count': fif_count,
                'rate': fif_rate,
                'success_count': total_count - fif_count,
                'success_rate': round(100 - fif_rate, 1),
                'details': fif_details
            },
            'side_effect': {
                'count': side_effect_count,
                'rate': side_effect_rate,
                'no_effect_count': total_count - side_effect_count,
                'no_effect_rate': round(100 - side_effect_rate, 1),
                'details': side_effect_details
            },
            'rollback': {
                'count': rollback_count,
                'rate': rollback_rate,
                'no_rollback_count': total_count - rollback_count,
                'no_rollback_rate': round(100 - rollback_rate, 1),
                'details': rollback_details
            },
            'trend': trend_data,
            'table_data': table_data,
            'filter_options': filter_options
        })
        
    except Exception as e:
        print(f"❌ CXL3 Stats Error: {e}")
        print(traceback.format_exc())
        return jsonify({'error': str(e)}), 500


@app.route('/pr_swrn_insights')
@login_required
def pr_swrn_insights():
    """
    PR과 SWRN 연동 인사이트 API
    Open PR들에 대해 SWRN에서 유사한 해결 사례 검색
    """
    try:
        from swrn_indexer import get_swrn_indexer
        indexer = get_swrn_indexer()
        
        # 인덱스 확인
        stats = indexer.get_stats()
        if not stats.get("indexed"):
            return jsonify({
                'error': 'SWRN index not built',
                'message': 'Run: python swrn_indexer.py --build'
            }), 400
        
        # PR 데이터 소스 결정
        pr_type = request.args.get('type', 'days_open')  # 'days_open' or 'chronic'
        limit = int(request.args.get('limit', '10'))
        
        # TableExport.csv에서 PR 데이터 로드
        csv_path = os.path.join(os.path.dirname(__file__), 'data', 'TableExport.csv')
        if not os.path.exists(csv_path):
            return jsonify({'error': 'TableExport.csv not found'}), 404
        
        df = pd.read_csv(csv_path, encoding='utf-8')
        today = datetime.now()
        
        open_prs = []
        
        if pr_type == 'chronic':
            # Type 2 (Chronic) Open 조건: Escalation 데이터에서 가져오기
            # TableExport.csv에서 오래된 PR 찾기
            waiting_statuses = ['Confirmed', 'In Review', 'Develop', 'Create']
            for _, row in df.iterrows():
                status = str(row.get('Status', ''))
                if status in waiting_statuses:
                    submitted_date = row.get('Submitted Date')
                    days_open = 0
                    if pd.notna(submitted_date):
                        try:
                            date_obj = pd.to_datetime(submitted_date)
                            days_open = (today - date_obj).days
                        except:
                            pass
                    
                    if days_open > 60:  # 60일 이상 Open된 PR
                        open_prs.append({
                            'pr_number': str(row.get('PR Number', '')),
                            'title': str(row.get('Title', '')),
                            'status': status,
                            'days_open': days_open
                        })
        else:
            # Days Open - Waiting PR Fix
            waiting_statuses = ['Confirmed', 'In Review', 'Develop']
            for _, row in df.iterrows():
                status = str(row.get('Status', ''))
                if status in waiting_statuses:
                    submitted_date = row.get('Submitted Date')
                    days_open = 0
                    if pd.notna(submitted_date):
                        try:
                            date_obj = pd.to_datetime(submitted_date)
                            days_open = (today - date_obj).days
                        except:
                            pass
                    
                    if days_open > 30:  # 30일 이상 Waiting
                        open_prs.append({
                            'pr_number': str(row.get('PR Number', '')),
                            'title': str(row.get('Title', '')),
                            'status': status,
                            'days_open': days_open
                        })
        
        # days_open 기준 정렬
        open_prs.sort(key=lambda x: x['days_open'], reverse=True)
        open_prs = open_prs[:limit]
        
        # SWRN에서 인사이트 검색
        insights = indexer.find_insights_for_open_prs(open_prs, limit_per_pr=3)
        
        return jsonify({
            'pr_type': pr_type,
            'total_open_prs': len(open_prs),
            'insights_found': len(insights),
            'insights': insights,
            'swrn_stats': stats
        })
        
    except ImportError as e:
        return jsonify({'error': f'SWRN module not available: {str(e)}'}), 500
    except Exception as e:
        print(traceback.format_exc())
        return jsonify({'error': str(e)}), 500

@app.route('/pr_similar_search')
@login_required
def pr_similar_search():
    """
    단일 PR에 대한 SWRN 유사 검색 API
    """
    try:
        from swrn_indexer import get_swrn_indexer
        indexer = get_swrn_indexer()
        
        pr_number = request.args.get('pr_number', '')
        title = request.args.get('title', '')
        limit = int(request.args.get('limit', '5'))
        
        if not title:
            return jsonify({'error': 'title parameter required'}), 400
        
        # 유사 PR 검색
        result = indexer.find_similar_prs(title, pr_number, limit=limit)
        
        # HTML 테이블 생성
        if result.get('found', 0) > 0:
            html = f'<div style="margin-bottom:10px;"><h3 style="margin:0 0 8px 0;color:#7c3aed;">🔍 "{pr_number}" 유사 PR 검색 결과 ({result["found"]}건)</h3>'
            html += f'<p style="font-size:12px;color:#666;margin:5px 0;">키워드: {", ".join(result.get("keywords", []))}</p></div>'
            html += '<table style="width:100%;border-collapse:collapse;font-size:14px;margin-bottom:10px;">'
            html += '<thead><tr style="background:linear-gradient(135deg,#7c3aed,#a855f7);color:white;">'
            html += '<th style="border:1px solid #6b21a8;padding:12px;text-align:left;width:10%;">PR Number</th>'
            html += '<th style="border:1px solid #6b21a8;padding:12px;text-align:left;width:8%;">Type</th>'
            html += '<th style="border:1px solid #6b21a8;padding:12px;text-align:left;width:10%;">SW Version</th>'
            html += '<th style="border:1px solid #6b21a8;padding:12px;text-align:left;width:25%;">Issue Description</th>'
            html += '<th style="border:1px solid #6b21a8;padding:12px;text-align:left;width:25%;">Solution / Benefit</th>'
            html += '<th style="border:1px solid #6b21a8;padding:12px;text-align:center;width:6%;">Score</th>'
            html += '</tr></thead><tbody>'
            
            for idx, pr in enumerate(result.get('similar_prs', [])):
                bg_color = "#faf5ff" if idx % 2 == 0 else "#ffffff"
                issue = pr.get("issue_description", "-")[:200]
                solution_or_benefit = pr.get("solution_or_benefit", pr.get("solution", "-"))[:200]
                
                # PR 유형에 따른 스타일
                pr_type = pr.get("pr_type", "unknown")
                pr_type_label = pr.get("pr_type_label", "")
                if pr_type == 'new_feature':
                    type_badge = '<span style="background:#22c55e;color:white;padding:2px 6px;border-radius:3px;font-size:11px;">New Feature</span>'
                elif pr_type == 'issue_fix':
                    type_badge = '<span style="background:#ef4444;color:white;padding:2px 6px;border-radius:3px;font-size:11px;">Issue Fix</span>'
                else:
                    type_badge = '<span style="background:#6b7280;color:white;padding:2px 6px;border-radius:3px;font-size:11px;">-</span>'
                
                # 키워드 하이라이트
                for kw in result.get("keywords", []):
                    issue = re.sub(f'({re.escape(kw)})', r'<mark style="background:#fef08a;">\1</mark>', issue, flags=re.IGNORECASE)
                
                html += f'<tr style="background:{bg_color};">'
                html += f'<td style="border:1px solid #ddd;padding:10px;font-family:monospace;font-weight:bold;color:#7c3aed;">{pr["pr_number"]}</td>'
                html += f'<td style="border:1px solid #ddd;padding:10px;text-align:center;">{type_badge}</td>'
                html += f'<td style="border:1px solid #ddd;padding:10px;font-family:monospace;font-size:12px;">{pr.get("sw_version", "-")}</td>'
                html += f'<td style="border:1px solid #ddd;padding:10px;color:#555;">{issue}</td>'
                html += f'<td style="border:1px solid #ddd;padding:10px;color:#065f46;">{solution_or_benefit}</td>'
                html += f'<td style="border:1px solid #ddd;padding:10px;text-align:center;font-weight:bold;color:#7c3aed;">{pr.get("relevance_score", 0)}</td>'
                html += '</tr>'
            
            html += '</tbody></table>'
            result['html_table'] = html
        
        return jsonify(result)
        
    except Exception as e:
        print(traceback.format_exc())
        return jsonify({'error': str(e)}), 500

@app.route('/powerbi_escalation_stats')
@login_required
def powerbi_escalation_stats():
    """
    Fetch Escalation data from Power BI
    Filter: Region=KOREA, Support Type=Software
    """
    try:
        print("🔄 Fetching Power BI Escalation data...")
        
        # Fetch from Power BI
        df = fetch_powerbi_data()
        
        if df is None or df.empty:
            print("⚠️ No Power BI data available, using sample data")
            # Return empty data structure
            return jsonify({
                'type2_tickets': [],
                'type3_tickets': [],
                'all_tickets': [],
                'data_source': 'powerbi_unavailable',
                'error': 'Power BI data not available. Please configure Azure AD credentials.'
            })
        
        print(f"✓ Power BI data loaded: {len(df)} rows")
        print(f"Columns: {df.columns.tolist()}")
        
        # Process data (adjust column names based on actual Power BI data structure)
        # Common Power BI columns: Ticket ID, Type, Days Open, Customer, Status, etc.
        
        type2_tickets = []
        type3_tickets = []
        all_tickets = []
        
        for _, row in df.iterrows():
            ticket = {
                'ticket_id': str(row.get('Ticket ID', row.get('TicketID', ''))),
                'type': str(row.get('Type', row.get('TicketType', ''))),
                'days_open': int(row.get('Days Open', row.get('DaysOpen', 0))),
                'customer': str(row.get('Customer', '')),
                'status': str(row.get('Status', '')),
                'priority': str(row.get('Priority', '')),
                'owner': str(row.get('Owner', row.get('Assigned To', ''))),
                'description': str(row.get('Description', row.get('Summary', ''))),
                'created_date': str(row.get('Created Date', row.get('CreatedDate', ''))),
                'region': str(row.get('Region', 'KOREA')),  # Pre-filtered
                'support_type': str(row.get('Support Type', 'Software'))  # Pre-filtered
            }
            
            all_tickets.append(ticket)
            
            # Categorize by type
            ticket_type = ticket['type'].lower()
            if 'type 2' in ticket_type or 'chronic' in ticket_type:
                type2_tickets.append(ticket)
            elif 'type 3' in ticket_type or 'pg' in ticket_type:
                type3_tickets.append(ticket)
        
        # Sort by days open (descending)
        type2_tickets.sort(key=lambda x: x['days_open'], reverse=True)
        type3_tickets.sort(key=lambda x: x['days_open'], reverse=True)
        
        print(f"✓ Processed: {len(type2_tickets)} Type 2 tickets, {len(type3_tickets)} Type 3 tickets")
        
        return jsonify({
            'type2_tickets': type2_tickets,
            'type3_tickets': type3_tickets,
            'all_tickets': all_tickets,
            'data_source': 'powerbi',
            'total_tickets': len(all_tickets),
            'filters': {
                'region': 'KOREA',
                'support_type': 'Software'
            },
            'last_updated': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        })
        
    except Exception as e:
        print("❌ Power BI Escalation Stats Error:")
        print(traceback.format_exc())
        return jsonify({
            'error': str(e),
            'traceback': traceback.format_exc(),
            'data_source': 'error'
        }), 500

@app.route('/sw_ib_stats')
@login_required
def sw_ib_stats():
    """
    Fetch SW IB Version data from CSV or SharePoint
    Returns SW version distribution and table data
    """
    try:
        
        all_tools = []
        data_source = "csv"
        
        # Try to read from CSV file
        csv_path = Config.get_sw_ib_version_csv()
        
        if csv_path.exists():
            print(f"✅ Found SW IB CSV: {csv_path}")
            try:
                df = pd.read_csv(csv_path, encoding='utf-8')
                data_source = "csv"
                
                for _, row in df.iterrows():
                    tool_id = str(row.get('Customer Tool ID', ''))
                    tool_type = str(row.get('Tool type', ''))
                    sw_version = str(row.get('S/W Version', ''))
                    
                    # Parse Tool type if it's in JSON array format
                    if tool_type.startswith('["') and tool_type.endswith('"]'):
                        try:
                            tool_list = json.loads(tool_type.replace("'", '"'))
                            tool_type = ', '.join(tool_list) if isinstance(tool_list, list) else tool_type
                        except:
                            pass
                    
                    all_tools.append({
                        'tool_id': tool_id,
                        'tool_type': tool_type,
                        'sw_version': sw_version
                    })
                
                print(f"✅ Loaded {len(all_tools)} tools from CSV")
                    
            except Exception as e:
                print(f"Error reading CSV: {e}")
                traceback.print_exc()
        
        # Count SW versions
        version_counts = {}
        chamber_types_by_version = {}  # Track chamber types for each version
        
        for tool in all_tools:
            version = tool['sw_version']
            chamber_type = tool['tool_type']
            
            version_counts[version] = version_counts.get(version, 0) + 1
            
            if version not in chamber_types_by_version:
                chamber_types_by_version[version] = {}
            chamber_types_by_version[version][chamber_type] = chamber_types_by_version[version].get(chamber_type, 0) + 1
        
        # Parse version and sort by SP then HF then Patch (lower to higher for display)
        def parse_version(version_str):
            """Parse version like '1.8.4-SP33-HF9e' or '1.8.4-SP20-HF9-Patch267' into (SP, HF, Patch)"""
            sp_match = re.search(r'SP(\d+)', version_str)
            hf_match = re.search(r'HF(\d+)', version_str)
            patch_match = re.search(r'Patch(\d+)', version_str)
            
            sp_num = int(sp_match.group(1)) if sp_match else 0
            hf_num = int(hf_match.group(1)) if hf_match else 0
            patch_num = int(patch_match.group(1)) if patch_match else 0
            
            return (sp_num, hf_num, patch_num)
        
        # Sort all versions by SP then HF then Patch (ascending for chart display left to right)
        sorted_versions_by_num = sorted(
            version_counts.items(),
            key=lambda x: parse_version(x[0])
        )
        # Keep as ordered list of tuples to preserve order in JSON
        sorted_versions = [(v, c) for v, c in sorted_versions_by_num]
        
        # Get Top 5 versions by count (for Top 5 pie chart)
        top5_by_count = sorted(version_counts.items(), key=lambda x: x[1], reverse=True)[:5]
        # Keep as list of tuples to preserve order (highest count first)
        top5_versions = [(v, c) for v, c in top5_by_count]
        
        # Sort versions by SP then HF (higher is better) for Top 5 Higher Versions
        sorted_by_version = sorted(
            [(v, c, chamber_types_by_version.get(v, {})) for v, c in version_counts.items()],
            key=lambda x: parse_version(x[0]),
            reverse=True
        )[:5]
        
        top5_higher_versions = {
            item[0]: {'count': item[1], 'chamber_types': item[2]} 
            for item in sorted_by_version
        }
        
        # Get highest version only for label display
        highest_version = sorted_by_version[0][0] if sorted_by_version else ""
        
        # Get highest SW version per Tool Type
        tool_type_highest = {}
        for tool in all_tools:
            tool_type = tool['tool_type']
            sw_version = tool['sw_version']
            
            if tool_type not in tool_type_highest:
                tool_type_highest[tool_type] = sw_version
            else:
                # Compare versions and keep the higher one
                if parse_version(sw_version) > parse_version(tool_type_highest[tool_type]):
                    tool_type_highest[tool_type] = sw_version
        
        # Sort tool types by name for table display
        tool_type_table = sorted(tool_type_highest.items(), key=lambda x: x[0])
        
        return jsonify({
            'version_counts': sorted_versions,  # List of [version, count] tuples
            'top5_versions': top5_versions,
            'top5_higher_versions': top5_higher_versions,
            'highest_version_label': highest_version,
            'tool_type_highest': tool_type_table,
            'tools': all_tools,
            'data_source': data_source,
            'total_tools': len(all_tools)
        })
        
    except Exception as e:
        print(f"❌ SW IB stats error: {e}")
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500

@app.route('/chat', methods=['POST'])
@login_required
def chat():
    """
    Multi-LLM Data Analysis Chatbot
    Supports: Rule-based, DeepSeek, Hugging Face, Groq, Google Gemini, OpenRouter
    """
    try:
        data = request.json
        user_message = data.get('message', '').lower()
        selected_model = data.get('model', 'local-rag')  # local-rag, rule-based, deepseek, huggingface, groq, gemini, openrouter
        
        if not user_message:
            return jsonify({'error': 'No message provided'}), 400
        
        print(f"💬 User question: {user_message}")
        print(f"🤖 Selected model: {selected_model}")
        
        # Fetch current dashboard data for analysis
        escalation_data = {}
        issues_data = {}
        sw_data = {}
        
        # Get Escalation data (Type 2, Type 3 tickets)
        try:
            escalation_df = pd.read_excel(Config.get_ticket_details_xlsx(), engine='openpyxl')
            
            # Check for required columns
            if 'Ticket Type' in escalation_df.columns:
                type3_tickets = escalation_df[escalation_df['Ticket Type'] == 'Type 3 (PG)']
                type2_tickets = escalation_df[escalation_df['Ticket Type'] == 'Type 2 (Chronic)']
                
                # Calculate average days if 'Created Date' exists
                avg_days = 0
                if 'Created Date' in type3_tickets.columns:
                    try:
                        avg_days = (pd.Timestamp.now() - pd.to_datetime(type3_tickets['Created Date'])).dt.days.mean()
                    except:
                        avg_days = 0
                
                escalation_data = {
                    'type3_count': len(type3_tickets),
                    'type3_avg_days': avg_days,
                    'products': type3_tickets['Product'].value_counts().to_dict() if 'Product' in type3_tickets.columns else {}
                }
            else:
                escalation_data = {'error': 'Ticket Type column missing'}
                
        except Exception as e:
            print(f"Escalation data error: {e}")
            escalation_data = {'error': str(e)}

        # Get Issues Tracking data
        try:
            issues_df = pd.read_csv(Config.get_issues_tracking_csv())
            
            # Clean up columns that might have JSON-like string formatting
            for col in ['Current Status', 'Module Type', 'Fab', 'Priority', 'SW Version']:
                if col in issues_df.columns:
                    # Remove [" and "] and " characters
                    issues_df[col] = issues_df[col].astype(str).str.replace(r'[\[\]"]', '', regex=True)
                    # Also remove single quotes if they exist
                    issues_df[col] = issues_df[col].str.replace("'", "")
            
            # Filter for last 3 months
            if 'Date reported' in issues_df.columns:
                issues_df['Date reported'] = pd.to_datetime(issues_df['Date reported'], errors='coerce')
                three_months_ago = pd.Timestamp.now() - pd.DateOffset(months=3)
                filtered_df = issues_df[issues_df['Date reported'] >= three_months_ago].copy()
            else:
                filtered_df = issues_df.copy()

            issues_data = {
                'total': len(filtered_df),
                'status_counts': filtered_df['Current Status'].value_counts().to_dict() if 'Current Status' in filtered_df.columns else {},
                'fab_counts': filtered_df['Fab'].value_counts().to_dict() if 'Fab' in filtered_df.columns else {},
                'module_counts': filtered_df['Module Type'].value_counts().to_dict() if 'Module Type' in filtered_df.columns else {},
                'priority_counts': filtered_df['Priority'].value_counts().to_dict() if 'Priority' in filtered_df.columns else {},
                'sw_versions': filtered_df['Issued SW'].value_counts().to_dict() if 'Issued SW' in filtered_df.columns else {},
                'df': filtered_df  # Pass the dataframe for detailed analysis
            }
        except Exception as e:
            print(f"Issues data error: {e}")
            issues_data = {'error': str(e)}

        # Get SW Version data
        try:
            sw_df = pd.read_csv(Config.get_tool_info_csv())
            sw_data = {
                'total_tools': len(sw_df),
                'versions': sw_df['SW Version'].value_counts().to_dict() if 'SW Version' in sw_df.columns else {}
            }
        except Exception as e:
            print(f"SW data error: {e}")
            sw_data = {'error': str(e)}

        # Generate response based on model
        if selected_model == 'rule-based':
            response = generate_rule_based_response(user_message, issues_data, escalation_data, sw_data)
        elif selected_model == 'local-rag':
            # Local RAG System (TF-IDF 기반 - 완전 오프라인)
            try:
                from local_rag import get_rag_system
                rag = get_rag_system()
                
                if not rag.initialized:
                    # Auto-initialize if not done
                    print("🔄 Auto-initializing RAG system...")
                    rag.load_and_index_data(force_reindex=False)
                
                # Query RAG
                rag_response = rag.rag_query(user_message)
                
                # Markdown to HTML 변환
                import re
                html_content = rag_response
                # ## 헤더
                html_content = re.sub(r'^## (.+)$', r'<h3 style="color:#7c3aed; margin:15px 0 10px 0;">\1</h3>', html_content, flags=re.MULTILINE)
                # ### 서브헤더
                html_content = re.sub(r'^### (.+)$', r'<h4 style="color:#2d3748; margin:12px 0 8px 0;">\1</h4>', html_content, flags=re.MULTILINE)
                # **볼드**
                html_content = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', html_content)
                # *이탤릭*
                html_content = re.sub(r'\*([^*]+)\*', r'<em style="color:#666;">\1</em>', html_content)
                # 테이블 변환
                lines = html_content.split('\n')
                in_table = False
                table_html = []
                new_lines = []
                for line in lines:
                    if line.strip().startswith('|') and line.strip().endswith('|'):
                        if not in_table:
                            in_table = True
                            table_html = ['<table style="width:100%; border-collapse:collapse; margin:10px 0; font-size:13px;">']
                        cells = [c.strip() for c in line.strip().split('|')[1:-1]]
                        if all(c.replace('-','') == '' for c in cells):
                            continue  # 구분선 스킵
                        if len(table_html) == 1:  # 헤더
                            table_html.append('<tr>' + ''.join(f'<th style="background:#e2e8f0; padding:8px; border:1px solid #cbd5e0; text-align:left;">{c}</th>' for c in cells) + '</tr>')
                        else:
                            table_html.append('<tr>' + ''.join(f'<td style="padding:8px; border:1px solid #e2e8f0;">{c}</td>' for c in cells) + '</tr>')
                    else:
                        if in_table:
                            table_html.append('</table>')
                            new_lines.append('\n'.join(table_html))
                            table_html = []
                            in_table = False
                        new_lines.append(line)
                if in_table:
                    table_html.append('</table>')
                    new_lines.append('\n'.join(table_html))
                html_content = '\n'.join(new_lines)
                # 줄바꿈 변환 - 이미 완전한 HTML인 경우(Delta Summary 등)는 건너뛰기
                if not ('<div style="font-family' in html_content or 'Delta Summary' in html_content):
                    html_content = html_content.replace('\n\n', '<br><br>').replace('\n', '<br>')
                
                # Format response with HTML
                response = f"""
<div class="bot-card" style="line-height: 1.6;">
    <div class="bot-card-header" style="margin-bottom: 10px;">
        <div class="chat-icon" style="width: 32px; height: 32px; display: flex; align-items: center; justify-content: center; background: #84BD00; border-radius: 8px;">
            <span style="color: white; font-weight: bold; font-size: 16px; font-family: Arial, sans-serif;">L</span>
        </div>
        <h2 class="bot-card-title" style="margin: 0; color: #00897b;">K-Bot Says:</h2>
    </div>
    <div style="background: linear-gradient(135deg, #f0fdf4, #ecfdf5); padding: 18px; border-radius: 12px; border-left: 4px solid #84BD00;">
        {html_content}
    </div>
    <p style="margin: 10px 0 0 0; font-size: 11px; color: #999;">
        🔒 완전 로컬 처리 | 외부 API 호출 없음 | TF-IDF 기반 검색
    </p>
</div>
"""
            except ImportError as e:
                response = f"❌ Local RAG 모듈을 로드할 수 없습니다: {e}"
            except Exception as e:
                response = f"❌ Local RAG 오류: {e}"
                traceback.print_exc()
        else:
            # Placeholder for other models
            response = f"Model {selected_model} not implemented yet."
            
        return jsonify({'response': response})

    except Exception as e:
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500

def generate_rule_based_response(question, issues_data, escalation_data, sw_data):
    response = ""
    question_types = []
    
    # Debug print
    print(f"DEBUG: Question='{question}'")
    
    if 'type 3' in question or 'type3' in question:
        question_types.append('type3')
    if 'sw' in question or 'version' in question:
        question_types.append('sw_version')
    if 'waiting' in question or 'pr' in question:
        question_types.append('waiting_pr')
    if 'fab' in question:
        question_types.append('fab')
    if 'm15' in question or 'nand' in question:
        question_types.append('fab') # M15 is a FAB question
        
    print(f"DEBUG: Detected Types={question_types}")
    print(f"DEBUG: Escalation Error={'error' in escalation_data}")
    print(f"DEBUG: Issues Error={'error' in issues_data}")
        
    # 1. Type 3 티켓 관련 질문
    if 'type3' in question_types:
        if 'error' not in escalation_data:
            type3_count = escalation_data.get('type3_count', 0)
        type3_avg_days = escalation_data.get('type3_avg_days', 0)
        products = escalation_data.get('products', {})
        
        response += f"""
<div class="bot-card">
    <div class="bot-card-header">
        <div class="chat-icon" style="width: 32px; height: 32px; font-size: 16px; background: #dc2626;">🚨</div>
        <h2 class="bot-card-title">Type 3 티켓 분석</h2>
    </div>
    
    <h3 style="color: #dc2626; margin: 5px 0; font-size: 14px;">Type 3 티켓이 많은 주요 원인</h3>
    <ul class="bot-list">
        <li><strong>현재 Type 3 티켓:</strong> <span class="bot-highlight">{type3_count}건</span> (평균 {type3_avg_days:.1f}일 오픈)</li>
        <li><strong>제품별 분포:</strong> {', '.join([f'{p}: {c}건' for p, c in sorted(products.items(), key=lambda x: x[1], reverse=True)[:5]])}</li>
        <li><strong>주요 원인:</strong>
            <ul style="margin-top: 5px;">
                <li>복잡한 시스템 문제로 해결까지 장기간 소요</li>
                <li>여러 부서 협업이 필요한 cross-functional 이슈</li>
                <li>근본 원인 분석(RCA)에 시간 소요</li>
            </ul>
        </li>
        <li><strong>개선 방향:</strong>
            <ul style="margin-top: 5px;">
                <li>Early detection 시스템 구축</li>
                <li>전문가 그룹 즉시 투입</li>
                <li>유사 케이스 DB 활용</li>
            </ul>
        </li>
    </ul>
</div>
"""
        return response
    
    # 2. SW 버전별 문제 분석
    if 'sw_version' in question_types and 'error' not in issues_data:
        sw_versions = issues_data.get('sw_versions', {})
        
        response += f"""
<div class="bot-card">
    <div class="bot-card-header">
        <div class="chat-icon" style="width: 32px; height: 32px; font-size: 16px; background: #7c3aed;">💾</div>
        <h2 class="bot-card-title">SW 버전 문제 분석</h2>
    </div>
    
    <h3 style="color: #7c3aed; margin: 5px 0; font-size: 14px;">가장 많은 문제가 발생한 SW 버전 Top 5</h3>
    <table class="bot-table">
        <thead>
            <tr>
                <th>순위</th>
                <th>SW 버전</th>
                <th style="text-align: center;">문제 건수</th>
            </tr>
        </thead>
        <tbody>
"""
        for idx, (sw, count) in enumerate(sorted(sw_versions.items(), key=lambda x: x[1], reverse=True)[:5], 1):
            response += f"""
        <tr>
            <td>#{idx}</td>
            <td><strong>{sw}</strong></td>
            <td style="text-align: center;"><span class="bot-badge bot-badge-red">{count}건</span></td>
        </tr>
"""
        response += """
        </tbody>
    </table>
    <h3 style="color: #7c3aed; margin: 15px 0 5px 0; font-size: 14px;">SW 업그레이드 우선순위 권장</h3>
    <ol class="bot-list">
        <li><strong>High Priority:</strong> 문제가 5건 이상인 버전은 즉시 업그레이드</li>
        <li><strong>Medium Priority:</strong> 2-4건인 버전은 다음 유지보수 기간에 업그레이드</li>
        <li><strong>Low Priority:</strong> 1건 이하는 모니터링 후 결정</li>
    </ol>
</div>
"""
        return response
    
    # 3. Waiting PR fix 개선 방법
    if 'waiting_pr' in question_types and 'error' not in issues_data:
        status_counts = issues_data.get('status_counts', {})
        waiting_pr_count = status_counts.get('Waiting PR fix', 0)
        
        # Try to get detailed PR info if available
        try:
            df = issues_data.get('df')
            if df is not None:
                waiting_pr_df = df[df['Current Status'].str.contains('Waiting PR fix', na=False)].copy()
            else:
                waiting_pr_df = pd.DataFrame()
            
            response += f"""
<div class="bot-card">
    <div class="bot-card-header">
        <div class="chat-icon" style="width: 32px; height: 32px; font-size: 16px; background: #f59e0b;">⏳</div>
        <h2 class="bot-card-title">Waiting PR Fix 상세 분석</h2>
    </div>
    
    <h3 style="color: #f59e0b; margin: 5px 0; font-size: 14px;">현재 상태: <span class="bot-highlight">{waiting_pr_count}건</span> 대기 중</h3>
    
    <table class="bot-table">
        <thead>
            <tr>
                <th>PR 번호</th>
                <th>제목</th>
                <th style="text-align: center;">Days Open</th>
            </tr>
        </thead>
        <tbody>
"""
            for idx, (_, row) in enumerate(waiting_pr_df.head(5).iterrows(), 1):
                pr_number = row.get('PR or ES ', 'N/A')
                title = row.get('Issue', 'No title')
                if len(str(title)) > 40:
                    title = str(title)[:40] + '...'
                
                # Calculate days open
                days = 'N/A'
                if pd.notna(row.get('Date reported')):
                    try:
                        date_reported = pd.to_datetime(row.get('Date reported'), errors='coerce')
                        if pd.notna(date_reported):
                            days = (pd.Timestamp.now() - date_reported).days
                    except:
                        pass
                
                response += f"""
        <tr>
            <td><strong class="bot-highlight" style="color: #dc2626;">{pr_number}</strong></td>
            <td>{title}</td>
            <td style="text-align: center;"><span class="bot-badge bot-badge-orange">{days}일</span></td>
        </tr>
"""
            response += """
        </tbody>
    </table>

    <h3 style="color: #059669; margin: 15px 0 5px 0; font-size: 14px;">📋 개선 방법</h3>
    
    <div style="background: #f0fdf4; padding: 12px; border-left: 4px solid #059669; margin-bottom: 10px; border-radius: 4px;">
        <h4 style="margin: 0 0 5px 0; color: #047857; font-size: 14px;">1. 프로세스 개선</h4>
        <ul class="bot-list" style="margin: 0;">
            <li>PR 리뷰 SLA 설정 (48시간 내 initial review)</li>
            <li>우선순위 라벨링 시스템 도입 (Critical/High/Normal)</li>
            <li>주간 PR 리뷰 회의 정례화</li>
        </ul>
    </div>
</div>
"""
            return response
        except Exception as e:
            print(f"Waiting PR detail error: {e}")
            # Fallback to simple view if CSV read fails
            pass

    # 4. FAB별 문제 분석
    if 'fab' in question_types and 'error' not in issues_data:
        fab_counts = issues_data.get('fab_counts', {})
        
        # FAB 분석
        response += f"""
<div class="bot-card">
    <div class="bot-card-header">
        <div class="chat-icon" style="width: 32px; height: 32px; font-size: 16px; background: #0891b2;">🏭</div>
        <h2 class="bot-card-title">FAB별 문제 분석</h2>
    </div>
    
    <h3 style="color: #0891b2; margin: 5px 0; font-size: 14px;">FAB별 이슈 발생 현황</h3>
    <table class="bot-table">
        <thead>
            <tr>
                <th>FAB</th>
                <th style="text-align: center;">이슈 건수</th>
                <th>비중</th>
            </tr>
        </thead>
        <tbody>
"""
        total_fab = sum(fab_counts.values())
        for fab, count in sorted(fab_counts.items(), key=lambda x: x[1], reverse=True):
            percentage = (count / total_fab * 100) if total_fab > 0 else 0
            response += f"""
        <tr>
            <td><strong>{fab}</strong></td>
            <td style="text-align: center;"><span class="bot-badge bot-badge-red">{count}건</span></td>
            <td>
                <div class="bot-progress-container">
                    <div class="bot-progress-bar-bg">
                        <div class="bot-progress-bar-fill" style="width: {percentage}%; background: #0891b2;"></div>
                    </div>
                    <span style="font-size: 12px;">{percentage:.1f}%</span>
                </div>
            </td>
        </tr>
"""
        response += """
        </tbody>
    </table>
</div>
"""
        return response
    
    # =================================================================
    # DEFAULT: GENERAL ISSUES TRACKING ANALYSIS (일반 전체 리포트)
    # =================================================================
    if 'error' not in issues_data:
        total = issues_data.get('total', 0)
        status_counts = issues_data.get('status_counts', {})
        fab_counts = issues_data.get('fab_counts', {})
        module_counts = issues_data.get('module_counts', {})
        priority_counts = issues_data.get('priority_counts', {})
        sw_versions = issues_data.get('sw_versions', {})
        df = issues_data.get('df')
        
        # Keyword Analysis
        from collections import Counter
        
        all_text = " ".join(df['Issue'].dropna().astype(str).tolist()).lower() if df is not None else ""
        words = re.findall(r'\w+', all_text)
        common_words = {'the', 'to', 'and', 'of', 'in', 'a', 'for', 'on', 'is', 'with', 'at', 'by', 'from', 'after', 'during', 'due', 'not', 'be', 'as', 'or', 'are', 'this', 'that', 'it', 'an', 'have', 'has', 'was', 'which', 'but', 'check', 'failed', 'following'}
        filtered_words = [w for w in words if w not in common_words and len(w) > 2 and not w.isdigit()]
        keyword_counts = Counter(filtered_words).most_common(10)
        
        # Sort SW versions for display
        sorted_sw_versions = sorted(sw_versions.items(), key=lambda x: x[1], reverse=True)[:5]
        
        # Generate HTML-based visual report
        response += f"""
<div class="bot-card" style="line-height: 1.3;">
    <div class="bot-card-header" style="margin-bottom: 10px;">
        <div class="chat-icon" style="width: 32px; height: 32px; font-size: 16px; background: #00897b;">📊</div>
        <h2 class="bot-card-title" style="margin: 0;">Issues Tracking 분석 보고서</h2>
    </div>
    <p style="margin: 0 0 10px 0; font-size: 13px; color: #666;">분석 기간: 최근 3개월 | 총 이슈: <span class="bot-highlight">{total}건</span></p>
    
    <!-- Problem SW Version (Top 5) - Vertical Bar Chart -->
    <h3 style="color: #00897b; margin: 0 0 8px 0; font-size: 14px;">💾 문제 발생 SW 버전 (Top 5)</h3>
    <div style="background: #f8f9fa; padding: 15px; border-radius: 8px; margin-bottom: 15px; border: 1px solid #eee;">
"""
        if sorted_sw_versions:
            max_sw_count = sorted_sw_versions[0][1] if sorted_sw_versions else 1
            response += """        <div style="display: flex; align-items: flex-end; justify-content: space-around; height: 120px; gap: 8px; border-bottom: 1px solid #ccc; padding-bottom: 5px;">
"""
            for idx, (sw, count) in enumerate(sorted_sw_versions, 1):
                bar_height = (count / max_sw_count * 100) if max_sw_count > 0 else 10
                if bar_height < 10: bar_height = 10
                response += f"""
            <div style="flex: 1; display: flex; flex-direction: column; align-items: center; justify-content: flex-end; height: 100%;">
                <div style="font-size: 11px; font-weight: bold; color: #dc2626; margin-bottom: 3px;">{count}</div>
                <div style="width: 100%; max-width: 45px; height: {bar_height}%; background: linear-gradient(180deg, #00897b, #4db6ac); border-radius: 4px 4px 0 0; min-height: 8px;"></div>
            </div>
"""
            response += """        </div>
        <div style="display: flex; justify-content: space-around; gap: 8px; margin-top: 5px;">
"""
            for idx, (sw, count) in enumerate(sorted_sw_versions, 1):
                # Shorten version name for display
                sw_short = sw.replace('1.8.4-', '').replace('-', '\n') if len(sw) > 12 else sw
                response += f"""            <div style="flex: 1; font-size: 8px; color: #333; text-align: center; font-weight: 600; line-height: 1.2; word-break: break-all;">{sw_short}</div>
"""
            response += """        </div>
"""
        else:
            response += """<p style="margin: 0; color: #999; font-size: 12px;">SW 버전 데이터가 없습니다.</p>"""
        
        response += """
    </div>

    <!-- Keyword Analysis - Vertical Bar Chart -->
    <h3 style="color: #00897b; margin: 0 0 8px 0; font-size: 14px;">🔍 주요 문제 키워드 분석 (Top 8)</h3>
    <div style="background: #f8f9fa; padding: 15px; border-radius: 8px; margin-bottom: 15px; border: 1px solid #eee;">
"""
        if keyword_counts:
            max_keyword_count = keyword_counts[0][1] if keyword_counts else 1
            top_keywords = keyword_counts[:8]
            response += """        <div style="display: flex; align-items: flex-end; justify-content: space-around; height: 120px; gap: 6px; border-bottom: 1px solid #ccc; padding-bottom: 5px;">
"""
            for word, count in top_keywords:
                bar_height = (count / max_keyword_count * 100) if max_keyword_count > 0 else 10
                if bar_height < 10: bar_height = 10
                response += f"""
            <div style="flex: 1; display: flex; flex-direction: column; align-items: center; justify-content: flex-end; height: 100%;">
                <div style="font-size: 10px; font-weight: bold; color: #7c3aed; margin-bottom: 3px;">{count}</div>
                <div style="width: 100%; max-width: 35px; height: {bar_height}%; background: linear-gradient(180deg, #7c3aed, #a78bfa); border-radius: 4px 4px 0 0; min-height: 8px;"></div>
            </div>
"""
            response += """        </div>
        <div style="display: flex; justify-content: space-around; gap: 6px; margin-top: 5px;">
"""
            for word, count in top_keywords:
                response += f"""            <div style="flex: 1; font-size: 9px; color: #333; text-align: center; font-weight: 600;">{word}</div>
"""
            response += """        </div>
"""
        response += """
    </div>

    <!-- Top 3 Problem Details -->
    <h3 style="color: #00897b; margin: 0 0 8px 0; font-size: 14px;">📋 상위 3개 문제 상세 분석</h3>
"""
        for idx, (word, count) in enumerate(keyword_counts[:3], 1):
            percentage = (count / total * 100) if total > 0 else 0
            examples = []
            if df is not None:
                example_rows = df[df['Issue'].str.contains(word, case=False, na=False)].head(3)
                for _, row in example_rows.iterrows():
                    issue_text = str(row['Issue'])
                    if len(issue_text) > 60: issue_text = issue_text[:60] + "..."
                    pr_link = row.get('PR or ES ', '#')
                    sw_ver = row.get('Issued SW', 'N/A')
                    examples.append(f'<div style="margin: 2px 0;"><a href="{pr_link}" target="_blank" style="color: #0066cc;">🔗</a> <span style="color: #555;">{issue_text}</span> <span style="font-size: 10px; color: #999;">| {sw_ver}</span></div>')
            
            examples_html = "".join(examples)
            
            response += f"""
    <div style="margin-bottom: 10px; border-left: 3px solid #00897b; padding-left: 10px;">
        <div style="font-weight: bold; color: #333; margin-bottom: 3px; font-size: 13px;">{idx}. {word.upper()} ({count}건, {percentage:.1f}%)</div>
        <div style="font-size: 11px; background: #f9f9f9; padding: 6px; border-radius: 4px;">{examples_html}</div>
    </div>
"""

        response += """
    <!-- Status Distribution Chart - Vertical Bar Chart -->
    <h3 style="color: #00897b; margin: 0 0 8px 0; font-size: 14px;">📈 상태별 분포</h3>
    <div style="background: #f8f9fa; padding: 15px; border-radius: 8px; margin-bottom: 15px; border: 1px solid #eee;">
"""
        sorted_status = sorted(status_counts.items(), key=lambda x: x[1], reverse=True)[:5]
        max_status_count = sorted_status[0][1] if sorted_status else 1
        
        response += """        <div style="display: flex; align-items: flex-end; justify-content: space-around; height: 120px; gap: 10px; border-bottom: 1px solid #ccc; padding-bottom: 5px;">
"""
        for status, count in sorted_status:
            bar_height = (count / max_status_count * 100) if max_status_count > 0 else 10
            if bar_height < 10: bar_height = 10
            response += f"""
            <div style="flex: 1; display: flex; flex-direction: column; align-items: center; justify-content: flex-end; height: 100%;">
                <div style="font-size: 11px; font-weight: bold; color: #00897b; margin-bottom: 3px;">{count}</div>
                <div style="width: 100%; max-width: 50px; height: {bar_height}%; background: linear-gradient(180deg, #00897b, #26a69a); border-radius: 4px 4px 0 0; min-height: 8px;"></div>
            </div>
"""
        response += """        </div>
        <div style="display: flex; justify-content: space-around; gap: 10px; margin-top: 5px;">
"""
        for status, count in sorted_status:
            # Clean up status text for display
            status_clean = status.replace('[', '').replace(']', '').replace('"', '').strip()
            if len(status_clean) > 15:
                status_clean = status_clean[:15] + '...'
            response += f"""            <div style="flex: 1; font-size: 9px; color: #555; text-align: center; font-weight: 600; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">{status_clean}</div>
"""
        response += """        </div>
    </div>
"""
        
        response += """
    </div>

    <!-- FAB Distribution Chart -->
    <h3 style="color: #00897b; margin: 0 0 8px 0; font-size: 14px;">🏭 FAB별 이슈 현황 (Top 5)</h3>
    <div style="background: #f8f9fa; padding: 15px; border-radius: 8px; margin-bottom: 15px; border: 1px solid #eee;">
"""
        sorted_fab = sorted(fab_counts.items(), key=lambda x: x[1], reverse=True)[:5]
        max_fab_count = sorted_fab[0][1] if sorted_fab else 1
        
        response += """    <div style="display: flex; align-items: flex-end; justify-content: space-around; height: 120px; gap: 10px; border-bottom: 1px solid #ccc; padding-bottom: 5px;">
"""
        for fab, count in sorted_fab:
            bar_height = (count / max_fab_count * 100) if max_fab_count > 0 else 0
            if bar_height < 10: bar_height = 10
            
            response += f"""
        <div style="flex: 1; display: flex; flex-direction: column; align-items: center; justify-content: flex-end; height: 100%;">
            <div style="font-size: 11px; font-weight: bold; color: #00897b; margin-bottom: 3px;">{count}</div>
            <div style="width: 100%; max-width: 40px; height: {bar_height}%; background: linear-gradient(180deg, #00897b, #26a69a); border-radius: 4px 4px 0 0; min-height: 5px;"></div>
        </div>
"""
        response += """    </div>
        <div style="display: flex; justify-content: space-around; gap: 10px; margin-top: 4px;">
"""
        for fab, _ in sorted_fab:
             response += f"""<div style="flex: 1; font-size: 9px; color: #555; text-align: center; font-weight: 600; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">{fab}</div>"""
        response += """</div>
    </div>

    <!-- Module Type Chart -->
    <h3 style="color: #00897b; margin: 0 0 8px 0; font-size: 14px;">🔧 Module Type (Top 5)</h3>
    <div style="background: #f8f9fa; padding: 15px; border-radius: 8px; margin-bottom: 15px; border: 1px solid #eee;">
"""
        sorted_modules = sorted(module_counts.items(), key=lambda x: x[1], reverse=True)[:5]
        max_module_count = sorted_modules[0][1] if sorted_modules else 1
        
        response += """    <div style="display: flex; align-items: flex-end; justify-content: space-around; height: 120px; gap: 10px; border-bottom: 1px solid #ccc; padding-bottom: 5px;">
"""
        for module, count in sorted_modules:
            bar_height = (count / max_module_count * 100) if max_module_count > 0 else 0
            if bar_height < 10: bar_height = 10
            
            response += f"""
        <div style="flex: 1; display: flex; flex-direction: column; align-items: center; justify-content: flex-end; height: 100%;">
            <div style="font-size: 11px; font-weight: bold; color: #00897b; margin-bottom: 3px;">{count}</div>
            <div style="width: 100%; max-width: 40px; height: {bar_height}%; background: linear-gradient(180deg, #00897b, #4db6ac); border-radius: 4px 4px 0 0; min-height: 5px;"></div>
        </div>
"""
        response += """    </div>
        <div style="display: flex; justify-content: space-around; gap: 10px; margin-top: 4px;">
"""
        for module, _ in sorted_modules:
             response += f"""<div style="flex: 1; font-size: 9px; color: #555; text-align: center; font-weight: 600; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">{module}</div>"""
        response += """</div>
    </div>

    <!-- Waiting PR Fix Section -->
    <h3 style="color: #f59e0b; margin: 0; font-size: 14px;">⏳ Waiting PR Fix (최근 3개월)</h3>
"""
        if df is not None:
            waiting_pr_df = df[df['Current Status'].str.contains('Waiting PR fix', na=False)].copy()
            
            long_pending = []
            if not waiting_pr_df.empty:
                for _, row in waiting_pr_df.iterrows():
                    if pd.notna(row.get('Date reported')):
                        try:
                            date_reported = pd.to_datetime(row.get('Date reported'), errors='coerce')
                            days_open = (pd.Timestamp.now() - date_reported).days
                            if days_open > 30:
                                long_pending.append((row.get('PR or ES ', 'N/A'), days_open))
                        except:
                            pass

            if not waiting_pr_df.empty:
                response += """<table class="bot-table" style="margin: 0; margin-top: 3px; width: 100%;">
        <thead><tr><th style="font-size: 14px;">PR 번호</th><th style="font-size: 14px;">Issue</th><th style="text-align: center; font-size: 14px;">Date</th></tr></thead>
        <tbody>
"""
                for _, row in waiting_pr_df.head(5).iterrows():
                    pr_num = row.get('PR or ES ', 'N/A')
                    issue_desc = str(row.get('Issue', ''))
                    if len(issue_desc) > 50: issue_desc = issue_desc[:50] + '...'
                    date_str = row.get('Date reported', '').strftime('%Y-%m-%d') if pd.notna(row.get('Date reported')) else 'N/A'
                    
                    response += f"""<tr><td><span class="bot-highlight">{pr_num}</span></td><td style="font-size: 13px;">{issue_desc}</td><td style="text-align: center; font-size: 13px;">{date_str}</td></tr>
"""
                response += """</tbody></table>
"""
                if long_pending:
                    response += f"""
    <div style="background: #fff3cd; padding: 8px; border-radius: 6px; border: 1px solid #ffeeba; margin: 8px 0;">
        <div style="font-size: 11px; color: #856404; font-weight: bold;">⚠️ 장기 미해결 PR (30일 이상):</div>
        <ul style="margin: 3px 0 0 15px; font-size: 11px; color: #856404; padding: 0;">
"""
                    for pr, days in long_pending[:5]:
                        response += f"<li style='margin: 2px 0;'><strong>{pr}</strong>: {days}일 경과</li>"
                    response += """</ul></div>
"""
            else:
                response += "<p style='font-size: 12px; color: #666; margin: 5px 0;'>최근 3개월 내 Waiting PR Fix 상태인 이슈가 없습니다.</p>"

        # Enhanced AI Summary
        top_fab = sorted_fab[0][0] if sorted_fab else 'N/A'
        top_fab_count = sorted_fab[0][1] if sorted_fab else 0
        top_module = sorted_modules[0][0] if sorted_modules else 'N/A'
        top_module_count = sorted_modules[0][1] if sorted_modules else 0
        waiting_count = status_counts.get('Waiting PR fix', 0)
        fixed_count = status_counts.get('Fixed by operating', 0) + status_counts.get('Fixed', 0)
        top_sw = sorted_sw_versions[0][0] if sorted_sw_versions else 'N/A'
        top_sw_count = sorted_sw_versions[0][1] if sorted_sw_versions else 0
        top_keyword = keyword_counts[0][0] if keyword_counts else 'N/A'
        
        # Calculate resolution rate
        resolution_rate = (fixed_count / total * 100) if total > 0 else 0
        
        response += f"""
    <div style="background: #e0f2f1; padding: 12px; border-radius: 8px; margin-top: 10px; border-left: 4px solid #00897b;">
        <p style="margin: 0; font-size: 13px; color: #00695c; line-height: 1.5;">
            <strong>💡 AI 분석 요약</strong><br>
            <br>
            📊 <strong>전체 현황:</strong> 최근 3개월간 총 <strong>{total}건</strong>의 이슈가 발생했으며, 현재 해결률은 <strong>{resolution_rate:.1f}%</strong>입니다.<br>
            <br>
            🏭 <strong>FAB 분석:</strong> <strong>{top_fab}</strong>에서 가장 많은 이슈({top_fab_count}건)가 발생했습니다. 해당 FAB의 장비 점검 및 운영 프로세스 검토를 권장합니다.<br>
            <br>
            🔧 <strong>모듈 분석:</strong> <strong>{top_module}</strong> 모듈에서 {top_module_count}건의 이슈가 집중되고 있어 예방적 유지보수가 필요합니다.<br>
            <br>
            💾 <strong>SW 버전:</strong> <strong>{top_sw}</strong> 버전에서 {top_sw_count}건으로 가장 많은 문제가 발생했습니다. 해당 버전의 패치 적용 또는 업그레이드를 검토하세요.<br>
            <br>
            🔑 <strong>핵심 키워드:</strong> "<strong>{top_keyword}</strong>" 관련 이슈가 빈번히 발생하고 있어 근본 원인 분석(RCA)이 필요합니다.<br>
            <br>
            ⏳ <strong>PR 현황:</strong> 현재 <strong>{waiting_count}건</strong>의 이슈가 PR Fix 대기 중입니다. 장기 미해결 건에 대한 escalation이 필요합니다.
        </p>
    </div>
</div>
"""
        return response
    
    return "죄송합니다. 데이터를 분석할 수 없습니다."


# =================================================================
# RAG System API Endpoints
# =================================================================

@app.route('/rag/status')
@login_required
def rag_status():
    """RAG 시스템 상태 확인"""
    try:
        from local_rag import get_rag_system
        rag = get_rag_system()
        status = rag.get_status()
        return jsonify(status)
    except ImportError as e:
        return jsonify({
            'error': f'RAG module not available: {e}',
            'initialized': False
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/rag/initialize', methods=['POST'])
@login_required
def rag_initialize():
    """RAG 시스템 초기화 및 데이터 인덱싱"""
    try:
        from local_rag import get_rag_system
        
        data = request.json or {}
        force_reindex = data.get('force_reindex', False)
        
        rag = get_rag_system()
        success = rag.load_and_index_data(force_reindex=force_reindex)
        
        return jsonify({
            'success': success,
            'document_count': len(rag.documents),
            'status': rag.get_status()
        })
    except ImportError as e:
        return jsonify({'error': f'RAG module not available: {e}'}), 500
    except Exception as e:
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@app.route('/rag/search', methods=['POST'])
@login_required
def rag_search():
    """RAG 벡터 검색"""
    try:
        from local_rag import get_rag_system
        
        data = request.json
        query = data.get('query', '')
        top_k = data.get('top_k', 5)
        
        if not query:
            return jsonify({'error': 'No query provided'}), 400
        
        rag = get_rag_system()
        
        if not rag.initialized:
            rag.load_and_index_data()
        
        results = rag.search(query, top_k=top_k)
        
        return jsonify({
            'query': query,
            'results': results,
            'count': len(results)
        })
    except ImportError as e:
        return jsonify({'error': f'RAG module not available: {e}'}), 500
    except Exception as e:
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


# ============================================================
# SWRN PDF 자동 인덱싱 (서버 시작 시)
# ============================================================
def auto_index_swrn():
    """Flask 시작 시 SWRN PDF 증분 인덱싱 실행"""
    try:
        from swrn_indexer import SWRNIndexer
        import threading
        
        def run_indexing():
            try:
                indexer = SWRNIndexer()
                
                # 인덱스 DB가 없거나 새 PDF가 있으면 인덱싱
                if not indexer.db_path.exists():
                    print("📚 SWRN Index not found. Building initial index...")
                    result = indexer.build_index()
                    if "error" not in result:
                        print(f"✅ SWRN Index built: {result.get('processed_files', 0)} files, {result.get('total_prs', 0)} PRs")
                else:
                    # 증분 인덱싱 (새 파일만)
                    result = indexer.build_index(force_rebuild=False)
                    new_files = result.get('processed_files', 0)
                    if new_files > 0:
                        print(f"✅ SWRN Index updated: {new_files} new files indexed")
                    else:
                        print("✅ SWRN Index is up to date")
            except Exception as e:
                print(f"⚠️ SWRN auto-indexing failed: {e}")
        
        # 백그라운드 스레드에서 실행 (서버 시작 지연 방지)
        thread = threading.Thread(target=run_indexing, daemon=True)
        thread.start()
        print("🔄 SWRN auto-indexing started in background...")
        
    except ImportError:
        print("ℹ️ SWRN Indexer not available (swrn_indexer.py missing)")
    except Exception as e:
        print(f"⚠️ SWRN auto-indexing setup failed: {e}")


@app.route('/swrn_reindex', methods=['POST'])
@login_required
def swrn_reindex():
    """SWRN PDF 수동 재인덱싱 API"""
    try:
        from swrn_indexer import SWRNIndexer
        
        force = request.args.get('force', 'false').lower() == 'true'
        indexer = SWRNIndexer()
        
        result = indexer.build_index(force_rebuild=force)
        
        if "error" in result:
            return jsonify({"success": False, "error": result["error"]}), 400
        
        return jsonify({
            "success": True,
            "message": "SWRN indexing completed",
            "stats": {
                "total_files": result.get("total_files", 0),
                "processed_files": result.get("processed_files", 0),
                "total_pages": result.get("total_pages", 0),
                "total_prs": result.get("total_prs", 0),
                "elapsed_seconds": round(result.get("elapsed_seconds", 0), 1)
            }
        })
    except ImportError:
        return jsonify({"success": False, "error": "SWRN Indexer not available"}), 500
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/swrn_status')
@login_required
def swrn_status():
    """SWRN 인덱스 상태 조회 API"""
    try:
        from swrn_indexer import SWRNIndexer
        import sqlite3
        
        indexer = SWRNIndexer()
        
        if not indexer.db_path.exists():
            return jsonify({
                "indexed": False,
                "message": "Index not built yet"
            })
        
        # DB에서 통계 조회
        conn = sqlite3.connect(str(indexer.db_path))
        cursor = conn.cursor()
        
        cursor.execute("SELECT COUNT(*) FROM pdf_files")
        total_files = cursor.fetchone()[0]
        
        cursor.execute("SELECT SUM(page_count) FROM pdf_files")
        total_pages = cursor.fetchone()[0] or 0
        
        cursor.execute("SELECT COUNT(DISTINCT pr_number) FROM pr_index")
        total_prs = cursor.fetchone()[0]
        
        cursor.execute("SELECT MAX(indexed_at) FROM pdf_files")
        last_indexed = cursor.fetchone()[0]
        
        conn.close()
        
        # SWRN 폴더의 PDF 파일 수
        pdf_count = len(list(indexer.swrn_folder.glob("*.pdf"))) if indexer.swrn_folder.exists() else 0
        
        return jsonify({
            "indexed": True,
            "db_size_mb": round(indexer.db_path.stat().st_size / 1024 / 1024, 1),
            "total_files": total_files,
            "total_pages": total_pages,
            "total_prs": total_prs,
            "last_indexed": last_indexed,
            "pdf_files_in_folder": pdf_count,
            "needs_update": pdf_count > total_files
        })
    except ImportError:
        return jsonify({"error": "SWRN Indexer not available"}), 500
    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == '__main__':
    import os
    # Flask debug 모드에서 reloader가 두 번 실행되는 것을 방지
    # WERKZEUG_RUN_MAIN이 'true'일 때만 인덱싱 실행 (reloader의 child 프로세스)
    # 또는 debug=False일 때 실행
    is_reloader_process = os.environ.get('WERKZEUG_RUN_MAIN') == 'true'
    
    if is_reloader_process:
        # Reloader child 프로세스에서만 인덱싱 실행 (한 번만)
        auto_index_swrn()
    
    app.run(host='0.0.0.0', port=8060, debug=True)


