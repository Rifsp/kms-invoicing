import uuid
from decimal import Decimal
from django import forms
from django.core.exceptions import ValidationError
from django.utils import timezone
from .models import Product, Partner, Procurement, OrderItem, SupplierPrice, InvoiceProfile
from .permissions import is_owner
from .uploads import validate_evidence,prepare_logo
from .widgets import SearchSelect

class ProductForm(forms.ModelForm):
    class Meta:
        model=Product
        fields=['code','name','category','unit','active']
class PartnerForm(forms.ModelForm):
    class Meta:
        model=Partner
        fields=['name','kind','phone','address','active']
        widgets={'address':forms.Textarea(attrs={'rows':3})}
class ProcurementForm(forms.ModelForm):
    class Meta:
        model=Procurement
        fields=['cooperative','kitchen','delivery_date','notes']
        labels={'cooperative':'Koperasi','kitchen':'Dapur tujuan'}
        widgets={'delivery_date':forms.DateInput(attrs={'type':'date'}),'notes':forms.Textarea(attrs={'rows':3})}
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        for field,kind in [('cooperative','cooperative'),('kitchen','kitchen')]:
            self.fields[field].queryset=Partner.objects.filter(kind=kind,active=True)
            self.fields[field].widget=SearchSelect(kind)
            self.fields[field].widget.choices=self.fields[field].choices
class ItemForm(forms.ModelForm):
    class Meta:
        model=OrderItem
        fields=['product','supplier','quantity','supplier_price','kms_price','cooperative_price','supplier_quote']
        labels={'product':'Barang','supplier':'Supplier'}
        widgets={'supplier_quote':forms.HiddenInput()}
    def __init__(self,*args,user,**kwargs):
        super().__init__(*args,**kwargs)
        self.fields['product'].queryset=Product.objects.filter(active=True)
        self.fields['product'].widget=SearchSelect('product')
        self.fields['product'].widget.choices=self.fields['product'].choices
        self.fields['supplier'].queryset=Partner.objects.filter(kind='supplier',active=True)
        self.fields['supplier'].widget=SearchSelect('supplier')
        self.fields['supplier'].widget.choices=self.fields['supplier'].choices
        self.fields['supplier_quote'].queryset=SupplierPrice.objects.all()
        for key in ['supplier_price','kms_price','cooperative_price','quantity']:
            self.fields[key].widget.attrs.update({'min':'0.01' if key=='quantity' else '0','step':'0.01','data-calc':key})
    def clean(self):
        data = super().clean()
        quote = data.get('supplier_quote')
        if quote:
            if quote.product_id != getattr(data.get('product'),'pk',None) or quote.supplier_id != getattr(data.get('supplier'),'pk',None):
                self.add_error('supplier_quote','Bukti harga tidak sesuai dengan barang / supplier.')
            if data.get('supplier_price') != quote.price or quote.unit != getattr(data.get('product'),'unit',None):
                self.add_error('supplier_price','Harga / satuan harus sama dengan penawaran yang dipilih. Simpan penawaran baru bila ada perubahan.')
            if quote.effective_date > timezone.localdate():
                self.add_error('supplier_quote','Harga belum berlaku.')
        return data

class PaymentForm(forms.Form):
    evidence=forms.FileField(label='Bukti pembayaran: foto otomatis dikompres / PDF maks. 1 MB',required=False)
    def clean_evidence(self): return validate_evidence(self.cleaned_data.get('evidence'))
    amount=forms.DecimalField(label='Nominal pembayaran (Rp)',min_value=Decimal('0.01'),max_digits=18,decimal_places=2)
    date=forms.DateField(label='Tanggal pembayaran',initial=timezone.localdate,widget=forms.DateInput(attrs={'type':'date'}))
    reference=forms.CharField(label='Referensi bukti / transfer',max_length=120)
    request_key=forms.UUIDField(widget=forms.HiddenInput,initial=uuid.uuid4)
class AttachmentForm(forms.Form):
    file=forms.FileField(label='Bukti: foto otomatis dikompres / PDF maks. 1 MB')
    def clean_file(self): return validate_evidence(self.cleaned_data['file'])


