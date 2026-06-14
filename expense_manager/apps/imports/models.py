from django.db import models
from expense_manager.apps.accounts.models import CustomUser, Participant
from expense_manager.apps.groups.models import Group

class ImportSession(models.Model):
    STATUS_CHOICES = [
        ('PENDING_REVIEW', 'Pending Review'),
        ('IMPORTED', 'Imported'),
        ('REJECTED', 'Rejected'),
    ]

    uploaded_by = models.ForeignKey(CustomUser, on_delete=models.CASCADE, related_name='import_sessions')
    group = models.ForeignKey(Group, on_delete=models.CASCADE, related_name='import_sessions')
    file_name = models.CharField(max_length=255)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='PENDING_REVIEW')
    created_at = models.DateTimeField(auto_now_add=True)
    auto_created_accounts_json = models.TextField(null=True, blank=True)

    def __str__(self):
        return f"Session {self.id} for {self.group.name} by {self.uploaded_by.name} ({self.status})"

class ImportRow(models.Model):
    STATUS_CHOICES = [
        ('PENDING', 'Pending'),
        ('RESOLVED', 'Resolved'),
        ('REJECTED', 'Rejected'),
    ]

    session = models.ForeignKey(ImportSession, on_delete=models.CASCADE, related_name='rows')
    row_number = models.IntegerField()
    
    # Raw CSV fields
    date = models.CharField(max_length=50, null=True, blank=True)
    description = models.CharField(max_length=255, null=True, blank=True)
    paid_by = models.CharField(max_length=255, null=True, blank=True)
    amount = models.CharField(max_length=50, null=True, blank=True)
    currency = models.CharField(max_length=10, null=True, blank=True)
    split_type = models.CharField(max_length=50, null=True, blank=True)
    split_with = models.TextField(null=True, blank=True)
    split_details = models.TextField(null=True, blank=True)
    notes = models.TextField(null=True, blank=True)
    
    # Resolved/clean fields (populated initially by auto-fixes, and editable by user)
    resolved_date = models.DateField(null=True, blank=True)
    resolved_description = models.CharField(max_length=255, null=True, blank=True)
    resolved_paid_by_name = models.CharField(max_length=255, null=True, blank=True) # Normalized name of payer
    resolved_amount = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    resolved_currency = models.CharField(max_length=3, null=True, blank=True)
    resolved_split_type = models.CharField(max_length=20, null=True, blank=True)
    resolved_split_with = models.TextField(null=True, blank=True)  # Semicolon separated
    resolved_split_details = models.TextField(null=True, blank=True)
    resolved_notes = models.TextField(null=True, blank=True)
    
    # Multi-currency fields (calculated if USD)
    original_amount = models.DecimalField(max_digits=12, decimal_places=4, null=True, blank=True)
    original_currency = models.CharField(max_length=3, null=True, blank=True)
    exchange_rate = models.DecimalField(max_digits=12, decimal_places=6, null=True, blank=True)

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='PENDING')
    is_imported = models.BooleanField(default=False)
    is_settlement = models.BooleanField(default=False)

    def __str__(self):
        return f"Row {self.row_number} - {self.description or 'No desc'}"

class ImportAnomaly(models.Model):
    SEVERITY_CHOICES = [
        ('INFO', 'INFO'),
        ('WARNING', 'WARNING'),
        ('ERROR', 'ERROR'),
    ]

    DECISION_CHOICES = [
        ('PENDING', 'Pending'),
        ('APPROVED', 'Approved'),
        ('REJECTED', 'Rejected'),
        ('EDITED', 'Edited'),
    ]

    session = models.ForeignKey(ImportSession, on_delete=models.CASCADE, related_name='anomalies')
    row = models.ForeignKey(ImportRow, on_delete=models.CASCADE, related_name='anomalies')
    type = models.CharField(max_length=50)  # e.g., 'CURRENCY_MISMATCH', 'DUPLICATE', etc.
    severity = models.CharField(max_length=10, choices=SEVERITY_CHOICES)
    raw_value = models.TextField()
    suggested_fix = models.TextField()
    decision = models.CharField(max_length=20, choices=DECISION_CHOICES, default='PENDING')
    resolved_value = models.TextField(null=True, blank=True)
    is_resolved = models.BooleanField(default=False)

    def __str__(self):
        return f"Row {self.row.row_number} - {self.type} ({self.severity}) - {self.decision}"
