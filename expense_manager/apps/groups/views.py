import datetime
from decimal import Decimal
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db import transaction
from django.conf import settings
from expense_manager.apps.accounts.models import CustomUser, Participant
from expense_manager.apps.groups.models import Group, GroupMembership
from expense_manager.apps.expenses.models import Expense, ExpenseSplit
from expense_manager.apps.settlements.models import Settlement
from expense_manager.apps.imports.models import ImportSession
from expense_manager.apps.expenses.services.balance_calculator import get_group_balances
from expense_manager.apps.expenses.services.split_calculator import calculate_splits

@login_required
def dashboard_view(request):
    user = request.user
    
    # Get all memberships of the user
    user_memberships = GroupMembership.objects.filter(user=user)
    user_groups = [m.group for m in user_memberships]
    
    # If user is ADMIN, they can see all groups in the system, otherwise only their joined groups
    if user.role == 'ADMIN':
        all_groups = Group.objects.all()
    else:
        all_groups = user_groups
        
    # User's participant profile
    try:
        participant = user.participant
    except Participant.DoesNotExist:
        # Auto-create participant profile if missing
        participant = Participant.objects.create(name=user.name, user=user, is_external=False)
        
    net_balances_by_group = {}
    people_you_owe = {}  # {participant_name: total_amount}
    people_who_owe_you = {}  # {participant_name: total_amount}
    total_net_balance = Decimal('0.00')
    dashboard_debts = []
    
    # Iterate through all groups the user is member of to compute aggregate balances
    for g in user_groups:
        balances_data = get_group_balances(g)
        
        user_net = Decimal('0.00')
        owes_list = []
        owed_by_list = []
        ledger_records = []
        
        # User net in this group
        if participant.id in balances_data['balances']:
            user_bal = balances_data['balances'][participant.id]
            net_balances_by_group[g.id] = user_bal['net']
            user_net = user_bal['net']
            total_net_balance += user_bal['net']
            ledger_records = balances_data['explanations'].get(participant.id, [])
            
        # Simplified debts in this group
        for simp in balances_data['simplifications']:
            if simp['from'].id == participant.id:
                # User owes someone
                to_name = simp['to'].name
                people_you_owe[to_name] = people_you_owe.get(to_name, Decimal('0.00')) + simp['amount']
                owes_list.append(simp)
            elif simp['to'].id == participant.id:
                # Someone owes User
                from_name = simp['from'].name
                people_who_owe_you[from_name] = people_who_owe_you.get(from_name, Decimal('0.00')) + simp['amount']
                owed_by_list.append(simp)
                
        if user_net != 0 or owes_list or owed_by_list or ledger_records:
            dashboard_debts.append({
                'group': g,
                'net': user_net,
                'owes': owes_list,
                'owed_by': owed_by_list,
                'ledger_records': ledger_records
            })

    # Search and sorting query parameters
    query = request.GET.get('q', '').strip()
    sort_by = request.GET.get('sort_by', '-date').strip()
    
    expenses_qs = Expense.objects.filter(group__in=user_groups, paid_by=participant).prefetch_related('splits', 'splits__participant')
    
    if query:
        expenses_qs = expenses_qs.filter(
            description__icontains=query
        ) | expenses_qs.filter(
            paid_by__name__icontains=query
        ) | expenses_qs.filter(
            group__name__icontains=query
        )
        
    # Sorting logic
    if sort_by == 'amount':
        expenses_qs = expenses_qs.order_by('amount', '-created_at')
    elif sort_by == '-amount':
        expenses_qs = expenses_qs.order_by('-amount', '-created_at')
    elif sort_by == 'description':
        expenses_qs = expenses_qs.order_by('description', '-created_at')
    elif sort_by == 'date':
        expenses_qs = expenses_qs.order_by('expense_date', '-created_at')
    else: # default -date
        expenses_qs = expenses_qs.order_by('-expense_date', '-created_at')
        
    # Limit dashboard view display, but for export we export all matching
    recent_expenses = expenses_qs[:5]
    if request.GET.get('export') == 'csv':
        import csv
        from django.http import HttpResponse
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = f'attachment; filename="expenses_export_{datetime.date.today()}.csv"'
        writer = csv.writer(response)
        writer.writerow(['Description', 'Group', 'Paid By', 'Date', 'Amount', 'Status'])
        for exp in expenses_qs:
            writer.writerow([exp.description, exp.group.name, exp.paid_by.name, exp.expense_date.strftime('%Y-%m-%d'), exp.amount, exp.status])
        return response
    
    # Get recent settlements from user's groups
    recent_settlements = Settlement.objects.filter(group__in=user_groups).order_by('-date', '-created_at')[:5]
    
    # Import sessions uploaded by user
    import_status = ImportSession.objects.filter(uploaded_by=user).order_by('-created_at')[:5]
    if user.role == 'ADMIN':
        import_status = ImportSession.objects.all().order_by('-created_at')[:5]

    total_you_owe = sum(people_you_owe.values())
    total_owed_to_you = sum(people_who_owe_you.values())
    total_debts = total_you_owe + total_owed_to_you
    
    if total_debts > 0:
        owed_pct = int((total_owed_to_you / total_debts) * 100)
        owe_pct = 100 - owed_pct
    else:
        owed_pct = 50
        owe_pct = 50

    # Generate Group Summaries matching the budget card layout
    group_summaries = []
    for g in user_groups:
        balances_data = get_group_balances(g)
        
        # Total spent in group
        group_total = sum(exp.amount for exp in g.expenses.filter(status='ACTIVE'))
        
        # User net in this group
        user_net = Decimal('0.00')
        if participant.id in balances_data['balances']:
            user_net = balances_data['balances'][participant.id]['net']
            
        # Calculate visual fill percent
        if group_total > 0:
            share_pct = min(100, int((abs(user_net) / group_total) * 100))
            if share_pct == 0:
                share_pct = 25
        else:
            share_pct = 0
            
        group_summaries.append({
            'group': g,
            'total_spent': group_total,
            'user_net': user_net,
            'share_pct': share_pct
        })

    context = {
        'all_groups': all_groups,
        'user_groups': user_groups,
        'total_net_balance': total_net_balance,
        'total_you_owe': total_you_owe,
        'total_owed_to_you': total_owed_to_you,
        'owed_pct': owed_pct,
        'owe_pct': owe_pct,
        'group_summaries': group_summaries,
        'people_you_owe': people_you_owe,
        'people_who_owe_you': people_who_owe_you,
        'recent_expenses': recent_expenses,
        'recent_settlements': recent_settlements,
        'import_status': import_status,
        'q_query': query,
        'sort_by': sort_by,
        'dashboard_debts': dashboard_debts
    }
    return render(request, 'groups/dashboard.html', context)

