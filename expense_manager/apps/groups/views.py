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
    
    # Iterate through all groups the user is member of to compute aggregate balances
    for g in user_groups:
        balances_data = get_group_balances(g)
        
        # User net in this group
        if participant.id in balances_data['balances']:
            user_bal = balances_data['balances'][participant.id]
            net_balances_by_group[g.id] = user_bal['net']
            total_net_balance += user_bal['net']
            
        # Simplified debts in this group
        for simp in balances_data['simplifications']:
            if simp['from'].id == participant.id:
                # User owes someone
                to_name = simp['to'].name
                people_you_owe[to_name] = people_you_owe.get(to_name, Decimal('0.00')) + simp['amount']
            elif simp['to'].id == participant.id:
                # Someone owes User
                from_name = simp['from'].name
                people_who_owe_you[from_name] = people_who_owe_you.get(from_name, Decimal('0.00')) + simp['amount']

    # Get recent expenses from user's groups
    recent_expenses = Expense.objects.filter(group__in=user_groups).order_by('-expense_date', '-created_at')[:5]
    
    # Get recent settlements from user's groups
    recent_settlements = Settlement.objects.filter(group__in=user_groups).order_by('-date', '-created_at')[:5]
    
    # Import sessions uploaded by user
    import_status = ImportSession.objects.filter(uploaded_by=user).order_by('-created_at')[:5]
    if user.role == 'ADMIN':
        import_status = ImportSession.objects.all().order_by('-created_at')[:5]

    context = {
        'all_groups': all_groups,
        'user_groups': user_groups,
        'total_net_balance': total_net_balance,
        'people_you_owe': people_you_owe,
        'people_who_owe_you': people_who_owe_you,
        'recent_expenses': recent_expenses,
        'recent_settlements': recent_settlements,
        'import_status': import_status
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
    balances_data = get_group_balances(group)
    
    # Expenses (Include Active, Draft, Inactive)
    expenses = group.expenses.all().order_by('-expense_date', '-created_at')
    
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

    context = {
        'group': group,
        'memberships': memberships,
        'expenses': expenses,
        'settlements': settlements,
        'balances': balances_data['balances'],
        'simplifications': balances_data['simplifications'],
        'explanations': balances_data['explanations'],
        'import_history': import_history,
        'user_part_id': user_part_id
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
        
        # Delete items
        group.expenses.all().delete()
        group.settlements.all().delete()
        group.import_sessions.all().delete()
        
        messages.success(request, f"Successfully flushed all data for group '{group.name}': {expenses_count} expenses, {settlements_count} settlements, and {sessions_count} import sessions deleted.")
        return redirect('group_detail', group_id=group.id)
        
    return redirect('group_detail', group_id=group.id)
