import uuid
from decimal import Decimal
from functools import wraps
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Sum,Q,F,DecimalField,Case,When,Value,IntegerField
from django.db.models.functions import Coalesce
from django.core.files.storage import default_storage
from django.core.exceptions import PermissionDenied
from django.http import FileResponse, HttpResponse, JsonResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.utils import timezone
from django.views.decorators.http import require_POST
from django.core.paginator import Paginator
from .models import Product,Partner,Procurement,OrderItem,Invoice,Attachment,SupplierPrice,InvoiceProfile,AuditEvent,Payment,SALES_KINDS,INVOICE_KINDS,LedgerEntry,FinancialEvidence,DOCUMENT_KINDS,document_label,ACTIVE_INVOICE_KINDS,ACTIVE_DOCUMENT_KINDS
from .forms import ProductForm,PartnerForm,ProcurementForm,ItemForm,PaymentForm,AttachmentForm,SupplierPriceForm,InvoiceProfileForm,ReportFilterForm,CashForm,PaymentReportFilterForm,InvoiceListFilterForm
from .permissions import require_access,is_owner,owner_required
from . import services
from .uploads import prepare_evidence
from .exports import workbook_response
from .filters import period,order_sort,financial_sort,financial_status

def access(view):
    @login_required
    @wraps(view)
    def wrapped(request,*args,**kwargs):
        require_access(request.user)
        return view(request,*args,**kwargs)
    return wrapped

def paginate(request,qs): return Paginator(qs,25).get_page(request.GET.get('page'))
def error_message(request,error): messages.error(request,' '.join(error.messages))

def report_data(user, orders):
    rows=[]
    totals={'coop_sales':Decimal('0'),'coop_margin':Decimal('0')}
    if is_owner(user): totals.update(kms_sales=Decimal('0'),kms_margin=Decimal('0'))
    for order in orders:
        if order.status=='cancelled':continue
        invoices={i.kind:i for i in order.invoices.all() if i.kind in SALES_KINDS}
        kms=invoices.get('kms'); coop=invoices.get('cooperative')
        row={'order':order,'coop_sales':coop.total if coop else None,
             'coop_margin':coop.total-kms.total if coop and kms else None}
        if is_owner(user):
            purchase=sum((i.purchase_total for i in order.items.all()),Decimal('0'))
            row.update(kms_sales=kms.total if kms else None,kms_margin=kms.total-purchase if kms else None)
        for key in totals:
            if row.get(key) is not None: totals[key]+=row[key]
        rows.append(row)
    return rows,totals

@access
def dashboard(request):
    orders=Procurement.objects.select_related('kitchen','cooperative')
    invoices=Invoice.objects.filter(kind__in=ACTIVE_INVOICE_KINDS).exclude(procurement__status='cancelled').prefetch_related('payments')
    today=timezone.localdate()
    confirmed=orders.exclude(status__in=['draft','cancelled']).filter(confirmed_at__year=today.year,confirmed_at__month=today.month).prefetch_related('items','invoices')
    _,totals=report_data(request.user,confirmed)
    context={'active':'dashboard','orders':orders[:6],'active_count':orders.exclude(status__in=['received','cancelled']).count(),'shipped_count':orders.filter(status='shipped').count(),'unpaid_count':sum(1 for i in invoices if i.remaining>0),'totals':totals,'month':today}
    if is_owner(request.user): context['balance']=services.balance()
    return render(request,'core/dashboard.html',context)

def master_list(request,kind):
    from .forms import MasterListFilterForm
    model=Product if kind=='product' else Partner
    form=MasterListFilterForm(request.GET)
    qs=model.objects.all()
    if form.is_valid():
        data=form.cleaned_data;q=data.get('q')
        if q:qs=qs.filter(Q(name__icontains=q)|Q(code__icontains=q)) if kind=='product' else qs.filter(name__icontains=q)
        if data.get('status'):qs=qs.filter(active=data['status']=='active')
        qs=qs.order_by('-active','name','pk') if data.get('sort')=='status' else qs.order_by('name','pk')
    else:qs=qs.none()
    return render(request,'core/master_list.html',{'active':'products' if kind=='product' else 'partners','title':'Master barang' if kind=='product' else 'Supplier, koperasi & dapur','kind':kind,'filter_form':form,'page':paginate(request,qs)})

@access
def products(request):return master_list(request,'product')

@access
def partners(request):return master_list(request,'partner')

@access
def master_edit(request,kind,pk=None):
    if kind not in ['product','partner']: return HttpResponse(status=404)
    model,form_class=(Product,ProductForm) if kind=='product' else (Partner,PartnerForm)
    instance=get_object_or_404(model,pk=pk) if pk else None
    form=form_class(request.POST or None,instance=instance)
    if request.method=='POST' and form.is_valid():
        with transaction.atomic():
            obj=form.save()
            services.audit(request.user,f'{kind}.saved',obj.pk)
        messages.success(request,'Data berhasil disimpan.')
        return redirect('products' if kind=='product' else 'partners')
    return render(request,'core/form.html',{'form':form,'title':('Ubah ' if pk else 'Tambah ')+('barang' if kind=='product' else 'mitra'),'active':'products' if kind=='product' else 'partners'})

