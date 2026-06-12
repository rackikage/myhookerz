"""
adb_bridge.py — ADB Phone Proxy Bridge
Connects Android phones via USB/ADB and uses each phone's cellular
data connection as an HTTP proxy carrier.

Architecture:
  Phone (Python micro proxy :8080 via Termux)
       ↕ adb forward tcp:210XX tcp:8080
  Host (localhost:210XX) ← used as SUTTTA/HTTP proxy

Each phone  →  1 proxy endpoint  →  Instagram sees real mobile carrier IP.
"""
import os
import re
import json
import time
import socket
import random
import string
import threading
import subprocess
import tempfile
from pathlib import Path
from queue import Queue

ADB = "adb"
PROXY_PORT_ON_PHONE = 8080
BASE_PORT = 21000

PROXY_PY_SOURCE = r'''import sys, os, json, socket, select, threading, urllib.parse, time

def handle(conn, addr):
    data = conn.recv(65536)
    if not data:
        conn.close()
        return
    try:
        first = data.split(b"\r\n")[0].decode("utf-8", errors="replace")
        parts = first.split()
        if len(parts) < 3:
            conn.close()
            return
        method, target, _ = parts
        if method == "CONNECT":
            host, port = target.split(":")
            port = int(port)
            s = socket.socket()
            s.connect((host, port))
            conn.sendall(b"HTTP/1.1 200 OK\r\n\r\n")
            sockets = [conn, s]
            while True:
                r, _, _ = select.select(sockets, [], [], 30)
                if not r:
                    break
                for sock in r:
                    other = s if sock is conn else conn
                    try:
                        d = sock.recv(65536)
                        if not d:
                            raise ConnectionError
                        other.sendall(d)
                    except:
                        return
        else:
            parsed = urllib.parse.urlparse(target)
            host = parsed.hostname
            port = parsed.port or 80
            path = parsed.path or "/"
            if parsed.query:
                path += "?" + parsed.query
            s = socket.socket()
            s.connect((host, port))
            req = f"{method} {path} HTTP/1.1\r\nHost: {host}\r\nConnection: close\r\n"
            for line in data.split(b"\r\n")[1:]:
                if line.strip() and not line.lower().startswith(b"host:"):
                    req += line.decode("utf-8", errors="replace") + "\r\n"
            req += "\r\n"
            s.sendall(req.encode())
            while True:
                d = s.recv(65536)
                if not d:
                    break
                conn.sendall(d)
    except Exception as e:
        try:
            conn.sendall(b"HTTP/1.1 502 Bad Gateway\r\n\r\n")
        except:
            pass
    finally:
        try:
            conn.close()
        except:
            pass

def main():
    port = int(sys.argv[1]) if len(sys.argv) > 1 else {PORT}
    s = socket.socket()
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(("127.0.0.1", port))
    s.listen(128)
    open("/data/local/tmp/.proxy_ready", "w").close()
    while True:
        conn, addr = s.accept()
        threading.Thread(target=handle, args=(conn, addr), daemon=True).start()

if __name__ == "__main__":
    main()
'''


class ADBPhone:
    def __init__(self, serial, model=None, local_port=None):
        self.serial = serial
        self.model = model or _get_model(serial)
        self.local_port = local_port
        self.proxy_url = f"http://localhost:{local_port}" if local_port else None
        self.online = True
        self.fail_count = 0
        self.battery = None
        self.operator = None
        self.ip_address = None

    def dict(self):
        return {
            'serial': self.serial,
            'model': self.model,
            'local_port': self.local_port,
            'proxy_url': self.proxy_url,
            'online': self.online,
            'fail_count': self.fail_count,
            'battery': self.battery,
            'operator': self.operator,
        }


def _get_model(serial):
    try:
        r = subprocess.run(
            [ADB, "-s", serial, "shell", "getprop", "ro.product.model"],
            capture_output=True, text=True, timeout=5,
        )
        return r.stdout.strip() or "unknown"
    except:
        return "unknown"


def _get_battery(serial):
    try:
        r = subprocess.run(
            [ADB, "-s", serial, "shell", "dumpsys", "battery"],
            capture_output=True, text=True, timeout=5,
        )
        m = re.search(r'level:\s*(\d+)', r.stdout)
        return int(m.group(1)) if m else None
    except:
        return None


def _get_operator(serial):
    try:
        r = subprocess.run(
            [ADB, "-s", serial, "shell", "getprop", "gsm.operator.alpha"],
            capture_output=True, text=True, timeout=5,
        )
        return r.stdout.strip() or None
    except:
        return None


def list_devices():
    """Return list of serials for connected devices."""
    try:
        r = subprocess.run([ADB, "devices"], capture_output=True, text=True, timeout=5)
        lines = r.stdout.strip().split("\n")[1:]
        return [
            line.split("\t")[0]
            for line in lines
            if line.strip() and "device" in line and "unauthorized" not in line
        ]
    except subprocess.TimeoutExpired:
        return []
    except:
        return []


def check_adb():
    try:
        r = subprocess.run([ADB, "version"], capture_output=True, text=True, timeout=5)
        return r.returncode == 0
    except:
        return False


