import io
from pathlib import Path
import pytest
from PIL import Image
from werkzeug.datastructures import FileStorage
from werkzeug.exceptions import RequestEntityTooLarge, UnprocessableEntity
import upload_security
from test_assignment_sync import site, rows


def picture(format='JPEG', size=(8, 6), exif=None):
    stream = io.BytesIO()
    image = Image.new('RGB', size, 'red')
    image.save(stream, format=format, **({'exif': exif} if exif else {}))
    return stream.getvalue()


@pytest.mark.parametrize('format', ['JPEG', 'PNG', 'WEBP'])
def test_real_images_are_saved_as_pixel_only_jpeg(tmp_path, format):
    raw = picture(format) + b'APPENDED_SCRIPT_MUST_NOT_SURVIVE'
    upload = FileStorage(io.BytesIO(raw), filename='../../unexpected.exe', content_type='application/octet-stream')
    name = upload_security.save_attendance_photo(upload, tmp_path)
    assert Path(name).name == name and name.endswith('.jpg')
    saved = (tmp_path/name).read_bytes()
    assert b'APPENDED_SCRIPT' not in saved
    with Image.open(io.BytesIO(saved)) as image:
        assert image.format == 'JPEG' and image.size == (8, 6)
        image.load()


def test_exif_orientation_preserved_and_metadata_removed(tmp_path):
    exif = Image.Exif(); exif[274] = 6; exif[270] = 'private metadata'
    raw = picture(exif=exif)
    name = upload_security.save_attendance_photo(FileStorage(io.BytesIO(raw), filename='camera.jpg'), tmp_path)
    with Image.open(tmp_path/name) as image:
        assert image.size == (6, 8)
        assert not image.getexif()
    assert b'private metadata' not in (tmp_path/name).read_bytes()


@pytest.mark.parametrize('raw', [b'<script>alert(1)</script>', b'MZ executable', b'PK\x03\x04 archive', b'\xff\xd8truncated', b''])
def test_spoofed_and_broken_images_do_not_reach_storage(tmp_path, raw):
    with pytest.raises(UnprocessableEntity):
        upload_security.save_attendance_photo(FileStorage(io.BytesIO(raw), filename='photo.jpg', content_type='image/jpeg'), tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_upload_limits_before_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(upload_security, 'MAX_PHOTO_BYTES', 10)
    with pytest.raises(RequestEntityTooLarge):
        upload_security.save_attendance_photo(FileStorage(io.BytesIO(b'x'*11), filename='photo.jpg'), tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_pixel_limit_before_decode(tmp_path, monkeypatch):
    monkeypatch.setattr(upload_security, 'MAX_PHOTO_PIXELS', 10)
    with pytest.raises(RequestEntityTooLarge):
        upload_security.save_attendance_photo(FileStorage(io.BytesIO(picture()), filename='photo.jpg'), tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_rejected_photo_keeps_attendance_and_original_evidence(site):
    module, _, data = site
    worker = module.app.test_client()
    with worker.session_transaction() as session: session['worker_id'] = 2
    before = rows(module, 'att')
    response = worker.post('/event/1', data={'wid':'2','act':'in','photo':(io.BytesIO(b'<html>not an image</html>'),'photo.jpg')}, headers={'X-Requested-With':'fetch'})
    assert response.status_code == 422 and response.json['ok'] is False
    assert rows(module, 'att') == before
    assert list((data/'uploads').iterdir()) == []


def test_valid_photo_clock_in_and_out_keep_existing_flow(site):
    module, admin, data = site
    worker = module.app.test_client()
    with worker.session_transaction() as session: session['worker_id'] = 2
    for act in ('in', 'out'):
        response = worker.post('/event/1', data={'wid':'2','act':act,'photo':(io.BytesIO(picture()),'photo.jpg')}, headers={'X-Requested-With':'fetch'})
        assert response.status_code == 200 and response.json['ok'] is True
    connection = module.con()
    row = connection.execute('select * from att where worker_id=2').fetchone(); connection.close()
    assert row['cin'] and row['cout'] and row['pinphoto'] != row['poutphoto']
    for name in (row['pinphoto'], row['poutphoto']):
        assert (data/'uploads'/name).is_file()
        assert admin.get('/uploads/'+name+'?raw=1').status_code == 200
        assert module.app.test_client().get('/uploads/'+name+'?raw=1').status_code == 302


def test_no_photo_stays_supported_and_security_headers(site):
    assert upload_security.save_attendance_photo(None, site[2]) is None
    response = site[1].get('/')
    assert response.headers['X-Content-Type-Options'] == 'nosniff'
    assert response.headers['X-Frame-Options'] == 'SAMEORIGIN'
    assert response.headers['Referrer-Policy'] == 'strict-origin-when-cross-origin'


def test_request_size_limit_returns_useful_json(site):
    module, _, _ = site
    module.app.config['MAX_CONTENT_LENGTH'] = 10
    client = module.app.test_client()
    response = client.post('/worker-device/verify', data={'code':'123456','worker_id':'2'}, headers={'X-Requested-With':'fetch'})
    assert response.status_code == 413 and response.json['ok'] is False
