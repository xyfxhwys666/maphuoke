from __future__ import annotations

from io import BytesIO

import pytest
from backend.app.batch.importers import CompanyInputImporter, ImportValidationError
from openpyxl import Workbook


def test_utf8_csv_import_normalizes_headers_and_deduplicates_identity() -> None:
    csv_data = '公司名称,城市\n深圳示例科技有限公司,深圳市\n 深圳示例科技有限公司 ,深圳市\n广州另一家公司,广州市\n'

    rows = CompanyInputImporter.from_csv(csv_data)

    assert [(row.company_name, row.city) for row in rows] == [
        ('深圳示例科技有限公司', '深圳市'),
        ('广州另一家公司', '广州市'),
    ]
    assert rows[0].row_number == 2


def test_import_rejects_missing_required_columns_and_reports_row_number() -> None:
    with pytest.raises(ImportValidationError, match='第2行.*城市'):
        CompanyInputImporter.from_csv('company_name,city\n示例公司,\n')

    with pytest.raises(ImportValidationError, match='公司名称.*城市'):
        CompanyInputImporter.from_csv('company_name\n示例公司\n')


def test_xlsx_import_reads_company_and_city_columns() -> None:
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(['company_name', 'city'])
    sheet.append(['深圳示例科技有限公司', '深圳市'])
    buffer = BytesIO()
    workbook.save(buffer)

    rows = CompanyInputImporter.from_xlsx(buffer.getvalue())

    assert len(rows) == 1
    assert rows[0].company_name == '深圳示例科技有限公司'
    assert rows[0].city == '深圳市'
