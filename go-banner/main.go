package main

import (
	"crypto/tls"
	"encoding/json"
	"fmt"
	"io"
	"net"
	"os"
	"sort"
	"strconv"
	"strings"
	"sync"
	"time"
)

const (
	contractVersion      = 1
	maxBannerRead        = 1024
	maxBannerOutputRunes = 300
	maxBannerWorkers     = 32
	nativeEventFDEnv     = "CICADAPORT_NATIVE_EVENT_FD"
	helpText             = "Usage: go-banner --request-stdin\n\nOpciones:\n  --request-stdin  Lee una solicitud banner_request v1 completa desde stdin.\n  --help           Muestra esta ayuda y termina.\n"
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
type nativeEventWriter struct {
	encoder  *json.Encoder
	file     *os.File
	started  time.Time
	sequence int
	target   string
	total    int
	workers  int
}

func newNativeEventWriter(w io.Writer, target string, total, workers int) *nativeEventWriter {
	return &nativeEventWriter{encoder: json.NewEncoder(w), started: time.Now(), target: target, total: total, workers: workers}
}
func nativeEventWriterFromEnv(target string, total, workers int) (*nativeEventWriter, error) {
	raw := os.Getenv(nativeEventFDEnv)
	if raw == "" {
		return nil, nil
	}
	fd, err := strconv.Atoi(raw)
	if err != nil || fd < 3 {
		return nil, fmt.Errorf("%s debe ser descriptor heredado", nativeEventFDEnv)
	}
	file := os.NewFile(uintptr(fd), "cicadaport-native-event")
	if file == nil {
		return nil, fmt.Errorf("no se pudo abrir native_event")
	}
	w := newNativeEventWriter(file, target, total, workers)
	w.file = file
	return w, nil
}
func (w *nativeEventWriter) close() error {
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

func serviceName(port int) string {
	services := map[int]string{
		20:    "FTP-Data",
		21:    "FTP",
		22:    "SSH",
		23:    "Telnet",
		25:    "SMTP",
		53:    "DNS",
		80:    "HTTP",
		110:   "POP3",
		143:   "IMAP",
		443:   "HTTPS",
		445:   "SMB",
		465:   "SMTPS",
		587:   "SMTP-Submission",
		636:   "LDAPS",
		993:   "IMAPS",
		995:   "POP3S",
		1433:  "MSSQL",
		2376:  "Docker-TLS",
		3306:  "MySQL",
		3389:  "RDP",
		5432:  "PostgreSQL",
		5900:  "VNC",
		6379:  "Redis",
		8000:  "HTTP-Alt",
		8080:  "HTTP-Alt",
		8443:  "HTTPS-Alt",
		9200:  "Elasticsearch",
		27017: "MongoDB",
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
	decoder := json.NewDecoder(reader)
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
		return request, fmt.Errorf(
			"contract_version no compatible: %d; esperado %d",
			request.ContractVersion,
			contractVersion,
		)
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

func sanitizeBanner(raw string) string {
	cleaned := strings.ToValidUTF8(raw, "")
	cleaned = strings.ReplaceAll(cleaned, "\x00", "")
	cleaned = strings.ReplaceAll(cleaned, "\r", " ")
	cleaned = strings.ReplaceAll(cleaned, "\n", " ")
	cleaned = strings.TrimSpace(cleaned)

	runes := []rune(cleaned)
	if len(runes) > maxBannerOutputRunes {
		return string(runes[:maxBannerOutputRunes])
	}

	return cleaned
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

	request := fmt.Sprintf(
		"HEAD / HTTP/1.0\r\nHost: %s\r\nUser-Agent: CicadaPort\r\n\r\n",
		hostHeader,
	)
	return []byte(request)
}

func buildTargetAddress(host string, port int) string {
	return net.JoinHostPort(normalizeHost(host), strconv.Itoa(port))
}

func openBannerConnection(
	host string,
	port int,
	timeout time.Duration,
) (net.Conn, error) {
	address := buildTargetAddress(host, port)
	rawConnection, err := net.DialTimeout("tcp", address, timeout)
	if err != nil {
		return nil, err
	}

	deadline := time.Now().Add(timeout)
	if err := rawConnection.SetDeadline(deadline); err != nil {
		_ = rawConnection.Close()
		return nil, err
	}

	if !shouldUseTLS(port) {
		return rawConnection, nil
	}

	normalizedHost := normalizeHost(host)
	tlsConfig := &tls.Config{
		InsecureSkipVerify: true,
		MinVersion:         tls.VersionTLS12,
	}

	if net.ParseIP(normalizedHost) == nil {
		tlsConfig.ServerName = normalizedHost
	}

	tlsConnection := tls.Client(rawConnection, tlsConfig)
	if err := tlsConnection.Handshake(); err != nil {
		_ = rawConnection.Close()
		return nil, err
	}

	return tlsConnection, nil
}

func newBannerResult(host string, port int) BannerResult {
	return BannerResult{
		ContractVersion: contractVersion,
		RecordType:      "banner_result",
		Target:          host,
		Port:            port,
		Status:          "empty",
		Service:         serviceName(port),
		Banner:          nil,
		Error:           nil,
		Source:          "go",
	}
}

func grabBanner(host string, port int, timeout time.Duration) BannerResult {
	result := newBannerResult(host, port)

	conn, err := openBannerConnection(host, port, timeout)
	if err != nil {
		message := err.Error()
		result.Status = "error"
		result.Error = &message
		return result
	}
	defer conn.Close()

	if shouldSendHTTPProbe(port) {
		if _, err := conn.Write(buildHTTPProbe(host)); err != nil {
			message := err.Error()
			result.Status = "error"
			result.Error = &message
			return result
		}
	}

	buffer := make([]byte, maxBannerRead)
	n, err := conn.Read(buffer)

	if n > 0 {
		banner := sanitizeBanner(string(buffer[:n]))
		if banner != "" {
			result.Status = "captured"
			result.Banner = &banner
		}
	}

	if err != nil && n == 0 {
		message := err.Error()
		result.Status = "error"
		result.Error = &message
		return result
	}

	return result
}

func grabBannersObserved(host string, ports []int, timeout time.Duration, events *nativeEventWriter) ([]BannerResult, error) {
	results := make([]BannerResult, 0, len(ports))
	resultsChannel := make(chan BannerResult, len(ports))
	portsChannel := make(chan int, len(ports))
	var wg sync.WaitGroup
	for _, port := range ports {
		portsChannel <- port
	}
	close(portsChannel)
	workerCount := min(maxBannerWorkers, len(ports))
	for range workerCount {
		wg.Add(1)
		go func() {
			defer wg.Done()
			for p := range portsChannel {
				resultsChannel <- grabBanner(host, p, timeout)
			}
		}()
	}
	go func() { wg.Wait(); close(resultsChannel) }()
	completed := 0
	var eventErr error
	for result := range resultsChannel {
		results = append(results, result)
		completed++
		if eventErr == nil {
			p := result.Port
			eventErr = events.emit("port_completed", result.Status, &p, completed)
		}
	}
	sort.Slice(results, func(i, j int) bool { return results[i].Port < results[j].Port })
	if eventErr != nil {
		return nil, eventErr
	}
	return results, nil
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

func run(
	args []string,
	stdin io.Reader,
	stdout io.Writer,
	stderr io.Writer,
) int {
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
	if err := events.emit("engine_started", "running", nil, 0); err != nil {
		fmt.Fprintln(stderr, err)
		return 1
	}
	results, err := grabBannersObserved(request.Target, request.Ports, timeout, events)
	if err != nil {
		fmt.Fprintln(stderr, err)
		return 1
	}
	if err := events.emit("engine_completed", "success", nil, len(results)); err != nil {
		fmt.Fprintln(stderr, err)
		return 1
	}
	encoder := json.NewEncoder(stdout)
	for _, result := range results {
		if err := encoder.Encode(result); err != nil {
			fmt.Fprintln(stderr, "Error generando JSONL:", err)
			return 1
		}
	}

	return 0
}

func main() {
	os.Exit(run(os.Args[1:], os.Stdin, os.Stdout, os.Stderr))
}
