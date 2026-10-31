from decimal import Decimal, InvalidOperation
from django import template
register=template.Library()
@register.filter
def rupiah(value):
    try: return 'Rp'+f'{Decimal(value):,.2f}'.replace(',','_').replace('.',',').replace('_','.')
    except (InvalidOperation,TypeError,ValueError): return 'Rp0,00'

@register.filter
def rupiah_ringkas(value):
    """Keep every meaningful cent while omitting a redundant ,00 on list screens."""
    formatted=rupiah(value)
    return formatted[:-3] if formatted.endswith(',00') else formatted
