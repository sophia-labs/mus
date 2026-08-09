# Aigua v2 working outputs

This directory is the conventional destination for local analysis outputs. The
files are not authoritative merely because they are here; durable identity
comes from a `mus_analysis.store.ResearchObjectStore` receipt.

Useful commands:

```bash
# Independent detector lanes plus reconciliation
mus-analysis segment-audio ../aigua_raw.wav \
  --output segmentation.json \
  --store ../research-object

# Three pitch lanes plus explicit consensus/refusal states
mus-analysis extract-pitch ../aigua_raw.wav \
  --start-seconds 12.464 --end-seconds 12.969 \
  --fmin-hz 700 --fmax-hz 5000 \
  --output event-20-pitch.json \
  --store ../research-object

# Continuous spectral, modulation, FM, and pitch trajectories
mus-analysis analyze-gesture ../aigua_raw.wav \
  --start-seconds 12.464 --end-seconds 12.969 \
  --fmin-hz 700 --fmax-hz 5000 \
  --output event-20-gesture.json \
  --store ../research-object
```

Large generated outputs should remain local until array-artifact and Garden
materialization policy is finalized.