class CashForm(forms.Form):
    direction=forms.ChoiceField(label='Jenis mutasi',choices=[('income','Uang masuk'),('expense','Uang keluar')])
    amount=forms.DecimalField(label='Nominal (Rp)',min_value=Decimal('0.01'),max_digits=18,decimal_places=2)
    date=forms.DateField(label='Tanggal mutasi',initial=timezone.localdate,widget=forms.DateInput(attrs={'type':'date'}))
    description=forms.CharField(label='Keterangan',max_length=200)
    evidence=forms.FileField(label='Bukti: foto otomatis dikompres / PDF maks. 1 MB',required=False)
    request_key=forms.UUIDField(widget=forms.HiddenInput,initial=uuid.uuid4)
    def clean_evidence(self): return validate_evidence(self.cleaned_data.get('evidence'))


class SupplierPriceForm(forms.ModelForm):
    class Meta:
        model=SupplierPrice
        fields=['product','supplier','price','effective_date','note']
        labels={'product':'Barang','supplier':'Supplier'}
        widgets={'effective_date':forms.DateInput(attrs={'type':'date'})}
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        self.fields['product'].queryset=Product.objects.filter(active=True)
        self.fields['product'].widget=SearchSelect('product')
        self.fields['product'].widget.choices=self.fields['product'].choices
        self.fields['supplier'].queryset=Partner.objects.filter(kind='supplier',active=True)
        self.fields['supplier'].widget=SearchSelect('supplier')
        self.fields['supplier'].widget.choices=self.fields['supplier'].choices

class InvoiceProfileForm(forms.ModelForm):
    clear_logo_left=forms.BooleanField(label='Hapus logo kiri untuk invoice berikutnya',required=False)
    clear_logo_right=forms.BooleanField(label='Hapus logo kanan untuk invoice berikutnya',required=False)
    signer_1_title=forms.CharField(label='Jabatan kiri atas',max_length=140,required=False,widget=forms.TextInput(attrs={'placeholder':'Sekretaris'}))
    signer_1_name=forms.CharField(label='Nama kiri atas',max_length=140,required=False)
    signer_1_identity=forms.CharField(label='Pangkat / NRP / NIP kiri atas',max_length=200,required=False)
    signer_2_title=forms.CharField(label='Jabatan kanan atas',max_length=140,required=False,widget=forms.TextInput(attrs={'placeholder':'Ur. Usaha'}))
    signer_2_name=forms.CharField(label='Nama kanan atas',max_length=140,required=False)
    signer_2_identity=forms.CharField(label='Pangkat / NRP / NIP kanan atas',max_length=200,required=False)
    signer_3_title=forms.CharField(label='Jabatan tengah bawah',max_length=140,required=False,widget=forms.TextInput(attrs={'placeholder':'Ketua koperasi'}))
    signer_3_name=forms.CharField(label='Nama tengah bawah',max_length=140,required=False)
    signer_3_identity=forms.CharField(label='Pangkat / NRP / NIP tengah bawah',max_length=200,required=False)
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        if self.instance.kind=='procurement':
            for name in ['prefix','number_pattern','reset','due_days','style']:self.fields.pop(name)
        for index,signer in enumerate((self.instance.signers or [])[:3],1):
            for key in ['title','name','identity']:self.initial[f'signer_{index}_{key}']=signer.get(key,'')
    def clean_logo_left(self):return self.clean_logo('logo_left')
    def clean_logo_right(self):return self.clean_logo('logo_right')
    def clean_logo(self,key):
        file=self.cleaned_data.get(key)
        return prepare_logo(file) if file and hasattr(file,'content_type') else file
    def clean(self):
        data=super().clean();self.signers=[]
        for index in range(1,4):
            signer={key:data.get(f'signer_{index}_{key}','') for key in ['title','name','identity']}
            if any(signer.values()):
                if not signer['title'] or not signer['name']:self.add_error(f'signer_{index}_name','Isi jabatan dan nama untuk penanda tangan ini.')
                self.signers.append(signer)
            else:self.signers.append(signer)
        if not any(any(s.values()) for s in self.signers):self.signers=[]
        return data

    class Meta:
        model=InvoiceProfile
        fields=['prefix','number_pattern','reset','title','heading','address','logo_left','logo_right','bank_info','signature','footer','style','due_days']
        labels={'heading':'Nama organisasi pada kop','signature':'Penanda tangan tunggal (format lama, opsional)'}
        widgets={**{key:forms.Textarea(attrs={'rows':3}) for key in ['address','bank_info','footer']},'logo_left':forms.FileInput(attrs={'accept':'image/png,image/jpeg'}),'logo_right':forms.FileInput(attrs={'accept':'image/png,image/jpeg'})}

