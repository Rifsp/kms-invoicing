"""Reusable Excel export for the deployed Django application."""
from io import BytesIO
import re
from decimal import Decimal
from datetime import date,datetime
from openpyxl import Workbook
from openpyxl.styles import Font,PatternFill,Alignment
from openpyxl.utils import get_column_letter
from django.http import HttpResponse


def workbook_response(sheets,filename):
    workbook=Workbook();workbook.remove(workbook.active)
    for title,headers,rows in sheets:
        sheet=workbook.create_sheet(title)
        sheet.append(headers)
        for row in rows:
            values=[]
            for value in row:
                if isinstance(value,tuple):value=value[0]
                if isinstance(value,str):
                    value=re.sub(r'[\x00-\x08\x0B-\x0C\x0E-\x1F]','',value)[:32767]
                    if value.startswith(('=','+','-','@')):value="'"+value
                if isinstance(value,Decimal):value=float(value)
                values.append(value)
            sheet.append(values)
            for index,value in enumerate(row,1):
                cell=sheet.cell(sheet.max_row,index)
                if isinstance(value,tuple):
                    cell.hyperlink=value[1];cell.font=Font(color='17664F',underline='single')
                elif isinstance(value,Decimal):cell.number_format='#,##0.00;[Red](#,##0.00)'
                elif isinstance(value,(date,datetime)):cell.number_format='dd mmm yyyy'
        for cell in sheet[1]:
            cell.font=Font(bold=True,color='FFFFFF');cell.fill=PatternFill('solid',fgColor='17664F')
        sheet.freeze_panes='A2';sheet.auto_filter.ref=sheet.dimensions
        sheet.row_dimensions[1].height=28
        for index,header in enumerate(headers,1):
            sheet.column_dimensions[get_column_letter(index)].width=min(45,max(18,len(header)+3))
        for row in sheet.iter_rows(min_row=2):
            for cell in row:cell.alignment=Alignment(vertical='top',wrap_text=True)
    stream=BytesIO();workbook.save(stream)
    response=HttpResponse(stream.getvalue(),content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    response['Content-Disposition']=f'attachment; filename="{filename}.xlsx"'
    response['Cache-Control']='private, no-store'
    return response
