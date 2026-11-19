#!/usr/bin/env python3
"""
RadioLog küratörlü liste denetleyicisi — her gün sunucuda (GitHub Actions) çalışır.

Ne yapar:
  1. stations.json'daki her yayını açıp gerçekten ses geldiğini doğrular
     (HLS'de oynatma listesini ve ilk parçayı da kontrol eder).
  2. Açılmayan yayın için sırayla dener: elle verilen "alternatives" adresleri, sonra
     Radio Browser'da aynı kimlik (uuid) ya da aynı ad + ülke. Çalışan yeni adres
     bulunursa stations.json güncellenir ve "replacements" listesine eklenir
     (uygulama kullanıcıların kütüphanesindeki eski adresi de düzeltir).
  3. Art arda FAIL_DAYS gün açılmayan istasyon "ok": false yapılır (uygulamada gizlenir).
     Tek günlük kesinti listeden düşürmez.
  4. Çıktı: ../../docs/curated.json (uygulamanın indirdiği dosya) + state.json (sayaçlar).

Kullanım:
    python tools/curated/check_stations.py            # tam denetim
    python tools/curated/check_stations.py --limit 20 # deneme
"""
import argparse
import datetime as dt
import http.client
import json
import re
import socket
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
STATIONS = HERE / "stations.json"
STATE = HERE / "state.json"
OUT = ROOT / "docs" / "curated.json"

UA = "RadioLogCurator/1.0 (+https://github.com)"
TIMEOUT = 12
MIN_AUDIO_BYTES = 16 * 1024
FAIL_DAYS = 2
MAX_REPLACEMENTS = 500
RB_MIRRORS = [
    "https://de1.api.radio-browser.info",
    "https://de2.api.radio-browser.info",
    "https://fi1.api.radio-browser.info",
]

AUDIO_TYPES = ("audio/", "application/ogg", "video/mp2t")
HLS_TYPES = ("mpegurl", "x-mpegurl", "vnd.apple.mpegurl")
PLAYLIST_TYPES = ("audio/x-scpls", "audio/scpls", "audio/x-mpegurl", "audio/mpegurl")

_ctx = ssl.create_default_context()


def _open(url, extra_headers=None, timeout=TIMEOUT):
    headers = {"User-Agent": UA, "Icy-MetaData": "0"}
    if extra_headers:
        headers.update(extra_headers)
    req = urllib.request.Request(url, headers=headers)
    return urllib.request.urlopen(req, timeout=timeout, context=_ctx)


def _read_some(resp, want):
    got = 0
    while got < want:
        chunk = resp.read(min(8192, want - got))
        if not chunk:
            break
        got += len(chunk)
    return got


def check_stream(url, depth=0, timeout=TIMEOUT):
    """(ok, sebep) döner."""
    if depth > 2:
        return False, "çok fazla yönlendirme"
    try:
        with _open(url, timeout=timeout) as resp:
            ctype = (resp.headers.get("Content-Type") or "").split(";")[0].strip().lower()
            final_url = resp.geturl()
            path = urllib.parse.urlparse(final_url).path.lower()

            if any(t in ctype for t in HLS_TYPES) or path.endswith(".m3u8"):
                text = resp.read(256 * 1024).decode("utf-8", "replace")
                return check_hls(final_url, text, depth)

            if ctype in PLAYLIST_TYPES or path.endswith((".pls", ".m3u")):
                text = resp.read(64 * 1024).decode("utf-8", "replace")
                inner = first_playlist_entry(text)
                if not inner:
                    return False, "boş çalma listesi"
                return check_stream(urllib.parse.urljoin(final_url, inner), depth + 1, timeout)

            if not (ctype.startswith(AUDIO_TYPES) or ctype in ("", "application/octet-stream")):
                return False, f"ses değil ({ctype})"
            got = _read_some(resp, MIN_AUDIO_BYTES)
            if got < MIN_AUDIO_BYTES:
                return False, f"yalnızca {got} bayt geldi"
            return True, ctype or "audio"
    except http.client.BadStatusLine as e:
        # Eski Shoutcast "ICY 200 OK" — Python tanımıyor ama yayın çalışıyor
        if "ICY" in str(e):
            return True, "icy"
        return False, f"geçersiz yanıt: {e}"
    except urllib.error.HTTPError as e:
        return False, f"HTTP {e.code}"
    except (urllib.error.URLError, socket.timeout, TimeoutError, ConnectionError, OSError) as e:
        return False, f"bağlantı: {getattr(e, 'reason', e)}"
    except Exception as e:  # noqa: BLE001
        return False, f"hata: {e}"


def first_playlist_entry(text):
    for line in text.splitlines():
        line = line.strip()
        if line.lower().startswith("file") and "=" in line:
            return line.split("=", 1)[1].strip()
        if line and not line.startswith("#") and not line.startswith("["):
            return line
    return None


def check_hls(base, text, depth):
    if "#EXTM3U" not in text:
        return False, "HLS değil"
    entries = [l.strip() for l in text.splitlines() if l.strip() and not l.startswith("#")]
    if not entries:
        return False, "boş HLS"
    first = urllib.parse.urljoin(base, entries[0])
    if "#EXT-X-STREAM-INF" in text:
        # Ana liste → ilk varyant
        try:
            with _open(first) as r:
                sub = r.read(256 * 1024).decode("utf-8", "replace")
            return check_hls(first, sub, depth + 1) if depth < 3 else (False, "derin HLS")
        except Exception as e:  # noqa: BLE001
            return False, f"varyant: {e}"
    try:
        with _open(first) as r:
            got = _read_some(r, 4096)
        return (got > 0), "hls" if got > 0 else "boş parça"
    except Exception as e:  # noqa: BLE001
        return False, f"parça: {e}"


