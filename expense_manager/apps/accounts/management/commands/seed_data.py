import datetime
from django.core.management.base import BaseCommand
from expense_manager.apps.accounts.models import CustomUser, Participant
from expense_manager.apps.groups.models import Group, GroupMembership

class Command(BaseCommand):
    help = 'Seeds initial users, participants, groups, and memberships for the technical assessment'

    def handle(self, *args, **options):
        self.stdout.write('Seeding database with test data...')

        # 1. Create Users
        users_data = [
            {'name': 'Aisha', 'email': 'aisha@example.com', 'role': 'ADMIN'},
            {'name': 'Rohan', 'email': 'rohan@example.com', 'role': 'MEMBER'},
            {'name': 'Priya', 'email': 'priya@example.com', 'role': 'MEMBER'},
            {'name': 'Meera', 'email': 'meera@example.com', 'role': 'MEMBER'},
            {'name': 'Sam', 'email': 'sam@example.com', 'role': 'MEMBER'},
        ]

        users = {}
        for ud in users_data:
            user, created = CustomUser.objects.get_or_create(
                email=ud['email'],
                defaults={
                    'name': ud['name'],
                    'role': ud['role'],
                    'is_staff': ud['role'] == 'ADMIN',
                    'is_superuser': ud['role'] == 'ADMIN'
                }
            )
            if created:
                user.set_password('password123')
                user.save()
                self.stdout.write(f"Created user {user.name}")
            else:
                self.stdout.write(f"User {user.name} already exists")
            users[user.name] = user

            # Create or link Participant
            part, p_created = Participant.objects.get_or_create(
                name=user.name,
                defaults={'user': user, 'is_external': False}
            )
            if p_created:
                self.stdout.write(f"Created participant for user {user.name}")
            else:
                if not part.user:
                    part.user = user
                    part.is_external = False
                    part.save()
                    self.stdout.write(f"Linked existing participant {part.name} to user")

        # 2. Create External Participants
        external_names = ['Dev', 'Kabir']
        for name in external_names:
            part, p_created = Participant.objects.get_or_create(
                name=name,
                defaults={'is_external': True}
            )
            if p_created:
                self.stdout.write(f"Created external participant {name}")

        # 3. Create Group
        group, g_created = Group.objects.get_or_create(
            name='Shared Flat',
            defaults={'created_by': users['Aisha']}
        )
        if g_created:
            self.stdout.write("Created group 'Shared Flat'")
        else:
            self.stdout.write("Group 'Shared Flat' already exists")

        # 4. Create Memberships with time bounds
        # Aisha: Joined 2026-01-01
        # Rohan: Joined 2026-01-01
        # Priya: Joined 2026-01-01
        # Meera: Joined 2026-01-01, Left 2026-03-31
        # Sam: Joined 2026-04-15
        memberships_data = [
            {'user': users['Aisha'], 'joined': datetime.date(2026, 1, 1), 'left': None, 'role': 'ADMIN'},
            {'user': users['Rohan'], 'joined': datetime.date(2026, 1, 1), 'left': None, 'role': 'MEMBER'},
            {'user': users['Priya'], 'joined': datetime.date(2026, 1, 1), 'left': None, 'role': 'MEMBER'},
            {'user': users['Meera'], 'joined': datetime.date(2026, 1, 1), 'left': datetime.date(2026, 3, 31), 'role': 'MEMBER'},
            {'user': users['Sam'], 'joined': datetime.date(2026, 4, 15), 'left': None, 'role': 'MEMBER'},
        ]

        for md in memberships_data:
            membership, m_created = GroupMembership.objects.get_or_create(
                group=group,
                user=md['user'],
                defaults={
                    'joined_at': md['joined'],
                    'left_at': md['left'],
                    'role': md['role']
                }
            )
            if m_created:
                left_str = f" to {md['left']}" if md['left'] else " (active)"
                self.stdout.write(f"Added membership for {md['user'].name} from {md['joined']}{left_str}")
            else:
                self.stdout.write(f"Membership for {md['user'].name} already exists")

        self.stdout.write(self.style.SUCCESS('Database seeding completed successfully!'))
