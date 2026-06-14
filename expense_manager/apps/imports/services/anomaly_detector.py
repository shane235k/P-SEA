import re
import datetime
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation
from django.conf import settings
from expense_manager.apps.accounts.models import Participant, CustomUser
from expense_manager.apps.groups.models import GroupMembership
from expense_manager.apps.expenses.models import Expense
from expense_manager.apps.imports.models import ImportAnomaly, ImportRow
from expense_manager.apps.expenses.services.split_calculator import round_half_up, parse_split_details

def parse_date_robust(date_str):
    """
    Parses date_str in YYYY-MM-DD, DD/MM/YYYY, MM/DD/YYYY, or Month DD formats.
    Returns (parsed_date, is_ambiguous, message)
    """
    date_str = date_str.strip()
    if not date_str:
        return None, True, "Date is empty"

    # Try YYYY-MM-DD
    try:
        dt = datetime.datetime.strptime(date_str, "%Y-%m-%d").date()
        return dt, False, "Parsed as YYYY-MM-DD"
    except ValueError:
        pass

    # Try DD/MM/YYYY or MM/DD/YYYY
    slash_match = re.match(r'^(\d{1,2})/(\d{1,2})/(\d{4})$', date_str)
    if slash_match:
        part1 = int(slash_match.group(1))
        part2 = int(slash_match.group(2))
        year = int(slash_match.group(3))
        
        # Check if ambiguous (both <= 12)
        if part1 <= 12 and part2 <= 12:
            # Check if identical (e.g. 03/03/2026)
            if part1 == part2:
                # Same day and month, so it's not ambiguous in effect, but let's parse it directly
                return datetime.date(year, part2, part1), False, "Parsed unambiguously (day and month are same)"
            # Otherwise it's ambiguous
            # Default to DD/MM/YYYY (Indian standard)
            try:
                dt = datetime.date(year, part2, part1) # day=part1, month=part2
                return dt, True, "Ambiguous: Could be DD/MM or MM/DD. Defaulting to DD/MM."
            except ValueError:
                pass
        else:
            # Unambiguous
            # If part1 > 12, then it must be day=part1, month=part2
            if part1 > 12:
                try:
                    return datetime.date(year, part2, part1), False, "Parsed as DD/MM/YYYY"
                except ValueError:
                    pass
            # If part2 > 12, then it must be day=part2, month=part1
            if part2 > 12:
                try:
                    return datetime.date(year, part1, part2), False, "Parsed as MM/DD/YYYY"
                except ValueError:
                    pass

    # Try formats like "Mar 14" or "March 14"
    alpha_match = re.match(r'^([a-zA-Z]{3,})\s+(\d{1,2})$', date_str)
    if alpha_match:
        month_str = alpha_match.group(1)[:3].lower()
        day = int(alpha_match.group(2))
        month_map = {
            'jan': 1, 'feb': 2, 'mar': 3, 'apr': 4, 'may': 5, 'jun': 6,
            'jul': 7, 'aug': 8, 'sep': 9, 'oct': 10, 'nov': 11, 'dec': 12
        }
        if month_str in month_map:
            month = month_map[month_str]
            # Use 2026 as default year from context
            default_year = 2026
            try:
                dt = datetime.date(default_year, month, day)
                return dt, True, "Ambiguous: Missing year. Defaulting to 2026."
            except ValueError:
                pass

    return None, True, f"Failed to parse date format: {date_str}"


def make_signature(date_val, payer_val, amount_val, currency_val, split_with_val):
    # Normalize Date
    norm_date = ""
    if isinstance(date_val, datetime.date):
        norm_date = str(date_val)
    else:
        dt, _, _ = parse_date_robust(str(date_val or ''))
        norm_date = str(dt) if dt else str(date_val or '')
        
    # Normalize Payer
    norm_payer = str(payer_val or '').strip().lower()
    
    # Normalize Amount
    norm_amount = ""
    if isinstance(amount_val, Decimal):
        norm_amount = str(round_half_up(amount_val))
    else:
        raw_amt = str(amount_val or '').strip().replace(',', '')
        try:
            val_dec = Decimal(raw_amt)
            norm_amount = str(round_half_up(val_dec))
        except (InvalidOperation, ValueError):
            norm_amount = raw_amt
            
    norm_currency = str(currency_val or '').strip().upper()
    norm_splits = ";".join(sorted([n.strip().lower() for n in str(split_with_val or '').split(';') if n.strip()]))
    
    return (norm_date, norm_payer, norm_amount, norm_currency, norm_splits)

