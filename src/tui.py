"""Dashboard TUI de CicadaPort construido sobre Textual."""

from __future__ import annotations

from collections import deque
from datetime import datetime
import time
from typing import Deque, Optional, Set

from rich.markup import escape
from textual import work
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.message import Message
from textual.widgets import RichLog, Static
from textual.worker import Worker

from config import config
from src.contracts import PortState
from src.errors import ScanCancelledError
from src.events import ScanEvent, ScanEventType
from src.network import NetworkUtils
from src.orchestrator import (
    DISABLED_BANNER_ENGINE,
    MANDATORY_BANNER_ENGINE,
    MANDATORY_SCAN_ENGINE,
    ScanBatchOutcome,
    ScanBatchRequest,
    ScanOrchestrator,
    ScanOutcome,
    ScanRequest,
)
from src.scanner import ScanResult


TuiRequest = ScanRequest | ScanBatchRequest
TuiOutcome = ScanOutcome | ScanBatchOutcome


class OrchestratorUpdate(Message):
    """Transporta un evento del núcleo al hilo principal de Textual."""

    def __init__(self, event: ScanEvent) -> None:
        self.event = event
        super().__init__()


class OrchestratorFailure(Message):
    """Transporta un error controlado desde el worker."""

    def __init__(self, error: Exception) -> None:
        self.error = error
        super().__init__()


class OrchestratorStopped(Message):
    """Confirma que el worker terminó después de una cancelación."""