@login_required
def create_group_view(request):
    if request.user.role != 'ADMIN':
        messages.error(request, "Only Administrators can create groups.")
        return redirect('dashboard')
        
    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        if name:
            group = Group.objects.create(name=name, created_by=request.user)
            # Auto add creator as Admin member of the group
            GroupMembership.objects.create(
                group=group,
                user=request.user,
                joined_at=datetime.date.today(),
                role='ADMIN'
            )
            messages.success(request, f"Group '{name}' created successfully!")
            return redirect('group_detail', group_id=group.id)
        else:
            messages.error(request, "Group name cannot be empty.")
            
    return render(request, 'groups/create_group.html')

@login_required
def group_detail_view(request, group_id):
    group = get_object_or_404(Group, id=group_id)
    user = request.user
    
    # Check membership
    is_member = GroupMembership.objects.filter(group=group, user=user).exists()
    if not is_member and user.role != 'ADMIN':
        messages.error(request, "You do not have permission to view this group.")
        return redirect('dashboard')
        
    # Calculate balances
    simplify = request.GET.get('simplify', 'true') != 'false'
    balances_data = get_group_balances(group, simplify=simplify)
    
    # Attach 'owes' and 'owed_by' lists directly to each participant's balance dictionary for easy template rendering
    for p_id, bal in balances_data['balances'].items():
        bal['owes'] = []
        bal['owed_by'] = []
        
    for simp in balances_data['simplifications']:
        from_id = simp['from'].id
        to_id = simp['to'].id
        if from_id in balances_data['balances']:
            balances_data['balances'][from_id]['owes'].append(simp)
        if to_id in balances_data['balances']:
            balances_data['balances'][to_id]['owed_by'].append(simp)
    
    # Expenses (Include Active, Draft, Inactive)
    expenses_qs = group.expenses.all().order_by('-expense_date', '-created_at')
    from django.core.paginator import Paginator
    paginator = Paginator(expenses_qs, 15)
    page_number = request.GET.get('page')
    expenses = paginator.get_page(page_number)
    
    # Settlements
    settlements = group.settlements.all().order_by('-date', '-created_at')
    
    # Memberships
    memberships = group.memberships.select_related('user').all()
    
    # Imports
    import_history = group.import_sessions.all().order_by('-created_at')

    # Get user participant record if it exists
    user_part_id = None
    if hasattr(user, 'participant'):
        user_part_id = user.participant.id

    # Active tab from query param
    active_tab = request.GET.get('tab', 'overview')
    if active_tab not in ['overview', 'expenses', 'imports']:
        active_tab = 'overview'

    # Compute contribution data for Chart.js
    # List of participants in group and their total active spend contribution
    contributions = []
    members_list = [m.user.participant for m in memberships if hasattr(m.user, 'participant')]
    for member in members_list:
        member_spent = sum(exp.amount for exp in group.expenses.filter(paid_by=member, status='ACTIVE'))
        contributions.append({
            'name': member.name,
            'spent': float(member_spent)
        })

    # Prepare net balances list for Chart.js
    chart_balances = []
    for p_id, bal in balances_data['balances'].items():
        chart_balances.append({
            'name': bal['participant'].name,
            'net': float(bal['net'])
        })

    context = {
        'group': group,
        'memberships': memberships,
        'expenses': expenses,
        'settlements': settlements,
        'balances': balances_data['balances'],
        'simplifications': balances_data['simplifications'],
        'explanations': balances_data['explanations'],
        'import_history': import_history,
        'user_part_id': user_part_id,
        'active_tab': active_tab,
        'contributions_json': contributions,
        'chart_balances_json': chart_balances,
        'simplify': simplify
    }
    return render(request, 'groups/group_detail.html', context)

