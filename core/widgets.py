from django import forms


class SearchSelect(forms.Select):
    """Render only the chosen option; retrieve the rest via authenticated search."""
    def __init__(self,kind,attrs=None):
        super().__init__(dict(attrs or {},**{'data-search-kind':kind}))
    def optgroups(self,name,value,attrs=None):
        choices=self.choices
        if hasattr(choices,'queryset'):
            ids=[str(v) for v in value if str(v).isdigit() and len(str(v))<20]
            options=[('','Pilih dari pencarian…')]
            if ids:options.extend((obj.pk,choices.field.label_from_instance(obj)) for obj in choices.queryset.filter(pk__in=ids))
            self.choices=options
            try:return super().optgroups(name,value,attrs)
            finally:self.choices=choices
        return super().optgroups(name,value,attrs)
