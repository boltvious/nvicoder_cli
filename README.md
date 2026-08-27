# nvicoder

CLI coding agent ala **Claude Code**, tapi "otaknya" pakai model dari
**NVIDIA NIM API** (endpoint yang kompatibel dengan format OpenAI). Bisa jalan
di terminal, baca/tulis/edit file, jalankan command shell, dan menyelesaikan
task coding secara agentic (loop: pikir → panggil tool → lihat hasil →
ulangi sampai selesai).

## Cara Kerja (Arsitektur Singkat)

Claude Code (dan tool sejenis seperti Cursor Agent, Aider, dsb) pada
dasarnya adalah **loop sederhana**, bukan sihir:

1. Kirim riwayat percakapan + system prompt + daftar "tools" (fungsi yang
   boleh dipanggil model: baca file, tulis file, jalankan shell, dst) ke LLM.
2. LLM membalas salah satu dari dua hal:
   - Teks jawaban biasa → tampilkan ke user, loop selesai.
   - Satu atau lebih **tool_call** (mis. `read_file(path="main.py")`) →
     Python yang menjalankan fungsi itu betulan di disk, lalu hasilnya
     dikirim balik ke LLM sebagai pesan role `"tool"`.
3. Ulangi langkah 2 sampai LLM tidak minta tool lagi (berarti sudah selesai)
   atau limit iterasi tercapai.

Yang membedakan implementasi bagus vs. asal-asalan biasanya bukan di
loop-nya, tapi di: **kualitas tool** (edit_file yang presisi, bukan cuma
overwrite total), **system prompt** yang disiplin, **keamanan** (konfirmasi
sebelum command berbahaya), dan **pemilihan model** yang tepat untuk
tugasnya. `nvicoder` mengimplementasikan semua bagian itu dengan sederhana
supaya gampang kamu modifikasi sendiri.

File penting:

| File | Isi |
|---|---|
| `nvicoder/agent.py` | Loop agentic inti + streaming + rekonstruksi tool_call |
| `nvicoder/tools.py` | Definisi & implementasi tool (read/write/edit file, shell, search) |
| `nvicoder/config.py` | Pemetaan level "effort" → model NVIDIA NIM |
| `nvicoder/cli.py` | Entry point, REPL, slash command (`/effort`, `/model`, dst) |
| `nvicoder/ui.py` | Print warna/format terminal |

## Arsitektur Constitutional AI Critic

**Update Terbaru**: Arsitektur dual-model diubah dari Chain-of-Thought reasoning menjadi **Constitutional AI self-critique**.

```
BEFORE:
User → Reasoning Model (Nemotron Ultra) → Plan → Assistant Model (Muse) → Execute → Output

AFTER (Current):
User → Assistant Model (Muse) → Execute → Output → Critic Model (Nemotron Ultra) → Constitutional Evaluation → Output + Critique
```

**Keuntungan:**
- ✅ Output dievaluasi secara otomatis terhadap Constitution (HARMLESS > HONEST > HELPFUL)
- ✅ Critique transparan untuk user
- ✅ Model critic menggunakan `nvidia/nemotron-3-ultra-550b-a55b` untuk evaluasi mendalam
- ✅ Assistant fokus eksekusi, critic fokus validasi etika & keamanan

### Konfigurasi Dual-Model

```bash
export NVICODER_DUAL_MODEL=true
export NVICODER_CRITIC_MODEL="nvidia/nemotron-3-ultra-550b-a55b"
export NVICODER_ASSISTANT_MODEL="meta/muse-glimmer-30b"
```

## Instalasi

```bash
cd nvicoder
pip install -e .
# atau tanpa install package: pip install -r requirements.txt
```

## API Key

1. Buat akun & ambil API key gratis di https://build.nvidia.com (klik model
   apa saja → "Get API Key"). Key berformat `nvapi-...`.
2. Set sebagai environment variable:

```bash
export NVIDIA_API_KEY="nvapi-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
```

## Menjalankan

```bash
# mode interaktif (REPL), default effort=medium
nvicoder

# langsung set effort dari awal
nvicoder --effort high

# mode satu-kali (non-interaktif), cocok untuk script/CI
nvicoder --effort high "refactor fungsi parse_config di config.py biar lebih ringkas"

# kalau belum di-install, bisa langsung:
python -m nvicoder.cli --effort high
```