@login_required
@transaction.atomic
def add_expense_view(request, group_id):
    group = get_object_or_404(Group, id=group_id)
    user = request.user
    
    # Check memberships
    is_member = GroupMembership.objects.filter(group=group, user=user).exists()
    if not is_member and user.role != 'ADMIN':
        messages.error(request, "Permission denied.")
        return redirect('dashboard')
        
    # Fetch members of the group to select as splits
    group_members = [m.user.participant for m in group.memberships.select_related('user__participant').all() if hasattr(m.user, 'participant')]
    all_participants = Participant.objects.all()

    if request.method == 'POST':
        description = request.POST.get('description', '').strip()
        amount_str = request.POST.get('amount', '').strip()
        expense_date_str = request.POST.get('expense_date', '').strip()
        payer_id = request.POST.get('paid_by', '').strip()
        split_type = request.POST.get('split_type', 'EQUAL').upper()
        split_with_ids = request.POST.getlist('split_with')
        split_details = request.POST.get('split_details', '').strip()
        
        # Validation
        if not description or not amount_str or not expense_date_str or not payer_id or not split_with_ids:
            messages.error(request, "All fields are required.")
        else:
            try:
                amount = Decimal(amount_str)
                expense_date = datetime.datetime.strptime(expense_date_str, '%Y-%m-%d').date()
                paid_by = Participant.objects.get(id=payer_id)
                split_participants = Participant.objects.filter(id__in=split_with_ids)
                
                # Check split_calculator
                calculated_splits = calculate_splits(amount, split_type, split_participants, split_details)
                
                # Create Expense
                expense = Expense.objects.create(
                    group=group,
                    description=description,
                    amount=amount,
                    currency='INR',
                    expense_date=expense_date,
                    paid_by=paid_by,
                    split_type=split_type,
                    status='ACTIVE'
                )
                
                for s in calculated_splits:
                    ExpenseSplit.objects.create(
                        expense=expense,
                        participant=s['participant'],
                        share_amount=s['share_amount'],
                        share_percentage=s.get('share_percentage'),
                        share_ratio=s.get('share_ratio')
                    )
                
                messages.success(request, f"Expense '{description}' added successfully!")
                return redirect('group_detail', group_id=group.id)
                
            except Exception as e:
                messages.error(request, f"Failed to add expense: {str(e)}")
                
    context = {
        'group': group,
        'participants': all_participants,
        'group_members': group_members,
        'default_date': datetime.date.today().strftime('%Y-%m-%d')
    }
    return render(request, 'groups/add_expense.html', context)

