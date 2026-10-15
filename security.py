import shutil
import stat
import zipfile
from pathlib import Path, PurePosixPath
from PIL import Image, UnidentifiedImageError

def safe_extract_zip(zip_path: Path, destination: Path):
    destination = Path(destination).resolve()
    destination.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path) as archive:
        for info in archive.infolist():
            name = info.filename
            if "\x00" in name or "\\" in name:
                raise ValueError("ZIP contains an invalid path.")
            rel = PurePosixPath(name)
            if rel.is_absolute() or ".." in rel.parts:
                raise ValueError("ZIP contains an unsafe path.")
            mode = (info.external_attr >> 16) & 0xFFFF
            if stat.S_ISLNK(mode):
                raise ValueError("ZIP symlinks are not allowed.")
            target = (destination / Path(*rel.parts)).resolve()
            if target != destination and destination not in target.parents:
                raise ValueError("ZIP path escapes the project folder.")
            if info.is_dir() or name.endswith("/"):
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(info, "r") as source, target.open("wb") as output:
                shutil.copyfileobj(source, output, 1024 * 1024)
    if not (destination / "index.html").is_file():
        raise ValueError("ZIP-এর root folder-এ index.html পাওয়া যায়নি.")

def validate_png(path: Path):
    try:
        with Image.open(path) as im:
            if im.format != "PNG":
                raise ValueError("Icon অবশ্যই PNG format হতে হবে.")
            im.verify()
        with Image.open(path) as im:
            if im.width < 1 or im.height < 1:
                raise ValueError("PNG icon invalid.")
    except (UnidentifiedImageError, OSError) as exc:
        raise ValueError("PNG icon পড়া যাচ্ছে না; অন্য PNG দিন.") from exc

def cleanup_path(path):
    if not path:
        return
    try:
        p = Path(path)
        if p.is_dir():
            shutil.rmtree(p, ignore_errors=True)
        elif p.exists():
            p.unlink()
    except OSError:
        pass
