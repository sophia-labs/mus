import Lake
open Lake DSL

package «mus-formal» where
  -- pure-core, NO dependencies — the Garden ontology-to-lean convention:
  -- `lake build` fetches nothing. mathlib arrives only when the holonomy
  -- package needs real analysis, as its own deliberate upgrade.

@[default_target]
lean_lib «MusFormal» where
  globs := #[.submodules `MusFormal]
