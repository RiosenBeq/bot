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
   "Bekçi" bölümü.
2. **İkinci fabrika gelince.** Her programa farklı `UZAK_PANO_TESIS_ID`; ana tesisi
   sabitlemek için Vercel'de `ANA_TESIS`. Kimlik göndermeyen (eski) bir program canlı
   rapor gönderdikçe hiçbir tesis komut almaz; Tesisler ekranı bunu uyarıyla söyler.
3. **Yayın sonrası bir kez:** Vercel panosunda son yayının Runtime Logs'una bakın. Bekçi
   açılmadıysa günde bir 403 satırı (Vercel Cron, CRON_SECRET yok) olağandır.

## Teknik işler

1. **Çoklu tesis tam ayrımı:** tesis başına pano, komut kuyruğu, bekçi eşiği ve hesap
   yetkisi (bir operatör yalnız kendi tesisine). İkinci saha gerçekten gelince.
2. **Aynı tesis kimliği iki bilgisayarda:** tesis özetine bilgisayar adı ekleyip
   Tesisler ekranında "kimlik çakışması" uyarısı göstermek. Bugün yalnız belgede uyarı var.
3. **Vercel Pro'ya geçilirse** `vercel.json` cron'unu `*/5 * * * *` yapmak. Hobby'de
   alt-günlük cron yayını durdurur; değiştirmeyin.
