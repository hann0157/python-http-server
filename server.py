import socket
import os

# Server 監聽設定
# 預設只接受本機連線，避免展示用帳密與檔案操作暴露在區域網路。
HOST = "127.0.0.1"
PORT = 8080

WEB_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "www"))
UPLOAD_ROOT = os.path.abspath(os.path.join(WEB_ROOT, "uploads"))

VALID_USERNAME = "admin"
VALID_PASSWORD = "1234"

# Server 每次啟動都產生新的隨機 Session Token 登入成功後放進 Cookie
SESSION_TOKEN = os.urandom(24).hex()

# 限制 Header、Body 大小及等待時間
# 避免 Client 無限傳送或一直占用連線
MAX_HEADER_SIZE = 64 * 1024
MAX_BODY_SIZE = 5 * 1024 * 1024
RECV_SIZE = 4096
CLIENT_TIMEOUT = 5

# 白名單：只接受作業指定的方法及 HTTP/1.0、HTTP/1.1
ALLOWED_METHODS = {"GET", "POST", "HEAD", "PUT", "DELETE"}
SUPPORTED_VERSIONS = {"HTTP/1.0", "HTTP/1.1"}

# 狀態碼對應的狀態描述
STATUS_TEXT = {
    200: "OK",
    301: "Moved Permanently",
    400: "Bad Request",
    404: "Not Found",
    505: "HTTP Version Not Supported",
}

def percent_decode(text, plus_as_space=False):
    # 自行解碼 URL 中的 %XX；表單模式下也可把 + 轉成空白
    result = bytearray()
    index = 0

    while index < len(text):
        char = text[index]

        if char == "%":
            # %E6 這類格式代表一個十六進位 Byte
            if index + 2 >= len(text):
                return None
            try:
                result.append(int(text[index + 1:index + 3], 16))
            except ValueError:
                return None
            index += 3
        elif char == "+" and plus_as_space:
            result.append(32)
            index += 1
        else:
            try:
                result.extend(char.encode("latin-1"))
            except UnicodeEncodeError:
                result.extend(char.encode("utf-8"))
            index += 1

    # URL 百分比編碼的內容以 UTF-8 還原成 Python 字串
    try:
        return result.decode("utf-8")
    except UnicodeDecodeError:
        return None

#把檔名編碼成可安全放進 URL 的 UTF-8 百分比格式
def percent_encode(text):
    safe = b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~"
    result = ""
    for byte in text.encode("utf-8"):
        if byte in safe:
            result += chr(byte)
        else:
            result += "%" + format(byte, "02X")
    return result

# 跳脫 HTML 特殊字元，避免檔名被瀏覽器當成 HTML 標籤或程式碼
def html_escape(text):
    return (text.replace("&", "&amp;")
                .replace("<", "&lt;")
                .replace(">", "&gt;")
                .replace('"', "&quot;")
                .replace("'", "&#39;"))

# 解析 application/x-www-form-urlencoded
def parse_form(body):
    try:
        text = body.decode("utf-8")
    except UnicodeDecodeError:
        return None

    values = {}
    if text == "":
        return values

    for item in text.split("&"):
        if "=" not in item:
            return None
        key, value = item.split("=", 1)
        key = percent_decode(key, plus_as_space=True)
        value = percent_decode(value, plus_as_space=True)
        if key is None or value is None:
            return None
        values[key] = value

    return values

# 從 multipart/form-data 的 Content-Type 取出各區塊分隔線
def multipart_boundary(content_type):
    parts = content_type.split(";")
    if parts[0].strip().lower() != "multipart/form-data":
        return None

    for item in parts[1:]:
        item = item.strip()
        if item.lower().startswith("boundary="):
            value = item.split("=", 1)[1].strip()
            if len(value) >= 2 and value[0] == '"' and value[-1] == '"':
                value = value[1:-1]
            if value == "" or "\r" in value or "\n" in value:
                return None
            try:
                return value.encode("ascii")
            except UnicodeEncodeError:
                return None
    return None