class CicadaPortApp(App[None]):
    """Monitor terminal para una solicitud validada por la CLI."""

    TITLE = "CicadaPort"
    SUB_TITLE = "Authorized Security Assessment"
    BINDINGS = [
        ("f1", "show_help", "Ayuda"),
        ("f5", "start_scan", "Repetir"),
        ("ctrl+x", "cancel_scan", "Cancelar"),
        ("ctrl+l", "clear_feed", "Limpiar eventos"),
        ("q", "request_quit", "Salir"),
        ("f10", "request_quit", "Salir"),
    ]

    CSS = """
    App {
        background: ansi_default;
    }

    Screen {
        background: ansi_default;
        color: #cfdeec;
        padding: 0;
    }

    #topbar {
        height: 4;
        background: ansi_default;
        color: #cfeeff;
        border-bottom: solid #1c3d56;
        padding: 0 2;
        content-align: left middle;
    }

    #top-row {
        height: 17;
        padding: 1 1 0 1;
    }

    #activity-panel {
        width: 3fr;
        min-width: 60;
        margin-right: 1;
    }

    #session-panel {
        width: 2fr;
        min-width: 42;
    }

    #middle-row {
        height: 1fr;
        min-height: 9;
        padding: 1 1 0 1;
    }

    #findings-panel {
        width: 6fr;
        min-width: 58;
        margin-right: 1;
    }

    #feed-panel {
        width: 5fr;
        min-width: 48;
    }

    #evidence-panel {
        height: 8;
        min-height: 7;
        margin: 1 1 0 1;
    }

    .panel {
        background: ansi_default;
        border: round #1d3448;
        padding: 0 1;
    }

    .panel-active {
        border: round #2a718c;
    }

    .panel:focus-within {
        border: round #38bdf8;
    }

    .panel-title {
        height: 2;
        color: #8bdcff;
        text-style: bold;
        background: ansi_default;
        padding: 0 1;
        content-align: left middle;
    }

    .panel-body {
        height: 1fr;
        background: transparent;
        color: #cfdeec;
        padding: 0 1;
    }

    #activity-signals {
        height: 3;
        padding: 0 1;
    }

    #telemetry-metrics {
        height: 4;
        padding: 0 1;
    }

    .metric-card {
        width: 1fr;
        height: 4;
        background: ansi_default;
        border-left: solid #183a50;
        color: #cfdeec;
        margin-right: 1;
        padding: 0 1;
        content-align: left middle;
    }

    #metric-filtered {
        margin-right: 0;
    }

    #activity-progress {
        height: 3;
        padding: 0 1;
    }

    #session {
        padding: 1 1 0 1;
    }

    RichLog {
        border: none;
        background: transparent;
        overflow-x: hidden;
        scrollbar-color: #285a75;
        scrollbar-background: ansi_default;
        scrollbar-size: 1 1;
    }

    #keybar {
        height: 2;
        background: ansi_default;
        color: #7896ad;
        border-top: solid #173449;
        padding: 0 2;
        content-align: left middle;
    }
    """

    EVENT_STYLES = {
        "SYSTEM": "#38bdf8",
        "CONFIG": "#818cf8",
        "SCAN": "#22d3ee",
        "SERVICE": "#a78bfa",
        "OPEN": "bold #2dd4bf",
        "REPORT": "#e879f9",
        "CANCEL": "#fbbf24",
        "ERROR": "bold #fb7185",
        "RESULT": "#cbd5e1",
    }
    GRAPH_CHARS = "▁▂▃▄▅▆▇█"
    FILTERED_STATES = frozenset(
        {
            PortState.FILTERED,
            PortState.UNFILTERED,
            PortState.OPEN_FILTERED,
            PortState.CLOSED_FILTERED,
        }
    )

    def __init__(
        self,
        request: TuiRequest,
        *,
        auto_start: bool = True,
    ) -> None:
        super().__init__(ansi_color=True)
        self._request = request
        self._template = self._template_request(request)
        self._auto_start = auto_start
        self._orchestrator: Optional[ScanOrchestrator] = None
        self._scan_worker: Optional[Worker] = None
        self._scan_active = False
        self._phase = "queued"
        self._resolved_host = "-"
        self._current_target = self._target_label(request)
        self._effective_scan_engine = MANDATORY_SCAN_ENGINE
        self._effective_banner_engine = (
            MANDATORY_BANNER_ENGINE
            if self._template.banner_grab
            else DISABLED_BANNER_ENGINE
        )
        self._progress = 0.0
        self._scanned_ports = 0
        self._requested_targets = self._request_target_count(request)
        self._target_total = self._requested_targets
        self._completed_targets = 0
        self._failed_targets = 0
        self._completed_target_keys: Set[str] = set()
        self._failed_target_keys: Set[str] = set()
        self._total_ports = self._request_total_port_count(request)
        self._open_ports = 0
        self._closed_ports = 0
        self._filtered_ports = 0
        self._scan_started_at: Optional[float] = None
        self._scan_finished_elapsed = 0.0
        self._last_outcome: Optional[TuiOutcome] = None
        self._last_result: Optional[ScanResult] = None
        self._latency_samples: Deque[float] = deque(maxlen=76)
        self._state_samples: Deque[PortState] = deque(maxlen=76)
        self._session_id = datetime.now().strftime("%y%m%d-%H%M%S")

    def compose(self) -> ComposeResult:
        yield Static(id="topbar")
        with Horizontal(id="top-row"):
            with Vertical(classes="panel", id="activity-panel"):
                yield Static(
                    "[bold #8bdcff]01  TELEMETRY[/] "
                    "[#4d7189]/ LIVE SCAN SIGNAL[/]",
                    classes="panel-title",
                )
                yield Static(id="activity-signals")
                with Horizontal(id="telemetry-metrics"):
                    yield Static(classes="metric-card", id="metric-rate")
                    yield Static(classes="metric-card", id="metric-open")
                    yield Static(classes="metric-card", id="metric-closed")
                    yield Static(classes="metric-card", id="metric-filtered")
                yield Static(id="activity-progress")
            with Vertical(classes="panel", id="session-panel"):
                yield Static(
                    "[bold #8bdcff]02  EXECUTION[/] "
                    "[#4d7189]/ SESSION PLAN[/]",
                    classes="panel-title",
                )
                yield Static(classes="panel-body", id="session")
        with Horizontal(id="middle-row"):
            with Vertical(classes="panel", id="findings-panel"):
                yield Static(
                    "[bold #8bdcff]03  ENDPOINTS[/] "
                    "[#4d7189]/ OPEN SERVICES[/]",
                    classes="panel-title",
                )
                yield RichLog(
                    highlight=False,
                    markup=True,
                    wrap=False,
                    auto_scroll=True,
                    classes="panel-body",
                    id="findings",
                )
            with Vertical(classes="panel", id="feed-panel"):
                yield Static(
                    "[bold #8bdcff]04  EVENT STREAM[/] "
                    "[#4d7189]/ ENGINE OUTPUT[/]",
                    classes="panel-title",
                )
                yield RichLog(
                    highlight=False,
                    markup=True,
                    wrap=True,
                    auto_scroll=True,
                    classes="panel-body",
                    id="feed",
                )
        with Vertical(classes="panel", id="evidence-panel"):
            yield Static(
                "[bold #8bdcff]05  EVIDENCE[/] "
                "[#4d7189]/ SERVICE FINGERPRINT[/]",
                classes="panel-title",
            )
            yield Static(classes="panel-body", id="evidence")
        yield Static(id="keybar")

    def on_mount(self) -> None:
        self._initialize_panels()
        self._refresh_dashboard()
        self.set_interval(0.5, self._refresh_runtime)
        if self._auto_start:
            self.call_after_refresh(self.action_start_scan)

    def _feed(self) -> RichLog:
        return self.query_one("#feed", RichLog)

    def _findings(self) -> RichLog:
        return self.query_one("#findings", RichLog)

    @staticmethod
    def _timestamp() -> str:
        return datetime.now().strftime("%H:%M:%S")

    def _write_event(self, channel: str, message: str) -> None:
        style = self.EVENT_STYLES.get(channel, "#e2e8f0")
        self._feed().write(
            f"[#55758d]{self._timestamp()}[/] "
            f"[{style}]{escape(channel):<8}[/] {escape(message)}"
        )

    def _initialize_panels(self) -> None:
        self._feed().clear()
        self._findings().clear()
        self._write_event(
            "SYSTEM",
            f"session {self._session_id} initialized from validated CLI arguments",
        )
        self._write_event(
            "CONFIG",
            (
                f"targets={self._requested_targets} "
                f"profile={self._template.profile} ports={self._template.ports}"
            ),
        )
        self._write_event(
            "SYSTEM",
            "authorized targets only; telemetry reflects engine evidence",
        )
        self._render_findings_header()
        self.query_one("#evidence", Static).update(
            "[#55758d]NO SERVICE EVIDENCE YET[/]\n"
            "[#8aa4b8]The panel will retain the latest verifiable fingerprint "
            "produced by the selected engine.[/]"
        )
        self.query_one("#keybar", Static).update(
            "[#38bdf8]F1[/] CONTEXT   "
            "[#60a5fa]F5[/] REPEAT   "
            "[#fbbf24]CTRL+X[/] ABORT   "
            "[#818cf8]CTRL+L[/] CLEAR EVENTS   "
            "[#e879f9]Q / F10[/] EXIT   "
            "[#55758d]// CLI PARAMETERS LOCKED[/]"
        )

    @staticmethod
    def _progress_bar(progress: float, width: int = 38) -> str:
        normalized = max(0.0, min(100.0, progress))
        completed = int((normalized / 100.0) * width)
        blocks = "━" * completed
        remaining = "─" * (width - completed)
        return f"{blocks}{remaining} {normalized:5.1f}%"

    @classmethod
    def _sparkline(cls, samples: Deque[float], width: int = 68) -> str:
        values = list(samples)[-width:]
        if not values:
            return "·" * width
        peak = max(values)
        if peak <= 0:
            return cls.GRAPH_CHARS[0] * len(values)
        return "".join(
            cls.GRAPH_CHARS[
                min(
                    len(cls.GRAPH_CHARS) - 1,
                    int((value / peak) * (len(cls.GRAPH_CHARS) - 1)),
                )
            ]
            for value in values
        ).rjust(width, "·")

    def _state_line(self, width: int = 68) -> str:
        states = list(self._state_samples)[-width:]
        cells = []
        for state in states:
            if state is PortState.OPEN:
                cells.append("[bold #2dd4bf]◆[/]")
            elif state in self.FILTERED_STATES:
                cells.append("[#fbbf24]◆[/]")
            else:
                cells.append("[#20465d]·[/]")
        return f"{'·' * (width - len(states))}{''.join(cells)}"

    def _elapsed(self) -> float:
        if self._scan_active and self._scan_started_at is not None:
            return max(0.0, time.monotonic() - self._scan_started_at)
        return self._scan_finished_elapsed

    def _rate(self) -> float:
        elapsed = self._elapsed()
        if elapsed <= 0:
            return 0.0
        return self._scanned_ports / elapsed

    def _eta(self) -> str:
        rate = self._rate()
        remaining = max(0, self._total_ports - self._scanned_ports)
        if not self._scan_active or rate <= 0:
            return "--:--"
        seconds = int(remaining / rate)
        minutes, seconds = divmod(seconds, 60)
        hours, minutes = divmod(minutes, 60)
        if hours:
            return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
        return f"{minutes:02d}:{seconds:02d}"

    @staticmethod
    def _format_duration(seconds: float) -> str:
        normalized = max(0.0, seconds)
        minutes, remaining_seconds = divmod(normalized, 60.0)
        hours, remaining_minutes = divmod(int(minutes), 60)
        if hours:
            return (
                f"{hours:02d}:{remaining_minutes:02d}:"
                f"{remaining_seconds:04.1f}"
            )
        return f"{remaining_minutes:02d}:{remaining_seconds:04.1f}"

    @staticmethod
    def _session_pair(
        left: str,
        right: str,
        width: int,
        *,
        values: bool = False,
        accent: bool = False,
    ) -> str:
        left_value = f"{str(left)[:width]:<{width}}"
        right_value = f"{str(right)[:width]:<{width}}"
        if accent:
            left_style = "#67e8f9"
            right_style = "#a5b4fc"
        elif values:
            left_style = right_style = "#cfdeec"
        else:
            left_style = right_style = "#55758d"
        return (
            f"[{left_style}]{escape(left_value)}[/]  "
            f"[{right_style}]{escape(right_value)}[/]"
        )

    def _refresh_topbar(self) -> None:
        phase_style = {
            "queued": "#818cf8",
            "scanning": "#22d3ee",
            "service-detection": "#a78bfa",
            "complete": "#2dd4bf",
            "cancelled": "#fbbf24",
            "failed": "#fb7185",
        }.get(self._phase, "#94a3b8")
        target_label = self._target_label(self._request)
        self.query_one("#topbar", Static).update(
            "[bold #8bdcff]CICADAPORT[/]  "
            "[#41677f]/ SPECIALIZED RECON CONSOLE[/]     "
            "[#55758d]SESSION[/] "
            f"[#a5b4fc]{self._session_id}[/]\n"
            "[#55758d]TARGET SET[/] "
            f"[#e4f2fc]{escape(target_label)}[/]   "
            "[#55758d]PROFILE[/] "
            f"[#7dd3fc]{escape(self._template.profile.upper())}[/]   "
            "[#55758d]ENGINE[/] "
            f"[#67e8f9]{escape(self._effective_scan_engine.upper())}[/]   "
            "[#55758d]PHASE[/] "
            f"[bold {phase_style}]{escape(self._phase.upper())}[/]   "
            f"[#7896ad]{self._timestamp()}[/]"
        )

    def _refresh_activity(self) -> None:
        signal_widget = self.query_one("#activity-signals", Static)
        activity_width = signal_widget.size.width
        graph_width = max(18, min(52, activity_width - 28))
        progress_width = max(18, activity_width - 15)
        progress = self._progress_bar(self._progress, progress_width)
        latency = self._sparkline(self._latency_samples, graph_width)
        states = self._state_line(graph_width)
        signal_widget.update(
            f"[#55758d]RTT / MS[/]        [#38bdf8]{latency}[/]\n"
            f"[#55758d]PORT RESPONSE[/]   {states}"
        )
        self.query_one("#metric-rate", Static).update(
            "[#55758d]THROUGHPUT[/]\n"
            f"[bold #67e8f9]{self._rate():,.1f}[/] "
            "[#7896ad]ports/s[/]"
        )
        self.query_one("#metric-open", Static).update(
            "[#55758d]OPEN[/]\n"
            f"[bold #2dd4bf]{self._open_ports:,}[/] "
            "[#7896ad]endpoints[/]"
        )
        self.query_one("#metric-closed", Static).update(
            "[#55758d]CLOSED[/]\n"
            f"[bold #b8c7d5]{self._closed_ports:,}[/] "
            "[#7896ad]ports[/]"
        )
        self.query_one("#metric-filtered", Static).update(
            "[#55758d]FILTERED[/]\n"
            f"[bold #fbbf24]{self._filtered_ports:,}[/] "
            "[#7896ad]ports[/]"
        )
        self.query_one("#activity-progress", Static).update(
            "[#55758d]COVERAGE[/]  "
            f"[#e4f2fc]{self._scanned_ports:,} / {self._total_ports:,}[/]   "
            "[#55758d]ETA[/] "
            f"[#b8c7d5]{self._eta()}[/]   "
            "[#55758d]ELAPSED[/] "
            f"[#b8c7d5]{self._format_duration(self._elapsed())}[/]\n"
            f"[#60a5fa]{progress}[/]"
        )

    def _refresh_session(self) -> None:
        request = self._template
        report_mode = (
            request.output if request.output else f"{request.report_dir}/scan_report_*"
        )
        session_width = self.query_one("#session", Static).size.width
        column_width = max(13, min(24, (session_width - 5) // 2))
        target = self._clean_field(self._current_target, max(18, session_width - 2))
        resolved = self._clean_field(
            self._resolved_host,
            max(18, session_width - 2),
        )
        port_scope = self._clean_field(request.ports, column_width)
        report = self._clean_field(str(report_mode), max(22, session_width - 2))
        active_targets = self._active_target_count()
        target_workers = (
            self._request.target_workers
            if isinstance(self._request, ScanBatchRequest)
            else 1
        )
        target_counts = self._session_pair(
            str(self._requested_targets),
            str(active_targets),
            column_width,
            values=True,
        )
        completion_counts = self._session_pair(
            str(self._completed_targets),
            str(self._failed_targets),
            column_width,
            values=True,
        )
        transport_values = self._session_pair(
            "TCP CONNECT",
            port_scope,
            column_width,
            values=True,
        )
        engine_values = self._session_pair(
            self._effective_scan_engine.upper(),
            self._effective_banner_engine.upper(),
            column_width,
            values=True,
            accent=True,
        )
        worker_values = self._session_pair(
            str(request.threads),
            str(target_workers),
            column_width,
            values=True,
        )
        self.query_one("#session", Static).update(
            "[#55758d]CURRENT TARGET / RESOLUTION[/]\n"
            f"[#e4f2fc]{escape(target)}[/]  "
            f"[#67e8f9]{escape(resolved)}[/]\n"
            f"{self._session_pair('TARGETS', 'ACTIVE', column_width)}\n"
            f"{target_counts}\n"
            f"{self._session_pair('DONE', 'FAILED', column_width)}\n"
            f"{completion_counts}\n"
            f"{self._session_pair('TRANSPORT', 'PORT SCOPE', column_width)}\n"
            f"{transport_values}\n"
            f"{self._session_pair('SCAN ENGINE', 'SERVICE ENGINE', column_width)}\n"
            f"{engine_values}\n"
            f"{self._session_pair('THREAD BUDGET', 'TARGET WORKERS', column_width)}\n"
            f"{worker_values}\n"
            "[#55758d]OUTPUT / REPORT[/]\n"
            f"[#e879f9]{escape(request.report_format.upper())}[/]  "
            f"[#8aa4b8]{escape(report)}[/]"
        )

    def _refresh_dashboard(self) -> None:
        self.query_one("#activity-panel").set_class(
            self._scan_active,
            "panel-active",
        )
        self._refresh_topbar()
        self._refresh_activity()
        self._refresh_session()

    def _refresh_runtime(self) -> None:
        required_widgets = (
            "#topbar",
            "#activity-signals",
            "#metric-rate",
            "#metric-open",
            "#metric-closed",
            "#metric-filtered",
            "#activity-progress",
            "#session",
        )
        if any(
            self.query_one_optional(selector) is None
            for selector in required_widgets
        ):
            return

        self._refresh_topbar()
        self._refresh_activity()
        self._refresh_session()

    def _build_request(self) -> TuiRequest:
        """Devuelve la solicitud inmutable recibida desde la CLI."""
        return self._request

    @staticmethod
    def _template_request(request: TuiRequest) -> ScanRequest:
        return request.template if isinstance(request, ScanBatchRequest) else request

    @staticmethod
    def _request_target_count(request: TuiRequest) -> int:
        if isinstance(request, ScanBatchRequest):
            return max(1, len(request.targets))
        return 1

    @classmethod
    def _request_total_port_count(cls, request: TuiRequest) -> int:
        template = cls._template_request(request)
        return cls._request_port_count(template) * cls._request_target_count(request)

    @staticmethod
    def _request_port_count(request: ScanRequest) -> int:
        if request.common_ports:
            return len(config.COMMON_PORTS)
        port_range = NetworkUtils.validate_port_range(request.ports)
        if port_range is None:
            return 0
        start_port, end_port = port_range
        return end_port - start_port + 1

    @staticmethod
    def _target_label(request: TuiRequest) -> str:
        if isinstance(request, ScanBatchRequest):
            total = max(1, len(request.targets))
            first = request.targets[0] if request.targets else "targets"
            return f"{total} targets / {first}"
        return request.host

    def _active_target_count(self) -> int:
        remaining = max(
            0,
            self._target_total - self._completed_targets - self._failed_targets,
        )
        if not self._scan_active:
            return 0
        configured = (
            self._request.target_workers
            if isinstance(self._request, ScanBatchRequest)
            else 1
        )
        return min(configured, self._template.threads, remaining)

    @staticmethod
    def _event_context(event: ScanEvent) -> str:
        target = event.data.get("target")
        resolved = event.data.get("resolved_host")
        index = event.data.get("target_index")
        total = event.data.get("target_total")
        parts = []
        if index and total:
            parts.append(f"{index}/{total}")
        if target:
            parts.append(str(target))
        if resolved and resolved != target:
            parts.append(str(resolved))
        return f"[{' | '.join(parts)}] " if parts else ""

    @staticmethod
    def _event_target_key(event: ScanEvent) -> str:
        failure = event.data.get("failure")
        if failure is not None:
            return f"{failure.target}|{failure.resolved_host or ''}|{failure.phase}"
        return "|".join(
            str(event.data.get(name) or "")
            for name in ("target_index", "target", "resolved_host")
        )

    def _set_active(self, active: bool) -> None:
        if not active and self._scan_started_at is not None:
            self._scan_finished_elapsed = max(
                0.0,
                time.monotonic() - self._scan_started_at,
            )
        self._scan_active = active
        self._refresh_dashboard()

    def action_start_scan(self) -> None:
        if self._scan_active:
            self._write_event("ERROR", "a scan is already active")
            return
        self._phase = "scanning"
        self._progress = 0.0
        self._scanned_ports = 0
        self._requested_targets = self._request_target_count(self._request)
        self._target_total = self._requested_targets
        self._completed_targets = 0
        self._failed_targets = 0
        self._completed_target_keys.clear()
        self._failed_target_keys.clear()
        self._total_ports = self._request_total_port_count(self._request)
        self._open_ports = 0
        self._closed_ports = 0
        self._filtered_ports = 0
        self._scan_started_at = time.monotonic()
        self._scan_finished_elapsed = 0.0
        self._last_outcome = None
        self._last_result = None
        self._resolved_host = "-"
        self._current_target = self._target_label(self._request)
        self._latency_samples.clear()
        self._state_samples.clear()
        self._render_findings_header()
        self._set_active(True)
        self._write_event(
            "SCAN",
            (
                f"launching targets={self._requested_targets} "
                f"profile={self._template.profile} ports={self._template.ports}"
            ),
        )
        self._scan_worker = self._run_scan(self._request)

    def action_cancel_scan(self) -> None:
        if not self._scan_active:
            self._write_event("SYSTEM", "no active scan")
            return
        self._write_event(
            "CANCEL",
            "cooperative shutdown requested for active engines",
        )
        if self._orchestrator is not None:
            self._orchestrator.cancel()
        elif self._scan_worker is not None:
            self._scan_worker.cancel()

    def action_clear_feed(self) -> None:
        self._feed().clear()
        self._write_event("SYSTEM", "event stream cleared")

    def action_show_help(self) -> None:
        self._write_event(
            "SYSTEM",
            "scan parameters come from the shell; F5 repeats the same request",
        )
        self._write_event(
            "SYSTEM",
            "Ctrl+X aborts safely; Ctrl+L clears events; Q or F10 exits",
        )

    def action_request_quit(self) -> None:
        if self._orchestrator is not None:
            self._orchestrator.cancel()
        if self._scan_worker is not None:
            self._scan_worker.cancel()
        self.exit()

    @staticmethod
    def _execute_request(
        orchestrator: ScanOrchestrator,
        request: TuiRequest,
    ) -> TuiOutcome:
        if isinstance(request, ScanBatchRequest):
            return orchestrator.run_many(request)
        return orchestrator.run(request)

    @work(
        thread=True,
        exclusive=True,
        group="scan",
        exit_on_error=False,
    )
    def _run_scan(self, request: TuiRequest) -> None:
        def post_event(event: ScanEvent) -> None:
            self.post_message(OrchestratorUpdate(event))

        self._orchestrator = ScanOrchestrator(event_callback=post_event)
        try:
            self._execute_request(self._orchestrator, request)
        except ScanCancelledError:
            self.post_message(OrchestratorStopped())
        except Exception as error:
            self.post_message(OrchestratorFailure(error))

    @staticmethod
    def _clean_field(value: object, limit: int = 96) -> str:
        normalized = " ".join(str(value or "").split())
        if len(normalized) <= limit:
            return normalized
        return f"{normalized[: limit - 3]}..."

    def _render_findings_header(self) -> None:
        findings = self._findings()
        findings.clear()
        findings.write(
            "[#55758d]TARGET          ADDRESS          ENDPOINT     STATE   "
            "SERVICE          RTT       FINGERPRINT[/]"
        )

    def _write_finding(
        self,
        result: ScanResult,
        *,
        target: Optional[str] = None,
        resolved_host: Optional[str] = None,
    ) -> None:
        service = self._clean_field(result.service or "unknown", 16)
        fingerprint = self._clean_field(result.banner or "pending", 32)
        target_value = self._clean_field(target or result.target or "-", 15)
        address_value = self._clean_field(
            resolved_host or result.address or "-",
            15,
        )
        self._findings().write(
            f"[#e4f2fc]{escape(target_value):<15}[/] "
            f"[#67e8f9]{escape(address_value):<15}[/] "
            f"[bold #e4f2fc]{result.port:>5}/"
            f"{escape(result.protocol.upper()):<6}[/] "
            "[bold #2dd4bf]OPEN[/]    "
            f"[#67e8f9]{escape(service):<16}[/] "
            f"[#8aa4b8]{result.response_time * 1000:>7.2f}ms[/] "
            f"[#a5b4fc]{escape(fingerprint)}[/]"
        )

    def _update_evidence(
        self,
        result: ScanResult,
        *,
        target: Optional[str] = None,
        resolved_host: Optional[str] = None,
    ) -> None:
        self._last_result = result
        banner = escape(self._clean_field(result.banner or "not captured yet", 300))
        target_value = escape(
            self._clean_field(target or result.target or "-", 72)
        )
        address_value = escape(
            self._clean_field(resolved_host or result.address or "-", 72)
        )
        self.query_one("#evidence", Static).update(
            "[#55758d]OPEN ENDPOINT[/]  "
            f"[bold #2dd4bf]{result.port}/{escape(result.protocol.upper())}[/]   "
            "[#55758d]SERVICE[/]  "
            f"[#67e8f9]{escape(result.service or 'unknown')}[/]   "
            "[#55758d]RTT[/]  "
            f"[#cfdeec]{result.response_time * 1000:.2f} MS[/]\n"
            f"[#55758d]TARGET[/] [#e4f2fc]{target_value}[/] "
            "[#41677f]→[/] "
            f"[#67e8f9]{address_value}[/]\n"
            f"[#55758d]FINGERPRINT[/]  [#a5b4fc]{banner}[/]"
        )

    def _render_final_findings(self, outcome: ScanOutcome) -> None:
        open_results = [
            result
            for result in outcome.results
            if result.state is PortState.OPEN
        ]
        self._render_findings_header()
        if not open_results:
            self._findings().write("[#55758d]No open endpoints detected.[/]")
        for result in open_results:
            self._write_finding(
                result,
                target=outcome.target,
                resolved_host=outcome.resolved_host,
            )

        if self._last_result is None:
            endpoint = "[#55758d]LAST ENDPOINT[/]  [#8aa4b8]NONE[/]"
        else:
            endpoint = (
                f"[#55758d]LAST ENDPOINT[/]  [bold #2dd4bf]"
                f"{self._last_result.port}/"
                f"{escape(self._last_result.protocol.upper())}[/]   "
                f"[#55758d]SERVICE[/]  [#67e8f9]"
                f"{escape(self._last_result.service or 'unknown')}[/]"
            )
        self.query_one("#evidence", Static).update(
            endpoint
            + "   [#55758d]OPEN[/]  [bold #2dd4bf]"
            f"{outcome.statistics['open_ports']}[/]   "
            "[#55758d]CLOSED[/]  "
            f"[#cfdeec]{outcome.statistics['closed_ports']}[/]   "
            "[#55758d]FILTERED[/]  [#fbbf24]"
            f"{outcome.statistics['filtered_ports']}[/]\n"
            f"[#55758d]TARGET[/]  [#e4f2fc]{escape(outcome.target)}[/]  "
            "[#41677f]→[/]  [#67e8f9]"
            f"{escape(outcome.resolved_host)}[/]\n"
            f"[#55758d]REPORT[/]  [#e879f9]"
            f"{escape(str(outcome.output_path))}[/]"
        )

    def _render_final_batch(self, outcome: ScanBatchOutcome) -> None:
        self._render_findings_header()
        open_count = 0
        for target_outcome in outcome.outcomes:
            for result in target_outcome.results:
                if result.state is PortState.OPEN:
                    open_count += 1
                    self._write_finding(
                        result,
                        target=target_outcome.target,
                        resolved_host=target_outcome.resolved_host,
                    )
        if open_count == 0:
            self._findings().write("[#55758d]No open endpoints detected.[/]")

        stats = outcome.statistics
        latest_report = (
            str(outcome.outcomes[-1].output_path)
            if outcome.outcomes
            else "none"
        )
        self.query_one("#evidence", Static).update(
            "[#55758d]BATCH RESULT[/]  "
            f"[#e4f2fc]{stats['completed_targets']} completed[/]   "
            f"[#fb7185]{stats['failed_targets']} failed[/]   "
            f"[#2dd4bf]{stats['open_ports']} open[/]\n"
            "[#55758d]RESOLVED[/]  "
            f"[#67e8f9]{stats['resolved_targets']}[/]   "
            "[#55758d]TARGET WORKERS[/]  "
            f"[#a5b4fc]{stats['target_workers']}[/]   "
            "[#55758d]WORKER BUDGET[/]  "
            f"[#cfdeec]{stats['worker_budget']}[/]\n"
            "[#55758d]LATEST REPORT[/]  "
            f"[#e879f9]{escape(latest_report)}[/]"
        )

    def on_orchestrator_update(
        self,
        message: OrchestratorUpdate,
    ) -> None:
        event = message.event
        context = self._event_context(event)

        if event.progress is not None:
            self._progress = max(0.0, min(100.0, float(event.progress)))

        target_total = event.data.get("target_total")
        if target_total:
            self._target_total = max(self._target_total, int(target_total))
            self._total_ports = (
                self._request_port_count(self._template) * self._target_total
            )
        if event.data.get("target"):
            self._current_target = str(event.data["target"])
        if event.data.get("resolved_host"):
            self._resolved_host = str(event.data["resolved_host"])

        if event.kind == ScanEventType.TARGET_STARTED:
            self._write_event("SCAN", context + event.message)
            self._refresh_dashboard()
            return

        if event.kind == ScanEventType.PROGRESS:
            if event.result is not None:
                self._scanned_ports += 1
                self._latency_samples.append(
                    max(0.0, event.result.response_time * 1000.0)
                )
                self._state_samples.append(event.result.state)
                if event.result.state in self.FILTERED_STATES:
                    self._filtered_ports += 1
                elif event.result.state is PortState.CLOSED:
                    self._closed_ports += 1
            self._refresh_activity()
            return

        if event.kind == ScanEventType.STATUS:
            phase = event.data.get("phase")
            if phase:
                self._phase = str(phase)
            if event.data.get("scan_engine"):
                self._effective_scan_engine = str(event.data["scan_engine"])
            if event.data.get("banner_engine"):
                self._effective_banner_engine = str(event.data["banner_engine"])
            channel = "SERVICE" if self._phase == "service-detection" else "SCAN"
            self._write_event(channel, context + event.message)
            self._refresh_dashboard()
            return

        if event.kind == ScanEventType.OPEN_PORT and event.result is not None:
            self._open_ports += 1
            target = str(event.data.get("target") or event.result.target or "-")
            resolved = str(
                event.data.get("resolved_host") or event.result.address or "-"
            )
            self._write_finding(
                event.result,
                target=target,
                resolved_host=resolved,
            )
            self._update_evidence(
                event.result,
                target=target,
                resolved_host=resolved,
            )
            self._write_event(
                "OPEN",
                (
                    context
                    + f"{event.result.port}/{event.result.protocol} "
                    f"{event.result.service or 'unknown'} "
                    f"rtt={event.result.response_time * 1000:.2f}ms"
                ),
            )
            self._refresh_activity()
            return

        if event.kind == ScanEventType.REPORT:
            self._write_event("REPORT", context + event.message)
            return

        if event.kind == ScanEventType.TARGET_COMPLETE:
            key = self._event_target_key(event)
            if key not in self._completed_target_keys:
                self._completed_target_keys.add(key)
                self._completed_targets += 1
            self._write_event("RESULT", context + "target complete")
            self._refresh_dashboard()
            return

        if event.kind == ScanEventType.TARGET_FAILED:
            key = self._event_target_key(event)
            if key not in self._failed_target_keys:
                self._failed_target_keys.add(key)
                self._failed_targets += 1
            failure = event.data.get("failure")
            if failure is not None:
                self._current_target = failure.target
                self._resolved_host = failure.resolved_host or "-"
            self._write_event("ERROR", context + event.message)
            self._refresh_dashboard()
            return

        if event.kind == ScanEventType.COMPLETE:
            outcome = event.data["outcome"]
            self._last_outcome = outcome
            self._phase = "complete"
            self._resolved_host = outcome.resolved_host
            self._current_target = outcome.target
            self._effective_scan_engine = outcome.scan_engine
            self._effective_banner_engine = outcome.banner_engine
            self._progress = 100.0
            self._scanned_ports = outcome.statistics["total_ports"]
            self._open_ports = outcome.statistics["open_ports"]
            self._closed_ports = outcome.statistics["closed_ports"]
            self._filtered_ports = outcome.statistics["filtered_ports"]
            self._completed_targets = 1
            self._render_final_findings(outcome)
            self._write_event(
                "RESULT",
                (
                    f"complete open={outcome.statistics['open_ports']} "
                    f"closed={outcome.statistics['closed_ports']} "
                    f"filtered={outcome.statistics['filtered_ports']}"
                ),
            )
            self._set_active(False)
            self._orchestrator = None
            return

        if event.kind == ScanEventType.BATCH_COMPLETE:
            outcome = event.data["outcome"]
            self._last_outcome = outcome
            stats = outcome.statistics
            self._phase = "complete"
            self._progress = 100.0
            self._requested_targets = stats["requested_targets"]
            self._target_total = stats["resolved_targets"]
            self._completed_targets = stats["completed_targets"]
            self._failed_targets = stats["failed_targets"]
            self._scanned_ports = stats["total_ports"]
            self._total_ports = stats["total_ports"]
            self._open_ports = stats["open_ports"]
            self._closed_ports = stats["closed_ports"]
            self._filtered_ports = stats["filtered_ports"]
            self._current_target = "batch complete"
            self._resolved_host = f"{stats['resolved_targets']} resolved"
            self._render_final_batch(outcome)
            self._write_event("RESULT", event.message)
            self._set_active(False)
            self._orchestrator = None
            return

        if event.kind == ScanEventType.CANCELLED:
            self._phase = "cancelled"
            self._write_event("CANCEL", context + event.message)
            if not isinstance(self._request, ScanBatchRequest):
                self._set_active(False)
                self._orchestrator = None

    def on_orchestrator_failure(
        self,
        message: OrchestratorFailure,
    ) -> None:
        self._phase = "failed"
        self._write_event("ERROR", f"scan failed: {message.error}")
        self._set_active(False)
        self._orchestrator = None

    def on_orchestrator_stopped(
        self,
        _message: OrchestratorStopped,
    ) -> None:
        self._phase = "cancelled"
        if self._scan_active:
            self._write_event(
                "CANCEL",
                "all active targets stopped cooperatively",
            )
            self._set_active(False)
        self._orchestrator = None


def launch_tui(request: TuiRequest) -> None:
    """Inicia el monitor TUI con una solicitud validada por la CLI."""
    CicadaPortApp(request=request, auto_start=True).run()
