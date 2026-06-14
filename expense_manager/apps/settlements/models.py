from django.db import models
from expense_manager.apps.groups.models import Group
from expense_manager.apps.accounts.models import Participant

class Settlement(models.Model):
    group = models.ForeignKey(Group, on_delete=models.CASCADE, related_name='settlements')
    payer = models.ForeignKey(Participant, on_delete=models.CASCADE, related_name='settlements_paid')
    receiver = models.ForeignKey(Participant, on_delete=models.CASCADE, related_name='settlements_received')
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    currency = models.CharField(max_length=3, default='INR')
    date = models.DateField()
    
    # Audit links
    import_session = models.ForeignKey(
        'imports.ImportSession',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='settlements'
    )
    import_row_number = models.IntegerField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.payer.name} paid {self.receiver.name} {self.amount} {self.currency} on {self.date}"
