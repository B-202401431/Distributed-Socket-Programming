#!/usr/bin/env python3
"""Shared experiment helpers. Network transfer itself is implemented in C."""
import concurrent.futures
import csv
import hashlib
import io
import os
from pathlib import Path
import platform
import socket
import subprocess
import time

ROOT = Path(__file__).resolve().parents[1]
STARTUP_FIX_VERSION = 'startup-wait-v1'
SERVER_STARTUP_TIMEOUT_DEFAULT = 600
CASES = ['Part1', 'Part2_Case1', 'Part2_Case2', 'Part2_Case2_Enhanced']
SUMMARY_FIELDS = ['case','mode','topic','probability','clients','connections_per_client','repeat',
 'status','successful_clients','useful_bytes','payload_sent','redundant_bytes','protocol_bytes',
 'total_application_bytes','makespan_s','goodput_MiB_s','payload_rate_MiB_s',
 'redundancy_percent','failures','attempts','sha256_verified','clock_uncertainty_s','run_id']

def build():
    for case in CASES:
        subprocess.run(['make','-C',str(ROOT/case)],check=True,capture_output=True,text=True)

def environment():
    identity=Path('/etc/machine-id')
    machine=identity.read_text().strip() if identity.exists() else socket.gethostname()
    return {'hostname':socket.gethostname(),'platform':platform.platform(),
            'machine_identity_sha256':hashlib.sha256(machine.encode()).hexdigest(),
            'python':platform.python_version(),'cpus':os.cpu_count(),
            'compiler':subprocess.check_output(['gcc','--version'],text=True).splitlines()[0]}

def sha256(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda:f.read(1024*1024),b''):h.update(block)
    return h.hexdigest()

def manifest(dataset,topic):
    source=Path(dataset).resolve()/topic
    if not source.is_dir():raise ValueError('Topic directory not found: '+str(source))
    files={p.name:{'size':p.stat().st_size,'sha256':sha256(p)}
           for p in sorted(source.iterdir()) if p.is_file() and not p.is_symlink()}
    return {'topic':topic,'files':files,'bytes':sum(v['size'] for v in files.values()),
            'blocks_64KiB':sum((v['size']+65535)//65536 for v in files.values())}

def check_files(directory,reference):
    directory=Path(directory)
    if not directory.is_dir():return False
    names={p.name for p in directory.iterdir() if p.is_file() and not p.is_symlink()}
    if names!=set(reference['files']):return False
    return all((directory/name).stat().st_size==v['size'] and
               sha256(directory/name)==v['sha256'] for name,v in reference['files'].items())

def free_port():
    with socket.socket() as s:s.bind(('127.0.0.1',0));return s.getsockname()[1]

def start_server(case,dataset,port,mode,probability,logdir):
    # The C server indexes EVERY topic before bind/listen. Large image trees on
    # /mnt/c can take much longer than the former 200 x 20 ms (~4 s) polling loop.
    try:
        startup_timeout=int(os.environ.get('FT_STARTUP_TIMEOUT',str(SERVER_STARTUP_TIMEOUT_DEFAULT)))
    except ValueError as exc:
        raise ValueError('FT_STARTUP_TIMEOUT must be an integer from 1 to 3600 seconds.') from exc
    if not 1<=startup_timeout<=3600:
        raise ValueError('FT_STARTUP_TIMEOUT must be an integer from 1 to 3600 seconds.')
    if not 1<=port<=65535:
        raise ValueError('Server port must be from 1 to 65535.')
    logdir=Path(logdir);logdir.mkdir(parents=True,exist_ok=True)
    error_path=logdir/'server.stderr.log'
    out=(logdir/'server.csv').open('w');err=error_path.open('w')
    command=[str(ROOT/case/'server'),str(port),str(Path(dataset).resolve()),
             mode if case=='Part1' else str(probability)]
    p=None
    def diagnostics():
        try:return error_path.read_text(errors='replace')
        except OSError:return ''
    try:
        # Catch a leftover manual server/probe before doing a long dataset scan.
        with socket.socket(socket.AF_INET,socket.SOCK_STREAM) as check:
            check.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1)
            try:check.bind(('0.0.0.0',port))
            except OSError as exc:
                raise RuntimeError(f'TCP port {port} is unavailable: {exc}. Stop the old manual server or network_check.py serve before starting the coordinator.') from exc
        p=subprocess.Popen(command,stdout=out,stderr=err,text=True)
        started=time.monotonic();deadline=started+startup_timeout;next_notice=started+10
        print(f'[SERVER START] {case}: indexing dataset; startup limit {startup_timeout}s.',flush=True)
        while True:
            status=p.poll();log=diagnostics()
            if status is not None:
                raise RuntimeError(f'{case} server exited with code {status}; read {error_path}.\n{log[-2000:].strip()}')
            remaining=deadline-time.monotonic()
            if remaining<=0:
                raise RuntimeError(f'Server readiness timeout after {startup_timeout}s while starting {case}. Dataset: {Path(dataset).resolve()}. Read {error_path}; check the scan/disk and FT_STARTUP_TIMEOUT.\n{log[-2000:].strip()}')
            # Only the child we launched can satisfy this marker. A connection
            # to an unrelated listener must not be mistaken for readiness.
            if any(line.startswith('Ready:') for line in log.splitlines()):
                try:
                    with socket.create_connection(('127.0.0.1',port),timeout=min(.2,remaining)):pass
                except OSError:pass
                else:
                    if p.poll() is None:
                        print(f'[SERVER READY] {case} on port {port}, startup {time.monotonic()-started:.1f}s.',flush=True)
                        break
            now=time.monotonic()
            if now>=next_notice:
                print(f'[SERVER WAIT] {case}: indexing/starting, {now-started:.0f}s elapsed; limit {startup_timeout}s. Log: {error_path}',flush=True)
                next_notice=now+10
            time.sleep(min(.1,max(0,deadline-time.monotonic())))
    except BaseException:
        if p is not None:stop_server((p,out,err))
        else:out.close();err.close()
        raise
    return p,out,err

def stop_server(handle):
    p,out,err=handle
    p.terminate()
    try:p.wait(timeout=5)
    except subprocess.TimeoutExpired:p.kill();p.wait()
    out.close();err.close()

def write_csv(path,rows,fields=None):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    if fields is None:fields=list(dict.fromkeys(k for row in rows for k in row))
    with path.open('w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(rows)

def run_clients(case,ip,port,reference,count,logdir,output,start_at=0,clock_offset=0,
                uncertainty=0,lanes=2,timeout=600,max_attempts=1000,node='local'):
    logdir=Path(logdir);logdir.mkdir(parents=True,exist_ok=True)
    output=Path(output)
    if output.exists():raise ValueError('Use a fresh output path: '+str(output))
    output.mkdir(parents=True)
    def one(i):
        delay=start_at-(time.time()+clock_offset)
        if delay>0:time.sleep(delay)
        command=[str(ROOT/case/'client'),ip,str(port),reference['topic'],str(output/str(i))]
        if case=='Part2_Case2_Enhanced':command.append(str(lanes))
        start=time.time()+clock_offset;mono=time.monotonic();code=-1;error=''
        stdout_path=logdir/f'client_{i}.csv';stderr_path=logdir/f'client_{i}.stderr.log'
        with stdout_path.open('w') as out,stderr_path.open('w') as err:
            try:
                code=subprocess.run(command,stdout=out,stderr=err,
                    env={**os.environ,'FT_MAX_ATTEMPTS':str(max_attempts)},timeout=timeout).returncode
            except subprocess.TimeoutExpired:error='client_timeout'
            except OSError as e:error=str(e)
        end=start+time.monotonic()-mono
        try:
            rows=list(csv.DictReader(stdout_path.open()))
            row=rows[-1] if rows else {}
        except (OSError,csv.Error):row={}
        verified=code==0 and row.get('success')=='1' and check_files(output/str(i)/reference['topic'],reference)
        if code==0 and not verified:error='output_hash_or_protocol_failure'
        row.update(node=node,client_number=i,start_epoch=start,end_epoch=end,
                   returncode=code,sha256_verified=int(verified),error=error,
                   clock_uncertainty_s=uncertainty,success=int(verified))
        row.setdefault('session','');row.setdefault('attempts',0)
        row.setdefault('useful_bytes',0);row.setdefault('connections',lanes if case==CASES[-1] else 1)
        if not verified:row['useful_bytes']=0
        return row
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1,count)) as pool:
        rows=list(pool.map(one,range(count)))
    write_csv(logdir/'clients.csv',rows,fields=None if rows else ['node','success'])
    return rows

