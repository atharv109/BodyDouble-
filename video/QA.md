# V5 QA report

Reviewed 2026-11-08 against the 102-second composition and full draft.

## Automated checks

- `hyperframes doctor`: Node 24, FFmpeg 8.1, Chrome and Docker available. Optional Whisper is absent and not required because this film uses authored caption copy. The machine reported low free memory, so renders use two workers.
- `hyperframes lint`: 0 errors, 0 warnings.
- `hyperframes validate`: no console errors; 30/30 text elements pass WCAG AA.
- `hyperframes inspect --samples 15 --json`: 0 layout issues across 15 samples.
- Animation map: 190 tweens, 100 mapped, 90 micro-tweens skipped. Reviewed all flags. Offscreen flags are the intentional seal wipe and footage push crops; fast flags are 160ms caption exits; collision flags are full-frame wrappers; dead zones are deliberate evidence-reading holds over live product footage.
- Draft: `video/out/body-double-draft.mp4`, 102.0s, 1920x1080, 30fps H.264 + 48kHz stereo AAC.

## Full-film review

- Opening thesis is readable within eight seconds.
- Story order remains breach → preserve production → isolated twin → sealed investigation → evidence → human approval → teardown.
- Product footage and captions remain synchronized at all scene boundaries.
- Caption copy stays within safe margins and no text clips or overlaps.
- Architecture scene distinguishes production, snapshot and twin and makes containment legible.
- The repeated gold-edge wipe is consistent and restrained; holds are intentional reading time, not dead air.
- Every technical claim remains traceable to the V1 claims ledger and captured product behavior.
- Renderer verification exposed V2 capture files whose real 960x540 browser capture occupied the upper-left quadrant of a gray 1920x1080 canvas. Every source clip was normalized by cropping that real quadrant and upscaling it to 1920x1080; the final delivery is frame-checked after rendering.
- Initial mix measured -35.6 LUFS and was materially too quiet. The music master was corrected to -22.9 LUFS integrated with -3.9 dBFS true peak before the composition bus, retaining conservative SFX levels and final limiters.
