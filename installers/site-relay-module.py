#!/usr/bin/env python3
"""Minimal WPO patch to pinned upstream tproxy-server.

The public site is independent of Telegram WEB Proxy credentials. Upstream
requires at least one transport profile even for a static public website.
This patch permits zero profiles; it never creates a synthetic credential,
transport profile, QR link, or hidden user.

Only run against the exact upstream revision pinned in install-webproxy-core.sh.
"""
import pathlib
import sys

if len(sys.argv) != 2:
    raise SystemExit("usage: wpo-relay-zero-profiles-patch.py /path/to/upstream/tproxy-server")

source = pathlib.Path(sys.argv[1])
target = source / "internal/config/config.go"
original = target.read_text(encoding="utf-8")
old = '''\tif len(source.Profiles) == 0 || len(source.Profiles) > limits.MaxProfiles {
\t\treturn nil, fmt.Errorf("profiles must contain between 1 and %d entries", limits.MaxProfiles)
\t}'''
new = '''\t// WPO: The relay may serve a public site with zero WEB Proxy profiles.
\t// With no capabilities, bridge and transport authentication never succeed.
\tif len(source.Profiles) > limits.MaxProfiles {
\t\treturn nil, fmt.Errorf("profiles must contain between 0 and %d entries", limits.MaxProfiles)
\t}'''
if original.count(old) == 1:
    target.write_text(original.replace(old, new), encoding="utf-8")
elif original.count(new) == 1:
    pass
else:
    raise SystemExit("Unsupported upstream tproxy-server config.go: exact pinned guard not found")

# The pinned upstream credential-permissions test writes a mode 0444 file,
# then assumes os.WriteFile created it with exactly those bits. With a secure
# installer umask the newly created file can have fewer permission bits.
# Explicit chmod makes the security assertion valid regardless of umask.
# The test is retained and still requires Load() to REJECT the unsafe file
# once CREDENTIALS_DIRECTORY has been cleared.
permissions_test = source / "internal/config/config_test.go"
permissions_source = permissions_test.read_text(encoding="utf-8")
original_test = '''\tif err := os.WriteFile(profiles, []byte(content), 0444); err != nil {
\t\tt.Fatal(err)
\t}
\tt.Setenv("CREDENTIALS_DIRECTORY", credentials)'''
corrected_test = '''\tif err := os.WriteFile(profiles, []byte(content), 0444); err != nil {
\t\tt.Fatal(err)
\t}
\t// WPO: Verify intended 0444 permissions independently of process umask.
\tif err := os.Chmod(profiles, 0444); err != nil {
\t\tt.Fatal(err)
\t}
\tt.Setenv("CREDENTIALS_DIRECTORY", credentials)'''
if permissions_source.count(original_test) == 1:
    permissions_test.write_text(
        permissions_source.replace(original_test, corrected_test), encoding="utf-8"
    )
elif permissions_source.count(corrected_test) != 1:
    raise SystemExit("Pinned upstream permissions test changed: refusing unexpected patch")

# Tests run against actual Go types, not an imitation or mock of the relay.
tests = {
    "internal/config/wpo_empty_profiles_test.go": r'''package config

import (
    "os"
    "path/filepath"
    "testing"
)

func TestWPOEmptyProfilesAreAllowedForPublicSite(t *testing.T) {
    root := t.TempDir()
    public := filepath.Join(root, "public")
    if err := os.Mkdir(public, 0700); err != nil { t.Fatal(err) }
    if err := os.WriteFile(filepath.Join(public, "index.html"), []byte("site-without-proxy"), 0600); err != nil { t.Fatal(err) }
    profiles := filepath.Join(root, "profiles.json")
    if err := os.WriteFile(profiles, []byte("{\"profiles\":[]}"), 0600); err != nil { t.Fatal(err) }
    cfg := filepath.Join(root, "config.json")
    raw := "{\"public_hostname\":\"proxy.example.com\",\"public_dir\":\"" + public + "\",\"profiles_file\":\"" + profiles + "\"}"
    if err := os.WriteFile(cfg, []byte(raw), 0600); err != nil { t.Fatal(err) }
    loaded, err := Load(cfg)
    if err != nil { t.Fatalf("site-only relay rejected: %v", err) }
    if len(loaded.Profiles) != 0 { t.Fatalf("unexpected transport profile: %#v", loaded.Profiles) }
}
''',
    "internal/server/wpo_empty_profiles_test.go": r'''package server

import (
    "net/http"
    "net/http/httptest"
    "os"
    "path/filepath"
    "strings"
    "testing"

    "github.com/telegramdesktop/tproxy-server/internal/config"
)

func TestWPOSiteWithoutTransportProfiles(t *testing.T) {
    root := t.TempDir()
    if err := os.WriteFile(filepath.Join(root, "index.html"), []byte("site-with-zero-web-profiles"), 0600); err != nil {
        t.Fatal(err)
    }
    settings := config.Defaults()
    settings.PublicHostname = "proxy.example.com"
    settings.PublicDir = root
    settings.Profiles = nil
    application, err := New(settings)
    if err != nil { t.Fatal(err) }
    defer application.Shutdown()

    check := func(url string, method string, auth string, wantCode int, wantBody string) {
        t.Helper()
        request := httptest.NewRequest(method, url, nil)
        if auth != "" { request.Header.Set("Authorization", auth) }
        response := httptest.NewRecorder()
        application.Handler().ServeHTTP(response, request)
        if response.Code != wantCode {
            t.Fatalf("request %s: status %d, want %d", url, response.Code, wantCode)
        }
        if wantBody != "" && !strings.Contains(response.Body.String(), wantBody) {
            t.Fatalf("request %s: unexpected body %q", url, response.Body.String())
        }
    }
    check("https://proxy.example.com/", http.MethodGet, "", http.StatusOK, "site-with-zero-web-profiles")
    check("https://proxy.example.com/?bridge="+strings.Repeat("A", 43),
          http.MethodGet, "", http.StatusOK, "site-with-zero-web-profiles")
    check("https://proxy.example.com/api/v1/session",
          http.MethodPost, "Bearer not-a-session", http.StatusNotFound, "")
}
'''
}
for relative, code in tests.items():
    destination = source / relative
    if destination.exists() and destination.read_text(encoding="utf-8") != code:
        raise SystemExit("Refusing to replace a different Go test: " + relative)
    destination.write_text(code, encoding="utf-8")

print("WPO relay patched: 0 WEB Proxy profiles allowed; static website and authentication tests installed.")