def summarize(spec,clients,server_log):
    with Path(server_log).open() as f:server=list(csv.DictReader(f))
    success=len(clients)==spec['clients'] and all(str(r['success'])=='1' for r in clients)
    useful=sum(int(r.get('useful_bytes',0)) for r in clients)
    sent=sum(int(r['payload_sent']) for r in server)
    wire=sum(int(r['app_bytes_sent'])+int(r['app_bytes_received']) for r in server)
    seconds=max((float(r['end_epoch']) for r in clients),default=0)-min((float(r['start_epoch']) for r in clients),default=0)
    if success and (seconds<=0 or sent<useful):raise ValueError('Incomplete logs or invalid time/bytes')
    if seconds<=0:seconds=1e-9
    return dict(case=spec['case'],mode=spec['mode'],topic=spec['topic'],probability=spec['probability'],
        clients=spec['clients'],connections_per_client=spec.get('lanes',2) if spec['case']==CASES[-1] else 1,
        repeat=spec['repeat'],status='SUCCESS' if success else 'FAILED',
        successful_clients=sum(str(r['success'])=='1' for r in clients),useful_bytes=useful,
        payload_sent=sent,redundant_bytes=sent-useful if success else '',protocol_bytes=wire-sent,
        total_application_bytes=wire,makespan_s=seconds,goodput_MiB_s=useful/1048576/seconds,
        payload_rate_MiB_s=sent/1048576/seconds,
        redundancy_percent=100*(sent-useful)/useful if success and useful else '',
        failures=sum(int(r['injected']) for r in server),attempts=sum(int(r.get('attempts',0)) for r in clients),
        sha256_verified=int(success),clock_uncertainty_s=max((float(r.get('clock_uncertainty_s',0)) for r in clients),default=0),
        run_id=spec['run_id'])

def schedule(topic,probabilities,repeats=3,lanes=2):
    settings=[('Part1',m,0,n) for m in ['single','multi'] for n in [2]]
    settings += [(c,'multi',p,4) for c in CASES[1:] for p in probabilities]
    jobs=[]
    for case,mode,p,n in settings:
        for repeat in range(1,repeats+1):
            jobs.append(dict(case=case,mode=mode,probability=p,clients=n,repeat=repeat,
                topic=topic,lanes=lanes,run_id=f'{case}_{mode}_p{p:g}_n{n}_r{repeat}'))
    return jobs
