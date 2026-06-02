---
bug_id: 2043895
investigated_at: 2026-06-01T00:00:00Z
status: investigated
depth: triage
root_cause: navigator.mediaCapabilities.decodingInfo() instantiates a real MediaDataDecoder (create + Init + Shutdown) on every non-DRM video query, with no result caching, so each call costs ~17 ms on Windows (WMF/RDD setup) regardless of repetition.
affected_files:
  - dom/media/mediacapabilities/MediaCapabilities.cpp#L1059
  - dom/media/mediacapabilities/MediaCapabilities.cpp#L854
  - dom/media/mediacapabilities/MediaCapabilities.cpp#L1093
regression_range: null
related_bugs: [1676902, 1758786]
complexity: medium
notes: Reporter's own benchmark shows cached == uncached == ~17 ms/call, which directly confirms there is no result cache. Bug 1676902 (closed WORKSFORME) addressed earlier regressions but the steady-state per-call cost remains.
---

# Bug 2043895 Investigation (triage mode)

## Summary

- **Bug**: [Bug 2043895](https://bugzilla.mozilla.org/show_bug.cgi?id=2043895)
- **Title**: mediaCapabilities.decodingInfo is still slow
- **Component**: Audio/Video
- **Current Severity/Priority**: -- / -- (unset)
- **Status**: UNCONFIRMED

`navigator.mediaCapabilities.decodingInfo()` is ~17 ms/call on Firefox Nightly 153 (Windows) vs ~0.09 ms on Chromium. The reporter's benchmark shows cold, uncached, and cached (identical-config) calls all cost the same ~17 ms, proving there is no result caching. The cost comes from Firefox actually creating, initializing, and shutting down a real `MediaDataDecoder` per query (a heavyweight WMF/RDD round-trip on Windows), whereas Chromium answers from a static capability table. This delays Shaka-player startup by tens of seconds when many stream variants must be probed.

## Findings

### Root cause
**Verified**: For a non-DRM video config, `decodingInfo()` calls `CheckVideoDecodingInfo`, which on a fresh per-call `TaskQueue` runs `AllocationWrapper::CreateDecoder` → `decoder->Init()` → `IsHardwareAccelerated()` → `decoder->Shutdown()` for every query — see [`MediaCapabilities.cpp:1093-1136`](https://searchfox.org/mozilla-central/source/dom/media/mediacapabilities/MediaCapabilities.cpp#1093). On Windows the H.264 (`avc1.640028`) decoder is a Media Foundation decoder that must be created on an MTA thread and set up across the RDD/utility process, which is the bulk of the ~17 ms. The result is **not cached**: there is no lookup keyed on the configuration before the decoder is built, and the reporter's "cached" run (same config N times) measuring identical to "uncached" confirms this empirically.

### Affected files
- [`dom/media/mediacapabilities/MediaCapabilities.cpp`](https://searchfox.org/mozilla-central/source/dom/media/mediacapabilities/MediaCapabilities.cpp#L1059) — `CheckVideoDecodingInfo` creates/inits/shuts down a real decoder per call (lines 1093, 1106, 1127)
- [`dom/media/mediacapabilities/MediaCapabilities.cpp`](https://searchfox.org/mozilla-central/source/dom/media/mediacapabilities/MediaCapabilities.cpp#L854) — `CreateNonWebRTCDecodingInfo` builds a brand-new `TaskQueue` for each query

### Regression range
None identified. Bug 1676902 comment 3 notes large improvements landed up to Firefox 135 (471 ms → 7 ms for VP8/WebM), but those did not address the steady-state decoder-instantiation cost on the Windows H.264/WMF path that this bug measures.

### Related context
- [Bug 1676902](https://bugzilla.mozilla.org/show_bug.cgi?id=1676902) — "Poor performance comparatively with navigator.mediaCapabilities.decodingInfo", closed WORKSFORME 2025-09; this bug is effectively its reopening for the remaining slow case.
- [Bug 1758786](https://bugzilla.mozilla.org/show_bug.cgi?id=1758786) — blocked by 1676902 (related decodingInfo work).
- Firefox Knowledge Wiki `components/MediaCapabilities.md` documents the `WMFDecoderModule::Supports()` path but not the per-call decoder-instantiation cost — this investigation adds that.

## Proposed Solution

(Hypothesis — deep verification did not run.) Two complementary directions: (1) **Cache** `decodingInfo` results keyed on the normalized configuration, so repeated/identical queries (the common Shaka-player case of probing many variants) skip decoder instantiation entirely — this alone would collapse the "cached" path toward Chromium numbers. (2) For the **uncached/cold** path, avoid creating and initializing a full `MediaDataDecoder` just to read `smooth`/`powerEfficient`; prefer a lighter capability query (the audio path already uses `PDMFactory::Supports` without building a decoder — see [`MediaCapabilities.cpp:987-999`](https://searchfox.org/mozilla-central/source/dom/media/mediacapabilities/MediaCapabilities.cpp#987)) and derive `powerEfficient`/`smooth` from static decoder metadata where possible, reserving full decoder init for cases that genuinely need runtime probing.

## Notes

- Open question for deep mode: confirm the ~17 ms is dominated by WMF/RDD decoder `Init()` (instrument `CheckVideoDecodingInfo`), and whether a config-keyed cache is safe given that `powerEfficient` can depend on dynamic GPU state (the wiki notes `Supports()` does not reflect runtime DXVA slot count — a cache must decide how long results stay valid).
- The benchmark uses `type: 'media-source'` H.264 1080p30 — a very common Shaka/DASH probe, so user impact is broad on Windows.
- No Firefox Profiler link, media log, or about:support in the bug; none needed — the reporter's self-contained benchmark plus the code path are sufficient to localize the cost.

---
*Triage-mode investigation. Re-run `/bug-start 2043895` (deep mode) when ready to implement.*
