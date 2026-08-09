//! mus-notation — the TEXT FACE's lexical layer (workstream W-B of
//! `sophia/plans/mus-mo-language-20260809.md`).
//!
//! REFRAMED 2026-08-09: mus text is not the truth of a score; it is the
//! most-honored *face* of a Meaningful Object whose mergeable source is an
//! op-log (see `mus-oplog`) and whose operative body is a projected
//! ScoreGraph (see `mus-graph`). This crate will hold `parse` (text → graph
//! proposal) and the lexer beneath it. The Python implementation is a
//! *migration validator*, not a definition: the 3,604 oracle vectors in
//! `tests/vectors/` (generated from the reference implementation over the
//! whole corpus) are the floor for lexical compatibility, and deliberate
//! divergences are vocabulary decisions, recorded, never accidents.
//!
//! Status: vectors laid; lexer implementation is W-B for the worker line.

pub const VECTORS_NOTE: &str =
    "tests/vectors/{tokens,bars}.json — oracle-generated lexical floor (3,604 tokens)";
