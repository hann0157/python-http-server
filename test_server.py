import socket
import os

HOST = "127.0.0.1"
PORT = 8080
PASSED = 0
FAILED = 0

def send_raw(request):
    data = b""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as client:
        client.settimeout(3)
        client.connect((HOST, PORT))
        client.sendall(request)
        while True:
            try:
                chunk = client.recv(4096)
            except socket.timeout:
                break
            if not chunk:
                break
            data += chunk
    return data

def parse_response(response):
    if b"\r\n\r\n" not in response:
        return None, {}, b""
    head, body = response.split(b"\r\n\r\n", 1)
    lines = head.decode("iso-8859-1").split("\r\n")
    status = int(lines[0].split(" ")[1])
    headers = {}
    for line in lines[1:]:
        name, value = line.split(":", 1)
        headers[name.lower()] = value.strip()
    return status, headers, body

def request(method, path, headers=None, body=b"", version="HTTP/1.1"):
    if headers is None:
        headers = {}
    headers["Host"] = "127.0.0.1"
    headers["Connection"] = "close"
    if body or method in {"POST", "PUT"}:
        headers["Content-Length"] = str(len(body))

    lines = [method + " " + path + " " + version]
    for name, value in headers.items():
        lines.append(name + ": " + value)
    raw = ("\r\n".join(lines) + "\r\n\r\n").encode("iso-8859-1") + body
    return parse_response(send_raw(raw))

def check(name, condition, detail=""):
    global PASSED, FAILED
    if condition:
        PASSED += 1
        print("[PASS]", name)
    else:
        FAILED += 1
        print("[FAIL]", name, detail)

def main():
    status, headers, body = request("GET", "/")
    check("301 redirects unauthenticated user", status == 301 and
            headers.get("location") == "/login.html" and b"<a href=" in body,
            str(status))

    status, headers, body = request("GET", "/login.html")
    check("200 serves login page", status == 200 and b"<form" in body,
            str(status))

    login_body = b"username=admin&password=1234"
    status, headers, body = request(
        "POST",
        "/login",
        {"Content-Type": "application/x-www-form-urlencoded"},
        login_body,
    )
    cookie_header = headers.get("set-cookie", "")
    cookie = cookie_header.split(";", 1)[0]
    check("Cookie authentication login", status == 301 and cookie.startswith("session="),
            str(status))

    auth = {"Cookie": cookie}

    status, headers, body = request("GET", "/index.html", dict(auth))
    check("GET returns requested file", status == 200 and b"Final Project" in body,
            str(status))

    status, headers, body = request("HEAD", "/index.html", dict(auth))
    check("HEAD returns headers only", status == 200 and body == b"" and
            int(headers.get("content-length", "0")) > 0, str(status))

    status, headers, body = request("GET", "/missing.txt", dict(auth))
    check("404 for missing file", status == 404, str(status))

    status, headers, body = request(
        "GET", "/index.html", {"Cookie": "session=wrong-token"}
    )
    check("Invalid Cookie is rejected", status == 301 and
            headers.get("location") == "/login.html", str(status))

    bad_request = b"GET / HTTP/1.1\r\nConnection: close\r\n\r\n"
    status, headers, body = parse_response(send_raw(bad_request))
    check("400 for malformed request", status == 400, str(status))

    status, headers, body = request("GET", "/", dict(auth), version="HTTP/9.9")
    check("505 for unsupported version", status == 505, str(status))

    patch_request = (
        "PATCH /index.html HTTP/1.1\r\n"
        "Host: 127.0.0.1\r\n"
        "Cookie: " + cookie + "\r\n"
        "Connection: close\r\n\r\n"
    ).encode("iso-8859-1")
    status, headers, body = parse_response(send_raw(patch_request))
    check("400 for unsupported method", status == 400, str(status))

    status, headers, body = request("GET", "/%2e%2e/server.py", dict(auth))
    check("400 blocks path traversal", status == 400, str(status))

    http_10_request = b"GET /login.html HTTP/1.0\r\nConnection: close\r\n\r\n"
    status, headers, body = parse_response(send_raw(http_10_request))
    check("HTTP/1.0 works without Host", status == 200, str(status))

    lowercase_header_request = (
        "GET /index.html HTTP/1.1\r\n"
        "host: 127.0.0.1\r\n"
        "cookie: " + cookie + "\r\n"
        "connection: close\r\n\r\n"
    ).encode("iso-8859-1")
    status, headers, body = parse_response(send_raw(lowercase_header_request))
    check("Header names are case-insensitive", status == 200, str(status))

    file_body = b"PUT test file from raw socket"
    status, headers, body = request("PUT", "/files/machine_test.txt", dict(auth), file_body)
    check("PUT stores a file", status == 200, str(status))

    status, headers, body = request("GET", "/files/machine_test.txt", dict(auth))
    check("GET reads PUT file", status == 200 and body == file_body, str(status))

    post_body = b"name=Lin&project=web-server"
    status, headers, body = request("POST", "/echo", dict(auth), post_body)
    check("POST accepts request body", status == 200 and post_body in body,
            str(status))

    status, headers, body = request("DELETE", "/files/machine_test.txt", dict(auth))
    check("DELETE removes a file", status == 200, str(status))

    status, headers, body = request("GET", "/files/machine_test.txt", dict(auth))
    check("Deleted file becomes 404", status == 404, str(status))

    print("\nResult:", PASSED, "passed,", FAILED, "failed")
    if FAILED == 0:
        print("All machine tests passed.")

if __name__ == "__main__":
    main()
