<div align="center">

# UIF → JSON

### Knight Online arayüzleri ve kaynak bağlantıları için Python CLI

![Python](https://img.shields.io/badge/Python-3.11%2B-3776AB?style=flat-square&logo=python&logoColor=white)
![Version](https://img.shields.io/badge/S%C3%BCr%C3%BCm-0.5.0-2563EB?style=flat-square)
![Dependencies](https://img.shields.io/badge/Ek_ba%C4%9F%C4%B1ml%C4%B1l%C4%B1k-Yok-168455?style=flat-square)
[![License](https://img.shields.io/badge/Lisans-MIT-334155?style=flat-square)](LICENSE)

**Yapımcı: Zorlanis**

</div>

---

**UIF to JSON**, Knight Online client dosyalarını okuyarak arayüz ağacını,
koordinatları, doku kesimlerini, yazıları, fontları ve TBL bağlantılarını JSON'a
aktarır. Yapay zekâ destekli Unity aktarımı için kaynakları izlenebilir veriler
ve kapsam raporları üretir.

Python standart kütüphanesini kullanır. Kaynak client dosyaları değiştirilmez;
çıktılar seçilen klasöre yazılır. Oyun dosyaları ve üretilmiş çıktılar bu depoya dahil değildir.

## Özellikler

- **UIF çözümleme:** Öğe türü/ID, parent-child ilişkileri, çizim sırası, konum,
  boyut, tıklama alanı, stiller, düğme durumları ve animasyon kareleri.
- **Görsel kullanımı:** DXT dosyası, normalize UV, piksel kesimi, ölçek,
  gerçek dosya eşleşmesi ve varsa mevcut PNG adayları.
- **Yazı ve fontlar:** Varsayılan metinler, araç ipuçları, ARGB renk, font adı,
  boyut, kalın/italik bilgisi ve client içindeki font dosyası adayları.
- **TBL bağlantıları:** Tipli satırlar, anahtarlar, kaynak hücre konumları,
  UIF/görsel/ses/model/efekt ve diğer dosya yolu referansları.
- **Tablo denetimi:** Sütun profilleri, anahtar tekilliği, kodlama alternatifleri,
  dış URI'ler ve incelenmesi gereken yol benzeri değerler.
- **Efekt görselleri:** FXB içindeki doku prefix/kare bağımlılıklarından DXT/PNG
  yolları çıkarılır. FXB dönüşümü aktarımı yapan yapay zekâya bırakılır.
- **Veri bütünlüğü:** Başarılı UIF ve çözülmüş TBL verisi, ayrıştırılan alanlardan
  yeniden oluşturularak kaynak baytlarıyla karşılaştırılır.
- **Otomasyon:** Etkileşimsiz kullanım, NDJSON olayları, ilerleme bilgisi ve çıkış kodları.

## Başlatma

**Python 3.11 veya üzeri** yeterlidir. Proje klasöründe:

```powershell
python uif2json.py
```

Terminal bir UIF dosyası veya klasör yolu sorar. Enter ile varsayılan client
kullanılır: `C:\NTTGame\KnightOnlineEn`. Varsayılanı `KO_CLIENT_ROOT` ortam
değişkeniyle veya komutta `--client-root` ile değiştirebilirsiniz.

```powershell
python uif2json.py --client-root "D:\Client" --non-interactive --compact
```

Program alt klasörlerdeki UIF'leri, client kökündeki TBL dosyalarını ve efektin
görsel bağımlılıklarını tarar. Varsayılan çıktı çalışma klasöründeki `outputs/`
dizinidir; bu dizin ilk çalıştırmada oluşturulur.

CLI komutunu kurmak için:

```powershell
python -m pip install .
uif2json --help
```

## Kullanım

Tek UIF dosyası:

```powershell
python uif2json.py "D:\Client\UI\co_inventory_us.uif" --client-root "D:\Client" --compact
```

Belirli bir UIF klasörü ve farklı çıktı yolu:

```powershell
python uif2json.py -d "D:\Client\UI" --client-root "D:\Client" -o "D:\UIF-JSON" --compact
```

TBL ve FXB taramaları, seçilen UIF alt klasöründen bağımsız olarak
`--client-root` içinde yapılır. Bunları kapatmak için `--no-tbl` / `--no-effects` kullanın.

Var olan çıktıları güncelleme:

```powershell
python uif2json.py --client-root "D:\Client" --non-interactive --compact --overwrite
```

Mevcut UIF/TBL JSON'ları varsayılan olarak korunur. Kaynak, çözümleyici sürümü,
kodlama veya dosya eşleşmeleri değişmişse `--overwrite` gerekir. Toplu raporlar
her tamamlanan taramada yenilenir; önceki çalışmalardan kalan dosyaları güncel
saymak için son `manifest.json` ve ilgili indekslerdeki durumu kontrol edin.

| Seçenek | İşlev |
| --- | --- |
| `input` veya `-d DIR` | UIF dosyası / taranacak klasör; birlikte kullanılamaz. |
| `--client-root DIR` | TBL ve kaynak dosyalarının bulunduğu client kökü. |
| `-o DIR` | Çıktı klasörü; varsayılan `./outputs`. |
| `--compact` | JSON boşluklarını azaltır. |
| `--overwrite` | Mevcut UIF/TBL JSON'larını günceller. |
| `--encoding CODEC` | UIF metin kodlaması; varsayılan `auto`. |
| `--tbl-encoding CODEC` | TBL metin kodlaması; varsayılan `auto`. |
| `--no-tbl` / `--no-effects` | İlgili taramayı kapatır. |
| `--non-interactive` | Kullanıcı girişi beklemez. |
| `--json` / `--quiet` | NDJSON olayları / yalnızca sonuç ve hatalar. |
| `--strict-assets` | Eksik UIF kaynaklarını ve TBL → UIF eşleşmelerini hata sayar. |
| `--version` / `--help` | Sürüm / komut yardımı. |

## Çıktılar

Dosya yolları client klasör yapısını korur:

```text
outputs/
├── AI_GUIDE.md
├── manifest.json
├── migration_report.json
├── screen_index.json
├── texture_index.json
├── table_index.json
├── ...
├── uif/UI/co_inventory_us.json
└── tbl/Data/UIs_us.json
```

| Dosya | İçerik |
| --- | --- |
| `uif/**/*.json` | Tam öğe ağacı, ham alanlar, geometri, yazılar ve kaynak kullanımı. |
| `tbl/**/*.json` | Tipli TBL hücreleri, ham metin baytları ve dosya referansları. |
| `AI_GUIDE.md` | Aktarımı yapacak yapay zekâ için okuma sırası ve yorumlama kuralları. |
| `migration_report.json` | Unity aktarım kapsamı ve doğrulanmamış bilgiler. |
| `screen_index.json` | UIF → TBL/doku/font bağlantıları ve ayrıntılı JSON yolları. |
| `texture_index.json` / `unresolved_textures.json` | Doku kullanım indeksi / eşleşmeyen dokular. |
| `text_index.json` / `font_index.json` | Metin araması / fontların kullanıldığı öğeler ve font dosyası adayları. |
| `resource_index.json` | Doku, ses ve Flash kaynakları. |
| `table_index.json` / `tbl_uif_links.json` | TBL sonuçları / kaynak hücreleriyle dosya bağlantıları. |
| `tbl_text_matches.json` | TBL ve UIF arasında aynı yazının geçtiği yerler; runtime bağlantısı kanıtı değildir. |
| `table_schema_report.json` | Sütun tipleri, değer dağılımları, anahtarlar ve kodlama incelemesi. |
| `table_review_candidates.json` | Dış URI'ler ve sınıflandırılmamış yol benzeri hücreler. |
| `effect_index.json` | Orijinal FXB yolları ve `images` altında DXT/PNG bağımlılıkları. |
| `asset_inventory.json` | Tüm indekslenmiş client dosyaları; uygunluk kararını tüketici verir. |
| `coverage_report.json` / `manifest.json` | UIF bayt kapsamı / son taramanın dosya sonuçları ve sayaçları. |

Bir görseli izlemek için `texture_index.json` içindeki `used_by` alanından
UIF ve öğe UID'sine, ardından UIF'nin `node_index` alanıyla ilgili öğeye gidin.
TBL → UIF bağlantıları hücrenin satır anahtarını, sütun numarasını ve bayt
konumunu içerir. Sütun ve satır indeksleri sıfır tabanlıdır.

## Yapay zekâ ve otomasyon

```powershell
python uif2json.py --client-root "D:\Client" --non-interactive --compact --overwrite --json
```

Olaylar `schema_version: 1` içeren JSON satırlarıdır: `indexing`, `tbl_found`,
`tbl_file`, `found`, `file`, `audit_stage`, `audit_progress`, `error`, `summary`,
`cancelled`. `parsed` / `failed` UIF, `tbl_parsed` / `tbl_failed` TBL;
`effect_failed` FXB bağımlılığı okuma sayılarını belirtir. Referans sayısı,
tekil dosya sayısıyla aynı değildir.

| Çıkış kodu | Anlamı |
| --- | --- |
| `0` | Veri çıkarma tamamlandı; ayrıca raporlanan belirsizlikler bulunabilir. |
| `1` | Okuma/ayrıştırma hatası veya `--strict-assets` ile eksik kaynak. Diğer dosyalar işlenir. |
| `2` | Geçersiz komut satırı seçenekleri. |
| `130` | Kullanıcı işlemi durdurdu; tamamlanan dosyalar korunur. |

## Kapsam ve sınırlar

- UIF koordinatları kayıtlı canvas piksel değerleridir. Üst öğe konumu alt
  öğeye tekrar eklenmez; parent-relative farklar ayrıca verilir.
- `visual_sources`, DXT ve mevcut PNG **adaylarının** yollarını verir.
  PNG/DXT piksel eşitliği doğrulanmaz; PNG ve Unity/FXB dönüşümü yapılmaz.
- `unity_ugui_geometry`, sabit üst-sol düzen için isteğe bağlı bir tariftir.
  Orijinal runtime anchor, çözünürlük veya ekran ölçeği bilgisi değildir.
- Font adı eşleşmesi; aynı yüz, glif kapsamı, satır kırılımı veya piksel
  rasterizasyonunu garanti etmez. Eksik fontlar raporlanır.
- Sütun anlamları, birimleri ve sayısal ID ilişkileri doğrulanmadığında
  `unknown` kalır. Aynı ID, aynı yazı veya küçük değer kümesi anlam kanıtı sayılmaz.
- Kodlama seçimi sezgiseldir. Ham baytlar korunur; bilinen dil için
  `--encoding` / `--tbl-encoding` seçin. Alternatifler tablo raporunda yer alır.
- Bilinmeyen kontrol/stil/ek alanlar korunur. Desteklenmeyen dosyalar açık
  hata verir. Oyun kodu, sunucu metinleri ve çalışma anındaki davranışlar uydurulmaz.
- Kaynak binary dosyalar kopyalanmaz. Üretilmiş JSON'lar yerel mutlak yollar
  içerebilir; aktarımı yapan yapay zekâ için kaynak client erişimi gerekir.

Dosyalar gereksiz olduğu varsayılarak elenmez. Birebir Unity aktarımı için
kaynak client ve Unity görüntülerinin aynı çözünürlük, dil ve kontrol durumunda
karşılaştırılması gerekir. Bu araç bütün bir oyun içe aktarıcısı değildir.

İkili düzenler ve JSON alanları: [FORMAT.md](FORMAT.md).

## Lisans

Copyright © 2026 **Zorlanis**. [MIT](LICENSE).
TBL kripto sabitlerinin kaynağı ve üçüncü taraf lisansı:
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
