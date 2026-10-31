# UIF JSON biçimi · schema_version 1

Bu belge `ko-uif-to-json` 0.5.0 çıktısını açıklar. `schema_version` veri
şemasını, `analysis_version` ise yorumları üreten uygulama sürümünü belirtir.
Burada listelenen çıktı dosyaları çalışma sırasında oluşturulur; depoda hazır
client verisi veya üretilmiş rapor bulunmaz. Komut kullanımı için [README.md](README.md).

Bu proje UIF dosyalarını çalıştırmaz veya değiştirmez. Dosya içindeki kayıtları
okur; bilinen ilişkileri ayrıca hesaplar. Her başarılı dosyada `bytes_consumed`
kaynak boyutuna eşittir. Sonda okunmamış bayt varsa dosya başarılı sayılmaz.
`analysis_version`, ek yorumların üretildiği uygulama sürümünü belirtir.
`coverage.byte_reconstruction: exact_match`, JSON'a aktarılan ham alanlardan
kaynak dosyanın bellekte birebir yeniden oluşturulabildiğini belirtir.

## İkili kayıt düzeni

Sayılar little-endian'dır. Dizeler, `int32 byte_length` ve bunu takip eden ham
baytlardan oluşur; uzunluk karakter sayısı değildir.

Bir öğe şu sırayla saklanır:

1. Kayıt adı.
2. Alt öğe sayısını alt 16 bitte, başlık etiketini üst 16 bitte taşıyan `uint32`.
3. Her alt öğe için `uint32 type_id` ve aynı düzenle iç içe öğe kaydı.
4. Öğe ID'si, `region` ve `movable_region` için iki adet dört `int32` dikdörtgen.
5. `uint32 style`, `uint32 reserved`, araç ipucu.
6. Ses alanları bulunan profillerde açılma ve kapanma ses dosyaları.
7. Opak ek baytlar ve türe özgü alanlar.

Desteklenen başlık etiketleri 0, 1, 2 ve 3'tür. Etiket 0/1 için ek bayt yoktur;
2/3 için sırasıyla 2/3 ek bayt bulunur. Bu baytların anlamı doğrulanmadığından
`binary.extension_hex` olarak korunur. Etiket bir oyun sürüm numarası olarak sunulmaz.

Sesli/sessiz ve satır aralıklı/aralıksız profiller denenir. Yalnızca dosyanın
tamamını eksiksiz tüketen profil kabul edilir; dosya adına göre profil seçilmez.

## Türe özgü alanlar

| Tür | ID | Ek alanlar |
| --- | --- | --- |
| base | 0 | Temel alanlar. |
| button | 1 | Tıklama dikdörtgeni; profil destekliyorsa hover ve tıklama sesi. |
| static | 2 | Profil destekliyorsa tıklama sesi. |
| progress | 3 | Görseller ve roller alt öğelerden çıkarılır. |
| image | 4 | Doku dosya adı, dört `float32` UV değeri, animasyon FPS'si. |
| scrollbar | 5 | Düğme ve trackbar referansları alt öğelerden çıkarılır. |
| string | 6 | Font adı, varsa boyut ve bayraklar, ARGB renk, yazı, profile göre satır aralığı. |
| trackbar | 7 | Arka plan ve tutamaç görselleri alt öğelerden çıkarılır. |
| edit | 8 | Static ses alanına ek olarak yazma sesi. |
| area | 9 | Alan türü numarası. |
| tooltip | 10 | Temel alanlar. |
| list | 14 | Font adı, varsa boyut, renk ve iki 32 bit kalın/italik alanı. |
| unknown_15/16/17 | 15–17 | Temel alanlar okunur; kontrol anlamı bilinmiyor. |
| flash | 18 | Bilinmeyen sayı, dosya referansı ve UV dikdörtgeni. |

11/12/13 gibi düzeni doğrulanmamış türler
sessizce atlanmaz; açık hata döndürülür. Sayılar, dize uzunlukları, derinlik ve
dosya sınırları denetlenir. Sonlu olmayan float değerleri kabul edilmez.

## JSON alanları

