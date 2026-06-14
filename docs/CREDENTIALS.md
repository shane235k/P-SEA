# Developer & Testing Credentials

Use the following credentials to access the SplitAudit application.

## Seeded Users

All seeded accounts share the password: `password123`

| Name | Email (Username) | Role | Status / Details |
|---|---|---|---|
| **Aisha** | `aisha@example.com` | `ADMIN` | Creator of the Shared Flat group |
| **Rohan** | `rohan@example.com` | `MEMBER` | Active member of the Shared Flat group |
| **Priya** | `priya@example.com` | `MEMBER` | Active member of the Shared Flat group |
| **Meera** | `meera@example.com` | `MEMBER` | Joined 2026-01-01, Left 2026-03-31 (Inactive) |
| **Sam** | `sam@example.com` | `MEMBER` | Joined 2026-04-15 (Active) |

## Seed Command

If you need to reset the database and re-seed the test data, run the custom Django management command:

```powershell
python manage.py flush --no-input
python manage.py seed_data
```
