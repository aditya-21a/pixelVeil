# PixelVeil — TESTING.md

Given the product's entire value proposition is "you don't need to manually check the output," a missed detection here isn't a minor bug — it's an actual privacy leak. This doc exists to define pass/fail *before* writing detection code, not after.

---

## 1. Testing Philosophy

- **Bias toward catching false negatives over false positives.** A face or PII string that's missed defeats the product's purpose. A region that's over-blurred is a minor annoyance. When tuning thresholds, always err toward "blur when uncertain."
- **No feature ships to the UI phase until it passes its test cases against planted test data.** Pipeline validation (Phase 2 in TASKS.md) happens before any GUI work.
- **Track every miss, even small ones**, in `KNOWN_ISSUES.md` (or the Results screen's "Flag an issue" log during manual review) — don't let known limitations quietly disappear.

---

## 2. Test Video Set (build these first)

Create 3-5 short (30s-2min) test videos with deliberately planted content:

| Test video | Contents |
|---|---|
| `test_faces_basic.mp4` | 1 clear frontal face, static, well-lit |
| `test_faces_multi.mp4` | 2-3 faces, some angled, some partially occluded (to observe MediaPipe's known limitation, not to expect perfection) |
| `test_pii_text.mp4` | Screen recording of a mock form/dashboard with a fake email, fake phone number, fake credit card number, fake IP address typed/visible on screen |
| `test_mixed.mp4` | Combination — face visible + PII text on screen simultaneously, some scrolling/moving text |
| `test_zones.mp4` | A recording where the same UI panel (e.g. a mock CRM sidebar) is visible throughout, used to test user-marked static zone redaction |

Keep these checked into `tests/sample_videos/` per the architecture.md file structure.

---

## 3. Test Cases & Acceptance Criteria

### 3.1 Face Detection
| Case | Expected result | Pass criteria |
|---|---|---|
| Single frontal face, static | Detected and blurred every frame | 100% of frames have the face blurred |
| Multiple faces in frame | All detected and blurred | No face left unblurred in a majority of frames — flag any consistent miss |
| Angled face (known MediaPipe weak point) | May be missed — this is a documented, accepted v1 limitation | Log the miss rate; don't block v1 ship on this, but record it honestly in KNOWN_ISSUES.md |
| Face partially occluded | May be missed — same as above | Same handling |

### 3.2 OCR + PII Matching
| Case | Expected result | Pass criteria |
|---|---|---|
| Static visible email address | Detected, matched as EMAIL, redacted | Detected in the majority of sampled frames it's visible in |
| Static visible phone number | Detected, matched as PHONE | Same |
| Static visible credit card number | Detected, matched as CARD | Same |
| Static visible IP address | Detected, matched as IP | Same |
| Scrolling/moving text containing PII | May be missed between OCR samples | Log miss rate; this is expected given frame-sampling — note it as a known tradeoff, consider increasing sample rate if miss rate is too high |
| Plain non-PII text on screen (e.g. a heading) | NOT flagged as PII | No false positives on ordinary text — verify regex specificity |

### 3.3 Redaction Modes
| Case | Expected result | Pass criteria |
|---|---|---|
| Blur mode selected | All flagged regions (faces + PII) blurred/boxed | Visual check: no readable text or recognizable face remains in flagged regions |
| Fake-data mode selected | PII regions show placeholder text instead of a blank box; faces still blurred (faces don't get fake-data treatment) | Placeholder text is legible and clearly fake (e.g. "Test User 1," not confusingly similar to real data) |
| Mixed mode video (`test_mixed.mp4`) | Both treatments apply correctly to their respective region types simultaneously | No overlap/conflict errors between face and PII redaction |

### 3.4 Static Zones
| Case | Expected result | Pass criteria |
|---|---|---|
| User draws a zone over a static panel | Zone redacted in every frame regardless of detection | 100% of frames have the zone covered — this should be the most reliable feature since it needs no ML |
| Zone drawn incorrectly (too small/misplaced) | Only the drawn area is covered, not adjacent content | Confirms zone coordinates map correctly to video resolution, not just canvas display size (a common bug source — canvas display size vs. actual video pixel dimensions) |

### 3.5 Output Integrity
| Case | Expected result | Pass criteria |
|---|---|---|
| Any processed video | Plays correctly in a standard player (VLC, Windows Media Player) | No corruption, no codec errors |
| Audio track | Original audio preserved in output | Audio present and in sync — this was a specific known failure mode of OpenCV's raw VideoWriter, which is why ffmpeg muxing exists (see DECISIONS.md D8) |

---

## 4. Manual Review Process

For every test video processed during Phase 2 validation:
1. Watch the full output video.
2. For every miss (face or PII not redacted) or false positive (something redacted that shouldn't be), note the timestamp and what was missed/wrongly flagged.
3. Log these in the Results screen's "Flag an issue" feature (per design.md) or directly in `KNOWN_ISSUES.md`.
4. Calculate a rough miss rate per category (faces, emails, phones, cards, IPs) — this becomes your honest, quotable accuracy baseline, useful both for your own confidence and for any future marketing claims (don't market "100% guaranteed" — see roadmap.md's honest caveat on this).

---

## 5. What "Ready for GUI Phase" Looks Like

Do not move to Phase 3 (UI build) until:
- All static-content test cases (basic faces, static PII text, static zones) pass at or near 100%.
- Known limitations (angled faces, scrolling text) are documented, not silently ignored.
- Output video integrity (playback + audio) is confirmed reliable across all test videos.

## 6. What "Ready to Ship v1" Looks Like

- Pipeline validation above is complete and miss rates are documented.
- At minimum 5-10 people from target communities have tried a demo/beta build and given real feedback (per roadmap.md marketing plan) — technical correctness alone isn't launch-readiness, real user reaction is.
- KNOWN_ISSUES.md accurately reflects current limitations so marketing claims stay honest.