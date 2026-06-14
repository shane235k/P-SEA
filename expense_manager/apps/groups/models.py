from django.db import models
from expense_manager.apps.accounts.models import CustomUser

class Group(models.Model):
    name = models.CharField(max_length=255)
    created_by = models.ForeignKey(CustomUser, on_delete=models.SET_NULL, null=True, related_name='created_groups')
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name

class GroupMembership(models.Model):
    group = models.ForeignKey(Group, on_delete=models.CASCADE, related_name='memberships')
    user = models.ForeignKey(CustomUser, on_delete=models.CASCADE, related_name='group_memberships')
    joined_at = models.DateField()
    left_at = models.DateField(null=True, blank=True)
    role = models.CharField(
        max_length=20,
        choices=[('ADMIN', 'Admin'), ('MEMBER', 'Member')],
        default='MEMBER'
    )

    def __str__(self):
        left_str = f" to {self.left_at}" if self.left_at else " (active)"
        return f"{self.user.name} in {self.group.name} from {self.joined_at}{left_str}"
