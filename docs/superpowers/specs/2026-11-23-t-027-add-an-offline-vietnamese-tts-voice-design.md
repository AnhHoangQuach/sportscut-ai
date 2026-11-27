# T-027: Add an offline Vietnamese TTS voice-over mixed with ducking via `--voiceover`

Request R-005. Plan: `docs/superpowers/plans/2026-11-23-t-027-add-an-offline-vietnamese-tts-voice.md`.

## Product Owner request

Bình luận AI: tạo tiêu đề, caption, hashtag, thậm chí lồng tiếng bình luận tiếng Việt.

## Goal

Add a `sportscut[tts]` extra using Piper, an offline CPU TTS that fits the 10-minute budget. Its Vietnamese voice model downloads on first use or through `sportscut download-models` into the user cache and is never committed. A `Synthesizer` protocol keeps the engine swappable. Add `commentary/voiceover.py`: it synthesizes each script line, places it at its time, and mixes it with ffmpeg, lowering the original audio by about 12 dB while speech plays (volume envelope or sidechaincompress). It writes `clip_NN.vo.mp4`, plus the vertical version when `--vertical` is set, and leaves the original clips untouched. Tests use a fake synthesizer that emits a tone: the output duration equals the clip duration within 0.1 s, the tone is present at the scripted times, and the original-audio RMS drops by at least 8 dB during speech and is unchanged elsewhere. A real Piper smoke test is skipped when the extra is missing. Assumptions: a single default voice with no voice options (YAGNI). Without the extra, `--voiceover` exits with a clear install hint.

## Acceptance criteria

