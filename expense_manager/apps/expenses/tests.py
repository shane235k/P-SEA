import datetime
from decimal import Decimal
from django.test import TestCase
from django.urls import reverse
from expense_manager.apps.accounts.models import CustomUser, Participant
from expense_manager.apps.groups.models import Group, GroupMembership
from expense_manager.apps.expenses.models import Expense, ExpenseSplit
from expense_manager.apps.settlements.models import Settlement
from expense_manager.apps.expenses.services.split_calculator import calculate_splits, parse_split_details
from expense_manager.apps.expenses.services.balance_calculator import get_group_balances
from expense_manager.apps.imports.services.anomaly_detector import parse_date_robust

class SplitCalculatorTestCase(TestCase):
    def setUp(self):
        self.aisha = Participant.objects.create(name="Aisha", is_external=False)
        self.rohan = Participant.objects.create(name="Rohan", is_external=False)
        self.priya = Participant.objects.create(name="Priya", is_external=False)
        self.participants = [self.aisha, self.rohan, self.priya]

    def test_parse_split_details(self):
        details = "Aisha 30%; Rohan 40%; Priya 30%"
        parsed = parse_split_details(details)
        self.assertEqual(parsed['Aisha'], Decimal('30'))
        self.assertEqual(parsed['Rohan'], Decimal('40'))
        self.assertEqual(parsed['Priya'], Decimal('30'))

        details_shares = "Aisha 1; Rohan 2; Priya 1"
        parsed_shares = parse_split_details(details_shares)
        self.assertEqual(parsed_shares['Aisha'], Decimal('1'))
        self.assertEqual(parsed_shares['Rohan'], Decimal('2'))

    def test_equal_split_rounding(self):
        # 100 divided by 3 is 33.33, 33.33, 33.34
        splits = calculate_splits(Decimal('100.00'), 'EQUAL', self.participants)
        amounts = [s['share_amount'] for s in splits]
        self.assertEqual(sum(amounts), Decimal('100.00'))
        self.assertIn(Decimal('33.34'), amounts)
        self.assertIn(Decimal('33.33'), amounts)

    def test_percentage_split(self):
        splits = calculate_splits(
            Decimal('1500.00'),
            'PERCENTAGE',
            self.participants,
            "Aisha 30%; Rohan 40%; Priya 30%"
        )
        shares_map = {s['participant'].name: s['share_amount'] for s in splits}
        self.assertEqual(shares_map['Aisha'], Decimal('450.00'))
        self.assertEqual(shares_map['Rohan'], Decimal('600.00'))
        self.assertEqual(shares_map['Priya'], Decimal('450.00'))

    def test_shares_split(self):
        splits = calculate_splits(
            Decimal('3600.00'),
            'SHARES',
            self.participants,
            "Aisha 1; Rohan 2; Priya 1"
        )
        shares_map = {s['participant'].name: s['share_amount'] for s in splits}
        self.assertEqual(shares_map['Aisha'], Decimal('900.00'))
        self.assertEqual(shares_map['Rohan'], Decimal('1800.00'))
        self.assertEqual(shares_map['Priya'], Decimal('900.00'))


class DateParserTestCase(TestCase):
    def test_parse_date_robust(self):
        # Standard YYYY-MM-DD
        dt, amb, msg = parse_date_robust("2026-02-01")
        self.assertEqual(dt, datetime.date(2026, 2, 1))
        self.assertFalse(amb)

        # Unambiguous DD/MM/YYYY
        dt, amb, msg = parse_date_robust("15/03/2026")
        self.assertEqual(dt, datetime.date(2026, 3, 15))
        self.assertFalse(amb)

        # Ambiguous DD/MM/YYYY
        dt, amb, msg = parse_date_robust("01/03/2026")
        self.assertEqual(dt, datetime.date(2026, 3, 1))
        self.assertTrue(amb)

        # Missing Year Month DD
        dt, amb, msg = parse_date_robust("Mar 14")
        self.assertEqual(dt, datetime.date(2026, 3, 14))
        self.assertTrue(amb)