@access
def orders(request):
    from .forms import OrderListFilterForm
    form=OrderListFilterForm(request.GET)
    qs=Procurement.objects.select_related('cooperative','kitchen')
    if form.is_valid():
        data=form.cleaned_data;qs=period(qs,form,'delivery_date')
        if data.get('status'):qs=qs.filter(status=data['status'])
        if data.get('q'):
            q=data['q'];qs=qs.filter(Q(kitchen__name__icontains=q)|Q(cooperative__name__icontains=q)|Q(pk=int(q[4:]) if q.upper().startswith('PGD-') and q[4:].isdigit() and len(q)<20 else -1))
        qs=order_sort(qs,data.get('sort'))
    else:qs=qs.none()
    return render(request,'core/order_list.html',{'active':'orders','page':paginate(request,qs),'filter_form':form,'period_hint':'Berdasarkan tanggal pengiriman'})

@access
def order_create(request):
    form=ProcurementForm(request.POST or None,initial={'delivery_date':timezone.localdate()})
    if request.method=='POST' and form.is_valid():
        with transaction.atomic():
            order=form.save(commit=False); order.created_by=request.user; order.save()
            services.audit(request.user,'procurement.created',order.code)
        return redirect('purchase_lines',pk=order.pk)
    return render(request,'core/form.html',{'form':form,'title':'Buat pengadaan','active':'orders'})

@access
def order_detail(request,pk):
    order=get_object_or_404(Procurement.objects.select_related('cooperative','kitchen','created_by'),pk=pk)
    items=list(order.items.select_related('product','supplier'))
    totals={'purchase':sum((i.purchase_total for i in items),Decimal('0')),'kms':sum((i.kms_total for i in items),Decimal('0')),'coop':sum((i.cooperative_total for i in items),Decimal('0')),'kitchen':sum((i.kitchen_total for i in items),Decimal('0'))}
    return render(request,'core/order_detail.html',{'active':'orders','order':order,'items':items,'totals':totals,'invoices':order.invoices.filter(kind__in=SALES_KINDS).prefetch_related('payments'),'legacy_invoices':order.invoices.filter(kind='kitchen').prefetch_related('payments'),'supplier_invoices':order.invoices.filter(kind='supplier').prefetch_related('payments'),'attachments':order.attachments.all(),'attachment_form':AttachmentForm()})

@access
def item_edit(request,order_id,pk=None):
    order=get_object_or_404(Procurement,pk=order_id)
    if order.status!='draft':
        messages.error(request,'Transaksi telah dikunci.');return redirect('order_detail',pk=order_id)
    item=get_object_or_404(OrderItem,pk=pk,procurement=order) if pk else None
    form=ItemForm(request.POST or None,user=request.user,instance=item)
    if request.method=='POST' and form.is_valid():
        try:
            services.save_item(request.user,order_id,form,pk)
            messages.success(request,'Barang dan harga berhasil disimpan.')
            return redirect('order_detail',pk=order_id)
        except ValidationError as e: form.add_error(None,e)
    return render(request,'core/item_form.html',{'form':form,'title':'Ubah barang & harga' if pk else 'Tambah barang & harga','order':order,'active':'orders'})

@access
@require_POST
def item_delete(request,order_id,pk):
    get_object_or_404(OrderItem,pk=pk,procurement_id=order_id)
    try: services.delete_item(request.user,order_id,pk)
    except ValidationError as e: error_message(request,e)
    return redirect('order_detail',pk=order_id)

@access
@require_POST
def order_confirm(request,pk):
    get_object_or_404(Procurement,pk=pk)
    try:
        services.confirm_order(request.user,pk)
        messages.success(request,'Harga dikunci. Tagihan per supplier serta invoice KMS ke koperasi dan koperasi ke dapur telah diterbitkan.')
    except ValidationError as e: error_message(request,e)
    return redirect('order_detail',pk=pk)

@access
@require_POST
def order_advance(request,pk):
    get_object_or_404(Procurement,pk=pk)
    try: services.advance_order(request.user,pk)
    except ValidationError as e: error_message(request,e)
    return redirect('order_detail',pk=pk)

