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
import concurrent.futures
import uuid
import multiprocessing as mp
from time import sleep
from tqdm import tqdm

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

    ############################### scrape ###############################
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
            if not db.pass_filters(article, key):
                value[i] = None
                continue
            if summarizer.get_token_count(text) > 3500:
                text = summarizer.summarize(text, 3500/summarizer.get_token_count(text))
            article['uid'] = str(uuid.uuid4())
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
        db.insert_many(value, key)

    twentymin_df = db.get_by_publish_date(TWENTYMIN_NAME, datetime.now().strftime("%Y-%m-%d"))
    blick_df = db.get_by_publish_date(BLICK_NAME, datetime.now().strftime("%Y-%m-%d"))
    tagi_df = db.get_by_publish_date(TAGI_NAME, datetime.now().strftime("%Y-%m-%d"))
    zeit_df = db.get_by_publish_date(ZEIT_NAME, datetime.now().strftime("%Y-%m-%d"))

    print(f'{yellow}Articles from Today: "20min": {len(twentymin_df)}, "blick": {len(blick_df)}, "tagi": {len(tagi_df)}, "zeit": {len(zeit_df)}{reset}')
    if sum(len(df) for df in [twentymin_df, blick_df, tagi_df, zeit_df]) < 10:
        warn(f'{orange}No articles found for today!{reset}')
        exit(1)
    
    ############################### compare ###############################
    # create folder for today
    today = datetime.now().strftime('%Y-%m-%dT%H')
    if not os.path.exists("ChatGPT/"+today):
        os.makedirs("ChatGPT/"+today)

    today_path = "ChatGPT/"+today+"/"

    # get matches
    matches = mm.cross_compare(today_path, db, summarizer)

    ########################## Create Videos ############################
    # create dict for description links
    discription_links_dict = {
        "20min": "",
        "dieZeit": "",
        "Blick": "",
        "Tagesanzeiger": "",
    }

    warn(f"Found {len(matches)} matches")
    # Parallel process matches using multithreading
    with concurrent.futures.ThreadPoolExecutor() as executor:
        # Pass the required arguments to the process_match function
        executor.map(lambda match: vm.process_match(today_path, match, summarizer, tts), matches)

    executor.shutdown(wait=True)
    info(f'{green}Finished processing matches videos{reset}')
    # remove duplicates
    tags = []
    videos = []
    info(f'{green}Create videos for matches{reset}')
    for match in os.listdir(today_path):
        # load videos
        try:
            # load discription links
            with open(f'{today_path}{match}/match.json') as f:
                match_data = json.load(f)
                for article in match_data['articles']:
                    discription_links_dict[article['newspaper']] += f'\t\t{article["article"]["url"]}\n'
            
            info(f'{green}create video for {match}{reset}')
            videos.append(vm.create_video(match_data['images'], match_data['title'], f'{today_path}{match_data["uid"]}/'))
            # load tags
            with open(f'{today_path}{match}/tags.json') as f:
                tags_match = json.load(f)
                for tag in tags_match:
                    if tag not in tags:
                        tags.append(tag)
        except Exception as e:
            error(f'{orange}Error loading video from {match}: {e}{reset}')

    if len(videos) == 0:
        error(f'{orange}No videos found!{reset}')
        exit(1)

    # create final video
    info("Creating final video")
    vm.create_final_video(videos, f'{today_path}')
    # create titel for final video
    info("Creating final titel")
    title = vm.create_final_titel(tags, f'{today_path}', summarizer)
    # create final thumbnail
    info("Creating final thumbnail")
    vm.create_final_thumbnail(tags, f'{today_path}', title)

    decription = vm.DESCRIPTION.format(**discription_links_dict)

    info(f'{green}Video created at {today_path}{reset}')

    ############################### upload ###############################
    # get tags and title
    date = datetime.now().strftime("%d.%m.%Y")
    title = TITEL_TEMPLATE.format(date)
    info('final video path: {}, final thumpnail path: {}'.format(today_path+"final.mp4", today_path+"final_thumbnail.png"))
    if len(tags) > 10:
        tags = tags[:10]
    video_id = uploadManager.upload(today_path+"final.mp4", title, decription, ['News', 'Schweiz', 'Deutschland', 'ChatGPT']+tags, 25)
    video_id = uploadManager.set_thumbnail(video_id, today_path+"final_thumbnail.png")