@login_required
def add_settlement_view(request, group_id):
    group = get_object_or_404(Group, id=group_id)
    user = request.user
    
    is_member = GroupMembership.objects.filter(group=group, user=user).exists()
    if not is_member and user.role != 'ADMIN':
        messages.error(request, "Permission denied.")
        return redirect('dashboard')
        
    group_members = [m.user.participant for m in group.memberships.select_related('user__participant').all() if hasattr(m.user, 'participant')]
    all_participants = Participant.objects.all()

    if request.method == 'POST':
        payer_id = request.POST.get('payer', '').strip()
        receiver_id = request.POST.get('receiver', '').strip()
        amount_str = request.POST.get('amount', '').strip()
        date_str = request.POST.get('date', '').strip()
        
        if not payer_id or not receiver_id or not amount_str or not date_str:
            messages.error(request, "All fields are required.")
        elif payer_id == receiver_id:
            messages.error(request, "Payer and Receiver cannot be the same person.")
        else:
            try:
                payer = Participant.objects.get(id=payer_id)
                receiver = Participant.objects.get(id=receiver_id)
                amount = Decimal(amount_str)
                date = datetime.datetime.strptime(date_str, '%Y-%m-%d').date()
                
                Settlement.objects.create(
                    group=group,
                    payer=payer,
                    receiver=receiver,
                    amount=amount,
                    currency='INR',
                    date=date
                )
                
                messages.success(request, f"Settlement logged: {payer.name} paid {receiver.name} INR {amount}")
                return redirect('group_detail', group_id=group.id)
            except Exception as e:
                messages.error(request, f"Failed to record settlement: {str(e)}")
                
    context = {
        'group': group,
        'group_members': group_members,
        'participants': all_participants,
        'default_date': datetime.date.today().strftime('%Y-%m-%d')
    }
    return render(request, 'groups/add_settlement.html', context)

@login_required
@transaction.atomic
def manage_membership_view(request, group_id):
    group = get_object_or_404(Group, id=group_id)
    if request.user.role != 'ADMIN':
        messages.error(request, "Only Administrators can manage group memberships.")
        return redirect('group_detail', group_id=group.id)
        
    users = CustomUser.objects.all()
    memberships = group.memberships.all()

    if request.method == 'POST':
        action = request.POST.get('action', '')
        
        if action == 'add':
            user_id = request.POST.get('user_id', '')
            joined_str = request.POST.get('joined_at', '')
            role = request.POST.get('role', 'MEMBER')
            
            if not user_id or not joined_str:
                messages.error(request, "User and Join Date are required.")
            else:
                try:
                    target_user = CustomUser.objects.get(id=user_id)
                    joined_at = datetime.datetime.strptime(joined_str, '%Y-%m-%d').date()
                    
                    # Check if already has active membership
                    existing = GroupMembership.objects.filter(group=group, user=target_user, left_at__isnull=True).first()
                    if existing:
                        messages.error(request, f"{target_user.name} is already an active member of this group.")
                    else:
                        GroupMembership.objects.create(
                            group=group,
                            user=target_user,
                            joined_at=joined_at,
                            role=role
                        )
                        # Ensure participant profile exists
                        Participant.objects.get_or_create(name=target_user.name, defaults={'user': target_user, 'is_external': False})
                        messages.success(request, f"Added {target_user.name} to the group.")
                except Exception as e:
                    messages.error(request, f"Error adding member: {str(e)}")
                    
        elif action == 'leave':
            membership_id = request.POST.get('membership_id', '')
            left_str = request.POST.get('left_at', '')
            
            if not membership_id or not left_str:
                messages.error(request, "Membership ID and Leave Date are required.")
            else:
                try:
                    left_at = datetime.datetime.strptime(left_str, '%Y-%m-%d').date()
                    membership = GroupMembership.objects.get(id=membership_id, group=group)
                    
                    if left_at < membership.joined_at:
                        messages.error(request, "Leave date cannot be before join date.")
                    else:
                        membership.left_at = left_at
                        membership.save()
                        messages.success(request, f"Recorded departure of {membership.user.name} on {left_at}.")
                except Exception as e:
                    messages.error(request, f"Error recording leave: {str(e)}")
                    
        return redirect('manage_memberships', group_id=group.id)

    context = {
        'group': group,
        'users': users,
        'memberships': memberships,
        'default_date': datetime.date.today().strftime('%Y-%m-%d')
    }
    return render(request, 'groups/manage_memberships.html', context)