- `source`: Client'e göre yol, tam yol, dosya boyutu ve SHA-256.
- `format`: Algılanan profil, tam tüketim bilgisi, koordinat ve sıra açıklaması.
- `root`: Tam öğe ağacı; alt öğeler fiziksel dosya sırasıyla tutulur.
- `node_index`: Dosya içinde benzersiz UID'den `root.children[... ]` yoluna eşleme.
- `textures`: Tekil doku referansları, eşleşen dosyalar, boyut/format ve kullanan UID'ler.
- `texts`: Varsayılan string öğeleri; font, renk, hizalama ve bölge bilgisi.
- `tooltips`: Boş olmayan araç ipuçları ve bağlı oldukları öğeler.
- `duplicate_element_ids`: ID'si ortak olan öğeler. Boş ID'ler bu listeye alınmaz.
- `warnings`: Eksik kaynak, kodlama tahmini ve kontrol anlamı belirsizlikleri.
- `coverage`: Bayt eşitliği doğrulaması, kodlama sayıları ve anlamı doğrulanmamış alanlar.
- `resources`: Düğüm ve kullanım rolüyle birlikte ses/Flash dosyası eşleşmeleri.
- `table_links`: Bu UIF'nin yolunu taşıyan çözümlenmiş TBL hücreleri.

UID'ler yalnızca ilgili UIF içinde benzersizdir. Farklı UIF'lerdeki aynı UID aynı
kontrol değildir. Global indekslerde UIF yolu ve UID birlikte kullanılır.

### Ham veri

Her öğede `binary.offset`, `binary.length`, fiziksel tür alanı konumu, birleşik
başlık değeri ve ek baytlar bulunur. `binary.length` alt öğeleri de kapsayan
toplam kayıt aralığıdır. `binary.strings`, boş olmayan dizelerin orijinal
baytlarını, uzunluğunu, uzunluk alanının konumunu ve seçilen kodlamayı içerir.
Boş dizeler JSON'daki boş alanları ve profil düzeniyle temsil edilir.

### Koordinat ve çizim sırası

`region` içindeki sol/üst/sağ/alt canvas piksel koordinatları korunur. Genişlik
`right-left`, yükseklik `bottom-top` olarak hesaplanır. Üst öğeye göre yerleşim,
üst öğenin sol/üst değerleri çıkarılarak bulunur; üst öğe konumu tekrar eklenmez.

Standart temel N3 UI çizim sırası fiziksel dosya sırasıyla arkadan öne ilerler.
Düğme ve animasyon görsellerinin hepsi aynı anda çizilmez: `usage_role`,
`state_images` ve kare referansları hangi parçanın ne zaman kullanılacağını ayırır.
Dosyada çalışma anındaki geçerli düğme/ilerleme durumu saklanmadığından uydurulmaz.
Temel fare dağıtımı ters dosya sırasındadır; durum, görünürlük ve kontrolün özel
kodları bu sırayı etkileyebilir. Bunlar referans N3 davranışıdır, kapalı client
üzerinde yürütülerek doğrulanmış sonuçlar değildir.

Sıfır olmayan taşıma dikdörtgenleri ve düğme tıklama dikdörtgenleri için
`layout.interaction_regions`, öğeye ve köke göre koordinatları ayrıca verir.
Yazılarda `text_layout` istenen hizalamadır. Gerçek karakter konumları ve satır
kırılımı font ölçülerine, metin boyuna ve çalışma anındaki kodlamaya bağlıdır;
dosyadaki dikdörtgenden tek başına hesaplanamaz.

`image.quad` kayıtlı canvas sınırları ve UV çiftlerinden oluşur. Eski Direct3D 9
çizicisinin kullandığı yarım piksel düzeltmesi JSON koordinatlarına uygulanmaz;
yerel çizici köşeleri oluştururken x/y'den 0.5 çıkarır.

### Doku kesimi

UV'ler dosyadaki dört `float32` değerin karşılıklarıdır. Doku boyutu gerçek
dosyanın başlığından okunabildiyse:

```text
source_left   = u_left   × texture_width
source_top    = v_top    × texture_height
source_right  = u_right  × texture_width
source_bottom = v_bottom × texture_height
```

Piksel kesimleri yuvarlanmaz veya 0–1 UV aralığına sıkıştırılmaz. Ters yönde
UV kullanan öğelerde `flip_x` / `flip_y` belirtilir. Kaynak boyutu bilinmiyorsa
UV korunur; piksel kesimi üretilmez.

