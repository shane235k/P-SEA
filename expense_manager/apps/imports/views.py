import datetime
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.conf import settings
from expense_manager.apps.groups.models import Group, GroupMembership
from expense_manager.apps.imports.models import ImportSession, ImportRow, ImportAnomaly
from expense_manager.apps.imports.services.csv_parser import parse_csv_to_staging
from expense_manager.apps.imports.services.anomaly_detector import detect_anomalies
from expense_manager.apps.imports.services.import_processor import finalize_session_import

@login_required
def upload_csv_view(request, group_id):
    group = get_object_or_404(Group, id=group_id)
    
    if request.user.role != 'ADMIN':
        messages.error(request, "Only Administrators can import CSV data.")
        return redirect('group_detail', group_id=group.id)
        
    if request.method == 'POST' and request.FILES.get('csv_file'):
        csv_file = request.FILES['csv_file']
        
        if not csv_file.name.endswith('.csv'):
            messages.error(request, "Please upload a valid CSV file.")
            return redirect('group_detail', group_id=group.id)
            
        try:
            # Read bytes content
            file_content = csv_file.read()
            
            # Create ImportSession
            session = ImportSession.objects.create(
                uploaded_by=request.user,
                group=group,
                file_name=csv_file.name,
                status='PENDING_REVIEW'
            )
            
            # Parse into staging tables
            parse_csv_to_staging(session, file_content)
            
            # Run Anomaly Detection
            detect_anomalies(session)
            
            messages.success(request, f"CSV uploaded successfully! {session.rows.count()} rows staged for review.")
            return redirect('import_review', session_id=session.id)
            
        except Exception as e:
            messages.error(request, f"Error processing CSV: {str(e)}")
            return redirect('group_detail', group_id=group.id)
            
    return render(request, 'imports/upload_csv.html', {'group': group})

@login_required
def import_review_view(request, session_id):
    session = get_object_or_404(ImportSession, id=session_id)
    
    # Check authorization
    if request.user.role != 'ADMIN':
        messages.error(request, "Only Administrators can review imports.")
        return redirect('group_detail', group_id=session.group.id)
        
    # Get all staging rows and anomalies
    rows = session.rows.all().order_by('row_number').prefetch_related('anomalies')
    
    # Count of active errors
    unresolved_errors_count = session.anomalies.filter(severity='ERROR', is_resolved=False).exclude(row__status='REJECTED').count()
    
    context = {
        'session': session,
        'rows': rows,
        'unresolved_errors_count': unresolved_errors_count
    }
    return render(request, 'imports/import_review.html', context)

@login_required
def approve_row_view(request, session_id, row_id):
    session = get_object_or_404(ImportSession, id=session_id)
    row = get_object_or_404(ImportRow, id=row_id, session=session)
    
    if request.user.role != 'ADMIN':
        messages.error(request, "Access denied.")
        return redirect('dashboard')
        
    # Confirming the row matches the auto-fixes
    row.status = 'RESOLVED'
    row.save()
    
    # Mark warning/info anomalies on this row as resolved
    row.anomalies.all().update(is_resolved=True, decision='APPROVED')
    
    messages.success(request, f"Row {row.row_number} approved.")
    return redirect('import_review', session_id=session.id)

@login_required
def reject_row_view(request, session_id, row_id):
    session = get_object_or_404(ImportSession, id=session_id)
    row = get_object_or_404(ImportRow, id=row_id, session=session)
    
    if request.user.role != 'ADMIN':
        messages.error(request, "Access denied.")
        return redirect('dashboard')
        
    row.status = 'REJECTED'
    row.save()
    
    row.anomalies.all().update(is_resolved=True, decision='REJECTED')
    
    messages.info(request, f"Row {row.row_number} rejected (will not be imported).")
    return redirect('import_review', session_id=session.id)

