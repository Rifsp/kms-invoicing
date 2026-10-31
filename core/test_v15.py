import uuid
from io import BytesIO
from zipfile import ZipFile
from decimal import Decimal
from datetime import timedelta
from django.test import TestCase,override_settings
from django.urls import reverse
from django.utils import timezone
from django.core.exceptions import PermissionDenied,ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.contrib.auth import get_user_model
from openpyxl import load_workbook
from .tests import FixtureMixin
from .models import Payment,LedgerEntry,AuditEvent,Procurement,Attachment
from . import services


class CorrectionsTests(FixtureMixin,TestCase):
    def test_operator_cash_access_and_owner_only_all_cancel_routes(self):
        entry=services.cash_movement(self.operator,1000,'income',timezone.localdate(),'Modal oleh admin',uuid.uuid4())
        self.assertEqual(services.balance(),1000)
        self.client.force_login(self.operator)
        self.assertEqual(self.client.get(reverse('finance')).status_code,200)
        for kind,pk in [('cash',entry.pk),('order',self.order.pk),('payment',999)]:
            url=reverse('cancel_transaction',args=[kind,pk])
            self.assertEqual(self.client.get(url).status_code,403)
            self.assertEqual(self.client.post(url,{'reason':'Koreksi salah input'}).status_code,403)
        with self.assertRaises(PermissionDenied):services.delete_item(self.operator,self.order.pk,self.item.pk)
        with self.assertRaises(PermissionDenied):services.cancel_order(self.operator,self.order.pk,'Salah pengadaan')
        self.assertTrue(self.order.items.exists())
    def test_payment_cancellation_restores_cash_and_remaining_once_keeps_evidence(self):
        self.confirm();self.fund('1000');invoice=self.order.invoices.get(kind='supplier')
        proof=SimpleUploadedFile('nota.pdf',b'%PDF-1.4\n%%EOF',content_type='application/pdf')
        payment=services.record_payment(self.operator,invoice.pk,100,timezone.localdate(),'REF',uuid.uuid4(),evidence=proof)
        services.cancel_payment(self.owner,payment.pk,'Duplikat pembayaran')
        services.cancel_payment(self.owner,payment.pk,'Klik ulang pembatalan')
        invoice.refresh_from_db()
        self.assertEqual(services.balance(),1000);self.assertEqual(invoice.paid,0)
        self.assertTrue(Payment.objects.get(pk=payment.pk).cancelled_at)
        self.assertTrue(LedgerEntry.objects.get(payment=payment).cancelled_at)
        self.assertEqual(payment.evidences.count(),1)
        self.assertEqual(AuditEvent.objects.filter(action='payment.cancelled').count(),1)
        self.client.force_login(self.owner)
        page=self.client.get(reverse('payment_reports'));self.assertEqual(len(page.context['page']),0)
        self.assertEqual(self.client.get(reverse('invoice_detail',args=[invoice.pk])).status_code,200)
    def test_cannot_reverse_spent_income_or_cancel_linked_cash_independently(self):
        incoming=self.fund('1000')
        outgoing=services.cash_movement(self.operator,800,'expense',timezone.localdate(),'Pembelian',uuid.uuid4())
        with self.assertRaises(ValidationError):services.cancel_cash(self.owner,incoming.pk,'Koreksi modal awal')
        self.assertEqual(services.balance(),200)
        services.cancel_cash(self.owner,outgoing.pk,'Pengeluaran salah catat')
        services.cancel_cash(self.owner,incoming.pk,'Modal salah catat')
        self.assertEqual(services.balance(),0)
        self.confirm();self.fund('1000');invoice=self.order.invoices.get(kind='supplier');payment=self.pay(invoice,100)
        with self.assertRaises(ValidationError):services.cancel_cash(self.owner,LedgerEntry.objects.get(payment=payment).pk,'Jangan lepas kas invoice')
    def test_order_cancellation_requires_no_active_payment_blocks_payment_and_omzet(self):
        self.confirm();self.fund('1000');invoice=self.order.invoices.get(kind='supplier');payment=self.pay(invoice,100)
        with self.assertRaises(ValidationError):services.cancel_order(self.owner,self.order.pk,'Pengadaan tidak jadi')
        services.cancel_payment(self.owner,payment.pk,'Salah catat pembayaran')
        services.cancel_order(self.owner,self.order.pk,'Pengadaan tidak jadi')
        with self.assertRaises(ValidationError):self.pay(invoice,100)
        with self.assertRaises(ValidationError):services.advance_order(self.operator,self.order.pk)
        self.client.force_login(self.owner)
        self.assertEqual(self.client.get(reverse('reports')).context['rows'],[])
        page=self.client.get(reverse('invoice_detail',args=[invoice.pk]))
        self.assertContains(page,'DIBATALKAN');self.assertNotContains(page,'Simpan pembayaran')
        self.assertEqual(self.order.invoices.count(),4)
    def test_superadmin_can_cancel_and_reason_is_required(self):
        admin=get_user_model().objects.create_superuser('root',password='test')
        with self.assertRaises(ValidationError):services.cancel_order(admin,self.order.pk,'')
        services.cancel_order(admin,self.order.pk,'Pengadaan salah dibuat')
        self.order.refresh_from_db();self.assertEqual(self.order.status,'cancelled')
    def test_bulk_saved_delete_denied_and_rolls_back_operator_changes(self):
        from .test_bulk import BulkEntryTests
        from .forms import PurchaseFormSet
        helpers=BulkEntryTests();helpers.item=self.item;helpers.product=self.product;helpers.supplier=self.supplier
        data=helpers.purchase_data([helpers.purchase_row(DELETE='on'),helpers.purchase_row(id=None,quantity='2')])
        with self.assertRaises(PermissionDenied):services.save_purchase_lines(self.operator,self.order.pk,PurchaseFormSet(data,prefix='items'),0)
        self.assertEqual(self.order.items.count(),1)
    def test_date_filtered_finance_and_no_thumbnail_requests(self):
        self.fund('1000');yesterday=timezone.localdate()-timedelta(days=1)
        services.cash_movement(self.operator,200,'income',yesterday,'Modal kemarin',uuid.uuid4())
        self.client.force_login(self.operator)
        page=self.client.get(reverse('finance'),{'start':timezone.localdate(),'end':timezone.localdate()})
        self.assertEqual(page.context['income'],1000);self.assertEqual(page.context['balance'],1200)
        self.assertEqual(len(page.context['page']),1);self.assertNotContains(page,'thumb=1')
        self.assertContains(page,'Unduh bukti per tanggal')
    def test_archive_filters_transaction_dates_names_and_retains_cancelled(self):
        today=timezone.localdate();yesterday=today-timedelta(days=1)
        file=lambda:SimpleUploadedFile('foto.pdf',b'%PDF-1.4\n%%EOF',content_type='application/pdf')
        entry=services.cash_movement(self.operator,1000,'income',yesterday,'Modal audit',uuid.uuid4(),evidence=file())
        services.cancel_cash(self.owner,entry.pk,'Modal dobel input')
        services.cash_movement(self.operator,100,'income',today,'Hari ini',uuid.uuid4(),evidence=file())
        self.client.force_login(self.operator)
        response=self.client.get(reverse('evidence_archive'),{'start':yesterday.isoformat(),'end':yesterday.isoformat()})
        with ZipFile(BytesIO(b''.join(response.streaming_content))) as archive:
            names=archive.namelist();self.assertEqual(len(names),2)
            name=next(n for n in names if n.endswith('.pdf'))
            self.assertTrue(name.startswith(yesterday.isoformat()+'/'));self.assertIn('-batal-',name)
            self.assertIn('Dibatalkan',archive.read('daftar-bukti.csv').decode('utf-8-sig'))
        proof=entry.evidences.get();self.assertIn(yesterday.isoformat(),proof.original_name)
        response=self.client.get(reverse('financial_evidence_download',args=[proof.pk]));self.assertIn('batal',response['Content-Disposition']);response.close()
        self.assertEqual(self.client.get(reverse('evidence_archive'),{'start':today,'end':yesterday}).status_code,200)
    def test_completed_procurement_exports_snapshot_and_exact_profit(self):
        profile=services.invoice_profile('procurement');profile.heading='KOP ORGANISASI';profile.footer='Catatan audit';profile.save()
        self.confirm();services.advance_order(self.operator,self.order.pk);services.advance_order(self.operator,self.order.pk)
        profile.heading='KOP BARU';profile.save()
        self.client.force_login(self.operator)
        response=self.client.get(reverse('procurement_export',args=[self.order.pk,'xlsx']))
        self.assertEqual(response.status_code,200)
        book=load_workbook(BytesIO(response.content));sheet=book.active
        self.assertEqual(sheet['B1'].value,'KOP ORGANISASI')
        header=next(row[0].row for row in sheet if row[0].value=='NO')
        self.assertEqual(sheet.cell(header+1,7).value,500)
        self.assertEqual(sheet.cell(header+1,9).value,500)
        self.assertEqual(sheet.cell(header+1,12).value,500)
        self.assertEqual(sheet.cell(header+1,13).value,50000)
        self.assertEqual(sheet.cell(header+2,13).value,50000)
        self.assertEqual(sheet.page_setup.orientation,'landscape')
        response=self.client.get(reverse('procurement_export',args=[self.order.pk,'pdf']))
        self.assertTrue(response.content.startswith(b'%PDF-'))
        self.assertEqual(response['Content-Type'],'application/pdf')
    def test_export_blocked_for_draft_confirmed_and_cancelled(self):
        self.client.force_login(self.owner)
        for format in ['xlsx','pdf']:
            self.assertEqual(self.client.get(reverse('procurement_export',args=[self.order.pk,format])).status_code,302)
        self.confirm()
        self.assertEqual(self.client.get(reverse('procurement_export',args=[self.order.pk,'pdf'])).status_code,302)
        services.cancel_order(self.owner,self.order.pk,'Pengadaan tidak jadi')
        self.assertEqual(self.client.get(reverse('procurement_export',args=[self.order.pk,'xlsx'])).status_code,302)
    def test_invoice_filter_ignores_cancelled_payment_amount(self):
        self.confirm();self.fund('2000000');invoice=self.order.invoices.get(kind='supplier');payment=self.pay(invoice,invoice.total)
        services.cancel_payment(self.owner,payment.pk,'Salah catat pelunasan')
        self.client.force_login(self.owner)
        page=self.client.get(reverse('supplier_invoices'),{'status':'unpaid'})
        self.assertEqual(page.context['count'],1)
    def test_cancelled_request_key_cannot_reapply_financial_movement(self):
        key=uuid.uuid4();entry=services.cash_movement(self.operator,100,'income',timezone.localdate(),'Salah modal',key)
        services.cancel_cash(self.owner,entry.pk,'Modal tidak terjadi')
        with self.assertRaises(ValidationError):services.cash_movement(self.operator,100,'income',timezone.localdate(),'Salah modal',key)
    def test_report_profile_has_own_kop_and_can_save_without_invoice_number_fields(self):
        self.client.force_login(self.owner)
        page=self.client.get(reverse('invoice_settings',args=['procurement']))
        self.assertEqual(page.status_code,200);self.assertContains(page,'Laporan pengadaan')
        self.assertNotContains(page,'name="number_pattern"')
        data={'title':'LAPORAN PENGADAAN','heading':'Organisasi Sendiri','address':'Alamat organisasi','bank_info':'Rekening','signature':'','footer':'Catatan','signer_1_title':'Sekretaris','signer_1_name':'Pengurus','signer_1_identity':'NRP 123'}
        response=self.client.post(reverse('invoice_settings',args=['procurement']),data)
        self.assertEqual(response.status_code,302)
        profile=services.invoice_profile('procurement');self.assertEqual(profile.heading,'Organisasi Sendiri');self.assertEqual(profile.signers[0]['name'],'Pengurus')
        self.client.force_login(self.operator)
        self.assertEqual(self.client.post(reverse('invoice_settings',args=['procurement']),data).status_code,403)
