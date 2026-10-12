"""Validate supplied clinical modalities without interpreting clinical content."""
from io import BytesIO
import warnings

MAX_TEXT = 100_000
MAX_FILE = 20 * 1024 * 1024
MAX_PIXELS = 25_000_000


def validate_text(text):
    if not isinstance(text, str) or not text.strip():
        raise ValueError('Văn bản trống. Hãy nhập nội dung hoặc chọn file TXT UTF-8.')
    if len(text) > MAX_TEXT or '\x00' in text:
        raise ValueError('Văn bản vượt 100.000 ký tự hoặc chứa ký tự không hợp lệ.')
    return text


def decode_txt(content):
    if not content or len(content) > MAX_FILE:
        raise ValueError('File TXT trống hoặc vượt 20 MB.')
    try: text = content.decode('utf-8-sig')
    except UnicodeDecodeError: raise ValueError('File TXT phải được lưu bằng UTF-8.') from None
    return validate_text(text)


def validate_image(content):
    from PIL import Image
    if not content or len(content) > MAX_FILE:
        raise ValueError('Ảnh trống hoặc vượt 20 MB.')
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            with Image.open(BytesIO(content)) as image:
                if image.format not in {'JPEG', 'PNG'}:
                    raise ValueError('Chỉ hỗ trợ ảnh JPEG/PNG; chưa hỗ trợ DICOM hoặc WebP.')
                if image.width * image.height > MAX_PIXELS or getattr(image, 'n_frames', 1) != 1:
                    raise ValueError('Ảnh phải có một khung và không vượt 25 triệu pixel.')
                fmt = image.format
                image.verify()
            with Image.open(BytesIO(content)) as image: image.load()
        return '.png' if fmt == 'PNG' else '.jpg'
    except ValueError: raise
    except Exception:
        raise ValueError('Ảnh JPEG/PNG bị lỗi hoặc không đọc được.') from None


def validate_modalities(text, image, same_case):
    if text is None and image is None: raise ValueError('Cần văn bản/TXT, ảnh X-quang, hoặc cả hai.')
    if text is not None: validate_text(text)
    if image is not None: validate_image(image)
    if text is not None and image is not None and not same_case:
        raise ValueError('Cần xác nhận văn bản và ảnh thuộc cùng một ca.')
    return 'text_xray' if text is not None and image is not None else 'xray' if image is not None else 'text'