class MonthFilterForm(forms.Form):
    month=forms.DateField(label='Bulan',required=False,input_formats=['%Y-%m'],widget=forms.DateInput(format='%Y-%m',attrs={'type':'month'}))
    all_months=forms.BooleanField(label='Semua bulan',required=False)
    sort=forms.ChoiceField(label='Urutkan',required=False,choices=[('newest','Terbaru'),('oldest','Terlama'),('status','Status')])
    filter_defaults={}
    def __init__(self,data=None,*args,**kwargs):
        if data is not None:
            data=data.copy()
            # An explicit date range remains usable without a hidden month constraint.
            if 'month' not in data and not (data.get('start') or data.get('end')):
                data['month']=timezone.localdate().strftime('%Y-%m')
            for key,value in self.filter_defaults.items():
                if key not in data:data[key]=value
        else:
            initial=kwargs.setdefault('initial',{})
            initial.setdefault('month',timezone.localdate().replace(day=1))
        super().__init__(data,*args,**kwargs)
    @property
    def primary_fields(self):
        return [self[name] for name in ['month','q','status','direction','sort'] if name in self.fields]
    @property
    def advanced_fields(self):
        names=['month','q','status','direction','sort','all_months']
        return [field for field in self if field.name not in names]
    @property
    def advanced_active(self):
        return any(self.data.get(field.name) for field in self.advanced_fields)
    def clean(self):
        data=super().clean()
        if not data.get('all_months') and not data.get('month') and not (data.get('start') or data.get('end')):
            self.add_error('month','Pilih bulan atau centang Semua bulan.')
        return data


class OrderListFilterForm(MonthFilterForm):
    q=forms.CharField(label='Cari pengadaan / dapur',required=False,max_length=100)
    status=forms.ChoiceField(label='Status pengadaan',required=False,choices=[('','Semua status')]+list(Procurement.Status.choices))


class FinanceFilterForm(MonthFilterForm):
    status=forms.ChoiceField(label='Status transaksi',required=False,choices=[('','Semua status'),('active','Aktif'),('cancelled','Dibatalkan')])
    direction=forms.ChoiceField(label='Jenis mutasi',required=False,choices=[('','Masuk & keluar'),('income','Uang masuk'),('expense','Uang keluar')])
    start=forms.DateField(label='Dari tanggal',required=False,widget=forms.DateInput(attrs={'type':'date'}))
    end=forms.DateField(label='Sampai tanggal',required=False,widget=forms.DateInput(attrs={'type':'date'}))
    def clean(self):
        data=super().clean()
        if data.get('start') and data.get('end') and data['start']>data['end']:raise ValidationError('Tanggal awal harus sebelum tanggal akhir.')
        return data


class ReportFilterForm(MonthFilterForm):
    status=forms.ChoiceField(label='Status pengadaan',required=False,choices=[('','Semua status')]+[(k,v) for k,v in Procurement.Status.choices if k not in ['draft','cancelled']])
    start=forms.DateField(label='Dari tanggal terbit',required=False,widget=forms.DateInput(attrs={'type':'date'}))
    end=forms.DateField(label='Sampai tanggal',required=False,widget=forms.DateInput(attrs={'type':'date'}))
    cooperative=forms.ModelChoiceField(label='Koperasi',required=False,queryset=Partner.objects.filter(kind='cooperative'),widget=SearchSelect('cooperative'))
    kitchen=forms.ModelChoiceField(label='Dapur',required=False,queryset=Partner.objects.filter(kind='kitchen'),widget=SearchSelect('kitchen'))
    def clean(self):
        data=super().clean()
        if data.get('start') and data.get('end') and data['start']>data['end']:
            raise ValidationError('Tanggal awal harus sebelum tanggal akhir.')
        return data


