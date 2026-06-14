# AI_USAGE.md - AI Usage Log and Corrections

This document tracks the usage of AI tools during the development of the SplitAudit application.

---

## 1. AI Tools & Prompts Used

* **AI System**: Gemini 3.5 Flash (High) (acting as coding assistant)
* **Key Prompts**:
  * "Create the initial implementation plan for a production-quality expense sharing Django application..."
  * "Write the anomaly detector service in Django, verifying all 16 specific rules..."
  * "Write unit tests for the Split Calculator and the Balance Engine..."

---

## 2. AI Correction Log (3 Cases)

### Case 1: Custom User Model without Username field configuration

* **What the AI Suggested**:
  The AI suggested overriding `AbstractUser` to support email login like this:
  ```python
  class CustomUser(AbstractUser):
      email = models.EmailField(unique=True)
      USERNAME_FIELD = 'email'
  ```
* **Why it was Wrong**:
  Subclassing `AbstractUser` in Django inherits the `username` field by default. If you simply set `USERNAME_FIELD = 'email'` without setting `username = None`, Django's system checks fail with errors indicating that the `username` field conflicts or must be included in `REQUIRED_FIELDS`. Additionally, the default `UserManager` still expects a `username` parameter when running `createsuperuser`.
* **How it was Corrected**:
  We explicitly set `username = None` inside `CustomUser`, and implemented a custom `CustomUserManager` that overrides both `create_user` and `create_superuser` to completely exclude the `username` parameter:
  ```python
  class CustomUser(AbstractUser):
      username = None
      email = models.EmailField(unique=True)
      # ...
  ```

---

### Case 2: Rounding errors using float division for equal splits

* **What the AI Suggested**:
  To calculate equal splits, the AI suggested dividing the amount using Python floats:
  ```python
  share = amount / len(participants)
  ```
* **Why it was Wrong**:
  Floating-point numbers cannot represent decimal values precisely. For example, splitting ₹100 among 3 people resulted in `33.333333333333336`. Summing these floats resulted in rounding discrepancies, making the total sum mismatch the original expense amount. In financial ledgers, this causes balances to leak pennies and fails audit tests.
* **How it was Corrected**:
  We wrapped all monetary values in the `Decimal` type, utilized `ROUND_HALF_UP` for precision, calculated the sum of splits, computed the remainder discrepancy, and allocated it to the first participant:
  ```python
  base_share = round_half_up(amount / Decimal(num_participants))
  # ... adjust for discrepancy ...
  ```

---

### Case 3: Duplicate detection query filtering across groups

* **What the AI Suggested**:
  The AI suggested identifying existing duplicates in the database by filtering solely on amount and date:
  ```python
  dups = Expense.objects.filter(expense_date=date, amount=amount)
  ```
* **Why it was Wrong**:
  This query lacked a filter for the specific `Group`. If an identical expense (same amount and date) existed in an entirely different group (e.g. flatmates vs trip group), the importer flagged it as a duplicate, requiring unnecessary administrative approval or blocking.
* **How it was Corrected**:
  We updated the query to filter explicitly by the current group of the import session, ensuring that duplicate checks are isolated per group:
  ```python
  db_dups = Expense.objects.filter(
      group=group,
      expense_date=res_date,
      amount=res_amount,
      paid_by__name__iexact=res_payer,
      status='ACTIVE'
  )
  ```
