package main

import (
	"bytes"
	"context"
	"crypto/sha256"
	"crypto/tls"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net"
	"os"
	"sort"
	"strconv"
	"strings"
	"sync"
	"time"
	"unicode/utf8"
)

const (
	contractVersion                = 1
	serviceEvidenceContractVersion = 2
	maxRequestBytes                = 1 << 20
	maxBannerRead                  = 4096
	maxBannerOutputRunes           = 300
	maxBannerWorkers               = 32
	maxResultChannelCapacity       = 32
	maxProbePayloadBytes           = 1024
	nativeEventFDEnv               = "CICADAPORT_NATIVE_EVENT_FD"
	serviceEvidenceFDEnv           = "CICADAPORT_SERVICE_EVIDENCE_FD"
	helpText                       = "Usage: go-banner --request-stdin\n\nOpciones:\n  --request-stdin  Lee una solicitud banner_request v1 completa desde stdin.\n  --help           Muestra esta ayuda y termina.\n"
)

type invocation int

const (
	invocationHelp invocation = iota
	invocationRequestStdin
)

type BannerRequest struct {
	ContractVersion int    `json:"contract_version"`
	RecordType      string `json:"record_type"`
	Target          string `json:"target"`
	Ports           []int  `json:"ports"`
	TimeoutMS       int64  `json:"timeout_ms"`
}

type BannerResult struct {
	ContractVersion int     `json:"contract_version"`
	RecordType      string  `json:"record_type"`
	Target          string  `json:"target"`
	Port            int     `json:"port"`
	Status          string  `json:"status"`
	Service         string  `json:"service"`
	Banner          *string `json:"banner"`
	Error           *string `json:"error"`
	Source          string  `json:"source"`
}

type NativeEvent struct {
	ContractVersion int    `json:"contract_version"`
	RecordType      string `json:"record_type"`
	Engine          string `json:"engine"`
	Phase           string `json:"phase"`
	Event           string `json:"event"`
	Target          string `json:"target"`
	Sequence        int    `json:"sequence"`
	ElapsedMS       int64  `json:"elapsed_ms"`
	Port            *int   `json:"port"`
	Status          string `json:"status"`
	Completed       int    `json:"completed"`
	Total           int    `json:"total"`
	Workers         int    `json:"workers"`
}

type ProbeDescriptor struct {
	Identifier       string   `json:"identifier"`
	Version          int      `json:"version"`
	Transport        string   `json:"transport"`
	PayloadSHA256    string   `json:"payload_sha256"`
	MaximumBytes     int      `json:"maximum_bytes"`
	Terminators      []string `json:"terminators"`
	Invasiveness     string   `json:"invasiveness"`
	AllowedByDefault bool     `json:"allowed_by_default"`
	Parser           string   `json:"parser"`
}

type PhaseTimeoutEvidence struct {
	ConnectMS      int64 `json:"connect_timeout_ms"`
	TLSHandshakeMS int64 `json:"tls_handshake_timeout_ms"`
	WriteMS        int64 `json:"write_timeout_ms"`
	FirstByteMS    int64 `json:"first_byte_timeout_ms"`
	IdleReadMS     int64 `json:"idle_read_timeout_ms"`
	TotalProbeMS   int64 `json:"total_probe_timeout_ms"`
}

type TLSEvidence struct {
	TLSNegotiated       bool     `json:"tls_negotiated"`
	CertificatePresent  bool     `json:"certificate_present"`
	CertificateVerified bool     `json:"certificate_verified"`
	VerificationError   string   `json:"verification_error"`
	ProtocolVersion     string   `json:"protocol_version"`
	CipherSuite         string   `json:"cipher_suite"`
	ALPN                string   `json:"alpn"`
	Subject             string   `json:"subject"`
	Issuer              string   `json:"issuer"`
	SANDNS              []string `json:"san_dns"`
	SANIP               []string `json:"san_ip"`
	NotBefore           string   `json:"not_before"`
	NotAfter            string   `json:"not_after"`
	CertificateSHA256   string   `json:"certificate_sha256"`
	ChainLength         int      `json:"chain_length"`
}

