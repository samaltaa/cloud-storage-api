from fastapi import FastAPI, UploadFile, File, HTTPException, Form, Request
from fastapi.responses import FileResponse, HTMLResponse, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from fastapi import APIRouter

import os
import shutil
import json
from datetime import datetime
from pathlib import Path

from cryptography.fernet import Fernet

app = FastAPI(title="Private Cloud", version="1.0")

# Static files and templates
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

STORAGE = Path("/home/chongzi/cloud/storage")
CATEGORIES = ["images", "notes", "datasets", "general"]

for cat in CATEGORIES:
    (STORAGE / cat).mkdir(parents=True, exist_ok=True)

#services 

"""
TODO: 
[]create service for resizing images 
[]create service to compress images
[X]create service for encryption 
[X]create service for decryption
[]create hashing service 
[]create service to allow multiple uploads
"""

#generate encryption key 
key = Fernet.generate_key()
#save key in a file
with open('encryption.key', 'wb') as f:
    f.write(key)

#encryption services 
def load_encrypt_key():
    with open('encryption.key', 'rb') as f:
        key = f.read()
    fernet = Fernet(key)
    return fernet

def encrypt_file_service(file_path: Path):
    fernet_key = load_encrypt_key()

    with open(file_path, 'rb') as f:
        original_file = f.read()

    encrypted_file = fernet_key.encrypt(original_file)
    #overwrite the original file encrypted data
    with open(file_path, 'wb') as f:
        f.write(encrypted_file)
    return encrypted_file

def decrypt_file_service(file_path: Path):
    fernet_key = load_encrypt_key()

    with open(file_path, 'rb') as f:
        encrypted_file = f.read()

    decrypted_file = fernet_key.decrypt(encrypted_file)
    decoded_decryption = decrypted_file.decode()

    return decoded_decryption


#enpoint logic services
def list_files_service() -> dict:
    result = {}
    total = 0 
    for cat in CATEGORIES:
        files = sorted(os.listdir(STORAGE / cat))
        result[cat] = files
        total += len(files)
    return {"total_files": total, "categories": result}

def list_categories_service(category: str) -> dict:
    cat_path = STORAGE / category
    files = []
    for file in sorted(os.listdir(cat_path), reverse=True):
        file_path = cat_path / file
        stat = os.stat(file_path)
        files.append({
            "name": file,
            "size_bytes": stat.st_size,
            "size_mb": round(stat.st_size / 1024 / 1024, 2),
            "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(),
        })
    return {"category": category, "count": len(files), "files": files}

def upload_service(category: str, file: UploadFile) -> dict:
    time_stamp = datetime.now().strftime()
    safe_name = file.filename.replace(" ", "_")  
    file_name = f"{time_stamp}_{safe_name}"
    file_path = STORAGE /category / file_name

    with open(file_path, "wb") as f:
        shutil.copyfilesobj(file.file, f)

    size = os.path.getsize(file_path)
    return {
        "status": "uploaded",
        "file_name": file_name,
        "categpory": category,
        "size_bytes": size,
        "size_mb": round(size / 1024 / 1024, 2)
    } 

def delete_service(category: str, file_name: str) -> dict:
    file_path = STORAGE / category / file_name

    if not file_path.exists():
        raise HTTPException(404, "File not found")
    os.remove(file_path)
    return Response(status_code=200, content="", media_type="text/html")

def get_path_service(category: str, file_name: str) -> Path:
    file_path = STORAGE / category / file_name

    if not file_path.exists():
        raise HTTPException(404, "File not found")
    return file_path

#routers v1, no logic just HTTP layer
api_v1 = APIRouter(prefix="/api/v1/files", tags=["files"])

def require_valid_category(category:str):
    #raise http exception
    if category not in CATEGORIES:
        raise HTTPException(400, f"Category must be one of: {CATEGORIES}")
    
@api_v1.get("")
def list_files():
    return list_files_service()

@api_v1.get("/{category}")
def list_category_files(category: str):
    require_valid_category(category)
    return list_categories_service(category)

@api_v1.post("/upload/{category}")
def upload_file(category: str, file: UploadFile = File(...)):
    require_valid_category(category)
    return upload_service(category, file)

@api_v1.get("/download/{category}/{filename}")
def download_file(category: str, file_name:str):

    require_valid_category(category)
    file_path = get_path_service(category, file_name)

    return FileResponse(file_path, file_name=file_name)

@api_v1.delete("/{category}/{file_name}")
def delete_file(category: str, file_name: str):
    require_valid_category(category)
    return delete_service(category, file_name)

