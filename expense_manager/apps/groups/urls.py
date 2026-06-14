from django.urls import path
from . import views

urlpatterns = [
    path('', views.dashboard_view, name='dashboard'),
    path('reports/', views.reports_view, name='reports'),
    path('history/', views.history_view, name='history'),
    path('profile/', views.profile_view, name='profile'),
    path('settings/', views.settings_view, name='settings'),
    
    path('groups/create/', views.create_group_view, name='create_group'),
    path('groups/<int:group_id>/', views.group_detail_view, name='group_detail'),
    path('groups/<int:group_id>/add-expense/', views.add_expense_view, name='add_expense'),
    path('groups/<int:group_id>/add-settlement/', views.add_settlement_view, name='add_settlement'),
    path('groups/<int:group_id>/memberships/', views.manage_membership_view, name='manage_memberships'),
    path('groups/<int:group_id>/flush/', views.flush_group_data_view, name='flush_group_data'),
    path('groups/<int:group_id>/export/', views.export_group_report_view, name='export_group_report'),
]