type ServiceEvidence struct {
	ContractVersion int                  `json:"contract_version"`
	RecordType      string               `json:"record_type"`
	Target          string               `json:"target"`
	Port            int                  `json:"port"`
	ServiceHint     string               `json:"service_hint"`
	Status          string               `json:"status"`
	Confidence      string               `json:"confidence"`
	Probe           ProbeDescriptor      `json:"probe"`
	Phase           string               `json:"phase"`
	PartialBytes    bool                 `json:"partial_bytes"`
	RawLength       int                  `json:"raw_length"`
	CapturedLength  int                  `json:"captured_length"`
	Truncated       bool                 `json:"truncated"`
	Encoding        string               `json:"encoding"`
	PayloadSHA256   string               `json:"payload_sha256"`
	BannerDisplay   *string              `json:"banner_display"`
	Error           *string              `json:"error"`
	Timeouts        PhaseTimeoutEvidence `json:"timeouts"`
	TLS             *TLSEvidence         `json:"tls"`
}

type nativeEventWriter struct {
	encoder  *json.Encoder
	file     *os.File
	started  time.Time
	sequence int
	target   string
	total    int
	workers  int
}

type serviceEvidenceWriter struct {
	encoder *json.Encoder
	file    *os.File
}

type probePlan struct {
	descriptor ProbeDescriptor
	payload    []byte
	useTLS     bool
}

type phaseTimeouts struct {
	connect      time.Duration
	tlsHandshake time.Duration
	write        time.Duration
	firstByte    time.Duration
	idleRead     time.Duration
	totalProbe   time.Duration
}

type probeOutcome struct {
	result   BannerResult
	evidence ServiceEvidence
}

func newNativeEventWriter(w io.Writer, target string, total, workers int) *nativeEventWriter {
	return &nativeEventWriter{encoder: json.NewEncoder(w), started: time.Now(), target: target, total: total, workers: workers}
}

func inheritedFileFromEnv(name, label string) (*os.File, error) {
	raw := os.Getenv(name)
	if raw == "" {
		return nil, nil
	}
	fd, err := strconv.Atoi(raw)
	if err != nil || fd < 3 {
		return nil, fmt.Errorf("%s debe ser descriptor heredado", name)
	}
	file := os.NewFile(uintptr(fd), label)
	if file == nil {
		return nil, fmt.Errorf("no se pudo abrir %s", label)
	}
	return file, nil
}

func nativeEventWriterFromEnv(target string, total, workers int) (*nativeEventWriter, error) {
	file, err := inheritedFileFromEnv(nativeEventFDEnv, "cicadaport-native-event")
	if err != nil || file == nil {
		return nil, err
	}
	writer := newNativeEventWriter(file, target, total, workers)
	writer.file = file
	return writer, nil
}

func serviceEvidenceWriterFromEnv() (*serviceEvidenceWriter, error) {
	file, err := inheritedFileFromEnv(serviceEvidenceFDEnv, "cicadaport-service-evidence")
	if err != nil || file == nil {
		return nil, err
	}
	return &serviceEvidenceWriter{encoder: json.NewEncoder(file), file: file}, nil
}

func (w *nativeEventWriter) close() error {
	if w == nil || w.file == nil {
		return nil
	}
	return w.file.Close()
}

func (w *serviceEvidenceWriter) close() error {
	if w == nil || w.file == nil {
		return nil
	}
	return w.file.Close()
}

func (w *nativeEventWriter) emit(event, status string, port *int, completed int) error {
	if w == nil {
		return nil
	}
	w.sequence++
	return w.encoder.Encode(NativeEvent{ContractVersion: contractVersion, RecordType: "native_event", Engine: "go", Phase: "banner_grab", Event: event, Target: w.target, Sequence: w.sequence, ElapsedMS: time.Since(w.started).Milliseconds(), Port: port, Status: status, Completed: completed, Total: w.total, Workers: w.workers})
}

