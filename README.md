# itrix-backend

## Demo data

Populate the database with realistic demo data for a live presentation (leads across
every pipeline stage, NDAs, evaluations, PoCs, follow-up tasks, notifications,
templates, a monthly report, SLA thresholds, and a small team):

```bash
python manage.py seed_demo --flush
```

`--flush` first removes the rows this command owns (the demo users and the leads they
own, plus the demo templates / report — children cascade), so it is safe to re-run.
Without `--flush` the command is idempotent (uses `get_or_create` and the apps' own
creator services), so re-running won't duplicate.

After seeding, log into the dashboard with:

- **Email:** `demo@itrix.ai`
- **Password:** `demo12345`

This account is an ADMIN (permission role) / "Admin" (team role), `is_staff=True`, so
it also works for the Django admin.