class BalanceCalculatorTestCase(TestCase):
    def setUp(self):
        # Users
        self.admin_user = CustomUser.objects.create_user(email="admin@example.com", name="Admin", role="ADMIN")
        self.aisha_user = CustomUser.objects.create_user(email="aisha@example.com", name="Aisha")
        self.rohan_user = CustomUser.objects.create_user(email="rohan@example.com", name="Rohan")
        
        # Participants
        self.aisha = Participant.objects.create(name="Aisha", user=self.aisha_user, is_external=False)
        self.rohan = Participant.objects.create(name="Rohan", user=self.rohan_user, is_external=False)
        self.dev = Participant.objects.create(name="Dev", is_external=True)

        # Group
        self.group = Group.objects.create(name="Test Flat", created_by=self.admin_user)
        
        # Memberships
        # Aisha joined 2026-01-01
        # Rohan joined 2026-02-01
        GroupMembership.objects.create(group=self.group, user=self.aisha_user, joined_at=datetime.date(2026, 1, 1))
        GroupMembership.objects.create(group=self.group, user=self.rohan_user, joined_at=datetime.date(2026, 2, 1))

    def test_balances_respect_membership_dates(self):
        # Aisha pays ₹3000 on Jan 15th (Rohan was not a member yet).
        # Expense date: 2026-01-15.
        # Split was created equally, but Rohan should be protected by joined_at.
        # Here we verify the split logic.
        expense = Expense.objects.create(
            group=self.group,
            description="Jan Internet",
            amount=Decimal('3000.00'),
            expense_date=datetime.date(2026, 1, 15),
            paid_by=self.aisha,
            split_type='EQUAL',
            status='ACTIVE'
        )
        
        # Split only among Aisha (Rohan hadn't joined yet)
        ExpenseSplit.objects.create(expense=expense, participant=self.aisha, share_amount=Decimal('3000.00'))

        # Aisha pays ₹1200 on Feb 10th (Rohan joined on Feb 1st, so he is included).
        expense2 = Expense.objects.create(
            group=self.group,
            description="Feb Internet",
            amount=Decimal('1200.00'),
            expense_date=datetime.date(2026, 2, 10),
            paid_by=self.aisha,
            split_type='EQUAL',
            status='ACTIVE'
        )
        ExpenseSplit.objects.create(expense=expense2, participant=self.aisha, share_amount=Decimal('600.00'))
        ExpenseSplit.objects.create(expense=expense2, participant=self.rohan, share_amount=Decimal('600.00'))

        # Settlement: Rohan pays Aisha ₹600 on Feb 25
        Settlement.objects.create(
            group=self.group,
            payer=self.rohan,
            receiver=self.aisha,
            amount=Decimal('600.00'),
            date=datetime.date(2026, 2, 25)
        )

        balances_data = get_group_balances(self.group)
        
        # Aisha:
        # Paid: 3000 + 1200 = 4200
        # Owed: 3000 (Jan) + 600 (Feb) = 3600
        # Settlements Received: 600
        # Net: 4200 - 3600 + 0 - 600 = 0.00
        aisha_net = balances_data['balances'][self.aisha.id]['net']
        self.assertEqual(aisha_net, Decimal('0.00'))

        # Rohan:
        # Paid: 0
        # Owed: 600 (Feb)
        # Settlements Paid: 600
        # Net: 0 - 600 + 600 - 0 = 0.00
        rohan_net = balances_data['balances'][self.rohan.id]['net']
        self.assertEqual(rohan_net, Decimal('0.00'))
        
        # Excludes Dev from simplified transfer
        self.assertEqual(len(balances_data['simplifications']), 0)

from expense_manager.apps.expenses.templatetags.custom_filters import absolute

class TemplateFiltersTestCase(TestCase):
    def test_absolute_filter(self):
        self.assertEqual(absolute(Decimal('-50.25')), Decimal('50.25'))
        self.assertEqual(absolute(Decimal('120.00')), Decimal('120.00'))
        self.assertEqual(absolute(-15), 15)
        self.assertEqual(absolute("not-a-number"), "not-a-number")

from expense_manager.apps.imports.models import ImportSession, ImportRow, ImportAnomaly
from expense_manager.apps.imports.services.anomaly_detector import detect_anomalies

