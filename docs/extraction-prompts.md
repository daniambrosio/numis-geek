# Extraction prompts — Spec 38

> Lives in `src/numis_geek/services/extraction_templates/__init__.py`.
> One `Template` per `ExtractionSourceHint`. Each template has a prompt
> version, a system prompt, a user prefix, and a pydantic
> `output_model`.

## Hints shipped in V1

| Hint                 | Status        | Schema (key fields)                                |
|----------------------|---------------|----------------------------------------------------|
| `SCREENSHOT_PRICE`   | **Live**      | `ticker`, `price`, `currency`, `confidence`        |
| `BROKER_POSITION`    | **Live**      | `positions[]` with ticker/qty/price/confidence     |
| `BROKER_INCOME`      | Scaffold only | `events[]`; prompt is TODO before production       |
| `B3_TRADE_NOTE`      | Scaffold only | `trades[]`; prompt is TODO before production       |
| `FGTS_BALANCE`       | Scaffold only | `balance_brl`, `confidence`; prompt minimal        |
| `GENERIC`            | Aliased       | Routes to `BROKER_POSITION` until a router is built |

## How extraction flows

1. User clicks "Upload extrato" on a SnapshotPendency.
2. `<ExtractionUploadModal>` posts the file as an Attachment (Spec 19).
3. `POST /extractions` creates an `ExtractionJob` and runs the LLM **inline**
   (V1 sync mode — files are small, ~10-30s).
4. `services/extraction._read_attachment_payload` converts the attachment
   to either an image blob (PNG/JPEG/WEBP) or text (CSV; PDF falls back
   to text-or-image).
5. `Anthropic` SDK is called with the template's system prompt + a user
   prompt that prepends the user_prefix and the document text/image.
6. The reply is parsed by `parse_json_block` (handles ```json fences and
   prose preambles), then validated against the template's pydantic
   model.
7. `ExtractionJob.status = EXTRACTED` and the modal swaps into review.
8. User clicks "Confirmar e aplicar" → `POST /extractions/{id}/confirm`.
   The service writes the data (Asset.current_price for SCREENSHOT_PRICE
   and BROKER_POSITION), resolves the linked SnapshotPendency, and
   records audit log entries.

## Cost tracking

Each `ExtractionJob` row records `input_tokens`, `output_tokens`, and
`cost_usd` (computed via the pricing table in `integrations/llm.py`).
No admin dashboard yet — query SQL directly:

```sql
SELECT date(created_at) AS day,
       COUNT(*) AS jobs,
       SUM(cost_usd) AS spend_usd
FROM extraction_job
WHERE status = 'CONFIRMED'
GROUP BY 1
ORDER BY 1 DESC;
```

## Adding a new hint

1. Define `<HintName>Output` (pydantic) in `extraction_templates/__init__.py`.
2. Build a `Template(version=..., system=..., user_prefix=..., output_model=...)`.
3. Add it to the `TEMPLATES` dict.
4. Extend `services/extraction._apply_payload` with a `_apply_<hint>` helper
   that knows how to write the data to the domain model.
5. Write a test like `tests/test_extraction.py::test_confirm_<hint>...`
   that mocks the LLM via `set_llm_client(...)`.
6. Bump `prompt_version` on the template whenever you change the prompt.

## Test hook

`numis_geek.integrations.llm.set_llm_client(client)` swaps the global
client. The tests use a `FakeLLM` that returns canned JSON. Reset between
tests with the `autouse` fixture defined in `test_extraction.py`.

## Known limitations (V1)

- **PDF support is naive** — `_read_attachment_payload` tries UTF-8 decode
  and falls back to the raw bytes as image. Scanned PDFs may need
  `pypdfium`/`pdf2image` later.
- **No background worker** — sync extraction blocks the request for the
  LLM round-trip. APScheduler-based async is scoped for V2 when batch
  uploads land.
- **No PII redaction** — CPF/account numbers are sent verbatim. The
  Anthropic API doesn't train on API content by default, but document
  this risk before shipping a multi-user VPS.
- **Single-ticker screenshots only** — `SCREENSHOT_PRICE` assumes one
  asset per image. Multi-asset detection is V2.
