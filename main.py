from fastapi import FastAPI, UploadFile, File, HTTPException, Request, APIRouter
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles

import os
import io
import csv
import json
import base64
import hashlib
import shutil
import subprocess
from datetime import datetime
from pathlib import Path

from PIL import Image
from cryptography.fernet import Fernet
from dotenv import load_dotenv
load_dotenv()

app = FastAPI(title="Private Cloud", version="2.0")

app.mount("/static", StaticFiles(directory="static"), name="static")
app.mount("/icons", StaticFiles(directory="icons"), name="icons")
templates = Jinja2Templates(directory="templates")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

STORAGE    = Path("storage")
CATEGORIES = ["images", "notes", "datasets", "general"]

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".tiff", ".webp"}
VIDEO_EXTENSIONS = {".mp4", ".mov", ".avi", ".mkv", ".webm", ".m4v"}

IMAGE_QUALITY  = 82
IMAGE_MAX_DIM  = 3840
THUMBNAIL_SIZE = (320, 320)

VIDEO_CRF     = 28
VIDEO_PRESET  = "fast"
VIDEO_CODEC   = "libx264"
AUDIO_CODEC   = "aac"
AUDIO_BITRATE = "128k"

for _cat in CATEGORIES:
    (STORAGE / _cat).mkdir(parents=True, exist_ok=True)

_SECRET = os.getenv("CLOUD_SECRET_KEY")

if not _SECRET:
    raise RuntimeError("CLOUD_SECRET_KEY missing. Add it to .env")

_key_bytes  = hashlib.sha256(_SECRET.encode()).digest()
_FERNET_KEY = base64.urlsafe_b64encode(_key_bytes)
_fernet     = Fernet(_FERNET_KEY)


def encrypt(data: bytes) -> bytes:
    return _fernet.encrypt(data)


def decrypt(data: bytes) -> bytes:
    try:
        return _fernet.decrypt(data)
    except Exception:
        raise ValueError("Decryption failed — wrong key or corrupted file.")


def file_svc_list_all() -> dict:
    result = {}
    total  = 0
    for cat in CATEGORIES:
        files = sorted(os.listdir(STORAGE / cat))
        result[cat] = files
        total += len(files)
    return {"total_files": total, "categories": result}


def file_svc_list_category(category: str) -> dict:
    cat_path = STORAGE / category
    files    = []
    for f in sorted(os.listdir(cat_path), reverse=True):
        filepath = cat_path / f
        stat     = filepath.stat()
        files.append({
            "name":       f,
            "size_bytes": stat.st_size,
            "size_mb":    round(stat.st_size / 1024 / 1024, 2),
            "modified":   datetime.fromtimestamp(stat.st_mtime).isoformat(),
        })
    return {"category": category, "count": len(files), "files": files}


def file_svc_upload(category: str, filename: str, data: bytes) -> dict:
    timestamp  = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_name  = filename.replace(" ", "_")
    final_name = f"{timestamp}_{safe_name}"
    filepath   = STORAGE / category / final_name

    encrypted = encrypt(data)
    filepath.write_bytes(encrypted)

    return {
        "filename":          final_name,
        "category":          category,
        "size_bytes":        len(data),
        "size_mb":           round(len(data) / 1024 / 1024, 2),
        "encrypted":         True,
        "stored_size_bytes": len(encrypted),
    }


def file_svc_read(category: str, filename: str) -> bytes:
    filepath = STORAGE / category / filename
    if not filepath.exists():
        raise FileNotFoundError(filename)
    return decrypt(filepath.read_bytes())


def file_svc_get_path(category: str, filename: str) -> Path:
    filepath = STORAGE / category / filename
    if not filepath.exists():
        raise FileNotFoundError(filename)
    return filepath


def file_svc_delete(category: str, filename: str) -> dict:
    filepath = STORAGE / category / filename
    if not filepath.exists():
        raise FileNotFoundError(filename)
    filepath.unlink()
    return {"deleted": filename, "category": category}


def image_svc_compress(data: bytes, original_filename: str) -> tuple[bytes, str]:
    img = Image.open(io.BytesIO(data))

    if img.mode in ("P", "LA"):
        img = img.convert("RGBA")
    elif img.mode not in ("RGB", "RGBA"):
        img = img.convert("RGB")

    w, h = img.size
    if max(w, h) > IMAGE_MAX_DIM:
        scale = IMAGE_MAX_DIM / max(w, h)
        img   = img.resize((int(w * scale), int(h * scale)), Image.LANCZOS)

    buf = io.BytesIO()
    img.save(buf, format="WEBP", quality=IMAGE_QUALITY, method=6)
    buf.seek(0)

    stem = Path(original_filename).stem
    return buf.read(), f"{stem}.webp"


