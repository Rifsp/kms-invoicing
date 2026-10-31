from django import template
from django.utils.safestring import mark_safe
register=template.Library()
PATHS={
'more':'M5 12h.01 M12 12h.01 M19 12h.01',
'filter':'M4 6h16 M7 12h10 M10 18h4',
'home':'M3 10 12 3l9 7v10H3Z M9 20v-7h6v7',
'cart':'M3 3h2l3 12h11l2-8H6 M9 20h.01 M18 20h.01',
'box':'m3 7 9-4 9 4v10l-9 4-9-4Z M3 7l9 4 9-4 M12 11v10',
'invoice':'M6 3h12v18l-3-2-3 2-3-2-3 2Z M9 7h6 M9 11h6 M9 15h3',
'supplier':'M3 6h12v11H3Z M15 10h4l3 4v3h-7 M6 20a2 2 0 1 0 0-4 2 2 0 0 0 0 4 M18 20a2 2 0 1 0 0-4 2 2 0 0 0 0 4',
'chart':'M4 3v17h17 M8 16v-5 M13 16V7 M18 16V4',
'wallet':'M3 5h16v15H3Z M3 5V3h14 M15 10h6v6h-6Z M17 13h.01',
'users':'M9 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8 M2 21v-3a5 5 0 0 1 5-5h4a5 5 0 0 1 5 5v3 M17 4a4 4 0 0 1 0 7 M19 14a5 5 0 0 1 3 5v2',
'settings':'M12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8 M9 3l-1 3-3 1-2 4 2 2v4l4 2 3-1 3 1 4-2v-4l2-2-2-4-3-1-1-3Z',
'search':'M10 3a7 7 0 1 0 0 14 7 7 0 0 0 0-14 M15 15l6 6',
'plus':'M12 5v14 M5 12h14',
'check':'m5 12 4 4L19 6',
'arrow':'M4 12h16 m-6-6 6 6-6 6',
'back':'M20 12H4 m6-6-6 6 6 6',
'upload':'M12 16V3 m-5 5 5-5 5 5 M3 15v6h18v-6',
'download':'M12 3v13 m-5-5 5 5 5-5 M3 16v5h18v-5',
'eye':'M2 12s4-7 10-7 10 7 10 7-4 7-10 7-10-7-10-7 M12 9a3 3 0 1 0 0 6 3 3 0 0 0 0-6',
'print':'M7 8V3h10v5 M7 17H3V8h18v9h-4 M7 13h10v8H7Z',
'file':'M5 3h9l5 5v13H5Z M14 3v6h5 M8 13h8 M8 17h5',
'clock':'M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18 M12 7v5l4 2',
'logout':'M9 3H3v18h6 M8 12h13 m-5-5 5 5-5 5',
'menu':'M3 5h18 M3 12h18 M3 19h18',
'close':'m5 5 14 14 M19 5 5 19',
'info':'M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18 M12 11v6 M12 7h.01',
'save':'M4 3h14l3 3v15H3V3Z M7 3v6h10V3 M7 21v-8h10v8',
}
@register.simple_tag
def icon(name):
    path=PATHS.get(name,PATHS['file'])
    return mark_safe(f'<svg class="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="{path}"/></svg>')
def filtered_query(context):
    query=context['request'].GET.copy()
    form=context.get('filter_form')
    if form and form.is_bound:
        for key in ['month','all_months','status']:
            if key in form.data and key not in query:query[key]=form.data[key]
    return query

@register.simple_tag(takes_context=True)
def export_query(context):
    query=filtered_query(context);query.pop('page',None);query['export']='xlsx'
    return query.urlencode()

@register.simple_tag(takes_context=True)
def page_query(context,number):
    query=filtered_query(context);query.pop('export',None);query['page']=number
    return query.urlencode()