# 解析 Content-Disposition 參數
# 取得表單欄位名稱與上傳檔名
def disposition_parameters(value):
    parameters = {}
    for item in value.split(";")[1:]:
        item = item.strip()
        if "=" not in item:
            continue
        name, parameter = item.split("=", 1)
        parameter = parameter.strip()
        if len(parameter) >= 2 and parameter[0] == '"' and parameter[-1] == '"':
            parameter = parameter[1:-1]
        parameters[name.strip().lower()] = parameter
    return parameters

def parse_uploaded_file(content_type, body):
    # 解析 multipart Body 找出 name=file 的檔名與原始二進位內容
    boundary = multipart_boundary(content_type)
    if boundary is None:
        return None

    # multipart 用 --boundary 分隔不同欄位
    # 每個欄位也有自己的 Header 與 Body
    delimiter = b"--" + boundary
    for part in body.split(delimiter)[1:]:
        if part.startswith(b"--"):
            break
        if part.startswith(b"\r\n"):
            part = part[2:]
        if part.endswith(b"\r\n"):
            part = part[:-2]

        # 欄位 Header 和檔案資料之間使用 CRLF CRLF 分隔
        header_block, separator, data = part.partition(b"\r\n\r\n")
        if separator == b"":
            continue

        try:
            header_text = header_block.decode("iso-8859-1")
        except UnicodeDecodeError:
            return None

        part_headers = {}
        for line in header_text.split("\r\n"):
            if ":" not in line:
                return None
            name, value = line.split(":", 1)
            part_headers[name.strip().lower()] = value.strip()

        #  只取 HTML 表單中 <input name="file"> 所傳來的檔案欄位
        disposition = part_headers.get("content-disposition", "")
        parameters = disposition_parameters(disposition)
        if parameters.get("name") == "file" and "filename" in parameters:
            raw_filename = parameters["filename"]
            try:
                filename = raw_filename.encode("iso-8859-1").decode("utf-8")
            except (UnicodeEncodeError, UnicodeDecodeError):
                filename = raw_filename
            return filename, data
    return None

def receive_request(client):
    # 從 Client Socket 收完整 Request
    # 解析後回傳 request 字典或錯誤狀態碼
    data = b""

    # TCP 是資料串流 一次 recv() 不保證收到完整 Header 因此持續接收至 CRLF CRLF
    while b"\r\n\r\n" not in data:
        chunk = client.recv(RECV_SIZE)
        if not chunk:
            return None, 400
        data += chunk
        if len(data) > MAX_HEADER_SIZE:
            return None, 400

    # HTTP Header 與 Body 中間固定有一個空白行(就是\r\n\r\n)
    header_bytes, body = data.split(b"\r\n\r\n", 1)

    try:
        header_text = header_bytes.decode("iso-8859-1")
    except UnicodeDecodeError:
        return None, 400

    # 第一行格式：Method SP Request-Target SP HTTP-Version
    lines = header_text.split("\r\n")
    request_line = lines[0].split(" ")

    if len(request_line) != 3 or "" in request_line:
        return None, 400

    method, target, version = request_line

    # 不支援的 HTTP 版本回 505
    if version not in SUPPORTED_VERSIONS:
        return None, 505

    # 格式或方法錯誤回 400
    if method not in ALLOWED_METHODS:
        return None, 400
    if not target.startswith("/"):
        return None, 400

    # 每個 Header 用第一個冒號切成 name/value
    # 名稱統一轉小寫 用來忽略大小寫
    headers = {}
    for line in lines[1:]:
        if line == "" or ":" not in line:
            return None, 400
        name, value = line.split(":", 1)
        name = name.strip().lower()
        value = value.strip()
        if name == "" or any(char.isspace() for char in name):
            return None, 400
        if name in headers and headers[name] != value:
            return None, 400
        headers[name] = value

    # HTTP/1.1 規定必須有 Host
    # HTTP/1.0 允許沒有
    if version == "HTTP/1.1" and "host" not in headers:
        return None, 400

    # 只實作 Content-Length 不支援 chunked Transfer-Encoding
    if "transfer-encoding" in headers:
        return None, 400

    content_length = 0
    if "content-length" in headers:
        try:
            content_length = int(headers["content-length"])
        except ValueError:
            return None, 400
        if content_length < 0 or content_length > MAX_BODY_SIZE:
            return None, 400

    # Header 收完時 Body 可能尚未全部到達 用 Content-Length 繼續 recv()
    while len(body) < content_length:
        chunk = client.recv(min(RECV_SIZE, content_length - len(body)))
        if not chunk:
            return None, 400
        body += chunk

    body = body[:content_length]

    # 將解析結果集中存入字典
    # 交給後續 Router 與各 Method Handler 使用
    request = {
        "method": method,
        "target": target,
        "version": version,
        "headers": headers,
        "body": body,
    }
    return request, None