func (w *serviceEvidenceWriter) emit(evidence ServiceEvidence) error {
	if w == nil {
		return nil
	}
	return w.encoder.Encode(evidence)
}

func serviceName(port int) string {
	services := map[int]string{
		20: "FTP-Data", 21: "FTP", 22: "SSH", 23: "Telnet", 25: "SMTP",
		53: "DNS", 80: "HTTP", 110: "POP3", 143: "IMAP", 443: "HTTPS",
		445: "SMB", 465: "SMTPS", 587: "SMTP-Submission", 636: "LDAPS",
		993: "IMAPS", 995: "POP3S", 1433: "MSSQL", 2376: "Docker-TLS",
		3306: "MySQL", 3389: "RDP", 5432: "PostgreSQL", 5900: "VNC",
		6379: "Redis", 8000: "HTTP-Alt", 8080: "HTTP-Alt", 8443: "HTTPS-Alt",
		9200: "Elasticsearch", 27017: "MongoDB",
	}
	if service, ok := services[port]; ok {
		return service
	}
	return "Unknown"
}

func normalizePorts(rawPorts []int) ([]int, error) {
	portsMap := make(map[int]bool)
	for _, port := range rawPorts {
		if port < 1 || port > 65535 {
			return nil, fmt.Errorf("puerto fuera de rango: %d", port)
		}
		portsMap[port] = true
	}
	if len(portsMap) == 0 {
		return nil, fmt.Errorf("no se recibieron puertos válidos")
	}
	ports := make([]int, 0, len(portsMap))
	for port := range portsMap {
		ports = append(ports, port)
	}
	sort.Ints(ports)
	return ports, nil
}

func parseBannerRequest(reader io.Reader) (BannerRequest, error) {
	var request BannerRequest
	payload, err := io.ReadAll(io.LimitReader(reader, maxRequestBytes+1))
	if err != nil {
		return request, fmt.Errorf("no se pudo leer banner_request: %w", err)
	}
	if len(payload) > maxRequestBytes {
		return request, fmt.Errorf("banner_request excede %d bytes", maxRequestBytes)
	}
	decoder := json.NewDecoder(bytes.NewReader(payload))
	decoder.DisallowUnknownFields()
	if err := decoder.Decode(&request); err != nil {
		return request, fmt.Errorf("solicitud JSON de banners inválida: %w", err)
	}
	var trailing any
	if err := decoder.Decode(&trailing); err != io.EOF {
		if err == nil {
			return request, fmt.Errorf("la entrada debe contener un único objeto JSON")
		}
		return request, fmt.Errorf("contenido adicional inválido: %w", err)
	}
	if request.ContractVersion != contractVersion {
		return request, fmt.Errorf("contract_version no compatible: %d; esperado %d", request.ContractVersion, contractVersion)
	}
	if request.RecordType != "banner_request" {
		return request, fmt.Errorf("record_type debe ser 'banner_request'")
	}
	request.Target = strings.TrimSpace(request.Target)
	if request.Target == "" {
		return request, fmt.Errorf("target debe ser una cadena no vacía")
	}
	if strings.ContainsRune(request.Target, '\x00') {
		return request, fmt.Errorf("target contiene un carácter nulo")
	}
	ports, err := normalizePorts(request.Ports)
	if err != nil {
		return request, err
	}
	request.Ports = ports
	if request.TimeoutMS <= 0 {
		return request, fmt.Errorf("timeout_ms debe ser mayor a 0")
	}
	return request, nil
}

