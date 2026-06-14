from django.urls import path
from . import views

urlpatterns = [
    path('', views.dashboard_view, name='dashboard'),
    path('groups/create/', views.create_group_view, name='create_group'),
    path('groups/<int:group_id>/', views.group_detail_view, name='group_detail'),
    path('groups/<int:group_id>/add-expense/', views.add_expense_view, name='add_expense'),
    path('groups/<int:group_id>/add-settlement/', views.add_settlement_view, name='add_settlement'),
    path('groups/<int:group_id>/memberships/', views.manage_membership_view, name='manage_memberships'),
    path('groups/<int:group_id>/flush/', views.flush_group_data_view, name='flush_group_data'),
]