# 建立簡單 HTML Body
def make_html(title, message, hyperlink=None):
    link = ""
    if hyperlink is not None:
        url, text = hyperlink
        link = '<p><a href="' + url + '">' + text + "</a></p>"

    html = (
        "<!doctype html>"
        '<html lang="zh-Hant"><head><meta charset="utf-8">'
        "<title>" + title + "</title></head><body>"
        "<h1>" + title + "</h1><p>" + message + "</p>" + link +
        "</body></html>"
    )
    return html.encode("utf-8")

# 組合完整 HTTP Response 並透過 Client Socket 傳回
def send_response(client, status, body=b"", content_type="text/html; charset=utf-8",
                    extra_headers=None, send_body=True):
    reason = STATUS_TEXT[status]

    # Response 格式：Status Line + Headers + 空白行 + Body
    headers = [
        "HTTP/1.1 " + str(status) + " " + reason,
        "Server: CYCU-Simple-Python-Server",
        "Content-Type: " + content_type,
        "Content-Length: " + str(len(body)),
        "Connection: close",
    ]

    if extra_headers is not None:
        for name, value in extra_headers:
            headers.append(name + ": " + value)

    # 每行以 CRLF 結束
    # 最後再加一組 CRLF 形成 Header 和 Body 間的空白行
    response_head = ("\r\n".join(headers) + "\r\n\r\n").encode("iso-8859-1")

    # sendall() 會持續送到資料全部交給作業系統
    # HEAD 只送 Header、不送 Body
    if send_body:
        client.sendall(response_head + body)
    else:
        client.sendall(response_head)

# 建立 400、404、505...錯誤頁面後 交由 send_response() 傳送
def send_error(client, status, send_body=True):
    body = make_html(str(status) + " " + STATUS_TEXT[status],
                        "The server could not process this request.")
    send_response(client, status, body, send_body=send_body)

# 回傳 301、Location Header、Hyperlink 登入時也可附加 Set-Cookie
def send_redirect(client, location, message, send_body=True, cookie=None):
    body = make_html("301 Moved Permanently", message, (location, "Continue to " + location))
    headers = [("Location", location)]
    if cookie is not None:
        headers.append(("Set-Cookie", cookie))
    send_response(client, 301, body, extra_headers=headers, send_body=send_body)

# 依副檔名選擇 MIME Type 讓瀏覽器知道應如何處理 Response Body
def content_type_for(path):
    extension = os.path.splitext(path)[1].lower()
    types = {
        ".html": "text/html; charset=utf-8",
        ".htm": "text/html; charset=utf-8",
        ".css": "text/css; charset=utf-8",
        ".js": "application/javascript; charset=utf-8",
        ".txt": "text/plain; charset=utf-8",
        ".json": "application/json; charset=utf-8",
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".gif": "image/gif",
        ".svg": "image/svg+xml",
        ".pdf": "application/pdf",
        ".doc": "application/msword",
        ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ".zip": "application/zip",
    }
    return types.get(extension, "application/octet-stream")

# 移除 Query String、解碼 URL 並將反斜線統一成斜線
def request_path(target):
    path = target.split("?", 1)[0]
    decoded = percent_decode(path)
    if decoded is None or "\x00" in decoded:
        return None
    return decoded.replace("\\", "/")

# 把 URL 映射到 www 內的實體路徑 並阻擋 ../ 路徑穿越攻擊
def safe_file_path(url_path):
    relative = url_path.lstrip("/")
    full_path = os.path.abspath(os.path.join(WEB_ROOT, relative))

    # commonpath 必須仍是 WEB_ROOT 否則代表使用者企圖存取 www 外部
    try:
        if os.path.commonpath([WEB_ROOT, full_path]) != WEB_ROOT:
            return None
    except ValueError:
        return None
    return full_path

