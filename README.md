# AI Translator

Penerjemah suara **real-time dua arah** untuk Windows, untuk Zoom, Google Meet, Teams, Discord, YouTube, dan aplikasi lain.
Semua proses berjalan **offline di GPU Anda**. Tidak ada audio yang dikirim ke internet.

```
DENGAR : suara aplikasi (WASAPI loopback) → Whisper → TranslateGemma 4B → subtitle melayang
BICARA : mic Anda → Whisper → TranslateGemma 4B → XTTS-v2 (suara tiruan Anda) → VB-Cable → Zoom/Meet
```

## Fitur

- **Subtitle langsung per kata**: seperti caption Google Meet. Kata yang diucapkan muncul ±0,7 detik kemudian,
  terjemahannya menyusul ±1 detik setelahnya, lalu dirapikan saat kalimat selesai. Tetap jalan walau ada musik latar (Silero VAD).
- **Subtitle terjemahan melayang**: selalu di atas aplikasi lain, bisa digeser dan diubah ukurannya,
  dan tidak ikut terlihat saat share screen.
- **Tangkap per-aplikasi**: terjemahkan hanya suara Zoom atau Chrome, sementara notifikasi dan musik diabaikan.
- **Bicara dengan suara sendiri**: ucapan Anda diterjemahkan lalu diucapkan ulang dengan tiruan suara Anda,
  dan dikirim ke rapat lewat virtual mic.
- **Offline**: Whisper, TranslateGemma (llama.cpp), dan XTTS-v2 sudah termasuk di installer.
  Mesin terjemahan juga bisa dipindah ke Ollama lokal atau di VPS.
- Transkrip setiap sesi otomatis disimpan sebagai file teks.

## Kebutuhan PC

| | Minimum |
|---|---|
| OS | Windows 11, atau Windows 10 64-bit (per-aplikasi butuh build 20348+) |
| GPU | NVIDIA, VRAM 6 GB, driver terbaru. Tanpa GPU tetap jalan di CPU, tapi lambat |
| RAM | 16 GB |
| Disk | ~10 GB |
| Lainnya | Headset disarankan untuk fitur Bicara. Virtual mic (VB-CABLE) sudah ikut terpasang lewat installer |

## Instalasi (pengguna)

1. Salin **kedua file installer** ke satu folder: `AI-Translator-Setup-1.0.0.exe` dan `AI-Translator-Setup-1.0.0-1.bin`.
   Flashdisk harus berformat NTFS atau exFAT, karena FAT32 tidak bisa menyimpan file di atas 4 GB.
2. Jalankan `AI-Translator-Setup-1.0.0.exe` → Next → Finish. Tidak perlu internet.
3. Pilihan **"Pasang virtual mic (VB-CABLE)"** sudah tercentang. Installer memasangnya, memberi nama **"AI Translator Mic"**,
   dan menyembunyikan perangkat VB-CABLE yang tidak dipakai. Setelah Finish, **restart PC** satu kali.

## Cara pakai

Jendela utama punya menu **Beranda** (kedua arah, transkrip langsung, kesiapan sistem), **Dengar**, **Bicara**,
**Subtitle**, **Riwayat** (cari, salin, ekspor .srt), **Pengaturan** (GPU/VRAM, model Whisper, mesin terjemahan, tema),
dan **Tentang**. Saat pertama kali dibuka, muncul **Panduan awal** (cek sistem, rekam suara, lisensi).

**Dengar (terjemahkan orang lain)**
1. Pilih **Tangkap dari**: *Semua suara*, atau *Hanya aplikasi: Zoom.exe / chrome.exe / ...*.
   Aplikasinya harus sudah terbuka. Klik ↻ untuk memuat ulang daftar.
2. Pilih bahasa sumber (atau *Deteksi otomatis*) dan bahasa tujuan, lalu klik **▶ Mulai**.

