from decimal import Decimal
import datetime
from django.db import transaction
from django.utils import timezone
from expense_manager.apps.accounts.models import Participant, CustomUser
from expense_manager.apps.expenses.models import Expense, ExpenseSplit
from expense_manager.apps.settlements.models import Settlement
from expense_manager.apps.imports.models import ImportSession, ImportRow, ImportAnomaly
from expense_manager.apps.expenses.services.split_calculator import calculate_splits

def get_or_create_participant_by_name(name_str):
    """
    Looks up a participant case-insensitively.
    If not found, checks if a CustomUser exists with that name.
    If yes, links Participant to user. If no, creates an external Participant.
    """
    name_str = name_str.strip()
    if not name_str:
        raise ValueError("Participant name cannot be empty")
        
    # Look up existing participant
    p = Participant.objects.filter(name__iexact=name_str).first()
    if p:
        return p
        
    # Check if user exists with this name
    user = CustomUser.objects.filter(name__iexact=name_str).first()
    if user:
        p = Participant.objects.create(name=user.name, user=user, is_external=False)
        return p
        
    # Otherwise create external participant
    p = Participant.objects.create(name=name_str, is_external=True)
    return p

@transaction.atomic
def finalize_session_import(session, executor_user):
    """
    Finalizes the import session, turning ImportRow staging objects into 
    actual Expense and Settlement records.
    Returns a dictionary summarizing the import report.
    """
    if session.status != 'PENDING_REVIEW':
        raise ValueError("This import session has already been finalized or rejected.")
        
    rows = session.rows.all()
    group = session.group
    
    # Check if there are any remaining ERROR anomalies that are not rejected/resolved
    unresolved_errors = ImportAnomaly.objects.filter(
        session=session,
        severity='ERROR',
        is_resolved=False
    ).exclude(row__status='REJECTED')
    
    if unresolved_errors.exists():
        raise ValueError("Cannot finalize import: there are unresolved block errors.")
        
    # Find all unique participant names involved in non-rejected rows
    import re
    import json
    from expense_manager.apps.groups.models import GroupMembership
    
    involved_names = set()
    for row in rows:
        if row.status == 'REJECTED':
            continue
        if row.resolved_paid_by_name:
            involved_names.add(row.resolved_paid_by_name.strip())
        elif row.paid_by:
            involved_names.add(row.paid_by.strip())
            
        splits = [n.strip() for n in (row.resolved_split_with or row.split_with or '').split(';') if n.strip()]
        for s in splits:
            involved_names.add(s)
            
    auto_created_accounts = []
    
    # Check each name and create dev user if not registered
    for name in involved_names:
        if not name:
            continue
        # Check if a CustomUser exists with this name (case-insensitive)
        user = CustomUser.objects.filter(name__iexact=name).first()
        if not user:
            # Check if participant has an associated user
            part = Participant.objects.filter(name__iexact=name).first()
            if part and part.user:
                user = part.user
                
        if not user:
            # Auto-create CustomUser
            base_email = re.sub(r'[^a-zA-Z0-9]', '_', name.lower())
            email = f"{base_email}@dev.local"
            counter = 1
            while CustomUser.objects.filter(email=email).exists():
                email = f"{base_email}{counter}@dev.local"
                counter += 1
                
            password = f"DevPass_{name.replace(' ', '')}_2026!"
            
            user = CustomUser.objects.create_user(
                email=email,
                password=password,
                name=name,
                role='MEMBER'
            )
            
            # Link/create Participant
            p = Participant.objects.filter(name__iexact=name).first()
            if p:
                p.user = user
                p.is_external = False
                p.save()
            else:
                Participant.objects.create(name=name, user=user, is_external=False)
                
            # Record account details
            auto_created_accounts.append({
                'name': name,
                'email': email,
                'password': password
            })
            
        # Ensure they are added to group memberships so they don't trigger violation rules in split checks
        if not GroupMembership.objects.filter(group=group, user=user).exists():
            # Get earliest date of row for membership join date
            earliest_date = datetime.date.today()
            for r in rows:
                if r.status != 'REJECTED':
                    r_dt = r.resolved_date
                    if isinstance(r_dt, datetime.date):
                        if r_dt < earliest_date:
                            earliest_date = r_dt
            
            GroupMembership.objects.create(
                group=group,
                user=user,
                joined_at=earliest_date,
                role='MEMBER'
            )
            
    # Save auto-created accounts to ImportSession
    if auto_created_accounts:
        session.auto_created_accounts_json = json.dumps(auto_created_accounts)
        session.save()

    rows_processed = rows.count()
    rows_imported = 0
    rows_rejected = 0
    anomalies_detected = session.anomalies.count()
    
    for row in rows:
        if row.status == 'REJECTED':
            rows_rejected += 1
            # Mark anomalies of this row as resolved/rejected
            row.anomalies.all().update(is_resolved=True, decision='REJECTED')
            continue
            
        # Ensure all anomalies on this row are resolved
        row.anomalies.filter(is_resolved=False).update(is_resolved=True, decision='APPROVED')
        
        # 1. Convert to Settlement if flagged
        if row.is_settlement:
            payer_name = row.resolved_paid_by_name or row.paid_by
            # Payer must exist
            payer_part = get_or_create_participant_by_name(payer_name)
            
            # Receiver is the first name in split_with
            receiver_name = (row.resolved_split_with or row.split_with or '').split(';')[0].strip()
            receiver_part = get_or_create_participant_by_name(receiver_name)
            
            amt = row.resolved_amount if row.resolved_amount is not None else Decimal('0.00')
            dt = row.resolved_date if row.resolved_date else datetime.date.today()
            
            # Create Settlement
            Settlement.objects.create(
                group=group,
                payer=payer_part,
                receiver=receiver_part,
                amount=amt,
                currency=row.resolved_currency or 'INR',
                date=dt,
                import_session=session,
                import_row_number=row.row_number
            )
            
            row.is_imported = True
            row.status = 'RESOLVED'
            row.save()
            rows_imported += 1
            
        # 2. Convert to Expense
        else:
            payer_name = row.resolved_paid_by_name
            if not payer_name:
                # If payer is missing, and we are importing, it must have been set in draft
                # Create a draft expense
                payer_part = get_or_create_participant_by_name("Unknown Payer")
                exp_status = 'DRAFT'
            else:
                payer_part = get_or_create_participant_by_name(payer_name)
                # Zero amount is draft/inactive
                if row.resolved_amount == 0:
                    exp_status = 'INACTIVE'
                else:
                    exp_status = 'ACTIVE'
                    
            amt = row.resolved_amount if row.resolved_amount is not None else Decimal('0.00')
            dt = row.resolved_date if row.resolved_date else datetime.date.today()
            
            # Create Expense
            expense = Expense.objects.create(
                group=group,
                description=row.resolved_description or 'Imported Expense',
                amount=amt,
                currency=row.resolved_currency or 'INR',
                expense_date=dt,
                paid_by=payer_part,
                split_type=row.resolved_split_type or 'EQUAL',
                status=exp_status,
                original_amount=row.original_amount,
                original_currency=row.original_currency,
                exchange_rate=row.exchange_rate,
                import_session=session,
                import_row_number=row.row_number
            )
            
            # Compute splits and save splits
            split_names = [n.strip() for n in (row.resolved_split_with or '').split(';') if n.strip()]
            if not split_names:
                # Fallback to group members if split list is completely empty
                split_names = [m.user.name for m in group.memberships.all() if hasattr(m.user, 'participant')]
                
            split_participants = [get_or_create_participant_by_name(name) for name in split_names]
            
            # Calculate actual share splits
            try:
                splits_breakdown = calculate_splits(
                    amt,
                    expense.split_type,
                    split_participants,
                    row.resolved_split_details
                )
                
                for s in splits_breakdown:
                    ExpenseSplit.objects.create(
                        expense=expense,
                        participant=s['participant'],
                        share_amount=s['share_amount'],
                        share_percentage=s.get('share_percentage'),
                        share_ratio=s.get('share_ratio')
                    )
            except Exception as e:
                # If split calculation fails, create equal splits as safe fallback
                base_share = amt / Decimal(len(split_participants)) if split_participants else Decimal('0.00')
                for p in split_participants:
                    ExpenseSplit.objects.create(
                        expense=expense,
                        participant=p,
                        share_amount=base_share
                    )
            
            row.is_imported = True
            row.status = 'RESOLVED'
            row.save()
            rows_imported += 1
            
    # Mark session as imported
    session.status = 'IMPORTED'
    session.save()
    
    # Compile import report
    report = {
        'session_id': session.id,
        'group_name': group.name,
        'file_name': session.file_name,
        'uploaded_by': session.uploaded_by.name,
        'status': session.status,
        'rows_processed': rows_processed,
        'rows_imported': rows_imported,
        'rows_rejected': rows_rejected,
        'anomalies_detected': anomalies_detected,
        'timestamp': timezone.now().strftime('%Y-%m-%d %H:%M:%S UTC'),
        'executor': executor_user.name
    }
    
    return report
