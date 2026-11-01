#!/usr/bin/env python3
"""Three-PC lab runner. PC A coordinates C binaries on PCs B and C over HTTP.
Use only on the group's trusted lab LAN. No SSH account or third-party service.
"""
import argparse
import http.client
import ipaddress
import uuid
import base64
import io
import json
import socket
from pathlib import Path
import threading
import time
import urllib.request
import urllib.error
import zipfile
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from experiment import (ROOT,CASES,SUMMARY_FIELDS,build,environment,manifest,run_clients,
                        start_server,stop_server,summarize,schedule,write_csv)

# Explicitly bypass system HTTP proxies for private lab control traffic.
DIRECT = urllib.request.build_opener(urllib.request.ProxyHandler({}))
def request(url,path,data=None):
    body=None if data is None else json.dumps(data).encode()
    req=urllib.request.Request(url.rstrip('/')+path,data=body,
            headers={'Content-Type':'application/json'})
    for attempt in range(4):
        try:
            with DIRECT.open(req,timeout=30) as response:return json.load(response)
        except urllib.error.HTTPError:
            raise
        except (OSError,urllib.error.URLError):
            if attempt==3:raise
            time.sleep(.5*(attempt+1))


def coordinator(a):
    if a.ip.startswith('127.') and not a.rehearsal:
        raise SystemExit('Use PC A LAN IPv4 address. --rehearsal permits one-PC checks.')
    try:
        address=ipaddress.IPv4Address(a.ip)
        if address.is_unspecified or address.is_multicast:
            raise ValueError('Use PC A reachable Wi-Fi IPv4, not 0.0.0.0.')
    except ipaddress.AddressValueError as exc:
        raise ValueError('Invalid --ip: use PC A numeric Wi-Fi IPv4.') from exc
    print('[BUILD] Checking all four C programs...',flush=True)
    build();results=Path(a.results).resolve()
    if results.exists() and any(results.iterdir()):
        raise SystemExit('Use a NEW results directory so earlier logs are preserved.')
    results.mkdir(parents=True,exist_ok=True)
    reference=manifest(a.dataset,a.topic)
    if not reference['bytes']:raise SystemExit('Use a non-empty topic for performance tests.')
    k=max(10,reference['blocks_64KiB'])
    probabilities=a.probabilities if a.probabilities is not None else [0,.1/k,.5/k,1/k]
    if any(p<0 or p>=1 for p in probabilities):raise SystemExit('Use failure rates in [0,1).')
    jobs=schedule(a.topic,probabilities,a.repeats,a.lanes)
    if a.only:jobs=[j for j in jobs if j['case'] in a.only]
    (results/'source_manifest.json').write_text(json.dumps(reference,indent=2))
    (results/'schedule.json').write_text(json.dumps(jobs,indent=2))
    state={'nodes':{},'job':None,'received':{},'done':False,'error':''}
    lock=threading.Lock()
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def reply(self,data,status=200):
            body=json.dumps(data).encode();self.send_response(status)
            self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(body)))
            self.end_headers();self.wfile.write(body)
        def do_GET(self):
            if self.path=='/health':
                self.reply({'ok':True,'data_port':a.port,'data_ip':a.ip,'nodes':list(state['nodes'])});return
            if self.path=='/clock':self.reply({'epoch':time.time()});return
            if self.path=='/manifest':self.reply(reference);return
            if self.path.startswith('/job/'):
                node=self.path.rsplit('/',1)[-1]
                if node not in ['B','C']:self.reply({'error':'Use node B or C'},400);return
                with lock:
                    self.reply({'job':state['job'],'done':state['done'],'error':state['error']})
                return
            self.reply({'error':'unknown endpoint'},404)
        def do_POST(self):
            size=int(self.headers.get('Content-Length','0'))
            if size<=0 or size>32*1024*1024:self.reply({'error':'invalid size'},400);return
            try:payload=json.loads(self.rfile.read(size))
            except (ValueError,UnicodeError):self.reply({'error':'invalid JSON'},400);return
            node=payload.get('node')
            if node not in ['B','C']:self.reply({'error':'Use node B or C'},400);return
            with lock:
                if self.path=='/register':
                    if node in state['nodes'] and state['nodes'][node].get('registration_token') != payload['environment'].get('registration_token'):
                        self.reply({'error':'Node '+node+' is already registered. Use B on PC B and C on PC C; restart A for a fresh run.'},409);return
                    state['nodes'][node]={'peer_ip':self.client_address[0],**payload['environment']}
                    print('[CONNECTED] Node '+node+' registered from '+self.client_address[0],flush=True)
                elif self.path=='/result':
                    if state['job'] and payload.get('run_id')==state['job']['run_id']:
                        state['received'][node]=payload
                else:self.reply({'error':'unknown endpoint'},404);return
            self.reply({'ok':True})
    http=ThreadingHTTPServer((a.bind,a.control_port),Handler)
    thread=threading.Thread(target=http.serve_forever,daemon=True);thread.start()
    metadata={'server':environment(),'server_ip':a.ip,'topic':a.topic,
        'dataset_root':str(Path(a.dataset).resolve()),'transport':'ONE-PC REHEARSAL' if a.rehearsal else 'THREE-PC LAN',
        'real_three_pc':False,'repeats':a.repeats,'probabilities':probabilities,
        'network_note':a.network_note,
        'started_utc':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),'nodes':{}}
    rows=[];preflight=None
    try:
        # Keep the actual C listener reachable while the agents join.
        preflight=start_server('Part1',a.dataset,a.port,'multi',0,results/'preflight')
        print(f'PC A ready. On B and C: python3 Tools/lan.py agent --server http://{a.ip}:{a.control_port} --node B',flush=True)
        print('Use --node C on PC C. Waiting for both nodes.',flush=True)
        deadline=time.monotonic()+a.join_timeout;next_notice=0
        while True:
            with lock:ready=len(state['nodes'])==2
            if ready:break
            if time.monotonic()>=next_notice:
                with lock:missing=[n for n in ['B','C'] if n not in state['nodes']]
                print('[WAITING] Missing node(s): '+', '.join(missing),flush=True)
                next_notice=time.monotonic()+10
            if time.monotonic()>deadline:raise TimeoutError('Both client PCs did not register. Check both ports and unique --node B / --node C.')
            time.sleep(.2)
        print('[READY] Both B and C registered. Starting file-transfer checks.',flush=True)
        stop_server(preflight);preflight=None
        with lock:metadata['nodes']=dict(state['nodes'])
        peers={v['peer_ip'] for v in metadata['nodes'].values()}
        distinct=len(peers)==2 and all(not p.startswith('127.') and p!=a.ip for p in peers)
        identities={metadata['server']['machine_identity_sha256'],
                    *(n.get('machine_identity_sha256','') for n in metadata['nodes'].values())}
        separate_systems=len(identities)==3 and '' not in identities
        # Windows port forwarding can give B and C the same observed proxy IP.
        # Preserve both IP and system-identity evidence in the environment log.
        if not (distinct or separate_systems) and not a.rehearsal:
            raise RuntimeError('Use three separate PCs. --rehearsal is only for local checks.')
        metadata['real_three_pc']=bool((distinct or separate_systems) and not a.rehearsal)
        (results/'environment.json').write_text(json.dumps(metadata,indent=2))
        for index,spec in enumerate(jobs,1):
            logdir=results/'raw'/spec['run_id'];logdir.mkdir(parents=True)
            handle=start_server(spec['case'],a.dataset,a.port,spec['mode'],spec['probability'],logdir)
            try:
                job={**spec,'ip':a.ip,'port':a.port,'start_at':time.time()+a.start_delay,
                     'timeout':a.timeout,'max_attempts':a.max_attempts}
                with lock:state['received']={};state['job']=job
                deadline=time.monotonic()+a.timeout+90
                while True:
                    with lock:received=dict(state['received'])
                    if len(received)==2:break
                    if time.monotonic()>deadline:raise TimeoutError('Client agent did not return a batch result.')
                    time.sleep(.1)
                time.sleep(.15)  # Final BYE handling and server CSV flush, outside transfer timer.
            finally:
                with lock:state['job']=None
                stop_server(handle)
            clients=[]
            for node in ['B','C']:
                payload=received[node];clients.extend(payload['clients'])
                write_csv(logdir/f'{node}_clients.csv',payload['clients'],
                          fields=None if payload['clients'] else ['node','success'])
                (logdir/f'{node}_logs.zip').write_bytes(base64.b64decode(payload['logs_zip']))
            row=summarize(spec,clients,logdir/'server.csv');rows.append(row)
            write_csv(results/'summary.csv',rows,SUMMARY_FIELDS)
            print(f"[{index}/{len(jobs)}] {spec['run_id']}: {row['status']}, {row['goodput_MiB_s']:.2f} MiB/s, {row['failures']} faults",flush=True)
        metadata['completed_utc']=time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime())
        (results/'environment.json').write_text(json.dumps(metadata,indent=2))
        print('Measurements saved to '+str(results),flush=True)
        print('Next: edit team_members.csv, then python3 Tools/finalize.py --lan '+str(results),flush=True)
    except BaseException as exc:
        with lock:state['error']=str(exc)
        (results/'runner_error.txt').write_text(str(exc)+'\n')
        raise
    finally:
        if preflight is not None:stop_server(preflight)
        with lock:state['done']=True
        time.sleep(1);http.shutdown();http.server_close()