def invoice_list(request,group):
    form=InvoiceListFilterForm(request.GET,group=group)
    qs=Invoice.objects.filter(kind='supplier') if group=='supplier' else (Invoice.objects.filter(kind='kitchen') if group=='archive' else Invoice.objects.filter(kind__in=SALES_KINDS))
    qs=qs.select_related('procurement','supplier').prefetch_related('payments')
    if form.is_valid():
        data=form.cleaned_data
        qs=period(qs,form,'created_at__date')
        if data.get('q'):qs=qs.filter(Q(number__icontains=data['q'])|Q(issuer_name__icontains=data['q'])|Q(recipient_name__icontains=data['q'])|Q(procurement__kitchen__name__icontains=data['q']))
        for name,lookup in [('supplier','supplier'),('kind','kind'),('start','created_at__date__gte'),('end','created_at__date__lte')]:
            if data.get(name):qs=qs.filter(**{lookup:data[name]})
        qs=qs.annotate(paid_total=Coalesce(Sum('payments__amount',filter=Q(payments__cancelled_at__isnull=True)),Decimal('0'),output_field=DecimalField()))
        status=data.get('status')
        if status=='cancelled':qs=qs.filter(procurement__status='cancelled')
        elif status:
            qs=qs.exclude(procurement__status='cancelled')
            if status=='paid':qs=qs.filter(paid_total=F('total'))
            elif status=='partial':qs=qs.filter(paid_total__gt=0,paid_total__lt=F('total'))
            else:qs=qs.filter(paid_total=0,total__gt=0)
        if data.get('sort')=='status':
            qs=qs.annotate(status_rank=Case(When(procurement__status='cancelled',then=Value(3)),When(paid_total=F('total'),then=Value(2)),When(paid_total__gt=0,then=Value(1)),default=Value(0),output_field=IntegerField())).order_by('status_rank','-created_at','-pk')
        else:qs=qs.order_by('created_at' if data.get('sort')=='oldest' else '-created_at','pk' if data.get('sort')=='oldest' else '-pk')
    else:qs=qs.none()
    return render(request,'core/invoices.html',{'active':'supplier_invoices' if group=='supplier' else 'invoices','group':group,'page':paginate(request,qs),'filter_form':form,'count':qs.count(),'period_hint':'Berdasarkan tanggal terbit invoice'})

@access
def invoices(request):
    if request.GET.get('kind')=='supplier':return redirect('supplier_invoices')
    if request.GET.get('kind')=='kitchen':return redirect('office_invoice_archive')
    return invoice_list(request,'sales')

@access
def supplier_invoices(request):return invoice_list(request,'supplier')

@access
def office_invoice_archive(request):return invoice_list(request,'archive')

@access
def invoice_detail(request,pk):
    invoice=get_object_or_404(Invoice.objects.filter(kind__in=INVOICE_KINDS).select_related('procurement').prefetch_related('payments__evidences'),pk=pk)
    items=invoice.procurement.items.select_related('product')
    if invoice.kind=='supplier': items=items.filter(supplier=invoice.supplier)
    lines=[]
    for item in items:
        price={'supplier':item.supplier_price,'kms':item.kms_price,'cooperative':item.cooperative_price,'kitchen':item.kitchen_price}[invoice.kind]
        lines.append({'name':item.product_name,'unit':item.unit,'quantity':item.quantity,'price':price,'total':(price*item.quantity).quantize(Decimal('.01'))})
    return render(request,'core/invoice_detail.html',{'active':'supplier_invoices' if invoice.kind=='supplier' else 'invoices','invoice':invoice,'lines':lines,'print_config':invoice.print_snapshot,'proof_form':AttachmentForm(auto_id=False),'form':PaymentForm(initial={'amount':invoice.remaining})})

@access
@require_POST
def payment_create(request,pk):
    get_object_or_404(Invoice,pk=pk,kind__in=INVOICE_KINDS)
    form=PaymentForm(request.POST,request.FILES)
    if form.is_valid():
        try:
            services.record_payment(request.user,pk,form.cleaned_data['amount'],form.cleaned_data['date'],form.cleaned_data['reference'],form.cleaned_data['request_key'],evidence=form.cleaned_data.get('evidence'))
            messages.success(request,'Pembayaran dicatat. Saldo dan sisa tagihan diperbarui.')
        except ValidationError as e: error_message(request,e)
    else: messages.error(request,'Pembayaran gagal: '+str(form.errors.as_text()))
    return redirect('invoice_detail',pk=pk)

def filtered_orders(form):
    orders=Procurement.objects.exclude(status__in=['draft','cancelled']).select_related('cooperative','kitchen').prefetch_related('items','invoices')
    if not form.is_valid():return orders.none()
    orders=period(orders,form,'confirmed_at__date')
    if form.cleaned_data.get('status'):orders=orders.filter(status=form.cleaned_data['status'])
    for name,lookup in [('start','confirmed_at__date__gte'),('end','confirmed_at__date__lte'),('cooperative','cooperative'),('kitchen','kitchen')]:
        if form.cleaned_data.get(name):orders=orders.filter(**{lookup:form.cleaned_data[name]})
    return order_sort(orders,form.cleaned_data.get('sort'),'confirmed_at')


def payments_queryset(user,include_cancelled=False):
    qs=Payment.objects.all().select_related('invoice__procurement__cooperative','invoice__procurement__kitchen','invoice__supplier').prefetch_related('evidences')
    if not include_cancelled:qs=qs.filter(cancelled_at__isnull=True)
    return qs if is_owner(user) else qs.exclude(invoice__kind='kms')


