from django.db import models
from expense_manager.apps.groups.models import Group
from expense_manager.apps.accounts.models import Participant

class Expense(models.Model):
    SPLIT_TYPES = [
        ('EQUAL', 'Equal'),
        ('PERCENTAGE', 'Percentage'),
        ('SHARES', 'Shares'),
        ('EXACT', 'Exact Amount'),
    ]

    STATUS_CHOICES = [
        ('ACTIVE', 'Active'),
        ('DRAFT', 'Draft'),
        ('INACTIVE', 'Inactive'),
    ]

    group = models.ForeignKey(Group, on_delete=models.CASCADE, related_name='expenses')
    description = models.CharField(max_length=255)
    amount = models.DecimalField(max_digits=12, decimal_places=2)  # Local currency (INR)
    currency = models.CharField(max_length=3, default='INR')
    expense_date = models.DateField()
    paid_by = models.ForeignKey(Participant, on_delete=models.CASCADE, related_name='expenses_paid')
    split_type = models.CharField(max_length=20, choices=SPLIT_TYPES)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='ACTIVE')
    
    # Currency mismatch fields for auditability
    original_amount = models.DecimalField(max_digits=12, decimal_places=4, null=True, blank=True)
    original_currency = models.CharField(max_length=3, null=True, blank=True)
    exchange_rate = models.DecimalField(max_digits=12, decimal_places=6, null=True, blank=True)

    # Auditing back to imports
    import_session = models.ForeignKey(
        'imports.ImportSession',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='expenses'
    )
    import_row_number = models.IntegerField(null=True, blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.description} ({self.amount} {self.currency})"

class ExpenseSplit(models.Model):
    expense = models.ForeignKey(Expense, on_delete=models.CASCADE, related_name='splits')
    participant = models.ForeignKey(Participant, on_delete=models.CASCADE, related_name='splits')
    share_amount = models.DecimalField(max_digits=12, decimal_places=2)
    share_percentage = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    share_ratio = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)

    def __str__(self):
        return f"{self.participant.name} - {self.share_amount} ({self.expense.description})"