def image_svc_decompress(data: bytes, target_format: str = "PNG") -> tuple[bytes, str]:
    img = Image.open(io.BytesIO(data))
    buf = io.BytesIO()
    fmt = target_format.upper()

    if fmt == "JPEG":
        img.convert("RGB").save(buf, format="JPEG", quality=95)
        media_type = "image/jpeg"
    else:
        img.save(buf, format="PNG", optimize=True)
        media_type = "image/png"

    buf.seek(0)
    return buf.read(), media_type


def image_svc_metadata_from_bytes(data: bytes, filepath: Path) -> dict:
    img  = Image.open(io.BytesIO(data))
    stat = filepath.stat()
    return {
        "filename":          filepath.name,
        "format":            img.format,
        "mode":              img.mode,
        "width":             img.width,
        "height":            img.height,
        "stored_size_bytes": stat.st_size,
        "stored_size_mb":    round(stat.st_size / 1024 / 1024, 2),
        "modified":          datetime.fromtimestamp(stat.st_mtime).isoformat(),
    }


def image_svc_thumbnail(data: bytes) -> bytes:
    img = Image.open(io.BytesIO(data))
    img.thumbnail(THUMBNAIL_SIZE, Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="WEBP", quality=70)
    buf.seek(0)
    return buf.read()


def notes_svc_encrypt(data: bytes) -> bytes:
    return encrypt(data)


def notes_svc_decrypt(data: bytes) -> bytes:
    return decrypt(data)


def notes_svc_preview(filepath: Path, chars: int = 500) -> str:
    raw       = filepath.read_bytes()
    plaintext = notes_svc_decrypt(raw)
    text      = plaintext.decode("utf-8", errors="replace")
    return text[:chars] + ("…" if len(text) > chars else "")


def dataset_svc_preview(data: bytes, filename: str, rows: int = 10) -> dict:
    preview_rows: list[dict] = []
    headers: list[str]       = []
    total = 0

    text_io = io.StringIO(data.decode("utf-8", errors="replace"))
    reader  = csv.DictReader(text_io)
    headers = list(reader.fieldnames or [])
    for row in reader:
        total += 1
        if len(preview_rows) < rows:
            preview_rows.append(dict(row))

    return {
        "filename":     filename,
        "headers":      headers,
        "column_count": len(headers),
        "total_rows":   total,
        "preview_rows": len(preview_rows),
        "rows":         preview_rows,
    }


def _stream_bytes(data: bytes, chunk_size: int = 65536):
    buf = io.BytesIO(data)
    while True:
        chunk = buf.read(chunk_size)
        if not chunk:
            break
        yield chunk


def general_svc_is_video(filename: str) -> bool:
    return Path(filename).suffix.lower() in VIDEO_EXTENSIONS