**Bicara (terjemahkan suara Anda)**
1. Centang fitur Bicara, pilih mikrofon, lalu klik **● Rekam 15 dtk** untuk membuat sampel suara.
2. Klik **▶ Mulai**. Di Zoom/Meet/Teams, pilih mikrofon **"AI Translator Mic"**.
   Kalau namanya masih "CABLE Output", klik **Rapikan perangkat VB-CABLE** di tab Bicara (butuh izin admin sekali).

Pengaturan, transkrip, sampel suara, dan log disimpan di `%APPDATA%\AI Translator`.

## Performa

Diukur dengan satu kalimat berdurasi 5,7 detik, di RTX 3050 6 GB dibandingkan dengan CPU saja (i5-12400F):

| Tahap | GPU | CPU saja |
|---|---|---|
| Whisper small (ucapan → teks) | 0,3 dtk | 1,6 dtk |
| TranslateGemma 4B Q4_K_M | 0,3–0,9 dtk | 1,1–3,3 dtk |
| **Dengar: sampai subtitle muncul** | **~1,2 dtk** setelah kalimat selesai | **~5 dtk** |
| **Dengar, subtitle langsung**: kata asli / terjemahan | **~0,7 dtk / ~1,5 dtk** setelah diucapkan | tidak tersedia |
| XTTS-v2: membuat 4 dtk suara | 2,6 dtk (real-time) | 12 dtk (patah-patah) |

VRAM total dengan semua fitur aktif (termasuk Windows) sekitar 5,9 GB.
Saat dibuka, aplikasi memeriksa GPU dan driver NVIDIA. Kalau tidak ada GPU NVIDIA, atau drivernya belum terpasang
atau terlalu lama (driver minimum 551.61 untuk CUDA 12.4), aplikasi menampilkan peringatan beserta tombol *Unduh driver NVIDIA*.
Model otomatis dijalankan di CPU kalau GPU tidak tersedia.

## Untuk developer

