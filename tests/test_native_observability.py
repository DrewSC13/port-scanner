from __future__ import annotations
import json, os, stat, textwrap
from pathlib import Path
import pytest
from src.bridge_rust import RustScannerBridge
from src.bridge_go import GoBannerBridge
from src.native_events import NativeEvent

def exe(tmp_path:Path,name:str,engine:str)->Path:
    source=f'''#!/usr/bin/env python3
import json,os,sys,time
r=json.load(sys.stdin);ports=sorted(set(r["ports"]));workers=min({512 if engine=="rust" else 32},{'r.get("workers",1)' if engine=="rust" else 'len(ports)'},len(ports));fd=os.environ.get("CICADAPORT_NATIVE_EVENT_FD");e=os.fdopen(os.dup(int(fd)),"w") if fd else None;seq=0;t=time.monotonic()
def emit(event,status,port,completed):
 global seq
 if not e:return
 seq+=1;e.write(json.dumps({{"contract_version":1,"record_type":"native_event","engine":"{engine}","phase":"{'tcp_scan' if engine=='rust' else 'banner_grab'}","event":event,"target":r["target"],"sequence":seq,"elapsed_ms":int((time.monotonic()-t)*1000),"port":port,"status":status,"completed":completed,"total":len(ports),"workers":workers}})+"\\n");e.flush()
emit("engine_started","running",None,0)
for n,p in enumerate(ports,1):
 out={{"contract_version":1,"record_type":"{'port_result' if engine=='rust' else 'banner_result'}","target":r["target"],"port":p}}
 if "{engine}"=="rust":out.update({{"address":r["target"],"address_family":"ipv4","host_state":"up","protocol":"tcp","state":"closed","reason":"connection_refused","technique":"tcp_connect","service":"","banner":None,"response_time":.001,"is_open":False,"evidence":{{"reason":"connection_refused","source":"rust","detail":"fake","errno":111}}}});status="closed"
 else:out.update({{"status":"empty","service":"Unknown","banner":None,"error":None,"source":"go"}});status="empty"
 print(json.dumps(out),flush=True);emit("port_completed",status,p,n)
emit("engine_completed","success",None,len(ports))
'''
    p=tmp_path/name;p.write_text(textwrap.dedent(source));p.chmod(p.stat().st_mode|stat.S_IXUSR);return p

def check(events,engine):
 assert [e["event"] for e in events]==["engine_started","port_completed","port_completed","engine_completed"]
 assert [e["sequence"] for e in events]==[1,2,3,4];assert all(e["engine"]==engine for e in events)

def test_strict_event_rejects_extra():
 p={"contract_version":1,"record_type":"native_event","engine":"rust","phase":"tcp_scan","event":"engine_started","target":"127.0.0.1","sequence":1,"elapsed_ms":0,"port":None,"status":"running","completed":0,"total":1,"workers":1,"extra":1}
 with pytest.raises(ValueError):NativeEvent.from_payload(p)

def test_rust_fake(tmp_path):
 events=[];results=RustScannerBridge(str(exe(tmp_path,"rust","rust"))).scan("127.0.0.1",[80,81],workers=2,event_callback=events.append);assert len(results)==2;check(events,"rust")

def test_go_fake(tmp_path):
 events=[];results=GoBannerBridge(str(exe(tmp_path,"go","go"))).grab_banners("127.0.0.1",[80,81],event_callback=events.append);assert len(results)==2;check(events,"go")

@pytest.mark.skipif(not os.getenv("CICADAPORT_TEST_RUST_BINARY"),reason="Rust real no configurado")
def test_real_rust():
 events=[];RustScannerBridge(os.environ["CICADAPORT_TEST_RUST_BINARY"]).scan("127.0.0.1",[9],timeout=.2,workers=1,event_callback=events.append);assert events[-1]["event"]=="engine_completed"
@pytest.mark.skipif(not os.getenv("CICADAPORT_TEST_GO_BINARY"),reason="Go real no configurado")
def test_real_go():
 events=[];GoBannerBridge(os.environ["CICADAPORT_TEST_GO_BINARY"]).grab_banners("127.0.0.1",[9],timeout=.2,event_callback=events.append);assert events[-1]["event"]=="engine_completed"
