from os import listdir
import json
from logUtils import warn, info, error, green, blue, orange, reset, grey,yellow
from sqlite3 import connect
from scrapers.twentymin_scraper import scrape_20min
from scrapers.blick_scraper import scrape_blick
from scrapers.taggi_scraper import scrape_taggi
from scrapers.zeit_scraper import scrape_zeit
from datetime import datetime
import pandas as pd
from textUtils import SummarizManager, TTSManager, UploadManager
from database.DB_manager import DBManager
from matches.matchManager import CreateVideo

BLICK_NAME = 'Blick'
TWENTYMIN_NAME = '20min'
TAGI_NAME = 'Tagesanzeiger'
ZEIT_NAME = 'dieZeit'

DESCRIPTION = """Dieses Video wurde automatisch erstellt.
Die Korrektheit der Inhalte kann nicht garantiert werden.

Die Inhalte wurden von den folgenden News-Seiten gesammelt:
- 20min.ch
- blick.ch
- tagi.ch
- zeit.de

Mittels einer KI wurde eine Zusammenfassung/Video erstellt.
"""

TITEL_TEMPLATE = "News Noise CH - {}"

if __name__ == '__main__':
    uploadManager = UploadManager()
    summarizer = SummarizManager()
    tts = TTSManager()
    db = DBManager()
    db.create_update_tables()
    
    twenty_articles = scrape_20min(db)
    info(f'{green}Scraped {len(twenty_articles)} articles from 20min.ch{reset}')
    blick_articles = scrape_blick(db)
    info(f'{green}Scraped {len(blick_articles)} articles from blick.ch{reset}')
    tagi_articles = scrape_taggi(db)
    info(f'{green}Scraped {len(tagi_articles)} articles from tagi.ch{reset}')
    zeit_articles = scrape_zeit(db)
    info(f'{green}Scraped {len(zeit_articles)} articles from zeit.ch{reset}')

    db.insert_many(twenty_articles, TWENTYMIN_NAME)
    db.insert_many(blick_articles, BLICK_NAME)
    db.insert_many(tagi_articles, TAGI_NAME)
    db.insert_many(zeit_articles, ZEIT_NAME)


    twentymin_df = db.get_by_publish_date(TWENTYMIN_NAME, datetime.now().strftime("%Y-%m-%d"))
    blick_df = db.get_by_publish_date(BLICK_NAME, datetime.now().strftime("%Y-%m-%d"))
    tagi_df = db.get_by_publish_date(TAGI_NAME, datetime.now().strftime("%Y-%m-%d"))
    zeit_df = db.get_by_publish_date(ZEIT_NAME, datetime.now().strftime("%Y-%m-%d"))

    print(f'{yellow}Articles from Today: "20min": {len(twentymin_df)}, "blick": {len(blick_df)}, "tagi": {len(tagi_df)}, "zeit": {len(zeit_df)}{reset}')

    result_path, tags = CreateVideo(tts, summarizer, db)
    info(f'{green}Video created at {result_path}{reset}')
    # get tags and title
    date = datetime.now().strftime("%d.%m.%Y")
    title = TITEL_TEMPLATE.format(date)
    uploadManager.upload(result_path+"final.mp4", title, DESCRIPTION, ['News', 'Schweiz', 'Deutschland', 'ChatGPT']+tags, 25)