# 只保留檔名本身 並移除 Windows 不允許或有風險的字元
def clean_upload_filename(filename):
    filename = filename.replace("\\", "/").split("/")[-1].strip()
    filename = "".join(char for char in filename
                        if ord(char) >= 32 and char not in {'"', "<", ">", ":", "|", "?", "*"})
    if filename in {"", ".", ".."}:
        return None
    return filename

# 確認 上傳／下載 的實體路徑一定位於 www/uploads 之內
def safe_upload_path(filename):
    full_path = os.path.abspath(os.path.join(UPLOAD_ROOT, filename))
    try:
        if os.path.commonpath([UPLOAD_ROOT, full_path]) != UPLOAD_ROOT:
            return None
    except ValueError:
        return None

    return full_path

def cookie_value(headers, wanted_name):
    # 從 Cookie Header 的多組 name=value 中尋找指定 Cookie
    cookie = headers.get("cookie", "")
    for item in cookie.split(";"):
        item = item.strip()
        if "=" not in item:
            continue
        name, value = item.split("=", 1)
        if name.strip() == wanted_name:
            return value.strip()
    return None

def is_authenticated(headers):
    # 比較 Client 的 session Cookie 與 Server 啟動時產生的 Token
    return cookie_value(headers, "session") == SESSION_TOKEN

def handle_login(client, request):
    # 處理 POST /login：驗證帳密
    # 成功後用 Set-Cookie 建立登入狀態
    content_type = request["headers"].get("content-type", "")
    if "application/x-www-form-urlencoded" not in content_type:
        send_error(client, 400)
        return

    values = parse_form(request["body"])
    if values is None:
        send_error(client, 400)
        return

    # 登入成功回 301 並設定 Cookie  失敗則回 400
    if (values.get("username") == VALID_USERNAME and
            values.get("password") == VALID_PASSWORD):
        cookie = "session=" + SESSION_TOKEN + "; Path=/; HttpOnly; SameSite=Lax"
        send_redirect(client, "/index.html", "Login successful.", cookie=cookie)
    else:
        send_response(
            client,
            400,
            make_html("400 Bad Request", "Wrong username or password.", ("/login.html", "Back to login")),
        )

# 從 www 讀取指定檔案
# GET 回 Header+Body  HEAD 只回相同 Header
def handle_get_or_head(client, request, url_path):
    send_body = request["method"] != "HEAD"
    full_path = safe_file_path(url_path)

    if full_path is None:
        send_error(client, 400, send_body=send_body)
        return

    # 如果網址是資料夾 補上斜線後再使用該資料夾的 index.html
    if os.path.isdir(full_path):
        if not url_path.endswith("/"):
            send_redirect(client, url_path + "/", "Directory path redirected.", send_body=send_body)
            return
        full_path = os.path.join(full_path, "index.html")

    if not os.path.isfile(full_path):
        send_error(client, 404, send_body=send_body)
        return

    # 使用 rb 讀取才能同時支援文字、圖片、PDF 等二進位檔案
    try:
        with open(full_path, "rb") as file:
            body = file.read()
    except OSError:
        send_error(client, 404, send_body=send_body)
        return

    send_response(client, 200, body, content_type_for(full_path), send_body=send_body)

def files_page():
    # 動態建立 /files 頁面  包含上傳表單及可下載的檔案清單
    items = []
    try:
        names = sorted(os.listdir(UPLOAD_ROOT), key=lambda value: value.lower())
    except OSError:
        names = []

    for name in names:
        full_path = safe_upload_path(name)
        if full_path is None or not os.path.isfile(full_path):
            continue
        encoded = percent_encode(name)
        items.append(
            "<li>" + html_escape(name) + " - "
            '<a href="/download/' + encoded + '">Download</a></li>'
        )

    if items:
        file_list = "<ul>" + "".join(items) + "</ul>"
    else:
        file_list = "<p>No uploaded files.</p>"

    html = (
        "<!doctype html><html lang=\"zh-Hant\"><head><meta charset=\"utf-8\">"
        "<title>Upload and Download Files</title></head><body>"
        "<h1>Upload and Download Files</h1>"
        '<form action="/upload" method="post" enctype="multipart/form-data">'
        '<input type="file" name="file" required> '
        '<button type="submit">Upload</button></form>'
        "<h2>Uploaded files</h2>" + file_list +
        '<p><a href="/index.html">Back to home</a></p>'
        "</body></html>"
    )
    return html.encode("utf-8")

