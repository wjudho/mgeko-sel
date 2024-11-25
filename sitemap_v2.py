from playwright.sync_api import sync_playwright
import xml.etree.ElementTree as ET
from playwright_stealth import stealth_sync
import sqlite3
import logging
import time
import os
import json
import requests

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Constants
sitemap_url = 'https://www.mgeko.cc/sitemap.xml'
db_file = 'sitemap_urls.db'
cookies_file = "mg_cookies.json"
ENABLE_SKIP_EXISTING = True  # Set to False to disable this feature

def load_cookies(context):
    """Load cookies from file"""
    if os.path.exists(cookies_file):
        try:
            # Load cookies from file
            with open(cookies_file, "r") as f:
                cookies = json.load(f)
            context.add_cookies(cookies)
            logger.info("Using existing cookies for authentication")
            return True #cookies load successfully
        except json.JSONDecodeError as e:
            logger.error(f"Error loading cookies from file: {e}")
            logger.warning("Cookies have expired, re-authenticating...")
            try:
                os.remove(cookies_file)
            except OSError as e:
                logger.error(f"Error deleting cookies file: {e}")
            return False #cookies load failed
    return False
    
def save_cookies(context):
    """save cookies to json file"""
    cookies = context.cookies()
    try:
        with open(cookies_file, "w") as f:
            json.dump(cookies, f)
        logger.info("Cookies saved to file")
    except Exception as e:
        logger.error(f"Error saving cookies to file: {e}")
    
def login_page(page):
    """Login to get cookies"""
    page.goto("https://www.mgeko.cc/portal/api/login/", wait_until="networkidle")
    logging.info(f"Before signin: {page.url}")
    page.fill("input[name='user']", "wisjnu888")
    page.fill("input[name='pass']", "hikago88")
    page.click("button.login100-form-btn")
    logging.info(f"After signin: {page.url}")
    
def init_db():
    logger.info("Initializing the database...")
    conn = sqlite3.connect(db_file)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS metadata (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        url TEXT UNIQUE,
        title TEXT,
        rating TEXT,
        user_rated TEXT,
        chapters TEXT,
        views TEXT, 
        bookmarked TEXT,
        last_update TEXT
        )
    ''')
    conn.commit()
    conn.close()
    logger.info("Database initialized successfully.")
    
def fetch_sitemap(url):
    logger.info(f"Fetching sitemap from {url}...")
    response = requests.get(url)
    if response.status_code == 200:
        tree = ET.fromstring(response.content)
        namespace = {'ns': 'http://www.sitemaps.org/schemas/sitemap/0.9'}  # Define the namespace
        urls = [url.find('ns:loc', namespace).text for url in tree.findall('.//ns:url', namespace)]
        logger.info(f"Fetched {len(urls)} URLs from the sitemap.")
        return urls 
    else:
        logger.error(f"Failed to fetch sitemap, status code: {response.status_code}")
        return []

def get_metadata(page, url):
    try:
        # logger.info(f"Fetching metadata from {url}...")
        page.goto(url, wait_until="load")
        metadata = {
            'url': url,
            'title': page.locator("h1.novel-title").inner_text(),
            'rating': page.locator("div.rating-star > strong").inner_text().split()[0],
            'user_rated': page.locator("div.rating-star > strong > span").inner_text().replace('(', '').replace(')', '').strip(),
            'chapters': page.locator("div.header-stats > span:nth-child(1) > strong:nth-child(1)").inner_text().replace("book", "").strip(),
            'views': page.locator("div.header-stats > span:nth-child(2) > strong:nth-child(1)").inner_text().replace("supervised_user_circle", "").strip(),
            'bookmarked': page.locator("div.header-stats > span:nth-child(3) > strong:nth-child(1)").inner_text().replace("bookmark", "").strip(),
            'last_update': page.locator("div.updinfo > strong:nth-child(2)").inner_text()    
        }    
        # logger.info(f"Fetched metadata for {url}.")
        return metadata
    except Exception as e:
        logger.error(f"Error fetching metadata from {url}: {e}")
        return None  # Return None if there was an error
        

def save_all_to_db(metadata_list):
    logger.info("Saving all metadata to the database...")
    conn = sqlite3.connect(db_file)
    cursor = conn.cursor()

    # Prepare the SQL insert statement with upsert logic
    insert_sql = '''
        INSERT OR REPLACE INTO metadata (url, title, rating, user_rated, chapters, views, bookmarked, last_update) 
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    '''

    # Prepare a list of tuples for the batch insert
    data_to_insert = [
        (metadata['url'], metadata['title'], metadata['rating'], metadata['user_rated'],
         metadata['chapters'], metadata['views'], metadata['bookmarked'], metadata['last_update'])
        for metadata in metadata_list
    ]

    # Execute the batch insert
    cursor.executemany(insert_sql, data_to_insert)

    conn.commit()
    conn.close()
    logger.info("Batch metadata saved successfully.")

def url_exists_in_db(url):
    """Check if the URL already exists in the database."""
    conn = sqlite3.connect(db_file)
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM metadata WHERE url = ?", (url,))
    exists = cursor.fetchone()[0] > 0
    conn.close()
    return exists

def get_timer(start_time, end_time):
    total_time = end_time - start_time
    hours, remainder = divmod(total_time, 3600)
    minutes, seconds = divmod(remainder, 60)
    logger.info(f"Download completed in {int(hours)} hours, {int(minutes)} minutes and {int(seconds)} seconds.")

def main():
    start_time = time.time()
    init_db()
    urls = fetch_sitemap(sitemap_url)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)  # Launch a headless browser
        context = browser.new_context()
        page = context.new_page()  # Create a new page
        stealth_sync(page)
        # Authentication process      
        load_cookies(context)   # <== def function
        if not context.cookies():
            login_page(page)    # <== def function
            save_cookies(context)    

        batch_size = 50  # Set the batch size for processing
        metadata_list = []  # Initialize the list to hold metadata

        # Counter for tracking progress
        for index, url in enumerate(urls, start=1):
            if ENABLE_SKIP_EXISTING and url_exists_in_db(url):
                logger.info(f"Skipping {url}, already exists in the database.")
                continue  # Skip to the next URL if it exists
            
            metadata = get_metadata(page, url)  # Fetch metadata for each URL
            if metadata:
                metadata_list.append(metadata)  # Add to the list
            logger.info(f"[{index}] Fetched metadata from: {url}")
            
            # If the batch size is reached, save to the database
            if len(metadata_list) >= batch_size:
                save_all_to_db(metadata_list)  # Save the current batch
                metadata_list.clear()  # Clear the list after saving

        # Save any remaining metadata after the loop
        if metadata_list:
            save_all_to_db(metadata_list)
            
        browser.close()  # Close the browser after all pages have been processed
        logger.info("Browser closed. Finished processing all URLs.")
    
    end_time = time.time()
    get_timer(start_time, end_time)
        
if __name__ == "__main__":
    main()