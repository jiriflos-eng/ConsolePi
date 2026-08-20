// consolepi-discover finds ConsolePi Plus devices advertised on the local L2 network.
// It deliberately uses mDNS instead of a subnet scan: it is read-only, fast and
// never probes unrelated hosts.  mDNS multicast does not cross routed networks.
package main

import (
	"crypto/rand"
	"encoding/binary"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"io"
	"net"
	"net/http"
	"os"
	"os/exec"
	"path/filepath"
	"regexp"
	"runtime"
	"sort"
	"strings"
	"time"
)

const (
	serviceType = "_consolepi._tcp.local"
	mdnsAddress = "224.0.0.251:5353"
)

type device struct {
	Name        string `json:"name"`
	Hostname    string `json:"hostname,omitempty"`
	DisplayName string `json:"display_name,omitempty"`
	Location    string `json:"location,omitempty"`
	IPv4        string `json:"ipv4"`
	HTTPS       string `json:"https"`
	SSH         string `json:"ssh"`
}

type records struct {
	instances map[string]string
	targets   map[string]srvRecord
	addresses map[string][]net.IP
	identity  map[string]serviceIdentity
}

type srvRecord struct {
	target string
	port   uint16
}

type serviceIdentity struct {
	hostname    string
	displayName string
	location    string
}

type generatedKey struct {
	PrivatePath string `json:"private_path"`
	PublicPath  string `json:"public_path"`
	PublicKey   string `json:"public_key"`
}

var keyNamePattern = regexp.MustCompile(`^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$`)

func main() {
	flag.Usage = printUsage
	timeout := flag.Duration("timeout", 4*time.Second, "how long to listen for mDNS replies")
	jsonOutput := flag.Bool("json", false, "write devices as JSON")
	openWeb := flag.Bool("open", false, "open HTTPS when exactly one device is found")
	guiMode := flag.Bool("gui", false, "open a local graphical discovery page")
	shellMode := flag.Bool("shell", false, "write discovery results only to the terminal")
	generateKeyName := flag.String("generate-key", "", "create a local Ed25519 installation key in ~/.ssh")
	flag.Parse()
	if *generateKeyName != "" {
		key, err := generateInstallationKey(*generateKeyName)
		if err != nil {
			fatal(err.Error())
		}
		fmt.Printf("Private key: %s\nPublic key:  %s\n\nPaste this public key into Raspberry Pi Imager:\n%s\n", key.PrivatePath, key.PublicPath, key.PublicKey)
		return
	}
	if *timeout <= 0 || *timeout > 30*time.Second {
		fatal("--timeout must be between 1ms and 30s")
	}
	if *guiMode && *shellMode {
		fatal("--gui and --shell cannot be used together")
	}
	// The portable application is GUI-first.  Machine-readable and explicit
	// non-interactive operations remain terminal-oriented without --shell.
	if !*shellMode && !*jsonOutput && !*openWeb {
		if err := runGUI(*timeout); err != nil {
			fatal(err.Error())
		}
		return
	}

	devices, err := discover(*timeout)
	if err != nil {
		fatal(err.Error())
	}
	if *jsonOutput {
		data, err := json.MarshalIndent(devices, "", "  ")
		if err != nil {
			fatal(err.Error())
		}
		fmt.Println(string(data))
	} else if len(devices) == 0 {
		fmt.Println("No ConsolePi Plus device found on this local network.")
		fmt.Println("mDNS does not cross routed networks; use a known IP or an mDNS reflector.")
	} else {
		for _, d := range devices {
			fmt.Printf("%s\n  IPv4:  %s\n  Web:   %s\n  SSH:   %s\n", d.Name, d.IPv4, d.HTTPS, d.SSH)
		}
	}
	if *openWeb {
		if len(devices) != 1 {
			fatal("--open requires exactly one discovered ConsolePi Plus device")
		}
		if err := openURL(devices[0].HTTPS); err != nil {
			fatal(err.Error())
		}
	}
}