class PaymentReportFilterForm(ReportFilterForm):
    filter_defaults={'status':'active'}
    status=forms.ChoiceField(label='Status transaksi',required=False,choices=[('active','Aktif'),('cancelled','Dibatalkan'),('','Semua status')])
    supplier=forms.ModelChoiceField(label='Supplier',required=False,queryset=Partner.objects.filter(kind='supplier'),widget=SearchSelect('supplier'))
    kind=forms.ChoiceField(label='Jenis invoice',required=False)
    def __init__(self,*args,user,**kwargs):
        from .models import INVOICE_KINDS,Invoice
        super().__init__(*args,**kwargs)
        self.fields['start'].label='Pembayaran dari tanggal';self.fields['end'].label='Sampai tanggal'
        kinds=INVOICE_KINDS if is_owner(user) else [k for k in INVOICE_KINDS if k!='kms']
        self.fields['kind'].choices=[('','Semua jenis')]+[(k,('Arsip lama · '+Invoice.Kind(k).label) if k=='kitchen' else Invoice.Kind(k).label) for k in kinds]

class InvoiceListFilterForm(MonthFilterForm):
    q=forms.CharField(label='Cari invoice / nama mitra',required=False,max_length=100)
    status=forms.ChoiceField(label='Status pembayaran',required=False,choices=[('','Semua status'),('unpaid','Belum dibayar'),('partial','Dibayar sebagian'),('paid','Lunas'),('cancelled','Dibatalkan')])
    supplier=forms.ModelChoiceField(label='Supplier',required=False,queryset=Partner.objects.filter(kind='supplier'),widget=SearchSelect('supplier'))
    kind=forms.ChoiceField(label='Jenis invoice',required=False)
    start=forms.DateField(label='Terbit dari tanggal',required=False,widget=forms.DateInput(attrs={'type':'date'}))
    end=forms.DateField(label='Sampai tanggal',required=False,widget=forms.DateInput(attrs={'type':'date'}))
    def __init__(self,*args,group='sales',**kwargs):
        from .models import Invoice,SALES_KINDS
        super().__init__(*args,**kwargs)
        if group in ['supplier','archive']:self.fields.pop('kind')
        else:
            self.fields.pop('supplier')
            self.fields['kind'].choices=[('','Semua invoice penjualan')]+[(k,Invoice.Kind(k).label) for k in SALES_KINDS]
    def clean(self):
        data=super().clean()
        if data.get('start') and data.get('end') and data['start']>data['end']:raise ValidationError('Tanggal awal harus sebelum tanggal akhir.')
        return data

class RevisionForm(forms.Form):
    revision=forms.IntegerField(min_value=0,widget=forms.HiddenInput)


class PurchaseLineForm(forms.Form):
    id=forms.IntegerField(required=False,min_value=1,widget=forms.HiddenInput)
    product=forms.ModelChoiceField(label='Barang',queryset=Product.objects.filter(active=True),widget=SearchSelect('product'))
    quantity=forms.DecimalField(label='Jumlah',max_digits=12,decimal_places=2,min_value=Decimal('0.01'))
    supplier=forms.ModelChoiceField(label='Supplier',queryset=Partner.objects.filter(kind='supplier',active=True),widget=SearchSelect('supplier'))
    supplier_price=forms.DecimalField(label='Harga beli / satuan',max_digits=15,decimal_places=2,min_value=Decimal('0.01'))
    supplier_quote=forms.ModelChoiceField(queryset=SupplierPrice.objects.all(),required=False,widget=forms.HiddenInput)
    def clean(self):
        data=super().clean();quote=data.get('supplier_quote')
        if quote:
            if quote.product_id!=getattr(data.get('product'),'pk',None) or quote.supplier_id!=getattr(data.get('supplier'),'pk',None):
                self.add_error('supplier_quote','Penawaran tidak sesuai barang / supplier.')
            if quote.price!=data.get('supplier_price') or quote.unit!=getattr(data.get('product'),'unit',None) or quote.effective_date>timezone.localdate():
                self.add_error('supplier_price','Harga, satuan, atau tanggal penawaran tidak sesuai. Pilih penawaran yang berlaku atau isi harga manual.')
        return data


