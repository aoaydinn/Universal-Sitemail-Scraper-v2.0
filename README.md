# Universal Sitemail Scraper v2.0

Modern, kullanıcı arayüzlü (GUI) ve çok parçacıklı (multithreaded) evrensel bir e-posta toplama (scraping) aracıdır. Web sitelerinden, site haritalarından (sitemap), Google arama sonuçlarından (Dork), WHOIS kayıtlarından veya elinizdeki URL listelerinden otomatik olarak e-posta adreslerini kazır. 

Özellikle sitelerin e-postaları gizlemek için kullandığı **Cloudflare Email Protection** sistemini deşifre edebilme yeteneğine sahiptir.

## 🚀 Özellikler

- **Gelişmiş Kaynak Seçenekleri:** Tek bir web adresinden (URL), Sitemap.xml'den, Google Dork sorgularından, WHOIS bilgilerinden veya `.txt/.csv` dosyalarınızdan tarama yapabilirsiniz.
- **Cloudflare Şifre Çözücü:** Cloudflare tarafından şifrelenen (href içerisinde `/cdn-cgi/l/email-protection#...` ve HTML içerisinde `data-cfemail` özelliğiyle saklanan) e-postaları otomatik yakalar ve düz metin olarak çözer.
- **Akıllı Filtreleme (Pattern):** Hedefe yönelik tarama yapar. Belirlediğiniz anahtar kelimeleri içeren linklere öncelik vererek (Örn: sadece URL'sinde `firma` veya `iletisim` geçen sayfalar) tarama süresini ciddi ölçüde kısaltır.
- **Javascript Render (Selenium):** Dinamik olarak JS ile (sonradan) yüklenen sitelerdeki e-postaları yakalamak için arkaplanda gerçek bir tarayıcı simüle eder.
- **Otomatik Temizleme ve Doğrulama:** Sahte e-postaları (`@example.com`, `.png` gibi resim uzantıları vs.) otomatik eler, bulduğu adresleri global olarak tekilleştirir (tekrarlayanları siler) ve size bir güven puanı (`confidence`) sunar.
- **Kolay Dışa Aktarım:** Bulunan benzersiz e-postaları tek tıkla CSV, JSON veya TXT formatında kaydedin.

## 🛠️ Kurulum ve Gereksinimler

Program Python 3.7 ve üzeri sürümlerde çalışmaktadır. Çalıştırmak için bilgisayarınızda Python yüklü olmalıdır.

Gerekli kütüphaneleri yüklemek için komut satırında (Terminal / CMD) şu komutu çalıştırın:

```bash
pip install requests beautifulsoup4
```

**(Opsiyonel Kurulumlar)**  
Eğer Javascript Render (Selenium) ve WHOIS özelliklerini de kullanmak isterseniz aşağıdaki paketleri de kurmalısınız:
```bash
pip install selenium python-whois
```
*(Not: Selenium'un çalışması için bilgisayarınızda Google Chrome yüklü olmalıdır.)*

## 📖 Kullanım Rehberi

Programı başlatmak için komut satırında dosyanın olduğu dizine giderek şu komutu verin:
```bash
python Sitemailscrapper.py
```

Uygulama açıldığında sol panelden ayarları yapılandırıp sağ panelden sonuçları izleyebilirsiniz.

### 1. Kaynak Seçimi
Sol üst menüden tarama yapacağınız veri türünü seçin:
- **Tek URL / Domain:** Belirttiğiniz web sitesinden başlayarak sayfaları (derinlik sınırına kadar) gezer.
- **Sitemap.xml:** Sitenin sitemap dosyasını okur ve haritada tanımlanan tüm sayfaları teker teker tarar.
- **Google Dork:** Örneğin `site:ornek.com "email"` gibi gelişmiş sorgular yaparak dönen siteleri gezer.
- **WHOIS:** Belirttiğiniz domain adresinin kayıt bilgilerini (whois) çeker, sahibinin e-posta bilgisini bulmaya çalışır.
- **URL Listesi:** Bilgisayarınızdaki bir `.txt` dosyasındaki alt alta dizili web sitelerini sırasıyla tarar.

### 2. Gelişmiş Ayarlar
- **Derinlik (Depth):** Ana sayfadan itibaren kaç tıklama derine inileceğini belirler. (2 seçilirse: Ana Sayfa -> Hakkımızda -> Ekibimiz şeklinde ilerler).
- **Max Sayfa:** Uygulamanın en fazla kaç sayfa gezeceği limitidir. Çok büyük sitelerde programın sonsuza kadar çalışmasını engeller.
- **Gecikme (sn):** Her sayfa isteği arasında ne kadar bekleneceği (Rate Limit). `0.5-2.0` yazarsanız yarım saniye ile iki saniye arası rastgele bekler. Site tarafından engellenmemek (ban yememek) için önemlidir.
- **Filtre Pattern:** Sayfa linklerini (URL'leri) filtreler. Araya virgül koyarak (`firma,iletisim`) değerler girerseniz, scrapper sadece linkin içinde bu kelimeler geçen bağlantılara tıklar. Büyük portallarda boş sayfaları atlamak için çok etkilidir.
- **JS Render (Selenium):** Sayfanın kaynak kodunda gözükmeyen ama tarayıcıda gözüken mailler varsa bu seçeneği işaretleyin. Tarama hızı düşer ama başarı oranı artar.
- **Harici linkleri takip et:** Siteden Facebook'a, LinkedIn'e veya başka sitelere link verilmişse oralara da gidilip gidilmeyeceğini ayarlar.

### 3. Tarama ve Dışa Aktarma
- Gerekli hedefleri belirleyip **"▶ BAŞLAT"** butonuna basın.
- **"📋 Log"** sekmesinden aracın anlık ne yaptığını, hataları ve bulduğu yeni mailleri izleyebilirsiniz.
- **"📧 Sonuçlar"** sekmesinde bulduğu geçerli e-postaları listeler. İstediğiniz satıra sağ tıklayıp e-postayı kopyalayabilirsiniz.
- Tarama işlemi bittiğinde sağ üstteki **"💾 CSV, JSON, TXT"** butonlarına tıklayarak sonuçları dışa aktarın.

## 💡 İpuçları & Püf Noktalar
- Sistem akıllıdır; bir sayfanın footer kısmında aynı e-postayı 1000 sayfada görse dahi bunu fark eder ve günlüğe (log) sadece **1 kez** "yeni e-posta bulundu" olarak yazar. Sizi gereksiz log kalabalığından kurtarır.
- Hedef sitede Cloudflare koruması varsa hiçbir ayar yapmanıza gerek yoktur, sistem algıladığı an arka planda kendi şifrelerini çözer ve gerçek e-postayı size ulaştırır.
