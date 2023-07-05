import json
from logUtils import warn, info, error, green, blue, orange, reset,yellow
from scrapers.twentymin_scraper import scrape_20min
from scrapers.blick_scraper import scrape_blick
from scrapers.taggi_scraper import scrape_taggi
from scrapers.zeit_scraper import scrape_zeit
from datetime import datetime
import os
from textUtils import SummarizManager, TTSManager, UploadManager
from database.DB_manager import DBManager
import matches.matchManager as mm
import video.videoManager as vm
from video.videoManager import MEDIA_PATH
import concurrent.futures
import uuid
import multiprocessing as mp
from time import sleep
from tqdm import tqdm
import errno

from moviepy.editor import VideoFileClip
from pandas import DataFrame

BLICK_NAME = 'Blick'
TWENTYMIN_NAME = '20min'
TAGI_NAME = 'Tagesanzeiger'
ZEIT_NAME = 'die Zeit'

TITEL_TEMPLATE = "News Noise CH - {}"

MAX_DISCRIPTION_LENGTH = 5000

def convert_matches(matches:DataFrame, db:DBManager):
    # convert string saved fields to lists
    matches['tags'] = matches['tags'].apply(lambda x: x.split(';')) 
    matches['articles'] = matches['articles'].apply(lambda x: x.split(';'))
    matches['images'] = matches['images'].apply(lambda x: x.split(';'))

    matches['articles'] = matches['articles'].apply(lambda x: get_articles(db,x))  

    return matches

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

def scrape_newspapers(db: DBManager, summarizer: SummarizManager):
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
        # remove duplicates in links
        links = [article['url'] for article in value]
        if len(links) != len(set(links)):
            starting_len = len(value)
            value_buffer = []
            links_buffer = []
            for article in value:
                if article['url'] not in links_buffer:
                    value_buffer.append(article)
                    links_buffer.append(article['url'])
            value = value_buffer
            warn(f'{orange}Duplicates found in {key}! reduced from {starting_len} to {len(value)}{reset}')

        processed = len(value)
        for i, article in tqdm(enumerate(value), total=len(value), desc=f'Processing {key} articles'):
            text = article['text']
            if not db.pass_article_filters(article, key):
                value[i] = None
                processed -= 1
                continue
            if summarizer.get_token_count(text) > 3500:
                text = summarizer.summarize(text, 3500/summarizer.get_token_count(text))
            article['uid'] = str(uuid.uuid4())
            article['source'] = key
            res = summarizer.summarize_and_tag_gpt3(text)
            if res is None or res == {}:
                res = {
                    'summary': '',
                    'tags': []
                }
            article['summary'] = res['summary']
            article['tags'] = ';'.join(res['tags'])
            value[i] = article

        # remove articles that did not pass the filters
        value = [article for article in value if article is not None]
        inserted = db.insert_many(value, 'articles')
        info(f'{green}{processed} Articles Processed and {inserted} Inserted from {key}{reset}')

    twentymin_df = db.get_by_publish_date(TWENTYMIN_NAME, datetime.now().strftime("%Y-%m-%d"))
    blick_df = db.get_by_publish_date(BLICK_NAME, datetime.now().strftime("%Y-%m-%d"))
    tagi_df = db.get_by_publish_date(TAGI_NAME, datetime.now().strftime("%Y-%m-%d"))
    zeit_df = db.get_by_publish_date(ZEIT_NAME, datetime.now().strftime("%Y-%m-%d"))

    print(f'{yellow}Articles from Today: "20min": {len(twentymin_df)}, "blick": {len(blick_df)}, "tagi": {len(tagi_df)}, "zeit": {len(zeit_df)}{reset}')
    if sum(len(df) for df in [twentymin_df, blick_df, tagi_df, zeit_df]) < 10:
        warn(f'{orange}No articles found for today!{reset}')
        exit(1) 

def get_articles(db: DBManager, uids: list):
    articles = []
    for uid in uids:
        article = db.get_by_uid('articles', uid)
        articles.append(article)
    return articles