func printUsage() {
	output := flag.CommandLine.Output()
	fmt.Fprintln(output, "ConsolePi Plus Discovery — nalezení zařízení ConsolePi Plus v aktuální lokální síti.")
	fmt.Fprintln(output, "")
	fmt.Fprintln(output, "Použití:")
	fmt.Fprintln(output, "  consolepi-discover [parametry]")
	fmt.Fprintln(output, "")
	fmt.Fprintln(output, "Parametry:")
	fmt.Fprintln(output, "  --shell               Vypíše nalezená zařízení jen do terminálu.")
	fmt.Fprintln(output, "  --gui                 Kompatibilní alias pro výchozí grafické rozhraní.")
	fmt.Fprintln(output, "  --generate-key NÁZEV Vytvoří Ed25519 klíč do ~/.ssh/NÁZEV a ~/.ssh/NÁZEV.pub.")
	fmt.Fprintln(output, "  --open                Otevře HTTPS rozhraní, pokud je nalezen právě jeden ConsolePi Plus.")
	fmt.Fprintln(output, "  --json                Vypíše nalezená zařízení jako JSON.")
	fmt.Fprintln(output, "  --timeout DÉLKA       Čas pro mDNS hledání (výchozí 4 s, maximum 30 s).")
	fmt.Fprintln(output, "  -h, --help            Zobrazí tuto nápovědu.")
	fmt.Fprintln(output, "")
	fmt.Fprintln(output, "Poznámka: hledání používá mDNS pouze v lokální L2 síti; přes router/VPN")
	fmt.Fprintln(output, "funguje jen při povoleném mDNS reflector/proxy.")
}

type discoverFunc func(time.Duration) ([]device, error)

func runGUI(timeout time.Duration) error {
	listener, err := net.Listen("tcp4", "127.0.0.1:0")
	if err != nil {
		return fmt.Errorf("open local discovery page: %w", err)
	}
	url := "http://" + listener.Addr().String() + "/"
	fmt.Printf("ConsolePi Plus discovery page: %s\nPress Ctrl+C to close it.\n", url)
	if err := openURL(url); err != nil {
		listener.Close()
		return err
	}
	server := &http.Server{
		Handler:           guiHandler(timeout, discover),
		ReadHeaderTimeout: 5 * time.Second,
		IdleTimeout:       30 * time.Second,
	}
	return server.Serve(listener)
}

func guiHandler(timeout time.Duration, finder discoverFunc) http.Handler {
	token, err := guiToken()
	if err != nil {
		panic(err)
	}
	return guiHandlerWithKeyGenerator(timeout, finder, token, generateInstallationKey)
}

type keyGenerator func(string) (generatedKey, error)

func guiHandlerWithKeyGenerator(timeout time.Duration, finder discoverFunc, token string, generator keyGenerator) http.Handler {
	mux := http.NewServeMux()
	mux.HandleFunc("/", func(response http.ResponseWriter, request *http.Request) {
		if request.Method != http.MethodGet || request.URL.Path != "/" {
			http.NotFound(response, request)
			return
		}
		response.Header().Set("Content-Security-Policy", "default-src 'self'; connect-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'; base-uri 'none'; frame-ancestors 'none'")
		response.Header().Set("Content-Type", "text/html; charset=utf-8")
		_, _ = response.Write([]byte(strings.ReplaceAll(guiPage, "__KEYGEN_TOKEN__", token)))
	})
	mux.HandleFunc("/api/devices", func(response http.ResponseWriter, request *http.Request) {
		if request.Method != http.MethodGet {
			response.Header().Set("Allow", http.MethodGet)
			http.Error(response, "method not allowed", http.StatusMethodNotAllowed)
			return
		}
		devices, err := finder(timeout)
		if err != nil {
			http.Error(response, "discovery failed", http.StatusServiceUnavailable)
			return
		}
		response.Header().Set("Cache-Control", "no-store")
		response.Header().Set("Content-Type", "application/json; charset=utf-8")
		_ = json.NewEncoder(response).Encode(devices)
	})
	mux.HandleFunc("/api/generate-key", func(response http.ResponseWriter, request *http.Request) {
		if request.Method != http.MethodPost {
			response.Header().Set("Allow", http.MethodPost)
			http.Error(response, "method not allowed", http.StatusMethodNotAllowed)
			return
		}
		if request.Header.Get("X-ConsolePi-Keygen-Token") != token {
			http.Error(response, "forbidden", http.StatusForbidden)
			return
		}
		request.Body = http.MaxBytesReader(response, request.Body, 4096)
		var input struct {
			Name string `json:"name"`
		}
		decoder := json.NewDecoder(request.Body)
		if err := decoder.Decode(&input); err != nil || decoder.Decode(&struct{}{}) != io.EOF {
			http.Error(response, "invalid request", http.StatusBadRequest)
			return
		}
		key, err := generator(input.Name)
		if err != nil {
			http.Error(response, err.Error(), http.StatusBadRequest)
			return
		}
		response.Header().Set("Cache-Control", "no-store")
		response.Header().Set("Content-Type", "application/json; charset=utf-8")
		_ = json.NewEncoder(response).Encode(key)
	})
	return mux
}

