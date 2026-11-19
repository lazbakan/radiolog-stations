# RadioLog — küratörlü istasyon listesi

RadioLog uygulamasının Türkiye kategorilerindeki radyo listesi. Liste her gün
GitHub Actions'ta denetlenir; uygulama sonucu en fazla 12 saatte bir indirir:

    https://raw.githubusercontent.com/lazbakan/radiolog-stations/main/docs/curated.json

| Dosya | Ne işe yarar |
|---|---|
| `tools/curated/stations.json` | Kaynak liste (elle düzenlenebilir: `alternatives`, `uuid`) |
| `tools/curated/check_stations.py` | Günlük denetleyici |
| `tools/curated/state.json` | Hata sayaçları ve adres değişiklikleri (bot yazar) |
| `docs/curated.json` | Uygulamanın indirdiği sonuç (bot yazar) |

Ayrıntılar: [tools/curated/README.md](tools/curated/README.md)