@login_required
@transaction.atomic
def flush_group_data_view(request, group_id):
    group = get_object_or_404(Group, id=group_id)
    
    if request.user.role != 'ADMIN':
        messages.error(request, "Only Administrators can flush group data.")
        return redirect('group_detail', group_id=group.id)
        
    if request.method == 'POST':
        # Count items
        expenses_count = group.expenses.count()
        settlements_count = group.settlements.count()
        sessions_count = group.import_sessions.count()
        
        # Identify auto-created CustomUsers and Participants
        import json
        from django.db import models
        emails_to_delete = []
        names_to_delete = []
        for session in group.import_sessions.all():
            if session.auto_created_accounts_json:
                try:
                    accs = json.loads(session.auto_created_accounts_json)
                    for acc in accs:
                        emails_to_delete.append(acc['email'])
                        names_to_delete.append(acc['name'])
                except Exception:
                    pass
        
        # Delete items
        group.expenses.all().delete()
        group.settlements.all().delete()
        
        # Delete auto-created accounts and participants
        users = CustomUser.objects.filter(email__in=emails_to_delete)
        participants = Participant.objects.filter(models.Q(user__in=users) | models.Q(name__in=names_to_delete))
        
        participants_count = participants.count()
        users_count = users.count()
        
        participants.delete()
        users.delete()
        
        # Delete import sessions
        group.import_sessions.all().delete()
        
        messages.success(request, f"Successfully flushed all data for group '{group.name}': {expenses_count} expenses, {settlements_count} settlements, {sessions_count} import sessions, {participants_count} auto-created participants, and {users_count} user accounts deleted.")
        return redirect('group_detail', group_id=group.id)
        
    return redirect('group_detail', group_id=group.id)


@login_required
def export_group_report_view(request, group_id):
    group = get_object_or_404(Group, id=group_id)
    user = request.user
    
    is_member = GroupMembership.objects.filter(group=group, user=user).exists()
    if not is_member and user.role != 'ADMIN':
        messages.error(request, "Access denied.")
        return redirect('dashboard')
        
    import csv
    from django.http import HttpResponse
    
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename="group_{group.name}_report_{datetime.date.today()}.csv"'
    
    writer = csv.writer(response)
    writer.writerow(['TYPE', 'DATE', 'DESCRIPTION', 'PAYER/FROM', 'RECEIVER/TO', 'AMOUNT', 'STATUS', 'CURRENCY', 'NOTES'])
    
    # Write expenses
    for exp in group.expenses.all().order_by('expense_date'):
        writer.writerow([
            'EXPENSE',
            exp.expense_date.strftime('%Y-%m-%d'),
            exp.description,
            exp.paid_by.name,
            'ALL_MEMBERS',
            exp.amount,
            exp.status,
            exp.currency,
            ''
        ])
        
    # Write settlements
    for setl in group.settlements.all().order_by('date'):
        writer.writerow([
            'SETTLEMENT',
            setl.date.strftime('%Y-%m-%d'),
            f'Settlement: {setl.payer.name} paid {setl.receiver.name}',
            setl.payer.name,
            setl.receiver.name,
            setl.amount,
            'COMPLETED',
            setl.currency,
            ''
        ])
        
    return response


@login_required
def reports_view(request):
    user = request.user
    
    # Get completed import sessions
    user_memberships = GroupMembership.objects.filter(user=user)
    user_groups = [m.group for m in user_memberships]
    
    if user.role == 'ADMIN':
        sessions = ImportSession.objects.all().order_by('-created_at')
    else:
        sessions = ImportSession.objects.filter(group__in=user_groups).order_by('-created_at')
        
    # Check if download requested
    download_session_id = request.GET.get('download')
    if download_session_id:
        sess = get_object_or_404(ImportSession, id=download_session_id)
        # Auth check
        if user.role != 'ADMIN' and sess.group not in user_groups:
            messages.error(request, "Access denied.")
            return redirect('reports')
            
        import json
        from django.http import HttpResponse
        
        report_data = {
            'session_id': sess.id,
            'group_name': sess.group.name,
            'file_name': sess.file_name,
            'uploaded_by': sess.uploaded_by.name if sess.uploaded_by else 'System',
            'status': sess.status,
            'created_at': sess.created_at.strftime('%Y-%m-%d %H:%M:%S UTC'),
            'total_rows': sess.rows.count(),
            'imported_rows': sess.rows.filter(is_imported=True).count(),
            'rejected_rows': sess.rows.filter(status='REJECTED').count(),
            'anomalies_count': sess.anomalies.count(),
            'anomalies_list': [
                {
                    'row': anom.row.row_number if anom.row else 'Global',
                    'type': anom.type,
                    'severity': anom.severity,
                    'message': anom.suggested_fix,
                    'raw_value': anom.raw_value,
                    'resolved': anom.is_resolved,
                    'decision': anom.decision or 'None'
                }
                for anom in sess.anomalies.all()
            ]
        }
        
        response = HttpResponse(json.dumps(report_data, indent=2), content_type='application/json')
        response['Content-Disposition'] = f'attachment; filename="import_report_{sess.id}.json"'
        return response
        
    context = {
        'sessions': sessions,
        'user_groups': user_groups
    }
    return render(request, 'groups/reports.html', context)