def payments_excel_sheets(request,payments):
    rows=[];proofs=[]
    from django.urls import reverse
    for payment in payments:
        invoice=payment.invoice
        rows.append([payment.date,invoice.code,invoice.get_kind_display(),invoice.procurement.code,invoice.issuer_name,invoice.recipient_name,payment.amount,payment.reference,'Dibatalkan' if payment.cancelled_at else 'Aktif',('Buka pembayaran',request.build_absolute_uri(reverse('invoice_detail',args=[invoice.pk])))])
        for proof in payment.evidences.all():
            proofs.append([payment.pk,invoice.code,proof.original_name,('Lihat bukti (login)',request.build_absolute_uri(reverse('financial_evidence_download',args=[proof.pk])+'?preview=1'))])
    return [('Pembayaran',['Tanggal bayar','Invoice','Jenis','Pengadaan','Dari','Kepada','Nominal (Rp)','Referensi','Status','Detail'],rows),('Bukti',['ID pembayaran','Invoice','Nama file','Tautan bukti'],proofs)]


@access
def reports(request):
    form=ReportFilterForm(request.GET)
    orders=filtered_orders(form)
    rows,totals=report_data(request.user,orders)
    if request.GET.get('export')=='xlsx' and form.is_valid():
        fields=['coop_sales','coop_margin']
        headers=['Omzet koperasi','Profit koperasi']
        if is_owner(request.user):fields=['kms_sales','kms_margin']+fields;headers=['Omzet KMS','Profit KMS']+headers
        data=[[row['order'].code,row['order'].cooperative.name,row['order'].kitchen.name]+[row.get(key) for key in fields] for row in rows]
        summary=[[header,totals[key]] for header,key in zip(headers,fields)]
        sheets=[('Ringkasan',['Indikator','Nilai (Rp)'],summary),('Omzet dan profit',['Pengadaan','Koperasi','Dapur']+headers,data)]
        payments=payments_queryset(request.user).filter(invoice__procurement__in=orders)
        return workbook_response(sheets+payments_excel_sheets(request,payments),'kms-omzet-profit')
    return render(request,'core/reports.html',{'active':'reports','rows':rows,'totals':totals,'filter_form':form,'period_hint':'Berdasarkan tanggal konfirmasi pengadaan'})


@access
def payment_reports(request):
    form=PaymentReportFilterForm(request.GET,user=request.user)
    payments=payments_queryset(request.user,include_cancelled=True)
    if form.is_valid():
        payments=period(payments,form,'date')
        payments=financial_sort(financial_status(payments,form.cleaned_data.get('status')),form.cleaned_data.get('sort'))
        for name,lookup in [('start','date__gte'),('end','date__lte'),('supplier','invoice__supplier'),('kind','invoice__kind'),('cooperative','invoice__procurement__cooperative'),('kitchen','invoice__procurement__kitchen')]:
            if form.cleaned_data.get(name):payments=payments.filter(**{lookup:form.cleaned_data[name]})
    else:payments=payments.none()
    if request.GET.get('export')=='xlsx' and form.is_valid():return workbook_response(payments_excel_sheets(request,payments),'kms-pembayaran-bukti')
    return render(request,'core/payment_reports.html',{'active':'payment_reports','filter_form':form,'page':paginate(request,payments),'period_hint':'Berdasarkan tanggal pembayaran'})


@access
def supplier_prices(request):
    form=SupplierPriceForm(request.POST or None,initial={'effective_date':timezone.localdate(),'product':request.GET.get('product')})
    if request.method=='POST' and form.is_valid():
        services.record_quote(request.user,form)
        messages.success(request,'Harga supplier ditambahkan. Riwayat lama tetap tersimpan.')
        return redirect('supplier_prices')
    history=SupplierPrice.objects.select_related('product','supplier')
    product=request.GET.get('product','')
    selected=Product.objects.filter(pk=product).first() if product.isdigit() else None
    if selected: history=history.filter(product=selected)
    offers=services.supplier_offers(selected.pk,timezone.localdate()) if selected else []
    return render(request,'core/supplier_prices.html',{'active':'prices','form':form,'page':paginate(request,history),'selected_product':selected,'offers':offers})


@access
def supplier_offers(request):
    product=request.GET.get('product','')
    offers=services.supplier_offers(int(product),timezone.localdate()) if product.isdigit() else []
    return JsonResponse({'offers':[{'id':q.pk,'supplier_id':q.supplier_id,'supplier':q.supplier.name,'price':str(q.price),'unit':q.unit,'date':q.effective_date.isoformat()} for q in offers]})


