package main

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"io"
	"net"
	"net/http"
	"net/http/httptest"
	"strconv"
	"strings"
	"testing"
	"time"
	"unicode/utf8"
)

type panicReader struct{}

func (panicReader) Read([]byte) (int, error) {
	panic("stdin no debe leerse para ayuda o uso inválido")
}

func TestOnlyContractualProcessInvocationsAreAccepted(t *testing.T) {
	t.Parallel()

	selected, err := parseInvocation([]string{"--request-stdin"})
	if err != nil || selected != invocationRequestStdin {
		t.Fatalf("request invocation = (%v, %v); want request-stdin", selected, err)
	}

	selected, err = parseInvocation([]string{"--help"})
	if err != nil || selected != invocationHelp {
		t.Fatalf("help invocation = (%v, %v); want help", selected, err)
	}

	invalidCases := [][]string{
		nil,
		{"--host", "127.0.0.1"},
		{"--ports", "80"},
		{"--timeout", "1"},
		{"--unknown"},
		{"positional"},
		{"-request-stdin"},
		{"--request-stdin", "--help"},
	}
	for _, args := range invalidCases {
		if _, err := parseInvocation(args); err == nil {
			t.Fatalf("parseInvocation accepted invalid args: %v", args)
		}
	}
}

func TestHelpAndInvalidUsageDoNotReadStdin(t *testing.T) {
	t.Parallel()

	var stdout bytes.Buffer
	var stderr bytes.Buffer
	if code := run([]string{"--help"}, panicReader{}, &stdout, &stderr); code != 0 {
		t.Fatalf("help exit code = %d; want 0", code)
	}
	if stderr.Len() != 0 {
		t.Fatalf("help wrote stderr: %q", stderr.String())
	}
	if !strings.Contains(stdout.String(), "Usage: go-banner --request-stdin") {
		t.Fatalf("unexpected help: %q", stdout.String())
	}
	for _, historical := range []string{"--host", "--ports", "--timeout"} {
		if strings.Contains(stdout.String(), historical) {
			t.Fatalf("help exposes historical argument %s", historical)
		}
	}

	stdout.Reset()
	stderr.Reset()
	if code := run([]string{"--host", "127.0.0.1"}, panicReader{}, &stdout, &stderr); code != 2 {
		t.Fatalf("invalid usage exit code = %d; want 2", code)
	}
	if stdout.Len() != 0 || stderr.Len() == 0 {
		t.Fatalf("invalid usage channels = stdout %q, stderr %q", stdout.String(), stderr.String())
	}
}

func TestInvalidContractReturnsExecutionFailure(t *testing.T) {
	t.Parallel()

	var stdout bytes.Buffer
	var stderr bytes.Buffer
	code := run(
		[]string{"--request-stdin"},
		strings.NewReader("{}\n"),
		&stdout,
		&stderr,
	)
	if code != 1 {
		t.Fatalf("invalid contract exit code = %d; want 1", code)
	}
	if stdout.Len() != 0 || stderr.Len() == 0 {
		t.Fatalf("invalid contract channels = stdout %q, stderr %q", stdout.String(), stderr.String())
	}
}

func TestParseVersionedBannerRequest(t *testing.T) {
	t.Parallel()

	request, err := parseBannerRequest(strings.NewReader(
		`{"contract_version":1,"record_type":"banner_request","target":"127.0.0.1","ports":[443,80,443],"timeout_ms":250}`,
	))
	if err != nil {
		t.Fatalf("parseBannerRequest returned an error: %v", err)
	}

	if request.Target != "127.0.0.1" {
		t.Fatalf("target = %q; want 127.0.0.1", request.Target)
	}
	if len(request.Ports) != 2 || request.Ports[0] != 80 || request.Ports[1] != 443 {
		t.Fatalf("ports = %v; want [80 443]", request.Ports)
	}
	if request.TimeoutMS != 250 {
		t.Fatalf("timeout_ms = %d; want 250", request.TimeoutMS)
	}
}

func TestRejectsIncompleteOrExtendedBannerRequest(t *testing.T) {
	t.Parallel()

	cases := []string{
		`{"contract_version":1,"record_type":"banner_request","target":"127.0.0.1","ports":[80]}`,
		`{"contract_version":1,"record_type":"banner_request","target":"127.0.0.1","ports":[80],"timeout_ms":250,"unexpected":true}`,
		`{"contract_version":2,"record_type":"banner_request","target":"127.0.0.1","ports":[80],"timeout_ms":250}`,
	}

	for _, rawRequest := range cases {
		if _, err := parseBannerRequest(strings.NewReader(rawRequest)); err == nil {
			t.Fatalf("expected request to be rejected: %s", rawRequest)
		}
	}
}