Perintah dalam REPL:

```
/help              daftar perintah
/effort <level>    ganti effort: low | medium | high
/model <nama>      override model NVIDIA NIM manual, misal qwen/qwen3.5-122b-a10b
/models [all]      lihat daftar model dari API key kamu, bisa pilih langsung dari nomor
/clear             mulai sesi baru (hapus riwayat)
/yolo              toggle auto-approve semua run_command (hati-hati!)
/config            lihat file config.toml aktif & setting resolved
/exit              keluar
```

`/models` manggil `models.list()` langsung ke API key yang lagi kamu
pakai — berguna kalau lupa nama model persis, atau mau lihat model baru
yang baru dirilis NVIDIA tanpa buka browser. Defaultnya cuma nampilin
model yang namanya kelihatan relevan buat coding (mengandung kata
"instruct"/"chat"/"coder"/dst), biar nggak ketimbun ratusan model
TTS/vision/embedding yang tidak relevan. Pakai `/models all` buat lihat
daftar lengkap tanpa filter. Ketik nomornya buat langsung pakai model itu
di sesi sekarang (efeknya sama seperti `/model <nama>`, cuma nggak perlu
ngetik ID model yang panjang secara manual).

## Soal "Effort" (cepat vs akurat)

`nvicoder` tidak punya parameter "reasoning effort" resmi seperti model
OpenAI o-series — sebagai gantinya, effort diimplementasikan dengan
**memilih model + parameter yang berbeda** (lihat `nvicoder/config.py`):

| Effort | Model default | Kapan dipakai |
|---|---|---|
| `low` | `meta/llama-3.1-8b-instruct` | Task kecil, edit sederhana, butuh cepat |
| `medium` | `meta/llama-3.3-70b-instruct` | Default, seimbang |
| `high` | `nvidia/nemotron-3-super-120b-a12b` | Task kompleks/multi-file, butuh perencanaan lebih dalam |

Semua bisa kamu override lewat environment variable
(`NVICODER_MODEL_LOW`, `NVICODER_MODEL_MEDIUM`, `NVICODER_MODEL_HIGH`) atau
langsung `--model nama/model-lain` / `/model` saat runtime.

**Penting:** katalog model NVIDIA NIM berubah cukup sering, dan tidak
semua model mendukung tool/function calling. Sebelum memakai model
tertentu untuk `nvicoder`, cek dulu model card-nya di
https://build.nvidia.com/models — cari label "Function Calling" / "Tool
Calling" / "agentic". Kalau model yang kamu pilih ternyata tidak
mendukung tool calling, respons tool_calls akan selalu kosong dan agent
tidak akan pernah menyentuh file — kalau itu terjadi, ganti model.

Model lain yang sering disebut cocok untuk coding-agent per pertengahan
2026 (cek ketersediaan & harga terbaru sendiri): `deepseek-ai/deepseek-v3.2`,
`qwen/qwen3.5-122b-a10b`, `zhipuai/glm-4.7`,
`nvidia/llama-3.1-nemotron-ultra-253b-v1`, `mistralai/mistral-nemotron`.

## Mengedit "Kepribadian"/Kedisiplinan Agent (`prompt.md`)

System prompt-nya **tidak** ditanam di kode Python — ada di file terpisah
`nvicoder/prompt.md`, supaya gampang kamu ubah tanpa sentuh logic. Ini
tempat paling berpengaruh untuk bikin model open-source terasa "lebih
pintar", karena model kecil/menengah jauh lebih bergantung pada instruksi
eksplisit dibanding model besar.

