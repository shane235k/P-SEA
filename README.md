# SplitAudit - Shared Expense Manager with Anomaly Detection

SplitAudit is a production-quality, highly auditable Django-based split-expense management application designed to ingest messy real-world CSV logs, detect and explain financial anomalies, and maintain traceable debt calculations.

---

## 1. Tech Stack
* **Core**: Python 3.12, Django 6.0.6
* **Database**: SQLite (Development) / PostgreSQL-ready (Production)
* **Analytics**: Pandas (Optional / in requirements), Decimal arithmetic
* **Styling**: Bootstrap 5 + Bootstrap Icons

---

## 2. Key Features
* **Email-Based Authentication**: Admin and Member roles.
* **Dynamic Group Memberships**: Tracks timeline entries (`joined_at` and `left_at`) to ensure users never owe money for dates outside their active membership.
* **Explainable Balance Engine**: Computes net balances, resolves minimized peer payments using greedy debt simplification, and generates traceable ledger statements.
* **16-Policy CSV Auditing**: Identifies currency mismatches, ambiguous dates, name aliases, conflicting duplicates, and percentage errors, providing staging views for admin corrections.

---

## 3. Local Installation & Setup

1. **Clone/Navigate to the workspace**:
   Make sure you are in the root directory.

2. **Install Dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

3. **Run Migrations**:
   ```bash
   python manage.py makemigrations accounts groups expenses settlements imports
   python manage.py migrate
   ```

4. **Seed Initial Database**:
   Populates the database with system participants (Aisha, Rohan, Priya, Meera, Sam, Dev, Kabir) and group memberships.
   ```bash
   python manage.py seed_data
   ```

5. **Start Dev Server**:
   ```bash
   python manage.py rundev
   # or standard:
   python manage.py runserver
   ```

---

## 4. Default Seed Credentials

Every user's password is `password123`.

| User | Email | System Role | Group Membership Bounds |
|---|---|---|---|
| **Aisha** | `aisha@example.com` | **Admin** | Joined 2026-01-01 (Active) |
| **Rohan** | `rohan@example.com` | Member | Joined 2026-01-01 (Active) |
| **Priya** | `priya@example.com` | Member | Joined 2026-01-01 (Active) |
| **Meera** | `meera@example.com` | Member | Joined 2026-01-01, Left 2026-03-31 |
| **Sam** | `sam@example.com` | Member | Joined 2026-04-15 (Active) |

*Guests (Auto-Created External Participants)*: **Dev**, **Kabir**.

---

## 5. Execution of Unit Tests

Run the full backend engine test suite with:
```bash
python manage.py test expense_manager.apps.expenses
```
All tests should pass.