def is_port_free(port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(("127.0.0.1", port)) != 0


def reserve_ports(count, start=BASE_PORT):
    ports = []
    p = start
    while len(ports) < count:
        if is_port_free(p):
            ports.append(p)
        p += 1
    return ports


class ADBBridge:
    """Manages a pool of Android phones as HTTP proxy carriers."""

    def __init__(self):
        self.phones = {}
        self._lock = threading.Lock()
        self._monitor = None
        self._running = False

    # ── Device Detection ────────────────────────────────────────

    def scan(self):
        serials = []
        try:
            serials = list_devices()
        except:
            return []
        with self._lock:
            existing = set(self.phones.keys())
            current = set(serials)

            for serial in current - existing:
                port = self._next_port()
                phone = ADBPhone(serial, local_port=port)
                self.phones[serial] = phone

            for serial in existing - current:
                if serial in self.phones:
                    self._teardown_forward(serial)
                    del self.phones[serial]

        return [s.dict() for s in self.phones.values()]

    def _next_port(self):
        used = {p.local_port for p in self.phones.values() if p.local_port}
        p = BASE_PORT
        while p in used or not is_port_free(p):
            p += 1
        return p

    # ── ADB Port Forwarding ─────────────────────────────────────

    def setup_forward(self, serial):
        phone = self.phones.get(serial)
        if not phone:
            return False
        port = phone.local_port
        r = subprocess.run(
            [ADB, "-s", serial, "forward", f"tcp:{port}", f"tcp:{PROXY_PORT_ON_PHONE}"],
            capture_output=True, text=True, timeout=10,
        )
        if r.returncode == 0:
            phone.proxy_url = f"http://localhost:{port}"
            phone.online = True
            self._update_phone_info(serial)
            return True
        return False

    def _teardown_forward(self, serial):
        subprocess.run(
            [ADB, "-s", serial, "forward", "--remove", f"tcp:{PROXY_PORT_ON_PHONE}"],
            capture_output=True, timeout=5,
        )

    def _update_phone_info(self, serial):
        phone = self.phones.get(serial)
        if not phone:
            return
        phone.battery = _get_battery(serial)
        phone.operator = _get_operator(serial)

    # ── Proxy Provisioning ──────────────────────────────────────

    def provision_phone(self, serial):
        """Push and start a tiny Python HTTP proxy on the phone via Termux."""
        phone = self.phones.get(serial)
        if not phone:
            return False
        port = phone.local_port or PROXY_PORT_ON_PHONE

        proxy_code = PROXY_PY_SOURCE.replace("{PORT}", str(PROXY_PORT_ON_PHONE))
        proxy_code = proxy_code.replace("threading.Thread", "threading.Thread")

        remote_path = "/data/local/tmp/igproxy.py"
        local_tmp = f"/tmp/igproxy_{serial}.py"
        with open(local_tmp, "w") as f:
            f.write(proxy_code)

        try:
            subprocess.run(
                [ADB, "-s", serial, "push", local_tmp, remote_path],
                capture_output=True, timeout=10,
            )
            subprocess.run(
                [ADB, "-s", serial, "shell", "chmod", "755", remote_path],
                capture_output=True, timeout=5,
            )
            subprocess.run(
                [ADB, "-s", serial, "shell",
                 f"nohup termux-exec python3 {remote_path} {PROXY_PORT_ON_PHONE} > /dev/null 2>&1 &"],
                capture_output=True, timeout=10,
            )
            time.sleep(2)
            os.remove(local_tmp)
            return self.setup_forward(serial)
        except Exception as e:
            print(f"    [ADB] Provision failed for {serial}: {e}")
            return False

    def provision_all(self):
        results = []
        with self._lock:
            for serial in list(self.phones.keys()):
                ok = self.provision_phone(serial)
                results.append({'serial': serial, 'success': ok})
        return results

    # ── Proxy Pool ──────────────────────────────────────────────

    def get_proxy_list(self):
        if not self._lock.acquire(timeout=2):
            return []
        try:
            return [
                p.proxy_url for p in self.phones.values()
                if p.online and p.proxy_url
            ]
        finally:
            self._lock.release()

    def get_phone_for_proxy(self, proxy_url):
        with self._lock:
            for p in self.phones.values():
                if p.proxy_url == proxy_url:
                    return p
        return None

    def mark_failed(self, proxy_url):
        p = self.get_phone_for_proxy(proxy_url)
        if p:
            p.fail_count += 1
            if p.fail_count >= 5:
                p.online = False

    def get_stats(self):
        if not self._lock.acquire(timeout=3):
            return {'total_phones': 0, 'online_phones': 0, 'proxies_active': 0, 'phones': []}
        try:
            total = len(self.phones)
            online = sum(1 for p in self.phones.values() if p.online)
            return {
                'total_phones': total,
                'online_phones': online,
                'proxies_active': len(self.get_proxy_list()),
                'phones': [p.dict() for p in self.phones.values()],
            }
        finally:
            self._lock.release()

    # ── Monitor ─────────────────────────────────────────────────

    def start_monitor(self, interval=15):
        if self._running:
            return
        self._running = True
        self._monitor = threading.Thread(
            target=self._monitor_loop, args=(interval,), daemon=True
        )
        self._monitor.start()

    def stop_monitor(self):
        self._running = False

    def _monitor_loop(self, interval):
        while self._running:
            try:
                self.scan()
            except:
                pass
            time.sleep(interval)
