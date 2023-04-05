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

import multiprocessing as mp
from multiprocessing import Manager
from time import sleep

BLICK_NAME = 'Blick'
TWENTYMIN_NAME = '20min'
TAGI_NAME = 'Tagesanzeiger'
ZEIT_NAME = 'dieZeit'

TITEL_TEMPLATE = "News Noise CH - {}"

def scrape_process(queue, name, f):
    db = DBManager()  # Create a new DBManager instance for each process
    try:
        res = f(db)  # Pass the db instance to the scraper function
        info(f'{green}Scraped {len(res)} articles from {name}{reset}')
        info(f'{blue}Put into queue: {name} with {len(res)}{reset}')
        queue.put((name, res))
        return
    except Exception as e:
        error(f'{orange}Error scraping {name}: {e}{reset}')
        return


if __name__ == '__main__':
    uploadManager = UploadManager()
    summarizer = SummarizManager()
    tts = TTSManager()
    db = DBManager()
    db.create_update_tables()

    # create scrape result dictionary
    scrape_res_dict = {
        TWENTYMIN_NAME: None,
        BLICK_NAME: None,
        TAGI_NAME: None,
        ZEIT_NAME: None
    }

    queue = mp.Queue()
    # Make subprocesses with the shared_db instead of db
    scrapers = [
        mp.Process(target=scrape_process, args=(queue, TWENTYMIN_NAME, scrape_20min)),
        mp.Process(target=scrape_process, args=(queue, BLICK_NAME, scrape_blick)),
        mp.Process(target=scrape_process, args=(queue, TAGI_NAME, scrape_taggi)),
        mp.Process(target=scrape_process, args=(queue, ZEIT_NAME, scrape_zeit)),
    ]

    # start subprocesses
    print('starting subprocesses...')
    for proc in scrapers:
        proc.start()

    while queue.qsize() < len(scrapers):
        sleep(1)
    
    # get results from queue
    print('getting results from queue...')
    while not queue.empty():
        key, value = queue.get()
        scrape_res_dict[key] = value

    # wait for subprocesses to finish
    print('waiting for subprocesses to finish...')
    for proc in scrapers:
        proc.join(timeout=10)
        if proc.is_alive():
            warn(f'{orange}Process {proc.name} is still alive!{reset}')
            proc.terminate()

    # check if all scrapers returned results
    for key, value in scrape_res_dict.items():
        if value is None:
            error(f'{orange}Not all scrapers returned results!{reset}')
            continue
        db.insert_many(value, key)

    twentymin_df = db.get_by_publish_date(TWENTYMIN_NAME, datetime.now().strftime("%Y-%m-%d"))
    blick_df = db.get_by_publish_date(BLICK_NAME, datetime.now().strftime("%Y-%m-%d"))
    tagi_df = db.get_by_publish_date(TAGI_NAME, datetime.now().strftime("%Y-%m-%d"))
    zeit_df = db.get_by_publish_date(ZEIT_NAME, datetime.now().strftime("%Y-%m-%d"))

    print(f'{yellow}Articles from Today: "20min": {len(twentymin_df)}, "blick": {len(blick_df)}, "tagi": {len(tagi_df)}, "zeit": {len(zeit_df)}{reset}')
    if sum(len(df) for df in [twentymin_df, blick_df, tagi_df, zeit_df]) < 10:
        warn(f'{orange}No articles found for today!{reset}')
        exit(1)
    """ 
    result_path, tags, description = CreateVideo(tts, summarizer, db)
    info(f'{green}Video created at {result_path}{reset}')

    # get tags and title
    date = datetime.now().strftime("%d.%m.%Y")
    title = TITEL_TEMPLATE.format(date)
    info('final video path: {}, final thumpnail path: {}'.format(result_path+"final.mp4", result_path+"final_thumbnail.png"))
    if len(tags) > 10:
        tags = tags[:10]
    video_id = uploadManager.upload(result_path+"final.mp4", title, description, ['News', 'Schweiz', 'Deutschland', 'ChatGPT']+tags, 25)
    video_id = uploadManager.set_thumbnail(result_path+"final_thumbnail.png", video_id) """