@access
@owner_required
def invoice_settings(request,kind='kms'):
    if kind not in DOCUMENT_KINDS:return HttpResponse(status=404)
    partner_kind={'supplier':'supplier','cooperative':'cooperative','kitchen':'kitchen'}.get(kind)
    partners=Partner.objects.filter(kind=partner_kind) if partner_kind else Partner.objects.none()
    partner_id=request.GET.get('partner','')
    partner=get_object_or_404(partners,pk=partner_id) if partner_id and partner_id.isdigit() and len(partner_id)<20 else None
    with services.financial_transaction() as written:
        base=services.invoice_profile(kind)
        base=InvoiceProfile.objects.select_for_update().get(pk=base.pk)
        profile=InvoiceProfile.objects.filter(kind=kind,partner=partner).first() if partner else base
        if profile is None:
            defaults={field:getattr(base,field) for field in ['prefix','number_pattern','reset','title','heading','address','bank_info','signature','footer','style','due_days','signers']}
            defaults.update(logo_left=base.logo_left.name,logo_right=base.logo_right.name)
            profile=InvoiceProfile(kind=kind,partner=partner,**defaults)
        elif profile.pk:profile=InvoiceProfile.objects.select_for_update().get(pk=profile.pk)
        form=InvoiceProfileForm(request.POST or None,request.FILES or None,instance=profile)
        if request.method=='POST' and form.is_valid():
            profile=form.save(commit=False);profile.signers=form.signers
            for key in ['logo_left','logo_right']:
                if form.cleaned_data.get('clear_'+key):setattr(profile,key,'')
                file=getattr(profile,key)
                if file and not file._committed:
                    content=file.file;file.save(f'{uuid.uuid4().hex}.png',content,save=False);written.append(file)
            profile.save()
            services.audit(request.user,'invoice_profile.updated',kind,partner_id=partner.pk if partner else None)
            messages.success(request,'Pengaturan disimpan. Invoice yang sudah terbit tetap memakai kop, logo, dan tanda tangan sebelumnya.')
            from django.urls import reverse
            return redirect(reverse('invoice_settings',args=[kind])+(f'?partner={partner.pk}' if partner else ''))
    return render(request,'core/invoice_settings.html',{'active':'invoice_settings','form':form,'profile':profile,'selected_partner':partner,'partners':partners,'kind':kind,'kinds':[(k,document_label(k)) for k in ACTIVE_DOCUMENT_KINDS]})


@access
@require_POST
def attachment_upload(request,pk):
    order=get_object_or_404(Procurement,pk=pk)
    form=AttachmentForm(request.POST,request.FILES)
    if form.is_valid():
        try:
            f=form.cleaned_data['file'];original=f.name[:200]
            with services.financial_transaction() as written:
                optimized,thumb,suffix=prepare_evidence(f)
                attachment=Attachment(procurement=order,original_name=original,uploaded_by=request.user)
                attachment.file.save(f'{uuid.uuid4().hex}{suffix}',optimized,save=False);written.append(attachment.file)
                if thumb:
                    attachment.thumbnail.save(f'{uuid.uuid4().hex}.jpg',thumb,save=False);written.append(attachment.thumbnail)
                attachment.save()
                services.audit(request.user,'attachment.uploaded',order.code,attachment_id=attachment.pk)
            messages.success(request,'Bukti berhasil diunggah.')
        except ValidationError as error:error_message(request,error)
    else: messages.error(request,form.errors.as_text())
    return redirect('order_detail',pk=pk)

@access
def attachment_download(request,pk):
    attachment=get_object_or_404(Attachment,pk=pk)
    return private_file_response(request,attachment.file,attachment.original_name,attachment.thumbnail)

@access
@owner_required
def audit_log(request):
    from .forms import AuditFilterForm
    form=AuditFilterForm(request.GET)
    qs=AuditEvent.objects.select_related('actor')
    if form.is_valid():
        qs=period(qs,form,'created_at__date')
        if form.cleaned_data.get('q'):
            q=form.cleaned_data['q'];qs=qs.filter(Q(actor__username__icontains=q)|Q(action__icontains=q)|Q(target__icontains=q))
        qs=qs.order_by('created_at','pk') if form.cleaned_data.get('sort')=='oldest' else qs.order_by('-created_at','-pk')
    else:qs=qs.none()
    return render(request,'core/audit.html',{'active':'audit','filter_form':form,'period_hint':'Berdasarkan waktu aktivitas','page':paginate(request,qs)})


