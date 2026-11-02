import uuid
from io import BytesIO
from pathlib import Path
from decimal import Decimal
from tempfile import TemporaryDirectory
from PIL import Image
from django.test import TestCase,override_settings
from django.urls import reverse
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.exceptions import ValidationError
from django.utils import timezone
from openpyxl import load_workbook
from .tests import FixtureMixin
from .models import Product,Partner,Invoice,InvoiceProfile,FinancialEvidence,Payment,Attachment
from .forms import ItemForm
from .uploads import prepare_evidence,prepare_logo,validate_evidence
from .services import invoice_profile,record_payment,confirm_order


def picture(name='photo.png',size=(2200,1700),color='white'):
    stream=BytesIO();Image.new('RGB',size,color).save(stream,'PNG')
    return SimpleUploadedFile(name,stream.getvalue(),content_type='image/png')


class InterfaceTests(FixtureMixin,TestCase):
    def setUp(self):
        super().setUp();self.client.force_login(self.owner)
        self.media=TemporaryDirectory();self.addCleanup(self.media.cleanup)
        override=override_settings(MEDIA_ROOT=self.media.name);override.enable();self.addCleanup(override.disable)
    def test_supplier_and_sales_menus_and_order_groups_are_separate(self):
        self.confirm()
        supplier=self.order.invoices.get(kind='supplier')
        sales=self.order.invoices.get(kind='kms')
        page=self.client.get(reverse('supplier_invoices'))
        self.assertEqual([i.kind for i in page.context['page']],['supplier'])
        self.assertContains(page,supplier.code);self.assertNotContains(page,sales.code)
        page=self.client.get(reverse('invoices'))
        self.assertEqual(set(i.kind for i in page.context['page']),{'kms','cooperative'})
        self.assertNotContains(page,supplier.code)
        self.assertRedirects(self.client.get(reverse('invoices'),{'kind':'supplier'}),reverse('supplier_invoices'))
        detail=self.client.get(reverse('order_detail',args=[self.order.pk]))
        self.assertContains(detail,'Tagihan Supplier');self.assertContains(detail,'Invoice Penjualan')
    def test_lookup_supports_product_code_name_unit_and_caps_results(self):
        response=self.client.get(reverse('lookup'),{'kind':'product','q':'P001'})
        self.assertEqual(response.json()['results'][0]['label'],'P001 · Beras · kg')
        self.assertEqual(self.client.get(reverse('lookup'),{'kind':'product','q':'beras'}).json()['results'][0]['id'],self.product.pk)
        Product.objects.bulk_create([Product(code=f'ITEM-{i}',name=f'Barang {i}',category='Tes') for i in range(40)])
        self.assertEqual(len(self.client.get(reverse('lookup'),{'kind':'product'}).json()['results']),20)
        self.product.active=False;self.product.save()
        self.assertEqual(self.client.get(reverse('lookup'),{'kind':'product','q':'Beras'}).json()['results'],[])
        self.assertEqual(self.client.get(reverse('lookup'),{'kind':'arbitrary'}).status_code,400)
        self.client.logout();self.assertEqual(self.client.get(reverse('lookup'),{'kind':'product'}).status_code,302)
    def test_item_form_loads_only_selected_option_and_has_staged_search(self):
        Product.objects.create(code='OTHER',name='Should not render',category='Tes')
        form=ItemForm(user=self.owner,instance=self.item)
        html=str(form['product'])
        self.assertIn('data-search-kind="product"',html)
        self.assertIn('Beras',html);self.assertNotIn('Should not render',html)
        page=self.client.get(reverse('item_edit',args=[self.order.pk,self.item.pk]))
        self.assertContains(page,'data-stage="1"');self.assertContains(page,'data-stage="2"')
    def test_compression_reduces_dimensions_and_never_stores_original(self):
        optimized,thumb,suffix=prepare_evidence(picture())
        self.assertEqual(suffix,'.jpg');self.assertLessEqual(optimized.size,300*1024)
        image=Image.open(optimized);self.assertLessEqual(max(image.size),1600)
        self.assertLessEqual(max(Image.open(thumb).size),320)
        self.confirm();self.fund()
        payment=record_payment(self.owner,self.order.invoices.get(kind='supplier').pk,'100',timezone.localdate(),'PHOTO',uuid.uuid4(),evidence=picture('original.png'))
        proof=payment.evidences.get()
        self.assertTrue(proof.file.name.endswith('.jpg'));self.assertTrue(proof.thumbnail)
        files=[p for p in Path(self.media.name).rglob('*') if p.is_file()]
        self.assertEqual(len(files),2)
        self.assertFalse(any(p.name=='original.png' for p in files))
    def test_pdf_limit_and_invalid_images_are_rejected(self):
        with self.assertRaises(ValidationError):validate_evidence(SimpleUploadedFile('big.pdf',b'%PDF-'+b'0'*(1024*1024)))
        with self.assertRaises(ValidationError):validate_evidence(SimpleUploadedFile('bad.png',b'\x89PNG\r\n\x1a\nnot an image'))
        with self.assertRaises(ValidationError):prepare_logo(SimpleUploadedFile('logo.svg',b'<svg/>'))
    def test_inline_thumbnail_and_pdf_are_private_and_download_still_works(self):
        self.confirm();invoice=self.order.invoices.get(kind='kms')
        payment=record_payment(self.owner,invoice.pk,'100',timezone.localdate(),'PROOF',uuid.uuid4(),evidence=picture())
        proof=payment.evidences.get()
        response=self.client.get(reverse('financial_evidence_download',args=[proof.pk]),{'preview':'1','thumb':'1'})
        self.assertEqual(response['Content-Type'],'image/jpeg');self.assertIn('inline',response['Content-Disposition']);self.assertEqual(response['Cache-Control'],'private, no-store');response.close()
        response=self.client.get(reverse('financial_evidence_download',args=[proof.pk]))
        self.assertIn('attachment',response['Content-Disposition']);response.close()
        self.client.logout();self.assertEqual(self.client.get(reverse('financial_evidence_download',args=[proof.pk]),{'preview':'1'}).status_code,302)
    def profile_data(self,profile):
        keys=['prefix','number_pattern','reset','title','heading','address','bank_info','signature','footer','style','due_days']
        return {key:getattr(profile,key) for key in keys}
    def test_partner_specific_logos_three_signatures_and_immutable_print_snapshot(self):
        base=invoice_profile('cooperative');data=self.profile_data(base)
        data.update(heading='Organisasi Dapur A',logo_left=picture('left.png',size=(300,300)),logo_right=picture('right.png',size=(300,300)))
        for i,title in enumerate(['Sekretaris','Ur. Usaha','Ketua koperasi'],1):
            data.update({f'signer_{i}_title':title,f'signer_{i}_name':f'Nama {i}',f'signer_{i}_identity':f'NRP 000{i}'})
        url=reverse('invoice_settings',args=['cooperative'])+f'?partner={self.coop.pk}'
        self.assertEqual(self.client.post(url,data).status_code,302)
        profile=InvoiceProfile.objects.get(kind='cooperative',partner=self.coop)
        self.assertEqual(len(profile.signers),3);self.assertTrue(profile.logo_left)
        self.confirm();invoice=self.order.invoices.get(kind='cooperative')
        self.assertEqual(invoice.print_snapshot['heading'],'Organisasi Dapur A')
        old_logo=invoice.print_snapshot['logo_left']
        data=self.profile_data(profile);data.update(heading='Kop baru',clear_logo_left='on')
        self.client.post(url,data)
        invoice.refresh_from_db();self.assertEqual(invoice.print_snapshot['logo_left'],old_logo)
        page=self.client.get(reverse('invoice_detail',args=[invoice.pk]))
        self.assertContains(page,'Nama 3');self.assertContains(page,'NRP 0003');self.assertContains(page,'signer-third')
        self.assertNotContains(page,'harga dinaikkan');self.assertNotContains(page,'Kop baru')
        response=self.client.get(reverse('invoice_logo',args=[invoice.pk,'left']))
        self.assertEqual(response.status_code,200);self.assertEqual(response['Content-Type'],'image/png');response.close()
        self.client.force_login(self.operator)
        self.assertEqual(self.client.get(url).status_code,403)
    def test_partner_scope_falls_back_to_default_for_other_kitchen(self):
        base=invoice_profile('kitchen');base.heading='Pola umum';base.save()
        specific=InvoiceProfile.objects.create(kind='kitchen',partner=self.kitchen,prefix='DPR-A',heading='Khusus A')
        other=Partner.objects.create(name='Dapur B',kind='kitchen')
        self.assertEqual(invoice_profile('kitchen',self.kitchen).pk,specific.pk)
        self.assertEqual(invoice_profile('kitchen',other).pk,base.pk)
    def test_excel_filters_links_and_owner_only_financial_columns(self):
        self.confirm();invoice=self.order.invoices.get(kind='kms')
        record_payment(self.owner,invoice.pk,'100',timezone.localdate(),'=HYPERLINK("x")',uuid.uuid4(),evidence=picture())
        response=self.client.get(reverse('reports'),{'export':'xlsx'})
        self.assertEqual(response.status_code,200)
        book=load_workbook(BytesIO(response.content))
        self.assertIn('Omzet KMS',[cell.value for cell in book['Omzet dan profit'][1]])
        self.assertEqual(book['Pembayaran']['H2'].value,''' '=HYPERLINK("x")'''.strip())
        self.assertIsNotNone(book['Bukti']['D2'].hyperlink)
        self.client.force_login(self.operator)
        response=self.client.get(reverse('reports'),{'export':'xlsx'})
        book=load_workbook(BytesIO(response.content))
        self.assertNotIn('Omzet KMS',[cell.value for cell in book['Omzet dan profit'][1]])
        self.assertEqual(book['Pembayaran'].max_row,1)
        self.client.force_login(self.owner)
        response=self.client.get(reverse('reports'),{'export':'xlsx','start':'2099-01-01'})
        self.assertEqual(load_workbook(BytesIO(response.content))['Omzet dan profit'].max_row,1)
    def test_payment_report_filters_previews_and_excel_no_duplicate_payment_rows(self):
        self.confirm();self.fund()
        invoice=self.order.invoices.get(kind='supplier')
        payment=record_payment(self.owner,invoice.pk,'100',timezone.localdate(),'SUP',uuid.uuid4(),evidence=picture())
        from .services import attach_payment_evidence
        attach_payment_evidence(self.owner,payment.pk,picture('second.png'))
        page=self.client.get(reverse('payment_reports'),{'supplier':self.supplier.pk})
        self.assertEqual(len(page.context['page']),1);self.assertContains(page,'data-proof-preview');self.assertNotContains(page,'thumb=1')
        book=load_workbook(BytesIO(self.client.get(reverse('payment_reports'),{'supplier':self.supplier.pk,'export':'xlsx'}).content))
        self.assertEqual(book['Pembayaran'].max_row,2);self.assertEqual(book['Bukti'].max_row,3)
        self.assertEqual(book['Pembayaran']['G2'].value,100)
        self.client.force_login(self.operator)
        self.assertEqual(self.client.get(reverse('payment_reports'),{'kind':'kms'}).context['page'].paginator.count,0)
    def test_optimization_failure_on_additional_upload_is_reported_without_server_error(self):
        from unittest.mock import patch
        self.confirm();invoice=self.order.invoices.get(kind='kms')
        payment=record_payment(self.owner,invoice.pk,'100',timezone.localdate(),'TEST',uuid.uuid4())
        with patch('core.services.prepare_evidence',side_effect=ValidationError('Potong foto agar lebih kecil.')):
            response=self.client.post(reverse('payment_evidence_upload',args=[payment.pk]),{'file':picture()},follow=True)
        self.assertEqual(response.status_code,200);self.assertContains(response,'Potong foto agar lebih kecil.')
        self.assertEqual(payment.evidences.count(),0)
        self.assertEqual(Payment.objects.get(pk=payment.pk).amount,Decimal('100'))
    def test_cash_excel_is_owner_only_and_includes_proof_links(self):
        from .services import cash_movement
        entry=cash_movement(self.owner,'1000','income',timezone.localdate(),'Modal',uuid.uuid4(),evidence=picture())
        response=self.client.get(reverse('finance'),{'export':'xlsx'})
        book=load_workbook(BytesIO(response.content))
        self.assertEqual(book['Mutasi']['E2'].value,1000)
        self.assertIsNotNone(book['Bukti']['D2'].hyperlink)
        self.client.force_login(self.operator)
        self.assertEqual(self.client.get(reverse('finance'),{'export':'xlsx'}).status_code,200)