func TestNewBannerResultCarriesStableContractIdentity(t *testing.T) {
	t.Parallel()

	result := newBannerResult("127.0.0.1", 8080)

	if result.ContractVersion != contractVersion {
		t.Fatalf(
			"contract_version = %d; want %d",
			result.ContractVersion,
			contractVersion,
		)
	}
	if result.RecordType != "banner_result" || result.Source != "go" {
		t.Fatalf("unexpected result identity: %#v", result)
	}
	if result.Status != "empty" || result.Banner != nil || result.Error != nil {
		t.Fatalf("unexpected initial result state: %#v", result)
	}
}

func TestBuildTargetAddress(t *testing.T) {
	t.Parallel()

	tests := []struct {
		name string
		host string
		port int
		want string
	}{
		{
			name: "IPv4",
			host: "127.0.0.1",
			port: 443,
			want: "127.0.0.1:443",
		},
		{
			name: "hostname",
			host: "localhost",
			port: 8080,
			want: "localhost:8080",
		},
		{
			name: "IPv6",
			host: "::1",
			port: 22,
			want: "[::1]:22",
		},
		{
			name: "bracketed IPv6",
			host: "[2001:db8::10]",
			port: 8443,
			want: "[2001:db8::10]:8443",
		},
	}

	for _, test := range tests {
		test := test

		t.Run(test.name, func(t *testing.T) {
			t.Parallel()

			got := buildTargetAddress(test.host, test.port)
			if got != test.want {
				t.Fatalf("buildTargetAddress(%q, %d) = %q; want %q", test.host, test.port, got, test.want)
			}
		})
	}
}

func TestProbePolicy(t *testing.T) {
	t.Parallel()

	for _, port := range []int{80, 443, 8000, 8080, 8443, 9200} {
		if !shouldSendHTTPProbe(port) {
			t.Fatalf("expected HTTP probe to be enabled for port %d", port)
		}
	}

	for _, port := range []int{21, 22, 25, 3306, 6379} {
		if shouldSendHTTPProbe(port) {
			t.Fatalf("expected passive-only banner read for port %d", port)
		}
	}

	for _, port := range []int{443, 465, 636, 993, 995, 2376, 8443} {
		if !shouldUseTLS(port) {
			t.Fatalf("expected TLS to be enabled for port %d", port)
		}
	}

	for _, port := range []int{80, 8080, 9200} {
		if shouldUseTLS(port) {
			t.Fatalf("did not expect TLS for port %d", port)
		}
	}
}

func TestBuildHTTPProbe(t *testing.T) {
	t.Parallel()

	got := string(buildHTTPProbe("::1"))
	want := "HEAD / HTTP/1.0\r\nHost: [::1]\r\nUser-Agent: CicadaPort\r\n\r\n"

	if got != want {
		t.Fatalf("buildHTTPProbe returned %q; want %q", got, want)
	}
}

func TestSanitizeHostileBanner(t *testing.T) {
	t.Parallel()

	rawBytes := append(
		[]byte("\x00=2+5\r\n<script>alert(1)</script>"),
		0xff,
		0x00,
	)
	raw := string(rawBytes)
	want := "=2+5  <script>alert(1)</script>"

	if got := sanitizeBanner(raw); got != want {
		t.Fatalf("sanitizeBanner returned %q; want %q", got, want)
	}
}

func TestSanitizeBannerLimitsRunesWithoutBreakingUTF8(t *testing.T) {
	t.Parallel()

	got := sanitizeBanner(strings.Repeat("é", maxBannerOutputRunes+1))

	if !utf8.ValidString(got) {
		t.Fatal("sanitizeBanner returned invalid UTF-8")
	}

	if utf8.RuneCountInString(got) != maxBannerOutputRunes {
		t.Fatalf(
			"sanitizeBanner returned %d runes; want %d",
			utf8.RuneCountInString(got),
			maxBannerOutputRunes,
		)
	}
}