@access
def finance(request):
    form=CashForm(request.POST or None,request.FILES or None)
    if request.method=='POST' and form.is_valid():
        try:
            services.cash_movement(request.user,form.cleaned_data['amount'],form.cleaned_data['direction'],form.cleaned_data['date'],form.cleaned_data['description'],form.cleaned_data['request_key'],evidence=form.cleaned_data.get('evidence'))
            messages.success(request,'Mutasi dana KMS dan bukti berhasil dicatat.')
            return redirect(request.get_full_path())
        except ValidationError as error:form.add_error(None,error)
    wallet=services.kms_wallet()
    entries=LedgerEntry.objects.filter(wallet=wallet).select_related('payment__invoice','created_by').prefetch_related('evidences','payment__evidences').order_by('-date','-pk')
    from .forms import FinanceFilterForm
    date_filter=FinanceFilterForm(request.GET)
    if date_filter.is_valid():
        entries=period(entries,date_filter,'date')
        entries=financial_sort(financial_status(entries,date_filter.cleaned_data.get('status')),date_filter.cleaned_data.get('sort'))
        if date_filter.cleaned_data.get('direction'):entries=entries.filter(**{'amount__gt' if date_filter.cleaned_data['direction']=='income' else 'amount__lt':0})
        if date_filter.cleaned_data.get('start'):entries=entries.filter(date__gte=date_filter.cleaned_data['start'])
        if date_filter.cleaned_data.get('end'):entries=entries.filter(date__lte=date_filter.cleaned_data['end'])
    else:entries=entries.none()
    active_entries=entries.filter(cancelled_at__isnull=True)
    income=active_entries.filter(amount__gt=0).aggregate(total=Sum('amount'))['total'] or Decimal('0')
    expense=-(active_entries.filter(amount__lt=0).aggregate(total=Sum('amount'))['total'] or Decimal('0'))
    if request.GET.get('export')=='xlsx' and date_filter.is_valid():
        from django.urls import reverse
        rows=[];proof_rows=[]
        for entry in entries:
            invoice=entry.payment.invoice if entry.payment_id else None
            rows.append([entry.date,'Uang masuk' if entry.amount>0 else 'Uang keluar',invoice.code if invoice else 'Manual',entry.description,entry.amount,entry.created_by.username,'Dibatalkan' if entry.cancelled_at else 'Aktif'])
            proofs=list(entry.evidences.all())+(list(entry.payment.evidences.all()) if entry.payment_id else [])
            for proof in proofs:
                proof_rows.append([entry.pk,invoice.code if invoice else 'Manual',proof.original_name,('Lihat bukti (login)',request.build_absolute_uri(reverse('financial_evidence_download',args=[proof.pk])+'?preview=1'))])
        return workbook_response([('Ringkasan kas',['Indikator','Nilai (Rp)'],[['Saldo KMS',services.balance(wallet)],['Total masuk',income],['Total keluar',expense]]),('Mutasi',['Tanggal','Jenis','Invoice','Keterangan','Nominal bertanda (Rp)','Pencatat','Status'],rows),('Bukti',['ID mutasi','Invoice','Nama file','Tautan bukti'],proof_rows)],'kms-mutasi-kas')
    return render(request,'core/finance.html',{'active':'finance','filter_form':date_filter,'period_hint':'Berdasarkan tanggal mutasi','form':form,'balance':services.balance(wallet),'income':income,'expense':expense,'page':paginate(request,entries),'proof_form':AttachmentForm(auto_id=False)})


@access
@require_POST
def payment_evidence_upload(request,pk):
    payment=get_object_or_404(Payment,pk=pk,invoice__kind__in=INVOICE_KINDS)
    form=AttachmentForm(request.POST,request.FILES)
    if form.is_valid():
        try:
            services.attach_payment_evidence(request.user,payment.pk,form.cleaned_data['file'])
            messages.success(request,'Bukti ditautkan ke pembayaran.')
        except ValidationError as error:error_message(request,error)
    else:messages.error(request,form.errors.as_text())
    return redirect('invoice_detail',pk=payment.invoice_id)


@access
@require_POST
def cash_evidence_upload(request,pk):
    entry=get_object_or_404(LedgerEntry,pk=pk,wallet__name='KMS')
    form=AttachmentForm(request.POST,request.FILES)
    if form.is_valid():
        try:
            if entry.payment_id:
                services.attach_payment_evidence(request.user,entry.payment_id,form.cleaned_data['file'])
            else:
                services.attach_cash_evidence(request.user,pk,form.cleaned_data['file'])
            messages.success(request,'Bukti ditautkan ke mutasi dana KMS.')
        except ValidationError as error:error_message(request,error)
    else:messages.error(request,form.errors.as_text())
    return redirect('finance')


@access
def financial_evidence_download(request,pk):
    proof=get_object_or_404(FinancialEvidence.objects.select_related('payment__invoice'),pk=pk)
    return private_file_response(request,proof.file,services.evidence_filename(proof),proof.thumbnail)


@access
def lookup(request):
    kind=request.GET.get('kind','');q=request.GET.get('q','').strip()[:100]
    if kind=='product':
        qs=Product.objects.filter(active=True).filter(Q(name__icontains=q)|Q(code__icontains=q))
        rows=[{'id':p.pk,'label':f'{p.code} · {p.name} · {p.unit}'} for p in qs[:20]]
    elif kind in ['supplier','cooperative','kitchen']:
        qs=Partner.objects.filter(active=True,kind=kind,name__icontains=q)
        rows=[{'id':p.pk,'label':p.name} for p in qs[:20]]
    else:return JsonResponse({'results':[]},status=400)
    return JsonResponse({'results':rows})


