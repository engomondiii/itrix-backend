# Client website revisions October 27

Implements Round 1 (October 23), Round 2 (October 24), and the requested assistant and brand updates. The Round 2 CEO messages retain every supplied paragraph in order.

| Request | Implementation |
| --- | --- |
| R1 1 and 14 | ASTOP CTA and cross-page desktop/mobile navigation restore the homepage section after hydration, with sticky-header clearance. ASTOP topic is preserved. |
| R1 2 | Korean and English /partnership pages submit through the existing consent, CAPTCHA, persistence and email flow; distinct route and type appear in admin records. |
| R1 3 | Enter submission cancels the default action and stops bubbling; Shift+Enter and IME input retain their existing behavior. Chromium and Firefox regression coverage added. |
| R1 4 | Embedded assistant arrival and conversation layouts omit duplicated identity, language and account controls; standalone account routes remain available. |
| R1 5 | ASTOP availability heading and copy explicitly use #F8FAFC. Store launch gating remains intact. |
| R1 6–13 | Requested Korean/English sentence and version-label removals, Korean visit-purpose wording, Judge/CIA correction, and patent count alignment. |
| R2 1 | Terms effective date October 24, 2026 in both languages; force majeure and jurisdiction text retained. |
| R2 2 | Full supplied CEO messages, bold headline, signature, and existing mobile text sizes. |
| Additional requests | Wider responsive embedded chat; Ask itriX labels; approved vector logos across website/dashboard; versioned OG/Twitter image and refreshed icons. |

## Merge and deployment

Merge backend first, then web and dashboard. Backend accepts two additional inquiry fields; there are no database migrations, new environment variables or Knowledge Core ingestion steps for these presentation revisions. Existing store-release rules and evidence qualifications in the Knowledge Core are unchanged.

The existing DigitalOcean proxy needs no change. New pages use normal website paths. Social previews use /og-image-v31-20261027.png; previously shared KakaoTalk messages may retain cached previews until KakaoTalk refreshes them. Verify a fresh share after deployment.

## Validation

Production builds and TypeScript checks passed for web and dashboard. Lint has no errors; existing warnings are not release blockers. Backend website suite: 15 passed, including authenticated retrieval of a partnership submission. Origin-security unit tests passed. Browser checks are in playwright.revisions.config.ts and the GitHub workflow; local browser processes are blocked by the execution environment, so their outcome must be read from CI.
