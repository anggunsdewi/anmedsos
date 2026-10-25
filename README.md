# Crawler #KaburAjaDulu (X, Threads, TikTok)

Pipeline pengumpulan data media sosial untuk penelitian *Keresahan Ketenagakerjaan dan Aspirasi Bekerja ke Luar Negeri di Era #KaburAjaDulu*. Sumber data dipasang lewat antarmuka provider, jadi platform dipilih dari berkas konfigurasi:

| Platform | Config | Provider | Akses | Biaya |
|---|---|---|---|---|
| X | `config.yaml` | X API v2 resmi | Pay-per-use | ±US$26 untuk run default |
| Threads | `config.threads.yaml` | Threads API resmi (Meta) | Perlu App Review untuk `threads_keyword_search` | Gratis |
| TikTok | `config.tiktok.yaml` | Actor Apify (scraping pihak ketiga) | Akun Apify | Berbayar per hasil, ada kredit gratis bulanan |

Semua platform memakai kata kunci, periode, jendela mingguan, filter, pseudonimisasi, dan log yang sama. Pilih config dengan `-c`, misalnya `python -m crawler collect -c config.threads.yaml`. Detail tiap platform ada di bagian [Threads](#threads) dan [TikTok](#tiktok).

## Ringkasan alur

| Tahap | Perintah | Hasil |
|---|---|---|
| 1. Susun kueri per grup kata kunci | `plan` | Teks kueri dan jumlah unit (jendela x grup) |
| 2. Ambil per kueri dan per jendela mingguan, dengan cap yang sama | `collect` | `data/raw/<minggu>/<grup>.jsonl` |
| 3. Simpan progres setelah tiap halaman | otomatis | `checkpoints/state.json` |
| 4. Gabungkan seluruh data mentah | `process` | |
| 5. Deduplikasi berdasarkan ID unggahan, grup disimpan di `matched_groups` | `process` | |
| 6. Saring (periode, bahasa, repost, kata kunci, <3 kata, iklan lowongan, spam, teks identik lintas akun) | `process` | `data/interim/dropped_posts.csv` |
| 7. Pseudonimisasi (`user_hash` SHA-256 + salt, mention jadi `@user`, URL jadi `[url]`) | `process` | |
| 8. Ekspor dataset final dan sampel 100 baris | `process` | `data/final/dataset_final.csv`, `data/final/sample_100.csv` |
| 9. Catat jumlah data tiap tahap | `process` | `logs/process_summary.csv` |

## Akses X API dan biaya (baca dulu)

Periode penelitian (1 Jan 2025 s.d. 30 Jun 2026) sudah lewat lebih dari 7 hari, jadi wajib memakai **full-archive search** (`/2/tweets/search/all`). Recent search hanya menjangkau 7 hari terakhir.

Kondisi per Oktober 2026:

- Menurut dokumentasi resmi, full-archive search tersedia untuk akun **pay-per-use** dan **Enterprise** ([docs.x.com](https://docs.x.com/x-api/posts/search/quickstart/full-archive-search)).
- Sejak 6 Februari 2026 pay-per-use menjadi skema default. Paket Basic dan Pro tidak lagi dibuka untuk pendaftar baru, dan tier gratis tidak punya akses baca.
- Tarif baca yang dikutip berbagai sumber pihak ketiga sekitar **US$0,005 per unggahan** ([postproxy](https://postproxy.dev/blog/x-api-pricing-2026/), [socialcrawl](https://www.socialcrawl.dev/blog/x-twitter-api-2026)). Ini bukan rate card resmi, jadi cek angka pastinya di Developer Console sebelum membeli kredit.
- Perkiraan kasar dengan konfigurasi default: 5.148 unggahan x US$0,005 ≈ **US$26**, ditambah sedikit untuk percobaan ulang. Biaya endpoint `counts` (perintah `estimate`) belum jelas, jadi jalankan hanya jika perlu.
- Batas laju full-archive: 300 request per 15 menit dan 1 request per detik. Dengan default (234 unit, sekitar 1 request per unit), pengambilan selesai dalam beberapa menit.

Pengaman biaya: `collection.max_posts_total` menghentikan pengambilan saat total unggahan mentah mencapai angka itu. Jika kredit habis (HTTP 402 atau 429 `UsageCapExceeded`), crawler berhenti dengan rapi dan bisa dilanjutkan setelah kredit diisi.

## Threads

Threads API resmi gratis dan punya endpoint pencarian kata kunci (`keyword_search`) dengan filter tanggal (`since`/`until`), sehingga cocok untuk jendela mingguan ([dokumentasi](https://developers.facebook.com/documentation/threads/keyword-search)).

Yang perlu disiapkan:

1. Buat aplikasi di [Meta for Developers](https://developers.facebook.com/) dengan use case Threads API, lalu minta izin `threads_basic` dan `threads_keyword_search`.
2. **App Review wajib.** Tanpa persetujuan `threads_keyword_search`, hasil pencarian hanya berisi unggahan akun sendiri. Ajukan App Review dengan menjelaskan tujuan penelitian. Prosesnya bisa makan waktu dan tidak dijamin disetujui, jadi ajukan sedini mungkin.
3. Buat access token pengguna long-lived (berlaku 60 hari), isi di `.env` sebagai `THREADS_ACCESS_TOKEN`.

Batasan yang memengaruhi metode:

- Satu kueri hanya satu kata kunci (tidak ada OR), jadi crawler otomatis membuat kueri per kata kunci: 16 kata kunci x 78 minggu = 1.248 kueri. Batas Threads 2.200 kueri per 24 jam per pengguna, jadi semuanya muat dalam sehari.
- Tidak ada pagination; satu kueri maksimal 100 unggahan. Dengan cap 22 per grup per minggu (3-4 per kata kunci), ini tidak jadi masalah.
- Tidak ada filter bahasa, jadi bahasa dideteksi saat `process` dengan `langdetect` (kolom `lang_detected` = 1).
- Jumlah suka/balasan unggahan orang lain tidak tersedia, sehingga kolom metrik kosong. Descriptive analysis untuk keterlibatan tidak bisa dilakukan dari data Threads.
- `search_type: TOP` mengurutkan berdasarkan popularitas, `RECENT` berdasarkan waktu. Pertimbangannya sama dengan bagian "Urutan hasil" di bawah.

## TikTok

**TikTok Research API resmi belum bisa dipakai dari Indonesia.** Program itu hanya untuk peneliti di AS, Eropa, Kanada, dan Brasil ([TikTok for Developers](https://developers.tiktok.com/products/research-api/)). Karena itu provider TikTok memakai actor [Apify](https://apify.com/clockworks/tiktok-scraper) yang melakukan scraping web TikTok.

Yang perlu disiapkan: buat akun Apify, ambil API token di Settings > Integrations, isi di `.env` sebagai `APIFY_TOKEN`.

Hal yang perlu diketahui:

- **Biaya.** Apify menagih per hasil. Harga yang dikutip sumber pihak ketiga mulai sekitar US$1,70 per 1.000 video, dan filter tanggal dikenai biaya tambahan. Komentar memakai actor terpisah, sekitar US$0,50-5 per 1.000. Paket gratis Apify memberi kredit kecil per bulan. Cek harga terbaru di halaman actor, lalu uji dulu dengan `--limit-units 3` dan lihat tagihannya di Apify Console.
- **Unit data.** Caption video (`post_type` = original) dihitung terhadap cap. Komentar (`post_type` = comment, `parent_id` = ID video) opsional lewat `comments_per_video`. Komentar tidak mengurangi cap, tetapi tetap ditagih dan tetap dihitung oleh rem `max_posts_total`. Default: 10 video per grup per minggu (2.340 video) dan 5 komentar per video.
- **Kata kunci.** Kata kunci berawalan `#` dikirim sebagai hashtag, sisanya sebagai kueri pencarian video.
- **Tanggal.** Pencarian TikTok tidak menjamin rentang tanggal. Filter tanggal Apify tetap dikirim, lalu hasilnya disaring ulang per jendela. Untuk minggu-minggu lama, hasil bisa kurang dari cap (status `exhausted` di `collection_log.csv`).
- **Filter.** Video yang ditandai TikTok sebagai iklan dibuang lewat filter `sponsored`. Komentar tidak wajib memuat kata kunci (`keyword_filter_skip_types`), karena relevansinya datang dari video induknya. Bahasa komentar dideteksi dengan `langdetect`.
- **Ketentuan layanan.** Scraping melanggar Ketentuan Layanan TikTok. Ini harus dibahas terbuka di paragraf etika, termasuk alasan tidak memakai Research API (tidak eligible dari Indonesia).

## Instalasi

Butuh Python 3.10+.

```bash
cd kaburajadulu-crawler
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env               # Windows: copy .env.example .env
```

Isi `.env`:

- `X_BEARER_TOKEN`: Bearer Token aplikasi dari Developer Console X.
- `THREADS_ACCESS_TOKEN` / `APIFY_TOKEN`: hanya jika memakai Threads atau TikTok.
- `PSEUDONYM_SALT`: string acak rahasia. Buat sekali dengan `python -c "import secrets; print(secrets.token_hex(32))"` dan pakai yang sama di seluruh tim agar `user_hash` konsisten. Jangan dibagikan di repositori atau laporan.

## Cara menjalankan

```bash
python -m crawler plan                      # cek kueri, jumlah unit, total cap
python -m crawler collect --limit-units 3   # uji coba kecil (3 unit, sekitar 66 unggahan)
python -m crawler status                    # lihat progres
python -m crawler collect                   # ambil semua; aman dihentikan (Ctrl+C) dan dijalankan lagi
python -m crawler process                   # dedup, filter, pseudonimisasi, ekspor
```

`python -m crawler run` menjalankan `collect` lalu `process` sekaligus. Tambahkan `--provider mock` untuk mencoba seluruh pipeline dengan data sintetis tanpa token dan tanpa biaya.

Opsional: `python -m crawler estimate` menghitung jumlah unggahan yang cocok per minggu per grup lewat endpoint counts dan menyimpannya di `logs/volume_estimate.csv`. Angka ini menunjukkan volume percakapan yang sebenarnya, sebelum dibatasi cap, sehingga lebih tepat untuk grafik tren volume di descriptive analysis.

### Melanjutkan dari checkpoint

Setiap halaman hasil langsung ditulis ke `data/raw` dan progresnya dicatat di `checkpoints/state.json`. Jika proses terhenti (koneksi putus, kredit habis, laptop mati), jalankan perintah yang sama lagi. Unit yang sudah selesai dilewati, unit yang setengah jalan dilanjutkan dari `next_token` terakhir, dan baris yang tertulis setelah checkpoint terakhir dibuang agar tidak ganda. Untuk mengulang dari nol, hapus folder `data/raw` dan `checkpoints`.

## Konfigurasi (`config.yaml`)

Semua parameter penelitian ada di `config.yaml`, terpisah dari kode:

- `query.groups`: tiga grup kata kunci sesuai Tabel 2. Nama grup menjadi isi kolom `matched_groups`.
- `query.split_keywords`: `false` (default) menggabungkan kata kunci satu grup dengan OR dalam satu kueri. `true` membuat satu kueri per kata kunci dan membagi cap rata ke tiap kata kunci, sehingga kata kunci yang sangat ramai (mis. "gaji") tidak mendominasi grupnya. Konsekuensinya, jumlah request bertambah.
- `collection.cap_per_window`: batas unggahan per grup per minggu. Default 22, sehingga 78 minggu x 3 grup x 22 = 5.148 unggahan mentah (target ±5.000).
- `collection.slices_per_window` dan `provider.options.sort_order`: lihat bagian berikut.
- `processing.job_ad` dan `processing.spam`: daftar pola regex untuk iklan lowongan dan spam. Iklan dianggap terdeteksi jika cocok dengan 1 pola kuat atau minimal `min_hits` pola biasa. Ini sengaja tidak memakai kata "lowongan kerja" saja, karena kata itu juga kata kunci penelitian dan banyak dipakai saat mengeluh.
- `processing.identical_text_min_accounts`: teks yang sama (setelah URL, mention, dan tanda baca dibuang) dari minimal N akun berbeda dianggap bot atau spam, dan semua salinannya dibuang.

### Urutan hasil dan sebaran waktu dalam seminggu

Karena cap per minggu kecil (22) sementara volume aslinya bisa ribuan, unggahan mana yang terambil bergantung pada urutan hasil:

- `sort_order: recency` mengambil unggahan terbaru lebih dulu, sehingga 22 unggahan bisa menumpuk di beberapa jam terakhir minggu itu.
- `sort_order: relevancy` (default) memakai urutan relevansi X. Sebarannya dalam seminggu lebih luas, tetapi cenderung memilih unggahan dengan keterlibatan tinggi.
- `slices_per_window: 7` membagi tiap minggu menjadi 7 hari dengan cap dibagi rata (22 menjadi 3 atau 4 per hari). Sebaran harian jadi merata, tetapi X API meminta minimal 10 unggahan per halaman, jadi sekitar 3 kali lebih banyak unggahan yang terambil (dan ditagih) daripada yang disimpan.

Pilihan mana pun, tulis di bagian Metode Pengumpulan Data dan Keterbatasan Data.

## Mengganti sumber data

Provider dipilih di `provider.name`:

| Nilai | Keterangan |
|---|---|
| `x_api_v2` | X API v2 resmi (default) |
| `threads_api` | Threads API resmi |
| `tiktok_apify` | TikTok lewat actor Apify |
| `mock` | Data sintetis untuk uji coba |
| `paket.modul:NamaKelas` | Provider buatan sendiri |

Untuk API lain (mis. Scweet atau API pihak ketiga), salin `crawler/providers/example_custom.py`, isi `search_page()` agar mengembalikan unggahan dengan field standar (`id`, `created_at`, `text`, `lang`, `author_id`, `post_type`, `like_count`, `reply_count`, `repost_count`, `quote_count`, `hashtags`), lalu arahkan `provider.name` ke kelas itu. Set `platform` (isi kolom `platform`) dan `supports_or = False` jika API tidak mendukung OR.

Berkas config bisa mewarisi config lain dengan `extends: config.yaml` di baris pertama, lalu hanya menimpa bagian yang berbeda. Lihat `config.threads.yaml` dan `config.tiktok.yaml`. Jendela mingguan, cap, checkpoint, dedup, filter, pseudonimisasi, dan log tidak perlu diubah.

## Berkas luaran

| Berkas | Isi | Boleh di repo publik? |
|---|---|---|
| `data/raw/**.jsonl` | Data mentah per minggu per grup, termasuk `author_id` | Tidak (simpan di Drive privat) |
| `data/interim/dropped_posts.csv` | ID unggahan yang dibuang dan di filter mana | Tidak |
| `data/final/dataset_final.csv` | Dataset final terpseudonimkan | Tidak (simpan di Drive privat) |
| `data/final/sample_100.csv` | 100 baris acak dari dataset final | Ya |
| `logs/process_summary.csv` | Jumlah data tiap tahap, ditambahkan setiap kali `process` dijalankan (pisahkan per `run_id`) | Ya |
| `logs/collection_log.csv` | Per unit: kueri, cap, jumlah terambil, jumlah request, status | Ya |
| `logs/group_counts.csv` | Jumlah unggahan final per grup | Ya |
| `logs/volume_estimate.csv` | Hasil `estimate` | Ya |

Untuk Threads dan TikTok, folder `data/` dan `logs/` di atas berada di subfolder `threads/` atau `tiktok/` (mis. `data/threads/final/dataset_final.csv`), sehingga data tiap platform tidak tercampur.

Kolom `dataset_final.csv`: `platform` (x/threads/tiktok), `post_id`, `parent_id` (khusus komentar TikTok: ID video induk), `created_at` (UTC), `week_start` (tanggal awal minggu, WIB), `post_type` (original/reply/quote/comment), `lang`, `lang_detected` (1 jika bahasa hasil `langdetect`), `text`, `user_hash`, `like_count`, `reply_count`, `repost_count`, `quote_count`, `hashtags`, `matched_groups` (mis. `aspirasi;spesifik`).

Metrik yang tidak tersedia dibiarkan kosong, tidak diisi 0, dan jumlahnya dicatat di kolom `note` baris `final_pseudonymized` pada `process_summary.csv`.

Status di `collection_log.csv`: `cap_reached` berarti cap minggu itu terpenuhi, `exhausted` berarti hasil pencarian habis sebelum cap (volume minggu itu memang kecil).

Angka untuk bagian Kualitas Data (mentah, setelah deduplikasi, setelah tiap filter, persentase terbuang) bisa langsung diambil dari `process_summary.csv`. Kolom `dropped_pct_of_raw` menghitung persentase terhadap jumlah mentah.

## Minimalisasi data

Provider X hanya meminta field unggahan (`tweet.fields`) tanpa `expansions` ke objek pengguna, sehingga nama tampilan, foto profil, bio, dan lokasi tidak pernah diunduh. Provider Threads hanya meminta `id,text,timestamp,username,is_reply,is_quote_post,media_type`. Provider TikTok hanya menyimpan field yang dibutuhkan dari keluaran Apify. ID atau username penulis hanya ada di data mentah untuk keperluan hash dan deteksi teks identik, lalu tidak ikut ke dataset final.

## Catatan untuk bagian etika dan keterbatasan

- **Ketentuan layanan.** Pengambilan lewat X API resmi tunduk pada X Developer Agreement and Policy, termasuk larangan membagikan ulang konten secara massal. Ini sejalan dengan rencana hanya membagikan sampel 100 baris terpseudonimkan. Jika beralih ke Scweet atau scraping antarmuka web, perlu dicatat bahwa Ketentuan Layanan X melarang crawling atau scraping tanpa izin tertulis dan robots.txt X membatasi crawler, sehingga paragraf etika perlu membahasnya secara eksplisit.
- **Tabel 3.** Baris "Ketergantungan pada antarmuka web X yang tidak terdokumentasi" hanya relevan jika memakai Scweet. Dengan API resmi, risikonya berganti menjadi perubahan harga atau akses API. Mitigasinya tetap sama: versi pustaka dikunci (`requirements.txt`), kegagalan dicatat di log, dan pengumpulan bisa dilanjutkan dari checkpoint.
- **Filter berbasis aturan.** Filter iklan dan spam bersifat heuristik. Sebaiknya baca manual sekitar 100 unggahan acak dari `dataset_final.csv` dan beberapa yang dibuang di `dropped_posts.csv`, lalu sesuaikan pola di `config.yaml` sebelum analisis.
- **Lingkup geografis.** Lingkup Indonesia didekati lewat bahasa unggahan (`lang:id` dari X, `textLanguage` dari TikTok, atau `langdetect` untuk Threads dan komentar TikTok), bukan lokasi pengguna. `langdetect` kurang akurat untuk teks sangat pendek dan bahasa gaul.
- **Threads dan TikTok.** Threads API resmi tunduk pada Meta Platform Terms dan Threads Developer Terms. TikTok lewat Apify adalah scraping yang melanggar Ketentuan Layanan TikTok. Jika platform penelitian berubah dari X, judul, Tabel 2, Tabel 3, dan paragraf etika di paper juga perlu disesuaikan.

## Pengujian

```bash
python -m unittest discover tests -v
```

Pengujian mencakup pembagian jendela (78 minggu), pembagian cap, checkpoint dan resume (termasuk crash di tengah halaman), dedup dan `matched_groups`, semua filter, pseudonimisasi, serta penanganan 429, 5xx, koneksi putus, kuota habis, dan akses ditolak pada provider X, Threads, dan TikTok (dengan respons HTTP tiruan). Ada juga uji alur TikTok: komentar tidak mengurangi cap, video iklan dibuang, dan bahasa komentar dideteksi.

## Struktur kode

```
crawler/
  cli.py              perintah plan/estimate/collect/process/run/status
  config.py           baca config.yaml dan .env
  windows.py          jendela mingguan (zona waktu Asia/Jakarta) dan pembagian cap
  collect.py          pengambilan per unit, cap, checkpoint, collection_log
  checkpoint.py       state.json dan pemotongan baris yang belum tercatat
  process.py          merge, dedup, filter, pseudonimisasi, ekspor, process_summary
  filters.py          kriteria inklusi/eksklusi
  textutils.py        pembersihan teks, pencocokan kata kunci, hash
  providers/
    base.py           antarmuka SearchProvider dan format unggahan standar
    x_api_v2.py       X API v2 (rate limit, retry, backoff)
    threads_api.py    Threads API keyword_search
    tiktok_apify.py   TikTok via actor Apify (video + komentar)
    http.py           klien HTTP dengan retry untuk Threads dan TikTok
    mock.py           data sintetis
    example_custom.py kerangka untuk API lain
```