Doku bilgisi yalnızca başlıktan alınır. Bu proje DXT'yi PNG'ye çevirmez;
DXT1–DXT5 dahil format adını, boyutunu ve UIF'nin kullanımını çıkarır.

### Düğme ve kontrol rolleri

Düğme altındaki görselin `reserved` değeri 0 normal, 1 basılı, 2 hover/işaretli,
3 devre dışı görselini belirtir. Progress kontrolünde 0 arka plan, 1 ön plandır.
Trackbar'da 0 arka plan, 1 tutamaçtır. Tanımsız değerler ham olarak korunur.

N3 `AddChild`, öğeleri listenin başına ekler. Yükleyiciler bu listeyi dolaşıp
aynı durum/rol referansını tekrar atadığından, çakışmada fiziksel dosya sırasındaki
ilk aday etkindir. `effective_state_images` / `effective_control_parts` bu seçimi
gösterir. Düğmede seçili durum referansları dışındaki alt öğeler ayrıca çizilir;
`always_render_children` bunları listeler. Static/edit için etkin referans seçimi
diğer alt öğelerin çizilmediği anlamına gelmez.

Animasyon yükleyicisi alt görselleri ters fiziksel dosya sırasıyla kare dizisine
alır; `reserved` değerinin dizinle eşitliğini denetler. `image.frames` bu sırayı,
alt öğedeki `animation_frame_index` hesaplanan dizini gösterir. Orijinal
`reserved` değiştirilmez. `frame_count`, `cycle_seconds` ve
`frame_order_matches_reserved` ayrıca bulunur. Pozitif FPS ve en az bir kare
olmadan çevrim süresi üretilmez.

`area_type_name`, N3UIArea'nın doğrulanmış 0–12 numaralı alan türlerinin adıdır.
Bilinmeyen sayılarda ad `null` kalır ve kapsam raporuna kayıt eklenir.

## Kapsam raporları

Her belge kendi `coverage` verisini içerir. Toplu `coverage_report.json`,
başarılı/bayt doğrulanan dosya ve bayt sayılarını, kodlama dağılımını ve
`uninterpreted_fields` gruplarını içerir. Her grup ham değeri, alan adını,
kontrol türünü, ilgili UIF/JSON yollarını ve öğe UID'lerini gösterir.

Sıfır ek baytlar da anlamı doğrulanmamış veri kabul edilir. Alanın okunması ve
saklanması ile anlamının bilinmesi farklı kapsamlardır. Tür 11/12/13 ve
doğrulanmamış başlık etiketleri için destek iddia edilmez; bunlar açık hata verir.
Hiçbir rapor, oyunun kodunu veya sunucu davranışını UIF'den çıkardığını iddia etmez.

`resource_index.json`, mevcut doku ters indeksini `textures` altında ve
ses/Flash eşleşmelerini `other_resources` altında bir araya getirir.

## TBL okuma ve bağlantı biçimi

TBL analizi varsayılan olarak client kökündeki bütün `.tbl` dosyalarını kapsar;
`--no-tbl` ile kapatılabilir. Seçilen UIF alt klasörü TBL tarama kapsamını
daraltmaz. Reparse point ve sembolik bağlantılar takip edilmez.

### Şifreleme ve içerik

Desteklenen modern zarfın ilk 16 baytı
`4c26437f80f1579879fcaf2686d6208e`, sonraki 4 baytı big-endian düz veri boyutudur.
Payload 8 baytlık bloklardan oluşur. IP/FP içermeyen DES varyantı ve ardından
16 bit LCG çözümü uygulanır. Zarf boyutu ve en fazla 7 baytlık dolgu denetlenir.

Zarfsız tabloda şifresiz, modern LCG ve klasik LCG adayları denenir. Hiçbir
aday yalnızca okunabilir birkaç dize bulunduğu için kabul edilmez: tipli tablo
tam tüketilmeli ve düz veri alanlardan birebir yeniden oluşturulmalıdır.

Modern içerik 5 opak başlık baytı, `uint32 column_count`, sütun başına
`uint32 type_id`, `uint32 row_count` ve sıkı paketli hücreler içerir. Klasik
içerik doğrudan sütun sayısıyla başlar. Modern 5 baytlık başlığın anlamı
varsayılmaz ve `content_header_hex` içinde korunur.