func guiToken() (string, error) {
	bytes := make([]byte, 32)
	if _, err := rand.Read(bytes); err != nil {
		return "", fmt.Errorf("create local GUI token: %w", err)
	}
	return fmt.Sprintf("%x", bytes), nil
}

const guiPage = `<!doctype html>
<html lang="cs"><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>ConsolePi Plus Discovery</title>
<style>
body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;margin:0;background:#f2f7f6;color:#172c2a}
main{max-width:760px;margin:56px auto;padding:0 24px}.head{display:flex;justify-content:space-between;align-items:center;gap:16px}
h1{margin:0;font-size:32px;color:#087e72}p{color:#506966;line-height:1.5}.device{background:white;border:1px solid #cde0dd;border-radius:16px;margin:16px 0;padding:20px;box-shadow:0 5px 18px #0b50400d}
.address{font:600 20px ui-monospace,SFMono-Regular,Menlo,monospace;margin:7px 0 18px}.hostname{color:#075f56}button{border:0;border-radius:9px;padding:10px 14px;background:#087e72;color:white;font-weight:700;cursor:pointer;margin:3px 6px 0 0}button.secondary{background:#e4f2f0;color:#075f56}input{border:1px solid #cde0dd;border-radius:8px;padding:10px;font:inherit;width:230px;max-width:100%;box-sizing:border-box}.keygen{background:white;border:1px solid #cde0dd;border-radius:16px;margin:24px 0;padding:20px}.keygen h2{margin-top:0}.keygen pre{white-space:pre-wrap;word-break:break-all;background:#edf5f3;border-radius:8px;padding:12px}.keygen small{color:#506966}#status{min-height:24px}.error{color:#a22b2b}.empty{background:white;border-radius:16px;padding:24px}
</style><body><main><div class="head"><div><h1>ConsolePi Plus Discovery</h1><p>Nalezení zařízení v aktuální lokální síti.</p></div><button id="refresh">Obnovit</button></div><p id="status">Vyhledávám…</p><section id="devices"></section><section class="keygen"><h2>Instalační SSH klíč</h2><p>Klíč se vytvoří pouze v tomto počítači do <code>~/.ssh</code>. Do Raspberry Pi Imageru vložte následně jen veřejný klíč.</p><label for="key-name">Název klíče</label><div><input id="key-name" value="consolepi-admin" autocomplete="off"><button id="generate-key">Vytvořit klíč</button></div><p id="key-status"><small>Existující soubory se nikdy nepřepisují.</small></p></section></main>
<script>
const status=document.getElementById('status'), list=document.getElementById('devices');
function button(label, kind, handler){const b=document.createElement('button');b.textContent=label;b.className=kind||'';b.onclick=handler;return b}
function show(devices){list.replaceChildren();if(!devices.length){const e=document.createElement('div');e.className='empty';e.textContent='ConsolePi Plus nebylo v této lokální síti nalezeno.';list.append(e);return} for(const d of devices){const card=document.createElement('article');card.className='device';const title=document.createElement('strong');const hostname=document.createElement('span');hostname.className='hostname';hostname.textContent=d.hostname||d.name;title.append(hostname);let label=d.display_name||'';if(d.location)label+=(label?' ':'')+'('+d.location+')';if(label)title.append(document.createTextNode(' · '+label));const address=document.createElement('div');address.className='address';address.textContent=d.ipv4;card.append(title,address,button('Otevřít web','',()=>window.open(d.https,'_blank','noopener')),button('Kopírovat SSH','secondary',async()=>{try{await navigator.clipboard.writeText(d.ssh);status.textContent='SSH příkaz zkopírován.'}catch{status.textContent='Kopírování selhalo.';status.className='error'}}));list.append(card)}}
async function refresh(){status.className='';status.textContent='Vyhledávám…';try{const r=await fetch('/api/devices',{cache:'no-store'});if(!r.ok)throw Error();const d=await r.json();show(d);status.textContent=d.length?'Nalezeno zařízení: '+d.length:'Vyhledávání dokončeno.'}catch{status.textContent='Vyhledávání selhalo.';status.className='error'}}
document.getElementById('generate-key').onclick=async()=>{const target=document.getElementById('key-status'),name=document.getElementById('key-name').value.trim();target.className='';target.textContent='Vytvářím klíč…';try{const r=await fetch('/api/generate-key',{method:'POST',headers:{'Content-Type':'application/json','X-ConsolePi-Keygen-Token':'__KEYGEN_TOKEN__'},body:JSON.stringify({name})});const data=await r.json().catch(()=>({}));if(!r.ok)throw Error(data.error||'Vytvoření klíče selhalo.');target.replaceChildren();target.append('Veřejný klíč pro Raspberry Pi Imager:');const pre=document.createElement('pre');pre.textContent=data.public_key;target.append(pre,document.createTextNode('Soukromý klíč: '+data.private_path));}catch(error){target.textContent=error.message;target.className='error'}};
document.getElementById('refresh').onclick=refresh;refresh();
</script></body></html>`

