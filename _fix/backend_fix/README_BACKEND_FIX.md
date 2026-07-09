# itriX Backend Fix — qualify response now returns the client-page token

## What this fixes
The Compute Bottleneck Review dead-ended at `/review/preparing`. Root cause: the
qualify endpoint advanced the journey to `CLIENT_PAGE` and minted a capability token,
but **discarded it** — the response had no `capability_token` / `journey_state`, so the
public site never got the token it needs to forward the visitor to `/c/[token]`.

## The change (1 file)
`apps/review/services/qualification_processor.py`
- Captures the `AdvanceResult` from `reveal_client_page(...)` and reads the minted token
  + resulting journey state off `result.reveal`.
- Adds `capability_token` and `journey_state` to `QualificationResult` and to
  `to_dict()`, which now emits **both snake_case and camelCase** keys so the frontend
  contract can never drift again.
- Robust token acquisition: if the reveal is an idempotent no-op (retry / double
  submit) or raises, it re-mints a valid client-page token directly from the lead via
  `reveal_for_state(...)`. A resolvable token is returned whenever a real Lead exists.

## How to apply
From the `itrix-backend` root (the folder with `manage.py`):
```bash
unzip -o itrix-backend-fix.zip -d _fix
bash _fix/APPLY_BACKEND_FIX.sh
```
The script backs up each file it overwrites (`*.bak-<timestamp>`), then restart the app.

## Verified
Booted Django and ran the real review→qualify flow: the response now contains a valid
`capability_token` + `journeyState: CLIENT_PAGE`, and that token resolves through
`GET /journey/{token}/` → `authorizedSurface: client_page`. Retrying qualify (double
submit) still returns a resolvable token.
