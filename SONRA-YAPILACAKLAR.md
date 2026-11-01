# Sonra yapılacaklar - site (01.11.2026)

Sitedeki bekçi ("sistemden haber yok" alarmı) ve çoklu tesis görünümü main'dedir; hepsi
isteğe bağlıdır ve ortam değişkenleri yazılmadıkça site bugünkü gibi çalışır. Bu dosya
sitede KALAN işleri toplar. Programla birlikte bütün liste DALSAN deposunda:
`docs/SONRA-YAPILACAKLAR.md`.

## Sahibin yapacakları (kod gerekmez)

1. **Bekçiyi açmak (isteğe bağlı, önerilir).** Vercel, Settings, Environment Variables
   (Production): `BEKCI=acik`, `BEKCI_ESIK_DK`, `BEKCI_ALICILAR`, `BEKCI_ANAHTARI`, e-posta
   için `SMTP_*`, Telegram için `TELEGRAM_BOT`, Vercel Cron için `CRON_SECRET`; sonra
   Redeploy. Hobby'de cron günde bir çalışır: cron-job.org'da her 5 dakikada
   `/api/bekci` adresine `Authorization: Bearer <BEKCI_ANAHTARI>` başlığıyla istek kurun
   (UptimeRobot ücretsiz planı başlık ekleyemez, `?anahtar=` kullanın). Ayrıntı: README,
   "Bekçi" bölümü. D3 bitene kadar `/api/bekci` HEAD'e 405 döner: GET gönderen
   cron-job.org'u kullanın. Değerleri Türkçe harf olmadan yazın (`acik`; D4).
2. **İkinci fabrika gelince.** Her programa farklı `UZAK_PANO_TESIS_ID`; ana tesisi
   sabitlemek için Vercel'de `ANA_TESIS`. **D1 bitmeden ikinci tesisi bağlamayın.**
3. **Yayın sonrası bir kez:** Vercel panosunda son yayının Runtime Logs'una bakın. Bekçi
   açılmadıysa günde bir 403 satırı (Vercel Cron, CRON_SECRET yok) olağandır.

## Teknik işler

1. **Çoklu tesis tam ayrımı:** tesis başına pano, komut kuyruğu, bekçi eşiği ve hesap
   yetkisi (bir operatör yalnız kendi tesisine). İkinci saha gerçekten gelince.
2. **Aynı tesis kimliği iki bilgisayarda:** tesis özetine bilgisayar adı ekleyip
   Tesisler ekranında "kimlik çakışması" uyarısı göstermek. Bugün yalnız belgede uyarı var.
3. **Vercel Pro'ya geçilirse** `vercel.json` cron'unu `*/5 * * * *` yapmak. Hobby'de
   alt-günlük cron yayını durdurur; değiştirmeyin.

## Karşıt incelemenin bulguları - düzeltmesi yarım

Düzeltmelerine başlandı; yarım iş `oneriler-ek` dalındaki ara kayıtlardadır, doğrulanmadığı
için main'e girmedi. Hepsi varsayılan kapalı özelliklerdedir. Numaralar DALSAN deposundaki
listeyle aynıdır.

- **D1 (yüksek, yalnız tesis kimliği kullanılınca).** Kimlik göndermeyen (eski) bir program
  canlıyken bir tesis de ana olabiliyor (`ANA_TESIS` yazılıysa ya da tesis daha önce ana
  olduysa): iki fabrika birden komut alır, pano ikisi arasında gidip gelir. `_tesis_kaydet`'in
  her dalında ve `komut_al`'da "kimliksiz program canlı mı" denetimi; Tesisler'de uyarı.
- **D2 (düşük).** İzleyicinin reddedilen müdahale denemesi işlem kaydına yazılmıyor
  (`_durum_degistiren` 403'ü kayıttan önce veriyor; docs/19 §3.3).
- **D3 (düşük).** `/api/bekci` HEAD'e 405 dönüyor: `api/bekci.py`'ye `do_HEAD = do_GET`.
- **D4 (düşük).** `ANA_TESIS=İzmir`, `BEKCI=açık` sessizce etkisiz: Türkçe harf
  sadeleştirme ve doğrulama; tanınmayan `BEKCI` değeri 503 ile söylensin.
- **D5 (düşük).** Ana tesis değişince bekçi susan yeni ana tesisi değil eski ana tesisi
  adlandırıyor.
- **D6 (düşük).** Bekçi açıkken her rapora bir `DEL` ekleniyor (ayda yaklaşık 86 bin Upstash
  komutu): işaret `MGET`'e katılsın, `DEL` yalnız işaret varken.
- **D7 (düşük).** README: her fabrikanın kimliği farklı olmalı; UptimeRobot notu.
