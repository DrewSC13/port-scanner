package main

import (
	"strings"
	"testing"
	"unicode/utf8"
)

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