def private_file_response(request,file,filename,thumbnail=None):
    inline=request.GET.get('preview')=='1'
    chosen=thumbnail if inline and request.GET.get('thumb')=='1' and thumbnail else file
    handle=chosen.open('rb');head=handle.read(8);handle.seek(0)
    mime='application/pdf' if head.startswith(b'%PDF-') else ('image/png' if head.startswith(b'\x89PNG') else ('image/jpeg' if head.startswith(b'\xff\xd8') else 'application/octet-stream'))
    if mime=='image/jpeg' and chosen.name.endswith('.jpg'):
        from pathlib import PurePath
        filename=PurePath(filename).stem+'.jpg'
    response=FileResponse(handle,as_attachment=not inline,filename=filename,content_type=mime)
    response['Cache-Control']='private, no-store'
    response['X-Frame-Options']='SAMEORIGIN'
    if mime=='application/pdf':response['Content-Security-Policy']="frame-ancestors 'self'; base-uri 'none'"
    return response


@access
def invoice_logo(request,pk,slot):
    invoice=get_object_or_404(Invoice,pk=pk)
    if slot not in ['left','right']:return HttpResponse(status=404)
    name=invoice.print_snapshot.get('logo_'+slot,'')
    if not name or not name.startswith('invoice_logos/') or '..' in name:return HttpResponse(status=404)
    return FileResponse(default_storage.open(name,'rb'),content_type='image/png',headers={'Cache-Control':'private, no-store'})


@access
@owner_required
def profile_logo(request,pk,slot):
    profile=get_object_or_404(InvoiceProfile,pk=pk)
    if slot not in ['left','right']:return HttpResponse(status=404)
    file=getattr(profile,'logo_'+slot)
    if not file:return HttpResponse(status=404)
    return FileResponse(file.open('rb'),content_type='image/png',headers={'Cache-Control':'private, no-store'})

@access
def purchase_lines(request,pk):
    from .forms import PurchaseFormSet,RevisionForm
    order=get_object_or_404(Procurement,pk=pk)
    if order.status!='draft':return redirect('order_detail',pk=pk)
    items=list(order.items.select_related('product','supplier','supplier_quote').order_by('pk'))
    initial=[{'id':i.pk,'product':i.product_id,'supplier':i.supplier_id,'quantity':i.quantity,'supplier_price':i.supplier_price,'supplier_quote':i.supplier_quote_id} for i in items]
    formset=PurchaseFormSet(request.POST or None,initial=initial,prefix='items')
    revision=RevisionForm(request.POST or None,initial={'revision':order.revision})
    if request.method=='POST' and formset.is_valid() and revision.is_valid():
        try:
            services.save_purchase_lines(request.user,pk,formset,revision.cleaned_data['revision'])
            messages.success(request,'Seluruh barang dan harga beli disimpan sebagai draf.')
            return redirect('purchase_lines' if request.POST.get('action')=='stay' else 'sales_lines',pk=pk)
        except ValidationError as error:error_message(request,error)
    return render(request,'core/purchase_lines.html',{'active':'orders','order':order,'formset':formset,'revision_form':revision})


@access
def sales_lines(request,pk):
    from .forms import SalesFormSet,RevisionForm
    order=get_object_or_404(Procurement,pk=pk)
    if order.status!='draft':return redirect('order_detail',pk=pk)
    items=list(order.items.select_related('product','supplier').order_by('pk'))
    if not items:
        messages.info(request,'Isi barang dan harga beli supplier terlebih dahulu.')
        return redirect('purchase_lines',pk=pk)
    partial=request.method=='POST' and request.POST.get('action')=='back'
    initial=[{'id':i.pk,'kms_price':i.kms_price,'cooperative_price':i.cooperative_price} for i in items]
    formset=SalesFormSet(request.POST or None,initial=initial,prefix='prices',form_kwargs={'user':request.user,'partial':partial})
    revision=RevisionForm(request.POST or None,initial={'revision':order.revision})
    if request.method=='POST' and formset.is_valid() and revision.is_valid():
        try:
            services.save_sales_lines(request.user,pk,formset,revision.cleaned_data['revision'])
            messages.success(request,'Harga jual disimpan sebagai draf. Invoice belum diterbitkan.')
            return redirect('purchase_lines' if partial else 'order_detail',pk=pk)
        except ValidationError as error:error_message(request,error)
    by_id={i.pk:i for i in items}
    for form in formset:
        value=str(form['id'].value() or '')
        form.item=by_id.get(int(value)) if value.isdigit() and len(value)<20 else None
    return render(request,'core/sales_lines.html',{'active':'orders','order':order,'formset':formset,'revision_form':revision})


