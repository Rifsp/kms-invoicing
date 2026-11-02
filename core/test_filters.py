from datetime import date,datetime,timedelta
from decimal import Decimal
from io import BytesIO
from unittest.mock import patch
import uuid
from django.test import TestCase
from django.utils import timezone
from django.urls import reverse
from openpyxl import load_workbook
from .tests import FixtureMixin
from .models import Procurement,Invoice,LedgerEntry,Payment,Product
from .forms import FinanceFilterForm,OrderListFilterForm
from . import services


class TransactionFilterTests(FixtureMixin,TestCase):
    def setUp(self):
        super().setUp();self.client.force_login(self.owner)
        self.today=timezone.localdate();self.first=self.today.replace(day=1)
        self.previous=self.first-timedelta(days=1)
        self.next=(self.first.replace(day=28)+timedelta(days=4)).replace(day=1)
    def month(self,d):return d.strftime('%Y-%m')
    def new_order(self,day,status='draft'):
        return Procurement.objects.create(cooperative=self.coop,kitchen=self.kitchen,delivery_date=day,status=status,created_by=self.owner)
    def stamp(self,day):return timezone.make_aware(datetime.combine(day,datetime.min.time()))
    def test_default_month_and_requested_month_use_delivery_date(self):
        old=self.new_order(self.previous);future=self.new_order(self.next)
        page=self.client.get(reverse('orders'));self.assertEqual([o.pk for o in page.context['page']],[self.order.pk])
        page=self.client.get(reverse('orders'),{'month':self.month(self.previous)})
        self.assertEqual([o.pk for o in page.context['page']],[old.pk])
        self.assertNotContains(page,f'href="/orders/{future.pk}/"')
    def test_month_rolls_over_without_remembering_previous_default(self):
        with patch('core.forms.timezone.localdate',return_value=date(2026,12,31)):
            form=OrderListFilterForm({});self.assertTrue(form.is_valid());self.assertEqual(form.cleaned_data['month'],date(2026,12,1))
        with patch('core.forms.timezone.localdate',return_value=date(2027,1,1)):
            form=OrderListFilterForm({});self.assertTrue(form.is_valid());self.assertEqual(form.cleaned_data['month'],date(2027,1,1))
    def test_all_months_explicit_and_invalid_month_does_not_broaden_results(self):
        self.new_order(self.previous)
        page=self.client.get(reverse('orders'),{'all_months':'on'})
        self.assertEqual(page.context['page'].paginator.count,2)
        for query in [{'month':'2026-13'},{'month':''},{'sort':'status; DROP TABLE'}]:
            page=self.client.get(reverse('orders'),query);self.assertFalse(page.context['filter_form'].is_valid());self.assertEqual(len(page.context['page']),0)
    def test_order_status_filter_and_actual_status_sort(self):
        self.new_order(self.today,'received');self.new_order(self.today,'cancelled');self.new_order(self.today,'shipped');self.new_order(self.today,'confirmed')
        page=self.client.get(reverse('orders'),{'sort':'status'})
        self.assertEqual([o.status for o in page.context['page']],['draft','confirmed','shipped','received','cancelled'])
        page=self.client.get(reverse('orders'),{'status':'shipped'})
        self.assertEqual([o.status for o in page.context['page']],['shipped'])
    def test_finance_month_date_boundaries_and_all_time_balance(self):
        # Direct dated ledger fixtures also exercise month bounds in months with future days.
        wallet=services.kms_wallet()
        for day,value in [(self.previous,100),(self.first,200),(self.next-timedelta(days=1),300),(self.next,400)]:
            LedgerEntry.objects.create(wallet=wallet,date=day,amount=value,description='Test bulan',created_by=self.owner)
        page=self.client.get(reverse('finance'))
        self.assertEqual(len(page.context['page']),2);self.assertEqual(page.context['income'],500);self.assertEqual(page.context['balance'],1000)
        page=self.client.get(reverse('finance'),{'month':self.month(self.previous)})
        self.assertEqual(page.context['income'],100)
        book=load_workbook(BytesIO(self.client.get(reverse('finance'),{'month':self.month(self.previous),'export':'xlsx'}).content))
        self.assertEqual(book['Mutasi'].max_row,2);self.assertEqual(book['Mutasi']['A2'].value.date(),self.previous)
    def test_finance_status_direction_and_sort_are_combined(self):
        first=self.fund('1000');expense=services.cash_movement(self.operator,200,'expense',self.today,'Pengeluaran',uuid.uuid4())
        services.cancel_cash(self.owner,expense.pk,'Duplikat biaya')
        page=self.client.get(reverse('finance'),{'status':'cancelled','direction':'expense','sort':'status'})
        self.assertEqual([entry.pk for entry in page.context['page']],[expense.pk]);self.assertEqual(page.context['expense'],0)
        page=self.client.get(reverse('finance'),{'status':'active'})
        self.assertEqual([entry.pk for entry in page.context['page']],[first.pk])
    def test_explicit_date_range_can_cross_months_without_implicit_month(self):
        form=FinanceFilterForm({'start':self.previous.isoformat(),'end':self.today.isoformat()})
        self.assertTrue(form.is_valid());self.assertIsNone(form.cleaned_data['month'])
        self.assertFalse(FinanceFilterForm({'start':self.today,'end':self.previous}).is_valid())
    def test_invoice_month_uses_issue_date_and_status_excludes_void(self):
        self.confirm();invoice=self.order.invoices.get(kind='supplier')
        Invoice.objects.filter(pk=invoice.pk).update(created_at=self.stamp(self.previous))
        page=self.client.get(reverse('supplier_invoices'));self.assertEqual(page.context['count'],0)
        page=self.client.get(reverse('supplier_invoices'),{'month':self.month(self.previous),'status':'unpaid'});self.assertEqual(page.context['count'],1)
        services.cancel_order(self.owner,self.order.pk,'Pengadaan dibatalkan')
        page=self.client.get(reverse('supplier_invoices'),{'month':self.month(self.previous),'status':'unpaid'});self.assertEqual(page.context['count'],0)
        page=self.client.get(reverse('supplier_invoices'),{'month':self.month(self.previous),'status':'cancelled'});self.assertEqual(page.context['count'],1)
    def test_invoice_payment_status_sort_is_stable_and_colored(self):
        self.confirm();invoices={i.kind:i for i in self.order.invoices.all()}
        services.record_payment(self.operator,invoices['cooperative'].pk,invoices['cooperative'].total,self.today,'Lunas',uuid.uuid4())
        services.record_payment(self.operator,invoices['kms'].pk,100,self.today,'Cicilan',uuid.uuid4())
        extra=self.new_order(self.today)
        Invoice.objects.create(procurement=extra,kind='kms',issuer_name='KMS',recipient_name='Koperasi lain',total=1000,due_date=self.today)
        page=self.client.get(reverse('invoices'),{'sort':'status'})
        self.assertEqual([i.payment_status_key for i in page.context['page']],['unpaid','partial','paid'])
        for status in ['unpaid','partial','paid']:self.assertContains(page,f'class="badge {status}"')
    def test_payment_report_filters_cancelled_and_exports_same_status(self):
        self.confirm();invoice=self.order.invoices.get(kind='cooperative')
        payment=services.record_payment(self.operator,invoice.pk,100,self.today,'Audit',uuid.uuid4())
        services.cancel_payment(self.owner,payment.pk,'Duplikat pembayaran')
        self.assertEqual(len(self.client.get(reverse('payment_reports')).context['page']),0)
        query={'status':'cancelled','month':self.month(self.today)}
        page=self.client.get(reverse('payment_reports'),query);self.assertEqual(len(page.context['page']),1)
        book=load_workbook(BytesIO(self.client.get(reverse('payment_reports'),dict(query,export='xlsx')).content))
        self.assertEqual(book['Pembayaran']['I2'].value,'Dibatalkan')
    def test_pagination_keeps_month_status_sort_and_dates(self):
        for _ in range(27):self.new_order(self.previous,'confirmed')
        query={'month':self.month(self.previous),'status':'confirmed','sort':'oldest','start':self.previous.isoformat()}
        page=self.client.get(reverse('orders'),query)
        self.assertContains(page,'page=2');self.assertContains(page,'month='+self.month(self.previous));self.assertContains(page,'sort=oldest');self.assertContains(page,'status=confirmed')
        page=self.client.get(reverse('orders'),dict(query,page=2));self.assertEqual(len(page.context['page']),2)
    def test_reports_default_to_confirmation_month_and_selected_status(self):
        self.confirm();Procurement.objects.filter(pk=self.order.pk).update(confirmed_at=self.stamp(self.previous))
        self.assertEqual(self.client.get(reverse('reports')).context['rows'],[])
        page=self.client.get(reverse('reports'),{'month':self.month(self.previous),'status':'confirmed'})
        self.assertEqual(len(page.context['rows']),1)
        self.assertEqual(self.client.get(reverse('reports'),{'month':self.month(self.previous),'status':'received'}).context['rows'],[])
    def test_master_status_filters_do_not_hide_older_master_records(self):
        Product.objects.filter(pk=self.product.pk).update(created_at=self.stamp(self.previous))
        Product.objects.create(code='OLD',name='Nonaktif',category='Tes',active=False)
        page=self.client.get(reverse('products'),{'status':'active'});self.assertEqual([p.pk for p in page.context['page']],[self.product.pk])
        page=self.client.get(reverse('products'),{'sort':'status'});self.assertEqual([p.active for p in page.context['page']],[True,False])
    def test_actions_are_separate_from_amount_and_no_operator_cancel_links(self):
        self.fund('1000')
        page=self.client.get(reverse('finance'));self.assertContains(page,'data-row-dialog=');self.assertContains(page,'class="danger-zone"');self.assertContains(page,'class="transaction-filter-form"')
        self.client.force_login(self.operator)
        self.assertNotContains(self.client.get(reverse('finance')),'Batalkan mutasi')
        self.assertNotContains(self.client.get(reverse('orders')),'Batalkan pengadaan')
    def test_audit_period_defaults_and_selected_month(self):
        event=services.audit(self.owner,'test.month','PGD-test')
        from .models import AuditEvent
        AuditEvent.objects.filter(action='test.month').update(created_at=self.stamp(self.previous))
        self.assertEqual(len(self.client.get(reverse('audit')).context['page']),0)
        self.assertEqual(len(self.client.get(reverse('audit'),{'month':self.month(self.previous)}).context['page']),1)
    def test_compact_amounts_keep_nonzero_cents_visible(self):
        services.cash_movement(self.owner,Decimal('100.50'),'income',self.today,'Nominal dengan sen',uuid.uuid4())
        page=self.client.get(reverse('finance'));self.assertContains(page,'Rp100,50')