func stripTerminalSequences(value string) string {
	var out strings.Builder
	for index := 0; index < len(value); {
		if value[index] != 0x1b {
			r, size := utf8.DecodeRuneInString(value[index:])
			if r == utf8.RuneError && size == 1 {
				index++
				continue
			}
			out.WriteRune(r)
			index += size
			continue
		}
		index++
		if index >= len(value) {
			break
		}
		switch value[index] {
		case '[':
			index++
			for index < len(value) {
				b := value[index]
				index++
				if b >= 0x40 && b <= 0x7e {
					break
				}
			}
		case ']':
			index++
			for index < len(value) {
				if value[index] == 0x07 {
					index++
					break
				}
				if value[index] == 0x1b && index+1 < len(value) && value[index+1] == '\\' {
					index += 2
					break
				}
				index++
			}
		default:
			index++
		}
	}
	return out.String()
}

func isDangerousInvisible(r rune) bool {
	return (r >= 0x80 && r <= 0x9f) ||
		(r >= 0x200b && r <= 0x200f) ||
		(r >= 0x202a && r <= 0x202e) ||
		(r >= 0x2060 && r <= 0x206f) ||
		r == 0xfeff
}

func sanitizeBanner(raw string) string {
	cleaned := stripTerminalSequences(strings.ToValidUTF8(raw, ""))
	var out strings.Builder
	for _, r := range cleaned {
		switch {
		case r == 0:
			continue
		case r == '\r' || r == '\n' || r == '\t':
			out.WriteRune(' ')
		case r < 0x20 || r == 0x7f || isDangerousInvisible(r):
			continue
		default:
			out.WriteRune(r)
		}
	}
	value := strings.TrimSpace(out.String())
	runes := []rune(value)
	if len(runes) > maxBannerOutputRunes {
		return string(runes[:maxBannerOutputRunes])
	}
	return value
}

func shouldSendHTTPProbe(port int) bool {
	switch port {
	case 80, 443, 8000, 8080, 8443, 9200:
		return true
	default:
		return false
	}
}

func shouldUseTLS(port int) bool {
	switch port {
	case 443, 465, 636, 993, 995, 2376, 8443:
		return true
	default:
		return false
	}
}

func normalizeHost(host string) string {
	normalizedHost := strings.TrimSpace(host)
	normalizedHost = strings.TrimPrefix(normalizedHost, "[")
	normalizedHost = strings.TrimSuffix(normalizedHost, "]")
	return normalizedHost
}

func buildHTTPProbe(host string) []byte {
	normalizedHost := normalizeHost(host)
	hostHeader := normalizedHost
	if strings.Contains(normalizedHost, ":") {
		hostHeader = "[" + normalizedHost + "]"
	}
	request := fmt.Sprintf("HEAD / HTTP/1.0\r\nHost: %s\r\nUser-Agent: CicadaPort\r\n\r\n", hostHeader)
	return []byte(request)
}

func buildTargetAddress(host string, port int) string {
	return net.JoinHostPort(normalizeHost(host), strconv.Itoa(port))
}

func hashBytes(content []byte) string {
	digest := sha256.Sum256(content)
	return hex.EncodeToString(digest[:])
}

func phaseTimeoutsFromLegacy(timeout time.Duration) phaseTimeouts {
	return phaseTimeouts{connect: timeout, tlsHandshake: timeout, write: timeout, firstByte: timeout, idleRead: timeout, totalProbe: timeout}
}

func timeoutEvidence(timeouts phaseTimeouts) PhaseTimeoutEvidence {
	return PhaseTimeoutEvidence{
		ConnectMS: timeouts.connect.Milliseconds(), TLSHandshakeMS: timeouts.tlsHandshake.Milliseconds(),
		WriteMS: timeouts.write.Milliseconds(), FirstByteMS: timeouts.firstByte.Milliseconds(),
		IdleReadMS: timeouts.idleRead.Milliseconds(), TotalProbeMS: timeouts.totalProbe.Milliseconds(),
	}
}