Prompt bawaan sudah mencakup: urutan prioritas kalau instruksi bentrok,
alur wajib Pahami→Rencanakan→Eksekusi→Laporkan, aturan spesifik per tool,
cara pulih dari error tanpa infinite-loop, dan batasan keamanan. Silakan
edit langsung filenya untuk menyesuaikan gaya kerja (mis. tambah aturan
"selalu tulis unit test setelah nambah fungsi baru", atau "selalu jalankan
linter sebelum lapor selesai").

Untuk pakai prompt lain tanpa mengubah file bawaan:

```bash
nvicoder --prompt-file /path/ke/prompt-custom.md
```

Beberapa hal yang biasanya paling menambah "kepintaran" model kecil di
prompt:
- **Instruksi eksplisit, bukan implisit** — model kecil sering tidak
  menangkap norma tak tertulis (mis. "jangan overwrite file tanpa baca
  dulu") kalau tidak ditulis gamblang.
- **Urutan prioritas yang jelas** kalau ada instruksi yang berpotensi
  bentrok, supaya modelnya tidak "bingung" pilih mana yang menang.
- **Contoh format keluaran yang diinginkan** (few-shot) — kalau kamu mau
  gaya laporan akhir yang konsisten, tambahkan 1 contoh singkat di
  `prompt.md`.
- **Kondisi berhenti yang eksplisit** ("jangan ulangi tool call yang
  sama persis", "berhenti setelah gagal 2-3x") — ini yang paling efektif
  mencegah model kecil terjebak loop memanggil tool yang sama berulang.

## Config File (biar tidak perlu ketik `--effort` tiap kali)

Selain env var, `nvicoder` juga baca setting dari file **TOML** — pola yang
sama seperti `ruff`, `black`, atau `pytest` (config lewat `pyproject.toml`
atau file `.toml` khusus).

Contoh paling gampang: copy `nvicoder.example.toml` ke project kamu, rename
jadi `nvicoder.toml`:

```toml
# nvicoder.toml — taruh di root project
effort = "high"
yolo = false
# model = "qwen/qwen3.5-122b-a10b"     # opsional, override manual
# prompt_file = "./docs/prompt.md"     # opsional, system prompt kustom project ini
```

Habis itu tinggal `nvicoder` biasa (tanpa flag) di dalam folder itu — setting
otomatis kepakai. Kalau project kamu sudah punya `pyproject.toml` sendiri
(project Python lain, bukan nvicoder), section yang sama bisa ditaruh
langsung di sana di bawah `[tool.nvicoder]`, tidak perlu file terpisah:

```toml
[tool.nvicoder]
effort = "high"
```

### Model berbeda per tier effort (`[models]`)

`model = "..."` di atas nge-override **semua** tier sekaligus (effort
jadi cuma soal kecepatan streaming, bukan pilihan model lagi). Kalau
maunya tiap tier tetap punya model masing-masing tapi kamu mau pilih
sendiri modelnya (bukan default bawaan nvicoder), pakai section `[models]`:

```toml
# nvicoder.toml
effort = "medium"

[models]
low = "meta/llama-3.1-8b-instruct"
medium = "qwen/qwen3.5-122b-a10b"
high = "nvidia/nemotron-3-super-120b-a12b"
```

Cara dapetin nama model yang persis: ketik `/models` di REPL (lihat
bagian "Perintah dalam REPL" di bawah), pilih dari daftar yang muncul,
lalu copy ID-nya ke sini. Tier yang tidak kamu sebutkan di `[models]`
tetap pakai default bawaan nvicoder — jadi boleh cuma override satu tier
aja kalau yang lain sudah pas.

**Sumber config & prioritas** (yang di atas menang kalau bentrok):

1. Flag CLI eksplisit (`--effort`, `--model`, `--yolo`/`--no-yolo`, dst)
2. `./nvicoder.toml` di folder kerja saat ini (project)
3. `[tool.nvicoder]` di `./pyproject.toml` di folder kerja saat ini (project)
4. `~/.config/nvicoder/config.toml` (global, berlaku ke semua project —
   `%APPDATA%\nvicoder\config.toml` di Windows)
5. Environment variable (`NVICODER_EFFORT`, `NVICODER_MODEL_LOW/MEDIUM/HIGH`)
6. Default bawaan di `config.py`

Ketik `/config` di dalam REPL untuk lihat file config mana saja yang
kebaca, model yang aktif di tiap tier (low/medium/high), dan resolved
setting lainnya saat itu.

⚠️ `NVIDIA_API_KEY` **sengaja tidak bisa** di-set lewat file TOML manapun
— tetap harus environment variable, supaya tidak ada risiko API key
ke-commit tidak sengaja ke git bareng `nvicoder.toml`.

## Pengalaman Pertama Kali (Onboarding)

Kamu tidak perlu setup manual sama sekali sebelum pakai — cukup `cd` ke
project mana pun lalu ketik `nvicoder`. Alurnya:

1. **Cek API key** — urutan: env var `NVIDIA_API_KEY` → key tersimpan di
   `~/.config/nvicoder/credentials.json` → kalau dua-duanya kosong, wizard
   interaktif akan muncul: minta kamu paste key (input disembunyikan),
   validasi key itu dengan memanggil `models.list()` ke NVIDIA, lalu
   opsional menampilkan model apa saja yang tersedia di key kamu supaya
   bisa pilih default untuk effort `medium`. Di akhir, kamu ditanya mau
   simpan key itu ke disk atau tidak.
2. **Trust folder** — mirip Claude Code: pertama kali `nvicoder` dijalankan
   di sebuah folder, akan muncul prompt "Percaya folder ini?" karena
   nvicoder bisa baca/tulis/hapus file dan jalankan command shell di situ.
   Jawab `y` sekali, dan folder itu (path absolut, resolved lewat
   `os.path.realpath`) akan diingat permanen — tidak ditanya lagi di
   folder yang sama.

```
$ cd ~/project-baru
$ nvicoder
Selamat datang di nvicoder!
Belum ada NVIDIA_API_KEY yang terdeteksi (env var ataupun tersimpan).
Ambil API key gratis di https://build.nvidia.com ...
Paste API key (nvapi-...), input disembunyikan saat diketik: ****
Memvalidasi key... OK (114 model terlihat di key ini)

Beberapa model yang tersedia di key kamu:
  1. meta/llama-3.3-70b-instruct
  2. nvidia/nemotron-3-super-120b-a12b
  ...
  0. Lewati, pakai default bawaan (meta/llama-3.3-70b-instruct)
Pilih model default untuk effort=medium [0]: 0

Simpan key ini di ~/.config/nvicoder supaya tidak perlu input ulang lain kali? [Y/n]: y
Tersimpan di ~/.config/nvicoder/credentials.json.

⚠ Folder ini belum pernah dipercaya sebelumnya:
  /home/kamu/project-baru

Di dalam folder ini, nvicoder akan bisa:
  - membaca & menulis file (termasuk menimpa/menghapus isi file)
  - menjalankan command shell (selalu minta konfirmasi kecuali --yolo)

Percaya folder ini? [y/N]: y
OK, folder ini akan diingat — tidak akan ditanya lagi.

nvicoder — coding agent (NVIDIA NIM backend)
effort=medium  model=meta/llama-3.3-70b-instruct
>
```

Kali berikutnya di folder yang sama, langsung masuk ke prompt `>` tanpa
pertanyaan apapun.

**Flag terkait onboarding:**

| Flag | Fungsi |
|---|---|
| `-y`, `--yes` | Auto-jawab "ya" untuk prompt trust folder (buat CI/script non-interaktif) |
| `--logout` | Hapus API key tersimpan di `~/.config/nvicoder`, lalu keluar |
| `--untrust` | Cabut kepercayaan folder saat ini, lalu keluar (akan ditanya lagi) |

**Keamanan penyimpanan key:** kalau kamu pilih "simpan", key tersimpan
**plaintext** di `~/.config/nvicoder/credentials.json` dengan permission
file `600` (cuma bisa dibaca/ditulis pemilik file). Ini di luar folder
project mana pun, jadi tidak akan pernah ke-commit ke git secara tidak
sengaja — beda dengan `nvicoder.toml` project-level yang memang sengaja
**tidak pernah** menerima `api_key` sama sekali (lihat bagian Config File
di atas). Kalau kamu lebih nyaman key tidak pernah menyentuh disk sama
sekali, jawab "n" saat ditanya simpan, atau selalu pakai env var
`NVIDIA_API_KEY` (yang otomatis selalu menang lebih dulu daripada file
tersimpan).

## Melanjutkan Sesi (`--resume`)

Riwayat percakapan otomatis tersimpan ke `.nvicoder/sessions/<uuid>.json` di
dalam project — sekali per turn selesai (autosave, jaga-jaga kalau
terminal ke-close paksa), dan eksplisit saat `/exit`/`/quit`/Ctrl+D:

```
> /exit

Sesi tersimpan (95784ec9-b93c-407c-a09b-5adffae06620).
Lanjutkan lagi lain kali dengan: nvicoder --resume 95784ec9-b93c-407c-a09b-5adffae06620
```

Lain kali, di folder project yang sama:

```bash
nvicoder --resume 95784ec9-b93c-407c-a09b-5adffae06620
# atau pakai prefix pendek asal unik, mirip short-hash git:
nvicoder --resume 95784ec9
```

Lupa ID-nya? Lihat semua sesi tersimpan di project ini:

```bash
nvicoder --list-sessions
```
atau dari dalam REPL yang sedang jalan, ketik `/sessions`.

Beberapa detail penting:

- **Sesi kosong tidak tersimpan** — kalau kamu buka `nvicoder` terus langsung
  `/exit` tanpa ngobrol apa-apa, tidak ada file yang dibuat (menghindari
  folder `sessions/` penuh entri kosong tak berguna).
- **Effort/model ikut ke-resume** — kalau sesi yang kamu resume terakhir
  pakai `--effort high`, resume-nya otomatis pakai `high` lagi juga,
  KECUALI kamu eksplisit override (`nvicoder --resume <id> --effort low`
  tetap pakai `low`, flag CLI selalu menang).
- **Resume meng-update sesi yang sama**, bukan bikin sesi baru — jadi
  kamu bisa resume→lanjut ngobrol→exit→resume lagi berkali-kali, riwayat
  di file yang sama terus bertambah, ID-nya tidak berubah.
- **Per-project, bukan global** — sesi dari folder A tidak akan muncul
  kalau kamu jalankan `--list-sessions` dari folder B, karena riwayat
  biasanya mereferensikan file/path yang relatif ke project itu.
- Token counter (`session_tokens`) juga ikut ke-resume, jadi angka `sesi:`
  di baris `[tokens]` melanjutkan akumulasi dari sebelumnya, bukan reset
  ke 0.

⚠️ Folder `.nvicoder/sessions/` (sama seperti `.nvicoder/logs/`) sebaiknya
masuk `.gitignore` — isinya riwayat percakapan penuh (termasuk isi file
yang sempat dibaca/ditulis lewat tool), jadi bisa berisi hal sensitif
tergantung apa yang kamu kerjakan.

## Command Long-Running (dev server, watch mode)

Command kayak `flutter run`, `npm run dev`, `next dev`, `uvicorn --reload`
memang **didesain jalan terus** — beda dengan `pytest` atau `git status`
yang exit sendiri setelah selesai. Kalau dijalankan dengan cara biasa
(blocking + timeout), agent akan nyangkut menunggu sampai timeout habis
tanpa hasil apa-apa.

`nvicoder` sekarang mendeteksi pola command seperti ini (lihat
`LONG_RUNNING_HINTS` di `tools.py`) dan menawarkan tiga pilihan saat minta
konfirmasi:

```
[nvicoder] Command ini kelihatan seperti proses long-running (dev server/watch mode)
yang TIDAK AKAN SELESAI SENDIRI:
  $ flutter run
  Jalankan di background (b, disarankan), paksa foreground dengan timeout (f),
  selalu izinkan sesi ini (a), atau batal? [b/f/a/N]:
```

- **`b` (background)** — command dijalankan non-blocking, output ditulis
  ke file log di `.nvicoder/logs/<timestamp>-<nama>.log` di dalam project,
  dan tool langsung return dalam hitungan milidetik. Model (dan kamu) bisa
  cek progress kapan saja lewat `read_file` ke path log itu, atau minta
  model menghentikannya (`kill <pid>` / `taskkill /PID <pid> /F` di
  Windows — PID-nya ditampilkan di hasil).
- **`f` (foreground)** — tetap dijalankan blocking seperti biasa,
  kena timeout normal. Jarang perlu, kecuali kamu memang cuma mau lihat
  beberapa detik pertama output lalu mau di-Ctrl+C manual.
- **`a` (always)** — sama seperti `b`, PLUS mengaktifkan yolo mode untuk
  sisa sesi ini (lihat bagian berikutnya).
- **Tolak (Enter/N)** — command tidak dijalankan sama sekali.

Model juga sudah diinstruksikan lewat `prompt.md` untuk proaktif set
`background: true` sendiri saat memanggil `run_command` untuk command
jenis ini, jadi idealnya kamu tidak akan sering ditanya `b/f/a/N` — tapi
kalau modelnya lupa (model kecil kadang begitu), prompt-nya tetap jadi
pengaman. Instruksi ini juga sengaja diperluas ke **CLI/script apapun
yang modelnya buat atau jalankan sendiri yang isinya loop interaktif**
(REPL, chat loop, dst) — bukan cuma nama-nama dev server yang sudah
dikenal — supaya kasus seperti "model disuruh bikin coding-agent CLI lalu
mencoba menjalankan CLI itu sendiri" juga otomatis kebaca sebagai
long-running dan di-background-kan, bukan bikin sesi nyangkut.

Di mode `--yolo`, command long-running yang terdeteksi otomatis dijalankan
di background tanpa nanya (supaya tidak nyangkut nunggu konfirmasi yang
tidak akan pernah dijawab).

⚠️ Folder `.nvicoder/logs/` otomatis dibuat di project kamu — tambahkan ke
`.gitignore` kalau tidak mau ikut ke-commit.

## Melacak Background Job (`/jobs`)

Setiap command yang dijalankan di background (baik lewat pilihan `b`/`a`
di atas, maupun model yang langsung set `background: true`) dicatat
dalam registry sesi berjalan, dengan nomor urut (`#1`, `#2`, dst):

```
> /jobs
Background jobs (2 sedang jalan, 3 total sejak sesi ini mulai):
  #1  PID=521  [running]  flutter run
       log: .nvicoder/logs/job1-20260823-071303-flutter_run.log
  #2  PID=522  [running]  npm run dev
       log: .nvicoder/logs/job2-20260823-071303-npm_run_dev.log
  #3  PID=525  [selesai (exit=0)]  flutter pub get
       log: .nvicoder/logs/job3-20260823-071200-flutter_pub_get.log
```

Prompt REPL-nya sendiri juga berubah otomatis jadi `[N bg]>` (bukan `>`
polos) setiap kali ada job yang masih berjalan, jadi kamu selalu tahu
sekilas ada berapa proses background aktif tanpa perlu ngetik `/jobs`
tiap saat — baru buka detailnya (PID, log path, status) kalau memang
perlu.

## Ngurangi Friksi "Izinkan? [y/N]" Berulang-ulang

Kalau kamu lagi kerja aktif di satu project dan capek dikonfirmasi tiap
command, ada tiga opsi — dari yang paling cepat (di tengah kerjaan) sampai
yang paling permanen:

**Opsi A — Jawab `a` (always) langsung di prompt konfirmasi.** Paling
cepat, nggak perlu setup apapun duluan. Begitu ada command pertama yang
minta izin, jawab `a` alih-alih `y` — mulai saat itu, SEMUA command
berikutnya di sesi REPL yang sama (termasuk yang dari tool call lain
setelahnya) otomatis jalan tanpa nanya lagi. Efeknya sama persis dengan
`/yolo`, cuma dipicu langsung dari prompt-nya tanpa perlu ingat nama
command terpisah. Berlaku juga di prompt `b/f/a/N` untuk command
long-running (lihat bagian sebelumnya).

```
[nvicoder] Model minta izin menjalankan perintah:
  $ flutter pub get
  Izinkan? [y/N/a=selalu untuk sesi ini]: a
  [nvicoder] OK, semua command berikutnya di sesi ini auto-approve.
```

**Opsi B — `yolo = true` di `nvicoder.toml`.** Sama seperti Opsi A tapi
otomatis nyala dari awal setiap kali `nvicoder` dijalankan di project itu
(folder lain tetap normal), nggak perlu jawab `a` manual tiap sesi baru.
Cocok kalau kamu memang percaya penuh atau kerja di sandbox/branch yang
aman.

```toml
# nvicoder.toml
yolo = true
```

**Opsi C — `safe_commands` (lebih terukur).** Cuma command yang kamu
daftarin secara eksplisit yang auto-approve; command lain (termasuk yang
destruktif seperti `rm`, `git push --force`) tetap minta konfirmasi
seperti biasa. Cocok kalau mau hilangin friksi buat command rutin doang
(`flutter pub get`, `git add`, dst) tapi tetap ada pengaman buat yang lain.

```toml
# nvicoder.toml
safe_commands = [
    "flutter pub get",
    "flutter analyze",
    "flutter test",
    "git add",
    "git commit",
]
```

Match-nya berbasis **prefix** (sama seperti daftar aman bawaan di
`config.py`), jadi `"flutter pub get"` juga otomatis meng-cover
`flutter pub get --offline` dst, tapi TIDAK meng-cover `flutter pub
upgrade` (prefix beda). Ketik `/config` di REPL buat lihat daftar
`safe_commands` yang lagi aktif.

Command long-running yang terdeteksi (lihat bagian di atas) selalu lewat
alur `b/f/a/N`-nya sendiri, tidak kepengaruh `safe_commands` — tapi kalau
`yolo = true` (Opsi B) atau sudah pernah jawab `a` (Opsi A), keduanya
(long-running maupun command biasa) otomatis jalan tanpa nanya.

## Keamanan

- Setiap kali model memanggil `run_command` dengan perintah yang **tidak**
  ada di daftar aman (`ls`, `cat`, `git status`, `pytest`, dll — lihat
  `SAFE_COMMAND_PREFIXES` di `config.py`, plus `safe_commands` custom
  kamu kalau ada), `nvicoder` akan **berhenti dan minta konfirmasi
  `y/N/a`** ke kamu sebelum benar-benar menjalankannya.
- Mode `--yolo` / `/yolo` mematikan konfirmasi ini sepenuhnya. Cuma pakai
  ini di sandbox/container yang memang boleh rusak, jangan di mesin utama.
- `edit_file` mewajibkan `old_string` cocok **persis satu kali** di file,
  supaya tidak salah edit bagian lain yang mirip.

## Tampilan Output Model (Markdown, Reasoning Panel, Token Counter)

`nvicoder` pakai library [`rich`](https://github.com/Textualize/rich) untuk
merender output model, bukan cetak teks mentah — biar hasilnya kerasa
mirip Claude Code/Codex CLI:

- **Markdown ke-render rapi**: heading, **bold**, `code inline`, code
  block dengan bahasa, bullet list, dst dari jawaban model dirender jadi
  format aslinya di terminal (bukan simbol markdown mentah `**`/`##`/```` ``` ````
  yang keluar apa adanya).
- **Reasoning jadi panel "rolling-tail" yang bisa dibuka lagi**: kalau
  model kamu jenis reasoning (mengirim `reasoning_content` terpisah dari
  `content` saat streaming — ini yang terjadi kalau kamu pakai model
  seperti DeepSeek-R1/Qwen QwQ, biasanya di tier `high`), proses "mikir"
  yang panjang **tidak** ditampilkan penuh terus tumbuh ke bawah. Selama
  masih berlangsung, cuma **5 baris terakhir** yang kelihatan di panel
  kecil (baris lama otomatis "ketimpa" baris baru, mirip `tail -f`).
  Begitu jawaban final mulai muncul, panel itu langsung mengecil jadi
  satu baris ringkas (`✓ Reasoning selesai (N baris, N karakter)`).
  Teks reasoning LENGKAPnya tetap tersimpan — ketik **`/reasoning`** di
  REPL kapan saja setelah itu untuk melihat versi lengkapnya lagi (ini
  yang paling deket dengan "klik untuk expand" yang bisa dilakukan murni
  di terminal, tanpa GUI).
- **Penghitung token**: setiap turn selesai, muncul baris kecil redup:
  `[tokens] turn: prompt=1234 completion=567 total=1801 | sesi: 4521`.
  `turn` = token yang kepakai buat menjawab request itu (termasuk semua
  round-trip tool-calling di dalamnya kalau ada), `sesi` = akumulasi total
  sejak `nvicoder` dijalankan. Ini dari field `usage` yang NVIDIA kirim
  balik saat streaming (`stream_options={"include_usage": true}`) — kalau
  suatu model/endpoint ternyata tidak mengirim `usage` sama sekali, baris
  ini otomatis tidak muncul (bukan error, cuma memang datanya tidak ada).

Karena ini dependency baru, kalau kamu update dari instalasi lama, perlu
`pip install --editable .` ulang (atau `pip install rich` manual) supaya
`rich` ke-install.

## Verifikasi, Bukan Asumsi

`prompt.md` sekarang punya section eksplisit yang menyuruh model
membedakan **fakta yang terbukti lewat tool** vs **asumsi/tebakan**.
Intinya: `write_file`/`edit_file` yang sukses cuma membuktikan file-nya
kesimpan, BUKAN membuktikan kodenya benar — untuk project yang punya
build/compile/lint step (Flutter, TypeScript, Rust, dst), model
diwajibkan menjalankan verifikasi nyata (`flutter analyze`, `pytest`,
`tsc --noEmit`, dst) sebelum melaporkan sesuatu "berhasil". Model juga
diminta menandai eksplisit kalau dia menyebutkan sesuatu (versi library,
nama API) yang sebenarnya cuma dugaan, bukan yang sudah dia cek langsung
di project ini.

Ini bukan jaminan mutlak (model kecil kadang tetap lupa), tapi mengurangi
signifikan kasus model melaporkan "sudah beres" padahal cuma nulis file
tanpa pernah benar-benar mengetes hasilnya.

## Tampilan Output Tool (Full, Copy-Paste Ready)

Seperti **Claude Code**, `nvicoder` sekarang menampilkan **full output tool**
tanpa truncation (sebelumnya dipotong 800 karakter). Kamu bisa langsung
copy-paste hasil `read_file`, `run_command`, `search_files`, dll dari
terminal.

### History Compaction (Token Efficiency)

Agar riwayat percakapan panjang tidak meledak token per-request, tool
results lama (> threshold karakter) di-compact otomatis di history yang
dikirim ke model (placeholder singkat). Default:
- **Threshold**: 1200 karakter
- **Keep recent**: 3 hasil tool paling baru dibiarkan utuh

Override via environment variable (atau `nvicoder.toml`):

```bash
# Matikan compaction total (full history seperti Claude Code)
export NVICODER_TOOL_COMPACT_THRESHOLD=0

# Atau custom threshold
export NVICODER_TOOL_COMPACT_THRESHOLD=2000
export NVICODER_TOOL_KEEP_RECENT=5
```

```toml
# nvicoder.toml
[tool.nvicoder]
# env var tetap prioritas lebih tinggi, tapi bisa set di sini juga
# NVICODER_TOOL_COMPACT_THRESHOLD=0
```

> **Catatan**: Compaction hanya mempengaruhi history yang dikirim ke **model**.
> Tampilan di terminal (output `print_tool_result`) selalu full, tidak
> terpengaruh setting ini.

### User Input Compaction (Paste Teks Panjang)

Sama seperti tool results, **user message** yang terlalu panjang (mis. paste
log error, file besar, dokumentasi ke prompt) juga di-compact otomatis di
history yang dikirim ke model. Menggunakan **threshold & keep_recent yang
sama** dengan tool result compaction.

Ini mencegah token meledak saat user paste teks besar ke prompt, sambil
masih menjaga N pesan user terbaru utuh.

## Ide Pengembangan Lanjutan

- **Context/riwayat panjang**: saat ini seluruh riwayat percakapan dikirim
  ulang tiap turn tanpa ringkasan — untuk sesi panjang, tambahkan
  auto-summarization atau trimming berbasis token count (yang sekarang
  sudah kamu bisa lihat sendiri lewat `[tokens]` di tiap turn).
- **Multi-file diff view**: tampilkan unified diff sebelum `edit_file`
  benar-benar ditulis (saat ini langsung ditulis, tanpa preview).
- **Caching**: kalau butuh lebih hemat & cepat, cek apakah endpoint yang
  kamu pakai mendukung prompt caching untuk system prompt yang panjang.
