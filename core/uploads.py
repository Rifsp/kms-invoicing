"""Validate and optimize private uploads; originals are never retained for new photos."""
from io import BytesIO
import warnings
from PIL import Image,ImageOps,UnidentifiedImageError
from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile

PHOTO_LIMIT=5*1024*1024
PDF_LIMIT=1024*1024
SAVED_PHOTO_LIMIT=300*1024


def read_image(file):
    try:
        file.seek(0)
        with warnings.catch_warnings():
            warnings.simplefilter('error',Image.DecompressionBombWarning)
            im=Image.open(file)
            if im.format not in ['PNG','JPEG'] or im.width*im.height>24_000_000:
                raise ValidationError('Foto harus JPG/PNG dan maksimal 24 megapiksel.')
            im.verify()
            file.seek(0)
            im=ImageOps.exif_transpose(Image.open(file))
            im.load()
            return im
    except (UnidentifiedImageError,OSError,ValueError,Image.DecompressionBombError,Image.DecompressionBombWarning) as error:
        raise ValidationError('Gambar rusak atau tidak dapat dibaca.') from error
    finally:
        file.seek(0)


def validate_evidence(file):
    if file is None:return None
    head=file.read(8);file.seek(0)
    if head.startswith(b'%PDF-'):
        if file.size>PDF_LIMIT:raise ValidationError('PDF maksimal 1 MB. Perkecil file sebelum mengunggah.')
    else:
        if file.size>PHOTO_LIMIT:raise ValidationError('Foto sumber maksimal 5 MB; foto akan dikompres otomatis.')
        read_image(file)
    return file


def prepare_evidence(file):
    validate_evidence(file)
    head=file.read(8);file.seek(0)
    if head.startswith(b'%PDF-'):return file,None,'.pdf'
    im=read_image(file)
    if im.mode!='RGB':
        rgba=im.convert('RGBA');im=Image.new('RGB',rgba.size,'white');im.paste(rgba,mask=rgba.getchannel('A'))
    im.thumbnail((1600,1600),Image.Resampling.LANCZOS)
    output=None
    for side in [1600,1280,1024]:
        candidate=im.copy();candidate.thumbnail((side,side),Image.Resampling.LANCZOS)
        for quality in [80,70,60,50]:
            stream=BytesIO();candidate.save(stream,'JPEG',quality=quality,optimize=True)
            if stream.tell()<=SAVED_PHOTO_LIMIT:
                output=stream.getvalue();break
        if output is not None:break
    if output is None:raise ValidationError('Foto masih terlalu besar. Potong bagian yang tidak diperlukan lalu unggah ulang.')
    thumb=im.copy();thumb.thumbnail((320,320),Image.Resampling.LANCZOS)
    stream=BytesIO();thumb.save(stream,'JPEG',quality=65,optimize=True)
    return ContentFile(output,name='bukti.jpg'),ContentFile(stream.getvalue(),name='thumbnail.jpg'),'.jpg'


def prepare_logo(file):
    if file.size>2*1024*1024:raise ValidationError('Logo sumber maksimal 2 MB.')
    im=read_image(file).convert('RGBA');im.thumbnail((600,600),Image.Resampling.LANCZOS)
    stream=BytesIO();im.save(stream,'PNG',optimize=True)
    if stream.tell()>200*1024:raise ValidationError('Logo setelah diperkecil masih lebih dari 200 KB. Gunakan logo yang lebih sederhana.')
    return ContentFile(stream.getvalue(),name='logo.png')
