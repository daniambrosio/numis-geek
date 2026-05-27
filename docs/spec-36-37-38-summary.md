# Specs 36 / 37 / 38 — implementation summary (2026-05-26)

> Long unattended session: user dispatched 3 specs and went to sleep. I
> implemented in the order they recommended (37 → 36 → 38) and resolved
> every interview question autonomously following the spec's suggested
> answer. Each spec doc has an "Alignment decisions" section with the
> full list.

## Status

| Spec | Title                                  | Status                | Tests       |
|------|----------------------------------------|-----------------------|-------------|
| 37   | Composer Attachments & Edit Mode       | ✅ Done                | +10 backend / +6 frontend |
| 36   | Options Entry Points                   | ✅ Done                | +7 frontend (backend pre-existing from Spec 17) |
| 38   | Snapshot Upload Extraction (LLM)       | ✅ Done (V1)           | +10 backend / +6 frontend |

Final counts: **370 backend tests · 113 frontend tests · `npm run build`
clean.**

## What's in the app vs what's deferred

### Spec 37 — in scope, delivered

- `<NotesAttachmentsField>` reusable component (paste/drag/click + MIME
  whitelist + 10 MB cap).
- Integrated into `MovementComposer` and `DistributionComposer`.
- Audit diff helper (`utils/audit_diff.py`) — PUT endpoints record only
  changed fields, with Decimal comparison by value (not string).
- "Salvar alterações" label when editing.
- Persisted attachments list in edit mode, with soft-delete on click.

### Spec 37 — out of scope (deferred)

- **TransactionComposer / CardTxComposer** — they don't exist in the
  app yet (placeholders in `NovoButton`). When they ship, plug the
  same `<NotesAttachmentsField>` in.
- **ComposerProvider.edit()** — the existing per-page state
  (`setEditing(item); setComposerOpen(true)`) already works; lifting to
  a provider would be premature.

### Spec 36 — in scope, delivered

- `NovoButton` got the 8th item "Opção" (between Lançamento and Provento).
- `OptionModal` is now standalone — `underlying` is optional, picker
  appears when missing (filter STOCK/REIT/ETF, sort A-Z).
- "Salvar e abrir outra" button — keeps underlying + optionType, focuses
  back to ticker, shows toast.
- `MovementComposer` switches to a 2×2 lifecycle grid (`SELL_TO_CLOSE /
  BUY_TO_CLOSE / EXERCISED / EXPIRED`) when the selected asset is an
  OPTION. EXERCISED/EXPIRED dispatch to the dedicated backend endpoints
  via `onOptionLifecycleSaved` callback.
- `docs/compound-create-pattern.md` documents the recipe for the next
  compound-create class (Renda Fixa, Fundos).

### Spec 36 — out of scope (deferred)

- **Composer dedicado de Renda Fixa** (FIXED_INCOME compound) — explicit
  out-of-scope.
- **Roll de opção** (close + open in one gesture) — separate spec.
- **Contextual default in `inferDefault`** — current 8-item dropdown is
  good enough; adding dynamic suggestions complicates `defaultNovoItem`
  without clear payoff.

### Spec 38 — in scope, delivered (V1)

- `ExtractionJob` model + migration. Tracks status lifecycle, LLM
  metadata, cost, extracted JSON, and user edits.