@login_required
def history_view(request):
    user = request.user
    user_memberships = GroupMembership.objects.filter(user=user)
    user_groups = [m.group for m in user_memberships]
    
    # Query all expenses and settlements
    expenses = Expense.objects.filter(group__in=user_groups)
    settlements = Settlement.objects.filter(group__in=user_groups)
    
    # Unified list
    history_items = []
    for exp in expenses:
        history_items.append({
            'type': 'Expense',
            'date': exp.expense_date,
            'description': exp.description,
            'group': exp.group,
            'payer': exp.paid_by.name,
            'receiver': 'All members',
            'amount': exp.amount,
            'status': exp.status,
            'created_at': exp.created_at
        })
        
    for setl in settlements:
        history_items.append({
            'type': 'Settlement',
            'date': setl.date,
            'description': f"{setl.payer.name} paid {setl.receiver.name}",
            'group': setl.group,
            'payer': setl.payer.name,
            'receiver': setl.receiver.name,
            'amount': setl.amount,
            'status': 'ACTIVE',
            'created_at': setl.created_at
        })
        
    # Sort by date, then created_at
    history_items.sort(key=lambda x: (x['date'], x['created_at']), reverse=True)
    
    # Filtering
    query = request.GET.get('q', '').strip()
    group_id = request.GET.get('group', '')
    
    if query:
        history_items = [
            item for item in history_items
            if query.lower() in item['description'].lower() or
               query.lower() in item['payer'].lower() or
               query.lower() in item['group'].name.lower()
        ]
        
    if group_id:
        try:
            g_id = int(group_id)
            history_items = [item for item in history_items if item['group'].id == g_id]
        except ValueError:
            pass
            
    # Pagination
    from django.core.paginator import Paginator
    paginator = Paginator(history_items, 15)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    # Simple list display
    context = {
        'history_items': page_obj,
        'user_groups': user_groups,
        'selected_group': group_id,
        'q_query': query
    }
    return render(request, 'groups/history.html', context)


@login_required
def profile_view(request):
    user = request.user
    memberships = GroupMembership.objects.filter(user=user).select_related('group')
    user_groups = [m.group for m in memberships]
    
    # Compute user's net totals across all groups
    total_net = Decimal('0.00')
    total_paid = Decimal('0.00')
    total_shares = Decimal('0.00')
    
    # Get participant profile
    try:
        participant = user.participant
    except Participant.DoesNotExist:
        participant = Participant.objects.create(name=user.name, user=user, is_external=False)
        
    for g in user_groups:
        balances_data = get_group_balances(g)
        
        # User net in this group
        if participant.id in balances_data['balances']:
            user_bal = balances_data['balances'][participant.id]
            total_net += user_bal['net']
            
        # Expenses paid by user in this group
        g_paid = g.expenses.filter(paid_by=participant, status='ACTIVE')
        total_paid += sum(exp.amount for exp in g_paid)
        
        # Split share of user in this group
        g_splits = ExpenseSplit.objects.filter(expense__group=g, participant=participant, expense__status='ACTIVE')
        total_shares += sum(s.share_amount for s in g_splits)
        
    context = {
        'memberships': memberships,
        'total_net': total_net,
        'total_paid': total_paid,
        'total_shares': total_shares,
        'participant': participant
    }
    return render(request, 'groups/profile.html', context)


@login_required
def settings_view(request):
    user = request.user
    
    # System users
    users = CustomUser.objects.all().order_by('name')
    participants = Participant.objects.all().order_by('name')
    
    context = {
        'users': users,
        'participants': participants,
        'usd_rate': getattr(settings, 'USD_TO_INR_RATE', 83.00),
    }
    return render(request, 'groups/settings.html', context)
