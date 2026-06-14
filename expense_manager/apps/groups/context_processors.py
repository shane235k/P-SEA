from expense_manager.apps.groups.models import GroupMembership

def user_groups(request):
    if request.user.is_authenticated:
        memberships = GroupMembership.objects.filter(user=request.user)
        groups = [m.group for m in memberships]
        return {'user_groups': groups}
    return {'user_groups': []}
