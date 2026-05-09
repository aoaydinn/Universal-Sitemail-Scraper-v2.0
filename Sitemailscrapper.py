#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════════════════════╗
║           UNIVERSAL SITEMAIL SCRAPER v2.0 (GUI)                ║
║  Çok Kaynaklı • Otomatize • Thread'li • Filtrelemeli           ║
║  Destek: Sitemap, HTML Crawl, JS Render, Google Dork, WHOIS    ║
╚══════════════════════════════════════════════════════════════════╝
"""

import re
import sys
import os
import csv
import json
import time
import random
import hashlib
import threading
import queue
import ssl
import xml.etree.ElementTree as ET
from datetime import datetime
from typing import Set, List, Optional, Dict, Tuple, Callable
from dataclasses import dataclass, field
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urljoin, urlparse, parse_qs
from collections import OrderedDict
import webbrowser

# --- GUI ---
import tkinter as tk
from tkinter import ttk, scrolledtext, filedialog, messagebox

# --- HTTP & Parsing ---
try:
    import requests
    from requests.adapters import HTTPAdapter
    from urllib3.util.retry import Retry
except ImportError:
    requests = None

try:
    from bs4 import BeautifulSoup
except ImportError:
    BeautifulSoup = None

try:
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    SELENIUM_AVAILABLE = True
except ImportError:
    SELENIUM_AVAILABLE = False

try:
    import whois
    WHOIS_AVAILABLE = True
except ImportError:
    WHOIS_AVAILABLE = False


# ╔══════════════════════════════════════════════════╗
# ║               VERİ YAPILARI                      ║
# ╚══════════════════════════════════════════════════╝

@dataclass
class ScrapedEmail:
    """Kazınan her e-posta için zengin metadata"""
    email: str
    source_url: str
    found_on_page: str = ""
    context_snippet: str = ""
    confidence: float = 0.0
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    
    def __hash__(self):
        return hash(self.email.lower().strip())
    
    def __eq__(self, other):
        return self.email.lower().strip() == other.email.lower().strip()
    
    def to_dict(self) -> dict:
        return {
            'email': self.email,
            'source_url': self.source_url,
            'found_on_page': self.found_on_page,
            'context_snippet': self.context_snippet,
            'confidence': self.confidence,
            'timestamp': self.timestamp
        }


@dataclass
class ScrapingStats:
    """İstatistik takibi"""
    pages_crawled: int = 0
    pages_failed: int = 0
    emails_found: int = 0
    duplicate_removed: int = 0
    start_time: float = field(default_factory=time.time)
    sources_processed: int = 0
    
    @property
    def elapsed_seconds(self) -> float:
        return time.time() - self.start_time
    
    def summary(self) -> str:
        mins = int(self.elapsed_seconds // 60)
        secs = int(self.elapsed_seconds % 60)
        return (
            f"📊 Tarama Tamamlandı\n"
            f"├─ Sayfa: {self.pages_crawled} başarılı, {self.pages_failed} hatalı\n"
            f"├─ E-posta: {self.emails_found} bulundu\n"
            f"├─ Duplicate: {self.duplicate_removed} kaldırıldı\n"
            f"├─ Kaynak: {self.sources_processed} işlendi\n"
            f"└─ Süre: {mins}d {secs}s"
        )


# ╔══════════════════════════════════════════════════╗
# ║              ANA SCRAPER SINIFI                   ║
# ╚══════════════════════════════════════════════════╝

class UniversalEmailScraper:
    """
    Evrensel e-posta kazıyıcı.
    Desteklenen kaynaklar:
    1. Doğrudan URL (HTML parse)
    2. Sitemap.xml (rekürsif tüm URL'leri çıkarır)
    3. Google Dork (arama motoru üzerinden)
    4. WHOIS (domain kayıt bilgileri)
    5. JavaScript Render (Selenium ile dinamik sayfalar)
    """
    
    # RFC 5322 uyumlu e-posta regex'i
    EMAIL_PATTERN = re.compile(
        r'(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b',
        re.IGNORECASE
    )
    
    # Sahte / geçersiz e-postaları filtrelemek için pattern'ler
    FAKE_EMAIL_PATTERNS = [
        re.compile(r'@example\.com$', re.I),
        re.compile(r'@test\.com$', re.I),
        re.compile(r'@domain\.com$', re.I),
        re.compile(r'@email\.com$', re.I),
        re.compile(r'@yourdomain\.com$', re.I),
        re.compile(r'^user@', re.I),
        re.compile(r'^info@example', re.I),
        re.compile(r'@yoursite\.com$', re.I),
        re.compile(r'@sample\.', re.I),
        re.compile(r'@\w+\.local$', re.I),
        re.compile(r'@\w+\.invalid$', re.I),
        re.compile(r'@\w+\.test$', re.I),
        re.compile(r'\.png$|\.jpg$|\.gif$|\.svg$|\.webp$', re.I),
    ]
    
    # Yaygın kullanıcı adları (confidence artırma için)
    COMMON_LOCAL_PARTS = {
        'info', 'contact', 'support', 'sales', 'admin', 'hello',
        'marketing', 'hr', 'careers', 'jobs', 'media', 'press',
        'billing', 'office', 'team', 'help', 'service', 'business'
    }
    
    @staticmethod
    def decode_cloudflare_email(encoded_string: str) -> str:
        """
        Cloudflare'in email obfuscation sistemini çözer.
        Format: hexadecimal XOR anahtarı + şifrelenmiş veri
        """
        try:
            # İlk iki karakter hex anahtar
            key = int(encoded_string[:2], 16)
            decoded = ''
            # Geri kalan her iki hex karakteri bir byte olarak çöz
            for i in range(2, len(encoded_string), 2):
                char_code = int(encoded_string[i:i+2], 16) ^ key
                decoded += chr(char_code)
            return decoded
        except:
            return ""

    def __init__(
        self,
        max_depth: int = 2,
        max_pages: int = 500,
        delay_range: Tuple[float, float] = (0.5, 2.0),
        timeout: int = 15,
        user_agent: Optional[str] = None,
        use_selenium: bool = False,
        respect_robots_txt: bool = True,
        follow_external: bool = False,
        verify_ssl: bool = True,
        proxy: Optional[str] = None,
        filter_patterns: Optional[List[str]] = None,
        callback_progress: Optional[Callable] = None,
        callback_email: Optional[Callable] = None,
        callback_log: Optional[Callable] = None,
        stop_event: Optional[threading.Event] = None,
    ):
        self.max_depth = max_depth
        self.max_pages = max_pages
        self.delay_range = delay_range
        self.timeout = timeout
        self.user_agent = user_agent or self._default_user_agent()
        self.use_selenium = use_selenium and SELENIUM_AVAILABLE
        self.respect_robots_txt = respect_robots_txt
        self.follow_external = follow_external
        self.verify_ssl = verify_ssl
        self.proxy = proxy
        self.filter_patterns = filter_patterns or []
        self.callback_progress = callback_progress
        self.callback_email = callback_email
        self.callback_log = callback_log
        self.stop_event = stop_event or threading.Event()
        
        # Durum değişkenleri
        self.visited_urls: Set[str] = set()
        self.found_emails: Set[ScrapedEmail] = set()
        self.stats = ScrapingStats()
        self.session = self._create_session()
        self.driver = None
        
        # Domain bazlı robots.txt cache
        self._robots_cache: Dict[str, bool] = {}
        
        # Selenium driver başlat
        if self.use_selenium:
            self._init_selenium()
    
    def _default_user_agent(self) -> str:
        """Gerçekçi bir User-Agent oluştur"""
        agents = [
            # Chrome Windows
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
            # Firefox Windows
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0',
            # Safari Mac
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 14_4) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15',
            # Edge
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36 Edg/124.0.0.0',
        ]
        return random.choice(agents)
    
    def _create_session(self) -> requests.Session:
        """Retry ve backoff ile session oluştur"""
        session = requests.Session()
        
        retry_strategy = Retry(
            total=3,
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["GET", "HEAD"]
        )
        adapter = HTTPAdapter(max_retries=retry_strategy, pool_connections=10, pool_maxsize=50)
        session.mount("https://", adapter)
        session.mount("http://", adapter)
        
        session.headers.update({
            'User-Agent': self.user_agent,
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'tr-TR,tr;q=0.9,en-US;q=0.8,en;q=0.7',
            'Accept-Encoding': 'gzip, deflate',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
            'Cache-Control': 'max-age=0',
        })
        
        if self.proxy:
            session.proxies = {
                'http': self.proxy,
                'https': self.proxy
            }
        
        return session
    
    def _init_selenium(self):
        """Headless Chrome başlat"""
        try:
            options = Options()
            options.add_argument('--headless=new')
            options.add_argument('--no-sandbox')
            options.add_argument('--disable-dev-shm-usage')
            options.add_argument('--disable-gpu')
            options.add_argument('--window-size=1920,1080')
            options.add_argument(f'user-agent={self.user_agent}')
            options.add_argument('--disable-blink-features=AutomationControlled')
            options.add_experimental_option('excludeSwitches', ['enable-automation'])
            options.add_experimental_option('useAutomationExtension', False)
            
            if self.proxy:
                options.add_argument(f'--proxy-server={self.proxy}')
            
            # SSL hatalarını yoksay (gerekirse)
            if not self.verify_ssl:
                options.add_argument('--ignore-certificate-errors')
                options.add_argument('--allow-insecure-localhost')
            
            self.driver = webdriver.Chrome(options=options)
            self.driver.set_page_load_timeout(self.timeout)
            self._log("✓ Selenium driver başlatıldı (headless Chrome)")
        except Exception as e:
            self._log(f"⚠ Selenium başlatılamadı: {e}")
            self.use_selenium = False
    
    def _log(self, message: str):
        if self.callback_log:
            self.callback_log(message)
    
    def _emit_progress(self, current: int, total: int, status: str = ""):
        if self.callback_progress:
            self.callback_progress(current, total, status)
    
    def _emit_email(self, email: ScrapedEmail) -> bool:
        if email not in self.found_emails:
            self.found_emails.add(email)
            if self.callback_email:
                self.callback_email(email)
            return True
        return False
    
    def _delay(self):
        """Rate limiting için rastgele bekleme"""
        if self.delay_range[1] > 0:
            time.sleep(random.uniform(*self.delay_range))
    
    def _can_fetch(self, url: str) -> bool:
        """robots.txt kontrolü"""
        if not self.respect_robots_txt:
            return True
        
        parsed = urlparse(url)
        domain = f"{parsed.scheme}://{parsed.netloc}"
        
        if domain in self._robots_cache:
            return self._robots_cache[domain]
        
        try:
            robots_url = urljoin(domain, '/robots.txt')
            resp = self.session.get(robots_url, timeout=10, verify=self.verify_ssl)
            if resp.status_code == 200:
                # Basit kontrol: Disallow: / varsa ve path eşleşiyorsa false
                lines = resp.text.split('\n')
                disallowed = []
                current_agent = None
                for line in lines:
                    line = line.strip().split('#')[0].strip()
                    if not line:
                        continue
                    lowline = line.lower()
                    if lowline.startswith('user-agent:'):
                        current_agent = line.split(':', 1)[1].strip()
                    elif lowline.startswith('disallow:') and (current_agent == '*' or current_agent is None):
                        path = line.split(':', 1)[1].strip()
                        if path:
                            disallowed.append(path)
                
                for dis_path in disallowed:
                    if parsed.path.startswith(dis_path):
                        self._robots_cache[domain] = False
                        return False
                
                self._robots_cache[domain] = True
                return True
        except:
            pass
        
        self._robots_cache[domain] = True
        return True
    
    def _extract_emails_from_text(self, text: str, source_url: str, page_url: str = "") -> Set[ScrapedEmail]:
        """Metinden e-posta çıkar ve filtrele"""
        found = set()
        raw_emails = self.EMAIL_PATTERN.findall(text)
        
        for email in raw_emails:
            email = email.strip().rstrip('.').rstrip(',').rstrip(';').rstrip(':')
            
            # Sahte/geçersiz kontrolü
            is_fake = False
            for pattern in self.FAKE_EMAIL_PATTERNS:
                if pattern.search(email):
                    is_fake = True
                    break
            
            if is_fake:
                continue
            
            # Domain kısmı kontrolü
            try:
                local_part, domain = email.split('@', 1)
                if '.' not in domain or len(domain) < 4:
                    continue
                # En az 2 karakterli TLD
                tld = domain.split('.')[-1]
                if len(tld) < 2 or len(tld) > 24:
                    continue
            except:
                continue
            
            # Confidence hesapla
            confidence = 0.5
            if local_part.lower() in self.COMMON_LOCAL_PARTS:
                confidence += 0.2
            if not any(c.isdigit() for c in local_part):
                confidence += 0.1
            if len(local_part) >= 3 and len(local_part) <= 30:
                confidence += 0.1
            confidence = min(confidence, 0.99)
            
            # Context snippet
            idx = text.lower().find(email.lower())
            start = max(0, idx - 30)
            end = min(len(text), idx + len(email) + 30)
            snippet = text[start:end].strip()
            
            scraped = ScrapedEmail(
                email=email,
                source_url=source_url,
                found_on_page=page_url or source_url,
                context_snippet=snippet,
                confidence=confidence
            )
            found.add(scraped)
        
        return found
    
    def _crawl_url(self, url: str, depth: int = 0) -> Set[ScrapedEmail]:
        """Tek bir URL'yi tara"""
        if self.stop_event.is_set():
            return set()
        
        if url in self.visited_urls:
            return set()
        
        if self.stats.pages_crawled >= self.max_pages:
            return set()
        
        if depth > self.max_depth:
            return set()
        
        if not self._can_fetch(url):
            self._log(f"⊘ robots.txt engeli: {url}")
            return set()
        
        self.visited_urls.add(url)
        self._delay()
        
        all_emails: Set[ScrapedEmail] = set()
        parsed = urlparse(url)
        domain = f"{parsed.scheme}://{parsed.netloc}"
        
        try:
            # HTML içeriği al
            resp = self.session.get(
                url,
                timeout=self.timeout,
                verify=self.verify_ssl,
                allow_redirects=True
            )
            resp.raise_for_status()
            
            content_type = resp.headers.get('Content-Type', '').lower()
            if 'text/html' not in content_type and 'text/plain' not in content_type:
                # XML (sitemap olabilir)
                if 'xml' in content_type or url.endswith('.xml'):
                    return self._parse_sitemap_url(url, resp.text, depth)
                self.stats.pages_failed += 1
                return set()
            
            html = resp.text
            final_url = resp.url  # redirect sonrası gerçek URL
            
            # E-postaları çıkar
            emails = self._extract_emails_from_text(html, url, final_url)
            all_emails.update(emails)
            
            self.stats.pages_crawled += 1
            self._emit_progress(self.stats.pages_crawled, self.max_pages, f"Taranıyor: {url[:60]}")
            
            new_emails_count = 0
            for e in emails:
                if self._emit_email(e):
                    new_emails_count += 1
            
            if new_emails_count > 0:
                self._log(f"  ✓ {new_emails_count} yeni e-posta bulundu: {url[:60]}")
            
            # Linkleri takip et (sadece aynı domain içinde, depth izin veriyorsa)
            if BeautifulSoup and depth < self.max_depth and self.stats.pages_crawled < self.max_pages:
                soup = BeautifulSoup(html, 'html.parser')
                
                # Cloudflare span verilerini topla (data-cfemail)
                for span in soup.find_all(attrs={"data-cfemail": True}):
                    encoded = span.get('data-cfemail', '')
                    if encoded:
                        decoded_email = self.decode_cloudflare_email(encoded)
                        if decoded_email:
                            scraped = ScrapedEmail(
                                email=decoded_email,
                                source_url=url,
                                found_on_page=final_url,
                                context_snippet="Cloudflare Email Protection (span)",
                                confidence=0.95
                            )
                            all_emails.add(scraped)
                            if self._emit_email(scraped):
                                self._log(f"  ✓ Cloudflare (span) çözüldü: {decoded_email}")

                links = set()
                for a_tag in soup.find_all('a', href=True):
                    href = a_tag['href'].strip()
                    
                    if '/cdn-cgi/l/email-protection#' in href:
                        encoded = href.split('#')[-1]
                        decoded_email = self.decode_cloudflare_email(encoded)
                        if decoded_email:
                            scraped = ScrapedEmail(
                                email=decoded_email,
                                source_url=url,
                                found_on_page=final_url,
                                context_snippet="Cloudflare Email Protection",
                                confidence=0.95
                            )
                            all_emails.add(scraped)
                            if self._emit_email(scraped):
                                self._log(f"  ✓ Cloudflare e-posta çözüldü: {decoded_email}")
                        continue
                        
                    if '/cdn-cgi/l/email-protection' in href:
                        continue

                    if href and not href.startswith('#') and not href.startswith('javascript:'):
                        absolute = urljoin(final_url, href)
                        abs_parsed = urlparse(absolute)
                        
                        # Sadece http/https
                        if abs_parsed.scheme not in ('http', 'https'):
                            continue
                        
                        # External link kontrolü
                        if not self.follow_external and abs_parsed.netloc != parsed.netloc:
                            continue
                        
                        # Gereksiz dosya uzantılarını atla
                        skip_ext = ('.jpg', '.jpeg', '.png', '.gif', '.svg', '.webp',
                                   '.pdf', '.zip', '.doc', '.docx', '.xls', '.xlsx',
                                   '.mp4', '.mp3', '.avi', '.mov', '.wmv', '.flv',
                                   '.css', '.js', '.ico', '.woff', '.woff2', '.ttf', '.eot')
                        if any(abs_parsed.path.lower().endswith(ext) for ext in skip_ext):
                            continue
                        
                        # Pattern filtreleme
                        if self.filter_patterns:
                            matched = False
                            for pattern in self.filter_patterns:
                                if pattern.lower() in absolute.lower():
                                    matched = True
                                    break
                            if not matched:
                                continue
                        
                        links.add(absolute)
                
                # Linkleri tara
                for link in links:
                    if self.stop_event.is_set() or self.stats.pages_crawled >= self.max_pages:
                        break
                    if link not in self.visited_urls:
                        sub_emails = self._crawl_url(link, depth + 1)
                        all_emails.update(sub_emails)
        
        except requests.exceptions.Timeout:
            self.stats.pages_failed += 1
            self._log(f"  ⏱ Timeout: {url[:60]}")
        except requests.exceptions.ConnectionError:
            self.stats.pages_failed += 1
            self._log(f"  ⊘ Bağlantı hatası: {url[:60]}")
        except requests.exceptions.HTTPError as e:
            self.stats.pages_failed += 1
            self._log(f"  ✗ HTTP {e.response.status_code if e.response else '?'}: {url[:60]}")
        except Exception as e:
            self.stats.pages_failed += 1
            self._log(f"  ✗ Hata: {str(e)[:80]}")
        
        # Selenium ile dinamik render (opsiyonel)
        if self.use_selenium and self.driver and all_emails and depth == 0:
            try:
                self._log(f"  🔄 Dinamik render deneniyor: {url[:50]}")
                self.driver.get(url)
                WebDriverWait(self.driver, 5).until(
                    EC.presence_of_element_located((By.TAG_NAME, 'body'))
                )
                time.sleep(2)  # JS render için bekle
                dynamic_html = self.driver.page_source
                dynamic_emails = self._extract_emails_from_text(dynamic_html, url, url)
                new_dynamic = dynamic_emails - all_emails
                if new_dynamic:
                    self._log(f"  ✓ Dinamik render ile {len(new_dynamic)} yeni e-posta bulundu")
                    for e in new_dynamic:
                        self._emit_email(e)
                all_emails.update(dynamic_emails)
            except Exception as e:
                self._log(f"  ⚠ Dinamik render hatası: {str(e)[:60]}")
        
        return all_emails
    
    def _parse_sitemap_url(self, sitemap_url: str, xml_content: str, depth: int = 0) -> Set[ScrapedEmail]:
        """Sitemap XML'ini parse et ve URL'leri çıkar"""
        all_emails: Set[ScrapedEmail] = set()
        urls_found = []
        
        try:
            root = ET.fromstring(xml_content)
            
            # Namespace'leri yönet
            ns = {'sm': 'http://www.sitemaps.org/schemas/sitemap/0.9'}
            
            # <url> elemanlarını bul
            for url_elem in root.findall('.//sm:url', ns) + root.findall('.//url'):
                loc = url_elem.find('sm:loc', ns) if url_elem.find('sm:loc', ns) is not None else url_elem.find('loc')
                if loc is not None and loc.text:
                    urls_found.append(loc.text.strip())
            
            # <sitemap> (iç içe sitemap index)
            for sm_elem in root.findall('.//sm:sitemap', ns) + root.findall('.//sitemap'):
                loc = sm_elem.find('sm:loc', ns) if sm_elem.find('sm:loc', ns) is not None else sm_elem.find('loc')
                if loc is not None and loc.text and depth < 2:
                    nested_url = loc.text.strip()
                    self._log(f"  📑 İç içe sitemap: {nested_url[:60]}")
                    try:
                        nested_resp = self.session.get(nested_url, timeout=self.timeout, verify=self.verify_ssl)
                        nested_emails = self._parse_sitemap_url(nested_url, nested_resp.text, depth + 1)
                        all_emails.update(nested_emails)
                    except:
                        pass
            
            self.stats.sources_processed += 1
            self._log(f"📋 Sitemap'ten {len(urls_found)} URL çıkarıldı: {sitemap_url[:60]}")
            
            # Bulunan URL'leri tara
            for url in urls_found:
                if self.stop_event.is_set() or self.stats.pages_crawled >= self.max_pages:
                    break
                if url not in self.visited_urls:
                    emails = self._crawl_url(url, depth=1)
                    all_emails.update(emails)
        
        except ET.ParseError as e:
            self._log(f"  ✗ XML parse hatası: {str(e)[:60]}")
        
        return all_emails
    
    def scrape_from_sitemap(self, sitemap_url: str) -> Set[ScrapedEmail]:
        """Sitemap URL'sini tara"""
        self._log(f"🗺 Sitemap taranıyor: {sitemap_url}")
        try:
            resp = self.session.get(sitemap_url, timeout=self.timeout, verify=self.verify_ssl)
            resp.raise_for_status()
            return self._parse_sitemap_url(sitemap_url, resp.text)
        except Exception as e:
            self._log(f"  ✗ Sitemap alınamadı: {e}")
            return set()
    
    def scrape_from_url(self, start_url: str) -> Set[ScrapedEmail]:
        """Tek bir başlangıç URL'sinden recursive crawl"""
        self._log(f"🌐 URL taranıyor (depth={self.max_depth}): {start_url}")
        parsed = urlparse(start_url)
        if not parsed.scheme:
            start_url = f"https://{start_url}"
        return self._crawl_url(start_url, depth=0)
    
    def scrape_from_google_dork(self, query: str, max_results: int = 50) -> Set[ScrapedEmail]:
        """Google dork ile arama (site:domain.com gibi)"""
        all_emails: Set[ScrapedEmail] = set()
        self._log(f"🔍 Google Dork: {query}")
        
        # Google arama URL'si
        search_url = f"https://www.google.com/search?q={requests.utils.quote(query)}&num={min(max_results, 100)}"
        
        headers = {
            'User-Agent': self.user_agent,
            'Accept': 'text/html,application/xhtml+xml',
        }
        
        try:
            resp = self.session.get(search_url, headers=headers, timeout=self.timeout, verify=self.verify_ssl)
            if resp.status_code != 200:
                self._log(f"  ⚠ Google {resp.status_code} döndü (CAPTCHA veya block olabilir)")
                return all_emails
            
            if BeautifulSoup:
                soup = BeautifulSoup(resp.text, 'html.parser')
                links = []
                for a in soup.find_all('a', href=True):
                    href = a['href']
                    if href.startswith('/url?') or href.startswith('http'):
                        if 'google.com' not in href:
                            links.append(href)
                
                self._log(f"  Google'dan {len(links)} sonuç alındı")
                
                for i, link in enumerate(links[:max_results]):
                    if self.stop_event.is_set():
                        break
                    # Google'ın yönlendirme URL'sini temizle
                    if link.startswith('/url?'):
                        parsed_link = urlparse(link)
                        qs = parse_qs(parsed_link.query)
                        real_url = qs.get('q', [link])[0]
                    else:
                        real_url = link
                    
                    if real_url.startswith('http'):
                        self._log(f"  [{i+1}/{min(len(links), max_results)}] Taranıyor: {real_url[:60]}")
                        emails = self._crawl_url(real_url, depth=1)
                        all_emails.update(emails)
                        self._delay()
        
        except Exception as e:
            self._log(f"  ✗ Google dork hatası: {e}")
        
        return all_emails
    
    def scrape_from_whois(self, domain: str) -> Set[ScrapedEmail]:
        """WHOIS kayıtlarından e-posta çıkar"""
        all_emails: Set[ScrapedEmail] = set()
        
        if not WHOIS_AVAILABLE:
            self._log("⚠ python-whois kütüphanesi yüklü değil")
            return all_emails
        
        # Domain'i temizle
        domain = domain.replace('https://', '').replace('http://', '').replace('www.', '').split('/')[0]
        
        self._log(f"🔍 WHOIS sorgulanıyor: {domain}")
        
        try:
            w = whois.whois(domain)
            text_fields = []
            if w.text:
                text_fields.append(str(w.text))
            for field in ['emails', 'email', 'admin_email', 'tech_email', 'registrant_email']:
                if hasattr(w, field) and getattr(w, field):
                    val = getattr(w, field)
                    if isinstance(val, list):
                        text_fields.extend([str(v) for v in val])
                    else:
                        text_fields.append(str(val))
            
            all_text = '\n'.join(text_fields)
            emails = self._extract_emails_from_text(all_text, f"whois://{domain}", f"whois://{domain}")
            all_emails.update(emails)
            
            if emails:
                self._log(f"  ✓ WHOIS'ten {len(emails)} e-posta bulundu")
            else:
                self._log(f"  ℹ WHOIS'te e-posta bulunamadı (gizli olabilir)")
        
        except Exception as e:
            self._log(f"  ✗ WHOIS hatası: {str(e)[:80]}")
        
        return all_emails
    
    def scrape_url_list(self, urls: List[str]) -> Set[ScrapedEmail]:
        """Birden çok URL'yi paralel tara"""
        all_emails: Set[ScrapedEmail] = set()
        self._log(f"📋 {len(urls)} URL toplu taranıyor...")
        
        with ThreadPoolExecutor(max_workers=5) as executor:
            futures = {executor.submit(self.scrape_from_url, url): url for url in urls}
            for future in as_completed(futures):
                if self.stop_event.is_set():
                    break
                try:
                    emails = future.result()
                    all_emails.update(emails)
                except Exception as e:
                    self._log(f"  ✗ {futures[future][:40]}... hatası: {e}")
        
        return all_emails
    
    def remove_duplicates(self) -> int:
        """Duplicate e-postaları kaldır"""
        before = len(self.found_emails)
        # E-posta adresine göre unique yap
        seen = {}
        unique = set()
        for email_obj in self.found_emails:
            key = email_obj.email.lower().strip()
            if key not in seen:
                seen[key] = email_obj
                unique.add(email_obj)
        self.stats.duplicate_removed = before - len(unique)
        self.found_emails = unique
        return self.stats.duplicate_removed
    
    def cleanup(self):
        """Kaynakları temizle"""
        if self.driver:
            try:
                self.driver.quit()
            except:
                pass
        if self.session:
            try:
                self.session.close()
            except:
                pass


# ╔══════════════════════════════════════════════════╗
# ║                    GUI                           ║
# ╚══════════════════════════════════════════════════╝

class ScraperGUI:
    """Tkinter tabanlı kullanıcı arayüzü"""
    
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("Universal Sitemail Scraper v2.0")
        self.root.geometry("1100x750")
        self.root.minsize(900, 600)
        
        # Tema renkleri
        self.colors = {
            'bg': '#1e1e2e',
            'fg': '#cdd6f4',
            'accent': '#89b4fa',
            'success': '#a6e3a1',
            'warning': '#f9e2af',
            'error': '#f38ba8',
            'card': '#313244',
            'border': '#45475a',
            'input_bg': '#181825',
            'button': '#585b70',
            'button_hover': '#6c7086',
            'highlight': '#45475a',
        }
        
        # Stil
        self.style = ttk.Style()
        self.style.theme_use('clam')
        
        # Scraper instance
        self.scraper: Optional[UniversalEmailScraper] = None
        self.stop_event = threading.Event()
        self.scraping_thread: Optional[threading.Thread] = None
        self.email_queue = queue.Queue()
        self.collected_emails: List[ScrapedEmail] = []
        self.total_sources = 0
        self.processed_sources = 0
        
        self._build_ui()
        self._process_email_queue()
        
        # Kapanış temizliği
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
    
    def _build_ui(self):
        """Ana arayüzü oluştur"""
        self.root.configure(bg=self.colors['bg'])
        
        # Ana container
        main_frame = tk.Frame(self.root, bg=self.colors['bg'])
        main_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        # ── Sol Panel ──
        left_panel = tk.Frame(main_frame, bg=self.colors['bg'], width=380)
        left_panel.pack(side=tk.LEFT, fill=tk.BOTH, expand=False, padx=(0, 5))
        left_panel.pack_propagate(False)
        
        # Kaynak Seçimi
        card_source = tk.LabelFrame(
            left_panel, text="📌 Kaynak Seçimi", bg=self.colors['card'],
            fg=self.colors['fg'], font=('Segoe UI', 11, 'bold'),
            padx=10, pady=10, relief=tk.GROOVE, bd=1
        )
        card_source.pack(fill=tk.X, pady=(0, 10))
        
        self.source_var = tk.StringVar(value="url")
        
        sources = [
            ("🌐 Tek URL / Domain", "url"),
            ("🗺 Sitemap.xml", "sitemap"),
            ("🔍 Google Dork", "dork"),
            ("📇 WHOIS", "whois"),
            ("📄 URL Listesi (dosya)", "file"),
        ]
        
        for text, value in sources:
            rb = tk.Radiobutton(
                card_source, text=text, variable=self.source_var, value=value,
                bg=self.colors['card'], fg=self.colors['fg'],
                selectcolor=self.colors['input_bg'],
                activebackground=self.colors['card'],
                activeforeground=self.colors['accent'],
                font=('Segoe UI', 10),
                command=self._on_source_change,
                cursor='hand2'
            )
            rb.pack(anchor=tk.W, pady=2)
        
        # Input alanı
        card_input = tk.LabelFrame(
            left_panel, text="📝 Hedef", bg=self.colors['card'],
            fg=self.colors['fg'], font=('Segoe UI', 11, 'bold'),
            padx=10, pady=10, relief=tk.GROOVE, bd=1
        )
        card_input.pack(fill=tk.X, pady=(0, 10))
        
        self.input_label = tk.Label(
            card_input, text="URL / Domain:", bg=self.colors['card'],
            fg=self.colors['fg'], font=('Segoe UI', 9)
        )
        self.input_label.pack(anchor=tk.W, pady=(0, 3))
        
        input_frame = tk.Frame(card_input, bg=self.colors['card'])
        input_frame.pack(fill=tk.X)
        
        self.url_entry = tk.Entry(
            input_frame, bg=self.colors['input_bg'], fg=self.colors['fg'],
            insertbackground=self.colors['fg'], font=('Consolas', 10),
            relief=tk.FLAT, bd=0, highlightthickness=1,
            highlightbackground=self.colors['border'],
            highlightcolor=self.colors['accent']
        )
        self.url_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, ipady=8, padx=(0, 5))
        
        self.browse_btn = tk.Button(
            input_frame, text="📁", command=self._browse_file,
            bg=self.colors['button'], fg=self.colors['fg'],
            font=('Segoe UI', 10), relief=tk.FLAT, cursor='hand2',
            padx=8, pady=4
        )
        self.browse_btn.pack(side=tk.RIGHT)
        self.browse_btn.pack_forget()  # Başlangıçta gizli
        
        # Ayarlar
        card_settings = tk.LabelFrame(
            left_panel, text="⚙️ Ayarlar", bg=self.colors['card'],
            fg=self.colors['fg'], font=('Segoe UI', 11, 'bold'),
            padx=10, pady=10, relief=tk.GROOVE, bd=1
        )
        card_settings.pack(fill=tk.X, pady=(0, 10))
        
        settings_grid = tk.Frame(card_settings, bg=self.colors['card'])
        settings_grid.pack(fill=tk.X)
        
        # Max Depth
        tk.Label(settings_grid, text="Derinlik:", bg=self.colors['card'],
                fg=self.colors['fg'], font=('Segoe UI', 9)).grid(row=0, column=0, sticky=tk.W, pady=3)
        self.depth_var = tk.IntVar(value=2)
        tk.Spinbox(
            settings_grid, from_=0, to=10, textvariable=self.depth_var,
            width=5, bg=self.colors['input_bg'], fg=self.colors['fg'],
            font=('Segoe UI', 9), relief=tk.FLAT, bd=0,
            highlightthickness=1, highlightbackground=self.colors['border'],
            buttonbackground=self.colors['button']
        ).grid(row=0, column=1, sticky=tk.W, pady=3, padx=(5, 20))
        
        # Max Pages
        tk.Label(settings_grid, text="Max Sayfa:", bg=self.colors['card'],
                fg=self.colors['fg'], font=('Segoe UI', 9)).grid(row=0, column=2, sticky=tk.W, pady=3)
        self.pages_var = tk.IntVar(value=500)
        tk.Spinbox(
            settings_grid, from_=10, to=10000, increment=50, textvariable=self.pages_var,
            width=6, bg=self.colors['input_bg'], fg=self.colors['fg'],
            font=('Segoe UI', 9), relief=tk.FLAT, bd=0,
            highlightthickness=1, highlightbackground=self.colors['border'],
            buttonbackground=self.colors['button']
        ).grid(row=0, column=3, sticky=tk.W, pady=3)
        
        # Delay
        tk.Label(settings_grid, text="Gecikme (sn):", bg=self.colors['card'],
                fg=self.colors['fg'], font=('Segoe UI', 9)).grid(row=1, column=0, sticky=tk.W, pady=3)
        self.delay_var = tk.StringVar(value="0.5-2.0")
        tk.Entry(
            settings_grid, textvariable=self.delay_var, width=8,
            bg=self.colors['input_bg'], fg=self.colors['fg'],
            font=('Segoe UI', 9), relief=tk.FLAT, bd=0,
            highlightthickness=1, highlightbackground=self.colors['border'],
        ).grid(row=1, column=1, sticky=tk.W, pady=3, padx=(5, 20))
        
        # Timeout
        tk.Label(settings_grid, text="Timeout (sn):", bg=self.colors['card'],
                fg=self.colors['fg'], font=('Segoe UI', 9)).grid(row=1, column=2, sticky=tk.W, pady=3)
        self.timeout_var = tk.IntVar(value=15)
        tk.Spinbox(
            settings_grid, from_=5, to=120, textvariable=self.timeout_var,
            width=5, bg=self.colors['input_bg'], fg=self.colors['fg'],
            font=('Segoe UI', 9), relief=tk.FLAT, bd=0,
            highlightthickness=1, highlightbackground=self.colors['border'],
            buttonbackground=self.colors['button']
        ).grid(row=1, column=3, sticky=tk.W, pady=3)
        
        # Checkbox'lar
        self.selenium_var = tk.BooleanVar(value=False)
        cb_selenium = tk.Checkbutton(
            settings_grid, text="JS Render (Selenium)", variable=self.selenium_var,
            bg=self.colors['card'], fg=self.colors['fg'],
            selectcolor=self.colors['input_bg'],
            activebackground=self.colors['card'],
            font=('Segoe UI', 9), cursor='hand2'
        )
        cb_selenium.grid(row=2, column=0, columnspan=2, sticky=tk.W, pady=3)
        
        self.robots_var = tk.BooleanVar(value=True)
        cb_robots = tk.Checkbutton(
            settings_grid, text="robots.txt'ye uy", variable=self.robots_var,
            bg=self.colors['card'], fg=self.colors['fg'],
            selectcolor=self.colors['input_bg'],
            activebackground=self.colors['card'],
            font=('Segoe UI', 9), cursor='hand2'
        )
        cb_robots.grid(row=2, column=2, columnspan=2, sticky=tk.W, pady=3)
        
        self.external_var = tk.BooleanVar(value=False)
        cb_ext = tk.Checkbutton(
            settings_grid, text="Harici linkleri takip et", variable=self.external_var,
            bg=self.colors['card'], fg=self.colors['fg'],
            selectcolor=self.colors['input_bg'],
            activebackground=self.colors['card'],
            font=('Segoe UI', 9), cursor='hand2'
        )
        cb_ext.grid(row=3, column=0, columnspan=2, sticky=tk.W, pady=3)
        
        self.ssl_var = tk.BooleanVar(value=True)
        cb_ssl = tk.Checkbutton(
            settings_grid, text="SSL doğrula", variable=self.ssl_var,
            bg=self.colors['card'], fg=self.colors['fg'],
            selectcolor=self.colors['input_bg'],
            activebackground=self.colors['card'],
            font=('Segoe UI', 9), cursor='hand2'
        )
        cb_ssl.grid(row=3, column=2, columnspan=2, sticky=tk.W, pady=3)
        
        # Filtre Pattern
        tk.Label(settings_grid, text="Filtre Pattern:", bg=self.colors['card'],
                fg=self.colors['fg'], font=('Segoe UI', 9)).grid(row=4, column=0, sticky=tk.W, pady=3)
        self.filter_var = tk.StringVar(value="")
        tk.Entry(
            settings_grid, textvariable=self.filter_var, width=20,
            bg=self.colors['input_bg'], fg=self.colors['fg'],
            font=('Segoe UI', 9), relief=tk.FLAT, bd=0,
            highlightthickness=1, highlightbackground=self.colors['border'],
        ).grid(row=4, column=1, columnspan=3, sticky=tk.W, pady=3, padx=(5, 20))
        tk.Label(settings_grid, text="(virgülle ayırın, örn: firma,iletisim)", bg=self.colors['card'],
                fg=self.colors['border'], font=('Segoe UI', 8)).grid(row=5, column=1, columnspan=3, sticky=tk.W, pady=0, padx=5)
        
        # Kontrol butonları
        btn_frame = tk.Frame(left_panel, bg=self.colors['bg'])
        btn_frame.pack(fill=tk.X, pady=(5, 0))
        
        self.start_btn = tk.Button(
            btn_frame, text="▶ BAŞLAT", command=self._start_scraping,
            bg='#40a02b', fg='white', font=('Segoe UI', 11, 'bold'),
            relief=tk.FLAT, cursor='hand2', padx=20, pady=10,
            activebackground='#50c030', activeforeground='white'
        )
        self.start_btn.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 3))
        
        self.stop_btn = tk.Button(
            btn_frame, text="⏹ DURDUR", command=self._stop_scraping,
            bg='#d20f39', fg='white', font=('Segoe UI', 11, 'bold'),
            relief=tk.FLAT, cursor='hand2', padx=20, pady=10,
            activebackground='#e03050', activeforeground='white',
            state=tk.DISABLED
        )
        self.stop_btn.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(3, 0))
        
        # Alt Bilgi (Footer) - Yapımcı ve Versiyon
        footer_frame = tk.Frame(left_panel, bg=self.colors['bg'])
        footer_frame.pack(side=tk.BOTTOM, fill=tk.X, pady=(15, 5))
        
        dev_label = tk.Label(
            footer_frame, text="Yapımcı: aoaydin", bg=self.colors['bg'],
            fg=self.colors['accent'], font=('Segoe UI', 9, 'underline'), cursor='hand2'
        )
        dev_label.pack(side=tk.LEFT, padx=(5, 0))
        dev_label.bind("<Button-1>", lambda e: webbrowser.open("mailto:aaydin3494@gmail.com"))
        
        version_label = tk.Label(
            footer_frame, text="v2.0", bg=self.colors['bg'],
            fg=self.colors['border'], font=('Segoe UI', 9, 'bold'), cursor='hand2'
        )
        version_label.pack(side=tk.RIGHT, padx=(0, 5))
        version_label.bind("<Button-1>", lambda e: messagebox.showinfo("Sürüm Bilgisi", "Universal Sitemail Scraper\nVersiyon: 2.0\n\nYeni Özellikler:\n- Cloudflare Şifre Çözücü\n- Akıllı Filtreleme (Pattern)\n- Global Deduplication\n\nGeliştirici: aoaydin"))
        
        # ── Sağ Panel ──
        right_panel = tk.Frame(main_frame, bg=self.colors['bg'])
        right_panel.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True, padx=(5, 0))
        
        # İlerleme
        self.progress_frame = tk.Frame(right_panel, bg=self.colors['card'], height=8)
        self.progress_frame.pack(fill=tk.X, pady=(0, 8))
        self.progress_frame.pack_propagate(False)
        
        self.progress_bar = tk.Canvas(
            self.progress_frame, bg=self.colors['input_bg'],
            height=8, highlightthickness=0, bd=0
        )
        self.progress_bar.pack(fill=tk.X)
        
        self.status_label = tk.Label(
            right_panel, text="Hazır", bg=self.colors['bg'],
            fg=self.colors['fg'], font=('Segoe UI', 9), anchor=tk.W
        )
        self.status_label.pack(fill=tk.X, pady=(0, 5))
        
        # Notebook (sekmeler)
        notebook = ttk.Notebook(right_panel)
        notebook.pack(fill=tk.BOTH, expand=True)
        
        # ── Sonuçlar Sekmesi ──
        results_tab = tk.Frame(notebook, bg=self.colors['bg'])
        notebook.add(results_tab, text="📧 Sonuçlar")
        
        # Toolbar
        results_toolbar = tk.Frame(results_tab, bg=self.colors['card'], height=36)
        results_toolbar.pack(fill=tk.X, pady=(0, 5))
        results_toolbar.pack_propagate(False)
        
        self.email_count_label = tk.Label(
            results_toolbar, text="Bulunan: 0", bg=self.colors['card'],
            fg=self.colors['success'], font=('Segoe UI', 10, 'bold')
        )
        self.email_count_label.pack(side=tk.LEFT, padx=10)
        
        export_frame = tk.Frame(results_toolbar, bg=self.colors['card'])
        export_frame.pack(side=tk.RIGHT, padx=5)
        
        for fmt, ext in [("CSV", "csv"), ("JSON", "json"), ("TXT", "txt")]:
            btn = tk.Button(
                export_frame, text=f"💾 {fmt}",
                command=lambda e=ext: self._export_emails(e),
                bg=self.colors['button'], fg=self.colors['fg'],
                font=('Segoe UI', 9), relief=tk.FLAT, cursor='hand2',
                padx=8, pady=2
            )
            btn.pack(side=tk.LEFT, padx=2)
        
        # Email listesi
        list_frame = tk.Frame(results_tab, bg=self.colors['bg'])
        list_frame.pack(fill=tk.BOTH, expand=True)
        
        columns = ('#', 'E-posta', 'Kaynak', 'Güven')
        self.email_tree = ttk.Treeview(
            list_frame, columns=columns, show='headings',
            height=15, selectmode='extended'
        )
        
        self.email_tree.heading('#', text='#', anchor=tk.CENTER)
        self.email_tree.heading('E-posta', text='E-posta', anchor=tk.W)
        self.email_tree.heading('Kaynak', text='Kaynak URL', anchor=tk.W)
        self.email_tree.heading('Güven', text='Güven %', anchor=tk.CENTER)
        
        self.email_tree.column('#', width=40, anchor=tk.CENTER, stretch=False)
        self.email_tree.column('E-posta', width=250, anchor=tk.W)
        self.email_tree.column('Kaynak', width=300, anchor=tk.W)
        self.email_tree.column('Güven', width=70, anchor=tk.CENTER, stretch=False)
        
        # Scrollbar
        tree_scroll = ttk.Scrollbar(list_frame, orient=tk.VERTICAL, command=self.email_tree.yview)
        self.email_tree.configure(yscrollcommand=tree_scroll.set)
        
        self.email_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        tree_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        
        # Sağ tık menü
        self.tree_menu = tk.Menu(self.email_tree, tearoff=0, bg=self.colors['card'], fg=self.colors['fg'])
        self.tree_menu.add_command(label="📋 Kopyala", command=self._copy_selected_email)
        self.email_tree.bind("<Button-3>", self._show_tree_menu)
        self.email_tree.bind("<Control-c>", lambda e: self._copy_selected_email())
        
        # ── Log Sekmesi ──
        log_tab = tk.Frame(notebook, bg=self.colors['bg'])
        notebook.add(log_tab, text="📋 Log")
        
        self.log_area = scrolledtext.ScrolledText(
            log_tab, bg=self.colors['input_bg'], fg=self.colors['fg'],
            font=('Consolas', 9), relief=tk.FLAT, bd=0,
            insertbackground=self.colors['fg'],
            highlightthickness=1, highlightbackground=self.colors['border'],
            wrap=tk.WORD
        )
        self.log_area.pack(fill=tk.BOTH, expand=True, pady=(0, 5))
        
        # Log temizleme
        log_btn_frame = tk.Frame(log_tab, bg=self.colors['bg'])
        log_btn_frame.pack(fill=tk.X)
        tk.Button(
            log_btn_frame, text="🗑 Log'u Temizle",
            command=lambda: self.log_area.delete(1.0, tk.END),
            bg=self.colors['button'], fg=self.colors['fg'],
            font=('Segoe UI', 9), relief=tk.FLAT, cursor='hand2'
        ).pack(side=tk.RIGHT, padx=5)
        
        # ── İstatistikler Sekmesi ──
        stats_tab = tk.Frame(notebook, bg=self.colors['bg'])
        notebook.add(stats_tab, text="📊 İstatistik")
        
        self.stats_text = tk.Text(
            stats_tab, bg=self.colors['card'], fg=self.colors['fg'],
            font=('Consolas', 10), relief=tk.FLAT, bd=0,
            highlightthickness=1, highlightbackground=self.colors['border'],
            height=12, wrap=tk.WORD, padx=15, pady=15
        )
        self.stats_text.pack(fill=tk.BOTH, expand=True)
        self._update_stats_display()
    
    def _on_source_change(self):
        """Kaynak seçimi değişince input label'ı güncelle"""
        source = self.source_var.get()
        labels = {
            'url': 'URL / Domain:',
            'sitemap': 'Sitemap URL:',
            'dork': 'Google Dork Sorgusu:',
            'whois': 'Domain (örn: example.com):',
            'file': 'Dosya Seç (.txt/.csv):',
        }
        self.input_label.config(text=labels.get(source, 'URL:'))
        
        if source == 'file':
            self.browse_btn.pack(side=tk.RIGHT)
        else:
            self.browse_btn.pack_forget()
    
    def _browse_file(self):
        """Dosya seçme diyaloğu"""
        filename = filedialog.askopenfilename(
            title="URL Listesi Seç",
            filetypes=[("Text files", "*.txt"), ("CSV files", "*.csv"), ("All files", "*.*")]
        )
        if filename:
            self.url_entry.delete(0, tk.END)
            self.url_entry.insert(0, filename)
    
    def _show_tree_menu(self, event):
        """Sağ tık menüsü"""
        item = self.email_tree.identify_row(event.y)
        if item:
            self.email_tree.selection_set(item)
            self.tree_menu.post(event.x_root, event.y_root)
    
    def _copy_selected_email(self):
        """Seçili e-postayı panoya kopyala"""
        selection = self.email_tree.selection()
        if selection:
            emails = []
            for item in selection:
                values = self.email_tree.item(item, 'values')
                if values and len(values) > 1:
                    emails.append(values[1])
            if emails:
                self.root.clipboard_clear()
                self.root.clipboard_append('\n'.join(emails))
                self._log(f"📋 {len(emails)} e-posta panoya kopyalandı")
    
    def _log(self, message: str):
        """Log alanına mesaj ekle"""
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.log_area.insert(tk.END, f"[{timestamp}] {message}\n")
        self.log_area.see(tk.END)
    
    def _update_progress(self, current: int, total: int, status: str = ""):
        """İlerleme çubuğunu güncelle"""
        if total > 0:
            ratio = min(current / total, 1.0)
            width = 800 * ratio
            self.progress_bar.delete("all")
            self.progress_bar.create_rectangle(
                0, 0, width, 8, fill='#40a02b', outline=''
            )
        self.status_label.config(text=f"📊 {status}" if status else f"İlerleme: {current}/{total}")
    
    def _on_email_found(self, email: ScrapedEmail):
        """Yeni e-posta bulunduğunda queue'ya ekle"""
        self.email_queue.put(email)
    
    def _process_email_queue(self):
        """Email queue'sunu periyodik işle"""
        try:
            while True:
                email = self.email_queue.get_nowait()
                if email not in self.collected_emails:
                    self.collected_emails.append(email)
                    idx = len(self.collected_emails)
                    confidence_pct = f"%{int(email.confidence * 100)}"
                    source_short = email.source_url[:70] + '...' if len(email.source_url) > 70 else email.source_url
                    
                    self.email_tree.insert(
                        '', tk.END,
                        values=(idx, email.email, source_short, confidence_pct),
                        tags=('high_conf',) if email.confidence > 0.7 else ('low_conf',)
                    )
                    self.email_count_label.config(text=f"Bulunan: {idx}")
                    self._update_stats_display()
        except queue.Empty:
            pass
        
        self.root.after(100, self._process_email_queue)
    
    def _update_stats_display(self):
        """İstatistik panelini güncelle"""
        total = len(self.collected_emails)
        high_conf = sum(1 for e in self.collected_emails if e.confidence > 0.7)
        domains = len(set(e.email.split('@')[1] for e in self.collected_emails if '@' in e.email))
        
        stats = f"""
╔══════════════════════════════════╗
║     📊 TARAMA İSTATİSTİKLERİ     ║
╠══════════════════════════════════╣
║  Toplam E-posta     │ {total:<6}          ║
║  Yüksek Güven (>70%)│ {high_conf:<6}          ║
║  Benzersiz Domain   │ {domains:<6}          ║
║  İşlenen Sayfa      │ {self.processed_sources if hasattr(self, 'scraper') and self.scraper else 0:<6}          ║
╚══════════════════════════════════╝
"""
        self.stats_text.delete(1.0, tk.END)
        self.stats_text.insert(1.0, stats)
    
    def _parse_delay(self) -> Tuple[float, float]:
        """Gecikme string'ini parse et"""
        delay_str = self.delay_var.get().strip()
        try:
            if '-' in delay_str:
                parts = delay_str.split('-')
                return (float(parts[0]), float(parts[1]))
            else:
                val = float(delay_str)
                return (val, val * 2)
        except:
            return (0.5, 2.0)
    
    def _start_scraping(self):
        """Scraping işlemini başlat"""
        target = self.url_entry.get().strip()
        source_type = self.source_var.get()
        
        if not target:
            messagebox.showwarning("Uyarı", "Lütfen bir hedef girin.")
            return
        
        # Queue temizliği
        while not self.email_queue.empty():
            try:
                self.email_queue.get_nowait()
            except:
                break
        
        # Önceki sonuçları temizle
        self.collected_emails.clear()
        for item in self.email_tree.get_children():
            self.email_tree.delete(item)
        self.email_count_label.config(text="Bulunan: 0")
        
        # Yeni scraper oluştur
        self.stop_event.clear()
        
        delay_range = self._parse_delay()
        
        filter_str = self.filter_var.get().strip()
        filter_patterns = [p.strip() for p in filter_str.split(',') if p.strip()]
        
        self.scraper = UniversalEmailScraper(
            max_depth=self.depth_var.get(),
            max_pages=self.pages_var.get(),
            delay_range=delay_range,
            timeout=self.timeout_var.get(),
            use_selenium=self.selenium_var.get(),
            respect_robots_txt=self.robots_var.get(),
            follow_external=self.external_var.get(),
            verify_ssl=self.ssl_var.get(),
            filter_patterns=filter_patterns,
            callback_progress=self._update_progress,
            callback_email=self._on_email_found,
            callback_log=self._log,
            stop_event=self.stop_event,
        )
        
        # UI'ı başlatma moduna al
        self.start_btn.config(state=tk.DISABLED, bg='#585b70')
        self.stop_btn.config(state=tk.NORMAL)
        self.progress_bar.delete("all")
        
        # Scraping thread'i
        def run_scraping():
            try:
                all_emails = set()
                
                if source_type == 'url':
                    all_emails = self.scraper.scrape_from_url(target)
                elif source_type == 'sitemap':
                    all_emails = self.scraper.scrape_from_sitemap(target)
                elif source_type == 'dork':
                    all_emails = self.scraper.scrape_from_google_dork(target, max_results=50)
                elif source_type == 'whois':
                    all_emails = self.scraper.scrape_from_whois(target)
                elif source_type == 'file':
                    if os.path.exists(target):
                        with open(target, 'r', encoding='utf-8') as f:
                            urls = [line.strip() for line in f if line.strip()]
                        self._log(f"📄 Dosyadan {len(urls)} URL okundu")
                        all_emails = self.scraper.scrape_url_list(urls)
                    else:
                        self._log(f"✗ Dosya bulunamadı: {target}")
                
                # Duplicate temizliği
                removed = self.scraper.remove_duplicates()
                self._log(f"🗑 {removed} duplicate kaldırıldı")
                
                # İstatistik
                summary = self.scraper.stats.summary()
                self._log("\n" + "─"*40)
                self._log(summary)
                self._log(f"📧 Toplam benzersiz e-posta: {len(self.scraper.found_emails)}")
                
                # Final UI güncellemesi
                self.root.after(0, lambda: self.status_label.config(
                    text=f"✅ Tamamlandı - {len(self.collected_emails)} e-posta bulundu"
                ))
                
            except Exception as e:
                self._log(f"❌ Kritik hata: {e}")
                import traceback
                self._log(traceback.format_exc())
            finally:
                self.root.after(0, self._scraping_finished)
        
        self.scraping_thread = threading.Thread(target=run_scraping, daemon=True)
        self.scraping_thread.start()
    
    def _stop_scraping(self):
        """Scraping'i durdur"""
        self.stop_event.set()
        self._log("⏹ Durdurma sinyali gönderildi...")
        self.status_label.config(text="⏹ Durduruluyor...")
    
    def _scraping_finished(self):
        """Scraping bittiğinde UI'ı eski haline getir"""
        self.start_btn.config(state=tk.NORMAL, bg='#40a02b')
        self.stop_btn.config(state=tk.DISABLED)
        self._update_stats_display()
    
    def _export_emails(self, format_type: str):
        """E-postaları dışa aktar"""
        if not self.collected_emails:
            messagebox.showinfo("Bilgi", "Dışa aktarılacak e-posta yok.")
            return
        
        ext_map = {'csv': '.csv', 'json': '.json', 'txt': '.txt'}
        filename = filedialog.asksaveasfilename(
            title=f"{format_type.upper()} olarak kaydet",
            defaultextension=ext_map.get(format_type, '.csv'),
            filetypes=[
                (f"{format_type.upper()} files", f"*.{format_type}"),
                ("All files", "*.*")
            ]
        )
        
        if not filename:
            return
        
        try:
            emails_data = [e.to_dict() for e in self.collected_emails]
            
            if format_type == 'csv':
                with open(filename, 'w', newline='', encoding='utf-8-sig') as f:
                    writer = csv.DictWriter(f, fieldnames=emails_data[0].keys())
                    writer.writeheader()
                    writer.writerows(emails_data)
            
            elif format_type == 'json':
                with open(filename, 'w', encoding='utf-8') as f:
                    json.dump(emails_data, f, indent=2, ensure_ascii=False)
            
            elif format_type == 'txt':
                with open(filename, 'w', encoding='utf-8') as f:
                    for e in self.collected_emails:
                        f.write(f"{e.email}\n")
            
            self._log(f"💾 {len(self.collected_emails)} e-posta kaydedildi: {filename}")
            messagebox.showinfo("Başarılı", f"{len(self.collected_emails)} e-posta kaydedildi:\n{filename}")
        
        except Exception as e:
            messagebox.showerror("Hata", f"Dışa aktarma hatası: {e}")
    
    def _on_close(self):
        """Pencere kapanırken temizlik"""
        self.stop_event.set()
        if self.scraper:
            self.scraper.cleanup()
        self.root.destroy()
    
    def run(self):
        """GUI'yi başlat"""
        self._log("🚀 Universal Sitemail Scraper v2.0 başlatıldı")
        self._log("📌 Kaynak seçin ve hedef girin, ardından BAŞLAT'a tıklayın")
        self.root.mainloop()


# ╔══════════════════════════════════════════════════╗
# ║                    MAIN                          ║
# ╚══════════════════════════════════════════════════╝

def main():
    """Ana giriş noktası"""
    # Bağımlılık kontrolü
    missing = []
    if requests is None:
        missing.append("requests")
    if BeautifulSoup is None:
        missing.append("beautifulsoup4")
    
    if missing:
        print("="*50)
        print("⚠️  Eksik bağımlılıklar tespit edildi!")
        print(f"   Eksik: {', '.join(missing)}")
        print("\n   Yüklemek için:")
        print(f"   pip install {' '.join(missing)}")
        print("\n   Opsiyonel bağımlılıklar:")
        print("   pip install selenium python-whois")
        print("="*50)
        
        # GUI olmadan da çalışabilir mi?
        if 'tkinter' in str(sys.modules):
            response = input("\nYine de GUI'yi başlatmak ister misiniz? (e/h): ")
            if response.lower() not in ('e', 'evet', 'y', 'yes'):
                sys.exit(1)
    
    app = ScraperGUI()
    app.run()


if __name__ == '__main__':
    main()