def rb_get(path, params):
    q = urllib.parse.urlencode(params)
    for m in RB_MIRRORS:
        try:
            with _open(f"{m}{path}?{q}", timeout=15) as r:
                return json.loads(r.read().decode("utf-8"))
        except Exception:  # noqa: BLE001
            continue
    return []


TOKEN_PARAMS = {"sid", "session", "token", "auth", "key", "expires", "exp", "e", "zt",
                "st", "sig", "signature", "hash", "hdnts", "hdnea", "wmsauthsign"}
SESSION_PATH = re.compile(r"chunklist_w\d+|/session[_-]?id/|playlist_w\d+", re.I)


def looks_tokenized(url):
    """Oturum/imza taşıyan adres birkaç saat sonra ölür; kalıcı adres sayılmaz."""
    p = urllib.parse.urlparse(url)
    q = urllib.parse.parse_qs(p.query)
    return any(k.lower() in TOKEN_PARAMS for k in q) or bool(SESSION_PATH.search(p.path))


def find_replacement(st):
    """Çalışan yeni adres + (varsa) Radio Browser bilgisi."""
    candidates = []
    for alt in st.get("alternatives") or []:
        candidates.append({"url": alt})
    if st.get("uuid"):
        candidates += rb_get("/json/stations/byuuid", {"uuids": st["uuid"]})
    params = {"name": st["name"], "hidebroken": "true", "order": "clickcount",
              "reverse": "true", "limit": "6"}
    if st.get("countryCode"):
        params["countrycode"] = st["countryCode"]
    candidates += [c for c in rb_get("/json/stations/search", params)
                   if (c.get("name") or "").strip().lower() == st["name"].strip().lower()]

    tried = set()
    for c in candidates:
        url = c.get("url_resolved") or c.get("url")
        if not url or url == st["url"] or url in tried or looks_tokenized(url):
            continue
        tried.add(url)
        ok, _ = check_stream(url)
        if ok:
            return url, c
    return None, None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--workers", type=int, default=16)
    args = ap.parse_args()

    stations = json.loads(STATIONS.read_text(encoding="utf-8"))
    state = json.loads(STATE.read_text(encoding="utf-8")) if STATE.exists() else {}
    fails = state.get("fails", {})
    replacements = state.get("replacements", {})
    today = dt.date.today().isoformat()

    todo = stations[: args.limit] if args.limit else stations

    # 1) Hızlı paralel tur
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        first = list(ex.map(lambda st: check_stream(st["url"]), todo))

    # 2) Açılmayanlar tek tek, yavaşça yeniden denenir: aynı barındırma sunucusundaki
    #    birçok istasyona aynı anda bağlanmak bazı sunucularda zaman aşımına düşüyor.
    #    Ancak ikinci denemede de açılmayan için yeni adres aranır.
    results = []
    for st, (ok, why) in zip(todo, first):
        if not ok:
            time.sleep(0.5)
            ok, why2 = check_stream(st["url"], timeout=20)
            why = why if ok else why2
        if ok:
            results.append((st, True, why, None, None))
        else:
            new_url, info = find_replacement(st)
            results.append((st, False, why, new_url, info))

    n_ok = n_fixed = n_dead = 0
    for st, ok, why, new_url, info in results:
        key = st["url"]
        if ok:
            fails.pop(key, None)
            st["ok"] = True
            n_ok += 1
            continue
        if new_url:
            print(f"ONARILDI  {st['name']}: {key} -> {new_url}")
            replacements[key] = new_url
            # Zincirleme eski adresler de yeni adrese gitsin
            for old, tgt in list(replacements.items()):
                if tgt == key:
                    replacements[old] = new_url
            fails.pop(key, None)
            st["url"] = new_url
            if info:
                st["uuid"] = info.get("stationuuid") or st.get("uuid")
                if not st.get("favicon") and info.get("favicon"):
                    st["favicon"] = info["favicon"]
            st["ok"] = True
            n_fixed += 1
            continue
        rec = fails.get(key, {"days": 0, "last": None})
        if rec.get("last") != today:
            rec = {"days": rec.get("days", 0) + 1, "last": today}
        fails[key] = rec
        st["ok"] = rec["days"] < FAIL_DAYS
        st["lastError"] = why
        if not st["ok"]:
            n_dead += 1
        print(f"HATA({rec['days']}g) {st['name']}: {why}")

    # En yeni değişiklikler kalsın
    if len(replacements) > MAX_REPLACEMENTS:
        replacements = dict(list(replacements.items())[-MAX_REPLACEMENTS:])

    STATIONS.write_text(json.dumps(
        [{k: v for k, v in s.items() if k not in ("ok", "lastError")} for s in stations],
        ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    STATE.write_text(json.dumps({"fails": fails, "replacements": replacements},
                                ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    out = {
        "version": 1,
        "updated": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "stations": [{k: v for k, v in s.items() if k not in ("alternatives", "lastError") and v is not None}
                     for s in stations],
        "replacements": replacements,
    }
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")

    print(f"\nÇalışan {n_ok}, onarılan {n_fixed}, gizlenen {n_dead}, toplam {len(stations)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