func TestNativeEventWriterV1(t *testing.T) {
	var out bytes.Buffer
	w := newNativeEventWriter(&out, "127.0.0.1", 1, 1)
	p := 80
	if err := w.emit("port_completed", "captured", &p, 1); err != nil {
		t.Fatal(err)
	}
	var e NativeEvent
	if err := json.Unmarshal(out.Bytes(), &e); err != nil {
		t.Fatal(err)
	}
	if e.RecordType != "native_event" || e.Engine != "go" || e.Port == nil || *e.Port != 80 {
		t.Fatalf("evento inválido: %+v", e)
	}
}

func TestProbeRegistryOnlyEnablesPassiveAndSafe(t *testing.T) {
	t.Parallel()

	registry := probeRegistry()
	if len(registry) != 2 {
		t.Fatalf("probe registry length = %d; want 2", len(registry))
	}
	seen := map[string]bool{}
	for _, probe := range registry {
		if !probe.AllowedByDefault {
			t.Fatalf("default probe %q is disabled", probe.Identifier)
		}
		if probe.Invasiveness != "passive" && probe.Invasiveness != "safe" {
			t.Fatalf("unexpected invasiveness %q", probe.Invasiveness)
		}
		if probe.Version < 1 || len(probe.PayloadSHA256) != 64 {
			t.Fatalf("unversioned or unhashed probe: %+v", probe)
		}
		seen[probe.Invasiveness] = true
	}
	if !seen["passive"] || !seen["safe"] {
		t.Fatalf("registry does not contain passive and safe probes: %+v", registry)
	}
}

func TestSanitizeBannerRemovesTerminalAndBidiControls(t *testing.T) {
	t.Parallel()

	raw := "SSH\x1b]0;owned\x07\x1b[31m-red-\x1b[0m\u202e\u2066safe\u200b\ufeff"
	got := sanitizeBanner(raw)
	if got != "SSH-red-safe" {
		t.Fatalf("sanitizeBanner returned %q; want %q", got, "SSH-red-safe")
	}
	if !utf8.ValidString(got) {
		t.Fatal("sanitized banner is not valid UTF-8")
	}
}

func TestReadIncrementalIsBoundedAndHashed(t *testing.T) {
	t.Parallel()

	client, server := net.Pipe()
	defer client.Close()
	payload := bytes.Repeat([]byte("A"), maxBannerRead+1024)
	go func() {
		defer server.Close()
		_, _ = server.Write(payload)
	}()
	plan := probePlan{descriptor: ProbeDescriptor{MaximumBytes: maxBannerRead}}
	timeouts := phaseTimeoutsFromLegacy(time.Second)
	captured, rawLength, truncated, phase, err := readIncremental(
		context.Background(), client, plan, timeouts,
	)
	if err != nil {
		t.Fatalf("readIncremental returned error: %v", err)
	}
	if phase != "complete" || !truncated {
		t.Fatalf("phase/truncated = %q/%v; want complete/true", phase, truncated)
	}
	if len(captured) != maxBannerRead || rawLength <= maxBannerRead {
		t.Fatalf("captured/raw = %d/%d", len(captured), rawLength)
	}
	if hashBytes(captured) != hashBytes(bytes.Repeat([]byte("A"), maxBannerRead)) {
		t.Fatal("captured payload hash is not deterministic")
	}
}

func TestServiceEvidenceWriterV2(t *testing.T) {
	t.Parallel()

	var out bytes.Buffer
	writer := &serviceEvidenceWriter{encoder: json.NewEncoder(&out)}
	plan := selectProbe("127.0.0.1", 80)
	evidence := newServiceEvidence(
		"127.0.0.1", 80, plan, phaseTimeoutsFromLegacy(250*time.Millisecond),
	)
	if err := writer.emit(evidence); err != nil {
		t.Fatal(err)
	}
	var decoded ServiceEvidence
	if err := json.Unmarshal(out.Bytes(), &decoded); err != nil {
		t.Fatal(err)
	}
	if decoded.ContractVersion != 2 || decoded.RecordType != "service_evidence" {
		t.Fatalf("unexpected evidence identity: %+v", decoded)
	}
	if decoded.Probe.Invasiveness != "safe" || !decoded.Probe.AllowedByDefault {
		t.Fatalf("unexpected probe evidence: %+v", decoded.Probe)
	}
}

