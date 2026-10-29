"""Validate new attendance photos; never rewrite existing evidence or attendance."""
import io
import os
import uuid
from flask import abort, jsonify, request
from PIL import Image, ImageOps, UnidentifiedImageError

MAX_PHOTO_BYTES = 12 * 1024 * 1024
MAX_PHOTO_PIXELS = 32_000_000
FORM_LIMIT = MAX_PHOTO_BYTES + 1024 * 1024
PHOTO_FORMATS = ('JPEG', 'PNG', 'WEBP')


def save_attendance_photo(upload, directory):
    if not upload or not upload.filename:
        return None
    raw = upload.stream.read(MAX_PHOTO_BYTES + 1)
    if len(raw) > MAX_PHOTO_BYTES:
        abort(413, description='התמונה גדולה מדי. בחרו תמונה עד 12 מגה־בייט.')
    try:
        # Decode actual image bytes, not the attacker-controlled name/MIME type.
        with Image.open(io.BytesIO(raw), formats=PHOTO_FORMATS) as candidate:
            if candidate.width * candidate.height > MAX_PHOTO_PIXELS:
                abort(413, description='רזולוציית התמונה גדולה מדי. בחרו תמונה קטנה יותר.')
            candidate.verify()
        with Image.open(io.BytesIO(raw), formats=PHOTO_FORMATS) as candidate:
            candidate.load()
            oriented = ImageOps.exif_transpose(candidate)
            # A new pixel-only JPEG drops appended payloads, EXIF and other metadata.
            clean = Image.new('RGB', oriented.size, 'white')
            if 'A' in oriented.getbands():
                rgba = oriented.convert('RGBA')
                clean.paste(rgba, mask=rgba.getchannel('A'))
            else:
                clean.paste(oriented.convert('RGB'))
            output = io.BytesIO()
            clean.save(output, format='JPEG', quality=92)
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError):
        abort(422, description='הקובץ אינו תמונה תקינה. בחרו תמונת JPEG, PNG או WebP.')
    name = uuid.uuid4().hex + '.jpg'
    # No upload-controlled filenames, paths, or executable formats reach disk.
    with open(os.path.join(directory, name), 'xb') as destination:
        destination.write(output.getvalue())
    return name


def register_upload_security(app):
    app.config['MAX_CONTENT_LENGTH'] = FORM_LIMIT

    @app.errorhandler(413)
    @app.errorhandler(422)
    def invalid_upload(error):
        message = error.description if error.code == 422 else 'הקובץ גדול מדי. בחרו תמונה עד 12 מגה־בייט.'
        if request.headers.get('X-Requested-With') == 'fetch':
            return jsonify(ok=False, error=message), error.code
        return message, error.code

    @app.after_request
    def response_security(response):
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Frame-Options'] = 'SAMEORIGIN'
        response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
        return response
