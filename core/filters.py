"""Shared period and stable transaction sorting; lookup names are server-owned."""
from datetime import date
from django.db.models import Case,When,Value,IntegerField,F


def period(qs,form,lookup):
    data=form.cleaned_data
    month=data.get('month')
    if month and not data.get('all_months'):
        end=date(month.year+1,1,1) if month.month==12 else date(month.year,month.month+1,1)
        qs=qs.filter(**{lookup+'__gte':month,lookup+'__lt':end})
    return qs


def order_sort(qs,value,date_field='delivery_date'):
    if value=='status':
        qs=qs.annotate(status_rank=Case(*[When(status=status,then=Value(n)) for n,status in enumerate(['draft','confirmed','shipped','received','cancelled'])],default=Value(9),output_field=IntegerField()))
        return qs.order_by('status_rank','-'+date_field,'-pk')
    return qs.order_by(date_field if value=='oldest' else '-'+date_field,'pk' if value=='oldest' else '-pk')


def financial_sort(qs,value,date_field='date'):
    if value=='status':return qs.order_by(F('cancelled_at').asc(nulls_first=True),'-'+date_field,'-pk')
    return qs.order_by(date_field if value=='oldest' else '-'+date_field,'pk' if value=='oldest' else '-pk')


def financial_status(qs,status):
    if status=='active':return qs.filter(cancelled_at__isnull=True)
    if status=='cancelled':return qs.filter(cancelled_at__isnull=False)
    return qs