def general_svc_compress_video(input_path: Path, output_path: Path) -> dict:
    cmd = [
        "ffmpeg", "-y",
        "-i",        str(input_path),
        "-c:v",      VIDEO_CODEC,
        "-crf",      str(VIDEO_CRF),
        "-preset",   VIDEO_PRESET,
        "-c:a",      AUDIO_CODEC,
        "-b:a",      AUDIO_BITRATE,
        "-movflags", "+faststart",
        str(output_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg failed:\n{result.stderr[-600:]}")

    original_size   = input_path.stat().st_size
    compressed_size = output_path.stat().st_size
    saved_pct       = round((1 - compressed_size / original_size) * 100, 1) if original_size else 0
    return {
        "original_size_mb":   round(original_size   / 1024 / 1024, 2),
        "compressed_size_mb": round(compressed_size / 1024 / 1024, 2),
        "saved_percent":      saved_pct,
        "codec":              f"{VIDEO_CODEC} / {AUDIO_CODEC}",
        "crf":                VIDEO_CRF,
    }


def status_svc_disk_usage() -> dict:
    total, used, free = shutil.disk_usage(STORAGE)
    per_category      = {}
    for cat in CATEGORIES:
        cat_path  = STORAGE / cat
        cat_files = [f for f in cat_path.iterdir() if f.is_file()]
        cat_size  = sum(f.stat().st_size for f in cat_files)
        per_category[cat] = {
            "file_count": len(cat_files),
            "size_bytes": cat_size,
            "size_mb":    round(cat_size / 1024 / 1024, 2),
        }
    return {
        "disk_total_gb":       round(total / 1024 ** 3, 2),
        "disk_used_gb":        round(used  / 1024 ** 3, 2),
        "disk_free_gb":        round(free  / 1024 ** 3, 2),
        "disk_used_percent":   round(used  / total * 100, 1),
        "storage_by_category": per_category,
    }


def _require_category(category: str):
    if category not in CATEGORIES:
        raise HTTPException(status_code=404, detail=f"Unknown category: '{category}'")


def _category_counts() -> dict[str, int]:
    return {cat: len(os.listdir(STORAGE / cat)) for cat in CATEGORIES}


@app.get("/", response_class=HTMLResponse)
async def root_redirect(request: Request):
    counts = _category_counts()
    total  = sum(counts.values())
    return templates.TemplateResponse(request=request, name="index.html", context={"categories": CATEGORIES, "total_files": total, "category_counts": counts})


@app.get("/home", response_class=HTMLResponse)
async def homepage(request: Request):
    counts = _category_counts()
    total  = sum(counts.values())
    return templates.TemplateResponse(request=request, name="index.html", context={"categories": CATEGORIES, "total_files": total, "category_counts": counts})


@app.get("/category/{category}", response_class=HTMLResponse)
async def category_page(request: Request, category: str):
    _require_category(category)
    data = file_svc_list_category(category)
    return templates.TemplateResponse(request=request, name="category.html", context={"category": category, "files": data["files"]})


@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard_page(request: Request):
    counts = _category_counts()
    total  = sum(counts.values())
    disk   = status_svc_disk_usage()
    chart_counts = [disk["storage_by_category"][c]["file_count"] for c in CATEGORIES]
    chart_labels = [c.capitalize() for c in CATEGORIES]
    return templates.TemplateResponse(request=request, name="dashboard.html", context={"categories": CATEGORIES, "total_files": total, "disk": disk, "chart_counts_json": json.dumps(chart_counts), "chart_labels_json": json.dumps(chart_labels)})


@app.get("/files")
def list_all_files():
    return file_svc_list_all()


@app.get("/files/{category}")
def list_category_files(category: str):
    _require_category(category)
    return file_svc_list_category(category)


@app.post("/upload/{category}")
async def upload_file(category: str, file: UploadFile = File(...)):
    _require_category(category)
    data = await file.read()
    return file_svc_upload(category, file.filename, data)


@app.get("/download/{category}/{filename}")
def download_file(category: str, filename: str):
    _require_category(category)
    try:
        data = file_svc_read(category, filename)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="File not found")
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    return Response(content=data, media_type="application/octet-stream")


@app.delete("/delete/{category}/{filename}")
def delete_file(category: str, filename: str):
    _require_category(category)
    try:
        return file_svc_delete(category, filename)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="File not found")


@app.get("/status")
def status():
    return status_svc_disk_usage()


v1 = APIRouter(prefix="/api/v1", tags=["v1"])


@v1.post("/images/upload", summary="Upload image → WebP compress → encrypt → store")
async def v1_upload_image(file: UploadFile = File(...)):
    ext = Path(file.filename).suffix.lower()
    if ext not in IMAGE_EXTENSIONS:
        raise HTTPException(
            status_code=415,
            detail=f"Unsupported image type '{ext}'. Accepted: {sorted(IMAGE_EXTENSIONS)}",
        )
    raw = await file.read()

    try:
        compressed, new_name = image_svc_compress(raw, file.filename)
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"Image processing failed: {e}")

    result = file_svc_upload("images", new_name, compressed)
    result["original_size_kb"]   = round(len(raw)        / 1024, 1)
    result["compressed_size_kb"] = round(len(compressed) / 1024, 1)
    result["saved_percent"]      = round((1 - len(compressed) / len(raw)) * 100, 1)
    result["stored_format"]      = "webp"
    return result


@v1.get("/images/{filename}", summary="Decrypt → decode WebP → return PNG/JPEG")
def v1_get_image(filename: str, format: str = "png"):
    try:
        data = file_svc_read("images", filename)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Image not found")
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    try:
        decoded, media_type = image_svc_decompress(data, target_format=format.upper())
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"Decode failed: {e}")

    return Response(content=decoded, media_type=media_type)


@v1.get("/images/{filename}/thumbnail", summary="Decrypt → 320×320 WebP thumbnail")
def v1_image_thumbnail(filename: str):
    try:
        data = file_svc_read("images", filename)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Image not found")
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    return Response(content=image_svc_thumbnail(data), media_type="image/webp")


@v1.get("/images/{filename}/meta", summary="Image dimensions, format, size")
def v1_image_metadata(filename: str):
    try:
        path = file_svc_get_path("images", filename)
        data = file_svc_read("images", filename)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Image not found")
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    return image_svc_metadata_from_bytes(data, path)


@v1.get("/images", summary="List all stored images")
def v1_list_images():
    return file_svc_list_category("images")


@v1.delete("/images/{filename}")
def v1_delete_image(filename: str):
    try:
        return file_svc_delete("images", filename)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Image not found")