func selectProbe(host string, port int) probePlan {
	payload := []byte(nil)
	descriptor := ProbeDescriptor{
		Identifier: "passive-banner", Version: 1, Transport: "tcp", PayloadSHA256: hashBytes(nil),
		MaximumBytes: maxBannerRead, Terminators: []string{}, Invasiveness: "passive",
		AllowedByDefault: true, Parser: "opaque_banner",
	}
	if shouldSendHTTPProbe(port) {
		payload = buildHTTPProbe(host)
		descriptor.Identifier = "http-head"
		descriptor.Invasiveness = "safe"
		descriptor.Parser = "http_headers"
		descriptor.Terminators = []string{"\\r\\n\\r\\n"}
		descriptor.PayloadSHA256 = hashBytes(payload)
	}
	if shouldUseTLS(port) {
		descriptor.Transport = "tls"
	}
	return probePlan{descriptor: descriptor, payload: payload, useTLS: shouldUseTLS(port)}
}

func probeRegistry() []ProbeDescriptor {
	passive := selectProbe("127.0.0.1", 22).descriptor
	safe := selectProbe("127.0.0.1", 80).descriptor
	return []ProbeDescriptor{passive, safe}
}

func newBannerResult(host string, port int) BannerResult {
	return BannerResult{ContractVersion: contractVersion, RecordType: "banner_result", Target: host, Port: port, Status: "empty", Service: serviceName(port), Banner: nil, Error: nil, Source: "go"}
}

func newServiceEvidence(host string, port int, plan probePlan, timeouts phaseTimeouts) ServiceEvidence {
	return ServiceEvidence{
		ContractVersion: serviceEvidenceContractVersion, RecordType: "service_evidence", Target: host,
		Port: port, ServiceHint: serviceName(port), Status: "empty", Confidence: "low", Probe: plan.descriptor,
		Phase: "complete", Encoding: "utf-8-display", PayloadSHA256: hashBytes(nil), Timeouts: timeoutEvidence(timeouts),
	}
}

func tlsVersionName(version uint16) string {
	switch version {
	case tls.VersionTLS12:
		return "TLS1.2"
	case tls.VersionTLS13:
		return "TLS1.3"
	default:
		return fmt.Sprintf("0x%04x", version)
	}
}

func certificateEvidence(state tls.ConnectionState) *TLSEvidence {
	evidence := &TLSEvidence{
		TLSNegotiated: true, CertificatePresent: len(state.PeerCertificates) > 0,
		CertificateVerified: false, VerificationError: "verification_not_performed_observation_mode",
		ProtocolVersion: tlsVersionName(state.Version), CipherSuite: tls.CipherSuiteName(state.CipherSuite),
		ALPN: state.NegotiatedProtocol, ChainLength: len(state.PeerCertificates), SANDNS: []string{}, SANIP: []string{},
	}
	if len(state.PeerCertificates) == 0 {
		return evidence
	}
	certificate := state.PeerCertificates[0]
	evidence.Subject = certificate.Subject.String()
	evidence.Issuer = certificate.Issuer.String()
	evidence.SANDNS = append([]string(nil), certificate.DNSNames...)
	for _, address := range certificate.IPAddresses {
		evidence.SANIP = append(evidence.SANIP, address.String())
	}
	evidence.NotBefore = certificate.NotBefore.UTC().Format(time.RFC3339)
	evidence.NotAfter = certificate.NotAfter.UTC().Format(time.RFC3339)
	evidence.CertificateSHA256 = hashBytes(certificate.Raw)
	return evidence
}

func deadlineFor(ctx context.Context, duration time.Duration) time.Time {
	deadline := time.Now().Add(duration)
	if contextDeadline, ok := ctx.Deadline(); ok && contextDeadline.Before(deadline) {
		return contextDeadline
	}
	return deadline
}

func watchConnection(ctx context.Context, connection net.Conn) func() {
	finished := make(chan struct{})
	go func() {
		select {
		case <-ctx.Done():
			_ = connection.Close()
		case <-finished:
		}
	}()
	return func() { close(finished) }
}