Butuh: Python 3.9 (64-bit), Git, NVIDIA driver, dan untuk membuat installer
[Inno Setup 6](https://jrsoftware.org/isinfo.php) (`winget install JRSoftware.InnoSetup`).

```bat
git clone https://github.com/<user>/ai-translator.git
cd ai-translator
setup.bat                                             :: .venv + PyTorch CUDA 12.4 + dependensi
.venv\Scripts\python.exe packaging\download_models.py --xtts   :: model + llama.cpp (~5 GB)
run.bat                                               :: jalankan dari source
.venv\Scripts\python.exe main.py --selftest           :: uji semua model tanpa UI (hasil di app.log)
powershell -ExecutionPolicy Bypass -File packaging\build.ps1   :: build .exe + installer
```

Model dan llama.cpp **tidak disimpan di git** karena ukurannya beberapa GB.
`download_models.py` menaruhnya di:

| Folder | Isi | Sumber |
|---|---|---|
| `models/translategemma/` | `translategemma-4b-it.Q4_K_M.gguf` | [mradermacher/translategemma-4b-it-GGUF](https://huggingface.co/mradermacher/translategemma-4b-it-GGUF) |
| `models/whisper/faster-whisper-small/` | Whisper small (CTranslate2) | [Systran/faster-whisper-small](https://huggingface.co/Systran/faster-whisper-small) |
| `models/whisper/faster-whisper-base/` | Whisper base, untuk teks sementara subtitle langsung | [Systran/faster-whisper-base](https://huggingface.co/Systran/faster-whisper-base) |
| `models/tts/` | XTTS-v2 (opsi `--xtts`, lisensi CPML) | Coqui |
| `vendor/vbcable/` | Paket resmi VB-CABLE Driver Pack 45 | [vb-audio.com/Cable](https://vb-audio.com/Cable/) |
| `vendor/llama/` | llama.cpp `b11344` win-cuda-12.4-x64 + cudart | [ggml-org/llama.cpp releases](https://github.com/ggml-org/llama.cpp/releases/tag/b11344) |

### Struktur kode

| File | Isi |
|---|---|
| `main.py` | Entry point, logging, `--selftest` |
| `app/config.py` | Pengaturan (`config.json`), path `APP_DIR` (read-only) dan `DATA_DIR` (bisa ditulis) |
| `app/audio_capture.py` | Loopback/mic via WASAPI, pemutar ke virtual mic, rekam sampel |
| `app/process_loopback.py` | Tangkap audio satu aplikasi (WASAPI process loopback, ctypes) |
| `app/audio_setup.py` | Merapikan VB-CABLE: ganti nama mic/speaker, nonaktifkan CABLE In 16ch (`--setup-audio`) |
| `app/gpu_check.py` | Deteksi GPU NVIDIA, versi driver, dan VRAM |
| `app/streaming.py` | Subtitle langsung: Silero VAD + Whisper base tiap 0,4 dtk (teks sementara), LocalAgreement untuk memfinalkan kalimat, Whisper small + TranslateGemma untuk teks final |
| `app/segmenter.py` | VAD berbasis energi, memotong audio per kalimat |
| `app/asr.py` · `app/translator.py` · `app/tts.py` | Whisper · TranslateGemma (llama-server / Ollama) · XTTS-v2 |
| `app/pipeline.py` | Sesi dua arah yang berbagi satu Whisper dan satu penerjemah |
| `app/ui/` | `main_window.py` (kerangka, sesi), `pages.py` (7 halaman), `widgets.py` (komponen kustom), `theme.py` (warna/QSS terang-gelap, font Inter), `wizard.py` (panduan awal), `overlay.py` (subtitle) |
| `app/history.py` · `app/autostart.py` | Membaca transkrip untuk Riwayat + ekspor .srt · mulai bersama Windows (`--tray`) |
| `packaging/` | Spec PyInstaller, script Inno Setup, build, ikon, unduh model |
| `mockup/` | Mockup HTML untuk desain UI berikutnya |

### Hal yang perlu diketahui
- **Muat `torch` sebelum `ctranslate2`.** Kalau urutannya terbalik, XTTS crash dengan error `cudnnGetLibConfig` (sudah ditangani di `asr.py`).
- llama-server untuk TranslateGemma wajib memakai `--no-jinja --chat-template gemma`. Prompt Gemma dibentuk manual lewat `/completion`.
- VRAM 6 GB hampir penuh, jadi llama-server memakai `-c 1024 -b 256 -ub 256 -fa on`.
- Jangan rebuild PyInstaller selama ada junction `build\dist\AI Translator\models` atau `vendor`.
  `rmtree` di Python 3.9 bisa mengikuti junction itu dan menghapus model asli. Lepas dulu dengan `cmd /c rmdir`.
- Simpan model sebagai file biasa (`local_dir=`), jangan memakai cache Hugging Face. Cache HF memakai symlink, dan symlink rusak saat dibundel.

Untuk Ollama di VPS: jalankan dengan `OLLAMA_HOST=0.0.0.0`, dan **batasi aksesnya** (firewall, VPN, atau reverse proxy dengan auth).

## Lisensi

Kode aplikasi: tentukan sendiri (misalnya MIT). Komponen pihak ketiga punya lisensi masing-masing, lihat [packaging/NOTICE.txt](packaging/NOTICE.txt):

- **XTTS-v2**: Coqui Public Model License, **hanya untuk penggunaan non-komersial**.
- **TranslateGemma**: Gemma Terms of Use.
- **VB-CABLE** (VB-Audio Software) adalah *donationware*. Paket resminya ikut di installer tanpa perubahan.
  Kalau bermanfaat, [dukung pembuatnya](https://vb-audio.com/Cable/). Sebelum didistribusikan luas, minta persetujuan VB-Audio dulu
  (readme paketnya mensyaratkan izin untuk *integrasi ke installer lain*).

Gunakan fitur peniru suara hanya untuk suara Anda sendiri, atau suara orang yang sudah memberi izin.
