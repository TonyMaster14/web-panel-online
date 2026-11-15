# WPO Auto-select

The Happ subscription includes an Auto-select Xray JSON profile when more than
one distinct server is selected and automatic switching is enabled.

The client probes every selected VLESS XHTTP and Hysteria2 outbound concurrently.
`leastPing` selects the reachable outbound with the lowest observed latency;
there are no artificial weights based on country or subscription order. A failed
outbound is excluded after the next failed probe. It becomes eligible again after
a successful probe. Probes repeat 10 seconds after the previous batch completes;
timeouts add detection latency, so switching is not instantaneous.

Selection applies to new connections. An established TCP stream cannot be moved
to another server: the application must reconnect if that server disappears.
If every VPN outbound fails, the VPN route is blocked instead of using the first
dead server or bypassing the VPN. Explicit direct/block routing rules are retained.

## Install and update

New main/test installations copy the current `wpp_routing.py` automatically.
For an existing main panel run `wpo-auto-select-update.sh` from this release.
It verifies the downloaded module, saves a backup, restarts only the panel, and
rolls back if its localhost health check fails. Remote nodes and subscriber keys
are not changed. In Happ refresh the subscription, select Auto-select, and
reconnect so that the client loads the new JSON configuration.

## Validation

- Standard suite: `python3 -m unittest discover -s tests`.
- Real-core suite: `XRAY_TEST_BIN=/path/to/xray python3 -m unittest discover -s tests -p test_live_failover.py -v`.
- Tested core: Xray 26.7.28, Linux x86_64.
- Actual HTTP requests were carried through local VLESS XHTTP servers and through
  Hysteria2. The selected primary was stopped, requests moved to the backup, the
  primary was restarted, and requests returned to it. Both-down requests failed.
- The fixture alone permits loopback destinations and trusts a locally generated
  certificate. Production node permissions and TLS verification are unchanged.

This is a core integration test, not a test of every Happ application release or
of the user's live VPS network. A client-side probe URL must be reachable through
the nodes for health-based selection to work.