func generateInstallationKey(name string) (generatedKey, error) {
	home, err := os.UserHomeDir()
	if err != nil {
		return generatedKey{}, fmt.Errorf("find home directory: %w", err)
	}
	return generateInstallationKeyIn(home, name)
}

func generateInstallationKeyIn(home, name string) (generatedKey, error) {
	if !keyNamePattern.MatchString(name) {
		return generatedKey{}, errors.New("název klíče smí obsahovat jen písmena, číslice, tečku, pomlčku a podtržítko")
	}
	sshDirectory := filepath.Join(home, ".ssh")
	if info, err := os.Lstat(sshDirectory); err == nil {
		if !info.IsDir() || info.Mode()&os.ModeSymlink != 0 {
			return generatedKey{}, errors.New("~/.ssh není bezpečný adresář")
		}
	} else if os.IsNotExist(err) {
		if err := os.Mkdir(sshDirectory, 0700); err != nil {
			return generatedKey{}, fmt.Errorf("create ~/.ssh: %w", err)
		}
	} else {
		return generatedKey{}, fmt.Errorf("inspect ~/.ssh: %w", err)
	}
	privatePath := filepath.Join(sshDirectory, name)
	publicPath := privatePath + ".pub"
	for _, path := range []string{privatePath, publicPath} {
		if _, err := os.Lstat(path); err == nil {
			return generatedKey{}, fmt.Errorf("key already exists: %s", path)
		} else if !os.IsNotExist(err) {
			return generatedKey{}, fmt.Errorf("inspect key path: %w", err)
		}
	}
	command := exec.Command("ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-C", "consolepi-administrator-key", "-f", privatePath)
	if output, err := command.CombinedOutput(); err != nil {
		return generatedKey{}, fmt.Errorf("ssh-keygen failed: %s", strings.TrimSpace(string(output)))
	}
	if err := os.Chmod(privatePath, 0600); err != nil {
		return generatedKey{}, fmt.Errorf("protect private key: %w", err)
	}
	if err := os.Chmod(publicPath, 0644); err != nil {
		return generatedKey{}, fmt.Errorf("set public key mode: %w", err)
	}
	publicKey, err := os.ReadFile(publicPath)
	if err != nil {
		return generatedKey{}, fmt.Errorf("read public key: %w", err)
	}
	line := strings.TrimSpace(string(publicKey))
	if !strings.HasPrefix(line, "ssh-ed25519 ") || strings.Contains(line, "\n") {
		return generatedKey{}, errors.New("ssh-keygen nevytvořil očekávaný Ed25519 veřejný klíč")
	}
	return generatedKey{PrivatePath: privatePath, PublicPath: publicPath, PublicKey: line}, nil
}

func fatal(message string) {
	fmt.Fprintln(os.Stderr, "consolepi-discover:", message)
	os.Exit(1)
}

