---
bug_id: 2043087
investigated_at: 2026-05-30T00:00:00Z
status: investigated
depth: triage
root_cause: MFMediaEngineDecoderModule::Supports() reports HEVC as supported without requiring an mMediaEngineId, so for non-DRM MSE the PDMFactory selects the MFMediaEngineCDM utility path and CreateVideoDecoder later rejects with NS_ERROR_DOM_MEDIA_NOT_SUPPORTED_ERR (0x806e0003).
affected_files:
  - dom/media/platforms/wmf/MFMediaEngineDecoderModule.cpp#L97
  - dom/media/ipc/RemoteMediaManagerChild.cpp#L413
  - dom/media/ExternalEngineStateMachine.cpp#L342
  - dom/media/mediasource/MediaSourceDecoder.cpp
regression_range: null
related_bugs: [1752052, 1806566]
complexity: medium
notes: Intermittent because the failing path depends on which PDM Supports() answers first for HEVC under MSE; with pref=2 (encrypted-only) the MFMediaEngineCDM module still claims HEVC support and CreateVideoDecoder asserts mMediaEngineId. ExternalEngineStateMachine's pref==2 bailout in OnMetadataRead does fire for non-encrypted content, but the decoder-selection path through MFMediaEngineDecoderModule::Supports is reached separately and can still pick the CDM utility location.
---

# Bug 2043087 Investigation (triage mode)

## Summary

