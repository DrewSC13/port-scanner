package main

import "testing"

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
