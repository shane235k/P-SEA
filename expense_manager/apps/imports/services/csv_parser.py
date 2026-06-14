import csv
from expense_manager.apps.imports.models import ImportRow

def parse_csv_to_staging(session, file_content):
    """
    Parses raw CSV string content and saves to ImportRow staging table.
    """
    # Split by newline
    lines = file_content.decode('utf-8').splitlines()
    reader = csv.DictReader(lines)
    
    rows_created = []
    for idx, row in enumerate(reader):
        line_number = idx + 2  # Line 1 is headers
        
        db_row = ImportRow.objects.create(
            session=session,
            row_number=line_number,
            date=row.get('date', '').strip() if row.get('date') else '',
            description=row.get('description', '').strip() if row.get('description') else '',
            paid_by=row.get('paid_by', '').strip() if row.get('paid_by') else '',
            amount=row.get('amount', '').strip() if row.get('amount') else '',
            currency=row.get('currency', '').strip() if row.get('currency') else '',
            split_type=row.get('split_type', '').strip() if row.get('split_type') else '',
            split_with=row.get('split_with', '').strip() if row.get('split_with') else '',
            split_details=row.get('split_details', '').strip() if row.get('split_details') else '',
            notes=row.get('notes', '').strip() if row.get('notes') else ''
        )
        rows_created.append(db_row)
        
    return rows_created
