"""Procurement price comparison exports from locked transaction data."""
from io import BytesIO
from decimal import Decimal
from xml.sax.saxutils import escape
from django.core.files.storage import default_storage
from django.http import HttpResponse

HEADERS=['NO','TANGGAL','KETERANGAN','QTY','SATUAN','HPP KMS','MARGIN KMS','HPP KOP','MARGIN KOP','HPP DAPUR','REKOMENDASI DAPUR','PROFIT DAPUR','TOTAL PROFIT']
WIDTHS=[5,12,27,10,9,16,14,16,14,16,19,16,19]


def report_rows(order):
    rows=[]
    for n,item in enumerate(order.items.order_by('pk'),1):
        profit=item.kitchen_price-item.cooperative_price
        rows.append([n,order.delivery_date,item.product_name,item.quantity,item.unit,item.supplier_price,item.kms_price-item.supplier_price,item.kms_price,item.cooperative_price-item.kms_price,item.cooperative_price,item.kitchen_price,profit,(profit*item.quantity).quantize(Decimal('.01'))])
    return rows


def logo_bytes(config,slot):
    name=config.get('logo_'+slot,'')
    if not name or not name.startswith('invoice_logos/') or '..' in name:return None
    with default_storage.open(name,'rb') as file:return file.read()


def export_procurement(order,format):
    config=order.report_snapshot
    rows=report_rows(order)
    data=excel_bytes(order,config,rows) if format=='xlsx' else pdf_bytes(order,config,rows)
    mime='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' if format=='xlsx' else 'application/pdf'
    response=HttpResponse(data,content_type=mime)
    response['Content-Disposition']=f'attachment; filename="{order.code}-{order.delivery_date.isoformat()}.{format}"'
    response['Cache-Control']='private, no-store'
    return response


