# Deploying LawLedger with NSSM + IIS

This guide explains how to run LawLedger as a Windows service with
**NSSM** (Non-Sucking Service Manager) and make it accessible via IIS at
`http://<your-server>/lawledger`.

---

## Prerequisites

| Component | Details |
|-----------|---------|
| **Windows Server** (or Windows 10/11 Pro) | IIS enabled |
| **Python 3.10+** | Installed and in the PATH |
| **NSSM** | Downloaded from <https://nssm.cc/download> |
| **IIS – URL Rewrite** | Installed (Microsoft module) |
| **IIS – ARR (Application Request Routing)** | Installed and proxy enabled |
| **SQL Server** | Instance accessible from the server |

---

## 1. Preparing the Application

```powershell
# Clone or copy the repository into a permanent directory
# Example: C:\Apps\LawLedger
cd C:\Apps\LawLedger

# Create a virtual environment
python -m venv venv
venv\Scripts\activate

# Install the dependencies
pip install -r requirements.txt
```

### Configure the `.env` File

Create a `.env` file at the project root (`C:\Apps\LawLedger\.env`):

```ini
# ── Database ──
DB_SERVER=localhost
DB_NAME=LawLedger
DB_USER=sa
DB_PASSWORD=YourPassword
DB_DRIVER=ODBC Driver 17 for SQL Server

# ── Application ──
SECRET_KEY=a-random-secret-key
HOST=192.168.0.26
PORT=5000
USE_WAITRESS=true

# ── URL Prefix (IMPORTANT for /lawledger) ──
URL_PREFIX=/lawledger

# ── License ──
LICENSE_FILE=C:\Apps\LawLedger\config\license.json
```

> **Note:** `URL_PREFIX=/lawledger` tells Flask to generate all URLs
> with the `/lawledger` prefix. Without this variable, the application runs
> at the root (`/`).

---

## 2. Quick Test (without NSSM)

```powershell
cd C:\Apps\LawLedger
venv\Scripts\activate
python app.py
```

Open `http://127.0.0.1:5000/` in a browser to verify that
the application starts correctly.

---

## 3. Install the Service with NSSM

```powershell
# Open a command prompt as Administrator
nssm install LawLedger
```

In the NSSM window that opens:

| Field | Value |
|-------|-------|
| **Path** | `C:\Apps\LawLedger\venv\Scripts\python.exe` |
| **Startup directory** | `C:\Apps\LawLedger` |
| **Arguments** | `app.py` |

### "Environment" Tab

Add the environment variables (one per line):

```
USE_WAITRESS=true
URL_PREFIX=/lawledger
```

> The other variables are read from the `.env` file.

### "I/O" Tab (optional, for debugging)

| Field | Value |
|-------|-------|
| **Output (stdout)** | `C:\Apps\LawLedger\logs\stdout.log` |
| **Error (stderr)** | `C:\Apps\LawLedger\logs\stderr.log` |

Create the `logs` folder beforehand:

```powershell
mkdir C:\Apps\LawLedger\logs
```

### Start the Service

```powershell
nssm start LawLedger
```

Verification:

```powershell
nssm status LawLedger
# Should display: SERVICE_RUNNING
```

---

## 4. Configure IIS as a Reverse Proxy

### 4.1. Enable the ARR Proxy

1. Open **IIS Manager**
2. Select the server (root level)
3. Double-click **Application Request Routing Cache**
4. Click **Server Proxy Settings…** in the Actions panel
5. Check **Enable proxy** → **Apply**

### 4.2. Configure the Rewrite Rule

The `web.config` file is already included in the project. It must be placed at
the root of the default IIS site (`C:\inetpub\wwwroot\web.config`):

```xml
<?xml version="1.0" encoding="UTF-8"?>
<configuration>
  <system.webServer>
    <rewrite>
      <rules>
        <rule name="LawLedgerProxy" stopProcessing="true">
          <match url="^lawledger/?(.*)" />
          <action type="Rewrite" url="http://127.0.0.1:5000/{R:1}"
                  appendQueryString="true" />
        </rule>
      </rules>
    </rewrite>
  </system.webServer>
</configuration>
```

**What this rule does:**
- Intercepts any URL starting with `/lawledger/`
- Forwards the request to Flask at `http://127.0.0.1:5000/` by **stripping** the
  `/lawledger` prefix
- Flask reconstructs the prefix using the `URL_PREFIX` variable

### 4.3. Verify

Navigate to `http://192.168.0.26/lawledger` in a browser. You should
see the LawLedger login page.

---

## 5. Useful NSSM Commands

```powershell
# Check the status
nssm status LawLedger

# Stop the service
nssm stop LawLedger

# Restart the service
nssm restart LawLedger

# Edit the configuration
nssm edit LawLedger

# Remove the service
nssm remove LawLedger confirm
```

---

## 6. Troubleshooting

### The Application Does Not Start

1. Check the logs in `C:\Apps\LawLedger\logs\`
2. Test manually:
   ```powershell
   cd C:\Apps\LawLedger
   venv\Scripts\python.exe app.py
   ```
3. Verify that port 5000 is not already in use:
   ```powershell
   netstat -an | findstr :5000
   ```

### 502 Bad Gateway Error on IIS

- The LawLedger service is probably not running
- Check: `nssm status LawLedger`
- Verify that the ARR proxy is properly enabled

### Links/Redirects Are Not Working (404)

- Verify that `URL_PREFIX=/lawledger` is set in the `.env` or in the
  NSSM environment variables
- Restart the service after any change: `nssm restart LawLedger`

### The Login Page Loops or Assets Do Not Load

- Verify that the IIS Rewrite rule is in place and working
- Check the browser console (F12) for 404 errors on CSS/JS files

---

## 7. Architecture

```
  Browser
      │
      ▼
  http://192.168.0.26/lawledger/login
      │
      ▼
  IIS (port 80)
  ┌─────────────────────────────┐
  │  URL Rewrite + ARR Proxy    │
  │  /lawledger/login            │
  │       ↓ strip prefix         │
  │  → http://127.0.0.1:5000/login │
  └─────────────────────────────┘
      │
      ▼
  Flask/Waitress (port 5000)
  ┌─────────────────────────────┐
  │  SCRIPT_NAME = /lawledger   │
  │  Route: /login              │
  │  url_for('login')           │
  │    → /lawledger/login       │
  └─────────────────────────────┘
```
