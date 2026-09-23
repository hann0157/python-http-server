# Python HTTP Server（Python HTTP 伺服器）

A course project that implements a small HTTP/1.0 and HTTP/1.1 web server with Python TCP sockets.
It parses requests, creates responses, and handles files without a web framework.

這是使用 Python TCP Socket 實作的計算機網路課堂final project，支援部分 HTTP/1.0 與 HTTP/1.1 功能。
程式自行解析請求、組成回應並處理檔案，沒有使用現成的網頁框架。

## Features（功能）

| Feature（功能） | What the project does（實作內容） |
| --- | --- |
| Request parsing（請求解析） | Reads the request line, headers and body; receives bodies according to `Content-Length`（解析請求行、標頭與主體，依長度接收資料） |
| HTTP methods（HTTP 方法） | Handles `GET`, `HEAD`, `POST`, `PUT` and `DELETE`（處理讀取、只取標頭、提交、新增或覆寫、刪除） |
| Session cookie（登入狀態 Cookie） | Checks a server-generated session token before accessing protected pages（先驗證伺服器產生的登入識別碼） |
| Files（檔案） | Serves pages and supports browser uploads and downloads（提供網頁、瀏覽器上傳與下載） |
| Responses（回應） | Demonstrates status codes `200`, `301`, `400`, `404` and `505`（示範五種狀態碼） |
| Path validation（路徑檢查） | Rejects `../` traversal outside the `www` directory（拒絕以 `../` 存取 `www` 以外的路徑） |

## Run locally（在自己的電腦執行）

Requires Python 3; no third-party packages are needed.（需要 Python 3，無須安裝第三方套件。）

```bash
python server.py
```

Open `http://127.0.0.1:8080` in your browser.（在瀏覽器開啟上述本機網址。）

The **demo-only** credentials are `admin / 1234`（**僅供展示**的帳密為 `admin / 1234`）。Press `Ctrl+C` to stop the server（按 `Ctrl+C` 停止伺服器）。

## Run the checks（執行檢查）

Keep the server running, open another terminal in this folder, and run:（讓伺服器保持執行，另開一個終端機並在此資料夾執行：）

```bash
python test_server.py
```

The included test script checks 18 cases, including login, file operations, request errors and status codes.（附帶的測試程式檢查 18 種情況，包括登入、檔案操作、錯誤請求與狀態碼。）

## Files（檔案）

| Path（路徑） | Purpose（用途） |
| --- | --- |
| `server.py` | Server implementation（伺服器實作） |
| `test_server.py` | Socket-based checks（使用 Socket 的檢查程式） |
| `www/login.html` | Login page（登入頁） |
| `www/index.html` | Protected home page（登入後首頁） |
| `www/files/` | Example target for `PUT` and `DELETE`（檔案新增與刪除的範例目錄） |
| `www/uploads/` | Runtime uploads, excluded from Git（執行時上傳檔案，不納入 Git） |

## How it works（運作流程）

1. Accept a TCP connection and read bytes until the HTTP header terminator.（接受 TCP 連線，讀取資料直到 HTTP 標頭結束。）
2. Parse the request line, headers and body; reject unsupported or malformed requests.（解析請求行、標頭與主體，拒絕不支援或格式錯誤的請求。）
3. Check the session cookie and dispatch the request by path and method.（檢查登入 Cookie，再依路徑與方法決定處理方式。）
4. Send a status line, response headers and an optional body, then close the connection.（送出狀態行、回應標頭與可能的主體，最後關閉連線。）

## Scope and limitations（範圍與限制）

This is an educational server, **not a production service**. It listens on `127.0.0.1` by default, handles one connection at a time, uses a fixed demo password, and does not provide HTTPS or a user database. It rejects chunked request bodies and limits request body size to 5 MiB. The included checks verify selected behaviours; they are not a full security audit.

這是教學用途的伺服器，**不能直接用在正式服務**。預設只接受本機連線、一次處理一個連線，使用固定展示密碼，且沒有 HTTPS 或使用者資料庫；不支援分塊傳送的請求主體，主體大小上限為 5 MiB。附帶的測試只驗證部分行為，並非完整的安全檢查。