def excel_bytes(order,config,rows):
    from openpyxl import Workbook
    from openpyxl.styles import Font,Alignment,Border,Side,PatternFill
    from openpyxl.utils import get_column_letter
    from openpyxl.drawing.image import Image
    from openpyxl.worksheet.pagebreak import Break
    from openpyxl.worksheet.page import PageMargins
    book=Workbook();sheet=book.active;sheet.title='Pengadaan';sheet.sheet_view.showGridLines=False
    def text(cell,value):
        cell.value=str(value or '')
        cell.data_type='s'  # Treat all supplied labels as text, including Excel formula prefixes.
    for n,width in enumerate(WIDTHS,1):sheet.column_dimensions[get_column_letter(n)].width=width
    sheet.merge_cells('B1:L1');text(sheet['B1'],config.get('heading') or order.cooperative.name)
    sheet['B1'].font=Font(name='Times New Roman',size=17,bold=True);sheet['B1'].alignment=Alignment(horizontal='center')
    sheet.row_dimensions[1].height=27
    address=(config.get('address') or '').splitlines()
    for n,line in enumerate(address,2):
        sheet.merge_cells(start_row=n,start_column=2,end_row=n,end_column=12);text(sheet.cell(n,2),line);sheet.cell(n,2).alignment=Alignment(horizontal='center');sheet.row_dimensions[n].height=17
    header_end=max(5,2+len(address))
    for slot,anchor in [('left','A1'),('right','M1')]:
        data=logo_bytes(config,slot)
        if data:
            logo=Image(BytesIO(data));ratio=min(82/logo.width,82/logo.height);logo.width*=ratio;logo.height*=ratio;sheet.add_image(logo,anchor)
    title_row=header_end+1
    sheet.merge_cells(start_row=title_row,start_column=1,end_row=title_row,end_column=13)
    text(sheet.cell(title_row,1),config.get('title') or 'PENAWARAN HARGA');sheet.cell(title_row,1).font=Font(bold=True,size=13,underline='single');sheet.cell(title_row,1).alignment=Alignment(horizontal='center')
    sheet.row_dimensions[title_row].height=25
    meta=[f'Nomor: {order.code}',f'Kepada Yth. {order.office_name}',f'{order.kitchen.name} | {order.cooperative.name}',f'Tanggal pengiriman: {order.delivery_date:%d/%m/%Y}']
    for n,value in enumerate(meta,title_row+2):sheet.merge_cells(start_row=n,start_column=1,end_row=n,end_column=13);text(sheet.cell(n,1),value)
    start=title_row+7
    for n,header in enumerate(HEADERS,1):
        cell=sheet.cell(start,n,header);cell.font=Font(bold=True,size=10);cell.fill=PatternFill('solid',fgColor='E8ECE9');cell.alignment=Alignment(horizontal='center',vertical='center',wrap_text=True)
    sheet.row_dimensions[start].height=32
    thin=Side(style='thin',color='444444')
    for row_n,row in enumerate(rows,start+1):
        for col,value in enumerate(row,1):
            cell=sheet.cell(row_n,col)
            if isinstance(value,str):text(cell,value)
            else:cell.value=value
            cell.font=Font(size=10)
            cell.alignment=Alignment(horizontal='left' if col==3 else 'right',vertical='center',wrap_text=col==3)
            if col==2:cell.number_format='dd/mm/yyyy'
            elif col>=6:cell.number_format='"Rp "#,##0.00;[Red]("Rp "#,##0.00)'
            elif col==4:cell.number_format='#,##0.##'
        sheet.row_dimensions[row_n].height=max(20,14*((len(str(row[2]))+29)//30))
    end=start+len(rows)+1
    sheet.merge_cells(start_row=end,start_column=1,end_row=end,end_column=12);sheet.cell(end,1,'TOTAL PROFIT DAPUR').alignment=Alignment(horizontal='right')
    sheet.cell(end,13,sum((row[12] for row in rows),Decimal('0'))).number_format='"Rp "#,##0.00;[Red]("Rp "#,##0.00)'
    for row in sheet.iter_rows(min_row=start,max_row=end,max_col=13):
        for cell in row:cell.border=Border(left=thin,right=thin,top=thin,bottom=thin)
    for cell in sheet[end]:cell.font=Font(bold=True,size=10)
    signer_row=end+3
    for n,signer in enumerate(config.get('signers',[])[:3]):
        first,last=(2,5) if n==0 else ((9,12) if n==1 else (5,9))
        y=signer_row+(7 if n==2 else 0)
        for offset,key in [(0,'title'),(4,'name'),(5,'identity')]:
            sheet.merge_cells(start_row=y+offset,start_column=first,end_row=y+offset,end_column=last)
            cell=sheet.cell(y+offset,first);text(cell,signer.get(key));cell.alignment=Alignment(horizontal='center',wrap_text=True)
            sheet.row_dimensions[y+offset].height=25 if key=='identity' else 20
    footer_row=signer_row+(14 if config.get('signers') else 1)
    footer_text='\n'.join(str(config.get(k) or '') for k in ['bank_info','footer'] if config.get(k))
    if footer_text:
        sheet.merge_cells(start_row=footer_row,start_column=1,end_row=footer_row+2,end_column=13);text(sheet.cell(footer_row,1),footer_text);sheet.cell(footer_row,1).alignment=Alignment(wrap_text=True,vertical='top')
    sheet.freeze_panes=f'F{start+1}';sheet.print_title_rows=f'1:{start}';sheet.print_options.horizontalCentered=True
    sheet.page_setup.orientation='landscape';sheet.page_setup.paperSize=sheet.PAPERSIZE_A4;sheet.page_setup.fitToWidth=1;sheet.page_setup.fitToHeight=0
    sheet.sheet_properties.pageSetUpPr.fitToPage=True
    sheet.page_margins=PageMargins(left=.25,right=.25,top=.35,bottom=.35,header=.1,footer=.1)
    sheet.print_area=f'A1:M{footer_row+2}';sheet.oddFooter.center.text='Halaman &P dari &N'
    output=BytesIO();book.save(output);return output.getvalue()


def pdf_bytes(order,config,rows):
    from reportlab.platypus import SimpleDocTemplate,Table,TableStyle,Paragraph,Spacer,Image,KeepTogether
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4,landscape
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.enums import TA_CENTER,TA_RIGHT
    from reportlab.lib.units import mm
    output=BytesIO();width,height=landscape(A4)
    doc=SimpleDocTemplate(output,pagesize=(width,height),leftMargin=9*mm,rightMargin=9*mm,topMargin=8*mm,bottomMargin=11*mm)
    normal=ParagraphStyle('normal',fontName='Times-Roman',fontSize=8,leading=9)
    centered=ParagraphStyle('centered',parent=normal,alignment=TA_CENTER)
    heading=ParagraphStyle('heading',parent=centered,fontName='Times-Bold',fontSize=14,leading=16)
    def p(text,style=normal):return Paragraph(escape(str(text or '')).replace('\n','<br/>'),style)
    available=width-18*mm
    head=[p(config.get('heading') or order.cooperative.name,heading),p(config.get('address'),centered)]
    logos=[]
    for slot in ['left','right']:
        data=logo_bytes(config,slot)
        if data:
            logo=Image(BytesIO(data));logo._restrictSize(19*mm,19*mm);logos.append(logo)
        else:logos.append('')
    letterhead=Table([[logos[0],head,logos[1]]],colWidths=[23*mm,available-46*mm,23*mm]);letterhead.setStyle(TableStyle([('VALIGN',(0,0),(-1,-1),'MIDDLE'),('LINEBELOW',(0,0),(-1,-1),1,colors.black)]))
    story=[letterhead,Spacer(1,3*mm),p(config.get('title') or 'PENAWARAN HARGA',ParagraphStyle('title',parent=heading,fontSize=11,leading=13)),Spacer(1,3*mm),p(f'Nomor: {order.code}'),p(f'Kepada Yth. {order.office_name}'),p(f'{order.kitchen.name} / {order.cooperative.name}'),p(f'Tanggal pengiriman: {order.delivery_date:%d/%m/%Y}'),Spacer(1,3*mm)]
    def number(value):return f'{value:,.2f}'.replace(',','~').replace('.',',').replace('~','.')
    table_rows=[[p(h,ParagraphStyle('th',parent=centered,fontName='Times-Bold',fontSize=7,leading=8)) for h in HEADERS]]
    for row in rows:
        cells=[]
        for n,value in enumerate(row):
            if n==1:value=value.strftime('%d/%m/%Y')
            elif n>=5:value=number(value)
            elif n==3:value=number(value).removesuffix(',00')
            cells.append(p(value,normal if n==2 else ParagraphStyle('right',parent=normal,alignment=TA_RIGHT)))
        table_rows.append(cells)
    table_rows.append([p('TOTAL PROFIT DAPUR')]+['']*11+[p(number(sum((r[12] for r in rows),Decimal('0'))),ParagraphStyle('total',parent=normal,alignment=TA_RIGHT,fontName='Times-Bold'))])
    fractions=[.025,.065,.165,.045,.04,.075,.065,.075,.065,.075,.08,.065,.06]
    scale=sum(fractions);table=Table(table_rows,colWidths=[available*x/scale for x in fractions],repeatRows=1,hAlign='LEFT')
    table.setStyle(TableStyle([('GRID',(0,0),(-1,-1),.4,colors.black),('BACKGROUND',(0,0),(-1,0),colors.HexColor('#e8ece9')),('VALIGN',(0,0),(-1,-1),'MIDDLE'),('LEFTPADDING',(0,0),(-1,-1),3),('RIGHTPADDING',(0,0),(-1,-1),3),('TOPPADDING',(0,0),(-1,-1),3),('BOTTOMPADDING',(0,0),(-1,-1),3),('SPAN',(0,-1),(11,-1))]))
    story.append(table)
    ending=[Spacer(1,4*mm)]
    signers=config.get('signers',[])[:3]
    if signers:
        blocks=[]
        for signer in signers:blocks.append([p(signer.get('title'),centered),Spacer(1,9*mm),p(signer.get('name'),centered),p(signer.get('identity'),centered)])
        if len(blocks)>1:ending.append(Table([[blocks[0],blocks[1]]],colWidths=[available/2]*2))
        else:ending.extend(blocks[0])
        if len(blocks)>2:ending.extend([Spacer(1,3*mm)]+blocks[2])
    elif config.get('signature'):ending.extend([p('Hormat kami,'),Spacer(1,9*mm),p(config['signature'])])
    for key in ['bank_info','footer']:
        if config.get(key):ending.extend([Spacer(1,3*mm),p(config[key])])
    story.append(KeepTogether(ending))
    def page(canvas,doc):
        canvas.setFont('Times-Roman',8);canvas.drawRightString(width-9*mm,5*mm,f'{order.code} | Halaman {doc.page}')
    doc.build(story,onFirstPage=page,onLaterPages=page)
    return output.getvalue()
