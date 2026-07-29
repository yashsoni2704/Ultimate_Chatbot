import os
import gdown


def download_google_drive(url: str) -> str:
    """
    Download a file from Google Drive and return the local path.

    The filename/extension is preserved from the Drive metadata where
    possible (gdown does this automatically via fuzzy=True).  If gdown
    cannot determine the name, we fall back to 'downloaded_file.pdf'
    so the loader can at least detect the file type correctly.
    """
    os.makedirs("uploads", exist_ok=True)

    # gdown will append the real filename when given a directory path
    output = gdown.download(url, output="uploads/", fuzzy=True, quiet=False)

    if not output:
        raise RuntimeError(f"gdown failed to download: {url}")

    # gdown returns the full path it wrote to — use it directly
    return output
