# WF1 — mus-engine, first rung: samples → mix → master, renders smoke.mus

GOAL. The render FACE begins: a deterministic offline engine over the
ScoreGraph covering the sampler core. NOT in scope: synth, transforms,
quotes, filters, reverb sends (the room), swing (annotation applied =
straight for now), sidechain. Refuse loudly (typed) on out-of-scope
constructs — never render a silent approximation.

DELIVERABLE (`mus-rs/crates/mus-engine`; deps allowed: hound (wav I/O),
rubato (resampling); nothing else):
1. Pack loading: instrument.json manifest; wav samples via hound (the pack
   is all wav). f0 from manifest; `s=` selection; `off=`; `reverse`.
2. Varispeed via rubato (document the chosen quality profile); envelope
   (atk/rel defaults 0.003/0.035 with the reference's shaping exponents);
   ART_SHORTEN/gate cuts; dynamics dB map; ART_GAIN; gain param; equal-
   power pan with sweep support (`pan=a->b`); one-shot slot semantics.
3. Bar map (tempo/meter changes) shared with WD's layout — extract to a
   common module if WD landed one; else create `mus-graph::timing` and
   note it for WD.
4. Mix to stereo f32; master: the reference's RMS-target + windowed
   limiter + tanh + final RMS/ceiling landing (port `master()` faithfully;
   its comments explain why each half exists).
5. `mus render <score> -o out.wav --json` in mus-cli emitting a receipt:
   {schema:"mus.audio.render-receipt.v1", renderDigest: sha256(wav bytes),
   sourceDigest, logDigest?: null (text-adopted), headSelection: "sole"
   (no contested lineages in corpus), engineVersion, peakDbfs, rmsDbfs,
   wallSeconds}. A contested lineage in input → receipt names the chosen
   head's version id per lineage (R4).
ACCEPTANCE:
- renders `aigua/smoke.mus` (46 events, sampler-only) to a wav whose
  duration matches the Python render's ±1ms and whose per-second RMS
  envelope correlates > 0.99 with the Python render of the same score
  (test may spawn the Python renderer once and cache the wav in target/;
  mark `parity_`). Sample-exactness is NOT required (different
  resamplers); the correlation floor is the honest bar.
- refuses `aigua/aigua_1568.mus` with a typed UnsupportedConstruct error
  naming the first offending construct (synth).
- deterministic: two renders byte-identical; receipt digests equal.