- `ANTHROPIC` added to `IntegrationProvider` enum.
- `integrations/llm.py` with `LLMClient` Protocol (mockable),
  `AnthropicClient` (lazy-imports the SDK), `set_llm_client` injection
  hook, and a robust `parse_json_block` that survives ```json fences.
- 5 templates: `SCREENSHOT_PRICE` and `BROKER_POSITION` production-ready;
  `BROKER_INCOME`, `B3_TRADE_NOTE`, `FGTS_BALANCE` scaffolded.
- 4 endpoints: `POST /extractions`, `GET /extractions/{id}`,
  `POST /extractions/{id}/confirm`, `POST /extractions/{id}/reject`.
- Confirm applies SCREENSHOT_PRICE / BROKER_POSITION to
  `Asset.current_price` and resolves the linked SnapshotPendency.
- `<ExtractionUploadModal>` (4-stage flow), `<ConfidencePill>`, wired
  into `PendencyPanel` (replacing the stub `window.prompt`).
- `docs/extraction-prompts.md` documents how to add new hints and
  monitor cost via SQL.

### Spec 38 — out of scope (deferred to V2)

- **Async + APScheduler worker** — sync is enough for one-at-a-time
  pendency uploads.
- **Robust PDF→image conversion** (`pypdfium`/`pdf2image`) — V1 falls
  back to text decode or raw bytes.
- **Apply logic** for BROKER_INCOME, B3_TRADE_NOTE, FGTS_BALANCE —
  schema exists but `_apply_payload` returns an "not yet implemented"
  error.
- **Multi-asset detection** in screenshots — V1 is 1 ticker.
- **PII redaction** before sending to Anthropic — documented risk.
- **Admin observability page** `/admin/extractions` — cost lookup via
  SQL for now.

## Assumptions I made (when the spec was ambiguous or the user couldn't be asked)

1. **Spec 37 — partial-fail UX**: when uploading 4 attachments and 1
   fails after the record is saved, the record stays and an amber
   warning is shown. User can re-open and retry.
2. **Spec 37 — no "discard pending drafts?" confirmation** on Esc/X.
   Drafts are in-memory; the cost of dropping them is low.
3. **Spec 36 — icon for "Opção"**: `Sigma` from lucide-react. `trending-up`
   and `sparkles` were already used elsewhere; `Sigma` reads
   "compound-create" visually.
4. **Spec 36 — no confirmation dialog before EXERCISED submit** — the
   backend operation is atomic, the audit log covers it, and adding a
   confirm slows the weekend-batch use case.
5. **Spec 38 — model**: `claude-sonnet-4-5`. Best quality/cost for a
   structured-extraction task.
6. **Spec 38 — hint routing on GENERIC**: alias to BROKER_POSITION
   until a classifier is built. The output schema validation will
   surface mismatches.
7. **Spec 38 — Anthropic SDK installation**: marked as optional
   (`[project.optional-dependencies] llm`). The runtime fails clearly
   if the SDK isn't there and no mock is injected.
8. **Spec 38 — chosen approach for sync vs async**: sync. Spec
   recommended sync as the V1 simplicity win; I agreed.
9. **Spec 38 — confidence aggregation for list-based hints**: average
   the per-row `confidence`. Documented in `_overall_confidence`.

## Migration safety

- `numis_geek.db.bak-before-38` captured before applying the Spec 38
  migration.
- The migration only ADDS a table and EXTENDS an enum — no destructive
  changes.

## Files added / changed

### Backend

- `src/numis_geek/utils/audit_diff.py` (new)
- `src/numis_geek/models/extraction_job.py` (new)
- `src/numis_geek/integrations/llm.py` (new)
- `src/numis_geek/services/extraction.py` (new)
- `src/numis_geek/services/extraction_templates/__init__.py` (new)
- `src/numis_geek/api/routes/extractions.py` (new)
- `alembic/versions/c3d4e5f6a7b8_extraction_job.py` (new)
- `src/numis_geek/models/__init__.py` (export ExtractionJob et al.)
- `src/numis_geek/models/integration_credential.py` (+ ANTHROPIC enum value)
- `src/numis_geek/api/app.py` (register extractions router)
- `src/numis_geek/api/routes/asset_movements.py` (audit diff in PUT)
- `src/numis_geek/api/routes/distributions.py` (audit diff in PUT)
- `pyproject.toml` (optional `llm` dep)
- `tests/test_audit_diff.py` (new) · `tests/test_asset_movements.py`
  (+1 diff test) · `tests/test_extraction.py` (new) ·
  `tests/test_extractions_route.py` (new)

### Frontend

- `src/components/NotesAttachmentsField.tsx` (+ test)
- `src/components/MovementComposer.tsx` (notes field + OPTION lifecycle + tests)
- `src/components/DistributionComposer.tsx` (notes field)
- `src/components/OptionModal.tsx` (standalone, picker, save-and-new + tests)
- `src/components/AppLayout.tsx` (NovoButton + Opção)
- `src/components/PendencyPanel.tsx` (real ExtractionUploadModal)
- `src/components/ExtractionUploadModal.tsx` (new + test)
- `src/components/ConfidencePill.tsx` (new + test)
- `src/pages/AssetMovements.tsx` (compose=option, edit attachments, lifecycle refresh)
- `src/pages/Distributions.tsx` (edit attachments)
- `src/lib/api.ts` (Spec 19 + Spec 38 endpoints + types)

### Docs

- `docs/compound-create-pattern.md` (new)
- `docs/extraction-prompts.md` (new)
- `docs/spec-36-37-38-summary.md` (this file)
- `specs/36/37/38.md` (Status flipped to ✅ Done + Alignment decisions)
