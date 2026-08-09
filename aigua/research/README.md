# Aigua research-object layer

This directory contains the authored contracts for preserving Aigua v1 and
building Aigua v2.

- `aigua-v1-import.json` identifies historical artifacts and known manual
  annotations such as the vehicle-dominated event.
- `profile-registry.json` is the current scientific-question and pipeline
  registry. `historically-imported` profiles preserve v1; `foundation-implemented`
  profiles have executable code; `specified` profiles are designed but not yet
  implemented.
- `descriptor-registry.json` gives exact semantics and caveats for historical
  and new descriptor IDs.

Generated research objects belong in `aigua/research-object/` and are ignored by
Git. They are reproducible from committed source artifacts and the importer.

```bash
python aigua/import_research_object.py \
  --config aigua/research/aigua-v1-import.json

python -m mus_analysis verify --store aigua/research-object
```

The durable store uses content-addressed artifacts and write-once receipts. It
is suitable for later ingestion into a `gardend` project; the generated
`projections/aigua-v1.nt` is the first RDF face.
