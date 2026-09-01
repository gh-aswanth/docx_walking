# examples/data

The worked example, shared by [`examples/`](../) and [`tests/`](../../tests/).

| File | What it is |
| --- | --- |
| `Sample_Software_License_Agreement.docx` | a 92-paragraph SaaS agreement: 12 numbered sections, two signature tables, three exhibits |
| `action_items.json` | a 29-item customer-side plan that exercises **every** action type in `ACTION_SCHEMA` and every field in `ACTION_FIELDS` |

`action_items.json` names its contract by bare filename in the `document` field,
resolved beside the plan, so the two move together as a pair.

Three tests hold this pair honest:

- `test_demo_plan_covers_every_action_type` — the plan must not lose coverage
- `test_demo_plan_uses_every_action_field` — every advertised field is demonstrated
- `test_demo_plan_applies_cleanly` — all 29 items must actually land on the contract,
  not merely validate

So editing either file will fail the suite if it stops being a complete worked
example.
