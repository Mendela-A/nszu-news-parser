from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
from bs4 import BeautifulSoup
import json
import time
import requests
import hashlib
from datetime import datetime
import os


try:
    from config import (
        TELEGRAM_TOKEN,
        TELEGRAM_CHAT_ID,
        HEADLESS_MODE,
        MAX_NEWS_ITEMS,
        NEWS_LIMIT_TO_SEND,
        DATABASE_FILE,
        CLEANUP_OLD_RECORDS_DAYS
    )
except ImportError:
    print("❌ Файл config.py не знайдено!")
    print("📝 Скопіюйте config.example.py в config.py і заповніть дані")
    exit(1)

class NSZUParser:
    def __init__(self, headless=True, telegram_token=None, telegram_chat_id=None, db_file='sent_news.json'):
        """Ініціалізація парсера з Selenium"""
        self.base_url = "https://nszu.gov.ua"
        self.archive_url = f"{self.base_url}/arxiv-dokumentiv?groups%5B2%5D%5Battributes%5D%5B%5D=36"
        
        # Telegram налаштування
        self.telegram_token = telegram_token
        self.telegram_chat_id = telegram_chat_id
        
        # База відправлених новин
        self.db_file = db_file
        self.sent_news = self.load_sent_news()
        
        # Налаштування Chrome
        chrome_options = Options()
        if headless:
            chrome_options.add_argument('--headless')
        chrome_options.add_argument('--no-sandbox')
        chrome_options.add_argument('--disable-dev-shm-usage')
        chrome_options.add_argument('--disable-blink-features=AutomationControlled')
        chrome_options.add_argument('user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36')
        
        # Ініціалізація драйвера
        self.driver = webdriver.Chrome(
            service=Service(ChromeDriverManager().install()),
            options=chrome_options
        )
        self.wait = WebDriverWait(self.driver, 10)
    
    def load_sent_news(self):
        """Завантаження бази відправлених новин"""
        if os.path.exists(self.db_file):
            try:
                with open(self.db_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception as e:
                print(f"⚠️  Помилка завантаження БД: {e}")
                return {}
        return {}
    
    def save_sent_news(self):
        """Збереження бази відправлених новин"""
        try:
            with open(self.db_file, 'w', encoding='utf-8') as f:
                json.dump(self.sent_news, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"⚠️  Помилка збереження БД: {e}")
    
    def get_news_hash(self, news_item):
        """Створення унікального хешу для новини"""
        # Використовуємо заголовок + URL для унікальності
        unique_string = f"{news_item.get('title', '')}{news_item.get('url', '')}"
        return hashlib.md5(unique_string.encode()).hexdigest()
    
    def is_news_sent(self, news_item):
        """Перевірка чи була новина вже відправлена"""
        news_hash = self.get_news_hash(news_item)
        return news_hash in self.sent_news
    
    def mark_as_sent(self, news_item):
        """Позначити новину як відправлену"""
        news_hash = self.get_news_hash(news_item)
        self.sent_news[news_hash] = {
            'title': news_item.get('title', ''),
            'url': news_item.get('url', ''),
            'sent_at': datetime.now().isoformat(),
            'date': news_item.get('date', '')
        }
        self.save_sent_news()
    
    def filter_new_news(self, news_items):
        """Відфільтрувати тільки нові новини"""
        new_news = []
        for item in news_items:
            if not self.is_news_sent(item):
                new_news.append(item)
        return new_news
    
    def get_news_list(self, max_items=20):
        """Отримати список новин"""
        try:
            print("Завантаження сторінки...")
            self.driver.get(self.archive_url)
            time.sleep(3)
            
            # Прокрутка для завантаження всіх елементів
            self.driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(2)
            
            # Отримання HTML
            soup = BeautifulSoup(self.driver.page_source, 'html.parser')
            
            return self.parse_news_items(soup, max_items)
            
        except Exception as e:
            print(f"Помилка: {e}")
            return []
    
    def parse_news_items(self, soup, max_items):
        """Парсинг новин зі сторінки"""
        news_items = []
        
        # Можливі селектори для новин
        selectors = [
            'article',
            'div.news-item',
            'div.document-item',
            'div.item',
            'li.news',
            'div[class*="news"]',
            'div[class*="document"]'
        ]
        
        articles = []
        for selector in selectors:
            articles = soup.select(selector)
            if articles:
                print(f"Знайдено елементи за селектором: {selector}")
                break
        
        # Якщо не знайдено структуровані блоки, шукаємо посилання
        if not articles:
            print("Шукаємо посилання...")
            links = soup.find_all('a', href=True)
            for link in links[:max_items]:
                href = link.get('href', '')
                if '/e-data/' in href or '/document/' in href or '/news/' in href:
                    news_items.append({
                        'title': link.get_text(strip=True),
                        'url': self.base_url + href if href.startswith('/') else href,
                        'date': 'Не вказано',
                        'description': ''
                    })
        else:
            # Парсинг структурованих блоків
            for article in articles[:max_items]:
                try:
                    item = {}
                    
                    # Заголовок і посилання
                    title_elem = (article.find('h1') or article.find('h2') or 
                                 article.find('h3') or article.find('h4') or
                                 article.find('a'))
                    
                    if title_elem:
                        item['title'] = title_elem.get_text(strip=True)
                        
                        link = title_elem if title_elem.name == 'a' else title_elem.find('a')
                        if link and link.get('href'):
                            href = link['href']
                            item['url'] = self.base_url + href if href.startswith('/') else href
                    
                    # Дата
                    date_elem = (article.find('time') or 
                                article.find(class_=['date', 'published', 'post-date']) or
                                article.find('span', class_=lambda x: x and 'date' in x.lower()))
                    
                    item['date'] = date_elem.get_text(strip=True) if date_elem else 'Не вказано'
                    
                    # Опис
                    desc_elem = (article.find('p') or 
                                article.find(class_=['description', 'excerpt', 'summary']))
                    
                    item['description'] = desc_elem.get_text(strip=True) if desc_elem else ''
                    
                    if item.get('title'):
                        news_items.append(item)
                        
                except Exception as e:
                    print(f"Помилка парсингу елемента: {e}")
                    continue
        
        return news_items
    
    def format_telegram_message(self, news_items, limit=10):
        """Форматування повідомлення для Telegram"""
        if not news_items:
            return None
        
        message = "🏥 <b>Нові документи НСЗУ</b>\n"
        message += "━━━━━━━━━━━━━━━━━━━━\n\n"
        
        for i, item in enumerate(news_items[:limit], 1):
            title = item.get('title', 'Без заголовка')
            date = item.get('date', 'Не вказано')
            url = item.get('url', '')
            desc = item.get('description', '')
            
            message += f"<b>{i}. {title}</b>\n"
            message += f"📅 {date}\n"
            
            if desc:
                # Обмежуємо опис до 150 символів
                short_desc = desc[:150] + '...' if len(desc) > 150 else desc
                message += f"📝 {short_desc}\n"
            
            if url:
                message += f"🔗 <a href='{url}'>Читати повністю</a>\n"
            
            message += "\n"
        
        message += f"━━━━━━━━━━━━━━━━━━━━\n"
        message += f"Нових документів: {len(news_items)}"
        
        return message
    
    def send_to_telegram(self, message, parse_mode='HTML'):
        """Відправка повідомлення в Telegram"""
        if not self.telegram_token or not self.telegram_chat_id:
            print("❌ Не вказані токен або chat_id для Telegram")
            return False
        
        if not message:
            return False
        
        url = f"https://api.telegram.org/bot{self.telegram_token}/sendMessage"
        
        # Якщо повідомлення довге, розбиваємо на частини
        max_length = 4096
        if len(message) > max_length:
            parts = [message[i:i+max_length] for i in range(0, len(message), max_length)]
            for part in parts:
                payload = {
                    'chat_id': self.telegram_chat_id,
                    'text': part,
                    'parse_mode': parse_mode,
                    'disable_web_page_preview': True
                }
                try:
                    response = requests.post(url, json=payload)
                    response.raise_for_status()
                    time.sleep(1)
                except Exception as e:
                    print(f"❌ Помилка відправки в Telegram: {e}")
                    return False
        else:
            payload = {
                'chat_id': self.telegram_chat_id,
                'text': message,
                'parse_mode': parse_mode,
                'disable_web_page_preview': True
            }
            
            try:
                response = requests.post(url, json=payload)
                response.raise_for_status()
                print("✅ Повідомлення відправлено в Telegram!")
                return True
            except Exception as e:
                print(f"❌ Помилка відправки в Telegram: {e}")
                return False
    
    def send_news_to_telegram(self, news_items, limit=10):
        """Відправка новин в Telegram"""
        message = self.format_telegram_message(news_items, limit)
        if message:
            success = self.send_to_telegram(message)
            if success:
                # Позначаємо всі відправлені новини
                for item in news_items[:limit]:
                    self.mark_as_sent(item)
            return success
        return False
    
    def get_database_stats(self):
        """Отримати статистику бази даних"""
        return {
            'total_sent': len(self.sent_news),
            'database_file': self.db_file,
            'file_size': os.path.getsize(self.db_file) if os.path.exists(self.db_file) else 0
        }
    
    def clear_old_records(self, days=30):
        """Очистити старі записи (старше N днів)"""
        from datetime import timedelta
        cutoff_date = datetime.now() - timedelta(days=days)
        
        original_count = len(self.sent_news)
        self.sent_news = {
            hash_id: data for hash_id, data in self.sent_news.items()
            if datetime.fromisoformat(data.get('sent_at', '2000-01-01')) > cutoff_date
        }
        
        removed = original_count - len(self.sent_news)
        if removed > 0:
            self.save_sent_news()
            print(f"🗑️  Видалено {removed} старих записів")
        
        return removed
    
    def save_to_json(self, data, filename='nszu_news.json'):
        """Зберегти у JSON"""
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print(f"✓ Дані збережено у {filename}")
    
    def close(self):
        """Закрити браузер"""
        self.driver.quit()


# Використання
if __name__ == "__main__":
    parser = NSZUParser(
        headless=HEADLESS_MODE,
        telegram_token=TELEGRAM_TOKEN,
        telegram_chat_id=TELEGRAM_CHAT_ID,
        db_file=DATABASE_FILE
    )
    
    try:
        print("=" * 60)
        print("Парсер новин НСЗУ → Telegram (з БД)")
        print("=" * 60)
        
        # Показати статистику БД
        stats = parser.get_database_stats()
        print(f"\n📊 Статистика БД:")
        print(f"   Відправлено раніше: {stats['total_sent']} новин")
        print(f"   Файл БД: {stats['database_file']}")
        
        # Очистити старі записи (опціонально)
        # parser.clear_old_records(days=30)
        
        print("\n" + "=" * 60)
        
        # Отримання всіх новин
        all_news = parser.get_news_list(max_items=20)
        print(f"Всього новин знайдено: {len(all_news)}")
        
        # Фільтрація нових новин
        new_news = parser.filter_new_news(all_news)
        print(f"Нових новин (не відправлених): {len(new_news)}")
        print("=" * 60 + "\n")
        
        if new_news:
            # Виведення списку нових новин
            print("📰 Нові новини:\n")
            for i, item in enumerate(new_news, 1):
                print(f"{i}. {item.get('title', 'Без заголовка')}")
                print(f"   📅 {item.get('date', 'Не вказано')}")
                if item.get('url'):
                    print(f"   🔗 {item['url']}")
                print()
            
            # Збереження у JSON
            parser.save_to_json(all_news, 'nszu_all_news.json')
            parser.save_to_json(new_news, 'nszu_new_news.json')
            
            # Відправка в Telegram
            print("=" * 60)
            print("Відправка в Telegram...")
            print("=" * 60)
            parser.send_news_to_telegram(new_news, limit=10)
        else:
            print("✅ Немає нових новин для відправки!")
            print("   Всі новини вже були відправлені раніше.")
            
    finally:
        parser.close()
        print("\n✓ Браузер закрито")
        
        # Фінальна статистика
        final_stats = parser.get_database_stats()
        print(f"\n📊 Фінальна статистика:")
        print(f"   Всього в БД: {final_stats['total_sent']} новин")