func discover(timeout time.Duration) ([]device, error) {
	conn, err := net.ListenUDP("udp4", &net.UDPAddr{IP: net.IPv4zero, Port: 0})
	if err != nil {
		return nil, fmt.Errorf("open UDP socket: %w", err)
	}
	defer conn.Close()

	target, err := net.ResolveUDPAddr("udp4", mdnsAddress)
	if err != nil {
		return nil, err
	}
	state := records{map[string]string{}, map[string]srvRecord{}, map[string][]net.IP{}, map[string]serviceIdentity{}}
	deadline := time.Now().Add(timeout)
	phase := timeout / 3
	if phase < time.Millisecond {
		phase = time.Millisecond
	}

	if err := sendQuery(conn, target, serviceType, 12); err != nil {
		return nil, err
	}
	if err := collectReplies(conn, &state, minTime(deadline, time.Now().Add(phase))); err != nil {
		return nil, err
	}
	for _, instance := range state.instances {
		if _, exists := state.targets[canonical(instance)]; !exists {
			if err := sendQuery(conn, target, instance, 33); err != nil {
				return nil, err
			}
		}
		if err := sendQuery(conn, target, instance, 16); err != nil {
			return nil, err
		}
	}
	if err := collectReplies(conn, &state, minTime(deadline, time.Now().Add(phase))); err != nil {
		return nil, err
	}
	for _, srv := range state.targets {
		if len(state.addresses[canonical(srv.target)]) == 0 {
			if err := sendQuery(conn, target, srv.target, 1); err != nil {
				return nil, err
			}
		}
	}
	if err := collectReplies(conn, &state, deadline); err != nil {
		return nil, err
	}
	return state.devices(), nil
}

func minTime(a, b time.Time) time.Time {
	if a.Before(b) {
		return a
	}
	return b
}

func sendQuery(conn *net.UDPConn, target *net.UDPAddr, name string, recordType uint16) error {
	if _, err := conn.WriteToUDP(makeQuery(name, recordType), target); err != nil {
		return fmt.Errorf("send mDNS query: %w", err)
	}
	return nil
}

func collectReplies(conn *net.UDPConn, state *records, deadline time.Time) error {
	buf := make([]byte, 9000)
	for {
		if err := conn.SetReadDeadline(deadline); err != nil {
			return err
		}
		n, _, err := conn.ReadFromUDP(buf)
		if err != nil {
			if errors.Is(err, os.ErrDeadlineExceeded) || isTimeout(err) {
				break
			}
			return fmt.Errorf("read mDNS reply: %w", err)
		}
		parseMessage(buf[:n], state)
	}
	return nil
}

func isTimeout(err error) bool {
	var networkError net.Error
	return errors.As(err, &networkError) && networkError.Timeout()
}

func makeQuery(name string, recordType uint16) []byte {
	packet := make([]byte, 12)
	binary.BigEndian.PutUint16(packet[4:6], 1)
	packet = append(packet, encodeName(name)...)
	packet = append(packet, byte(recordType>>8), byte(recordType), 0x80, 1) // QU: reply unicast to this ephemeral port.
	return packet
}

func encodeName(name string) []byte {
	var out []byte
	for _, label := range strings.Split(strings.TrimSuffix(name, "."), ".") {
		out = append(out, byte(len(label)))
		out = append(out, label...)
	}
	return append(out, 0)
}

func parseMessage(packet []byte, state *records) {
	if len(packet) < 12 {
		return
	}
	questions := int(binary.BigEndian.Uint16(packet[4:6]))
	answers := int(binary.BigEndian.Uint16(packet[6:8])) + int(binary.BigEndian.Uint16(packet[8:10])) + int(binary.BigEndian.Uint16(packet[10:12]))
	offset := 12
	for range questions {
		_, next, ok := readName(packet, offset)
		if !ok || next+4 > len(packet) {
			return
		}
		offset = next + 4
	}
	for range answers {
		owner, next, ok := readName(packet, offset)
		if !ok || next+10 > len(packet) {
			return
		}
		kind := binary.BigEndian.Uint16(packet[next : next+2])
		rdLength := int(binary.BigEndian.Uint16(packet[next+8 : next+10]))
		rdata := next + 10
		if rdata+rdLength > len(packet) {
			return
		}
		switch kind {
		case 12: // PTR
			value, _, ok := readName(packet, rdata)
			if ok && sameName(owner, serviceType) {
				state.instances[canonical(value)] = value
			}
		case 33: // SRV
			if rdLength >= 6 {
				target, _, ok := readName(packet, rdata+6)
				if ok {
					state.targets[canonical(owner)] = srvRecord{target: target, port: binary.BigEndian.Uint16(packet[rdata+4 : rdata+6])}
				}
			}
		case 1: // A
			if rdLength == net.IPv4len {
				state.addresses[canonical(owner)] = append(state.addresses[canonical(owner)], net.IPv4(packet[rdata], packet[rdata+1], packet[rdata+2], packet[rdata+3]))
			}
		case 16: // TXT
			identity, ok := parseTXT(packet[rdata : rdata+rdLength])
			if ok {
				previous := state.identity[canonical(owner)]
				if identity.hostname != "" {
					previous.hostname = identity.hostname
				}
				if identity.displayName != "" {
					previous.displayName = identity.displayName
				}
				if identity.location != "" {
					previous.location = identity.location
				}
				state.identity[canonical(owner)] = previous
			}
		}
		offset = rdata + rdLength
	}
}

