"""Canal interno estricto para eventos de motores nativos."""
from __future__ import annotations
from dataclasses import dataclass
import json
import os
import threading
from typing import Callable, Iterable, Mapping, Optional

NATIVE_EVENT_FD_ENV = "CICADAPORT_NATIVE_EVENT_FD"
NativeEventCallback = Callable[[dict[str, object]], None]
FIELDS = frozenset({"contract_version","record_type","engine","phase","event","target","sequence","elapsed_ms","port","status","completed","total","workers"})
PHASES = {"rust":"tcp_scan","go":"banner_grab"}

@dataclass(frozen=True)
class NativeEvent:
    contract_version:int; record_type:str; engine:str; phase:str; event:str
    target:str; sequence:int; elapsed_ms:int; port:Optional[int]; status:str
    completed:int; total:int; workers:int

    @classmethod
    def from_payload(cls, payload: object) -> "NativeEvent":
        if not isinstance(payload, Mapping): raise ValueError("native_event debe ser objeto")
        missing=FIELDS-set(payload); extra=set(payload)-FIELDS
        if missing: raise ValueError("native_event incompleto: "+", ".join(sorted(missing)))
        if extra: raise ValueError("native_event contiene campos no admitidos: "+", ".join(sorted(extra)))
        event=cls(**dict(payload)); event.validate(); return event

    def validate(self) -> None:
        if self.contract_version!=1 or self.record_type!="native_event": raise ValueError("contrato native_event incompatible")
        if self.engine not in PHASES or self.phase!=PHASES[self.engine]: raise ValueError("motor/fase native_event incompatible")
        if self.event not in {"engine_started","port_completed","engine_completed"}: raise ValueError("evento incompatible")
        for name in ("sequence","elapsed_ms","completed","total","workers"):
            value=getattr(self,name)
            if isinstance(value,bool) or not isinstance(value,int): raise ValueError(f"{name} debe ser entero")
        if self.sequence<1 or self.elapsed_ms<0 or self.total<1: raise ValueError("contadores native_event inválidos")
        if not 1<=self.workers<=self.total or not 0<=self.completed<=self.total: raise ValueError("presupuesto native_event inválido")
        if self.port is not None and (isinstance(self.port,bool) or not isinstance(self.port,int) or not 1<=self.port<=65535): raise ValueError("port inválido")

    def to_payload(self) -> dict[str,object]:
        return {name:getattr(self,name) for name in FIELDS}

class NativeEventStream:
    def __init__(self, *, callback:NativeEventCallback, engine:str, target:str, ports:Iterable[int], workers:int) -> None:
        ports=tuple(sorted(set(ports)))
        if engine not in PHASES or not ports: raise ValueError("stream native_event inválido")
        self.callback=callback; self.engine=engine; self.phase=PHASES[engine]; self.target=target
        self.ports=ports; self.workers=min(max(1,workers),len(ports))
        self._read_fd=None; self._write_fd=None; self._thread=None; self._error=None
        self._events=[]; self._completed=set(); self._finished=False

    def start(self) -> None:
        self._read_fd,self._write_fd=os.pipe(); os.set_inheritable(self._write_fd,True)
        self._thread=threading.Thread(target=self._read,name=f"cicadaport-{self.engine}-events",daemon=True); self._thread.start()

    def popen_kwargs(self) -> dict[str,object]:
        if self._write_fd is None: raise RuntimeError("stream no iniciado")
        env=os.environ.copy(); env[NATIVE_EVENT_FD_ENV]=str(self._write_fd)
        return {"env":env,"pass_fds":(self._write_fd,)}

    def parent_after_spawn(self) -> None:
        if self._write_fd is not None: os.close(self._write_fd); self._write_fd=None

    def _read(self) -> None:
        try:
            assert self._read_fd is not None
            with os.fdopen(self._read_fd,'r',encoding='utf-8',newline='\n') as stream:
                self._read_fd=None
                for raw in stream:
                    if not raw.rstrip('\n'): raise ValueError("línea native_event vacía")
                    event=NativeEvent.from_payload(json.loads(raw)); self._accept(event); self.callback(event.to_payload())
        except BaseException as error: self._error=error

    def _accept(self,event:NativeEvent) -> None:
        if event.sequence!=len(self._events)+1: raise ValueError("sequence no monotónica")
        if (event.engine,event.phase,event.target)!=(self.engine,self.phase,self.target): raise ValueError("correlación native_event inválida")
        if event.total!=len(self.ports) or event.workers!=self.workers: raise ValueError("presupuesto native_event no coincide")
        if not self._events:
            if (event.event,event.port,event.status,event.completed)!=("engine_started",None,"running",0): raise ValueError("inicio native_event inválido")
        elif event.event=="port_completed":
            if event.port not in self.ports or event.port in self._completed: raise ValueError("puerto native_event inválido o duplicado")
            if event.completed!=len(self._completed)+1: raise ValueError("completed no monotónico")
            self._completed.add(event.port)
        elif event.event=="engine_completed":
            if event.port is not None or event.status!="success" or event.completed!=len(self.ports) or self._completed!=set(self.ports): raise ValueError("fin native_event inválido")
        else: raise ValueError("evento intermedio inválido")
        if self._events and self._events[-1].event=="engine_completed": raise ValueError("evento posterior al cierre")
        self._events.append(event)

    def finish(self) -> list[dict[str,object]]:
        if self._finished: return [e.to_payload() for e in self._events]
        self.parent_after_spawn(); assert self._thread is not None; self._thread.join(timeout=5)
        if self._thread.is_alive(): raise RuntimeError("canal native_event no finalizó")
        if self._error is not None: raise RuntimeError(f"canal native_event inválido: {self._error}") from self._error
        if len(self._events)!=len(self.ports)+2 or self._events[-1].event!="engine_completed": raise RuntimeError("canal native_event incompleto")
        self._finished=True; return [e.to_payload() for e in self._events]

    def abort(self) -> None:
        self.parent_after_spawn()
        if self._thread is not None: self._thread.join(timeout=2)