- **Bug**: [Bug 2043087](https://bugzilla.mozilla.org/show_bug.cgi?id=2043087)
- **Title**: Non-DRM MSE video intermittently routed to WMF Media Engine CDM utility process causing NS_ERROR_DOM_MEDIA_NOT_SUPPORTED_ERR (0x806e0003)
- **Component**: Audio/Video: Playback
- **Current Severity/Priority**: -- / --
- **Status**: UNCONFIRMED

Frigate NVR playback of non-DRM H.265/HEVC MSE content on Windows fails intermittently with `NS_ERROR_DOM_MEDIA_NOT_SUPPORTED_ERR (0x806e0003) - Utility MF Media Engine CDM only support for media engine playback`, even with `media.wmf.media-engine.enabled = 2` (encrypted-only). The reporter's media profile shows the engine being entered (`ExternalEngineStateMachine ... ReadingMetadata, ... video=video/hevc(supported=1)`), and the failure surfaces from [`RemoteMediaManagerChild::CreateVideoDecoder`](https://searchfox.org/mozilla-central/source/dom/media/ipc/RemoteMediaManagerChild.cpp#413) rejecting because `aLocation == UtilityProcess_MFMediaEngineCDM` while `aParams.mMediaEngineId` is empty. The intermittency comes from PDM ordering: when the MFMediaEngineCDM module wins the `Supports()` race for HEVC, decoder creation fails; otherwise (e.g. when the GPU/WMF HEVC path is picked) playback works.

## Findings

### Root cause

**Verified**: [`MFMediaEngineDecoderModule::SupportInternal`](https://searchfox.org/mozilla-central/source/dom/media/platforms/wmf/MFMediaEngineDecoderModule.cpp#97) returns `media::DecodeSupport::HardwareDecode` for HEVC purely based on (a) the `media.wmf.media-engine.enabled` pref being non-zero, (b) `gfxVars::CanUseHardwareVideoDecoding()`, and (c) `CanCreateMFTDecoder(HEVC)`. It does **not** check whether the caller has a `mMediaEngineId` (i.e. whether this is actually an EME/PlayReady playback). [`PDMFactory::CreateContentPDMs`](https://searchfox.org/mozilla-central/source/dom/media/platforms/PDMFactory.cpp#662) registers the `UtilityProcess_MFMediaEngineCDM` `RemoteDecoderModule` whenever the pref is non-zero (including the encrypted-only value 2). Once that module claims HEVC support, [`RemoteMediaManagerChild::CreateVideoDecoder`](https://searchfox.org/mozilla-central/source/dom/media/ipc/RemoteMediaManagerChild.cpp#413) hits the `!aParams.mMediaEngineId && aLocation == UtilityProcess_MFMediaEngineCDM` branch and rejects with `NS_ERROR_DOM_MEDIA_NOT_SUPPORTED_ERR` and the `"Utility MF Media Engine CDM only support for media engine playback"` reason string seen in the bug.

The [`ExternalEngineStateMachine`](https://searchfox.org/mozilla-central/source/dom/media/ExternalEngineStateMachine.cpp#342) pref==2 + non-encrypted bailout does work in `OnMetadataRead`, but it is on a different selection path (MSE state-machine choice) than decoder-module selection inside `MediaFormatReader`. So even when the state machine would fall back, the decoder side independently chooses the CDM utility module and fails.

**Hypothesis** (explains intermittency): Order/timing of decoder-module probing in [`PDMFactory`](https://searchfox.org/mozilla-central/source/dom/media/platforms/PDMFactory.cpp#117) determines which `Supports()` answer wins for HEVC on this configuration (GPU process HEVC vs. MFMediaEngineCDM utility). On runs where MFMediaEngineCDM is selected first, the failure manifests; otherwise, the GPU/RDD HEVC path succeeds.

### Affected files

- [`dom/media/platforms/wmf/MFMediaEngineDecoderModule.cpp`](https://searchfox.org/mozilla-central/source/dom/media/platforms/wmf/MFMediaEngineDecoderModule.cpp#97) — `SupportInternal` does not gate on `mMediaEngineId` / EME context, so it claims HEVC support for non-DRM playback.
- [`dom/media/ipc/RemoteMediaManagerChild.cpp`](https://searchfox.org/mozilla-central/source/dom/media/ipc/RemoteMediaManagerChild.cpp#413) — emits the `0x806e0003` rejection when the CDM utility is selected without an engine id.
- [`dom/media/ExternalEngineStateMachine.cpp`](https://searchfox.org/mozilla-central/source/dom/media/ExternalEngineStateMachine.cpp#330) — already handles the analogous pref==2 + non-encrypted case at the state-machine layer; the decoder-module layer needs the same gate.
- [`dom/media/mediasource/MediaSourceDecoder.cpp`](https://searchfox.org/mozilla-central/source/dom/media/mediasource/MediaSourceDecoder.cpp#84) — creates `ExternalEngineStateMachine` whenever the pref is non-zero, which is fine because the metadata-time bailout catches non-encrypted; not the bug source but part of the same selection story.

### Regression range

None identified. The MFMediaEngineCDM utility path and the existing pref==2 bailout pre-date this report; this is most likely a long-standing routing gap exposed by HEVC + non-DRM MSE.

### Related context

- Bug [1752052](https://bugzilla.mozilla.org/show_bug.cgi?id=1752052) ([meta] Media Foundation Playback & CDM Support) — resolved meta covering the broader feature area.
- Bug [1806566](https://bugzilla.mozilla.org/show_bug.cgi?id=1806566) ([meta] Implement supporting MF-based CDM on media engine playback) — resolved meta for the CDM-side work.
- Wiki: [[components/ExternalEngineStateMachine]] documents the EESM fallback semantics (narrow fallback window once `RunningEngine` is entered, and the `IsEncryptedCustomIdent` mechanism set by `SetCDMProxy`).

#### Profile evidence

`https://share.firefox.dev/4wS0c8h` — media-preset profile. Key markers:

- `[MediaDecoderStateMachine #1] ExternalEngineStateMachine[...] Decoder=..., State=ReadingMetadata, audio=audio/mp4a-latm (supported=1), video=video/hevc(supported=1)`
- `[MediaSupervisor] Sandbox Utility MF Media Engine CDM decoder supports requested type video/hevc`
- `[MediaSupervisor] MediaFormatReader[...] ::NotifyError: Video Decoding error: NS_ERROR_DOM_MEDIA_NOT_SUPPORTED_ERR (0x806e0003) - Utility MF Media Engine CDM only support for media engine playback`
- Adjacent `WMFDecoderModule::CreateVideoDecoder failed for manager with description wmf HEVC codec software video decoder ... Use VP8/VP9/AV1 MFT only if HW acceleration is available.` (HEVC has no SW fallback in WMF, so once HW selection misroutes, there is no rescue path.)

## Proposed Solution

Hypothesis-level direction (deep mode should verify each step):

1. In [`MFMediaEngineDecoderModule::SupportInternal`](https://searchfox.org/mozilla-central/source/dom/media/platforms/wmf/MFMediaEngineDecoderModule.cpp#97), additionally require an EME/media-engine context — e.g. only return `HardwareDecode` when the caller indicates an encrypted track / media-engine-id-bearing path (or when the pref is `1`, "encrypted and clear"). When pref is `2` (encrypted-only) and the request is non-DRM, return an empty `DecodeSupportSet` so PDMFactory falls through to GPU/WMF/RDD HEVC decoders.
2. Mirror the same gate in the `Supports()` checks PDMFactory consults so the MFMediaEngineCDM `RemoteDecoderModule` does not advertise non-DRM HEVC support.
3. Audit [`MFMediaEngineDecoderModule::SupportsConfig`](https://searchfox.org/mozilla-central/source/dom/media/platforms/wmf/MFMediaEngineDecoderModule.cpp#36) for the same gap (it currently calls into `RemoteMediaIn::UtilityProcess_MFMediaEngineCDM` `Supports` without any encryption context).

This keeps the MFMediaEngineCDM utility path strictly tied to EME/PlayReady playback, matching the comment near `media.wmf.media-engine.enabled` ("2: enable for encrypted only") and the existing EESM-side guard.

## Notes

Open questions for deep mode:

- Confirm by reading the code whether `SupportDecoderParams` carries enough signal (e.g. an `IsEncrypted()` accessor or `mMediaEngineId` analogue) to distinguish DRM vs. clear at the `Supports()` call site, or whether a small plumbing change is needed.
- Verify the WMF HEVC path's behavior for non-DRM HEVC on a machine with the Microsoft HEVC Video Extensions installed (per comment 8 the reporter has it). The current `WMFVideoMFTManager` log shows `Use VP8/VP9/AV1 MFT only if HW acceleration is available` which is a SW-side rejection — confirm the HEVC HW path is reachable via `WMFDecoderModule` once MFMediaEngineCDM stops claiming support.
- Reproduce locally with a simple non-DRM HEVC MSE testcase to capture stable repro and to drive a mochitest under `dom/media/test/`.

---
*Triage-mode investigation. Re-run `/bug-start 2043087` (deep mode) when ready to implement.*
