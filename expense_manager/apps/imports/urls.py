from django.urls import path
from . import views

urlpatterns = [
    path('groups/<int:group_id>/import/', views.upload_csv_view, name='upload_csv'),
    path('imports/session/<int:session_id>/', views.import_review_view, name='import_review'),
    path('imports/session/<int:session_id>/row/<int:row_id>/approve/', views.approve_row_view, name='approve_row'),
    path('imports/session/<int:session_id>/row/<int:row_id>/reject/', views.reject_row_view, name='reject_row'),
    path('imports/session/<int:session_id>/row/<int:row_id>/edit/', views.edit_staged_row_view, name='edit_row'),
    path('imports/session/<int:session_id>/row/<int:row_id>/resolve-duplicate/', views.resolve_duplicate_view, name='resolve_duplicate'),
    path('imports/session/<int:session_id>/finalize/', views.finalize_import_view, name='finalize_import'),
    path('imports/session/<int:session_id>/report/', views.import_report_view, name='import_report'),
    path('imports/session/<int:session_id>/pdf/', views.import_report_pdf_view, name='import_report_pdf'),
]