| Tip ID | Temsil |
| --- | --- |
| 1 / 2 | int8 / uint8 |
| 3 / 4 | int16 / uint16 |
| 5 / 6 | int32 / uint32 |
| 7 | uint32 bayt uzunluğu + ham dize baytları |
| 8 | float32; sonlu olmayan değerlerde `raw_hex` |
| 9 | Anlamı sürüme göre değişebilen 8 bayt; `raw_hex` korunur. |
| 10 | int64 |

Dosya boyutu 128 MiB, sütun sayısı 4096, satır sayısı 1 milyon, hücre sayısı
8 milyon ve tek dize uzunluğu 1 MiB ile sınırlandırılır. Okuma sınırları,
satır aralıkları ve düz veri yeniden oluşturma eşitliği denetlenir.

`tbl/**/*.json` alanları:

- `source`: Şifreli/orijinal dosyanın yolu, boyutu ve SHA-256'sı.
- `format`: Kullanılan şifre çözme biçimi ve metin kodlaması.
- `content_profile`, `content_header_hex`, `column_types`, `columns`: İçerik düzeni ve ham sütun türleri.
- `rows`: `index`, ilk sayısal hücreden `key`, tipli `values` ve `binary` aralıkları.
- `rows[].binary.strings`: ASCII dışındaki veya kodlama seçimiyle değişen dizelerin
  sütun numarasına göre ham hex/kodlama/konum bilgisi. Diğer dizeler ASCII ile birebir temsil edilir.
- `integrity`: Düz veri SHA-256'sı, tam tüketim ve `plaintext_reconstruction: exact_match`.
- `references`: Dosya uzantısı taşıyan dize hücreleri ve client dosyası eşleşmeleri.

Bu araç şifreli TBL dosyalarını yeniden yazmaz. Birebir doğrulanan veri,
şifre çözümü sonrası düz tablo içeriğidir; şifreli kaynak dosyanın bütünlük
kimliği ayrıca `source.sha256` ile tutulur.

### Bağlantı kanıtları

`tbl_uif_links.json.direct_uif_links`, `.uif` yolu taşıyan dize hücrelerini
`table`, `table_json`, `row_index`, `row_key`, `column_index`, `byte_offset`,
`reference` ve `resource` ile tanımlar. İndeksler sıfır tabanlıdır; `byte_offset`
şifre çözümü sonrası dize uzunluk alanının konumudur. Kaynak eşleştirme yöntemi
ve eksik/belirsiz sonuçlar korunur. `uif_json`, yalnızca o UIF bu taramada
başarıyla dışa aktarılmışsa doldurulur. UIF belgesinin `table_links` listesi
aynı bağlantıların ters yönünü sağlar. DXT'ye geçiş için bu belgenin `textures`
listesi ve `texture_index.json` kullanılabilir.

`other_file_references`, TBL içindeki DXT/görüntü/ses/Flash/TBL/FXB/N3/font yollarını
gösterir. Bu liste, türlenmiş bir dize hücresinin dosya yolu biçimindeki
değerini kanıtlar; kapalı client'in o hücreyi mutlaka kullandığını kanıtlamaz.

`tbl_text_matches.json`, en az 4 karakter uzunluğunda boş olmayan yazının TBL
ve UIF'de birebir eşit olduğu yerleri listeler. `is_runtime_binding: false`
alanı zorunludur. Sayısal benzerliklerden, öğe adlarından veya birden fazla
tabloda aynı ID'nin bulunmasından otomatik ilişki çıkarılmaz. Kodlama belirsizliği
metin eşleşmelerini de etkileyebilir. Oyun içindeki kesin ID → kontrol bağlantısı
client kodu veya çalışma anı gözlemi gerektirir.

`table_index.json` başarısız tabloları da listeler. Başarısız tablonun içeriği
ve bağlantıları başarılı sonuçlara karıştırılmaz. TBL çözümleme hatası çıkış
kodunu 1 yapar; diğer TBL/UIF dosyaları işlenmeye devam eder. Kapatılan TBL
analizi için manifestte `tbl_enabled: false` yer alır; önceki çalışmalardan kalan
TBL JSON'ları o çalışmanın güncel sonucu sayılmaz.

