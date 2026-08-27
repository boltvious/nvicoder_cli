# Infrastruktur Agent - Anthropic Claude Training Research

## Tanggal: 2025-01-XX

## Sumber Data
- **Tool**: `searxng_search` via VPS `http://103.235.75.211:8080`
- **Model**: `nvidia/nemotron-3-super-120b-a12b` (effort=high)
- **Query**: "Anthropic Claude Opus Sonnet training methodology Constitutional AI RLAIF"

---

## Ringkasan Eksekutif

Anthropic melatih model Claude (Opus, Sonnet) menggunakan pipeline **5 tahap** yang menggabungkan **Constitutional AI** + **RLAIF** (Reinforcement Learning from AI Feedback) untuk mencapai *scalable safety* — keamanan yang bisa diskalakan tanpa bergantung sepenuhnya pada label manusia yang mahal.

---

## Pipeline Pelatihan (5 Tahap)

| Tahap | Nama | Deskripsi |
|-------|------|-----------|
| **1** | **Pre-training** | Self-supervised learning pada korpus teks berskala besar untuk mempelajari pola bahasa umum |
| **2** | **SFT** (Supervised Fine-Tuning) | Fine-tuning pada demonstrasi manusia (jawaban ideal) untuk format, instruction following, tugas spesifik |
| **3** | **Constitutional AI** | Model mengkritik & merevisi output sendiri berdasarkan "constitution" (daftar prinsip eksplisit) → menghasilkan pasangan preferensi AI-generated |
| **4** | **Reward Model (RM)** | Dilatih pada data preferensi AI dari tahap 3 untuk memprediksi revisi mana yang lebih sesuai konstitusi |
| **5** | **RLAIF** (RL from AI Feedback) | Fine-tuning dengan RL (PPO) menggunakan reward dari RM — mengoptimalkan konsistensi dengan konstitusi tanpa label manusia per iterasi |

---

## Konstitusi Anthropic (Prinsip Utama)

| Prinsip | Deskripsi | Prioritas |
|---------|-----------|-----------|
| **Harmless** | Filter konten berbahaya, toksik, ilegal, diskriminatif | **Tertinggi** (fondasi) |
| **Honest** | Tidak hallucinate; akui ketidaktahuan | **Tinggi** |
| **Helpful** | Beri jawaban berguna, tapi tidak mengorbankan safety | **Tertinggi** (bisa dikorbankan jika konflik) |

> **Hierarki**: Safety/Ethics > Helpfulness saat konflik.

**Contoh klausul**: "Jangan membantu aktivitas ilegal", "Jangan menghasilkan konten berbahaya", "Jaga kejujuran", "Model boleh menolak permintaan yang bertentangan konstitusi".

---

## Infrastruktur Komputasi

| Aspek | Detail |
|-------|--------|
| **Cloud Provider** | **AWS** + **Google Cloud** (multi-cloud strategy) |
| **Hardware** | GPU/TPU spesifik tidak diumumkan publik |
| **Skala** | Large-scale distributed training |
| **Data Cutoff** | Opus: Agustus 2023 · Sonnet 3.7/Opus 4.5: Agustus 2025 |

---

## Deployment & Akses

| Platform | Status |
|----------|--------|
| **Anthropic API** | ✅ Primary access |
| **AWS Bedrock** | ✅ Managed service |
| **GCP Vertex AI** | ✅ Managed service |
| **Local Download** | ❌ **Tidak tersedia** (model proprietary) |

---

## Keamanan & Evaluasi

- **Red-teaming** ekstensif + audit eksternal
- **Post-training safety classifiers** + refusal mechanisms
- **Monitoring berkelanjutan** via Anthropic safety-evaluation suite
- **Benchmarks**: SOTA di MMLU, GSM-8K, HumanEval, multilingual, vision-language
- **Resistensi jailbreak** lebih kuat vs Claude 2.x

---

## RLHF vs RLAIF (Perbandingan)

| Aspek | RLHF | RLAIF |
|-------|------|-------|
| **Label Source** | Manusia | AI (LLM yang sudah aligned) |
| **Biaya** | Tinggi | Rendah |
| **Skalabilitas** | Terbatas | Tinggi |
| **Kualitas** | Sangat baik (gold standard) | Kompetitif, bergantung kualitas labeler AI |
| **Bias** | Bias manusia | Risiko bias dari labeler AI |
| **Peran Anthropic** | Fondasi alignment awal | Scaling & refinement |

> **Strategi Anthropic**: Kombinasi — RLHF untuk fondasi, RLAIF untuk scaling.

---

## Paper & Referensi Kunci

| # | Judul | Link | Tipe |
|---|-------|------|------|
| 1 | Constitutional AI: Harmlessness from AI Feedback | https://www.anthropic.com/research/constitutional-ai-harmlessness-from-ai-feedback | Paper resmi |
| 2 | RLAIF vs RLHF: Scaling RL from Human Feedback (Bai et al., 2022) | https://arxiv.org/abs/2309.00267 | ArXiv |
| 3 | How Anthropic Trains Claude (GUVI) | https://www.guvi.in/blog/how-anthropic-traines-claude-rlhf-vs-rlaif/ | Blog teknis |
| 4 | Constitutional AI Guide (AI Safety) | https://aisecurityandsafety.org/en/guides/constitutional-ai-guide/ | Panduan |
| 5 | Claude Model Card (PDF) | Via Anthropic API docs | Model card |

---

## Catatan Teknis untuk Implementasi

Jika ingin membangun pipeline serupa (mini-CAI/RLAIF):

1. **Constitution** → Tulis prinsip eksplisit (markdown/YAML)
2. **Critique/Revise** → Prompt model untuk kritik & revisi output sendiri
3. **Preference Pairs** → Kumpulkan (original, revised) sebagai data preferensi
4. **Reward Model** → Train classifier/ranker pada pairs
5. **RL Loop** → PPO dengan reward model sebagai reward signal
6. **Validasi** → Human eval di akhir untuk cek alignment

---

## Verifikasi Toolchain

| Test | Hasil |
|------|-------|
| `searxng_search` Constitutional AI | ✅ 5 hasil (paper, guide, wiki, PDF) |
| `searxng_search` RLAIF | ✅ 5 hasil (paper, blog, GitHub awesome-list) |
| `searxng_search` RLHF vs RLAIF | ✅ Perbandingan tabel + kesimpulan |
| `searxng_search` Claude training pipeline | ✅ 5 tahap detail + infrastructure |
| `searxng_search` Constitution principles | ✅ Helpful/Honest/Harmless + prioritas |
| `searxng_search` Model card Opus/Sonnet | ✅ Compute, data cutoff, safety, deployment |

---

## Next Steps (Opsional)

- [ ] Ekstrak teks konstitusi lengkap dari PDF/repo resmi
- [ ] Bangun demo mini-Constitutional AI dengan model kecil
- [ ] Bandingkan dengan pendekatan OpenAI (RLHF only), DeepMind (Sparrow), Meta (Llama Guard)
- [ ] Implementasikan safety filter berbasis konstitusi untuk project lain