class SalesLineForm(forms.Form):
    id=forms.IntegerField(min_value=1,widget=forms.HiddenInput)
    kms_price=forms.DecimalField(label='KMS → Koperasi',max_digits=15,decimal_places=2,min_value=0)
    cooperative_price=forms.DecimalField(label='Koperasi → Dapur',max_digits=15,decimal_places=2,min_value=0)
    def __init__(self,*args,user,partial=False,**kwargs):
        super().__init__(*args,**kwargs);self.partial=partial
        for name in ['kms_price','cooperative_price']:
            self.fields[name].required=not partial
            self.fields[name].widget.attrs.update({'min':0,'step':'0.01'})
        self.owner=True
    def clean(self):
        data=super().clean()
        for name in ['kms_price','cooperative_price']:
            if data.get(name) is None and name not in self.errors:data[name]=0
        if not self.partial:
            for name in ['cooperative_price','kms_price']:
                if name not in self.errors and data.get(name,0)<=0:self.add_error(name,'Harga harus lebih dari nol.')
        return data


class UniqueLineFormSet(forms.BaseFormSet):
    def clean(self):
        super().clean()
        if any(self.errors):return
        ids=[f.cleaned_data['id'] for f in self.forms if f.cleaned_data.get('id')]
        if len(ids)!=len(set(ids)):raise ValidationError('Ada ID baris berulang. Muat ulang pengadaan sebelum menyimpan.')


PurchaseFormSet=forms.formset_factory(PurchaseLineForm,formset=UniqueLineFormSet,extra=2,can_delete=True,min_num=1,validate_min=True,max_num=200,validate_max=True,absolute_max=220)
SalesFormSet=forms.formset_factory(SalesLineForm,formset=UniqueLineFormSet,extra=0,min_num=1,validate_min=True,max_num=200,validate_max=True,absolute_max=200)


class CatalogFilterForm(forms.Form):
    product=forms.ModelChoiceField(label='Cari barang',queryset=Product.objects.filter(active=True),widget=SearchSelect('product'),required=False)
    supplier=forms.ModelChoiceField(label='Cari supplier',queryset=Partner.objects.filter(kind='supplier',active=True),widget=SearchSelect('supplier'),required=False)
    q=forms.CharField(label='Kata kunci nama / kode',max_length=100,required=False)


class SupplierProductForm(forms.ModelForm):
    class Meta:
        from .models import SupplierProduct
        model=SupplierProduct
        fields=['product','supplier','note','active']
        labels={'product':'Barang','supplier':'Supplier'}
        widgets={'product':SearchSelect('product'),'supplier':SearchSelect('supplier')}
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        self.fields['product'].queryset=Product.objects.filter(active=True)
        self.fields['supplier'].queryset=Partner.objects.filter(kind='supplier',active=True)


class DateRangeForm(forms.Form):
    start=forms.DateField(label='Dari tanggal transaksi',required=False,widget=forms.DateInput(attrs={'type':'date'}))
    end=forms.DateField(label='Sampai tanggal transaksi',required=False,widget=forms.DateInput(attrs={'type':'date'}))
    def clean(self):
        data=super().clean()
        if data.get('start') and data.get('end') and data['start']>data['end']:
            raise ValidationError('Tanggal awal harus sebelum tanggal akhir.')
        return data

class EvidenceArchiveForm(DateRangeForm):
    start=forms.DateField(label='Dari tanggal transaksi',widget=forms.DateInput(attrs={'type':'date'}))
    end=forms.DateField(label='Sampai tanggal transaksi',widget=forms.DateInput(attrs={'type':'date'}))

class CancellationForm(forms.Form):
    reason=forms.CharField(label='Alasan pembatalan',max_length=300,min_length=5,widget=forms.Textarea(attrs={'rows':3}))

class MasterListFilterForm(forms.Form):
    q=forms.CharField(label='Cari nama / kode',required=False,max_length=100)
    status=forms.ChoiceField(label='Status',required=False,choices=[('','Semua status'),('active','Aktif'),('inactive','Nonaktif')])
    sort=forms.ChoiceField(label='Urutkan',required=False,choices=[('name','Nama A–Z'),('status','Status')])

class AuditFilterForm(MonthFilterForm):
    q=forms.CharField(label='Cari akun / aktivitas',required=False,max_length=100)
    sort=forms.ChoiceField(label='Urutkan',required=False,choices=[('newest','Terbaru'),('oldest','Terlama')])
