import os
import gdown


def download_google_drive(url):

    os.makedirs("uploads", exist_ok=True)

    output = os.path.join("uploads", "downloaded_file")

    gdown.download(url, output, fuzzy=True)

    return output