def make_conflict_signature(date_val, payer_val, split_with_val, desc_val):
    norm_date = ""
    if isinstance(date_val, datetime.date):
        norm_date = str(date_val)
    else:
        dt, _, _ = parse_date_robust(str(date_val or ''))
        norm_date = str(dt) if dt else str(date_val or '')
        
    norm_payer = str(payer_val or '').strip().lower()
    norm_splits = ";".join(sorted([n.strip().lower() for n in str(split_with_val or '').split(';') if n.strip()]))
    norm_desc = str(desc_val or '').strip().lower()
    
    return (norm_date, norm_payer, norm_splits, norm_desc)


def detect_anomalies(session):
    """
    Scans staging ImportRow rows for the session and logs ImportAnomaly items.
    """
    rows = session.rows.all().order_by('row_number')
    group = session.group
    
    # Pre-fetch existing registered members of the group to aid validation
    memberships = group.memberships.select_related('user__participant').all()
    group_members_map = {}
    for m in memberships:
        if hasattr(m.user, 'participant'):
            group_members_map[m.user.participant.name.lower()] = m
            
    # All system participants for alias mapping checks
    all_participants = Participant.objects.all()
    participant_name_map = {p.name.lower(): p for p in all_participants}

    # Helper for name normalization
    def normalize_name(name_str):
        if not name_str:
            return ""
        # Look for match in system participants
        cleaned = name_str.strip()
        cleaned_lower = cleaned.lower()
        if cleaned_lower in participant_map_to_proper:
            return participant_map_to_proper[cleaned_lower]
        return cleaned

    participant_map_to_proper = {p.name.lower(): p.name for p in all_participants}

    # Pre-scan rows to detect duplicate records inside the uploaded CSV itself
    # We will build signature maps using current resolved/working values of non-rejected rows
    exact_sig_map = {}
    conflict_sig_map = {}
    
    for row in rows:
        if row.status == 'REJECTED':
            continue
            
        exact_sig = make_signature(
            row.resolved_date or row.date,
            row.resolved_paid_by_name or row.paid_by,
            row.resolved_amount if row.resolved_amount is not None else row.amount,
            row.resolved_currency or row.currency,
            row.resolved_split_with or row.split_with
        )
        conflict_sig = make_conflict_signature(
            row.resolved_date or row.date,
            row.resolved_paid_by_name or row.paid_by,
            row.resolved_split_with or row.split_with,
            row.resolved_description or row.description
        )
        
        exact_sig_map[exact_sig] = exact_sig_map.get(exact_sig, 0) + 1
        
        if conflict_sig not in conflict_sig_map:
            conflict_sig_map[conflict_sig] = []
        conflict_sig_map[conflict_sig].append(row)

    # Let's iterate through rows and run checks
    for row in rows:
        if row.status == 'REJECTED':
            row.anomalies.all().update(is_resolved=True, decision='REJECTED')
            continue
            
        # Store existing anomaly decisions
        existing_decisions = {}
        for a in row.anomalies.all():
            existing_decisions[(a.type, a.raw_value.strip())] = (a.is_resolved, a.decision)
            
        # Delete any existing anomalies for this row first
        row.anomalies.all().delete()
        
        # We will collect anomalies for this row in memory first
        row_anomalies = []
        
        # Check if this row has already been initialized / edited
        is_first_run = (row.resolved_split_type is None)
        
        if is_first_run:
            # First run: initialize from raw values
            res_date = None
            res_desc = row.description
            res_payer = row.paid_by
            res_amount = None
            res_currency = row.currency
            res_split_type = row.split_type.upper() if row.split_type else 'EQUAL'
            res_split_with = row.split_with
            res_split_details = row.split_details
            res_notes = row.notes
            
            orig_amount = None
            orig_currency = None
            exch_rate = None
        else:
            # Subsequent run: use current resolved values as working basis
            res_date = row.resolved_date
            res_desc = row.resolved_description
            res_payer = row.resolved_paid_by_name
            res_amount = row.resolved_amount
            res_currency = row.resolved_currency
            res_split_type = row.resolved_split_type
            res_split_with = row.resolved_split_with
            res_split_details = row.resolved_split_details
            res_notes = row.resolved_notes
            
            orig_amount = row.original_amount
            orig_currency = row.original_currency
            exch_rate = row.exchange_rate

        # -------------------------------------------------------------
        # Rule 7: Missing Payer (ERROR)
        # -------------------------------------------------------------
        if not res_payer:
            row_anomalies.append({
                'type': 'MISSING_PAYER',
                'severity': 'ERROR',
                'raw_value': 'Payer field is empty',
                'suggested_fix': 'Provide a payer name. Expense will be imported as DRAFT and excluded from balances until fixed.'
            })
            res_payer = ""

        # -------------------------------------------------------------
        # Rule 5 & 6: Name Normalization (INFO) & Alias Mapping (WARNING)
        # -------------------------------------------------------------
        if res_payer:
            raw_p_name = res_payer.strip()
            norm_p_name = raw_p_name.lower()
            
            # Check for Alias Mapping (Priya S -> Priya)
            alias_match = re.match(r'^([a-zA-Z]+)\s+[a-zA-Z]$', raw_p_name)
            potential_base = alias_match.group(1) if alias_match else None
            
            if potential_base and potential_base.lower() in participant_name_map:
                base_proper_name = participant_name_map[potential_base.lower()].name
                if raw_p_name != base_proper_name:
                    row_anomalies.append({
                        'type': 'ALIAS_MAPPING',
                        'severity': 'WARNING',
                        'raw_value': f"Payer name: '{raw_p_name}'",
                        'suggested_fix': f"Map alias '{raw_p_name}' to system participant '{base_proper_name}'."
                    })
                    res_payer = base_proper_name
            elif norm_p_name in participant_name_map:
                proper_name = participant_name_map[norm_p_name].name
                if raw_p_name != proper_name:
                    row_anomalies.append({
                        'type': 'NAME_NORMALIZATION',
                        'severity': 'INFO',
                        'raw_value': f"Payer name: '{raw_p_name}'",
                        'suggested_fix': f"Normalize case and spaces to '{proper_name}'."
                    })
                    res_payer = proper_name
            else:
                res_payer = raw_p_name

        # -------------------------------------------------------------
        # Rule 4: Numeric Formatting (INFO)
        # -------------------------------------------------------------
        if isinstance(res_amount, Decimal):
            pass
        else:
            raw_amt_str = str(res_amount or row.amount or '').strip()
            cleaned_amt_str = raw_amt_str.replace(',', '') # Strip commas
            
            try:
                val_dec = Decimal(cleaned_amt_str)
                # Check if it has more than 2 decimal places or commas or spaces
                rounded_dec = round_half_up(val_dec)
                
                if ',' in raw_amt_str or raw_amt_str != cleaned_amt_str:
                    row_anomalies.append({
                        'type': 'NUMERIC_FORMATTING_COMMAS',
                        'severity': 'INFO',
                        'raw_value': f"Amount with formatting: '{raw_amt_str}'",
                        'suggested_fix': f"Strip formatting and parse as '{rounded_dec}'."
                    })
                
                # Decimal rounding check
                if val_dec != rounded_dec:
                    row_anomalies.append({
                        'type': 'NUMERIC_FORMATTING_ROUNDING',
                        'severity': 'INFO',
                        'raw_value': f"Amount: '{raw_amt_str}'",
                        'suggested_fix': f"Round amount '{val_dec}' to 2 decimal places using Round Half Up -> '{rounded_dec}'."
                    })
                res_amount = rounded_dec
            except (InvalidOperation, ValueError):
                row_anomalies.append({
                    'type': 'NUMERIC_FORMATTING_INVALID',
                    'severity': 'ERROR',
                    'raw_value': f"Amount: '{raw_amt_str}'",
                    'suggested_fix': 'Enter a valid numeric amount.'
                })
                res_amount = None

        # -------------------------------------------------------------
        # Rule 15: Zero Amount (WARNING) & Rule 16: Negative Amount (INFO)
        # -------------------------------------------------------------
        if res_amount is not None:
            if res_amount == 0:
                row_anomalies.append({
                    'type': 'ZERO_AMOUNT',
                    'severity': 'WARNING',
                    'raw_value': f"Amount: {res_amount}",
                    'suggested_fix': 'Import as INACTIVE/DRAFT expense (excluded from balances).'
                })
            elif res_amount < 0:
                row_anomalies.append({
                    'type': 'NEGATIVE_AMOUNT',
                    'severity': 'INFO',
                    'raw_value': f"Amount: {res_amount}",
                    'suggested_fix': 'Treat as a refund (negative expense split).'
                })

        # -------------------------------------------------------------
        # Rule 8: Missing Currency (WARNING) & Rule 1: Currency Mismatch (WARNING)
        # -------------------------------------------------------------
        raw_currency = (res_currency or '').strip()
        if not raw_currency:
            row_anomalies.append({
                'type': 'MISSING_CURRENCY',
                'severity': 'WARNING',
                'raw_value': 'Currency field is empty',
                'suggested_fix': "Suggest 'INR' (Indian Rupee)."
            })
            res_currency = 'INR'
        elif raw_currency.upper() == 'USD':
            # Convert to INR
            rate = Decimal(str(getattr(settings, 'USD_TO_INR_RATE', 83.00)))
            if res_amount is not None:
                orig_amount = res_amount
                orig_currency = 'USD'
                exch_rate = rate
                converted_amt = round_half_up(res_amount * rate)
                
                row_anomalies.append({
                    'type': 'CURRENCY_MISMATCH',
                    'severity': 'WARNING',
                    'raw_value': f"USD Value: {res_amount} USD",
                    'suggested_fix': f"Convert to INR using exchange rate {rate} -> {converted_amt} INR. Keep original values for auditing."
                })
                res_amount = converted_amt
                res_currency = 'INR'

        # -------------------------------------------------------------
        # Rule 12: Date Parsing (WARNING)
        # -------------------------------------------------------------
        if isinstance(res_date, datetime.date):
            pass
        else:
            raw_date = (res_date or row.date or '').strip()
            parsed_dt, is_date_ambiguous, date_msg = parse_date_robust(raw_date)
            if parsed_dt:
                res_date = parsed_dt
                if is_date_ambiguous:
                    row_anomalies.append({
                        'type': 'AMBIGUOUS_DATE',
                        'severity': 'WARNING',
                        'raw_value': f"Date: '{raw_date}'",
                        'suggested_fix': f"Confirm date as '{parsed_dt}' ({date_msg})."
                    })
            else:
                row_anomalies.append({
                    'type': 'DATE_PARSING_ERROR',
                    'severity': 'ERROR',
                    'raw_value': f"Date: '{raw_date}'",
                    'suggested_fix': 'Enter a valid date (e.g. YYYY-MM-DD).'
                })

        # -------------------------------------------------------------
        # Rule 9: Settlement Logged As Expense (WARNING)
        # -------------------------------------------------------------
        desc_lower = (res_desc or '').strip().lower()
        notes_lower = (res_notes or '').strip().lower()
        settlement_keywords = ['paid back', 'repaid', 'settled', 'deposit']
        is_logged_as_settlement = False
        for kw in settlement_keywords:
            if kw in desc_lower or kw in notes_lower:
                is_logged_as_settlement = True
                break
                
        if is_logged_as_settlement:
            row_anomalies.append({
                'type': 'SETTLEMENT_LOGGED_AS_EXPENSE',
                'severity': 'WARNING',
                'raw_value': f"Description: '{res_desc}', Notes: '{res_notes}'",
                'suggested_fix': "Convert from an Expense to a peer-to-peer Settlement."
            })
            row.is_settlement = True

        # -------------------------------------------------------------
        # Rule 10: Invalid Percentages (ERROR)
        # -------------------------------------------------------------
        if res_split_type == 'PERCENTAGE':
            try:
                pcts = parse_split_details(res_split_details)
                sum_pcts = sum(pcts.values())
                if sum_pcts != 100:
                    row_anomalies.append({
                        'type': 'INVALID_PERCENTAGES',
                        'severity': 'ERROR',
                        'raw_value': f"Percentages sum to {sum_pcts}%: '{res_split_details}'",
                        'suggested_fix': "Adjust percentages to sum up to exactly 100%."
                    })
            except Exception as e:
                row_anomalies.append({
                    'type': 'SPLIT_DETAILS_PARSE_ERROR',
                    'severity': 'ERROR',
                    'raw_value': f"Split details: '{res_split_details}'",
                    'suggested_fix': f"Correct syntax: Name Percentage% (e.g. 'Aisha 30%; Rohan 70%')."
                })

        # -------------------------------------------------------------
        # Rule 11: Split Metadata Conflict (ERROR)
        # -------------------------------------------------------------
        if res_split_type == 'EQUAL' and res_split_details:
            row_anomalies.append({
                'type': 'SPLIT_METADATA_CONFLICT',
                'severity': 'ERROR',
                'raw_value': f"Split type is 'equal' but split details supplied: '{res_split_details}'",
                'suggested_fix': "Remove split details to split equally, or change split type to matching format."
            })

        # -------------------------------------------------------------
        # Rule 13: Membership Violations (WARNING)
        # -------------------------------------------------------------
        split_names = [n.strip() for n in (res_split_with or '').split(';') if n.strip()]
        all_involved_names = set(split_names)
        if res_payer:
            all_involved_names.add(res_payer)

        for name in all_involved_names:
            norm_name = name.lower()
            
            alias_match = re.match(r'^([a-zA-Z]+)\s+[a-zA-Z]$', name.strip())
            pot_base = alias_match.group(1) if alias_match else None
            if pot_base and pot_base.lower() in participant_name_map:
                norm_name = pot_base.lower()
                
            if norm_name in group_members_map:
                memb = group_members_map[norm_name]
                if res_date:
                    joined = memb.joined_at
                    left = memb.left_at
                    
                    if res_date < joined:
                        row_anomalies.append({
                            'type': 'MEMBERSHIP_VIOLATION_BEFORE',
                            'severity': 'WARNING',
                            'raw_value': f"Participant '{name}' included on {res_date} but joined on {joined}",
                            'suggested_fix': f"Review if '{name}' should be included. Balances engine will exclude them before joining."
                        })
                    elif left and res_date > left:
                        row_anomalies.append({
                            'type': 'MEMBERSHIP_VIOLATION_AFTER',
                            'severity': 'WARNING',
                            'raw_value': f"Participant '{name}' included on {res_date} but left on {left}",
                            'suggested_fix': f"Review if '{name}' should be included. Balances engine will exclude them after leaving."
                        })

        # -------------------------------------------------------------
        # Rule 14: External Participants (INFO)
        # -------------------------------------------------------------
        for name in all_involved_names:
            norm_name = name.lower()
            alias_match = re.match(r'^([a-zA-Z]+)\s+[a-zA-Z]$', name.strip())
            pot_base = alias_match.group(1) if alias_match else None
            if pot_base and pot_base.lower() in participant_name_map:
                norm_name = pot_base.lower()
                
            if norm_name not in group_members_map:
                row_anomalies.append({
                    'type': 'EXTERNAL_PARTICIPANT',
                    'severity': 'INFO',
                    'raw_value': f"Participant '{name}' is not in the registered group membership.",
                    'suggested_fix': f"Create/map to external participant '{name}' automatically."
                })

        # -------------------------------------------------------------
        # Rule 14b: Missing User (WARNING)
        # -------------------------------------------------------------
        for name in all_involved_names:
            # Check if this name exists as a CustomUser (registered system user)
            user_exists = CustomUser.objects.filter(name__iexact=name.strip()).exists()
            if not user_exists:
                row_anomalies.append({
                    'type': 'MISSING_USER',
                    'severity': 'WARNING',
                    'raw_value': f"Participant '{name}' does not have a registered system account.",
                    'suggested_fix': f"Create dev user account for '{name}' automatically with a dev password."
                })

        # -------------------------------------------------------------
        # Rule 2: Exact Duplicate Entries (WARNING)
        # -------------------------------------------------------------
        if row.status == 'REJECTED':
            pass
        else:
            exact_sig = make_signature(res_date, res_payer, res_amount, res_currency, res_split_with)
            is_dup_in_session = exact_sig_map.get(exact_sig, 0) > 1
            
            is_dup_in_db = False
            if res_date and res_amount is not None and res_payer:
                db_dups = Expense.objects.filter(
                    group=group,
                    expense_date=res_date,
                    amount=res_amount,
                    paid_by__name__iexact=res_payer,
                    status='ACTIVE'
                )
                if db_dups.exists():
                    is_dup_in_db = True
                    
            if is_dup_in_session or is_dup_in_db:
                row_anomalies.append({
                    'type': 'DUPLICATE_ENTRY',
                    'severity': 'WARNING',
                    'raw_value': f"Duplicate signature: date={res_date}, payer={res_payer}, amount={res_amount}",
                    'suggested_fix': "Flagged as duplicate. Confirm if this is a separate transaction or should be rejected."
                })

        # -------------------------------------------------------------
        # Rule 3: Conflicting Duplicates (ERROR)
        # -------------------------------------------------------------
        if row.status == 'REJECTED':
            pass
        else:
            conflict_sig = make_conflict_signature(res_date, res_payer, res_split_with, res_desc)
            
            conflict_in_session = False
            session_matches = conflict_sig_map.get(conflict_sig, [])
            for other in session_matches:
                if other.id != row.id:
                    other_amt = other.resolved_amount if other.resolved_amount is not None else other.amount
                    _, _, other_amt_norm, _, _ = make_signature(None, None, other_amt, None, None)
                    _, _, current_amt_norm, _, _ = make_signature(None, None, res_amount, None, None)
                    if other_amt_norm != current_amt_norm:
                        conflict_in_session = True
                        break
                        
            conflict_in_db = False
            if res_date and res_payer:
                db_conflicts = Expense.objects.filter(
                    group=group,
                    expense_date=res_date,
                    paid_by__name__iexact=res_payer,
                    description__iexact=res_desc,
                    status='ACTIVE'
                ).exclude(amount=res_amount if res_amount is not None else Decimal('0.00'))
                if db_conflicts.exists():
                    conflict_in_db = True
                    
            if conflict_in_session or conflict_in_db:
                row_anomalies.append({
                    'type': 'CONFLICTING_DUPLICATE',
                    'severity': 'ERROR',
                    'raw_value': f"Conflicting amounts for same date/payer/desc: '{res_amount}'",
                    'suggested_fix': "Block import. Same expense logged with different amounts. Must resolve manually."
                })

        # Save resolved fields to the row staging data
        row.resolved_date = res_date
        row.resolved_description = res_desc
        row.resolved_paid_by_name = res_payer
        row.resolved_amount = res_amount
        row.resolved_currency = res_currency
        row.resolved_split_type = res_split_type
        row.resolved_split_with = res_split_with
        row.resolved_split_details = res_split_details
        row.resolved_notes = res_notes
        
        row.original_amount = orig_amount
        row.original_currency = orig_currency
        row.exchange_rate = exch_rate
        
        row.save()

        # Write anomalies to database
        for anom in row_anomalies:
            is_res, dec = existing_decisions.get((anom['type'], anom['raw_value'].strip()), (False, 'PENDING'))
            ImportAnomaly.objects.create(
                session=session,
                row=row,
                type=anom['type'],
                severity=anom['severity'],
                raw_value=anom['raw_value'],
                suggested_fix=anom['suggested_fix'],
                decision=dec,
                is_resolved=is_res
            )
            
    # Mark rows with errors as pending resolution, and rows without errors as clean
    for row in rows:
        if row.status == 'REJECTED':
            continue
        has_errors = row.anomalies.filter(severity='ERROR', is_resolved=False).exists()
        if has_errors:
            row.status = 'PENDING'
        else:
            row.status = 'RESOLVED'
        row.save()
