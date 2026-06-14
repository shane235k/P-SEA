import datetime
from django.test import TestCase
from django.urls import reverse
from expense_manager.apps.accounts.models import CustomUser, Participant
from expense_manager.apps.groups.models import Group, GroupMembership
from expense_manager.apps.expenses.models import Expense
from expense_manager.apps.imports.models import ImportSession

class GroupViewsTestCase(TestCase):
    def setUp(self):
        # Create users
        self.admin = CustomUser.objects.create_user(
            email="aisha@example.com", name="Aisha", role="ADMIN"
        )
        self.admin.set_password("password123")
        self.admin.save()
        
        self.member = CustomUser.objects.create_user(
            email="rohan@example.com", name="Rohan", role="MEMBER"
        )
        self.member.set_password("password123")
        self.member.save()

        # Participants
        self.p_aisha = Participant.objects.create(name="Aisha", user=self.admin)
        self.p_rohan = Participant.objects.create(name="Rohan", user=self.member)

        # Create Group
        self.group = Group.objects.create(name="Shared House", created_by=self.admin)
        
        # Memberships
        GroupMembership.objects.create(
            group=self.group, user=self.admin, joined_at=datetime.date(2026, 1, 1)
        )
        GroupMembership.objects.create(
            group=self.group, user=self.member, joined_at=datetime.date(2026, 1, 1)
        )

        # Expense
        self.expense = Expense.objects.create(
            group=self.group,
            description="Electric Bill",
            amount=3500.00,
            expense_date=datetime.date(2026, 2, 1),
            paid_by=self.p_aisha,
            split_type="EQUAL",
            status="ACTIVE"
        )

    def test_sidebar_routes_require_login(self):
        # Reports
        response = self.client.get(reverse('reports'))
        self.assertRedirects(response, '/accounts/login/?next=/reports/')
        
        # History
        response = self.client.get(reverse('history'))
        self.assertRedirects(response, '/accounts/login/?next=/history/')

        # Profile
        response = self.client.get(reverse('profile'))
        self.assertRedirects(response, '/accounts/login/?next=/profile/')

        # Settings
        response = self.client.get(reverse('settings'))
        self.assertRedirects(response, '/accounts/login/?next=/settings/')

    def test_sidebar_routes_render_successfully_when_authenticated(self):
        self.client.login(email="aisha@example.com", password="password123")
        
        # Reports
        response = self.client.get(reverse('reports'))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'groups/reports.html')

        # History
        response = self.client.get(reverse('history'))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'groups/history.html')

        # Profile
        response = self.client.get(reverse('profile'))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'groups/profile.html')

        # Settings
        response = self.client.get(reverse('settings'))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'groups/settings.html')

    def test_export_group_report_csv_downloads_successfully(self):
        self.client.login(email="aisha@example.com", password="password123")
        
        response = self.client.get(reverse('export_group_report', args=[self.group.id]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'text/csv')
        self.assertIn('Content-Disposition', response)
        self.assertTrue(response['Content-Disposition'].startswith('attachment; filename="group_Shared House_report_'))

        # Check content
        content = response.content.decode('utf-8')
        lines = content.split('\r\n')
        self.assertTrue(len(lines) > 1)
        # Verify Headers
        headers = lines[0].split(',')
        self.assertEqual(headers[0], 'TYPE')
        self.assertEqual(headers[2], 'DESCRIPTION')
        self.assertEqual(headers[5], 'AMOUNT')
        
        # Verify data row exists
        self.assertIn('Electric Bill', content)
        self.assertIn('3500.0', content)
        self.assertIn('Aisha', content)

    def test_download_import_report_json(self):
        self.client.login(email="aisha@example.com", password="password123")
        
        # Create a mock ImportSession
        session = ImportSession.objects.create(
            uploaded_by=self.admin,
            group=self.group,
            file_name="import_test.csv",
            status="IMPORTED"
        )
        
        url = reverse('reports') + f'?download={session.id}'
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'application/json')
        self.assertIn('Content-Disposition', response)
        self.assertTrue(response['Content-Disposition'].startswith('attachment; filename="import_report_'))
        
        # Verify JSON properties
        import json
        data = json.loads(response.content.decode('utf-8'))
        self.assertEqual(data['session_id'], session.id)
        self.assertEqual(data['file_name'], 'import_test.csv')
        self.assertEqual(data['status'], 'IMPORTED')

    def test_import_report_pdf_view_renders_successfully(self):
        self.client.login(email="aisha@example.com", password="password123")
        
        # Create a mock ImportSession
        session = ImportSession.objects.create(
            uploaded_by=self.admin,
            group=self.group,
            file_name="import_pdf_test.csv",
            status="IMPORTED"
        )
        
        # Reverse import_report_pdf URL
        url = reverse('import_report_pdf', args=[session.id])
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'imports/report_pdf.html')
        self.assertContains(response, 'import_pdf_test.csv')
        self.assertContains(response, 'SplitAudit Execution Audit Report')