### Sütun ve kodlama denetimi

`table_schema_report.json.tables`, her başarılı tablonun sütunlarını konumsal
olarak profiller. Her profilde tip, satır/tekil değer sayısı, boş/sıfır/negatif
sayısı, opak hücre sayısı, sayısal min/max ve sınırlı örnekler bulunur. En fazla
16 tekil değer varsa gözlenen küçük küme listelenir; enum olduğu iddia edilmez.
Sütun anlamı ve birimi `unknown` kalır. Satır anahtarları için null ve tekrarlı
anahtarlar raporlanır; hiçbir satır çakışma nedeniyle düşürülmez.

Otomatik TBL kodlaması ASCII/UTF-8, ardından klasik profilde CP949 veya modern
profilde geçerli CP949 çıktısındaki Hangul kanıtını değerlendirir; CP1254/CP950
ve CP949 son adaylar olarak denenir. Bu sıra sezgiseldir. Orijinal metin baytları
korunur. Kodlama incelemesi seçilen kodlamayı, farklı geçerli karşılıkları, hücre
konumunu ve sınırlı örnekleri gösterir; hiçbir alternatif kesin dil ilan edilmez.
Tam hücre değeri ve ham baytlar asıl TBL JSON'undadır.

Dosya uzantısı adayları yalnızca sabit bir listeye bağlı değildir: client
envanterindeki uzantılar da tanınır. Görüntü/ses/UIF/model/font/FXB dışındaki
dosyalar `asset` olarak raporlanır. `usage_semantics: not_inferred`, dosyanın
listelenmesinin yüklendiğini kanıtlamadığını belirtir. Örneğin bir bakım
tablosundaki dosya adları oyun içi kullanım anlamına gelmeyebilir.

`table_review_candidates.json` dış URI'leri ve sınıflandırılmamış yol benzeri
hücreleri ham değerleri ve kaynak konumlarıyla listeler. Kontrol karakterleri
ayrıca belirtilir. Satır sonunu backslash'a çevirme gibi onarımlar uygulanmaz.
URI'ler açılmaz. Bu adaylar doğrulanmış kaynak bağlantılarıyla karıştırılmaz.

## Unity aktarım denetimi ve görsel yolları

`screen_index.json` dosya bazında kaynak SHA-256, root bölgesi, kullanım sayıları,
TBL bağlantıları, doku kullanan UID'ler ve font ailelerini verir. Ayrıntılı
öğe verisinin asıl kaynağı ilgili `uif/**/*.json` dosyasıdır. Dosya adından
ekran rolü, varsayılan görünürlük veya kullanılmama sonucu çıkarılmaz.

Her öğede `unity_ugui_geometry`, sabit üst-sol düzen için anchor/pivot `[0,1]`,
`anchored_position: [relative_left,-relative_top]` ve `size_delta: [width,height]`
verir. Parent pivot'unun üst-sol, ölçeğin birim olduğu ve otomatik layout
uygulanmadığı varsayılır. Root için kayıtlı canvas konumu korunur. Bu alanlar
ham koordinatları değiştirmez; dinamik anchor/CanvasScaler çözümü üretmez.

Çözülen doku kaynaklarında `visual_sources` orijinal dosya yolunu, aynı stem'e
sahip DXT'yi ve varsa PNG adaylarını verir. Önce aynı göreli yol, ardından
`outputs/` altında aynalanmış yol, bulunamazsa tekil basename kontrol edilir.
PNG piksel eşitliği denetlenmez; aday yolu üretim zamanı/format doğrulaması
yerine geçmez. DXT veya PNG dönüşümü yapılmaz.

`font_index.json`, her font aile adını kullanan UIF/UID, boyut ve stilleri
gruplar. Client içindeki SFNT/TTF/OTF/TTC name tabloları okunur; aile adı
eşleşmesi yalnızca adaydır. Gerçek font yüzü, kalın/italik yüz seçimi, glif
kapsamı, shaping ve rasterizer eşitliği doğrulanmaz. Kaydedilmiş varsayılan
yazılardaki Unicode kod noktaları ayrıca verilir; sunucu metinleri buna dahil değildir.

