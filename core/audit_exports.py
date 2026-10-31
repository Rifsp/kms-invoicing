"""Stream private evidence to a temporary ZIP, never load a whole audit period in RAM."""
import csv
import tempfile
from io import StringIO
from zipfile import ZipFile, ZIP_DEFLATED
from django.db.models import Q
from django.http import FileResponse
from .models import FinancialEvidence,Attachment
from .services import evidence_filename
from django.utils.text import slugify
from pathlib import PurePath


def evidence_zip(start,end):
    output=tempfile.TemporaryFile()
    index=StringIO(newline='');writer=csv.writer(index)
    def safe(value):
        value=str(value)
        return "'"+value if value.startswith(('=','+','-','@','\t','\r')) else value
    writer.writerow(['Tanggal transaksi','Jenis','Transaksi','Status','File'])
    try:
        with ZipFile(output,'w',ZIP_DEFLATED,allowZip64=True) as archive:
            proofs=FinancialEvidence.objects.filter(Q(payment__date__range=(start,end))|Q(ledger_entry__date__range=(start,end))).select_related('payment__invoice__procurement','ledger_entry').order_by('pk')
            for proof in proofs.iterator(chunk_size=100):
                target=proof.payment if proof.payment_id else proof.ledger_entry
                name=f'{target.date.isoformat()}/{evidence_filename(proof)}'
                with proof.file.open('rb') as source,archive.open(name,'w',force_zip64=True) as dest:
                    while chunk:=source.read(1024*256):dest.write(chunk)
                transaction=proof.payment.invoice.code if proof.payment_id else f'KAS-{target.pk}'
                writer.writerow([target.date.isoformat(),'Pembayaran' if proof.payment_id else 'Mutasi manual',safe(transaction),'Dibatalkan' if target.cancelled_at else 'Aktif',name])
            attachments=Attachment.objects.filter(procurement__delivery_date__range=(start,end)).select_related('procurement').order_by('pk')
            for proof in attachments.iterator(chunk_size=100):
                order=proof.procurement
                name=f'{order.delivery_date.isoformat()}/{order.code}-lampiran-{proof.pk}-{slugify(PurePath(proof.original_name).stem)[:70]}{PurePath(proof.file.name).suffix}'
                with proof.file.open('rb') as source,archive.open(name,'w',force_zip64=True) as dest:
                    while chunk:=source.read(1024*256):dest.write(chunk)
                writer.writerow([order.delivery_date.isoformat(),'Lampiran pengadaan',order.code,order.get_status_display(),name])
            archive.writestr('daftar-bukti.csv','\ufeff'+index.getvalue())
        output.seek(0)
        response=FileResponse(output,as_attachment=True,filename=f'bukti-transaksi-{start.isoformat()}-sd-{end.isoformat()}.zip',content_type='application/zip')
        response['Cache-Control']='private, no-store'
        return response
    except Exception:
        output.close();raise
