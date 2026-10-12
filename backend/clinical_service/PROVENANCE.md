# Module provenance

Source: `clinical-ie-handover-0.2.0-research.zip`

SHA-256: `7d1864da63dace04a2b9d61b4b93a96b5c6b81b3b5eb3ee6ac6031693418fd8d`

70 files under `vendor/clinical-ie` are byte-identical to the supplied module. The selected runtime subset includes source, bundle metadata/assets, reference index, requirements and handover documentation. Research training datasets, notebooks and experiment outputs were not copied into the backend. Upstream documentation may refer to those omitted research files.

Two neural weights listed in the original IE manifest are absent from the supplied archive. See the root `CLINICAL_MULTIMODAL_UPDATE_VI.md`. No weights were fabricated or substituted; rule fallback remains disabled.

The HTTP adapter and job integration are new files outside the vendor directory. Runtime dependencies remain pinned by the original module requirements, installed in a separate Python 3.12 environment.
