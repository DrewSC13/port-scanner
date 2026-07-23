package main

import (
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
		993:   "IMAPS",
		995:   "POP3S",
		1433:  "MSSQL",
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
	cleaned := strings.ReplaceAll(raw, "\x00", "")
	cleaned = strings.ReplaceAll(cleaned, "\r", " ")
	cleaned = strings.ReplaceAll(cleaned, "\n", " ")
	cleaned = strings.TrimSpace(cleaned)

	if len(cleaned) > 300 {
		return cleaned[:300]
	}

	return cleaned
}

func shouldSendHTTPProbe(port int) bool {
	switch port {
	case 80, 8000, 8080, 8443, 9200:
		return true
	default:
		return false
	}
}

func buildTargetAddress(host string, port int) string {
	normalizedHost := strings.TrimSpace(host)
	normalizedHost = strings.TrimPrefix(normalizedHost, "[")
	normalizedHost = strings.TrimSuffix(normalizedHost, "]")

	return net.JoinHostPort(normalizedHost, strconv.Itoa(port))
}

func grabBanner(host string, port int, timeout time.Duration) BannerResult {
	address := buildTargetAddress(host, port)

	result := BannerResult{
		Port:    port,
		Banner:  "",
		Service: serviceName(port),
	}

	conn, err := net.DialTimeout("tcp", address, timeout)
	if err != nil {
		result.Error = err.Error()
		return result
	}
	defer conn.Close()

	deadline := time.Now().Add(timeout)
	if err := conn.SetDeadline(deadline); err != nil {
		result.Error = err.Error()
		return result
	}

	if shouldSendHTTPProbe(port) {
		request := fmt.Sprintf("HEAD / HTTP/1.0\r\nHost: %s\r\nUser-Agent: PortScanner-Pro-Go\r\n\r\n", host)
		_, _ = conn.Write([]byte(request))
	}

	buffer := make([]byte, 1024)
	n, err := conn.Read(buffer)

	if err != nil {
		result.Error = err.Error()
		return result
	}

	result.Banner = sanitizeBanner(string(buffer[:n]))
	return result
}

func grabBanners(host string, ports []int, timeout time.Duration) []BannerResult {
	results := make([]BannerResult, 0, len(ports))
	resultsChannel := make(chan BannerResult, len(ports))

	var wg sync.WaitGroup

	for _, port := range ports {
		wg.Add(1)

		go func(currentPort int) {
			defer wg.Done()
			resultsChannel <- grabBanner(host, currentPort, timeout)
		}(port)
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
