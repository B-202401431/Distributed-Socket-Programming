#!/usr/bin/env python3
"""Local startup regressions with synthetic data. Optional --baseline helper."""
import argparse,csv,importlib.util,os,socket,subprocess,sys,tempfile,time
from pathlib import Path
from unittest.mock import patch
import experiment as exp

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--baseline',type=Path);args=parser.parse_args()
    real_root=exp.ROOT;exp.build();actual_server=real_root/'Part1/server';actual_client=real_root/'Part1/client'
    with tempfile.TemporaryDirectory() as td:
        temp=Path(td);data=temp/'data';data.mkdir()
        counts=[4863,2623,1446,2112,3098,1668,1866,1820,4821,1862]
        names=['cane','cavallo','elefante','farfalla','gallina','gatto','mucca','pecora','ragno','scoiattolo']
        size,extra=divmod(600*1024*1024,sum(counts));index=0
        for name,count in zip(names,counts):
            folder=data/name;folder.mkdir()
            for i in range(count):
                with (folder/f'{i:05d}.bin').open('wb') as f:f.truncate(size+(index<extra))
                index+=1
        print('Fixture: 26,179 synthetic files; 600 MiB logical size (sparse).',flush=True)
        fake_root=temp/'wrapped';(fake_root/'Part1').mkdir(parents=True);wrapper=fake_root/'Part1/server'
        def executable(body):
            wrapper.write_text('#!'+sys.executable+'\n'+body);wrapper.chmod(0o755)
        executable(f'import os,sys,time\ntime.sleep(6)\nos.execv({str(actual_server)!r}, [{str(actual_server)!r}]+sys.argv[1:])\n')
        if args.baseline:
            spec=importlib.util.spec_from_file_location('baseline_experiment',args.baseline.resolve())
            old=importlib.util.module_from_spec(spec);spec.loader.exec_module(old);old.ROOT=fake_root;start=time.monotonic()
            try:handle=old.start_server('Part1',data,exp.free_port(),'multi',0,temp/'old')
            except RuntimeError as exc:
                assert 'readiness timeout' in str(exc),str(exc)
                print(f'REPRODUCED: old helper times out at {time.monotonic()-start:.2f}s before delayed server starts.',flush=True)
            else:old.stop_server(handle);raise AssertionError('Expected baseline timeout')
        with patch.object(exp,'ROOT',fake_root),patch.dict(os.environ,{'FT_STARTUP_TIMEOUT':'30'}):
            port=exp.free_port();start=time.monotonic();handle=exp.start_server('Part1',data,port,'multi',0,temp/'new')
            try:
                assert time.monotonic()-start>=6
                result=subprocess.run([str(actual_client),'127.0.0.1',str(port),'cane',str(temp/'out')],capture_output=True,text=True,timeout=90)
                assert result.returncode==0,result.stderr
                assert exp.check_files(temp/'out/cane',exp.manifest(data,'cane'))
                print('PASS: delayed real C server starts with full synthetic tree; cane transfer matches all SHA-256 hashes.',flush=True)
            finally:exp.stop_server(handle)
            executable("import sys\nprint('startup fixture: invalid source',file=sys.stderr)\nsys.exit(7)\n")
            start=time.monotonic()
            try:exp.start_server('Part1',data,exp.free_port(),'multi',0,temp/'exit')
            except RuntimeError as exc:
                assert 'code 7' in str(exc) and 'startup fixture: invalid source' in str(exc)
                assert time.monotonic()-start<5
            else:raise AssertionError('Exit was not detected')
            print('PASS: early process failure reports exit code and stderr promptly.',flush=True)
            pidfile=temp/'hung.pid'
            executable(f'import os,time\nfrom pathlib import Path\nPath({str(pidfile)!r}).write_text(str(os.getpid()))\ntime.sleep(60)\n')
            with patch.dict(os.environ,{'FT_STARTUP_TIMEOUT':'1'}):
                start=time.monotonic()
                try:exp.start_server('Part1',data,exp.free_port(),'multi',0,temp/'timeout')
                except RuntimeError as exc:
                    assert 'timeout after 1s' in str(exc),str(exc)
                    assert time.monotonic()-start<5
                else:raise AssertionError('Hung process was not timed out')
            try:os.kill(int(pidfile.read_text()),0)
            except ProcessLookupError:pass
            else:raise AssertionError('Timed-out child remains alive')
            print('PASS: bounded timeout cleans up the child process.',flush=True)
            with socket.socket() as occupied:
                occupied.bind(('0.0.0.0',0));occupied.listen()
                try:exp.start_server('Part1',data,occupied.getsockname()[1],'multi',0,temp/'occupied')
                except RuntimeError as exc:assert 'port' in str(exc) and 'unavailable' in str(exc)
                else:raise AssertionError('Unrelated listener accepted as readiness')
            print('PASS: occupied port is rejected instead of giving false readiness.',flush=True)
            for value in ('0','-1','abc','3601'):
                with patch.dict(os.environ,{'FT_STARTUP_TIMEOUT':value}):
                    try:exp.start_server('Part1',data,exp.free_port(),'multi',0,temp/'invalid')
                    except ValueError:pass
                    else:raise AssertionError('Invalid timeout accepted: '+value)
            print('PASS: invalid startup timeouts are rejected.',flush=True)
    print('STARTUP REGRESSIONS PASSED. Linux local tests, not Windows/hotspot measurements.',flush=True)
if __name__=='__main__':main()