#page routes
@api_v1.get("/home", response_class=HTMLResponse)
async def homepage(request: Request):
    data = list_files_service()
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "categories": CATEGORIES,
            "total_files": data.get("total_files", 0)
        }
    )


@api_v1.get("/category/{category}", response_class=HTMLResponse)
async def category_page(request: Request, category: str):
    require_valid_category(category)
    data = list_categories_service(category)
    files = sorted(data["files"], key=lambda x: x.get("modified", ""), reverse=True)
    return templates.TemplateResponse(
        request=request,
        name="category.html",
        context={
            "category": category,
            "files": files
        }
    )


app.include_router(api_v1)

@app.get("/api/v1/status")
def server_status():
    import shutil as sh
    total, used, free = sh.disk_usage("/")
    total_files = sum(len(os.listdir(STORAGE / cat)) for cat in CATEGORIES)
    return {
        "status": "online",
        "storage": {
            "total_gb": round(total / (1024**3), 1),
            "used_gb": round(used / (1024**3), 1),
            "free_gb": round(free / (1024**3), 1),
        },
        "total_files": total_files,
    }

@app.get("/api/v1/health")
def health():
    return {"message": "Personal Cloud API is running", "docs": "/docs"}

#prototype code

@app.get("/home", response_class=HTMLResponse)
async def homepage(request: Request):
    data = list_files()
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "categories": CATEGORIES,
            "total_files": data.get("total_files", 0)
        }
    )


@app.get("/category/{category}", response_class=HTMLResponse)
async def category_page(request: Request, category: str):
    if category not in CATEGORIES:
        raise HTTPException(status_code=400, detail="Invalid category")
    
    data = list_category_files(category)
    # Sort newest to oldest
    files = sorted(data["files"], key=lambda x: x.get("modified", ""), reverse=True)
    
    return templates.TemplateResponse(
        request=request,
        name="category.html",
        context={
            "category": category,
            "files": files
        }
    )

@app.post("/upload/{category}")
async def upload_file(category: str, file: UploadFile = File(...)):
    if category not in CATEGORIES:
        raise HTTPException(400, f"Category must be one of: {CATEGORIES}")
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_name = file.filename.replace(" ", "_")
    filename = f"{timestamp}_{safe_name}"
    filepath = STORAGE / category / filename
    
    with open(filepath, "wb") as f:
        shutil.copyfileobj(file.file, f)
    
    size = os.path.getsize(filepath)
    return {
        "status": "uploaded",
        "filename": filename,
        "category": category,
        "size_bytes": size,
        "size_mb": round(size / 1024 / 1024, 2),
    }


@app.get("/files")
def list_files():
    result = {}
    total = 0
    for cat in CATEGORIES:
        cat_path = STORAGE / cat
        files = sorted(os.listdir(cat_path))
        result[cat] = files
        total += len(files)
    return {"total_files": total, "categories": result}


@app.get("/files/{category}")
def list_category_files(category: str):
    if category not in CATEGORIES:
        raise HTTPException(400, f"Category must be one of: {CATEGORIES}")
    
    cat_path = STORAGE / category
    files = []
    for f in sorted(os.listdir(cat_path), reverse=True):   # newest first by filename
        filepath = cat_path / f
        stat = os.stat(filepath)
        files.append({
            "name": f,
            "size_bytes": stat.st_size,
            "size_mb": round(stat.st_size / 1024 / 1024, 2),
            "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(),
        })
    return {"category": category, "count": len(files), "files": files}


@app.get("/download/{category}/{filename}")
def download_file(category: str, filename: str):
    filepath = STORAGE / category / filename
    if not filepath.exists():
        raise HTTPException(404, "File not found")
    return FileResponse(filepath, filename=filename)


@app.delete("/delete/{category}/{filename}")
def delete_file(category: str, filename: str):
    filepath = STORAGE / category / filename
    if not filepath.exists():
        raise HTTPException(404, "File not found")
    os.remove(filepath)
    
    return Response(status_code=200, content="", media_type="text/html")


@app.get("/status")
def server_status():
    import shutil as sh
    total, used, free = sh.disk_usage("/")
    total_files = sum(len(os.listdir(STORAGE / cat)) for cat in CATEGORIES)
    return {
        "status": "online",
        "storage": {
            "total_gb": round(total / (1024**3), 1),
            "used_gb": round(used / (1024**3), 1),
            "free_gb": round(free / (1024**3), 1),
        },
        "total_files": total_files,
    }


@app.get("/health")
def root():
    return {"message": "Personal Cloud API is running", "docs": "/docs"}