func openProbeConnection(ctx context.Context, host string, port int, plan probePlan, timeouts phaseTimeouts) (net.Conn, *TLSEvidence, string, error) {
	dialer := net.Dialer{Timeout: timeouts.connect}
	rawConnection, err := dialer.DialContext(ctx, "tcp", buildTargetAddress(host, port))
	if err != nil {
		return nil, nil, "connect", err
	}
	if !plan.useTLS {
		return rawConnection, nil, "complete", nil
	}
	if err := rawConnection.SetDeadline(deadlineFor(ctx, timeouts.tlsHandshake)); err != nil {
		_ = rawConnection.Close()
		return nil, nil, "tls_handshake", err
	}
	normalizedHost := normalizeHost(host)
	tlsConfig := &tls.Config{InsecureSkipVerify: true, MinVersion: tls.VersionTLS12}
	if net.ParseIP(normalizedHost) == nil {
		tlsConfig.ServerName = normalizedHost
	}
	tlsConnection := tls.Client(rawConnection, tlsConfig)
	if err := tlsConnection.HandshakeContext(ctx); err != nil {
		_ = rawConnection.Close()
		return nil, nil, "tls_handshake", err
	}
	return tlsConnection, certificateEvidence(tlsConnection.ConnectionState()), "complete", nil
}

func writeAll(connection net.Conn, payload []byte) error {
	for len(payload) > 0 {
		written, err := connection.Write(payload)
		if err != nil {
			return err
		}
		if written == 0 {
			return io.ErrShortWrite
		}
		payload = payload[written:]
	}
	return nil
}

func terminatorIndex(content []byte, terminators []string) int {
	best := -1
	for _, encoded := range terminators {
		terminator := strings.ReplaceAll(encoded, "\\r", "\r")
		terminator = strings.ReplaceAll(terminator, "\\n", "\n")
		if index := bytes.Index(content, []byte(terminator)); index >= 0 {
			end := index + len(terminator)
			if best == -1 || end < best {
				best = end
			}
		}
	}
	return best
}

func readIncremental(ctx context.Context, connection net.Conn, plan probePlan, timeouts phaseTimeouts) ([]byte, int, bool, string, error) {
	buffer := make([]byte, 512)
	captured := make([]byte, 0, min(maxBannerRead, 1024))
	rawLength := 0
	firstRead := true
	for {
		phase := "idle_read"
		duration := timeouts.idleRead
		if firstRead {
			phase = "first_byte"
			duration = timeouts.firstByte
		}
		if err := connection.SetReadDeadline(deadlineFor(ctx, duration)); err != nil {
			return captured, rawLength, false, phase, err
		}
		n, err := connection.Read(buffer)
		if n > 0 {
			firstRead = false
			rawLength += n
			remaining := maxBannerRead + 1 - len(captured)
			if remaining > 0 {
				copyLength := min(n, remaining)
				captured = append(captured, buffer[:copyLength]...)
			}
			if end := terminatorIndex(captured, plan.descriptor.Terminators); end >= 0 {
				captured = captured[:end]
				return captured, rawLength, false, "complete", nil
			}
			if len(captured) > maxBannerRead {
				return captured[:maxBannerRead], rawLength, true, "complete", nil
			}
		}
		if err != nil {
			if errors.Is(err, io.EOF) {
				return captured, rawLength, false, "complete", nil
			}
			if ctx.Err() != nil {
				return captured, rawLength, false, "total_probe", ctx.Err()
			}
			if networkError, ok := err.(net.Error); ok && networkError.Timeout() && len(captured) > 0 {
				return captured, rawLength, false, "idle_read", nil
			}
			return captured, rawLength, false, phase, err
		}
	}
}

func classifyConfidence(plan probePlan, banner string) string {
	if banner == "" {
		return "low"
	}
	if plan.descriptor.Parser == "http_headers" && strings.HasPrefix(strings.ToUpper(banner), "HTTP/") {
		return "high"
	}
	return "medium"
}

