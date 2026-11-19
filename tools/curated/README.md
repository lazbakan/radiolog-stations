# Küratörlü liste — sunucu tarafı denetim

Uygulama, küratörlü radyo listesini (Türkiye kategorileri) her açılışta değil, en fazla
**12 saatte bir** sunucudan indirir. Liste her gün GitHub Actions'ta denetlenir:

| Durum | Ne olur |
|---|---|
| Yayın açılıyor | `ok: true` |
| Açılmıyor ama yeni adresi bulundu | Adres güncellenir, `replacements` listesine `eski → yeni` eklenir. Uygulama kullanıcıların **kütüphanesindeki/favorilerindeki** eski adresi de kendiliğinden düzeltir. |
| 1 gün açılmadı | Listede kalır (geçici kesinti olabilir) |
| 2 gün üst üste açılmadı | `ok: false` → uygulamada gizlenir; düzelince geri gelir |

Yeni adres şu sırayla aranır: `stations.json`'daki `alternatives` → Radio Browser'da aynı
kimlik (`uuid`) → aynı ad + ülke. Bulunan adres de gerçekten ses verdiği doğrulanmadan kullanılmaz.

## Kurulum (bir kez)

1. Bu klasörün içeriğini **herkese açık** `radiolog-stations` deposuna yükle.
2. **Settings → Actions → General → Workflow permissions**: "Read and write" seç
   (bot günlük sonucu depoya yazar).
3. Uygulamadaki `CURATED_JSON_URL` şu adresi okur:
   `https://raw.githubusercontent.com/azasdestek/radiolog-stations/main/docs/curated.json`
4. Actions sekmesinden **"Küratörlü radyo listesini denetle" → Run workflow** ile ilk çalıştırmayı yap.

Uygulamadaki listeyi (`CuratedStations.kt`) değiştirirsen ana projede
`python tools/curated/export_from_app.py` çalıştırıp yeni `stations.json`'ı bu depoya kopyala.

## Dosyalar

- `stations.json` — kaynak liste (elle düzenlenebilir). İsteğe bağlı alanlar:
  `uuid` (Radio Browser kimliği), `alternatives` (yedek adresler), `favicon`.
- `state.json` — günlük hata sayaçları ve adres değişiklikleri (bot yazar).
- `../../docs/curated.json` — uygulamanın indirdiği sonuç (bot yazar).
- `export_from_app.py` — `CuratedStations.kt` değişince kaynak listeyi yeniden üretir
  (elle eklenen `uuid`/`alternatives` korunur).

## Yerelde deneme

```bash
python tools/curated/check_stations.py --limit 20
```