def agent(a):
    print('[BUILD] Checking all four C programs...',flush=True)
    build()
    print('[CONTROL] Connecting to '+a.server,flush=True)
    try:
        health=request(a.server,'/health')
        if not health.get('ok') or 'data_ip' not in health or 'data_port' not in health:
            raise ValueError('Wrong service on control port. Stop diagnostic listeners and old servers.')
        print('[CONTROL OK] Coordinator reached.',flush=True)
        print('[DATA] Checking '+str(health['data_ip'])+':'+str(health['data_port']),flush=True)
        for attempt in range(10):
            try:
                with socket.create_connection((health['data_ip'],health['data_port']),timeout=5):pass
                break
            except OSError:
                if attempt==9:raise
                time.sleep(.5)
        ref=request(a.server,'/manifest')
    except (OSError,urllib.error.URLError,http.client.HTTPException,ValueError) as exc:
        raise SystemExit('Cannot reach PC A on BOTH control and data ports. '
            'Run Tools/network_check.py check --server-ip <PC_A_WINDOWS_IP>. '
            'See WIFI_WSL_GUIDE.md. Detail: '+str(exc))
    print('[DATA OK] Transfer port reached.',flush=True)
    env=environment();env['registration_token']=uuid.uuid4().hex
    request(a.server,'/register',{'node':a.node,'environment':env})
    print('[REGISTERED] Node '+a.node+' accepted by A. Waiting for both nodes / next batch.',flush=True)
    local=Path(a.results).resolve();local.mkdir(parents=True,exist_ok=True)
    downloads=Path(a.output).resolve();last=None
    def clock():
        samples=[]
        for _ in range(3):
            before=time.time();epoch=request(a.server,'/clock')['epoch'];after=time.time()
            samples.append((after-before,epoch-(before+after)/2))
        rtt,offset=min(samples);return offset,rtt/2
    while True:
        info=request(a.server,'/job/'+a.node)
        if info['done']:
            print('Coordinator finished. '+(info.get('error') or ''),flush=True);return
        job=info['job']
        if not job or job['run_id']==last:time.sleep(.2);continue
        if job['case'] not in CASES:raise ValueError('Unknown case')
        count=(job['clients']+1)//2 if a.node=='B' else job['clients']//2
        print('[BATCH] '+job['run_id']+'; local clients='+str(count),flush=True)
        offset,uncertainty=clock();folder=local/job['run_id']
        rows=run_clients(job['case'],job['ip'],job['port'],ref,count,folder,
            downloads/job['run_id'],start_at=job['start_at'],clock_offset=offset,
            uncertainty=uncertainty,lanes=job['lanes'],timeout=job['timeout'],
            max_attempts=job['max_attempts'],node=a.node)
        b=io.BytesIO()
        with zipfile.ZipFile(b,'w',zipfile.ZIP_DEFLATED) as z:
            for p in folder.iterdir():
                if p.is_file():z.write(p,p.name)
        payload={'node':a.node,'run_id':job['run_id'],'clients':rows,
                 'logs_zip':base64.b64encode(b.getvalue()).decode()}
        request(a.server,'/result',payload);last=job['run_id']
        print(f"{last}: {sum(str(r['success'])=='1' for r in rows)}/{count} clients verified",flush=True)