@v1.post("/notes/upload", summary="Upload note → encrypt → store")
async def v1_upload_note(file: UploadFile = File(...)):
    data      = await file.read()
    encrypted = notes_svc_encrypt(data)
    enc_name  = file.filename + ".enc"

    timestamp  = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_name  = enc_name.replace(" ", "_")
    final_name = f"{timestamp}_{safe_name}"
    filepath   = STORAGE / "notes" / final_name
    filepath.write_bytes(encrypted)

    return {
        "filename":             final_name,
        "category":             "notes",
        "encrypted":            True,
        "original_size_bytes":  len(data),
        "encrypted_size_bytes": len(encrypted),
        "size_mb":              round(len(encrypted) / 1024 / 1024, 2),
    }


@v1.get("/notes/{filename}", summary="Decrypt note → plaintext")
def v1_get_note(filename: str):
    try:
        path = file_svc_get_path("notes", filename)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Note not found")

    try:
        plaintext = notes_svc_decrypt(path.read_bytes())
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    return Response(content=plaintext, media_type="text/plain; charset=utf-8")


@v1.get("/notes/{filename}/preview", summary="Decrypted preview (first N chars)")
def v1_note_preview(filename: str, chars: int = 500):
    try:
        path = file_svc_get_path("notes", filename)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Note not found")

    try:
        preview = notes_svc_preview(path, chars)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    return {"filename": filename, "preview": preview, "chars_shown": min(chars, len(preview))}


@v1.get("/notes", summary="List all stored notes")
def v1_list_notes():
    return file_svc_list_category("notes")


@v1.delete("/notes/{filename}")
def v1_delete_note(filename: str):
    try:
        return file_svc_delete("notes", filename)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Note not found")


@v1.post("/datasets/upload", summary="Upload dataset → encrypt → store")
async def v1_upload_dataset(file: UploadFile = File(...)):
    data   = await file.read()
    result = file_svc_upload("datasets", file.filename, data)
    return result


@v1.get("/datasets/{filename}/preview", summary="Decrypt → preview first N rows (CSV only)")
def v1_dataset_preview(filename: str, rows: int = 10):
    try:
        data = file_svc_read("datasets", filename)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Dataset not found")
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    if not filename.lower().endswith(".csv"):
        raise HTTPException(status_code=415, detail="Preview is only available for .csv files")

    return dataset_svc_preview(data, filename, rows)


@v1.get("/datasets/{filename}/download", summary="Decrypt → streaming download")
def v1_dataset_download(filename: str):
    try:
        data = file_svc_read("datasets", filename)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Dataset not found")
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    return StreamingResponse(
        _stream_bytes(data),
        media_type="application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@v1.get("/datasets", summary="List all stored datasets")
def v1_list_datasets():
    return file_svc_list_category("datasets")


@v1.delete("/datasets/{filename}")
def v1_delete_dataset(filename: str):
    try:
        return file_svc_delete("datasets", filename)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Dataset not found")


@v1.post("/general/upload", summary="Upload file; videos → H.264 compress → encrypt → store")
async def v1_upload_general(file: UploadFile = File(...)):
    data     = await file.read()
    filename = file.filename

    if general_svc_is_video(filename):
        tmp_in   = STORAGE / "general" / f"_tmp_in_{filename}"
        stem     = Path(filename).stem
        out_name = f"{stem}_compressed.mp4"
        tmp_out  = STORAGE / "general" / f"_tmp_out_{out_name}"

        try:
            tmp_in.write_bytes(data)
            stats = general_svc_compress_video(tmp_in, tmp_out)
            compressed_data = tmp_out.read_bytes()
        except RuntimeError as e:
            raise HTTPException(status_code=422, detail=str(e))
        finally:
            tmp_in.unlink(missing_ok=True)
            tmp_out.unlink(missing_ok=True)

        result = file_svc_upload("general", out_name, compressed_data)
        result.update(stats)
        result["compressed"] = True
        return result

    result = file_svc_upload("general", filename, data)
    result["compressed"] = False
    return result


@v1.get("/general/{filename}", summary="Decrypt → stream video / download file")
def v1_get_general(filename: str):
    try:
        data = file_svc_read("general", filename)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="File not found")
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    if general_svc_is_video(filename):
        return StreamingResponse(
            _stream_bytes(data),
            media_type="video/mp4",
            headers={"Content-Disposition": f'inline; filename="{filename}"'},
        )
    return Response(content=data, media_type="application/octet-stream")


@v1.get("/general", summary="List all general files")
def v1_list_general():
    return file_svc_list_category("general")


@v1.delete("/general/{filename}")
def v1_delete_general(filename: str):
    try:
        return file_svc_delete("general", filename)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="File not found")


@v1.get("/status", summary="Disk usage per category + total disk stats")
def v1_status():
    return status_svc_disk_usage()


app.include_router(v1)