def create_videos(db: DBManager, today_date, today_path, summarizer, tts):
    ########################## Create Videos ############################

    # get matches from today
    matches = db.get_by_WHERE(
        f'"date" = \'{today_date}\'',
        'matches',
    )

    # error if nothing found
    if len(matches) == 0:
        error(f'{orange}No matches found!{reset}')
        exit(1)
    
    matches = convert_matches(matches, db)

    for _, match in matches.iterrows():
        vm.process_match(db, match.to_dict(), summarizer, tts)

    warn(f"Found {len(matches)} matches")

    info(f'{green}Finished processing matches videos{reset}')

    # get all videos tags and create final video
    videos = []
    tags = []
    for _, match in matches.iterrows():
        file_name = str(match['uid'])
        if not os.path.isdir(f'{MEDIA_PATH}/{file_name}'):
            error(f'{orange}No folder found for {file_name}!{reset}')
            continue
        if os.path.exists(f'{MEDIA_PATH}{file_name}/video.mp4'):
            video = VideoFileClip(f'{MEDIA_PATH}{file_name}/video.mp4')
            videos.append(video)
            tags += list(match['tags'])

            

    # create final video
    info("Creating final video")
    vm.create_final_video(videos, f'{today_path}')
    # create titel for final video
    info("Creating final titel")
    title = vm.create_final_titel(tags, f'{today_path}', summarizer)
    # create final thumbnail
    info("Creating final thumbnail")
    vm.create_final_thumbnail(matches['images'].values, today_date, today_path, title)

    info(f'{green}Video created at {today_path}{reset}')

def upload(uploadManager: UploadManager, db: DBManager, today_path: str, today_date: str):
    # create dict for description links
    discription_links_dict = {
        "20min": "",
        "die Zeit": "",
        "Blick": "",
        "Tagesanzeiger": "",
    }

    relative_max_description_length = (5000-len(":".join(list(discription_links_dict.keys()))))/ len(discription_links_dict)

    # get matches from today
    matches = db.get_by_WHERE(
        f'"date" = \'{today_date}\'',
        'matches',
    )

    # error if nothing found
    if len(matches) == 0:
        error(f'{orange}No matches found!{reset}')
        exit(1)

    # convert stringed fields to actual objects
    matches = convert_matches(matches, db)

    # check if video exists
    if not os.path.exists(today_path):
        error(f'{orange}No video found at {today_path}{reset}')
        raise FileNotFoundError(errno.ENOENT, os.strerror(errno.ENOENT), today_path)

    # get all videos tags and create final video
    tags = []
    for _, match in matches.iterrows():
        if match is None:
            continue

        for article in match['articles']:
            if len(discription_links_dict[article['source']])+len(article['url']) < relative_max_description_length:
                discription_links_dict[article['source']] += "* "+article['url'] + '\n'

        tag = match['tags']
        tags += tag

    tags = list(set(tags))


    # create description
    decription = vm.DESCRIPTION.format(**discription_links_dict)


    # get tags and title
    date = datetime.now().strftime("%d.%m.%Y")
    title = TITEL_TEMPLATE.format(date)
    info('final video path: {}, final thumpnail path: {}'.format(today_path+"final.mp4", today_path+"final_thumbnail.png"))
    if len(tags) > 10:
        tags = tags[:10]
    video_id = uploadManager.upload(today_path+"final.mp4", title, decription, ['News', 'Schweiz', 'Deutschland', 'DailyOutput']+tags, 25)
    video_id = uploadManager.set_thumbnail(video_id, today_path+"final_thumbnail.png")

def main():
    uploadManager = UploadManager()
    summarizer = SummarizManager()
    tts = TTSManager()
    db = DBManager()
    db.create_update_tables()

    # create folder for today
    today = datetime.now().strftime('%Y-%m-%dT%H')
    today_date = datetime.now().strftime('%Y-%m-%d')
    if not os.path.exists("DailyOutput/"+today):
        os.makedirs("DailyOutput/"+today)

    today_path = "DailyOutput/"+today+"/"

    scrape_newspapers(db, summarizer)
    mm.cross_compare(today_path, db, summarizer)
    create_videos(db, today_date, today_path, summarizer, tts)
    upload(uploadManager, db, today_path, today_date)

if __name__ == '__main__':
    main()


