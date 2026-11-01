#!/usr/bin/env python3
"""Run with Python on Windows OR WSL. No gcc or external packages needed.
serve: temporary listeners, stop with Ctrl+C before running the real coordinator.
check: test both TCP ports from each client PC.
"""
import argparse
import socket
import socketserver
import threading
import time

class Probe(socketserver.BaseRequestHandler):
    def handle(self):
        self.request.sendall(b'IT305 connectivity probe\n')

class Server(socketserver.ThreadingTCPServer):
    allow_reuse_address=True
    daemon_threads=True

def check(ip,ports,timeout=5):
    passed=True
    for port in ports:
        before=time.monotonic()
        try:
            with socket.create_connection((ip,port),timeout=timeout):pass
            print(f'PASS TCP {ip}:{port} ({time.monotonic()-before:.3f}s)')
        except OSError as exc:
            passed=False
            print(f'FAIL TCP {ip}:{port}: {exc}')
    return passed

def main():
    p=argparse.ArgumentParser(description=__doc__)
    sub=p.add_subparsers(dest='command',required=True)
    s=sub.add_parser('serve');s.add_argument('--bind',default='0.0.0.0')
    c=sub.add_parser('check');c.add_argument('--server-ip',required=True)
    for parser in (s,c):parser.add_argument('--ports',type=int,nargs='+',default=[9000,9101])
    a=p.parse_args()
    if any(not 1<=port<=65535 for port in a.ports):p.error('Ports must be 1..65535')
    if a.command=='check':
        if not check(a.server_ip,a.ports):
            print('Test PC A locally first. If local passes and B/C fail, inspect Windows forwarding, '
                  'firewall and hotspot device isolation. See WIFI_WSL_GUIDE.md.')
            raise SystemExit(1)
        return
    servers=[]
    try:
        for port in a.ports:
            server=Server((a.bind,port),Probe);servers.append(server)
            threading.Thread(target=server.serve_forever,daemon=True).start()
        print('Diagnostic listeners ready on '+', '.join(str(x) for x in a.ports),flush=True)
        print('Run check from B and C. Ctrl+C here BEFORE starting Tools/lan.py.',flush=True)
        threading.Event().wait()
    except KeyboardInterrupt:pass
    finally:
        for server in servers:server.shutdown();server.server_close()
if __name__=='__main__':main()
