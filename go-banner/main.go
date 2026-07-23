package main

import (
	"crypto/tls"
	"encoding/json"
	"flag"
	"fmt"
	"net"
	"os"
	"sort"
	"strconv"
	"strings"
	"sync"
	"time"
)

const (
	maxBannerRead        = 1024
	maxBannerOutputRunes = 300
	maxBannerWorkers     = 32
)

type BannerResult struct {
	Port    int    `json:"port"`
	Banner  string `json:"banner"`
	Service string `json:"service"`
	Error   string `json:"error,omitempty"`
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

func parsePorts(rawPorts string) ([]int, error) {
	parts := strings.Split(rawPorts, ",")
	portsMap := make(map[int]bool)

	for _, part := range parts {
		trimmed := strings.TrimSpace(part)

		if trimmed == "" {
			continue
		}

		port, err := strconv.Atoi(trimmed)
		if err != nil {
			return nil, fmt.Errorf("puerto inválido: %s", trimmed)
		}

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

func grabBanner(host string, port int, timeout time.Duration) BannerResult {
	result := BannerResult{
		Port:    port,
		Banner:  "",
		Service: serviceName(port),
	}

	conn, err := openBannerConnection(host, port, timeout)
	if err != nil {
		result.Error = err.Error()
		return result
	}
	defer conn.Close()

	if shouldSendHTTPProbe(port) {
		if _, err := conn.Write(buildHTTPProbe(host)); err != nil {
			result.Error = err.Error()
			return result
		}
	}

	buffer := make([]byte, maxBannerRead)
	n, err := conn.Read(buffer)

	if n > 0 {
		result.Banner = sanitizeBanner(string(buffer[:n]))
	}

	if err != nil && n == 0 {
		result.Error = err.Error()
		return result
	}

	return result
}

func grabBanners(host string, ports []int, timeout time.Duration) []BannerResult {
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

			for currentPort := range portsChannel {
				resultsChannel <- grabBanner(host, currentPort, timeout)
			}
		}()
	}

	wg.Wait()
	close(resultsChannel)

	for result := range resultsChannel {
		results = append(results, result)
	}

	sort.Slice(results, func(i, j int) bool {
		return results[i].Port < results[j].Port
	})

	return results
}

func main() {
	host := flag.String("host", "", "Host objetivo")
	rawPorts := flag.String("ports", "", "Lista de puertos separados por coma")
	timeoutSeconds := flag.Float64("timeout", 3.0, "Timeout por conexión en segundos")

	flag.Parse()

	if *host == "" {
		fmt.Fprintln(os.Stderr, "Falta argumento requerido: --host")
		os.Exit(1)
	}

	if *rawPorts == "" {
		fmt.Fprintln(os.Stderr, "Falta argumento requerido: --ports")
		os.Exit(1)
	}

	if *timeoutSeconds <= 0 {
		fmt.Fprintln(os.Stderr, "Timeout debe ser mayor a 0")
		os.Exit(1)
	}

	ports, err := parsePorts(*rawPorts)
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}

	timeout := time.Duration(*timeoutSeconds * float64(time.Second))
	results := grabBanners(*host, ports, timeout)

	jsonOutput, err := json.Marshal(results)
	if err != nil {
		fmt.Fprintln(os.Stderr, "Error generando JSON:", err)
		os.Exit(1)
	}

	fmt.Println(string(jsonOutput))
}