# 回傳檔案管理頁面  若是 HEAD 則不傳送頁面 Body
def handle_files_page(client, request):
    body = files_page()
    send_response(client, 200, body, send_body=request["method"] != "HEAD")

# 處理 POST / upload
# 解析 multipart 檔案 並安全寫入 uploads 資料夾
def handle_upload(client, request):
    content_type = request["headers"].get("content-type", "")
    uploaded = parse_uploaded_file(content_type, request["body"])
    if uploaded is None:
        send_error(client, 400)
        return

    filename, data = uploaded
    filename = clean_upload_filename(filename)
    if filename is None:
        send_error(client, 400)
        return

    full_path = safe_upload_path(filename)
    if full_path is None:
        send_error(client, 400)
        return

    # wb 可原封不動保存文字、圖片、Word 等各種二進位內容
    try:
        with open(full_path, "wb") as file:
            file.write(data)
    except OSError:
        send_error(client, 400)
        return

    body = make_html(
        "200 OK",
        "The file was uploaded successfully: " + html_escape(filename),
        ("/files", "Back to file list"),
    )
    send_response(client, 200, body)

# 處理 GET/HEAD /download/檔名  讓瀏覽器以下載附件的方式接收檔案
def handle_download(client, request, filename):
    send_body = request["method"] != "HEAD"
    if "/" in filename or "\\" in filename:
        send_error(client, 400, send_body=send_body)
        return
    filename = clean_upload_filename(filename)
    if filename is None:
        send_error(client, 400, send_body=send_body)
        return

    full_path = safe_upload_path(filename)
    if full_path is None:
        send_error(client, 400, send_body=send_body)
        return
    if not os.path.isfile(full_path):
        send_error(client, 404, send_body=send_body)
        return

    try:
        with open(full_path, "rb") as file:
            body = file.read()
    except OSError:
        send_error(client, 404, send_body=send_body)
        return

    # Content-Disposition: attachment 會要求瀏覽器下載 而不是直接顯示
    # filename* 使用 UTF-8 百分比編碼 可保留中文檔名
    ascii_name = "".join(char if 32 <= ord(char) < 127 and char not in {'"', "\\"}
                        else "_" for char in filename)
    disposition = ("attachment; filename=\"" + ascii_name + "\"; filename*=UTF-8''" +
                    percent_encode(filename))
    send_response(
        client,
        200,
        body,
        content_type_for(full_path),
        extra_headers=[("Content-Disposition", disposition)],
        send_body=send_body,
    )

# 一般 POST 測試：接收 Request Body 並將收到的內容回傳給 Client
def handle_post(client, request):
    body = b"POST data received:\n" + request["body"]
    send_response(client, 200, body, "text/plain; charset=utf-8")

# 將 PUT Request Body 寫入 URL 指定的 www 檔案 可以建立或覆寫
def handle_put(client, request, url_path):
    full_path = safe_file_path(url_path)

    if full_path is None or url_path.endswith("/"):
        send_error(client, 400)
        return

    parent = os.path.dirname(full_path)
    try:
        os.makedirs(parent, exist_ok=True)
        with open(full_path, "wb") as file:
            file.write(request["body"])
    except OSError:
        send_error(client, 400)
        return

    body = make_html("200 OK", "The file was stored successfully.", (url_path, "Open the file"))
    send_response(client, 200, body)