def main():
    p=argparse.ArgumentParser(description=__doc__);sub=p.add_subparsers(dest='command',required=True)
    s=sub.add_parser('server');s.add_argument('--dataset',required=True,type=Path)
    s.add_argument('--ip',required=True);s.add_argument('--topic',default='cane')
    s.add_argument('--bind',default='0.0.0.0');s.add_argument('--port',type=int,default=9000)
    s.add_argument('--control-port',type=int,default=9101);s.add_argument('--results',default='Results/lan')
    s.add_argument('--repeats',type=int,default=3);s.add_argument('--lanes',type=int,default=2)
    s.add_argument('--probabilities',type=float,nargs='+');s.add_argument('--timeout',type=int,default=1800)
    s.add_argument('--network-note',default='Not specified; record hotspot/router and WSL mode')
    s.add_argument('--max-attempts',type=int,default=1000);s.add_argument('--join-timeout',type=int,default=600)
    s.add_argument('--start-delay',type=float,default=5);s.add_argument('--rehearsal',action='store_true')
    s.add_argument('--only',choices=CASES,nargs='+')
    c=sub.add_parser('agent');c.add_argument('--server',required=True);c.add_argument('--node',choices=['B','C'],required=True)
    c.add_argument('--results',default='Results/client_node');c.add_argument('--output',default='downloads')
    q=sub.add_parser('status');q.add_argument('--server',required=True)
    a=p.parse_args()
    if a.command=='status':
        health=request(a.server,'/health')
        print(json.dumps(health,indent=2));return
    if a.command=='server':
        if a.repeats<1 or not 1<=a.lanes<=16:raise SystemExit('Invalid repeats or lane count')
        coordinator(a)
    else:agent(a)
if __name__=='__main__':
    try:main()
    except KeyboardInterrupt:
        raise SystemExit('Stopped by user. Use fresh result/output folders for the next run.')
    except Exception as exc:
        if hasattr(exc,'stderr') and exc.stderr:print(str(exc.stderr),flush=True)
        raise SystemExit('ERROR: '+str(exc))