`effect_index.json` dönüşüm çıktısı değildir. FXB içindeki bilinen parça
düzeni bağımlılık bulmak için okunur; doku prefix'i ve kare numarasından
`prefix + dört_haneli_dizin + .dxt` yolları türetilir. `images` bu DXT'leri,
çözümleme durumlarını ve mevcut PNG adaylarını verir. `other_dependencies`
model yollarını, `source` ve `absolute_path` orijinal FXB'yi gösterir.
Aktarım yapan AI, FXB dönüşümünü orijinal dosyadan gerçekleştirir.

Bağımlılık okuyucusu N3 base/particle/billboard/mesh/ground düzenlerini sınır
denetimiyle takip eder; sürüme göre 8/16/26 parça yuvası adayları denenir.
Okunan alanlar ve opak ekler bellekte kaynak baytları yeniden oluşturabilmelidir.
Yeni sürüm eklerinin anlamı doğrulanmış sayılmaz. Bu ara alanlar ayrı efekt
JSON'larına aktarılmaz. Desteklenmeyen dosya açıkça raporlanır. Efektin
UI ekranına veya dünya nesnesine çalışma anındaki bağlantısı tahmin edilmez.

`asset_inventory.json` tüm indekslenmiş client dosyalarını kapsar; seçilen
çıktı klasörü ve takip edilmeyen symlink/reparse point'ler tarama dışındadır.
Mevcut `outputs` isimli başka dizinler otomatik elenmez. Dosyanın boyutu,
uzantısı ve çözülen veride referans bulunup bulunmadığı verilir. Referanslı
dosyalar ile UIF/TBL/FXB/fontların SHA-256'sı hesaplanır; diğerlerinde hash
alanının olmaması hesaplanmadığını belirtir. Binary dosyalar kopyalanmaz.

`migration_report.json.pixel_identical_ready` gerçek Unity/client görüntü
karşılaştırması yapılmadan `true` olmaz. Ham bayt doğrulaması; kontrol
anlamları, oyun akışı, ekran yerleşimi veya efekt davranışının bilindiği
anlamına gelmez. `AI_GUIDE.md` tüketiciye bu ayrımı ve veri okuma sırasını açıklar.

## Biçim araştırması

Kayıt düzeni tam tüketim ve bayt yeniden oluşturma kontrolleriyle denetlenir.
Destek kapsamı farklı client sürümlerinde değişebilir. Koordinat/UV ve standart
kontrol davranışları için başvurulan birincil kaynaklar:

- [N3UIBase yükleme, taşıma ve çizim davranışı](https://github.com/Open-KO/KnightOnline/blob/master/src/N3Base/N3UIBase.cpp)
- [N3UIImage UV ve doku kullanımı](https://github.com/Open-KO/KnightOnline/blob/master/src/N3Base/N3UIImage.cpp)
- [N3UIString yazı ve font alanları](https://github.com/Open-KO/KnightOnline/blob/master/src/N3Base/N3UIString.cpp)
- [N3UIDef kontrol ve stil numaraları](https://github.com/Open-KO/KnightOnline/blob/master/src/N3Base/N3UIDef.h)
- [N3UIButton durum seçimi ve çizim](https://github.com/Open-KO/KnightOnline/blob/master/src/N3Base/N3UIButton.cpp)
- [N3UIArea alan türleri](https://github.com/Open-KO/KnightOnline/blob/master/src/N3Base/N3UIArea.h)
- [N3UIBase alt öğe listesi](https://github.com/Open-KO/KnightOnline/blob/master/src/N3Base/N3UIBase.h)
- [Modern TBL şifreleme sabitlerinin kaynağı](https://github.com/ThiagQPie/ko-tbl-editor/blob/main/tbl.py)
- [Klasik N3 TBL tipli okuma](https://github.com/Open-KO/KnightOnline/blob/master/src/N3Base/N3TableBase.h)
- [N3 FX bundle ve parça sırası](https://github.com/Open-KO/KnightOnline/blob/master/src/N3Base/N3FXBundle.cpp)
- [N3 efekt doku prefix/kare bağımlılıkları](https://github.com/Open-KO/KnightOnline/blob/master/src/N3Base/N3FXPartBase.cpp)

Python uygulaması referans istemci kodunu çalıştırmaz ve C++ dosyalarını
paketlemez. Uyarlanan TBL kripto sabitlerinin lisans bildirimi
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) içinde korunur.