@access
def catalog(request):
    from .forms import CatalogFilterForm
    from .models import SupplierProduct
    from django.db.models import OuterRef,Subquery
    form=CatalogFilterForm(request.GET)
    links=SupplierProduct.objects.filter(active=True,product__active=True,supplier__active=True).select_related('product','supplier')
    if form.is_valid():
        data=form.cleaned_data
        if data.get('product'):links=links.filter(product=data['product'])
        if data.get('supplier'):links=links.filter(supplier=data['supplier'])
        if data.get('q'):links=links.filter(Q(product__name__icontains=data['q'])|Q(product__code__icontains=data['q'])|Q(supplier__name__icontains=data['q']))
    else:links=links.none()
    latest=SupplierPrice.objects.filter(product_id=OuterRef('product_id'),supplier_id=OuterRef('supplier_id'),unit=OuterRef('product__unit'),effective_date__lte=timezone.localdate()).order_by('-effective_date','-pk')
    links=links.annotate(latest_price=Subquery(latest.values('price')[:1]),price_date=Subquery(latest.values('effective_date')[:1]))
    return render(request,'core/catalog.html',{'active':'catalog','filter_form':form,'page':paginate(request,links),'mode':'supplier' if request.GET.get('mode')=='supplier' else 'product'})


@access
def catalog_history(request,pk):
    from .models import SupplierProduct
    link=get_object_or_404(SupplierProduct.objects.select_related('product','supplier'),pk=pk)
    prices=SupplierPrice.objects.filter(product=link.product,supplier=link.supplier).select_related('created_by')
    return render(request,'core/catalog_history.html',{'active':'catalog','link':link,'page':paginate(request,prices),'today':timezone.localdate()})


@access
def catalog_create(request):
    from .forms import SupplierProductForm
    form=SupplierProductForm(request.POST or None)
    if request.method=='POST' and form.is_valid():
        with transaction.atomic():
            link=form.save();services.audit(request.user,'supplier_product.created',link.pk)
        messages.success(request,'Barang supplier didaftarkan. Harga dapat ditambahkan lewat Historis harga.')
        return redirect('catalog_history',pk=link.pk)
    return render(request,'core/form.html',{'active':'catalog','title':'Daftarkan barang yang disediakan supplier','form':form})


@access
@owner_required
def cancel_transaction(request,kind,pk):
    from .forms import CancellationForm
    models={'payment':Payment,'cash':LedgerEntry,'order':Procurement}
    if kind not in models:return HttpResponse(status=404)
    obj=get_object_or_404(models[kind],pk=pk)
    form=CancellationForm(request.POST or None)
    if request.method=='POST' and form.is_valid():
        try:
            function={'payment':services.cancel_payment,'cash':services.cancel_cash,'order':services.cancel_order}[kind]
            function(request.user,pk,form.cleaned_data['reason'])
            messages.success(request,'Transaksi dibatalkan. Data, bukti dan jejak audit tetap tersimpan.')
            if kind=='payment':return redirect('invoice_detail',pk=obj.invoice_id)
            if kind=='cash':return redirect('finance')
            return redirect('order_detail',pk=pk)
        except ValidationError as error:form.add_error(None,error)
    return render(request,'core/cancel_transaction.html',{'form':form,'kind':kind,'obj':obj,'active':'finance' if kind=='cash' else 'orders'})


@access
@owner_required
def order_edit(request,pk):
    order=get_object_or_404(Procurement,pk=pk)
    if order.status!='draft':
        messages.error(request,'Dokumen terbit dikunci. Untuk koreksi, batalkan lalu buat pengadaan pengganti.')
        return redirect('order_detail',pk=pk)
    form=ProcurementForm(request.POST or None,instance=order)
    if request.method=='POST' and form.is_valid():
        with transaction.atomic():
            locked=Procurement.objects.select_for_update().get(pk=pk)
            if locked.status!='draft':raise PermissionDenied('Pengadaan sudah dikunci.')
            changed=form.save(commit=False);changed.revision=locked.revision+1;changed.save()
            services.audit(request.user,'procurement.updated',order.code)
        return redirect('order_detail',pk=pk)
    return render(request,'core/form.html',{'form':form,'title':'Ubah tujuan pengadaan '+order.code,'active':'orders'})


@access
def evidence_archive(request):
    from .forms import EvidenceArchiveForm
    from .audit_exports import evidence_zip
    form=EvidenceArchiveForm(request.GET or None)
    if request.GET and form.is_valid():
        try:return evidence_zip(form.cleaned_data['start'],form.cleaned_data['end'])
        except FileNotFoundError:form.add_error(None,'Ada bukti yang berkasnya tidak tersedia. Pulihkan berkas lampiran dari backup sebelum mengunduh arsip lengkap.')
    return render(request,'core/evidence_archive.html',{'form':form,'active':'finance'})


@access
def procurement_export(request,pk,format):
    order=get_object_or_404(Procurement.objects.select_related('cooperative','kitchen'),pk=pk)
    if order.status!='received':
        messages.error(request,'Ekspor pengadaan tersedia setelah status Diterima dapur (selesai).')
        return redirect('order_detail',pk=pk)
    if format not in ['xlsx','pdf']:return HttpResponse(status=404)
    from .procurement_exports import export_procurement
    return export_procurement(order,format)
