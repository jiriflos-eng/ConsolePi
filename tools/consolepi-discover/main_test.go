package main

import (
	"bytes"
	"encoding/binary"
	"encoding/json"
	"net"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

func TestParseConsolePiAnswer(t *testing.T) {
	instance := "lab-consolepi._consolepi._tcp.local"
	target := "lab-consolepi.local"
	packet := make([]byte, 12)
	binary.BigEndian.PutUint16(packet[6:8], 4)
	packet = append(packet, resourceRecord(serviceType, 12, encodeName(instance))...)
	srv := append([]byte{0, 0, 0, 0, 1, 187}, encodeName(target)...)
	packet = append(packet, resourceRecord(instance, 33, srv)...)
	txt := append(txtRecord("hostname", "CPI1U-KLI"), txtRecord("display_name", "NAKIT UL - KLI")...)
	txt = append(txt, txtRecord("location", "Serverovna, rack R14")...)
	packet = append(packet, resourceRecord(instance, 16, txt)...)
	packet = append(packet, resourceRecord(target, 1, []byte{192, 168, 44, 25})...)

	state := records{map[string]string{}, map[string]srvRecord{}, map[string][]net.IP{}, map[string]serviceIdentity{}}
	parseMessage(packet, &state)
	devices := state.devices()
	if len(devices) != 1 {
		t.Fatalf("devices = %#v, want one device", devices)
	}
	if devices[0].IPv4 != "192.168.44.25" || devices[0].HTTPS != "https://192.168.44.25/" {
		t.Fatalf("unexpected device: %#v", devices[0])
	}
	if devices[0].Hostname != "CPI1U-KLI" || devices[0].DisplayName != "NAKIT UL - KLI" || devices[0].Location != "Serverovna, rack R14" {
		t.Fatalf("missing DNS-SD identity: %#v", devices[0])
	}
}

func txtRecord(key, value string) []byte {
	record := []byte(key + "=" + value)
	return append([]byte{byte(len(record))}, record...)
}

func TestGUIHandlerServesLoopbackPageAndDevices(t *testing.T) {
	handler := guiHandler(time.Second, func(timeout time.Duration) ([]device, error) {
		if timeout != time.Second {
			t.Fatalf("timeout = %s", timeout)
		}
		return []device{{Name: "test ConsolePi", IPv4: "192.0.2.10", HTTPS: "https://192.0.2.10/", SSH: "ssh consolepi@192.0.2.10"}}, nil
	})
	page := httptest.NewRecorder()
	handler.ServeHTTP(page, httptest.NewRequest(http.MethodGet, "/", nil))
	if page.Code != http.StatusOK || page.Header().Get("Content-Security-Policy") == "" {
		t.Fatalf("unexpected GUI page response: %#v", page.Result())
	}
	api := httptest.NewRecorder()
	handler.ServeHTTP(api, httptest.NewRequest(http.MethodGet, "/api/devices", nil))
	if api.Code != http.StatusOK || api.Header().Get("Cache-Control") != "no-store" {
		t.Fatalf("unexpected API response: %#v", api.Result())
	}
	var devices []device
	if err := json.Unmarshal(api.Body.Bytes(), &devices); err != nil || len(devices) != 1 || devices[0].IPv4 != "192.0.2.10" {
		t.Fatalf("invalid API body %q: %v", api.Body.String(), err)
	}
	method := httptest.NewRecorder()
	handler.ServeHTTP(method, httptest.NewRequest(http.MethodPost, "/api/devices", nil))
	if method.Code != http.StatusMethodNotAllowed {
		t.Fatalf("POST status = %d", method.Code)
	}
}

func TestGUIKeyGenerationRequiresToken(t *testing.T) {
	handler := guiHandlerWithKeyGenerator(time.Second, func(time.Duration) ([]device, error) { return nil, nil }, "test-token", func(name string) (generatedKey, error) {
		if name != "consolepi-admin" {
			t.Fatalf("key name = %q", name)
		}
		return generatedKey{PrivatePath: "/home/user/.ssh/consolepi-admin", PublicPath: "/home/user/.ssh/consolepi-admin.pub", PublicKey: "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAITest ConsolePi"}, nil
	})
	body := []byte(`{"name":"consolepi-admin"}`)
	denied := httptest.NewRecorder()
	handler.ServeHTTP(denied, httptest.NewRequest(http.MethodPost, "/api/generate-key", bytes.NewReader(body)))
	if denied.Code != http.StatusForbidden {
		t.Fatalf("missing token status = %d", denied.Code)
	}
	accepted := httptest.NewRecorder()
	request := httptest.NewRequest(http.MethodPost, "/api/generate-key", bytes.NewReader(body))
	request.Header.Set("X-ConsolePi-Keygen-Token", "test-token")
	handler.ServeHTTP(accepted, request)
	if accepted.Code != http.StatusOK || !strings.Contains(accepted.Body.String(), "ssh-ed25519") {
		t.Fatalf("key generation response = %d %q", accepted.Code, accepted.Body.String())
	}
}

func TestGenerateInstallationKeyDoesNotOverwrite(t *testing.T) {
	home := t.TempDir()
	key, err := generateInstallationKeyIn(home, "consolepi-admin")
	if err != nil {
		t.Fatal(err)
	}
	info, err := os.Stat(key.PrivatePath)
	if err != nil || info.Mode().Perm() != 0600 {
		t.Fatalf("private key mode = %v, err = %v", info.Mode(), err)
	}
	if !strings.HasPrefix(key.PublicKey, "ssh-ed25519 ") {
		t.Fatalf("public key = %q", key.PublicKey)
	}
	if _, err := generateInstallationKeyIn(home, "consolepi-admin"); err == nil {
		t.Fatal("second key generation unexpectedly overwrote the key")
	}
	if _, err := os.Stat(filepath.Join(home, ".ssh", "consolepi-admin.pub")); err != nil {
		t.Fatal(err)
	}
}

func resourceRecord(owner string, kind uint16, rdata []byte) []byte {
	record := encodeName(owner)
	header := make([]byte, 10)
	binary.BigEndian.PutUint16(header[0:2], kind)
	binary.BigEndian.PutUint16(header[2:4], 1)
	binary.BigEndian.PutUint32(header[4:8], 120)
	binary.BigEndian.PutUint16(header[8:10], uint16(len(rdata)))
	return append(append(record, header...), rdata...)
}
