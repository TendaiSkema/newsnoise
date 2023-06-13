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

BLICK_NAME = 'Blick'
TWENTYMIN_NAME = '20min'
TAGI_NAME = 'Tagesanzeiger'
ZEIT_NAME = 'die Zeit'

TITEL_TEMPLATE = "News Noise CH - {}"

# @GPT: This function 'scrape_process' runs a web scraping process for a specific website or source.
# It takes three arguments:
# - queue: a multiprocessing queue object that is used to store scraped data
# - name: a string denoting the name of the source being scraped
# - f: a function that performs the scraping. This function should take a DBManager instance as argument and return a list of scraped articles.
# 
# The function does the following:
# - It creates a new DBManager instance which is used to interact with the database.
# - It calls the scraping function 'f' passing the DBManager instance and gets a list of scraped articles.
# - It logs the number of articles scraped and adds them to the queue object for further processing.
# - If there's an error during the scraping process, it logs the error and the name of the source where the error occurred;
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

# @GPT: This function is responsible for scraping articles from various newspapers, 
# checking if the scraped articles pass certain filters, summarizing the articles and tagging them using a summarizer object, 
# then inserting the filtered, summarized and tagged articles into the database. 
# It initiates separate processes to scrape from each newspaper source. 
# It checks if all processes return a result, removes duplicate articles based on their urls and checks if an article passes filters defined in the database object. 
# If an article's text has more tokens than a predefined threshold, it gets summarized to the threshold limit. 
# Each article is then assigned a unique id and a source. 
# The articles are then summarized and tagged using the Summarizer object, and these processed articles are then inserted into the database. 
# It also fetches all the articles published on the current date from each newspaper source and prints out the count of articles found. 
# If the total number of articles found is less than 10, it warns the user and exits.;
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


        for i, article in tqdm(enumerate(value), total=len(value), desc=f'Processing {key} articles'):
            text = article['text']
            if not db.pass_article_filters(article, key):
                value[i] = None
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
        db.insert_many(value, 'articles')

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
    
    # convert string saved fields to lists
    matches['tags'] = matches['tags'].apply(lambda x: x.split(';')) 
    matches['articles'] = matches['articles'].apply(lambda x: x.split(';'))
    matches['images'] = matches['images'].apply(lambda x: x.split(';'))

    warn(f"Found {len(matches)} matches")
            
    # create videos for each match
    for _,match in matches.iterrows():
        # load articles
        articles = get_articles(db, match['articles'])
        match['articles'] = articles

        vm.process_match(db, match.to_dict(), summarizer, tts)

    info(f'{green}Finished processing matches videos{reset}')

    # get all videos tags and create final video
    videos = []
    tags = []
    for file in os.listdir(MEDIA_PATH):
        if not os.path.isdir(f'{MEDIA_PATH}/{file}'):
            continue
        if os.path.exists(f'{MEDIA_PATH}{file}/video.mp4'):
            video = VideoFileClip(f'{MEDIA_PATH}{file}/video.mp4')
            videos.append(video)
            match = db.get_by_uid('articles', file)
            if match is None:
                continue
            for article in match['articles']:
                art = db.get_by_uid(article, 'articles')
                if art is None:
                    continue

            tag = match['tags'].split(';')
            tags += tag

            

    # create final video
    info("Creating final video")
    vm.create_final_video(videos, f'{today_path}')
    # create titel for final video
    info("Creating final titel")
    title = vm.create_final_titel(tags, f'{today_path}', summarizer)
    # create final thumbnail
    info("Creating final thumbnail")
    vm.create_final_thumbnail(matches, today_date, today_path, title)

    info(f'{green}Video created at {today_path}{reset}')


# @GPT: Handles the upload of a video and its thumbnail to a platform using an UploadManager. 
# The function first formats the video's title using the current date. It logs the final paths of the video and thumbnail.
# If the provided tags exceed 10, it trims the list down to the first 10.
# The video is then uploaded with the given title, description, and tags (which include 'News', 'Schweiz', 'Deutschland', and 'ChatGPT' by default). 
# It also assigns a category number (25 in this case). 
# The video_id returned from the upload is then used to set the thumbnail for the video. 
# The function finally returns the video_id after the thumbnail is set;
def upload(uploadManager: UploadManager, db: DBManager, today_path: str):
    # create dict for description links
    discription_links_dict = {
        "20min": "",
        "die Zeit": "",
        "Blick": "",
        "Tagesanzeiger": "",
    }

    if not os.path.exists(today_path):
        error(f'{orange}No video found at {today_path}{reset}')
        raise FileNotFoundError(errno.ENOENT, os.strerror(errno.ENOENT), today_path)

    tags = []
    for file in os.listdir(today_path):
        if not os.path.isdir(f'{today_path}/{file}'):
            print(f'{today_path}/{file} is not a directory')
            continue

        match = db.get_by_uid('matches', file)
        if match is None:
            print(f'No match found for {file}')
            continue

        for article in match['articles']:
            art = db.get_by_uid('articles', article)
            if art is None:
                print(f'No article found for {article}')
                continue
            discription_links_dict[art['source']] += "\t"+art['url'] + '\n'

        tag = match['tags'].split(';')
        tags += tag

    decription = vm.DESCRIPTION.format(**discription_links_dict)


    # get tags and title
    date = datetime.now().strftime("%d.%m.%Y")
    title = TITEL_TEMPLATE.format(date)
    info('final video path: {}, final thumpnail path: {}'.format(today_path+"final.mp4", today_path+"final_thumbnail.png"))
    if len(tags) > 10:
        tags = tags[:10]
    video_id = uploadManager.upload(today_path+"final.mp4", title, decription, ['News', 'Schweiz', 'Deutschland', 'ChatGPT']+tags, 25)
    video_id = uploadManager.set_thumbnail(video_id, today_path+"final_thumbnail.png")


# @GPT: This is the main function which sets up various managers for uploading, text summarizing, text-to-speech (TTS) conversion, and database operations. 
# It then ensures a directory for today's date exists. Next, it scrapes newspapers and does a cross-comparison on them. 
# Based on the cross-comparison results, videos are created, and relevant tags and descriptions are generated. 
# Lastly, it uploads the created videos using the UploadManager. Here's a step-by-step breakdown:
# 1. Instantiate UploadManager, SummarizManager, TTSManager, and DBManager.
# 2. Create or update the database tables using DBManager.
# 3. Create a new directory for the current date if it doesn't exist already.
# 4. Scrape data from newspapers and summarize it.
# 5. Perform a cross-comparison on the scraped data.
# 6. Create videos based on the cross-comparison results, and generate corresponding tags and descriptions.
# 7. Upload the created videos along with their tags and descriptions using the UploadManager. ;
def main():
    uploadManager = UploadManager()
    summarizer = SummarizManager()
    tts = TTSManager()
    db = DBManager()
    db.create_update_tables()

    # create folder for today
    today = datetime.now().strftime('%Y-%m-%dT%H')
    today_date = datetime.now().strftime('%Y-%m-%d')
    if not os.path.exists("ChatGPT/"+today):
        os.makedirs("ChatGPT/"+today)

    today_path = "ChatGPT/"+today+"/"

    #scrape_newspapers(db, summarizer)
    #mm.cross_compare(today_path, db, summarizer)
    create_videos(db, today_date, today_path, summarizer, tts)
    upload(uploadManager, db, today_path)

if __name__ == '__main__':
    main()


