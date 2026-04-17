from fastapi import FastAPI, UploadFile, File, HTTPException, Form
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
import os
import shutil
import json
from datetime import datetime
from pathlib import Path

app = FastAPI(title="Private Cloud", version="1.0")

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
    for f in sorted(os.listdir(cat_path)):
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
    return {"status": "deleted", "filename": filename}

@app.post("/notes")
async def create_note(title: str = Form(...), content: str = Form(...)):
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_title = title.replace(" ", "_").lower()
    filename = f"{timestamp}_{safe_title}.json"
    filepath = STORAGE / "notes" / filename

    note = {
        "title": title,
        "content": content,
        "created": datetime.now().isoformat(),
    }

    with open(filepath, "w") as f:
        json.dump(note, f, indent=2)

    return {"status": "saved", "filename": filename, "note": note}


@app.get("/notes/{filename}")
def read_note(filename: str):

    filepath = STORAGE / "notes" / filename
    if not filepath.exists():
        raise HTTPException(404, "Note not found")
    with open(filepath) as f:
        return json.load(f)

@app.get("/status")
def server_status():

    import shutil as sh
    total, used, free = sh.disk_usage("/")
    total_files = sum(
        len(os.listdir(STORAGE / cat)) for cat in CATEGORIES
    )
    return {
        "status": "online",
        "storage": {
            "total_gb": round(total / (1024**3), 1),
            "used_gb": round(used / (1024**3), 1),
            "free_gb": round(free / (1024**3), 1),
        },
        "total_files": total_files,
    }

@app.get("/")
def root():
    return {"message": "Personal Cloud API is running", "docs": "/docs"}
