# Dynamic location feature validation

Branch: `feature/dynamic-location-alerts`. Do not merge or publish a release until checks below pass.

## Automated checks

- [ ] GitHub Actions `Validate / python-syntax` passes
- [ ] GitHub Actions `Validate / unit-tests` passes (Python 3.14)
- [ ] GitHub Actions `Validate / validate-hacs` passes
- [ ] GitHub Actions `Validate / validate-hassfest` passes
- [ ] Capture the successful workflow run URL and commit SHA

**Evidence status (2026-11-18):** No passing workflow result verified. The GitHub commit-status endpoint returned an empty status list; this is not a pass. A complete Home Assistant test environment was not available in the local sandbox.

## Home Assistant functional acceptance tests

1. **Static regression:** existing zone/county/marine configuration retains the same entity ID, alert count, attributes, deduplication and cleanup behavior.
2. **Home tracking:** create a new entry following `zone.home`; verify `/points` coverage, alert count and `location_status=current` after a successful refresh.
3. **Mobile tracking:** create a new entry following a GPS-capable `device_tracker`; verify its unique ID remains stable when moving between NWS forecast zones/counties.
4. **No GPS at startup:** tracker is unavailable or has no latitude/longitude; sensor reports unknown count rather than zero and does not request an empty NWS alert feed.
5. **GPS lost during refresh:** old alert details may remain for diagnostics, but the count is unknown and status is `location_unavailable`; old coverage must not become current.
6. **Rapid movement:** switch tracker locations repeatedly while `/points` or alert requests are in progress; only the newest valid location may become current.
7. **NWS outage:** simulate HTTP 503, timeout, and malformed `/points` data; do not discard last-good alerts or claim a new coverage is current.
8. **Recovery:** restore GPS and NWS access, including recovery to the *same* coverage; require a successful alert refresh before returning to current.
9. **Source change:** edit the tracked entity in options, reload, and verify the old observer unsubscribes and the new source takes effect.
10. **Unload/restart:** unload and restart Home Assistant; ensure no late observer callbacks and no stale dynamic tracking restored as current.
11. **Shared requests:** two entries with equivalent coverage share HTTP requests but keep independent alert histories and notification states.
12. **Frontend and blueprints:** verify existing alert card and persistent-notification automation remain compatible with both static and dynamic sensors.

## Release gate

Do not label the branch tested or create a development ZIP until automated checks pass and core HA scenarios (1-8, 10) are exercised. Record any failing scenario with reproduction steps and a corresponding regression test before fixing it.
