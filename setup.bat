@echo off
cd /d "%~dp0"
echo === Membuat virtual environment ===
if not exist .venv python -m venv .venv
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
echo === Menginstal PyTorch CUDA 12.4 (~2,5 GB) ===
python -m pip install torch torchaudio --index-url https://download.pytorch.org/whl/cu124
echo === Menginstal dependensi lain ===
python -m pip install -r requirements.txt
echo.
echo Selesai. Klik dua kali run.bat untuk menjalankan.
pause