func probeServiceWithPlan(parent context.Context, host string, port int, timeout time.Duration, plan probePlan) probeOutcome {
	result := newBannerResult(host, port)
	timeouts := phaseTimeoutsFromLegacy(timeout)
	evidence := newServiceEvidence(host, port, plan, timeouts)
	ctx, cancel := context.WithTimeout(parent, timeouts.totalProbe)
	defer cancel()

	connection, tlsEvidence, phase, err := openProbeConnection(ctx, host, port, plan, timeouts)
	evidence.TLS = tlsEvidence
	if err != nil {
		message := err.Error()
		result.Status = "error"
		result.Error = &message
		evidence.Status = "error"
		evidence.Phase = phase
		evidence.Error = &message
		return probeOutcome{result: result, evidence: evidence}
	}
	defer connection.Close()
	stopWatcher := watchConnection(ctx, connection)
	defer stopWatcher()

	if len(plan.payload) > maxProbePayloadBytes {
		message := "probe payload excede el límite interno"
		result.Status = "error"
		result.Error = &message
		evidence.Status = "error"
		evidence.Phase = "write"
		evidence.Error = &message
		return probeOutcome{result: result, evidence: evidence}
	}
	if len(plan.payload) > 0 {
		if err := connection.SetWriteDeadline(deadlineFor(ctx, timeouts.write)); err != nil {
			message := err.Error()
			result.Status = "error"
			result.Error = &message
			evidence.Status = "error"
			evidence.Phase = "write"
			evidence.Error = &message
			return probeOutcome{result: result, evidence: evidence}
		}
		if err := writeAll(connection, plan.payload); err != nil {
			message := err.Error()
			result.Status = "error"
			result.Error = &message
			evidence.Status = "error"
			evidence.Phase = "write"
			evidence.Error = &message
			return probeOutcome{result: result, evidence: evidence}
		}
	}

	raw, rawLength, truncated, readPhase, readErr := readIncremental(ctx, connection, plan, timeouts)
	evidence.RawLength = rawLength
	evidence.CapturedLength = len(raw)
	evidence.Truncated = truncated
	evidence.PartialBytes = len(raw) > 0 && readErr != nil
	evidence.PayloadSHA256 = hashBytes(raw)
	evidence.Phase = readPhase
	banner := sanitizeBanner(string(raw))
	if banner != "" {
		result.Status = "captured"
		result.Banner = &banner
		evidence.Status = "captured"
		evidence.BannerDisplay = &banner
		evidence.Confidence = classifyConfidence(plan, banner)
	}
	if readErr != nil {
		message := readErr.Error()
		evidence.Error = &message
		if len(raw) == 0 {
			result.Status = "error"
			result.Error = &message
			evidence.Status = "error"
		}
	}
	return probeOutcome{result: result, evidence: evidence}
}

func probeService(ctx context.Context, host string, port int, timeout time.Duration) probeOutcome {
	return probeServiceWithPlan(ctx, host, port, timeout, selectProbe(host, port))
}

func grabBanner(host string, port int, timeout time.Duration) BannerResult {
	return probeService(context.Background(), host, port, timeout).result
}

func streamBanners(parent context.Context, host string, ports []int, timeout time.Duration, sink func(probeOutcome) error) error {
	ctx, cancel := context.WithCancel(parent)
	defer cancel()
	workers := min(maxBannerWorkers, len(ports))
	capacity := min(maxResultChannelCapacity, max(1, workers))
	portsChannel := make(chan int, capacity)
	resultsChannel := make(chan probeOutcome, capacity)
	var waitGroup sync.WaitGroup

	waitGroup.Add(workers)
	for range workers {
		go func() {
			defer waitGroup.Done()
			for {
				select {
				case <-ctx.Done():
					return
				case port, ok := <-portsChannel:
					if !ok {
						return
					}
					outcome := probeService(ctx, host, port, timeout)
					select {
					case resultsChannel <- outcome:
					case <-ctx.Done():
						return
					}
				}
			}
		}()
	}

	go func() {
		defer close(portsChannel)
		for _, port := range ports {
			select {
			case portsChannel <- port:
			case <-ctx.Done():
				return
			}
		}
	}()
	go func() {
		waitGroup.Wait()
		close(resultsChannel)
	}()

	var sinkError error
	for outcome := range resultsChannel {
		if sinkError != nil {
			continue
		}
		if err := sink(outcome); err != nil {
			sinkError = err
			cancel()
		}
	}
	return sinkError
}