@login_required
def edit_staged_row_view(request, session_id, row_id):
    session = get_object_or_404(ImportSession, id=session_id)
    row = get_object_or_404(ImportRow, id=row_id, session=session)
    
    if request.user.role != 'ADMIN':
        messages.error(request, "Access denied.")
        return redirect('dashboard')
        
    if request.method == 'POST':
        # Retrieve edited values
        row.resolved_description = request.POST.get('description', '').strip()
        row.resolved_paid_by_name = request.POST.get('paid_by', '').strip()
        
        amt_str = request.POST.get('amount', '').strip()
        from decimal import Decimal
        try:
            row.resolved_amount = Decimal(amt_str) if amt_str else None
        except Exception:
            row.resolved_amount = None
            
        row.resolved_currency = request.POST.get('currency', 'INR').strip()
        row.resolved_split_type = request.POST.get('split_type', 'EQUAL').strip().upper()
        row.resolved_split_with = request.POST.get('split_with', '').strip()
        row.resolved_split_details = request.POST.get('split_details', '').strip()
        row.resolved_notes = request.POST.get('notes', '').strip()
        
        dt_str = request.POST.get('date', '').strip()
        if dt_str:
            try:
                row.resolved_date = datetime.datetime.strptime(dt_str, '%Y-%m-%d').date()
            except Exception:
                row.resolved_date = None
                
        row.is_settlement = 'is_settlement' in request.POST
        
        duplicate_action = request.POST.get('duplicate_action', '')
        if duplicate_action == 'duplicate':
            row.status = 'REJECTED'
            row.save()
            row.anomalies.all().update(is_resolved=True, decision='REJECTED')
        else:
            row.status = 'RESOLVED'
            row.save()
            row.anomalies.all().update(is_resolved=True, decision='EDITED')
            if duplicate_action == 'separate':
                row.anomalies.filter(type='DUPLICATE_ENTRY').update(is_resolved=True, decision='APPROVED')
        
        # Re-run anomaly detector to see if new/re-evaluated errors
        detect_anomalies(session)
        
        messages.success(request, f"Row {row.row_number} edits saved.")
        return redirect('import_review', session_id=session.id)
        
    has_duplicate_anomaly = row.anomalies.filter(type='DUPLICATE_ENTRY').exists()
    duplicate_decision = 'PENDING'
    if has_duplicate_anomaly:
        duplicate_decision = row.anomalies.filter(type='DUPLICATE_ENTRY').first().decision
        
    context = {
        'session': session,
        'row': row,
        'has_duplicate_anomaly': has_duplicate_anomaly,
        'duplicate_decision': duplicate_decision
    }
    return render(request, 'imports/edit_row.html', context)

@login_required
def finalize_import_view(request, session_id):
    session = get_object_or_404(ImportSession, id=session_id)
    
    if request.user.role != 'ADMIN':
        messages.error(request, "Access denied.")
        return redirect('dashboard')
        
    try:
        report = finalize_session_import(session, request.user)
        # Store report in session to display on report page
        request.session[f'report_{session.id}'] = report
        messages.success(request, "CSV data imported successfully!")
        return redirect('import_report', session_id=session.id)
    except Exception as e:
        messages.error(request, f"Finalization failed: {str(e)}")
        return redirect('import_review', session_id=session.id)

@login_required
def import_report_view(request, session_id):
    session = get_object_or_404(ImportSession, id=session_id)
    
    # Check if report was cached in session, else mock one from actual DB records
    report = request.session.get(f'report_{session.id}', None)
    
    if not report:
        # Mock summary if reloading later
        report = {
            'session_id': session.id,
            'group_name': session.group.name,
            'file_name': session.file_name,
            'uploaded_by': session.uploaded_by.name,
            'status': session.status,
            'rows_processed': session.rows.count(),
            'rows_imported': session.rows.filter(is_imported=True).count(),
            'rows_rejected': session.rows.filter(status='REJECTED').count(),
            'anomalies_detected': session.anomalies.count(),
            'timestamp': session.created_at.strftime('%Y-%m-%d %H:%M:%S UTC'),
            'executor': session.uploaded_by.name
        }
        
    rows = session.rows.all().order_by('row_number').prefetch_related('anomalies')
    
    import json
    auto_created_accounts = []
    if session.auto_created_accounts_json:
        try:
            auto_created_accounts = json.loads(session.auto_created_accounts_json)
        except Exception:
            pass
            
    context = {
        'session': session,
        'report': report,
        'rows': rows,
        'auto_created_accounts': auto_created_accounts
    }
    return render(request, 'imports/import_report.html', context)


@login_required
def resolve_duplicate_view(request, session_id, row_id):
    session = get_object_or_404(ImportSession, id=session_id)
    row = get_object_or_404(ImportRow, id=row_id, session=session)
    
    if request.user.role != 'ADMIN':
        messages.error(request, "Access denied.")
        return redirect('dashboard')
        
    if request.method == 'POST':
        resolution = request.POST.get('resolution', '')
        
        if resolution == 'duplicate':
            # Mark as duplicate -> reject it
            row.status = 'REJECTED'
            row.save()
            # Mark anomalies as resolved by rejection
            row.anomalies.all().update(is_resolved=True, decision='REJECTED')
            # Re-run detector to update exact duplicate counters
            detect_anomalies(session)
            messages.success(request, f"Row {row.row_number} rejected as duplicate. Duplicate warnings updated.")
        elif resolution == 'separate':
            # Mark as separate -> keep it
            # Find duplicate anomalies on this row and mark them as resolved/approved
            row.anomalies.filter(type='DUPLICATE_ENTRY').update(is_resolved=True, decision='APPROVED')
            
            # Check if there are other errors remaining. If not, set row status to RESOLVED
            has_errors = row.anomalies.filter(severity='ERROR', is_resolved=False).exists()
            if not has_errors:
                row.status = 'RESOLVED'
            row.save()
            
            messages.success(request, f"Row {row.row_number} marked as a separate transaction.")
            
    return redirect('import_review', session_id=session.id)