- AC1 pyproject.toml optional-dependencies has `tts = ["piper-tts>=1.3"]`. The api, youtube, llm, asr and dev lists are unchanged, and dev does not contain piper. `git ls-files '*.onnx' '*.onnx.json' '*.mp4' '*.wav'` prints nothing.
- AC2 In a fresh interpreter, `import sys, sportscut.cli, sportscut.pipeline, sportscut.commentary.voiceover; print('piper' in sys.modules, 'onnxruntime' in sys.modules)` prints `False False`. sportscut/commentary/voiceover.py does not contain the string 'subprocess'. The modules importing subprocess are still exactly ['events/incidents.py', 'media.py'], and pipeline.py and cli.py do not contain 'subprocess'.
- AC3 `voice_track(lines, fake, duration)` with a fake of sample_rate 1000 whose synthesize returns 3000 ones (3.0 s):
- `[(1.0,'a'),(2.0,'b')]`, duration 10.0 → spoken `[(1.0,4.0),(4.0,7.0)]` (the second line is delayed, with no overlap).
- `[(8.0,'x')]` → spoken `[(8.0,10.0)]`, and the track length is exactly 10000.
- `[(10.0,'x')]` and `[]` → spoken `[]`, an all-zero track, and synthesize is never called.
- Samples outside the spoken intervals are 0. Values are clipped to [-1, 1]. The dtype is float32.
- A synthesize that raises RuntimeError('boom') raises `SynthesisError` with message `text-to-speech failed: boom`.
- AC4 duck_intervals pads by 0.15 s, clamps to [0, duration] and merges overlapping or touching intervals:
- `duck_intervals([(1.0,2.0),(2.2,3.0)],10.0) == [(0.85,3.15)]` (±1e-9).
- `duck_intervals([(0.1,0.5)],10.0) == [(0.0,0.65)]`.
- `duck_intervals([(9.0,10.0)],10.0) == [(8.85,10.0)]`.
- `duck_intervals([],10.0) == []`.
- AC5 mix_filter([(1.85, 3.00714), (5.85, 7.29286)]) equals exactly `[0:a]aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo,volume=volume=0.251189:enable='between(t,1.850,3.007)+between(t,5.850,7.293)'[bg];[1:a]aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo[vo];[bg][vo]amix=inputs=2:duration=first:normalize=0[a]`. `mix_filter([])` gives the same string without `,volume=...`.
- AC6 media.mix_audio(clip, voice, graph, dest), with subprocess.run monkeypatched, is called once with exactly `[ffmpeg, '-v','error','-nostdin','-y','-i',clip,'-i',voice,'-filter_complex',graph,'-map','0:v:0','-map','[a]','-c:v','copy','-c:a','aac','-b:a','128k','-movflags','+faststart',dest]` and `capture_output=True, check=False`, and returns Path(dest). A missing clip or voice file raises MediaError 'media file not found: ...' without running ffmpeg. A non-zero exit raises MediaError starting with 'ffmpeg failed for'.
- AC7 Real-ffmpeg mix. The source is a 10 s clip (160x120 video, audio = 300 Hz sine, AAC). The fake synthesizer has sample_rate 22050 and returns a 2000 Hz sine at amplitude 0.3 of length round(script.speech_seconds(text)*22050). `make_voiceover([(2.0,'Vào! Bàn thắng!'),(6.0,'Tỉ số 1-0.')], fake, [(clip, tmp/'clip_01.vo.mp4')])` writes the vo file and returns `[dest]`. Measured on media.extract_audio, with band_rms = RMS after keeping only FFT bins within ±50 Hz of f in the window:
- probe_duration(vo) is within 0.1 s of probe_duration(clip).
- The vo file has 1 video and 1 audio stream.
- 2000 Hz band_rms inside each spoken window shrunk by 0.15 s on both sides is at least 30 dB above that band in [0.5,1.5] and [4.0,5.0].
- 300 Hz band_rms in those spoken windows is at least 8 dB below the same windows of the original clip.
- 300 Hz band_rms in [0.5,1.5], [4.0,5.0] and [8.0,9.5] is within 1 dB of the original.
- The clip's sha256 is unchanged after the call.
- AC8 make_voiceover with two targets, the clip and a second copy, calls fake.synthesize exactly once per script line (2 calls total) and writes both dest files. Each has a duration within 0.1 s of its source.
- AC9 download_voice with XDG_CACHE_HOME=tmp and `_fetch` monkeypatched to write bytes and record calls:
- The first call fetches exactly `[VOICE_URL+'.onnx', VOICE_URL+'.onnx.json']` in that order, with VOICE_URL equal to `https://huggingface.co/rhasspy/piper-voices/resolve/main/vi/vi_VN/vais1000/medium/vi_VN-vais1000-medium`. It returns `tmp/sportscut/piper/vi_VN-vais1000-medium.onnx`.
- A second call fetches nothing.
- A `_fetch` that raises OSError('offline') propagates OSError and leaves no `.onnx` or `*.part` file.
- AC10 With a fake `piper` module in sys.modules (PiperVoice.load records paths and returns a voice with config.sample_rate 22050 whose synthesize(text) yields 2 chunks with audio_float_array) and download_voice monkeypatched to return Path('/cache/v.onnx'):
- `PiperSynthesizer()` neither downloads nor loads.
- Two synthesize calls load exactly once, with '/cache/v.onnx', and each returns the float32 concatenation of the chunks.
- `sample_rate == 22050`.
- `default_synthesizer()` returns a PiperSynthesizer.
- With `sys.modules['piper'] = None`, `default_synthesizer()` returns None.
- AC11 `pipeline.run(burst_video, out, top=1, min_len=4, max_len=6, voiceover=True, synthesizer=fake)` (tone fake, real ffmpeg) writes out/clip_01.script.json (as in T-026) and out/clip_01.vo.mp4, whose duration is within 0.1 s of clip_01.mp4. The entry and highlights.json keys end with `script_file, voiceover_file`, and voiceover_file == 'clip_01.vo.mp4'. With vertical=True (vertical.render_vertical may be monkeypatched to copy the clip), it also writes out/vertical/clip_01.vo.mp4, and the keys end with `script_file, voiceover_file, vertical_voiceover_file` == 'vertical/clip_01.vo.mp4'. The clip's synthesize calls equal its script line count.
- AC12 Pipeline errors and compatibility:
- `run(burst_video, out, synthesizer=fake)` without voiceover raises PipelineError 'synthesizer needs voiceover=True', with no out/clip_01.mp4 created and the fake never called.
- A fake whose synthesize raises RuntimeError('boom') makes run raise PipelineError 'clip_01.mp4: text-to-speech failed: boom'.
- `run(..., voiceover=True)` with synthesizer=None writes no *.vo.mp4, and script_file stays the last key (the T-026 tests pass unedited).
- AC13 CLI cut (cli.run monkeypatched, recording kwargs):
- `cut v.mp4 --out O --voiceover` forwards `synthesizer` equal to the object returned by a monkeypatched voiceover.default_synthesizer, with empty stderr.
- When default_synthesizer returns None, synthesizer=None is forwarded, stderr is exactly `sportscut: notice: voice-over needs the [tts] extra: pip install 'sportscut[tts]'; only the commentary scripts are written\n`, and the exit code is 0.
- Without --voiceover, default_synthesizer is never called and synthesizer=None is forwarded.
- For an entry with file, vertical_file, script_file, voiceover_file and vertical_voiceover_file, stdout lists the 5 paths in that order.
- A PipelineError from run exits 1 with 'sportscut: error: <msg>'.
- AC14 `sportscut download-models --tts`:
- With voiceover.download_voice monkeypatched to return Path('/c/v.onnx'), it exits 0 with stdout exactly `downloaded Piper voice vi_VN-vais1000-medium to /c/v.onnx\n` and does not touch faster_whisper.
- When download_voice raises OSError('offline'), it exits 1 with stderr `sportscut download-models: error: offline\n`.
- `download-models --help` lists --tts.
- `download-models` without --tts keeps every T-022 behaviour (the T-022 tests pass unedited).
- AC15 tests/test_voiceover_piper_smoke.py is skipped (not failed) when piper is not importable (pytest.importorskip) or when download_voice raises OSError. When it runs with the real PiperSynthesizer:
- synthesize('Vào! Bàn thắng!') returns a 1-D float32 array of 0.3-5 s at sample_rate > 0, with max |x| > 0.01.
- After that warm-up, synthesizing the 3 lines of write_script(ClipFacts('goal',23,'Hà Nội FC','Hải Phòng','V.League 2026','1-0'), 30.0) takes < 5 s.
- make_voiceover on a 6 s synthetic clip gives a vo file whose duration is within 0.1 s of the clip.
- AC16 Docs:
- README has `### Lồng tiếng bình luận (--voiceover)` after `### Kịch bản bình luận` and before `## Theo dõi cầu thủ: đo độ chính xác (eval-player)`. It contains `pip install 'sportscut[tts]'`, `sportscut download-models --tts`, `clip_NN.vo.mp4`, `vertical/clip_NN.vo.mp4` and `12 dB`, and no ```json block.
- The README no longer contains 'sẽ có ở task sau', and the eval-crop section is still last and byte-identical.
- The T-026, T-004 and T-022 design specs end with an appended `## Updated by T-027` section that mentions `clip_NN.vo.mp4` (T-026), `synthesizer=None` (T-004) and `download-models --tts` (T-022).
- AC17 No regression:
- `python -m pytest -q` reports 0 failed, with no pre-existing test file edited, deleted or skipped.
- `python -m sportscut eval tests/fixtures/eval --json` f1 equals main.
- `eval-meta tests/fixtures/eval_meta --json` and `--json --script` outputs equal main.
- The commentary script/facts/meta/llm/eval_meta files, export.py, models.py, api.py, vertical.py, subtitles.py, reframe.py, sportscut/web/, tests/conftest.py, tests/fixtures/ and agent-office/ are unchanged against `git merge-base main HEAD`.
- media.py has 0 deleted lines. Any git-scope test is gated to branches starting with office/T-027.