func grabBannersObserved(host string, ports []int, timeout time.Duration, events *nativeEventWriter) ([]BannerResult, error) {
	results := make([]BannerResult, 0, len(ports))
	completed := 0
	err := streamBanners(context.Background(), host, ports, timeout, func(outcome probeOutcome) error {
		results = append(results, outcome.result)
		completed++
		port := outcome.result.Port
		return events.emit("port_completed", outcome.result.Status, &port, completed)
	})
	sort.Slice(results, func(i, j int) bool { return results[i].Port < results[j].Port })
	return results, err
}

func grabBanners(host string, ports []int, timeout time.Duration) []BannerResult {
	results, err := grabBannersObserved(host, ports, timeout, nil)
	if err != nil {
		panic(err)
	}
	return results
}

func parseInvocation(args []string) (invocation, error) {
	if len(args) != 1 {
		if len(args) == 0 {
			return 0, fmt.Errorf("uso inválido: se requiere --request-stdin o --help")
		}
		return 0, fmt.Errorf("uso inválido: solo se admite --request-stdin o --help")
	}
	switch args[0] {
	case "--help":
		return invocationHelp, nil
	case "--request-stdin":
		return invocationRequestStdin, nil
	default:
		return 0, fmt.Errorf("uso inválido: solo se admite --request-stdin o --help")
	}
}

func run(args []string, stdin io.Reader, stdout io.Writer, stderr io.Writer) int {
	selected, err := parseInvocation(args)
	if err != nil {
		fmt.Fprintln(stderr, err)
		return 2
	}
	if selected == invocationHelp {
		fmt.Fprint(stdout, helpText)
		return 0
	}
	request, err := parseBannerRequest(stdin)
	if err != nil {
		fmt.Fprintln(stderr, err)
		return 1
	}
	timeout := time.Duration(request.TimeoutMS) * time.Millisecond
	workers := min(maxBannerWorkers, len(request.Ports))
	events, err := nativeEventWriterFromEnv(request.Target, len(request.Ports), workers)
	if err != nil {
		fmt.Fprintln(stderr, err)
		return 1
	}
	if events != nil {
		defer events.close()
	}
	evidenceWriter, err := serviceEvidenceWriterFromEnv()
	if err != nil {
		fmt.Fprintln(stderr, err)
		return 1
	}
	if evidenceWriter != nil {
		defer evidenceWriter.close()
	}
	if err := events.emit("engine_started", "running", nil, 0); err != nil {
		fmt.Fprintln(stderr, err)
		return 1
	}

	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	encoder := json.NewEncoder(stdout)
	completed := 0
	err = streamBanners(ctx, request.Target, request.Ports, timeout, func(outcome probeOutcome) error {
		if err := encoder.Encode(outcome.result); err != nil {
			cancel()
			return fmt.Errorf("Error generando JSONL: %w", err)
		}
		if err := evidenceWriter.emit(outcome.evidence); err != nil {
			cancel()
			return fmt.Errorf("Error generando evidencia v2: %w", err)
		}
		completed++
		port := outcome.result.Port
		if err := events.emit("port_completed", outcome.result.Status, &port, completed); err != nil {
			cancel()
			return err
		}
		return nil
	})
	if err != nil {
		fmt.Fprintln(stderr, err)
		return 1
	}
	if err := events.emit("engine_completed", "success", nil, completed); err != nil {
		fmt.Fprintln(stderr, err)
		return 1
	}
	return 0
}

func main() {
	os.Exit(run(os.Args[1:], os.Stdin, os.Stdout, os.Stderr))
}