func TestStreamingEmitsFastResultBeforeSlowEndpoint(t *testing.T) {
	t.Parallel()

	fastPort, fastDone := startBannerListener(t, 0, "FAST\r\n")
	slowPort, slowDone := startBannerListener(t, 500*time.Millisecond, "SLOW\r\n")
	defer fastDone()
	defer slowDone()

	started := time.Now()
	first := make(chan probeOutcome, 1)
	err := streamBanners(
		context.Background(), "127.0.0.1", []int{slowPort, fastPort}, time.Second,
		func(outcome probeOutcome) error {
			select {
			case first <- outcome:
			default:
			}
			return nil
		},
	)
	if err != nil {
		t.Fatal(err)
	}
	outcome := <-first
	if outcome.result.Port != fastPort {
		t.Fatalf("first streamed port = %d; want fast port %d", outcome.result.Port, fastPort)
	}
	if elapsed := time.Since(started); elapsed < 450*time.Millisecond {
		// The full call waits for every result. The assertion above proves ordering;
		// this check confirms the slow endpoint actually exercised delayed completion.
		t.Fatalf("slow endpoint did not delay completion: %v", elapsed)
	}
}

func TestSinkFailureCancelsOutstandingConnections(t *testing.T) {
	t.Parallel()

	fastPort, fastDone := startBannerListener(t, 0, "FAST\r\n")
	hangingPort, hangingDone := startHangingListener(t)
	defer fastDone()
	defer hangingDone()

	started := time.Now()
	expected := errors.New("downstream closed")
	err := streamBanners(
		context.Background(), "127.0.0.1", []int{hangingPort, fastPort}, 5*time.Second,
		func(outcome probeOutcome) error {
			if outcome.result.Port == fastPort {
				return expected
			}
			return nil
		},
	)
	if !errors.Is(err, expected) {
		t.Fatalf("streamBanners error = %v; want %v", err, expected)
	}
	if elapsed := time.Since(started); elapsed > time.Second {
		t.Fatalf("cancellation took %v; want <= 1s", elapsed)
	}
}

func TestTLSEvidenceNeverClaimsUnverifiedCertificateIsVerified(t *testing.T) {
	t.Parallel()

	server := httptest.NewTLSServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		w.Header().Set("Server", "CicadaPort-Test")
		w.WriteHeader(http.StatusNoContent)
	}))
	defer server.Close()

	host, portText, err := net.SplitHostPort(strings.TrimPrefix(server.URL, "https://"))
	if err != nil {
		t.Fatal(err)
	}
	port, err := strconv.Atoi(portText)
	if err != nil {
		t.Fatal(err)
	}
	plan := selectProbe(host, 443)
	plan.payload = buildHTTPProbe(host)
	plan.useTLS = true
	outcome := probeServiceWithPlan(context.Background(), host, port, 2*time.Second, plan)
	if outcome.evidence.TLS == nil || !outcome.evidence.TLS.TLSNegotiated {
		t.Fatalf("TLS evidence missing: %+v", outcome.evidence)
	}
	if !outcome.evidence.TLS.CertificatePresent || outcome.evidence.TLS.CertificateVerified {
		t.Fatalf("certificate truthfulness violated: %+v", outcome.evidence.TLS)
	}
	if outcome.evidence.TLS.VerificationError != "verification_not_performed_observation_mode" {
		t.Fatalf("verification error = %q", outcome.evidence.TLS.VerificationError)
	}
	if len(outcome.evidence.TLS.CertificateSHA256) != 64 {
		t.Fatalf("certificate hash = %q", outcome.evidence.TLS.CertificateSHA256)
	}
}

func startBannerListener(t *testing.T, delay time.Duration, banner string) (int, func()) {
	t.Helper()
	listener, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	done := make(chan struct{})
	go func() {
		defer close(done)
		connection, err := listener.Accept()
		if err != nil {
			return
		}
		defer connection.Close()
		if delay > 0 {
			time.Sleep(delay)
		}
		_, _ = io.WriteString(connection, banner)
	}()
	return listener.Addr().(*net.TCPAddr).Port, func() {
		_ = listener.Close()
		select {
		case <-done:
		case <-time.After(2 * time.Second):
		}
	}
}

func startHangingListener(t *testing.T) (int, func()) {
	t.Helper()
	listener, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	done := make(chan struct{})
	go func() {
		defer close(done)
		connection, err := listener.Accept()
		if err != nil {
			return
		}
		defer connection.Close()
		buffer := make([]byte, 1)
		_, _ = connection.Read(buffer)
	}()
	return listener.Addr().(*net.TCPAddr).Port, func() {
		_ = listener.Close()
		select {
		case <-done:
		case <-time.After(2 * time.Second):
		}
	}
}