## Out of scope

- Voice, speed, pitch or volume options, multiple voices, or any non-Vietnamese voice.
- Exposing voice-over in the HTTP API or web preview (voiceover_url on /highlights, the T-028 'Lồng tiếng' toggle wiring), and a voiceover option on POST /highlights.
- The LLM script backend in `cut` (the template backend stays as in T-026).
- sidechaincompress, loudness normalisation (EBU R128), limiters or fades on the duck edges.
- Measuring or adapting to Piper's real speaking rate in the script budget (T-026's 3.5 syllables/s stays). Speech that runs long is delayed or truncated, not rewritten.
- Burning the script as subtitles on vo clips, and replacing (rather than mixing with) the original commentary.
- Bundling or vendoring Piper or the voice model, offline installation media, or GPU inference.
- Downloading the voice automatically from `download-models` without `--tts`.

## Decisions

- T-027: Voice-over lives in `sportscut/commentary/voiceover.py`. Its interfaces are the `Synthesizer` protocol (`sample_rate: int`, `synthesize(text) -> float32 mono ndarray`), `voice_track`, `duck_intervals`, `mix_filter`, `make_voiceover(lines, synthesizer, targets)`, `PiperSynthesizer`, `default_synthesizer()` and `download_voice()`. Swapping the TTS engine means writing another Synthesizer, and nothing else changes.
- T-027: Piper (`piper-tts>=1.3`, optional extra `sportscut[tts]`) with the single voice `vi_VN-vais1000-medium`. The voice (.onnx + .onnx.json) is downloaded from rhasspy/piper-voices on Hugging Face into `$XDG_CACHE_HOME/sportscut/piper` (default `~/.cache/sportscut/piper`) on first use or by `sportscut download-models --tts`. It is never committed. piper is imported lazily, and the model is loaded once per PiperSynthesizer.
- T-027: Ducking is a volume envelope, not sidechaincompress: the original audio is multiplied by 10^(-12/20) = 0.251189 on the spoken intervals padded by 0.15 s and merged, and it is untouched elsewhere. Voice and ducked audio are summed with `amix ... normalize=0` at 48 kHz stereo, the video is stream-copied, and the audio is re-encoded to AAC 128k. This makes 'unchanged elsewhere' exact and testable.
- T-027: Each script line starts at its scripted time. When real TTS audio runs longer than the gap, the next line is delayed (speech never overlaps), and audio past the clip end is dropped. The voice track is synthesized once per clip and reused for the vertical copy.
- T-027: All ffmpeg calls stay in media.py (new `media.mix_audio`). voiceover.py, pipeline.py and cli.py do not use subprocess, which keeps the T-018/T-022 importer rule.
- T-027: `pipeline.run(..., voiceover=False, synthesizer=None)`. A synthesizer requires voiceover=True. With a synthesizer it writes `clip_NN.vo.mp4` (and `vertical/clip_NN.vo.mp4` when vertical) and appends manifest keys `voiceover_file` and `vertical_voiceover_file` after `script_file`. With synthesizer=None the behaviour is exactly T-026 (scripts only). Original clips are never modified. Synthesis errors become PipelineError '<clip file>: text-to-speech failed: <exc>'.
- T-027 (deviates from the task's literal wording, recorded on purpose): without the [tts] extra, `cut --voiceover` does not fail. It prints the one-line stderr hint `sportscut: notice: voice-over needs the [tts] extra: pip install 'sportscut[tts]'; only the commentary scripts are written`, still writes the T-026 scripts and exits 0. Reason: the T-026 tests (test_commentary_script::test_cli_cut_voiceover_forwarded_and_printed, test_t026_acceptance::test_ac11_*) require exit 0 for `cut --voiceover` without the extra, and existing tests must not be weakened. This follows the T-022 `--subtitles` notice precedent.
- T-027: The voice download is opt-in through `sportscut download-models --tts`. `download-models` with no flag keeps its exact T-022 output (the T-022 tests pin stdout and stderr).
- T-027: Voice-over quality is measured by the automated band-RMS tests: speech tone present at the scripted times, the original audio ≥ 8 dB lower during speech and within 1 dB elsewhere, and output duration within 0.1 s. A later change to mixing must keep these gates.
- T-027: piper-tts is GPL-3.0. It is an optional extra installed by the user and is never vendored. The README says so.
- T-027: Size budget < 600 changed lines outside docs/superpowers including the Tester file (T-020 precedent). README changes are insert-only except the replaced T-026 sentence 'Âm thanh lồng tiếng sẽ có ở task sau.'.

## Existing specs this task changes

- `docs/superpowers/specs/2026-11-23-t-026-generate-a-timed-vietnamese-commentary-script-design.md`
- `docs/superpowers/specs/2026-11-23-t-004-add-a-pipeline-entry-point-and-design.md`
- `docs/superpowers/specs/2026-11-23-t-022-add-commentary-subtitles-to-vertical-clips-design.md`
