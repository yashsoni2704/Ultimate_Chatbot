import os
import re
from werkzeug.utils import secure_filename
from config import Config


def allowed_file(filename):
    """
    Check whether uploaded file is supported.
    """

    if "." not in filename:
        return False

    extension = filename.rsplit(".", 1)[1].lower()

    return extension in Config.ALLOWED_EXTENSIONS


def get_extension(file_path):
    """
    Return file extension.
    """

    return os.path.splitext(file_path)[1].lower()


def ensure_directories():
    """
    Create required directories.
    """

    os.makedirs(Config.UPLOAD_FOLDER, exist_ok=True)
    os.makedirs(Config.QDRANT_PATH, exist_ok=True)


def clean_filename(filename):
    """
    Secure uploaded filename.
    """

    return secure_filename(filename)


def is_google_drive_url(url):
    """
    Validate Google Drive URL.
    """

    patterns = [
        r"https://drive\.google\.com/file/d/.*",
        r"https://docs\.google\.com/.*"
    ]

    return any(re.match(pattern, url) for pattern in patterns)


def file_exists(path):
    """
    Check local file path.
    """

    return os.path.exists(path)


def get_filename(path):
    """
    Return filename from path.
    """

    return os.path.basename(path)


def success(message, **kwargs):
    """
    Standard success response.
    """

    response = {
        "status": "success",
        "message": message
    }

    response.update(kwargs)

    return response


def error(message):
    """
    Standard error response.
    """

    return {
        "status": "error",
        "message": message
    }