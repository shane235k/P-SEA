# DECISIONS.md - Architecture and Engineering Decisions

This document outlines the major architectural design choices made during development.

---

## 1. Staging Importer vs In-Place Importer

* **Problem**: Real-world CSV uploads are messy, corrupt, or contain conflicts. Importing directly into final ledger tables can cause partial imports, database pollution, or database rollbacks.
* **Alternatives Considered**:
  1. *Direct Insertion*: Parse row-by-row and save straight to `Expense` / `Settlement` models, failing or raising exceptions.
  2. *Draft-Only Insertion*: Create `Expense` objects marked as `DRAFT` for every row, making changes in place.
  3. *Staging Tables (Staging Row + Anomalies)*: (Chosen) Load all CSV rows into `ImportRow` as raw strings, compute anomalies into `ImportAnomaly`, and staging user resolutions.
* **Decision**: We chose **Staging Tables**.
* **Reasoning**: It guarantees that the database is never polluted with partially imported files or draft records that fail other validations. It allows the admin to edit cell values in a temporary area, approve auto-fixes, and reject rows before committing. Furthermore, it keeps a complete, auditable log of the "original raw value" alongside the "final committed value" for compliance.

---

## 2. Participant vs User Account Separation

* **Problem**: Splitwise-style groups often contain guests or temporary visitors (e.g., "Dev" visiting for the weekend, "Kabir" participating for a single day) who do not have registered accounts.
* **Alternatives Considered**:
  1. *Forced Accounts*: Require every name in the CSV to have a fully registered `User` account with email/password.
  2. *Separate Participant Model*: (Chosen) A separate `Participant` model that represents a person. It optionally links to a `CustomUser` via a OneToOne relationship.
* **Decision**: We chose the **Separate Participant Model**.
* **Reasoning**: This cleanly supports guest/external participants. When "Dev" appears in the CSV splits, the importer automatically creates a `Participant(name="Dev", is_external=True)`. If Dev later registers, an administrator can link his new user profile to this pre-existing participant ledger, preserving his balance history.

---

## 3. Dynamic Membership Time Bounds

* **Problem**: Group membership changes dynamically (e.g., Meera leaves on 2026-03-31, Sam joins on 2026-04-15). A member must not owe money for expenses that occurred before joining or after leaving.
* **Alternatives Considered**:
  1. *Simple Split Exclusions*: Depend solely on the CSV's `split_with` column to exclude members.
  2. *Hard Calculator Validation*: (Chosen) Enforce that the date of any active expense must fall between a member's `joined_at` and `left_at` bounds. If not, the split is flagged as a membership violation, and the calculation engine excludes them from liability for splits on that date.
* **Decision**: We chose **Hard Calculator Validation**.
* **Reasoning**: This provides two layers of safety. First, it flags violations during import (e.g., Meera still included in splits after leaving). Second, it ensures that even if an invalid split is committed, the calculation engine protects the user from financial liability on dates they were not members.

---

## 4. Rounding Discrepancy Adjustments

* **Problem**: Division of expenses can result in fractional cents (e.g., ₹100 split equally among Aisha, Rohan, and Priya yields ₹33.3333... each). Summing these splits gives ₹99.99, leaving a ₹0.01 discrepancy.
* **Alternatives Considered**:
  1. *Float standard types*: Use python floats (prone to representation errors like `33.333333333333336`).
  2. *Decimal representation with remainder allocation*: (Chosen) Use standard python `Decimal` with `ROUND_HALF_UP`, sum the split results, calculate the discrepancy against the total amount, and adjust the first participant's share by the remainder.
* **Decision**: We chose **Decimal representation with remainder allocation**.
* **Reasoning**: Financial ledgers must balance to the exact cent. Float representation is unsafe for financial data. Allocating the remainder ensures the sum of splits is mathematically equal to the expense total, keeping net balances accurate.

---

## 5. Debt Simplification Engine

* **Problem**: In a group of many members, direct peer-to-peer debts result in a large, confusing list of transactions.
* **Alternatives Considered**:
  1. *Direct Transfer Matrix*: Every borrower pays the exact payer of each expense.
  2. *Greedy Net Position Matching*: (Chosen) Calculate each member's net position, separate into positive (creditors) and negative (debtors) lists, and match the largest debtor with the largest creditor iteratively.
* **Decision**: We chose **Greedy Net Position Matching**.
* **Reasoning**: This minimizes the total number of peer-to-peer payments. It is mathematically equivalent to settling the direct debts, highly intuitive, and standard in peer-sharing products.
