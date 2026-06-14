from decimal import Decimal
from expense_manager.apps.accounts.models import Participant
from expense_manager.apps.expenses.models import Expense, ExpenseSplit
from expense_manager.apps.settlements.models import Settlement
from .split_calculator import round_half_up

def get_group_balances(group):
    """
    Computes net balances and explanations for all participants in a group.
    Returns:
    {
        'balances': {participant_id: {'participant': participant, 'net': Decimal, 'paid': Decimal, 'owed': Decimal, 'settled_paid': Decimal, 'settled_received': Decimal}},
        'simplifications': [{'from': debtor_participant, 'to': creditor_participant, 'amount': Decimal}],
        'explanations': {participant_id: [explanation_item_dict]}
    }
    """
    # Get all active expenses in this group
    expenses = Expense.objects.filter(group=group, status='ACTIVE').prefetch_related('splits', 'splits__participant', 'paid_by')
    
    # Get all settlements in this group
    settlements = Settlement.objects.filter(group=group).select_related('payer', 'receiver')
    
    # Identify all participants involved in this group
    # A participant is involved if they are in the group's memberships OR appeared in any expense/split/settlement
    participants_set = set()
    # Memberships
    for m in group.memberships.select_related('user__participant').all():
        if hasattr(m.user, 'participant'):
            participants_set.add(m.user.participant)
            
    # Also add anyone appearing in expenses or splits or settlements
    for exp in expenses:
        participants_set.add(exp.paid_by)
        for split in exp.splits.all():
            participants_set.add(split.participant)
            
    for setl in settlements:
        participants_set.add(setl.payer)
        participants_set.add(setl.receiver)
        
    participants = list(participants_set)
    
    # Initialize balance structures
    balances = {}
    explanations = {}
    for p in participants:
        balances[p.id] = {
            'participant': p,
            'paid': Decimal('0.00'),
            'owed': Decimal('0.00'),
            'settled_paid': Decimal('0.00'),
            'settled_received': Decimal('0.00'),
            'net': Decimal('0.00')
        }
        explanations[p.id] = []
        
    # Calculate Paid and Owed from Expenses
    for exp in expenses:
        payer = exp.paid_by
        balances[payer.id]['paid'] += exp.amount
        explanations[payer.id].append({
            'type': 'CREDIT',
            'category': 'EXPENSE_PAID',
            'date': exp.expense_date,
            'description': f"Paid for: {exp.description}",
            'amount': exp.amount,
            'reference_id': exp.id,
            'details': f"Total expense: {exp.amount} {exp.currency}"
        })
        
        for split in exp.splits.all():
            sp_part = split.participant
            balances[sp_part.id]['owed'] += split.share_amount
            explanations[sp_part.id].append({
                'type': 'DEBIT',
                'category': 'EXPENSE_OWED',
                'date': exp.expense_date,
                'description': f"Owed for: {exp.description}",
                'amount': split.share_amount,
                'reference_id': exp.id,
                'details': f"Paid by {exp.paid_by.name} (Total: {exp.amount} {exp.currency}, split: {exp.split_type})"
            })
            
    # Calculate Settled Paid and Received from Settlements
    for setl in settlements:
        payer = setl.payer
        receiver = setl.receiver
        
        balances[payer.id]['settled_paid'] += setl.amount
        explanations[payer.id].append({
            'type': 'CREDIT',
            'category': 'SETTLEMENT_PAID',
            'date': setl.date,
            'description': f"Settled payment to {receiver.name}",
            'amount': setl.amount,
            'reference_id': setl.id,
            'details': f"Sent peer settlement to {receiver.name}"
        })
        
        balances[receiver.id]['settled_received'] += setl.amount
        explanations[receiver.id].append({
            'type': 'DEBIT',
            'category': 'SETTLEMENT_RECEIVED',
            'date': setl.date,
            'description': f"Settled payment from {payer.name}",
            'amount': setl.amount,
            'reference_id': setl.id,
            'details': f"Received peer settlement from {payer.name}"
        })
        
    # Calculate Net positions
    for p_id, bal in balances.items():
        # Net = Paid - Owed + Settled_Paid - Settled_Received
        bal['net'] = bal['paid'] - bal['owed'] + bal['settled_paid'] - bal['settled_received']
        
    # Debt Simplification
    # Separate into creditors (net > 0) and debtors (net < 0)
    creditors = []
    debtors = []
    
    for p_id, bal in balances.items():
        net = bal['net']
        if net > Decimal('0.005'):
            creditors.append({'participant': bal['participant'], 'amount': net})
        elif net < Decimal('-0.005'):
            debtors.append({'participant': bal['participant'], 'amount': -net}) # Store as positive number for matching
            
    # Sort creditors descending, debtors descending
    creditors.sort(key=lambda x: x['amount'], reverse=True)
    debtors.sort(key=lambda x: x['amount'], reverse=True)
    
    simplifications = []
    
    c_idx = 0
    d_idx = 0
    
    while c_idx < len(creditors) and d_idx < len(debtors):
        creditor = creditors[c_idx]
        debtor = debtors[d_idx]
        
        c_amt = creditor['amount']
        d_amt = debtor['amount']
        
        transfer_amt = min(c_amt, d_amt)
        transfer_amt = round_half_up(transfer_amt)
        
        if transfer_amt > 0:
            simplifications.append({
                'from': debtor['participant'],
                'to': creditor['participant'],
                'amount': transfer_amt
            })
            
        creditor['amount'] -= transfer_amt
        debtor['amount'] -= transfer_amt
        
        if creditor['amount'] < Decimal('0.005'):
            c_idx += 1
        if debtor['amount'] < Decimal('0.005'):
            d_idx += 1
            
    # Sort explanations by date
    for p_id in explanations:
        explanations[p_id].sort(key=lambda x: x['date'])
        
    return {
        'balances': balances,
        'simplifications': simplifications,
        'explanations': explanations
    }