class StagingDuplicatesTestCase(TestCase):
    def setUp(self):
        self.admin = CustomUser.objects.create_user(email="admin2@example.com", name="Admin")
        self.group = Group.objects.create(name="Test Group 2", created_by=self.admin)
        self.session = ImportSession.objects.create(uploaded_by=self.admin, group=self.group, file_name="test.csv")

    def test_duplicate_rejection_clears_other_duplicates(self):
        # Create two identical staged rows
        row1 = ImportRow.objects.create(
            session=self.session,
            row_number=2,
            date="2026-02-01",
            description="Rent",
            paid_by="Aisha",
            amount="48000",
            currency="INR",
            split_type="equal",
            split_with="Aisha;Rohan"
        )
        row2 = ImportRow.objects.create(
            session=self.session,
            row_number=3,
            date="2026-02-01",
            description="Rent",
            paid_by="Aisha",
            amount="48000",
            currency="INR",
            split_type="equal",
            split_with="Aisha;Rohan"
        )

        # First run: both should be flagged as duplicates
        detect_anomalies(self.session)
        
        # Reload rows to fetch updated staging status/relations
        row1_reload = ImportRow.objects.get(id=row1.id)
        row2_reload = ImportRow.objects.get(id=row2.id)
        self.assertTrue(row1_reload.anomalies.filter(type='DUPLICATE_ENTRY').exists())
        self.assertTrue(row2_reload.anomalies.filter(type='DUPLICATE_ENTRY').exists())

        # Set row2 to REJECTED
        row2_reload.status = 'REJECTED'
        row2_reload.save()

        # Re-run: row1 should no longer be duplicate!
        detect_anomalies(self.session)
        row1_final = ImportRow.objects.get(id=row1.id)
        self.assertFalse(row1_final.anomalies.filter(type='DUPLICATE_ENTRY', is_resolved=False).exists())
        self.assertTrue(row1_final.anomalies.filter(type='DUPLICATE_ENTRY', is_resolved=True).exists())

    def test_missing_user_and_auto_creation(self):
        # Create a staged row with a completely new user
        row = ImportRow.objects.create(
            session=self.session,
            row_number=4,
            date="2026-02-01",
            description="Dinner",
            paid_by="NewGuy",
            amount="1200",
            currency="INR",
            split_type="equal",
            split_with="NewGuy;Admin"
        )
        
        # NewGuy is not registered. Run anomaly detection.
        detect_anomalies(self.session)
        
        row_reload = ImportRow.objects.get(id=row.id)
        # Verify MISSING_USER anomaly was raised
        self.assertTrue(row_reload.anomalies.filter(type='MISSING_USER').exists())
        
        # Verify the anomaly is saved and not deleted when we run again
        anom = row_reload.anomalies.get(type='MISSING_USER')
        anom.is_resolved = True
        anom.decision = 'APPROVED'
        anom.save()
        
        # Run detect_anomalies again, and verify that the decision is preserved
        detect_anomalies(self.session)
        row_reloaded_again = ImportRow.objects.get(id=row.id)
        anom_check = row_reloaded_again.anomalies.get(type='MISSING_USER')
        self.assertTrue(anom_check.is_resolved)
        self.assertEqual(anom_check.decision, 'APPROVED')
        
        # Now finalize the import session. It should automatically create the NewGuy CustomUser.
        from expense_manager.apps.imports.services.import_processor import finalize_session_import
        # We need to add membership for Admin (self.admin) so no errors block finalization, or make sure NewGuy is processed
        from expense_manager.apps.groups.models import GroupMembership
        GroupMembership.objects.create(group=self.group, user=self.admin, joined_at=datetime.date(2026, 1, 1))
        
        report = finalize_session_import(self.session, self.admin)
        
        # Verify NewGuy was created as a system user
        new_user = CustomUser.objects.filter(name__iexact="NewGuy").first()
        self.assertIsNotNone(new_user)
        self.assertEqual(new_user.email, "newguy@dev.local")
        
        # Verify the password and credentials list was stored in report and model
        self.assertIn("NewGuy", self.session.auto_created_accounts_json)

    def test_alias_resolution_options(self):
        # Create a participant Aisha
        aisha_user = CustomUser.objects.create_user(email="aisha@example.com", name="Aisha")
        aisha_participant = Participant.objects.create(name="Aisha", user=aisha_user)
        
        # Create a staged row with payer alias "Aisha S"
        row = ImportRow.objects.create(
            session=self.session,
            row_number=5,
            date="2026-02-01",
            description="Coffee",
            paid_by="Aisha S",
            amount="120",
            currency="INR",
            split_type="equal",
            split_with="Aisha;Admin"
        )
        
        # Run anomaly detection
        detect_anomalies(self.session)
        
        row_reload = ImportRow.objects.get(id=row.id)
        # Verify ALIAS_MAPPING anomaly is raised
        self.assertTrue(row_reload.anomalies.filter(type='ALIAS_MAPPING').exists())
        # The auto-resolution by default maps it (sets res_payer to Aisha)
        self.assertEqual(row_reload.resolved_paid_by_name, "Aisha")
        
        # Scenario 1: User chooses 'create' (keep alias and create new user)
        # Simulate POST action by calling the view or doing database updates & re-running detection
        # Set decision to EDITED
        anom = row_reload.anomalies.get(type='ALIAS_MAPPING')
        anom.is_resolved = True
        anom.decision = 'EDITED'
        anom.save()
        
        # When user chooses create, views.py sets resolved_paid_by_name to raw name "Aisha S"
        row_reload.resolved_paid_by_name = "Aisha S"
        row_reload.save()
        
        # Re-run detection
        detect_anomalies(self.session)
        
        row_reload2 = ImportRow.objects.get(id=row.id)
        # Verify the raw name is preserved and not overwritten to Aisha
        self.assertEqual(row_reload2.resolved_paid_by_name, "Aisha S")
        # Verify the anomaly is still in the DB with status EDITED/resolved
        anom2 = row_reload2.anomalies.get(type='ALIAS_MAPPING')
        self.assertTrue(anom2.is_resolved)
        self.assertEqual(anom2.decision, 'EDITED')
        
        # Scenario 2: User chooses 'map'
        # Set decision to APPROVED, and set name to base name "Aisha"
        anom2.is_resolved = True
        anom2.decision = 'APPROVED'
        anom2.save()
        row_reload2.resolved_paid_by_name = "Aisha"
        row_reload2.save()
        
        # Re-run detection
        detect_anomalies(self.session)
        row_reload3 = ImportRow.objects.get(id=row.id)
        # Since the name is now Aisha, which matches base name, the ALIAS_MAPPING warning is resolved/cleared from DB
        self.assertFalse(row_reload3.anomalies.filter(type='ALIAS_MAPPING', is_resolved=False).exists())
        self.assertTrue(row_reload3.anomalies.filter(type='ALIAS_MAPPING', is_resolved=True).exists())

        # Test editing GET renders dropdown and the resolve_alias views
        self.admin.role = 'ADMIN'
        self.admin.set_password("password123")
        self.admin.save()
        self.client.login(email="admin2@example.com", password="password123")
        
        # Reset row to trigger ALIAS_MAPPING warning
        row_reload3.resolved_paid_by_name = "Aisha S"
        row_reload3.save()
        detect_anomalies(self.session)
        
        # Test GET edit row has alias resolution option in template
        response = self.client.get(reverse('edit_row', args=[self.session.id, row.id]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Name Alias Resolution')
        
        # Test POST resolve_alias to 'create' (Keep Name)
        resolve_url = reverse('resolve_alias', args=[self.session.id, row.id])
        response = self.client.post(resolve_url, {'resolution': 'create'})
        self.assertRedirects(response, reverse('import_review', args=[self.session.id]))
        
        # Verify row name is kept as "Aisha S" and anomaly is resolved as EDITED
        row_final = ImportRow.objects.get(id=row.id)
        self.assertEqual(row_final.resolved_paid_by_name, "Aisha S")
        anom_final = row_final.anomalies.get(type='ALIAS_MAPPING')
        self.assertTrue(anom_final.is_resolved)
        self.assertEqual(anom_final.decision, 'EDITED')
        
        # Test POST resolve_alias to 'map' (Map to existing user)
        response = self.client.post(resolve_url, {'resolution': 'map'})
        self.assertRedirects(response, reverse('import_review', args=[self.session.id]))
        row_final2 = ImportRow.objects.get(id=row.id)
        self.assertEqual(row_final2.resolved_paid_by_name, "Aisha")
        self.assertFalse(row_final2.anomalies.filter(type='ALIAS_MAPPING', is_resolved=False).exists())
        self.assertTrue(row_final2.anomalies.filter(type='ALIAS_MAPPING', is_resolved=True).exists())




