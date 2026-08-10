# mus CLI

`mus check` is the Rust, effect-free compile/check face. It emits
`mus.audio.check-report.v1` and accepts `--base DIR` for resolving pack,
gesture, and tape artifacts independently of the score path.

## Atril swap

Atril can use this checker at the existing seam with:

```sh
MUS_CHECK_CMD="/Users/vera/dev/sophia/mus/mus-rs/target/release/mus check"
```

The Python checker remains the migration oracle while Rust parity is verified.