func parseTXT(data []byte) (serviceIdentity, bool) {
	var identity serviceIdentity
	for offset := 0; offset < len(data); {
		length := int(data[offset])
		offset++
		if offset+length > len(data) {
			return serviceIdentity{}, false
		}
		record := string(data[offset : offset+length])
		offset += length
		key, value, found := strings.Cut(record, "=")
		if !found || strings.ContainsAny(value, "\x00\r\n") {
			continue
		}
		value = strings.TrimSpace(value)
		switch key {
		case "hostname":
			if identity.hostname == "" {
				identity.hostname = value
			}
		case "display_name":
			if identity.displayName == "" {
				identity.displayName = value
			}
		case "location":
			if identity.location == "" {
				identity.location = value
			}
		}
	}
	return identity, true
}

func readName(packet []byte, start int) (string, int, bool) {
	labels := []string{}
	offset, next := start, start
	jumped := false
	for steps := 0; steps < 128; steps++ {
		if offset >= len(packet) {
			return "", 0, false
		}
		length := int(packet[offset])
		if length == 0 {
			if !jumped {
				next = offset + 1
			}
			return strings.Join(labels, "."), next, true
		}
		if length&0xc0 == 0xc0 {
			if offset+1 >= len(packet) {
				return "", 0, false
			}
			pointer := ((length & 0x3f) << 8) | int(packet[offset+1])
			if pointer >= len(packet) {
				return "", 0, false
			}
			if !jumped {
				next = offset + 2
				jumped = true
			}
			offset = pointer
			continue
		}
		if length&0xc0 != 0 || length > 63 || offset+1+length > len(packet) {
			return "", 0, false
		}
		labels = append(labels, string(packet[offset+1:offset+1+length]))
		offset += 1 + length
		if !jumped {
			next = offset
		}
	}
	return "", 0, false
}

func canonical(name string) string { return strings.ToLower(strings.TrimSuffix(name, ".")) }
func sameName(a, b string) bool    { return canonical(a) == canonical(b) }

func (state records) devices() []device {
	seen := map[string]device{}
	for instance, displayName := range state.instances {
		srv, ok := state.targets[instance]
		if !ok || srv.port != 443 {
			continue
		}
		for _, ip := range state.addresses[canonical(srv.target)] {
			if ip.To4() == nil {
				continue
			}
			address := ip.String()
			name := strings.TrimSuffix(displayName, ".")
			name = strings.TrimSuffix(name, "."+serviceType)
			identity := state.identity[instance]
			seen[address] = device{Name: name, Hostname: identity.hostname, DisplayName: identity.displayName, Location: identity.location, IPv4: address, HTTPS: "https://" + address + "/", SSH: "ssh consolepi@" + address}
		}
	}
	result := make([]device, 0, len(seen))
	for _, d := range seen {
		result = append(result, d)
	}
	sort.Slice(result, func(i, j int) bool { return result[i].IPv4 < result[j].IPv4 })
	return result
}

func openURL(url string) error {
	var command *exec.Cmd
	switch runtime.GOOS {
	case "darwin":
		command = exec.Command("open", url)
	case "windows":
		command = exec.Command("cmd", "/c", "start", "", url)
	default:
		command = exec.Command("xdg-open", url)
	}
	return command.Start()
}