# 刪除 URL 指定的檔案
# 不存在回 404 delete成功回 200
def handle_delete(client, url_path):
    full_path = safe_file_path(url_path)

    if full_path is None:
        send_error(client, 400)
        return
    if not os.path.isfile(full_path):
        send_error(client, 404)
        return

    try:
        os.remove(full_path)
    except OSError:
        send_error(client, 400)
        return

    send_response(client, 200, make_html("200 OK", "The file was deleted successfully."))

# HTTP Router：先驗證 再依路徑與 Method 分派給對應 Handler
def process_request(client, request):
    method = request["method"]
    url_path = request_path(request["target"])

    if url_path is None:
        send_error(client, 400, send_body=method != "HEAD")
        return

    # 登入頁必須在驗證 Cookie 前處理 否則未登入者永遠無法登入
    if method == "POST" and url_path == "/login":
        handle_login(client, request)
        return

    # 登出時以 Max-Age=0 要求瀏覽器立刻刪除 session Cookie
    if url_path == "/logout":
        expired_cookie = "session=; Path=/; Max-Age=0; HttpOnly; SameSite=Lax"
        send_redirect(client, "/login.html", "You have logged out.", send_body=method != "HEAD", cookie=expired_cookie)
        return

    # 除公開登入頁外 所有檔案與功能都必須先通過 Cookie 驗證
    public_login_page = url_path == "/login.html" and method in {"GET", "HEAD"}
    if not public_login_page and not is_authenticated(request["headers"]):
        send_redirect(client, "/login.html", "Please log in before accessing this page.", send_body=method != "HEAD")
        return

    # 驗證完成後才正式 Routing  順序由特殊路徑到一般 HTTP Method
    if url_path == "/":
        send_redirect(client, "/index.html", "The current page has moved.",
                        send_body=method != "HEAD")
    elif url_path == "/files" and method in {"GET", "HEAD"}:
        handle_files_page(client, request)
    elif url_path == "/upload" and method == "POST":
        handle_upload(client, request)
    elif url_path.startswith("/download/") and method in {"GET", "HEAD"}:
        handle_download(client, request, url_path[len("/download/"):])
    elif method in {"GET", "HEAD"}:
        handle_get_or_head(client, request, url_path)
    elif method == "POST":
        handle_post(client, request)
    elif method == "PUT":
        handle_put(client, request, url_path)
    elif method == "DELETE":
        handle_delete(client, url_path)
    else:
        send_error(client, 400)

def handle_client(client, address):
    # 處理單一 Client 連線：接收 Request、記錄紀錄、執行並回應
    client.settimeout(CLIENT_TIMEOUT)
    try:
        request, error_status = receive_request(client)
        if error_status is not None:
            send_error(client, error_status)
            print(address[0], "->", error_status)
            return

        print(address[0], "->", request["method"], request["target"])
        process_request(client, request)

    # 網路逾時、Client 中斷或檔案 I/O 錯誤時 盡可能回傳 400 而不讓 Server 崩潰
    except (socket.timeout, ConnectionError, OSError):
        try:
            send_error(client, 400)
        except OSError:
            pass

# 建立監聽 Socket 並進入 accept()
def run_server():
    # exist_ok=True 代表資料夾已存在也不會報錯
    os.makedirs(WEB_ROOT, exist_ok=True)
    os.makedirs(UPLOAD_ROOT, exist_ok=True)

    # AF_INET 代表 IPv4
    # SOCK_STREAM 代表可靠、有連線的 TCP
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
        # 重新啟動程式時允許快速重用 8080，避免 Address already in use
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

        # bind 指定本機位址與 Port
        server.bind((HOST, PORT))
        # listen 建立等待連線的佇列
        server.listen(10)

        print("Simple Web Server is running")
        print("Open: http://127.0.0.1:" + str(PORT))
        print("Files: http://127.0.0.1:" + str(PORT) + "/files")
        print("Login: " + VALID_USERNAME + " / " + VALID_PASSWORD)
        print("Press Ctrl+C to stop")

        try:
            while True:
                # accept() 會等待連線 回傳 Client Socket 與來源位址
                client, address = server.accept()

                # with 區塊結束後自動關閉該 Client 連線
                with client:
                    handle_client(client, address)
        except KeyboardInterrupt:
            print("\nServer stopped.")

if __name__ == "__main__":
    run_server()
