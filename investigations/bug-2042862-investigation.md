---
bug_id: 2042862
investigated_at: 2026-05-30T00:00:00Z
status: investigated
depth: triage
root_cause: AutoplayPolicy::IsAllowedToPlay(AudioContext&) early-returns true whenever media.autoplay.blocking_policy != sPOLICY_STICKY_ACTIVATION, so Web Audio bypasses all permission/activation checks under the transient-activation and click-to-play policies.
affected_files:
  - dom/media/autoplay/AutoplayPolicy.cpp#L297-L299
regression_range: null
related_bugs: [1511117, 2023365]
complexity: low
notes: Only triggered when the user sets a non-default media.autoplay.blocking_policy. The HTMLMediaElement path uses a distinct helper (IsAllowedToPlayByBlockingModel) that handles all three policies — the Web Audio path is the outlier.
---

# Bug 2042862 Investigation (triage mode)

## Summary

- **Bug**: [Bug 2042862](https://bugzilla.mozilla.org/show_bug.cgi?id=2042862)
- **Title**: Autoplay policy ineffective when not `sPOLICY_STICKY_ACTIVATION`
- **Component**: Core :: Audio/Video: Playback
- **Current Severity/Priority**: -- / --
- **Status**: UNCONFIRMED

Web Audio autoplay blocking is fully short-circuited when `media.autoplay.blocking_policy` is set to anything other than `0` (sticky activation). The gating helper [`IsEnableBlockingWebAudioByUserGesturePolicy()`](https://searchfox.org/mozilla-central/source/dom/media/autoplay/AutoplayPolicy.cpp#158) only returns `true` for sticky activation, so any other policy makes [`AutoplayPolicy::IsAllowedToPlay(AudioContext&)`](https://searchfox.org/mozilla-central/source/dom/media/autoplay/AutoplayPolicy.cpp#281) return `true` immediately at line 297, skipping the site-permission and activation checks. This is an oversight in the original Web Audio autoplay block design (bug 1511117), not a regression — the HTMLMediaElement path handles all three policies correctly via a separate helper.

## Findings

### Root cause

**Verified.** At [`AutoplayPolicy.cpp:297-299`](https://searchfox.org/mozilla-central/source/dom/media/autoplay/AutoplayPolicy.cpp#297) the AudioContext autoplay check does:

```cpp
if (!IsEnableBlockingWebAudioByUserGesturePolicy()) {
  return true;
}
```

And [`IsEnableBlockingWebAudioByUserGesturePolicy()`](https://searchfox.org/mozilla-central/source/dom/media/autoplay/AutoplayPolicy.cpp#158) is literally:

```cpp
static bool IsEnableBlockingWebAudioByUserGesturePolicy() {
  return StaticPrefs::media_autoplay_blocking_policy() ==
         sPOLICY_STICKY_ACTIVATION;
}
```

So for `media.autoplay.blocking_policy == 1` (transient activation) or `== 2` (click-to-play), the function returns `false`, the early-return fires, and Web Audio is unconditionally allowed to play regardless of user-gesture state or site permissions. By contrast, the HTMLMediaElement path uses [`IsAllowedToPlayByBlockingModel()`](https://searchfox.org/mozilla-central/source/dom/media/autoplay/AutoplayPolicy.cpp#163) which has explicit branches for all three policies. The wiki entry at `~/firefox-wiki/components/AutoplayPolicy.md` line 39 already documents this as a known sticky-activation-only behavior.

### Affected files

- [`dom/media/autoplay/AutoplayPolicy.cpp`](https://searchfox.org/mozilla-central/source/dom/media/autoplay/AutoplayPolicy.cpp)

### Regression range

None identified — this is the original Web Audio autoplay block design from bug 1511117 (the `[meta] block autoplay for web audio` tracker). The behavior has always been sticky-activation-only.

### Related context

- [Bug 1511117](https://bugzilla.mozilla.org/show_bug.cgi?id=1511117) — `[meta] block autoplay for web audio` — original meta where this Web Audio gating was implemented.
- [Bug 2023365](https://bugzilla.mozilla.org/show_bug.cgi?id=2023365) — `[meta] Auto Play Issues Meta` — A/V triage tracker for autoplay bugs.
- Reporter also notes `IsAllowedToPlay(AudioContext&)` has no `AUTOPLAY_LOG` traces, which made debugging unnecessarily hard — adding logging is a worthwhile cleanup alongside the fix.

## Proposed Solution

**Hypothesis** — deep verification not yet performed. The Web Audio path should mirror the HTMLMediaElement path: replace the `IsEnableBlockingWebAudioByUserGesturePolicy()` gate at [line 297](https://searchfox.org/mozilla-central/source/dom/media/autoplay/AutoplayPolicy.cpp#297) with a check that uses the same activation semantics as `IsAllowedToPlayByBlockingModel()` for each of the three policy values (sticky / transient / user-input-depth). Concretely, when `media.autoplay.block-webaudio` is enabled, all three policies should require an appropriate user activation before allowing the AudioContext to start; only `nsIAutoplay::ALLOWED` and an `ALLOW_ACTION` site permission should bypass it. Also add `AUTOPLAY_LOG` traces in `IsAllowedToPlay(AudioContext&)` so the decision can be diagnosed from a media log. Deep mode should confirm the exact semantics intended for Web Audio under the transient-activation policy (per-element vs. per-window activation requirement) before writing the patch.

## Notes

- The bug is only observable when the user changes `media.autoplay.blocking_policy` from its default of `0`, so user-visible impact is limited. Suggested triage: S3 / P3.
- Deep mode needs to confirm: (1) whether the transient-activation policy for Web Audio should check `HasValidTransientUserGestureActivation()` on the owner document (mirroring the HTMLMediaElement branch at lines 179-185) or whether AudioContext lacks the per-element "blessed" notion entirely; (2) whether the click-to-play policy (`sPOLICY_USER_INPUT_DEPTH`, value 2) is meaningful for AudioContext since there is no synchronous play() event handler. Both questions affect the exact shape of the replacement gate.
- Suggested test approach (deep mode): mochitest that pushes `media.autoplay.blocking_policy = 1` + `media.autoplay.default = 1` and asserts an AudioContext stays in `suspended` state without a user gesture, then resumes after a simulated click.

---
*Triage-mode investigation. Re-run `/bug-start 2042862` (deep mode) when ready to implement.*
